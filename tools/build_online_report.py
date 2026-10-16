"""Build the requested quarter from the GitHub journal; publish both files together."""
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webapp'))
import report_builder
from online_store import REPORTS, load_online
from server import Journal


def build_request():
    request = json.loads((ROOT / 'presentations/report-request.json').read_text(encoding='utf-8'))
    quarter, request_id = request.get('quarter', ''), request.get('request_id', '')
    if not re.fullmatch(r'20\d{2}-Q[1-4]', quarter) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', request_id):
        raise ValueError('Некорректный запрос сборки.')
    with tempfile.TemporaryDirectory(prefix='sms-online-') as temporary:
        journal = Journal(Path(temporary) / 'journal')
        ledger = load_online(journal)
        snapshot = journal.report_snapshot(quarter)
        output = Path(temporary) / 'report'
        output.mkdir()
        result = report_builder.build(snapshot, output, print)
        reports = json.loads(REPORTS.read_text(encoding='utf-8'))
        previous = reports.get(quarter, {})
        report = {**result, 'updated_at': datetime.now(timezone.utc).isoformat(), 'request_id': request_id,
                  'revisions': {e['id']: e['revision'] for e in ledger['events']
                                if e['quarter'] == quarter and e['include'] and not e['archived']}}
        # Files become visible together in the workflow's single Git commit.
        for kind in ['pptx', 'pdf']:
            relative = previous.get(kind, f'presentations/{quarter}/SMS_{quarter}.{kind}')
            destination = (ROOT / relative).resolve()
            if not destination.is_relative_to(ROOT / 'presentations') or destination.suffix != '.' + kind:
                raise ValueError('Некорректный путь отчета.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output / ('report.' + kind), destination)
            report[kind] = relative
        reports[quarter] = report
        REPORTS.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Ready: {quarter}; {result["slide_count"]} slides; request {request_id}')


if __name__ == '__main__':
    build_request()
