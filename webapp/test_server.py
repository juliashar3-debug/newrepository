import base64
from email.parser import Parser
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from server import Handler, Journal


class QuietHandler(Handler):
    def log_message(self,*args):
        pass


class InMemorySocket:
    """Exercise the actual HTTP handler without opening a listening socket."""
    def __init__(self,data):
        self.input=BytesIO(data)
        self.output=BytesIO()

    def makefile(self,*args):
        return self.input

    def sendall(self,data):
        self.output.write(data)


class JournalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=Journal(self.temp.name)
        self.server=SimpleNamespace(journal=self.journal)

    def tearDown(self):
        self.temp.cleanup()

    def request(self,path,body=None,headers=None):
        if isinstance(body,dict):
            body=json.dumps(body).encode()
            headers={'Content-Type':'application/json',**(headers or {})}
        headers={'Host':'127.0.0.1:8765',**(headers or {})}
        if body is not None:
            headers['Content-Length']=str(len(body))
        method='POST' if body is not None else 'GET'
        raw=f'{method} {path} HTTP/1.0\r\n'+''.join(f'{k}: {v}\r\n' for k,v in headers.items())+'\r\n'
        connection=InMemorySocket(raw.encode()+(body or b''))
        QuietHandler(connection,('127.0.0.1',1),self.server)
        head,data=connection.output.getvalue().split(b'\r\n\r\n',1)
        status_line,*lines=head.decode('latin-1').split('\r\n')
        return int(status_line.split()[1]),Parser().parsestr('\n'.join(lines)),data

    def create(self,**override):
        payload={'name':'Тестовый командный квиз','date':'2028-05-15','quarter':'2028-Q2',
                 'total_attendance':18,'sms_attendance':12,'organizer':'Совет молодых специалистов',
                 'description':'Встреча команды.'}
        payload.update(override)
        status,_,data=self.request('/api/events',payload)
        self.assertEqual(status,201,data)
        return json.loads(data)

    def test_initial_import_keeps_scope_and_sources(self):
        active=[e for e in self.journal.events() if e['include'] and e['quarter']=='2026-Q3']
        self.assertEqual(len(active),8)
        self.assertEqual(sum(bool(e['issues']) for e in active),3)
        self.assertTrue(all(any(p['group'] for p in e['photos']) for e in active))
        exported=self.journal.export('2026-Q3')
        night=next(e for e in exported['events'] if e['id']=='night_tula_run')
        self.assertIn('rounded',night['sms_attendance_source'])
        self.assertFalse(next(e for e in self.journal.events() if e['id']=='relay_autumn')['include'])

    def test_new_record_survives_restart_and_rejects_invalid_counts(self):
        event=self.create()
        reopened=Journal(self.temp.name)
        self.assertEqual(reopened.event(event['id'])['sms_attendance'],12)
        status,_,_=self.request('/api/events/'+event['id'],{'revision':event['revision'],'sms_attendance':19})
        self.assertEqual(status,400)
        self.assertEqual(reopened.event(event['id'])['sms_attendance'],12)

    def test_date_and_quarter_must_match(self):
        status,_,_=self.request('/api/events',{'name':'Октябрь','date':'2026-10-15','quarter':'2026-Q3'})
        self.assertEqual(status,400)
        status,_,_=self.request('/api/events',{'name':'Неверная дата','date':'2026-02-31','quarter':'2026-Q1'})
        self.assertEqual(status,400)

    def test_unknown_date_allowed_and_calculation_requires_source(self):
        self.create(date='',quarter='2028-Q2')
        status,_,_=self.request('/api/events',{'name':'Расчет','quarter':'2028-Q2','sms_attendance':5,'sms_type':'calculated'})
        self.assertEqual(status,400)

    def test_stale_revision_does_not_overwrite_changes(self):
        event=self.create()
        status,_,_=self.request('/api/events/'+event['id'],{'revision':event['revision'],'description':'Новый текст'})
        self.assertEqual(status,200)
        status,_,_=self.request('/api/events/'+event['id'],{'revision':event['revision'],'description':'Старый текст'})
        self.assertEqual(status,409)
        self.assertEqual(self.journal.event(event['id'])['description'],'Новый текст')

    def test_upload_group_selection_and_materials_export(self):
        event=self.create()
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQkAAAAASUVORK5CYII=')
        path=f"/api/events/{event['id']}/photos"
        headers={'Content-Type':'image/png','X-File-Name':'team.png'}
        status,_,data=self.request(path,png,headers)
        self.assertEqual(status,200,data)
        uploaded=json.loads(data)
        self.assertEqual(len(uploaded['photos']),1)
        self.assertTrue(uploaded['photos'][0]['group'])
        self.request(path,png,headers)
        self.assertEqual(len(self.journal.event(event['id'])['photos']),1)
        status,_,original=self.request(uploaded['photos'][0]['url'])
        self.assertEqual((status,original),(200,png))
        status,_,archive=self.request('/api/export.zip?quarter=2028-Q2')
        self.assertEqual(status,200)
        with zipfile.ZipFile(BytesIO(archive)) as package:
            exported=json.loads(package.read('events.json'))
            self.assertEqual(exported['events'][0]['sms_attendance'],12)
            photo=exported['events'][0]['photos'][0]
            self.assertEqual(package.read(photo['repository_path']),png)

    def test_archive_is_reversible_and_does_not_delete_photos(self):
        event=self.journal.event('dragon_boat_cup')
        fid=event['photos'][0]['id']
        self.request('/api/events/dragon_boat_cup/archive',{'archived':True})
        self.assertTrue(self.journal.event('dragon_boat_cup')['archived'])
        self.assertNotIn('dragon_boat_cup',[e['id'] for e in self.journal.export('2026-Q3')['events']])
        self.assertEqual(self.request('/media/'+fid)[0],200)
        self.request('/api/events/dragon_boat_cup/archive',{'archived':False})
        self.assertFalse(self.journal.event('dragon_boat_cup')['archived'])

    def test_cross_site_host_and_non_image_upload_rejected(self):
        event=self.create()
        self.assertEqual(self.request('/api/events',{'name':'x','quarter':'2028-Q2'},{'Origin':'https://example.org'})[0],403)
        self.assertEqual(self.request('/api/events',headers={'Host':'example.org'})[0],403)
        self.assertEqual(self.request('/api/events/'+event['id']+'/photos',b'<script>alert(1)</script>',{'Content-Type':'image/png'})[0],400)
        self.assertEqual(self.request('/%2e%2e/server.py')[0],404)

    def test_ready_pdf_and_html_are_downloadable(self):
        status,headers,body=self.request('/api/report?quarter=2026-Q3&format=pdf')
        self.assertEqual(status,200)
        self.assertTrue(body.startswith(b'%PDF'))
        status,headers,body=self.request('/')
        self.assertEqual(status,200)
        self.assertIn('text/html',headers['Content-Type'])
        self.assertIn('Журнал мероприятий'.encode(),body)


if __name__=='__main__':
    unittest.main()
