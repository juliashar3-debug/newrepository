import base64
import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import server


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_root = server.ROOT
        server.ROOT = Path(self.tmp.name)
        (server.ROOT / 'presentations').mkdir()
        self.original = {'organization': 'СМС', 'report_order': {'2026-Q3': ['existing']}, 'events': [{'id': 'existing', 'name': 'Существующее', 'photos': [], 'attendance_rules': {'sms': 'N-2'}, 'unknown_field': {'keep': True}}]}
        (server.ROOT / 'presentations/events.json').write_text(json.dumps(self.original), encoding='utf-8')

    def tearDown(self):
        server.ROOT = self.original_root
        self.tmp.cleanup()

    def payload(self):
        return {'name': 'Командный квиз', 'date': '2026-10-15', 'date_end': '', 'reported_quarter': '2026-Q4', 'sms_attendance': 12, 'total_attendance': 18, 'sms_attendance_source': 'Список СМС', 'total_attendance_source': 'Организатор', 'included_in_current_report': True}

    def test_create_photo_and_preserve_original(self):
        data = self.payload()
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        data['uploads'] = [{'name': '../../Фото.png', 'data': base64.b64encode(image).decode()}]
        event = server.persist(data)
        saved = server.load()
        self.assertEqual(saved['events'][0], self.original['events'][0])
        self.assertEqual(saved['report_order'], self.original['report_order'])
        self.assertEqual((server.ROOT / event['photos'][0]['repository_path']).read_bytes(), image)
        self.assertIn('presentations/2026-Q4/photos/', event['photos'][0]['repository_path'])
        data['uploads'] = []
        data['name'] = 'Обновлённый квиз'
        updated = server.persist(data, event['id'])
        self.assertEqual(updated['photos'], event['photos'])
        self.assertEqual(len(server.load()['events']), 2)

    def test_reject_invalid_values_without_changes(self):
        invalid = [dict(reported_quarter='2026-Q3'), dict(sms_attendance=19), dict(total_attendance=-1), dict(sms_attendance_source=''), dict(date='2026-02-30'), dict(date_end='2026-10-14'), dict(uploads=[{'data': base64.b64encode(b'<svg/>').decode()}])]
        for patch in invalid:
            with self.subTest(patch=patch):
                data = self.payload() | patch
                with self.assertRaises(ValueError):
                    server.persist(data)
                self.assertEqual(server.load(), self.original)

    def test_unknown_numbers_and_preservation(self):
        data = self.payload() | {'sms_attendance': None, 'total_attendance': None, 'date': '', 'included_in_current_report': False}
        result = server.persist(data, 'existing')
        self.assertIsNone(result['sms_attendance'])
        self.assertIn('date', result['pending_fields'])
        self.assertEqual(result['unknown_field'], {'keep': True})
        self.assertEqual(result['attendance_rules'], {'sms': 'N-2'})

    def test_http_routes_and_cross_origin(self):
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{http.server_port}'
        try:
            for route in ['/', '/app.js', '/style.css', '/api/health', '/api/events']:
                with urlopen(base+route) as response:
                    self.assertEqual(response.status, 200)
            request = Request(base+'/api/events', data=json.dumps(self.payload()).encode(), headers={'Content-Type':'application/json'}, method='POST')
            with urlopen(request) as response:
                self.assertEqual(response.status, 201)
            request = Request(base+'/api/events', data=b'{}', headers={'Content-Type':'application/json','Origin':'https://outside.example'}, method='POST')
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
            with self.assertRaises(HTTPError) as error:
                urlopen(base+'/photos/../../event-journal/server.py')
            self.assertEqual(error.exception.code, 404)
        finally:
            http.shutdown()
            http.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
