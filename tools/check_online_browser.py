"""Offline browser integration checks: every GitHub request is intercepted.
Run after build_public_site.py; optional SMS_SITE and CHROMIUM environment paths.
"""
import os
import shutil
import base64
import io
import json
from pathlib import Path
from urllib.parse import urlparse, unquote
import zipfile
from playwright.sync_api import sync_playwright
from PIL import Image

root=Path(__file__).resolve().parents[1]
site=Path(os.environ.get('SMS_SITE', root/'site'))
ledger=json.loads((root/'presentations/online-journal.json').read_text())
reports=json.loads((root/'presentations/online-reports.json').read_text())
blobs={}; trees={}; commits={}; committed=[]
head='head-original'; number=0; conflict=False; request=None
errors=[]
photo=io.BytesIO();Image.new('RGB',(40,30),'blue').save(photo,'PNG');photo=photo.getvalue()

def route_handler(route):
    global ledger,reports,head,number,conflict,request
    url=urlparse(route.request.url);path=unquote(url.path)
    body=route.request.post_data_json if route.request.method in ['POST','PATCH'] else None
    def result(data,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(data))
    if url.hostname=='sms.test':
        name=path.removeprefix('/newrepository/site/') or 'index.html'
        file=site/name
        mime='text/html' if file.suffix=='.html' else 'application/javascript' if file.suffix=='.js' else 'text/css' if file.suffix=='.css' else 'application/json'
        if file.is_file():route.fulfill(body=file.read_bytes(),content_type=mime)
        else:route.fulfill(status=404)
        return
    if url.hostname=='raw.githubusercontent.com':
        if path.endswith('online-journal.json'):result(ledger)
        elif path.endswith('online-reports.json'):result(reports)
        else:route.fulfill(content_type='image/png',body=photo)
        return
    if url.hostname!='api.github.com':raise AssertionError('Unexpected network '+url.hostname)
    if path=='/user':result({'login':'someone-else' if 'wrong' in route.request.headers.get('authorization','') else 'juliashar3-debug'});return
    path=path.removeprefix('/repos/juliashar3-debug/newrepository')
    if path=='':result({'permissions':{'push':True}})
    elif path.startswith('/contents/'):
        value=ledger if path.endswith('online-journal.json') else reports
        result({'content':base64.b64encode(json.dumps(value).encode()).decode()})
    elif path=='/git/ref/heads/main':result({'object':{'sha':head}})
    elif path.startswith('/git/commits/') and not body:result({'tree':{'sha':'base-tree'}})
    elif path=='/git/blobs':
        number+=1;sha=f'blob-{number}';blobs[sha]=body['content'].encode() if body['encoding']=='utf-8' else base64.b64decode(body['content']);result({'sha':sha})
    elif path=='/git/trees':
        number+=1;sha=f'tree-{number}';trees[sha]=body['tree'];result({'sha':sha})
    elif path=='/git/commits':
        number+=1;sha=f'commit-{number}';commits[sha]=body;result({'sha':sha})
    elif path=='/git/refs/heads/main':
        assert body['force'] is False
        if conflict:result({'message':'Reference update failed'},422);return
        head=body['sha'];commit=commits[head];committed.append(commit)
        for item in trees[commit['tree']]:
            if item['path'].endswith('online-journal.json'):ledger=json.loads(blobs[item['sha']])
            if item['path'].endswith('report-request.json'):request=json.loads(blobs[item['sha']])
        result({'object':{'sha':head}})
    elif path.startswith('/actions/workflows/'):
        result({'workflow_runs':[{'status':'in_progress','html_url':'https://github.com/juliashar3-debug/newrepository/actions/runs/123'}]})
    else:raise AssertionError('Unexpected API '+path)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
    page.route('**/*',route_handler);page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
    page.goto('https://sms.test/newrepository/site/')
    page.locator('.event-card').first.wait_for()
    assert page.locator('.event-card').count()==8
    page.locator('[data-edit]').first.click();page.locator('#public-card').wait_for(state='visible');page.locator('#public-close').click()
    page.locator('#add-event').click();page.locator('[name=key]').fill('wrong-test-key');page.locator('#owner-form [type=submit]').click()
    page.locator('#owner-error').wait_for(state='visible');assert not committed
    page.locator('[name=key]').fill('owner-test-key');page.locator('#owner-form [type=submit]').click()
    page.locator('#event-dialog').wait_for(state='visible')
    page.locator('[name=name]').fill('Проверка полного онлайн-журнала')
    page.locator('[name=date]').fill('2026-10-20');page.locator('[name=date]').dispatch_event('change')
    page.locator('[name=organizer]').fill('СМС');page.locator('textarea[name=description]').fill('Тест сохранения текста и фото')
    page.locator('[name=total_attendance]').fill('4');page.locator('[name=sms_attendance]').fill('3')
    page.locator('#photo-input').set_input_files({'name':'группа.png','mimeType':'image/png','buffer':photo})
    page.locator('#save-event').click();page.locator('#event-dialog').wait_for(state='hidden')
    assert len(committed)==1
    event=ledger['events'][-1];eid=event['id'];assert event['quarter']=='2026-Q4' and event['photos'][0]['group']
    assert len(trees[committed[-1]['tree']])==2
    page.locator('[data-view=report]').click()
    assert page.locator('#update-report').inner_text()=='Сформировать PPTX и PDF'
    with page.expect_download() as d:page.locator('[data-online-zip]').click()
    archive=zipfile.ZipFile(d.value.path());assert len(archive.namelist())==2;assert archive.testzip() is None
    assert json.loads(archive.read('journal.json'))['events'][0]['name']==event['name']
    page.locator('#update-report').click()
    page.wait_for_function('document.querySelector("#update-report").disabled')
    assert request['quarter']=='2026-Q4'
    reports['2026-Q4']={'pdf':'presentations/2026-Q4/report.pdf','pptx':'presentations/2026-Q4/report.pptx','slide_count':4,'event_count':1,'revisions':{eid:1},'request_id':request['request_id']}
    page.wait_for_function('document.querySelector("#update-report").innerText.includes("Обновить")',timeout=20000)
    assert page.get_by_text('Скачать PDF',exact=True).is_visible()
    page.locator('[data-view=events]').click();page.locator(f'[data-edit="{eid}"]').click()
    page.locator('textarea[name=description]').fill('Обновлённое описание');page.locator('#save-event').click();page.locator('#event-dialog').wait_for(state='hidden')
    assert ledger['events'][-1]['revision']==2
    page.locator('#report-update-prompt').wait_for(state='visible')
    page.locator(f'[data-edit="{eid}"]').click();page.locator('#archive-event').click();page.locator('#event-dialog').wait_for(state='hidden')
    assert ledger['events'][-1]['archived']
    page.locator('[data-filter=archived]').click();page.locator(f'[data-edit="{eid}"]').click();page.locator('#archive-event').click()
    page.locator('#event-dialog').wait_for(state='hidden');assert not ledger['events'][-1]['archived']
    page.locator('[data-filter=all]').click();page.locator(f'[data-edit="{eid}"]').click()
    page.locator('textarea[name=description]').fill('Несохранённый конфликт');conflict=True
    page.locator('#save-event').click();page.locator('#form-error').wait_for(state='visible')
    assert 'другой вкладке' in page.locator('#form-error').inner_text()
    assert ledger['events'][-1]['description']=='Обновлённое описание'
    assert page.locator('textarea[name=description]').input_value()=='Несохранённый конфликт'
    assert page.evaluate('JSON.stringify(localStorage)+JSON.stringify(sessionStorage)')=='{}{}'
    page.locator('#cancel-form').click();page.locator('#owner-connect').click();assert not page.evaluate('smsOnline.isOwner()')
    page.locator('#quarter-select').select_option('2026-Q3');page.locator('[data-view=report]').click()
    assert not errors,errors
    browser.close()
print('PASS: guest viewing, wrong-owner rejection, login, atomic card+photo commit, ZIP, Q4 build/status, dirty prompt, archive/restore, concurrent-write protection, no token storage, logout; no browser errors.')
