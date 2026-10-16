"""Build a read-only website from repository materials for GitHub Pages."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webapp'))
from server import Journal  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402


def build(output):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty; existing files are preserved.')
    output.mkdir(parents=True, exist_ok=True)
    for folder in ['photos', 'reports']:
        (output / folder).mkdir()
    for name in ['index.html', 'public.js', 'public.css']:
        shutil.copy2(ROOT / 'webapp/public' / name, output / name)
    shutil.copy2(ROOT / 'webapp/static/style.css', output / 'style.css')
    (output / '.nojekyll').touch()
    with tempfile.TemporaryDirectory(prefix='sms-public-') as temporary:
        journal = Journal(Path(temporary) / 'data')
        meta = journal.metadata()
        with journal.db() as connection:
            files = {row['id']: Path(row['path']) for row in connection.execute('SELECT id,path FROM files')}
        events = []
        fields = ['id', 'name', 'date', 'date_end', 'quarter', 'organizer', 'description',
                  'effect', 'sms_attendance', 'total_attendance', 'sms_type', 'total_type']
        for event in journal.events():
            if event['archived'] or not event['include']:
                continue
            public = {key: event.get(key) for key in fields}
            public['photos'] = []
            for photo in event['photos']:
                source = files[photo['id']]
                name = f"photos/{photo['id']}.jpg"
                with Image.open(source) as original:
                    prepared = ImageOps.exif_transpose(original).convert('RGB')
                    prepared.thumbnail((1600, 1600))
                    prepared.save(output / name, 'JPEG', quality=85, optimize=True)
                public['photos'].append({'url': name, 'group': photo['group']})
            events.append(public)
        reports = []
        for report in meta['reports']:
            public = {key: report.get(key) for key in ['quarter', 'slide_count', 'event_count', 'updated_date']}
            public['files'] = {}
            for kind in ['pptx', 'pdf']:
                if report['available'][kind]:
                    path = journal.report_path(report['quarter'], kind)
                    name = f"reports/{report['quarter']}.{kind}"
                    shutil.copy2(path, output / name)
                    public['files'][kind] = name
            reports.append(public)
        data = {'events': events, 'reports': reports, 'plans': meta['plans'], 'order': meta['order'],
                'default_quarter': meta['default_quarter'], 'quarters': meta['quarters'],
                'published_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        (output / 'journal.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    data = build(args.output)
    print(f"Published snapshot: {len(data['events'])} events; output: {args.output}")
