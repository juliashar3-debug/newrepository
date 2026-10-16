"""The hosted journal feeds the same validated report snapshot as the local app."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from online_store import JOURNAL, load_online, repository_file
from server import Journal


class OnlineStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.journal = Journal(Path(self.temporary.name) / 'data')
        self.data = json.loads(JOURNAL.read_text(encoding='utf-8'))

    def test_edits_photos_membership_and_next_quarter_feed_builder(self):
        event = next(e for e in self.data['events'] if e['id'] == 'night_tula_run')
        event.update(name='Новое название', quarter='2026-Q4', date='2026-10-20', revision=2)
        event['photos'] = list(reversed(event['photos']))[:2]
        load_online(self.journal, self.data)
        q3 = self.journal.report_snapshot('2026-Q3')
        q4 = self.journal.report_snapshot('2026-Q4')
        self.assertEqual(len(q3['events']), 7)
        self.assertEqual(len(q4['events']), 1)
        self.assertEqual(q4['events'][0]['name'], 'Новое название')
        self.assertEqual(len(q4['files']), 2)
        self.assertEqual(q4['plan']['target_quarter'], '2027-Q1')
        self.assertFalse(q4['cover_photos'])
        self.assertEqual(q4['template'], q3['template'])

    def test_bad_journal_rolls_back_without_losing_previous_cards(self):
        before = self.journal.events()
        self.data['events'][1]['sms_attendance'] = 1000000
        with self.assertRaises(ValueError):
            load_online(self.journal, self.data)
        self.assertEqual(before, self.journal.events())

    def test_duplicate_ids_and_path_escape_rejected(self):
        self.data['events'].append(copy.deepcopy(self.data['events'][0]))
        with self.assertRaises(ValueError):
            load_online(self.journal, self.data)
        for path in ['presentations/../AGENTS.md', '/etc/passwd', 'https://example.org/image.jpg']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                repository_file(path)

    def test_failed_pdf_keeps_existing_manifest_and_report_pair(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / 'tools/build_online_report.py'
        spec = importlib.util.spec_from_file_location('online_build', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = module.REPORTS.read_bytes()
        original_read = Path.read_text
        def read_text(path, *args, **kwargs):
            if path.name == 'report-request.json':
                return '{"quarter":"2026-Q3","request_id":"test-failure"}'
            return original_read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read_text), patch.object(module.report_builder, 'build', side_effect=ValueError('PDF failed')), self.assertRaises(ValueError):
            module.build_request()
        self.assertEqual(manifest, module.REPORTS.read_bytes())
