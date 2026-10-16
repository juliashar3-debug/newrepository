"""Publication includes selected materials and works below a repository URL prefix."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_public_site import build


class PublicSiteTests(unittest.TestCase):
    def test_public_snapshot_has_photos_reports_and_no_private_journal_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'site'
            data = build(output)
            self.assertEqual(len(data['events']), 8)
            self.assertNotIn('relay_autumn', {event['id'] for event in data['events']})
            for event in data['events']:
                self.assertFalse({'notes', 'source', 'formula', 'revision', 'website_notes'} & event.keys())
                for photo in event['photos']:
                    self.assertFalse(photo['url'].startswith('/'))
                    self.assertTrue((output / photo['url']).is_file())
            report = next(report for report in data['reports'] if report['quarter'] == '2026-Q3')
            for kind, url in report['files'].items():
                self.assertTrue((output / url).is_file())
                self.assertIn(kind, ['pptx', 'pdf'])
            self.assertEqual(json.loads((output / 'journal.json').read_text()), data)
            self.assertFalse(list(output.rglob('*.sqlite3')))
            html = (output / 'index.html').read_text()
            self.assertNotIn('href="/', html)
            self.assertNotIn('src="/', html)
            self.assertNotIn('/api/', (output / 'public.js').read_text())

    def test_export_does_not_overwrite_existing_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'owner.txt'
            marker.write_text('Keep me')
            with self.assertRaises(ValueError):
                build(temporary)
            self.assertEqual(marker.read_text(), 'Keep me')
