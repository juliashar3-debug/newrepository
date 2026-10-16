"""Build the full GitHub-backed website and a public fallback snapshot."""
import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webapp'))
from online_store import REPORTS, load_online
from PIL import Image, ImageOps
from server import Journal


def build(output):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty; existing files are preserved.')
    output.mkdir(parents=True, exist_ok=True)
    for folder in ['photos', 'reports']:
        (output / folder).mkdir()
    for name in ['public.js', 'public.css', 'online.js', 'online.css']:
        shutil.copy2(ROOT / 'webapp/public' / name, output / name)
    shutil.copy2(ROOT / 'webapp/static/style.css', output / 'style.css')
    shutil.copy2(ROOT / 'webapp/static/app.js', output / 'app.js')
    html = (ROOT / 'webapp/static/index.html').read_text(encoding='utf-8')
    html = html.replace('href="/', 'href="./').replace('src="/', 'src="./')
    html = html.replace('<script src="./app.js', '<link rel="stylesheet" href="online.css?v=20261016-2">\n  <script src="online.js?v=20261016-2" defer></script>\n  <script src="./app.js')
    html = html.replace('20261016-1', '20261016-2').replace('Личная локальная версия', 'Онлайн-журнал · GitHub')
    html = html.replace('<span class="avatar"', '<button id="owner-connect" class="button secondary">Подключить владельца</button><span class="avatar"')
    html = html.replace('</body>', (ROOT / 'webapp/public/owner-dialog.html').read_text(encoding='utf-8') + '\n</body>')
    (output / 'index.html').write_text(html, encoding='utf-8')
    (output / '.nojekyll').touch()
    with tempfile.TemporaryDirectory(prefix='sms-public-') as temporary:
        journal = Journal(Path(temporary) / 'data')
        online = load_online(journal)
        (output / 'online-snapshot.json').write_text(json.dumps({'journal': online, 'reports': json.loads(REPORTS.read_text(encoding='utf-8'))}, ensure_ascii=False), encoding='utf-8')
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
