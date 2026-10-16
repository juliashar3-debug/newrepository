#!/usr/bin/env python3
"""Local SMS event journal. Python 3.12+, no third-party dependencies."""
import argparse
import base64
import binascii
import copy
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import unquote, urlsplit
import uuid

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / 'static'
LOCK = threading.Lock()
MAX_BODY = 75 * 1024 * 1024
MAX_PHOTO = 8 * 1024 * 1024


def load():
    return json.loads((ROOT / 'presentations/events.json').read_text('utf-8'))


def atomic_save(data):
    target = ROOT / 'presentations/events.json'
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='.events-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def text(data, key, limit=5000):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'Некорректное поле: {key}')
    return value.strip()


def validate(data, existing=None):
    if not isinstance(data, dict):
        raise ValueError('Ожидается объект мероприятия')
    name = text(data, 'name', 250)
    if not name:
        raise ValueError('Укажите название мероприятия')
    day = text(data, 'date', 10)
    end = text(data, 'date_end', 10)
    quarter = text(data, 'reported_quarter', 7)
    if not re.fullmatch(r'20\d{2}-Q[1-4]', quarter):
        raise ValueError('Выберите отчётный квартал')
    if day:
        parsed = date.fromisoformat(day)
        actual = f'{parsed.year}-Q{(parsed.month-1)//3+1}'
        if quarter != actual:
            raise ValueError('Квартал должен соответствовать дате мероприятия')
    if end and (not day or date.fromisoformat(end) < date.fromisoformat(day)):
        raise ValueError('Дата окончания должна быть не раньше даты начала')
    result = copy.deepcopy(existing) if existing else {'id': 'event_' + uuid.uuid4().hex[:16]}
    result.update(name=name, date=day or None, date_end=end or None, reported_quarter=quarter)
    for field in ('description_draft', 'effect_draft', 'organizer', 'location', 'notes'):
        result[field] = text(data, field) or None
    for field in ('sms_attendance', 'total_attendance'):
        value = data.get(field)
        if value is not None and (type(value) is not int or not 0 <= value <= 10000000):
            raise ValueError('Численность должна быть целым неотрицательным числом')
        result[field] = value
        source = text(data, field + '_source', 2000)
        if value is not None and not source:
            raise ValueError('Укажите источник для каждого численного значения')
        prior_source = existing.get(field + '_source') if existing else None
        if isinstance(prior_source, dict) and source == json.dumps(prior_source, ensure_ascii=False, indent=2):
            result[field + '_source'] = prior_source
        elif source or not existing or value != existing.get(field):
            result[field + '_source'] = source or None
    if result['sms_attendance'] is not None and result['total_attendance'] is not None and result['sms_attendance'] > result['total_attendance']:
        raise ValueError('Число участников СМС не может превышать общий охват')
    if type(data.get('included_in_current_report')) is not bool:
        raise ValueError('Некорректный статус включения')
    result['included_in_current_report'] = data['included_in_current_report']
    result['inclusion_status'] = 'included_per_user' if data['included_in_current_report'] else 'draft'
    result['pending_fields'] = [k for k in ('date', 'organizer', 'sms_attendance', 'total_attendance') if result.get(k) is None]
    if not existing or day != existing.get('date'):
        result['event_date_confirmed'] = bool(day)
        result['date_source'] = {'type': 'journal form', 'value': day} if day else None
    result['updated_at'] = datetime.now(timezone.utc).isoformat()
    result.setdefault('created_at', result['updated_at'])
    if existing and isinstance(existing.get('location'), dict):
        try:
            if json.loads(result['location'] or 'null') == existing['location']:
                result['location'] = existing['location']
        except (ValueError, TypeError):
            pass
    uploads = data.get('uploads', [])
    if not isinstance(uploads, list) or len(uploads) > 6:
        raise ValueError('За один раз можно добавить до 6 фотографий')
    decoded = []
    for photo in uploads:
        if not isinstance(photo, dict):
            raise ValueError('Некорректное фото')
        encoded = photo.get('data', '')
        if not isinstance(encoded, str) or len(encoded) > 12 * 1024 * 1024:
            raise ValueError('Фото превышает 8 МБ')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('Не удалось прочитать фото')
        if not raw or len(raw) > MAX_PHOTO:
            raise ValueError('Фото должно быть не больше 8 МБ')
        if raw.startswith(b'\xff\xd8\xff'):
            ext = '.jpg'
        elif raw.startswith(b'\x89PNG\r\n\x1a\n'):
            ext = '.png'
        elif len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            ext = '.webp'
        else:
            raise ValueError('Поддерживаются фотографии JPEG, PNG и WebP')
        decoded.append((raw, ext, text(photo, 'name', 250)))
    result.setdefault('photos', [])
    return result, decoded


def persist(data, existing_id=None):
    with LOCK:
        journal = load()
        existing = next((e for e in journal['events'] if e['id'] == existing_id), None) if existing_id else None
        if existing_id and not existing:
            raise LookupError('Мероприятие не найдено')
        event, decoded = validate(data, existing)
        created = []
        try:
            for raw, ext, name in decoded:
                path = ROOT / 'presentations' / event['reported_quarter'] / 'photos' / event['id'] / (uuid.uuid4().hex + ext)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                created.append(path)
                event['photos'].append({'repository_path': path.relative_to(ROOT).as_posix(), 'original_name': name, 'source': 'journal upload'})
            if existing:
                journal['events'][journal['events'].index(existing)] = event
            else:
                journal['events'].append(event)
            atomic_save(journal)
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return event


class Handler(BaseHTTPRequestHandler):
    server_version = 'SMSJournal/1.0'

    def reply(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        route = unquote(urlsplit(self.path).path)
        if route == '/api/health':
            return self.reply(200, {'status': 'ok'})
        if route in ('/api/events', '/api/export'):
            with LOCK:
                return self.reply(200, load())
        if route.startswith('/photos/'):
            rel = route[len('/photos/'):]
            path = (ROOT / rel).resolve()
            if not path.is_relative_to(ROOT / 'presentations') or path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
                return self.reply(404, {'error': 'Файл не найден'})
        else:
            path = (STATIC / ('index.html' if route == '/' else route.lstrip('/'))).resolve()
            if not path.is_relative_to(STATIC):
                return self.reply(404, {'error': 'Файл не найден'})
        if not path.is_file():
            return self.reply(404, {'error': 'Файл не найден'})
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(path)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def mutate(self):
        # Browser writes must come from the same origin. Service is local by default.
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.reply(403, {'error': 'Источник запроса не разрешён'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'Ожидается JSON'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {'error': 'Слишком большой запрос'})
            data = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            if self.command == 'POST' and path == '/api/events':
                return self.reply(201, persist(data))
            if self.command == 'PUT' and re.fullmatch('/api/events/[a-zA-Z0-9_-]+', path):
                return self.reply(200, persist(data, path.rsplit('/', 1)[1]))
            return self.reply(404, {'error': 'Маршрут не найден'})
        except (ValueError, TypeError) as error:
            return self.reply(400, {'error': str(error)})
        except LookupError as error:
            return self.reply(404, {'error': str(error)})
        except OSError:
            return self.reply(500, {'error': 'Не удалось сохранить данные. Проверьте доступ к папке репозитория.'})

    do_POST = mutate
    do_PUT = mutate


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Журнал СМС: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
