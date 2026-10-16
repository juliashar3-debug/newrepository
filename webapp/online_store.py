"""Repository-backed journal for disposable publishing/report jobs, never local .data."""
import copy
import hashlib
import json
import mimetypes
import re
from pathlib import Path

from server import ROOT, now

JOURNAL = ROOT / 'presentations/online-journal.json'
REPORTS = ROOT / 'presentations/online-reports.json'


def repository_file(relative, suffixes=None):
    if not isinstance(relative, str) or not relative.startswith('presentations/'):
        raise ValueError('Материал должен находиться в presentations/.')
    path = (ROOT / relative).resolve()
    if not path.is_relative_to((ROOT / 'presentations').resolve()) or not path.is_file():
        raise ValueError('Материал не найден: ' + relative)
    if suffixes and path.suffix.lower() not in suffixes:
        raise ValueError('Неверный формат материала.')
    return path


def load_online(journal, data=None):
    """Replace only a disposable Journal with the validated online snapshot."""
    data = copy.deepcopy(data if data is not None else json.loads(JOURNAL.read_text(encoding='utf-8')))
    if data.get('schema_version') != 1 or not isinstance(data.get('events'), list):
        raise ValueError('Неизвестный формат онлайн-журнала.')
    seen = set()
    with journal.db() as conn:
        original = {row['id']: json.loads(row['document']) for row in conn.execute('SELECT * FROM events')}
        conn.execute('DELETE FROM events')
        for event in data['events']:
            eid = event.get('id', '')
            revision = event.get('revision')
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', eid) or eid in seen:
                raise ValueError('Некорректный или повторный ID мероприятия.')
            if type(revision) is not int or revision < 1:
                raise ValueError('Некорректная версия карточки.')
            seen.add(eid)
            photos = event.get('photos', [])
            if not isinstance(photos, list) or len(photos) > 30:
                raise ValueError('Допустимо до 30 фотографий.')
            photo_ids = set()
            for photo in photos:
                fid = photo.get('id', '')
                if not re.fullmatch(r'[a-f0-9]{24}', fid) or fid in photo_ids:
                    raise ValueError('Некорректный ID фотографии.')
                photo_ids.add(fid)
                path = repository_file(photo['repository_path'], {'.jpg', '.jpeg', '.png', '.webp'})
                old = conn.execute('SELECT path FROM files WHERE id=?', (fid,)).fetchone()
                if old and Path(old['path']) != path:
                    raise ValueError('ID фотографии ссылается на другой файл.')
                conn.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)',
                             (fid, str(photo['name']), str(path), mimetypes.guess_type(path.name)[0],
                              hashlib.sha256(path.read_bytes()).hexdigest(), now()))
            clean = journal.validate(event, {'id': eid, 'photos': photos, 'source': original.get(eid, {}).get('source', {})})
            conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                         (eid, json.dumps(clean, ensure_ascii=False), revision, 0, bool(event.get('archived')), now()))
        settings = json.loads(conn.execute("SELECT value FROM settings WHERE key='journal'").fetchone()[0])
        settings['report_order'] = data.get('order', {})
        settings['report_defaults']['report_period'] = data.get('default_quarter', '2026-Q3')
        # Preserve template metadata, while exposing reports generated online.
        manifest = json.loads(REPORTS.read_text(encoding='utf-8')) if REPORTS.exists() else {}
        for quarter, report in manifest.items():
            for kind in ['pptx', 'pdf']:
                repository_file(report[kind], {'.' + kind})
            settings['reports'][quarter] = {**settings['reports'].get(quarter, {}), **report}
        journal.setting(conn, 'journal', settings)
        if data.get('plans'):
            journal.setting(conn, 'plans', {'plans': data['plans']})
    return data
