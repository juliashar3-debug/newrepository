#!/usr/bin/env python3
"""Single-owner local event journal with optional installed report generation tools."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import shutil
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4
import zipfile
from contextlib import contextmanager

import report_builder

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / 'static'
MAX_UPLOAD = 20 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def quarter_for(value):
    dt = date.fromisoformat(value)
    return f'{dt.year}-Q{(dt.month - 1) // 3 + 1}'


def inspect_image(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', '.png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp', '.webp'
    raise ValueError('Загрузите фотографию в формате JPG, PNG или WebP.')


class Journal:
    def __init__(self, directory):
        self.report_lock = threading.Lock()
        self.jobs_lock = threading.Lock()
        self.report_jobs = {}
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        for folder in ['uploads', 'thumbnails', 'exports', 'reports']:
            (self.directory / folder).mkdir(exist_ok=True)
        self.path = self.directory / 'journal.sqlite3'
        with self.db() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    dirty INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    path TEXT NOT NULL, content_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
            ''')
            if not conn.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
                self.seed(conn)
            if not conn.execute("SELECT 1 FROM settings WHERE key='report_baselines'").fetchone():
                journal = json.loads(conn.execute("SELECT value FROM settings WHERE key='journal'").fetchone()[0])
                rows = conn.execute('SELECT * FROM events').fetchall()
                baselines = {}
                for quarter in journal.get('reports', {}):
                    baselines[quarter] = self.signatures(rows, quarter)
                    # A database from the previous site may already contain unbuilt edits.
                    for row in rows:
                        doc = json.loads(row['document'])
                        if row['dirty'] and doc['quarter'] == quarter:
                            baselines[quarter][doc['id']] = 'not-yet-built'
                self.setting(conn, 'report_baselines', baselines)
            self.relocate_files(conn)

    def relocate_files(self, conn):
        # A downloaded update may live in a different folder. Keep copied .data
        # backups usable after the previous checkout has been removed.
        for row in conn.execute('SELECT id,path FROM files').fetchall():
            old = Path(row['path'])
            uploaded = self.directory / 'uploads' / (row['id'] + old.suffix)
            target = uploaded if uploaded.is_file() else None
            if target is None and 'presentations' in old.parts:
                relative = old.parts[old.parts.index('presentations'):]
                original = ROOT.joinpath(*relative).resolve()
                if original.is_relative_to(ROOT) and original.is_file():
                    target = original
            if target is not None and target != old:
                conn.execute('UPDATE files SET path=? WHERE id=?', (str(target), row['id']))

    @staticmethod
    def setting(conn, key, value):
        conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                     (key, json.dumps(value, ensure_ascii=False)))

    @staticmethod
    def signatures(rows, quarter):
        result = {}
        for row in rows:
            doc = json.loads(row['document'])
            if doc['quarter'] != quarter or row['archived'] or not doc['include']:
                continue
            material = {key: value for key, value in doc.items() if key != 'source'}
            result[doc['id']] = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return result

    def report_status(self, quarter):
        with self.jobs_lock:
            return dict(self.report_jobs.get(quarter, {'state': 'idle', 'message': ''}))

    def report_snapshot(self, quarter):
        if not re.fullmatch(r'\d{4}-Q[1-4]', quarter):
            raise ValueError('Неверный квартал.')
        with self.db() as conn:
            conn.execute('BEGIN')
            settings = {row['key']: json.loads(row['value']) for row in conn.execute('SELECT * FROM settings')}
            journal = settings['journal']
            report = journal.get('reports', {}).get(quarter)
            if not report:
                raise ValueError('Для этого квартала сначала нужен оформленный шаблон отчета. Сейчас обновление доступно для III квартала 2026 года.')
            template = (ROOT / report['pptx']).resolve()
            if not template.is_relative_to(ROOT) or not template.is_file():
                raise ValueError('Шаблон презентации не найден. Скачайте репозиторий полностью.')
            rows = conn.execute('SELECT * FROM events').fetchall()
            fingerprints = self.signatures(rows, quarter)
            events = []
            for row in rows:
                doc = json.loads(row['document'])
                if doc['id'] in fingerprints:
                    doc['revision'] = row['revision']
                    doc['dirty'] = bool(row['dirty'])
                    events.append(doc)
            order = journal.get('report_order', {}).get(quarter, [])
            events.sort(key=lambda event: (order.index(event['id']) if event['id'] in order else len(order),
                                           event['date'] or '9999', event['id']))
            files = {}
            for event in events:
                for photo in event['photos']:
                    row = conn.execute('SELECT * FROM files WHERE id=?', (photo['id'],)).fetchone()
                    if not row or not Path(row['path']).is_file():
                        raise ValueError('Не найдена фотография «' + photo['name'] + '». Скачайте все материалы или загрузите снимок заново.')
                    path = Path(row['path'])
                    files[photo['id']] = {**dict(row), 'repository_path': str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else None}
        return {'quarter': quarter, 'template': str(template), 'events': events,
                'files': files, 'fingerprints': fingerprints}

    def rebuild_report(self, quarter):
        if not self.report_lock.acquire(blocking=False):
            current = self.report_status(quarter)
            if current['state'] == 'running':
                return current
            raise RuntimeError('Уже обновляется другой отчет. Дождитесь окончания сборки.')
        try:
            snapshot = self.report_snapshot(quarter)
            ready = report_builder.capabilities()
            if not ready['ready']:
                raise ValueError(ready['message'])
            with self.jobs_lock:
                self.report_jobs[quarter] = {'state': 'running', 'message': 'Подготавливаем отчет…'}
            worker = threading.Thread(target=self._build_report, args=(snapshot,), daemon=True)
            worker.start()
            return self.report_status(quarter)
        except Exception:
            self.report_lock.release()
            raise

    def _build_report(self, snapshot):
        quarter = snapshot['quarter']
        directory = self.directory / 'reports' / quarter / uuid4().hex
        def stage(message):
            with self.jobs_lock:
                self.report_jobs[quarter] = {'state': 'running', 'message': message}
        try:
            built = report_builder.build(snapshot, directory, stage)
            # Publish a single pointer to the completed pair; failed builds never replace downloads.
            with self.db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                settings = {row['key']: json.loads(row['value']) for row in conn.execute('SELECT * FROM settings')}
                generated = settings.get('generated_reports', {})
                generated[quarter] = {**built, 'pdf': str((directory / 'report.pdf').relative_to(self.directory)),
                                      'pptx': str((directory / 'report.pptx').relative_to(self.directory)),
                                      'updated_at': now(), 'updated_date': datetime.now().astimezone().date().isoformat()}
                baselines = settings.get('report_baselines', {})
                baselines[quarter] = snapshot['fingerprints']
                self.setting(conn, 'generated_reports', generated)
                self.setting(conn, 'report_baselines', baselines)
            with self.jobs_lock:
                self.report_jobs[quarter] = {'state': 'success', 'message': 'Презентация и PDF обновлены.'}
        except Exception as exc:
            shutil.rmtree(directory, ignore_errors=True)
            message = str(exc) if isinstance(exc, (report_builder.BuildError, ValueError)) else 'Не удалось собрать отчет. Предыдущие файлы сохранены; повторите обновление.'
            with self.jobs_lock:
                self.report_jobs[quarter] = {'state': 'error', 'message': message}
        finally:
            self.report_lock.release()

    def report_path(self, quarter, kind):
        if kind not in ['pdf', 'pptx']:
            raise ValueError('Неизвестный формат отчета.')
        with self.db() as conn:
            settings = {row['key']: json.loads(row['value']) for row in conn.execute('SELECT * FROM settings')}
        generated = settings.get('generated_reports', {}).get(quarter)
        base = self.directory if generated else ROOT
        report = generated or settings['journal'].get('reports', {}).get(quarter, {})
        relative = report.get(kind)
        if not relative:
            raise KeyError('Для этого квартала еще нет готового отчета.')
        target = (base / relative).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise KeyError('Файл отчета недоступен.')
        return target

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def seed(self, conn):
        journal = json.loads((ROOT / 'presentations/events.json').read_text())
        plan = json.loads((ROOT / 'presentations/plans.json').read_text())
        for source in journal['events']:
            photos = source.get('photos', [])
            if source['id'] == 'hero_race':
                photos = [{'repository_path': item['repository_path'],
                           'collage_position': 'center' if item['name'].endswith('-3.jpeg') else '',
                           'description': 'Фотография «Гонки героев»'}
                          for item in source.get('photo_repository_manifest', [])]
            saved = []
            for photo in photos:
                rel = photo.get('repository_path')
                if not rel:
                    continue
                path = (ROOT / rel).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file():
                    continue
                fid = hashlib.sha256(rel.encode()).hexdigest()[:24]
                content_type = mimetypes.guess_type(path.name)[0] or 'image/jpeg'
                conn.execute('INSERT OR IGNORE INTO files VALUES (?,?,?,?,?,?)',
                             (fid, path.name, str(path), content_type,
                              hashlib.sha256(path.read_bytes()).hexdigest(), now()))
                saved.append({'id': fid, 'name': path.name,
                              'description': photo.get('description', ''),
                              'group': photo.get('collage_position') == 'center'})
            count_source = str(source.get('attendance_source', ''))
            sms_source = source.get('sms_attendance_source')
            visible = source.get('visible_people_count')
            total = source.get('total_attendance')
            total_type = 'confirmed'
            if total is None and visible is not None:
                total, total_type = visible, 'photo'
            elif source.get('total_attendance_source'):
                total_type = 'calculated'
            elif 'Visual count' in count_source:
                total_type = 'photo'
            sms_type = 'confirmed'
            if isinstance(sms_source, dict):
                sms_type = sms_source.get('type') or ('calculated' if sms_source.get('formula') else 'confirmed')
                if sms_type not in ['confirmed','calculated']:
                    sms_type = 'confirmed'
            formula = source.get('attendance_rules', {})
            document = {
                'id': source['id'], 'name': source['name'],
                'date': source.get('date') or '', 'date_end': source.get('date_end') or '',
                'quarter': source.get('reported_quarter', ''),
                'organizer': source.get('organizer') or '',
                'description': source.get('description_draft') or '',
                'effect': source.get('effect_draft') or '',
                'sms_attendance': source.get('sms_attendance'),
                'total_attendance': total, 'sms_type': sms_type, 'total_type': total_type,
                'formula': '; '.join(f'{k}: {v}' for k,v in formula.items() if k in ['total','sms']) or
                           (sms_source.get('formula', '') if isinstance(sms_source,dict) else ''),
                'notes': source.get('website_notes', ('Нужно уточнить дату участия команды в ночном старте. В программе ночные 5 км — 22 августа, дневные 5 и 10 км — 23 августа 2026 года.'
                          if source['id'] == 'evocom_5_10km' else '') or
                         ('Подтверждено содействие в организации; полный состав организаторов не установлен.'
                          if source['id'] == 'museum_quiz_2026_09_17' else '')),
                'include': source.get('inclusion_status') != 'excluded_by_user',
                'photos': saved, 'source': source,
            }
            if saved and not any(p['group'] for p in saved):
                saved[0]['group'] = True
            conn.execute('INSERT INTO events VALUES (?,?,1,0,0,?)',
                         (document['id'], json.dumps(document, ensure_ascii=False), now()))
        for key, value in [('journal', journal), ('plans', plan), ('initialized', True)]:
            conn.execute('INSERT INTO settings VALUES (?,?)', (key,json.dumps(value,ensure_ascii=False)))

    def decorate(self, row):
        event = json.loads(row['document'])
        event.pop('source', None)
        event.update(revision=row['revision'], dirty=bool(row['dirty']),
                     archived=bool(row['archived']), updated_at=row['updated_at'])
        issues = []
        for key, label in [('date','дата'),('organizer','организатор'),
                           ('description','описание')]:
            if not event.get(key):
                issues.append(label)
        for key, label in [('sms_attendance','участники из СМС'),
                           ('total_attendance','численность команды')]:
            if event.get(key) is None:
                issues.append(label)
        if not event['photos']:
            issues.append('фотографии')
        if event['id'] == 'evocom_5_10km' and event.get('notes'):
            issues.append('дата ночного старта')
        event['issues'] = issues
        for photo in event['photos']:
            photo['url'] = '/media/' + photo['id']
            photo['thumbnail'] = photo['url'] + '?thumbnail=1'
        return event

    def events(self):
        with self.db() as conn:
            return [self.decorate(row) for row in conn.execute('SELECT * FROM events')]

    def event(self, event_id):
        with self.db() as conn:
            row = conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
            if not row:
                raise KeyError('Мероприятие не найдено.')
            return self.decorate(row)

    def validate(self, payload, existing=None):
        document = dict(existing or {})
        for key, limit in [('name',250),('organizer',1000),('description',6000),
                           ('effect',6000),('formula',1000),('notes',6000),
                           ('date',10),('date_end',10),('quarter',7)]:
            value = payload.get(key, document.get(key,''))
            if not isinstance(value,str) or len(value)>limit:
                raise ValueError('Проверьте поле: ' + key)
            document[key] = value.strip()
        if not document['name']:
            raise ValueError('Укажите название мероприятия.')
        if document['date']:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',document['date']):
                    raise ValueError()
                expected = quarter_for(document['date'])
            except ValueError:
                raise ValueError('Проверьте дату начала мероприятия.')
            if document['quarter'] and document['quarter'] != expected:
                raise ValueError('Дата мероприятия не соответствует выбранному кварталу.')
            document['quarter'] = expected
        if not re.fullmatch(r'\d{4}-Q[1-4]',document['quarter']):
            raise ValueError('Выберите отчетный квартал.')
        if document['date_end']:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',document['date_end']):
                    raise ValueError()
                date.fromisoformat(document['date_end'])
            except ValueError:
                raise ValueError('Проверьте дату окончания мероприятия.')
            if not document['date'] or document['date_end'] < document['date']:
                raise ValueError('Дата окончания должна быть не раньше даты начала.')
        for key in ['sms_attendance','total_attendance']:
            value = payload.get(key,document.get(key))
            if value in ['',None]:
                value = None
            if value is not None and (type(value) is not int or not 0 <= value <= 1000000):
                raise ValueError('Количество участников должно быть целым неотрицательным числом.')
            document[key] = value
        if (document['sms_attendance'] is not None and document['total_attendance'] is not None
                and document['sms_attendance'] > document['total_attendance']):
            raise ValueError('Участников из СМС не может быть больше общего числа в команде.')
        for key in ['sms_type','total_type']:
            value = payload.get(key,document.get(key,'confirmed'))
            if value not in ['confirmed','photo','calculated'] or (key=='sms_type' and value=='photo'):
                raise ValueError('Укажите источник численности.')
            document[key]=value
        if ('calculated' in [document['sms_type'],document['total_type']]
                and any(document.get(k) is not None and document[t]=='calculated'
                        for k,t in [('sms_attendance','sms_type'),('total_attendance','total_type')])
                and not document['formula']):
            raise ValueError('Для расчетной численности укажите формулу или основание расчета.')
        document['include'] = bool(payload.get('include',document.get('include',True)))
        if 'group_photo_id' in payload:
            photo_id = payload['group_photo_id']
            if photo_id and photo_id not in [p['id'] for p in document.get('photos',[])]:
                raise ValueError('Выберите общее фото из фотографий мероприятия.')
            for photo in document.get('photos',[]):
                photo['group'] = photo['id'] == photo_id
        return document

    def save(self, event_id, payload):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone() if event_id else None
            if event_id and not row:
                raise KeyError('Мероприятие не найдено.')
            if row and payload.get('revision') != row['revision']:
                raise RuntimeError('Карточка изменена в другой вкладке. Закройте форму и откройте ее снова.')
            document = self.validate(payload,json.loads(row['document']) if row else {'photos':[]})
            event_id = event_id or uuid4().hex
            document['id'] = event_id
            if row:
                conn.execute('UPDATE events SET document=?,revision=revision+1,dirty=1,updated_at=? WHERE id=?',
                             (json.dumps(document,ensure_ascii=False),now(),event_id))
            else:
                conn.execute('INSERT INTO events VALUES (?,?,1,1,0,?)',
                             (event_id,json.dumps(document,ensure_ascii=False),now()))
        return self.event(event_id)

    def upload(self,event_id,data,filename):
        kind,ext = inspect_image(data)
        sha = hashlib.sha256(data).hexdigest()
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
            if not row:
                raise KeyError('Мероприятие не найдено.')
            document=json.loads(row['document'])
            for photo in document['photos']:
                existing=conn.execute('SELECT sha256 FROM files WHERE id=?',(photo['id'],)).fetchone()
                if existing and existing['sha256']==sha:
                    return self.decorate(row)
            if len(document['photos'])>=30:
                raise ValueError('В одной карточке можно сохранить до 30 фотографий.')
            fid=uuid4().hex
            path=self.directory/'uploads'/(fid+ext)
            path.write_bytes(data)
            filename=Path(filename.replace('\\','/')).name[:180] or ('photo'+ext)
            conn.execute('INSERT INTO files VALUES (?,?,?,?,?,?)',(fid,filename,str(path),kind,sha,now()))
            document['photos'].append({'id':fid,'name':filename,'description':'','group':not document['photos']})
            conn.execute('UPDATE events SET document=?,revision=revision+1,dirty=1,updated_at=? WHERE id=?',
                         (json.dumps(document,ensure_ascii=False),now(),event_id))
        return self.event(event_id)

    def archive(self,event_id,archived):
        with self.db() as conn:
            result=conn.execute('UPDATE events SET archived=?,revision=revision+1,dirty=1,updated_at=? WHERE id=?',
                                (int(archived),now(),event_id))
            if not result.rowcount:
                raise KeyError('Мероприятие не найдено.')
        return self.event(event_id)

    def detach(self,event_id,photo_id,revision):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
            if not row:
                raise KeyError('Мероприятие не найдено.')
            if revision!=row['revision']:
                raise RuntimeError('Карточка изменилась. Откройте ее заново.')
            document=json.loads(row['document'])
            document['photos']=[p for p in document['photos'] if p['id']!=photo_id]
            if document['photos'] and not any(p['group'] for p in document['photos']):
                document['photos'][0]['group']=True
            conn.execute('UPDATE events SET document=?,revision=revision+1,dirty=1,updated_at=? WHERE id=?',
                         (json.dumps(document,ensure_ascii=False),now(),event_id))
        return self.event(event_id)

    def metadata(self):
        with self.db() as conn:
            settings={r['key']:json.loads(r['value']) for r in conn.execute('SELECT * FROM settings')}
            rows=conn.execute('SELECT * FROM events').fetchall()
        journal=settings['journal']
        events=self.events()
        quarters=sorted({e['quarter'] for e in events}|{'2026-Q3','2026-Q4','2027-Q1'},reverse=True)
        reports=[]
        for quarter, report in journal.get('reports',{}).items():
            generated=settings.get('generated_reports',{}).get(quarter)
            current=generated or report
            base=self.directory if generated else ROOT
            available={kind:bool(current.get(kind) and (base/current[kind]).is_file()) for kind in ['pdf','pptx']}
            before=settings.get('report_baselines',{}).get(quarter,{})
            after=self.signatures(rows,quarter)
            changed=sum(before.get(key)!=after.get(key) for key in before.keys()|after.keys())
            reports.append({**{k:current.get(k) for k in ['slide_count','event_count','updated_date','updated_at']},
                            'pending':report.get('pending',[]), 'job':self.report_status(quarter),
                            'quarter':quarter,'available':available,
                            'changed':changed})
        return {'quarters':quarters,'default_quarter':journal.get('report_defaults',{}).get('report_period','2026-Q3'),
                'reports':reports,'plans':settings['plans']['plans'],
                'order':journal.get('report_order',{}),'local_only':True,
                'report_builder':report_builder.capabilities()}

    def export(self,quarter):
        with self.db() as conn:
            rows=conn.execute('SELECT * FROM events WHERE archived=0').fetchall()
            original=json.loads(conn.execute("SELECT value FROM settings WHERE key='journal'").fetchone()[0])
            baselines=json.loads(conn.execute("SELECT value FROM settings WHERE key='report_baselines'").fetchone()[0])
        current_signatures=self.signatures(rows,quarter)
        result={k:v for k,v in original.items() if k not in ['events','report_order']}
        result['events']=[]
        for row in rows:
            doc=json.loads(row['document'])
            if doc['quarter']!=quarter:
                continue
            event=dict(doc.get('source',{}))
            for old in ['report_content','report_slide']:
                event.pop(old,None)
            built=baselines.get(quarter,{}).get(doc['id'])==current_signatures.get(doc['id']) and doc['include']
            event.update(id=doc['id'],name=doc['name'],date=doc['date'] or None,
                         date_end=doc['date_end'] or None,reported_quarter=doc['quarter'],
                         organizer=doc['organizer'] or None,description_draft=doc['description'],
                         effect_draft=doc['effect'],sms_attendance=doc['sms_attendance'],
                         total_attendance=doc['total_attendance'],planned_for_report=doc['include'],
                         included_in_current_report=bool(built),
                         inclusion_status='included_in_draft' if built else 'planned; website changes pending report assembly' if doc['include'] else 'excluded_by_user',
                         website_notes=doc['notes'],
                         attendance_source={'type':doc['total_type'],'source':'website entry','formula':doc['formula']},
                         sms_attendance_source={'type':doc['sms_type'],'source':'website entry','formula':doc['formula']},
                         photos=[{'repository_path':f"photos/{doc['id']}/{p['id']}{Path(p['name']).suffix.lower()}",
                                  'original_filename':p['name'],'file_id':p['id'],
                                  'collage_position':'center' if p['group'] else '',
                                  'description':p.get('description','')} for p in doc['photos']])
            source=doc.get('source',{})
            if source:
                event['repository_sources']={key:value for key,value in source.items()
                    if key.endswith('_source') or key in ['visible_people_count','attendance_rules','date','date_end','sms_attendance','total_attendance']}
                baseline_total=source.get('total_attendance')
                if baseline_total is None:
                    baseline_total=source.get('visible_people_count')
                if doc['total_attendance']==baseline_total:
                    event['attendance_source']=source.get('attendance_source',source.get('visible_people_count_source'))
                if doc['sms_attendance']==source.get('sms_attendance'):
                    event['sms_attendance_source']=source.get('sms_attendance_source',source.get('attendance_source'))
            result['events'].append(event)
        ids={e['id'] for e in result['events'] if e['planned_for_report']}
        oldorder=original.get('report_order',{}).get(quarter,[])
        result['report_order']={quarter:[i for i in oldorder if i in ids]+[e['id'] for e in result['events'] if e['id'] in ids and e['id'] not in oldorder]}
        result['exported_at']=now()
        return result


class Handler(BaseHTTPRequestHandler):
    server_version='SMSJournal/1.0'

    @property
    def journal(self):
        return self.server.journal

    def send(self,status,data,kind='application/json; charset=utf-8',filename=None):
        if not isinstance(data,bytes):
            data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','SAMEORIGIN')
        self.send_header('Cache-Control','no-store')
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def file(self,path,kind=None,download=False,cache=True):
        self.send_response(200)
        self.send_header('Content-Type',kind or mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(path.stat().st_size))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','private, max-age=3600' if cache and not download else 'no-store')
        if download:
            self.send_header('Content-Disposition',f'attachment; filename="report{path.suffix}"')
        self.end_headers()
        with path.open('rb') as stream:
            while chunk:=stream.read(256*1024):
                self.wfile.write(chunk)

    def error(self,exc):
        status=404 if isinstance(exc,KeyError) else 409 if isinstance(exc,RuntimeError) else 400 if isinstance(exc,ValueError) else 500
        if status==500:
            self.log_error('%r',exc)
        self.send(status,{'error':str(exc) if status!=500 else 'Не удалось сохранить данные. Попробуйте еще раз.'})

    def body(self,limit=256*1024):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=limit:
            raise ValueError('Файл слишком большой. Максимум — 20 МБ.' if limit==MAX_UPLOAD else 'Некорректный размер запроса.')
        data=self.rfile.read(length)
        if len(data)!=length:
            raise ValueError('Передача данных прервалась. Повторите загрузку.')
        return data

    def do_GET(self):
        try:
            if urlsplit('http://'+self.headers.get('Host','')).hostname not in ['127.0.0.1','localhost']:
                return self.send(403,{'error':'Этот журнал доступен только на локальном адресе.'})
            path=urlsplit(self.path)
            query=parse_qs(path.query)
            quarter=query.get('quarter',['2026-Q3'])[0]
            if path.path=='/api/events':
                return self.send(200,{'events':self.journal.events()})
            if path.path=='/api/meta':
                return self.send(200,self.journal.metadata())
            if path.path=='/api/report/status':
                return self.send(200,self.journal.report_status(quarter))
            if path.path in ['/api/export','/api/export.zip']:
                if not re.fullmatch(r'\d{4}-Q[1-4]',quarter):
                    raise ValueError('Неверный квартал.')
                exported=self.journal.export(quarter)
                if path.path=='/api/export':
                    return self.send(200,json.dumps(exported,ensure_ascii=False,indent=2).encode(),filename=f'sms-{quarter}.json')
                with tempfile.NamedTemporaryFile(dir=self.journal.directory/'exports',suffix='.zip',delete=False) as stream:
                    temp=Path(stream.name)
                try:
                    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr('events.json',json.dumps(exported,ensure_ascii=False,indent=2))
                        with self.journal.db() as conn:
                            plans=conn.execute("SELECT value FROM settings WHERE key='plans'").fetchone()[0]
                            archive.writestr('plans.json',plans)
                            for event in exported['events']:
                                for photo in event['photos']:
                                    row=conn.execute('SELECT path FROM files WHERE id=?',(photo['file_id'],)).fetchone()
                                    if row and Path(row['path']).is_file():
                                        archive.write(row['path'],photo['repository_path'])
                    return self.file(temp,'application/zip',download=True)
                finally:
                    temp.unlink(missing_ok=True)
            if path.path=='/api/report':
                kind=query.get('format',['pdf'])[0]
                return self.file(self.journal.report_path(quarter,kind),download=True)
            if path.path.startswith('/media/'):
                fid=path.path.rsplit('/',1)[-1]
                with self.journal.db() as conn:
                    row=conn.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
                if not row or not Path(row['path']).is_file():
                    raise KeyError('Фотография не найдена.')
                target=Path(row['path']).resolve()
                if not (target.is_relative_to(ROOT) or target.is_relative_to(self.journal.directory)):
                    raise KeyError('Фотография недоступна.')
                if query.get('thumbnail')==['1']:
                    thumbnail=self.journal.directory/'thumbnails'/(fid+'.jpg')
                    if not thumbnail.exists():
                        try:
                            from PIL import Image,ImageOps
                            with Image.open(target) as source:
                                image=ImageOps.exif_transpose(source).convert('RGB')
                                image.thumbnail((1000,800))
                                temporary=thumbnail.with_suffix('.'+uuid4().hex+'.tmp')
                                image.save(temporary,format='JPEG',quality=85,optimize=True)
                                os.replace(temporary,thumbnail)
                        except (ImportError,OSError):
                            thumbnail=None
                    if thumbnail and thumbnail.exists():
                        return self.file(thumbnail,'image/jpeg')
                return self.file(target,row['content_type'])
            static=STATIC/('index.html' if path.path=='/' else unquote(path.path).lstrip('/'))
            static=static.resolve()
            if not static.is_relative_to(STATIC) or not static.is_file():
                raise KeyError('Страница не найдена.')
            return self.file(static,cache=False)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as exc:
            self.error(exc)

    def do_POST(self):
        try:
            if urlsplit('http://'+self.headers.get('Host','')).hostname not in ['127.0.0.1','localhost']:
                return self.send(403,{'error':'Этот журнал доступен только на локальном адресе.'})
            origin=self.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                return self.send(403,{'error':'Запрос отклонен: откройте журнал в своей вкладке.'})
            if self.headers.get('Sec-Fetch-Site')=='cross-site':
                return self.send(403,{'error':'Запрос с другого сайта отклонен.'})
            path=urlsplit(self.path).path
            upload=re.fullmatch(r'/api/events/([a-zA-Z0-9_-]+)/photos',path)
            if upload:
                result=self.journal.upload(upload[1],self.body(MAX_UPLOAD),unquote(self.headers.get('X-File-Name','photo.jpg')))
                return self.send(200,result)
            if self.headers.get_content_type()!='application/json':
                raise ValueError('Ожидается JSON.')
            payload=json.loads(self.body())
            if not isinstance(payload,dict):
                raise ValueError('Некорректные данные формы.')
            if path=='/api/report/rebuild':
                quarter=payload.get('quarter','')
                if not isinstance(quarter,str):
                    raise ValueError('Выберите отчетный квартал.')
                return self.send(202,self.journal.rebuild_report(quarter))
            if path=='/api/events':
                return self.send(201,self.journal.save(None,payload))
            edit=re.fullmatch(r'/api/events/([a-zA-Z0-9_-]+)',path)
            if edit:
                return self.send(200,self.journal.save(edit[1],payload))
            archive=re.fullmatch(r'/api/events/([a-zA-Z0-9_-]+)/archive',path)
            if archive:
                return self.send(200,self.journal.archive(archive[1],bool(payload.get('archived',True))))
            detach=re.fullmatch(r'/api/events/([a-zA-Z0-9_-]+)/photos/([a-zA-Z0-9_-]+)/detach',path)
            if detach:
                return self.send(200,self.journal.detach(detach[1],detach[2],payload.get('revision')))
            raise KeyError('Действие не найдено.')
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as exc:
            self.error(exc)


def main():
    parser=argparse.ArgumentParser(description='Личный журнал мероприятий СМС АО ЦКБА')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir',default=str(Path(__file__).resolve().parent/'.data'))
    parser.add_argument('--open',action='store_true',help='Открыть журнал в браузере после запуска')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.journal=Journal(args.data_dir)
    print(f'Журнал открыт локально: http://127.0.0.1:{args.port}',flush=True)
    print('Остановка: Ctrl+C. Данные сохраняются в',server.journal.directory,flush=True)
    if args.open:
        import webbrowser
        try:
            webbrowser.open(f'http://127.0.0.1:{args.port}')
        except webbrowser.Error:
            print('Откройте указанный выше адрес в браузере.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
