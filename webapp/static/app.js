'use strict';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const paths = {
  grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  report:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h6',
  flag:'M4 22V3 M4 3c6-4 10 4 16 0v12c-6 4-10-4-16 0',
  help:'M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3 M12 17h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  spark:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',
  calendar:'M8 2v4 M16 2v4 M3 10h18 M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2',
  chevron:'m8 10 4 4 4-4', plus:'M12 5v14 M5 12h14', close:'m6 6 12 12 M18 6 6 18',
  search:'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  check:'m5 12 4 4L19 6', download:'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',
  upload:'M12 16V4 m-5 5 5-5 5 5 M4 16v5h16v-5',
  users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8 M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75',
  image:'M3 3h18v18H3z m0 13 5-5 4 4 3-3 6 6 M8 7h.01',
  arrow:'M5 12h14 m-5-5 5 5-5 5', clock:'M12 8v4l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  menu:'M4 6h16 M4 12h16 M4 18h16', archive:'M3 3h18v5H3z M5 8v13h14V8 M10 12h4',
  refresh:'M20 7v5h-5 M4 17v-5h5 M6.1 6a8 8 0 0 1 13 2l.9 4 M4 12l.9 4a8 8 0 0 0 13 2',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.report}"/></svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roman = ['','I','II','III','IV'];
const titles = {events:'Мероприятия совета',report:'Квартальный отчет',plans:'Цели и задачи',help:'Все начинается с карточки'};
const subtitles = {events:'Все события, фотографии и важные детали — в одном месте.',report:'Собранные материалы и готовая презентация за квартал.',plans:'Идеи, которые превращают прошедший опыт в следующие шаги.',help:'Добавляй материалы постепенно. Журнал поможет собрать их в отчет.'};
const state = {events:[],meta:null,quarter:'2026-Q3',view:'events',filter:'all',search:'',editing:null,pending:[],removed:[],mainPhoto:'',saving:false,changed:false};
let toastTimer;
const reportPolls = new Map();

function hydrateIcons(root = document) { $$('[data-icon]',root).forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }
function quarterLabel(value) { const [year,q] = value.split('-Q'); return `${roman[Number(q)] || q} квартал ${year}`; }
function dateLabel(event) {
  if (!event.date) return 'Дата не указана';
  const fmt = value => new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU',{day:'numeric',month:'long'});
  if (event.date_end && event.date_end !== event.date) return `${fmt(event.date)} — ${fmt(event.date_end)}`;
  return fmt(event.date);
}
function notify(message,error = false) { const el = $('#toast'); el.textContent = message; el.classList.toggle('error',error); el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true,5500); }
async function api(url,options = {}) {
  const response = await fetch(url,{...options,headers:{...(options.body && typeof options.body === 'string' ? {'Content-Type':'application/json'} : {}),...options.headers}});
  let result;
  try { result = await response.json(); } catch { throw new Error('Сервер не ответил. Проверьте, что журнал запущен.'); }
  if (!response.ok) throw new Error(result.error || 'Не удалось выполнить действие.');
  return result;
}
async function load() {
  const error = $('#load-error'); error.hidden = true;
  try {
    const [events,meta] = await Promise.all([api('/api/events'),api('/api/meta')]);
    state.events = events.events; state.meta = meta;
    if (!$('#quarter-select').dataset.loaded) state.quarter = meta.default_quarter;
    const quarters = [...new Set([...meta.quarters,state.quarter])].sort().reverse();
    $('#quarter-select').innerHTML = quarters.map(q => `<option value="${esc(q)}">${esc(quarterLabel(q))}</option>`).join('');
    $('#quarter-select').value = state.quarter; $('#quarter-select').dataset.loaded = '1';
    $('#connection').innerHTML = '<i></i>На этом компьютере';
    render();
    meta.reports.filter(report => report.job?.state === 'running').forEach(report => watchReport(report.quarter));
  } catch (e) {
    error.textContent = `${e.message} Обновите страницу после запуска сервера.`; error.hidden = false;
    $('#connection').textContent = 'Нет соединения';
    $('#event-grid').innerHTML = empty('Не удалось загрузить журнал','Сведения появятся после подключения к локальному серверу.');
  }
}
function selectedEvents(includeExcluded = false) { return state.events.filter(e => e.quarter === state.quarter && !e.archived && (includeExcluded || e.include)); }
function sorted(events) {
  const order = state.meta?.order?.[state.quarter] || [];
  return [...events].sort((a,b) => {
    const ai = order.indexOf(a.id), bi = order.indexOf(b.id);
    if (ai !== -1 || bi !== -1) return (ai === -1 ? 1000 : ai) - (bi === -1 ? 1000 : bi);
    return (a.date || '9999').localeCompare(b.date || '9999');
  });
}
function empty(title,body,add = false) { return `<div class="empty"><div class="empty-icon">${icon('calendar')}</div><h2>${esc(title)}</h2><p>${esc(body)}</p>${add ? `<button class="button primary" data-new>${icon('plus')}Добавить мероприятие</button>` : ''}</div>`; }
function render() {
  if (!state.meta) return;
  const events = selectedEvents();
  $('#nav-count').textContent = events.length;
  $('#page-title').textContent = titles[state.view]; $('#page-subtitle').textContent = subtitles[state.view];
  $('#breadcrumb-current').textContent = state.view === 'events' ? 'Мероприятия' : titles[state.view];
  $('#add-event').hidden = state.view !== 'events';
  const q = Number(state.quarter.slice(-1));
  $('#period-label').textContent = `${['','Январь — март','Апрель — июнь','Июль — сентябрь','Октябрь — декабрь'][q]} ${state.quarter.slice(0,4)}`;
  $$('.nav-item').forEach(el => el.classList.toggle('active',el.dataset.view === state.view));
  $$('.view').forEach(el => el.hidden = el.id !== `${state.view}-view`);
  renderReportPrompt();
  if (state.view === 'events') renderEvents();
  else if (state.view === 'report') renderReport();
  else if (state.view === 'plans') renderPlans();
  else renderHelp();
}
function reportUpdateButton(report) {
  const running = report?.job?.state === 'running';
  return `<button class="button primary" data-report-update ${running ? 'disabled aria-busy="true"' : ''}>${icon('refresh')}${running ? 'Обновляем…' : 'Обновить'}</button>`;
}
function renderReportPrompt() {
  const report = state.meta.reports.find(item => item.quarter === state.quarter);
  const prompt = $('#report-update-prompt');
  const running = report?.job?.state === 'running';
  prompt.hidden = state.view === 'report' || (!report?.changed && !running);
  prompt.innerHTML = `<div><strong>${running ? 'Обновляем презентацию и PDF' : 'Обновить презентацию и PDF?'}</strong><p>${running ? esc(report.job.message) : 'Мероприятия изменились после сборки отчета. Сохраненные правки готовы к переносу в оба файла.'}</p></div>${reportUpdateButton(report)}`;
}
async function updateReport() {
  const quarter = state.quarter;
  try {
    const status = await api('/api/report/rebuild',{method:'POST',body:JSON.stringify({quarter})});
    const report = state.meta.reports.find(item => item.quarter === quarter);
    if (report) report.job = status;
    state.view = 'report'; render(); watchReport(quarter);
  } catch (error) { notify(error.message,true); }
}
function watchReport(quarter) {
  if (reportPolls.has(quarter)) return;
  const tick = async () => {
    try {
      const status = await api(`/api/report/status?quarter=${encodeURIComponent(quarter)}`);
      const report = state.meta?.reports.find(item => item.quarter === quarter);
      if (report) report.job = status;
      if (status.state === 'running') {
        if (state.quarter === quarter) render();
        reportPolls.set(quarter,setTimeout(tick,1000));
      } else {
        reportPolls.delete(quarter);
        await load();
        notify(status.state === 'success' ? 'Презентация и PDF обновлены. Можно скачать новые файлы.' : status.message || 'Обновление прервано. Повторите сборку.',status.state !== 'success');
      }
    } catch (error) {
      reportPolls.delete(quarter);
      notify(`${error.message} Обновите страницу, чтобы проверить готовность отчета.`,true);
    }
  };
  reportPolls.set(quarter,setTimeout(tick,500));
}
function renderEvents() {
  const events = selectedEvents();
  const photos = events.reduce((n,e) => n + e.photos.length,0);
  const ready = events.filter(e => !e.issues.length).length;
  const cards = [
    ['Мероприятий за квартал',events.length,'grid','', 'в журнале'],
    ['Фотографий сохранено',photos,'image','','оригиналы'],
    ['Готовы к отчету',ready,'check','ready','карточек'],
    ['Нужно дополнить',events.length-ready,'clock','attention','карточек'],
  ];
  $('#stats').innerHTML = cards.map(([name,n,i,cl,hint]) => `<div class="stat ${cl}"><div class="stat-top">${name}<span class="stat-icon">${icon(i)}</span></div><div class="stat-value">${n}<small>${hint}</small></div></div>`).join('');
  $('#tab-all').textContent = events.length;
  $$('.tab').forEach(el => el.classList.toggle('active',el.dataset.filter === state.filter));
  let visible = state.events.filter(e => e.quarter === state.quarter);
  if (state.filter === 'archived') visible = visible.filter(e => e.archived);
  else if (state.filter === 'excluded') visible = visible.filter(e => !e.archived && !e.include);
  else visible = visible.filter(e => !e.archived && e.include && (state.filter === 'ready' ? !e.issues.length : state.filter === 'attention' ? e.issues.length : true));
  const search = state.search.toLocaleLowerCase('ru');
  visible = sorted(visible.filter(e => `${e.name} ${e.organizer} ${e.description}`.toLocaleLowerCase('ru').includes(search)));
  $('#event-grid').innerHTML = visible.length ? visible.map(eventCard).join('') : empty(state.search ? 'Ничего не найдено' : state.filter === 'all' ? 'Здесь начнется новый квартал' : 'Пока нет таких карточек',state.search ? 'Попробуйте другое название или очистите поиск.' : 'Добавьте мероприятие, описание и фотографии. Можно заполнять постепенно.',state.filter === 'all');
}
function eventCard(e) {
  const main = e.photos.find(p => p.group) || e.photos[0];
  const label = e.archived ? 'В архиве' : !e.include ? 'Не включено' : e.issues.length ? 'Нужно дополнить' : 'Готово к отчету';
  const status = e.archived || !e.include ? 'gray' : e.issues.length ? 'amber' : 'green';
  return `<article class="event-card"><div class="card-image">${main ? `<img src="${esc(main.thumbnail)}" alt="${esc(e.name)} — общее фото" loading="lazy">` : `<div class="no-photo">${icon('image')}Фотографии еще не добавлены</div>`}<span class="photo-badge">${icon('image')}${e.photos.length} фото</span></div><div class="card-body"><div class="card-date">${icon('calendar')}${esc(dateLabel(e))}</div><h2>${esc(e.name)}</h2><p class="card-description">${esc(e.description || 'Краткое описание можно добавить позже.')}</p><div class="card-counts"><div>${icon('users')}<strong>${e.total_attendance ?? '—'}</strong> в команде</div><div><strong>${e.sms_attendance ?? '—'}</strong> из СМС${e.sms_type === 'calculated' ? ' · расчет' : ''}</div></div><div class="card-bottom"><span class="status ${status}" ${e.issues.length ? `title="Уточнить: ${esc(e.issues.join(', '))}"` : ''}>${label}</span><button class="open-card" data-edit="${esc(e.id)}">Открыть${icon('arrow')}</button></div></div></article>`;
}
function renderReport() {
  const report = state.meta.reports.find(r => r.quarter === state.quarter);
  const events = sorted(selectedEvents());
  const missing = events.filter(e => e.issues.length);
  const fmt = type => `/api/report?quarter=${encodeURIComponent(state.quarter)}&format=${type}`;
  const running = report?.job?.state === 'running';
  const updated = report?.updated_at ? new Date(report.updated_at).toLocaleString('ru-RU') : report?.updated_date;
  $('#report-view').innerHTML = `<section class="panel report-hero" aria-busy="${running}"><div><p class="eyebrow">${esc(quarterLabel(state.quarter).toUpperCase())}</p><h2>${running ? 'Обновляем отчет' : report?.changed ? 'В отчете есть новые изменения' : report ? 'Отчет готов к скачиванию' : 'Материалы будущего отчета'}</h2><p>${report ? `${report.slide_count} слайдов · ${report.event_count} мероприятий в последней сборке.${updated ? ` Обновлено: ${esc(updated)}.` : ''}` : 'Добавляйте мероприятия и фотографии. Для первой сборки квартала подготовьте шаблон вместе с агентом.'}</p><div class="button-row">${report ? reportUpdateButton(report) : ''}${report?.available.pdf ? `<a class="button secondary" href="${fmt('pdf')}">${icon('report')}Скачать PDF</a>` : ''}${report?.available.pptx ? `<a class="button secondary" href="${fmt('pptx')}">${icon('download')}Скачать PPTX</a>` : ''}<a class="button secondary" href="/api/export.zip?quarter=${encodeURIComponent(state.quarter)}">${icon('download')}Материалы квартала · ZIP</a></div>${running ? `<p class="build-progress" role="status">${icon('refresh')}${esc(report.job.message)} Предыдущие файлы доступны до окончания обновления.</p>` : report?.changed ? '<p class="muted-note">Мероприятия изменены. Нажмите «Обновить», чтобы перенести сохраненные правки в презентацию и PDF.</p>' : report ? '<p class="muted-note">Презентация и PDF соответствуют сохраненным мероприятиям.</p>' : ''}${report?.job?.state === 'error' ? `<div class="banner error" role="alert">${esc(report.job.message)}</div>` : ''}</div><div class="report-icon">${icon('report')}</div></section>${report && !state.meta.report_builder?.ready ? `<div class="banner info">${esc(state.meta.report_builder?.message)} <a href="https://www.libreoffice.org/download/download-libreoffice/" target="_blank" rel="noopener">Скачать LibreOffice</a></div>` : ''}<section class="panel"><h2>Войдут в отчет</h2><p>${events.length} мероприятий · ${missing.length ? `${missing.length} карточки требуют уточнения` : 'основные поля заполнены'}</p>${events.length ? `<ol class="report-list">${events.map((e,i) => `<li><span class="order-number">${i+1}</span><span>${esc(e.name)}</span><span class="status ${e.issues.length ? 'amber' : 'green'}">${e.issues.length ? esc(e.issues.join(', ')) : 'Готово'}</span></li>`).join('')}</ol>` : '<p>Пока нет мероприятий, отмеченных для включения.</p>'}</section>`;
}
function renderPlans() {
  const plan = state.meta.plans.find(p => p.report_quarter === state.quarter);
  if (!plan) { $('#plans-view').innerHTML = empty('Предложения еще не подготовлены','План следующего квартала появится вместе с квартальной презентацией.'); return; }
  $('#plans-view').innerHTML = `<div class="banner info">Предложения на ${esc(quarterLabel(plan.target_quarter))}. План пока не утвержден.</div><div class="plan-grid">${plan.goals_and_tasks.map((p,i) => `<article class="panel plan-card"><span class="plan-number">0${i+1}</span><p class="eyebrow">ЦЕЛЬ</p><h2>${esc(p.goal)}</h2><div class="task"><p class="eyebrow">КОНКРЕТНАЯ ЗАДАЧА</p><p>${esc(p.task)}</p></div></article>`).join('')}</div>`;
}
function renderHelp() {
  $('#help-view').innerHTML = `<div class="help-grid"><section class="panel"><div class="help-number">ШАГ 01</div><h2>Расскажи о событии</h2><p>Укажи название, дату, организатора и коротко опиши участие команды. Неизвестные сведения можно оставить пустыми и дополнить позже.</p></section><section class="panel"><div class="help-number">ШАГ 02</div><h2>Добавь фотографии</h2><p>Загрузи снимки и выбери общее фото — для центра коллажа. Сохраняются оригиналы. Число одних и тех же людей на разных снимках не складываем.</p></section><section class="panel"><div class="help-number">ШАГ 03</div><h2>Обнови отчет</h2><p>После сохранения карточки журнал предложит обновить презентацию и PDF. Нажми «Обновить» и дождись завершения. Оба новых файла появятся в разделе «Квартальный отчет».</p></section></div><section class="panel"><h2>Что важно при заполнении</h2><p>Численность относится к команде ЦКБА. Для расчетных значений выбирай отметку «Расчетное число» и записывай формулу. При неизвестной дате выбери квартал вручную. Если дата указана, квартал определяется по ней.</p><p>Сборка сохраняет оформление отчета, общий снимок в центре и неизвестные числа прочерками. Для создания PDF нужен LibreOffice или Microsoft PowerPoint в Windows. Длинный текст продолжается на дополнительных слайдах.</p><p>Журнал и новые версии отчета хранятся на компьютере, где запущен сервер. Если редактировать карточки во время сборки, журнал предложит обновить отчет еще раз. Для передачи агенту используй выгрузку журнала или архив квартала.</p><p>Восстановить карточку из архива можно через фильтр «Архив». Удаление снимка из карточки не стирает исходный файл.</p></section>`;
}
function clearForm() {
  state.pending.forEach(p => URL.revokeObjectURL(p.url)); state.pending=[]; state.removed=[]; state.editing=null; state.mainPhoto=''; state.changed=false;
  $('#event-form').reset(); $('#form-error').hidden=true; $('#save-status').textContent='';
}
function openForm(id) {
  clearForm();
  const event = id ? state.events.find(e => e.id === id) : null;
  state.editing = event ? structuredClone(event) : null;
  const form = $('#event-form');
  const values = event || {include:true,total_type:'confirmed',sms_type:'confirmed'};
  for (const name of ['name','date','date_end','organizer','description','effect','total_attendance','sms_attendance','total_type','sms_type','formula','notes']) form.elements.namedItem(name).value = values[name] ?? '';
  form.elements.include.checked = values.include;
  const [year,quarter] = (event?.quarter || state.quarter).split('-Q');
  form.elements.year.value=year; form.elements.quarter_number.value=quarter;
  state.mainPhoto=event?.photos.find(p => p.group)?.id || event?.photos[0]?.id || '';
  $('#form-title').textContent=event ? 'Редактирование мероприятия' : 'Новое мероприятие';
  $('#archive-event').hidden=!event;
  $('#archive-event span:last-child').textContent=event?.archived ? 'Восстановить' : 'В архив';
  renderPhotos(); $('#event-dialog').showModal(); $('#sidebar').classList.remove('open');
  setTimeout(() => form.elements.name.focus(),50);
}
function closeForm(force=false) {
  if (state.saving) return;
  if (!force && state.changed && !window.confirm('Закрыть карточку без сохранения изменений?')) return;
  $('#event-dialog').close(); clearForm();
}
function renderPhotos() {
  const existing = (state.editing?.photos || []).filter(p => !state.removed.includes(p.id));
  const all=[...existing.map(p => ({key:p.id,url:p.thumbnail,name:p.name})),...state.pending.map(p => ({key:p.key,url:p.url,name:p.file.name}))];
  $('#photo-counter').textContent=all.length;
  $('#photo-list').innerHTML=all.map(p => `<div class="photo-item ${state.mainPhoto === p.key ? 'selected' : ''}"><img src="${esc(p.url)}" alt="${esc(p.name)}"><span class="photo-name">${esc(p.name)}</span><button type="button" class="photo-remove" data-remove="${esc(p.key)}" aria-label="Убрать ${esc(p.name)}">${icon('close')}</button><label><input type="radio" name="group_photo" value="${esc(p.key)}" ${state.mainPhoto === p.key ? 'checked' : ''}>${state.mainPhoto === p.key ? 'Общее фото · в центре коллажа' : 'Сделать общим фото'}</label></div>`).join('');
}
function addFiles(files) {
  if (state.saving) return;
  const errors=[];
  for (const file of files) {
    if (file.size > 20*1024*1024) { errors.push(`${file.name}: больше 20 МБ`); continue; }
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) { errors.push(`${file.name}: нужен JPG, PNG или WebP`); continue; }
    if ((state.editing?.photos.length || 0) - state.removed.length + state.pending.length >= 30) { errors.push('Можно сохранить до 30 фотографий в карточке'); break; }
    const key=`pending-${crypto.randomUUID()}`;
    state.pending.push({key,file,url:URL.createObjectURL(file)});
    if (!state.mainPhoto) state.mainPhoto=key;
    state.changed=true;
  }
  $('#photo-input').value=''; renderPhotos();
  if (errors.length) notify(errors.join('. '),true);
}
function removePhoto(key) {
  if (state.saving) return;
  const pending=state.pending.find(p => p.key === key);
  if (pending) { URL.revokeObjectURL(pending.url); state.pending=state.pending.filter(p => p.key !== key); }
  else if (state.editing && !state.removed.includes(key)) state.removed.push(key);
  if (state.mainPhoto === key) state.mainPhoto=state.editing?.photos.find(p => !state.removed.includes(p.id))?.id || state.pending[0]?.key || '';
  state.changed=true; renderPhotos();
}
async function saveForm(event) {
  event.preventDefault(); if (state.saving) return;
  const form=$('#event-form'), error=$('#form-error'); error.hidden=true;
  const value = name => form.elements.namedItem(name).value.trim();
  const payload = {};
  for (const name of ['name','date','date_end','organizer','description','effect','total_type','sms_type','formula','notes']) payload[name]=value(name);
  for (const name of ['total_attendance','sms_attendance']) payload[name]=value(name) === '' ? null : Number(value(name));
  payload.quarter=`${value('year')}-Q${value('quarter_number')}`; payload.include=form.elements.include.checked;
  if (state.editing) payload.revision=state.editing.revision;
  if (state.editing?.photos.some(p => p.id === state.mainPhoto) && !state.removed.includes(state.mainPhoto)) payload.group_photo_id=state.mainPhoto;
  state.saving=true; $('#save-event').disabled=true; $('#cancel-form').disabled=true; $('#close-form').disabled=true; $('#archive-event').disabled=true;
  const controls=$$('input,select,textarea,button',form);
  controls.forEach(control => control.disabled=true);
  try {
    $('#save-status').textContent='Сохраняем сведения…';
    state.editing=await api(state.editing ? `/api/events/${encodeURIComponent(state.editing.id)}` : '/api/events',{method:'POST',body:JSON.stringify(payload)});
    while (state.removed.length) {
      const id=state.removed[0];
      state.editing=await api(`/api/events/${encodeURIComponent(state.editing.id)}/photos/${encodeURIComponent(id)}/detach`,{method:'POST',body:JSON.stringify({revision:state.editing.revision})});
      state.removed.shift();
    }
    const total=state.pending.length; let done=0;
    while (state.pending.length) {
      const item=state.pending[0];
      $('#save-status').textContent=`Фото ${done+1} из ${total}…`;
      const result=await api(`/api/events/${encodeURIComponent(state.editing.id)}/photos`,{method:'POST',headers:{'Content-Type':item.file.type,'X-File-Name':encodeURIComponent(item.file.name)},body:item.file});
      const previous=new Set(state.editing.photos.map(p => p.id));
      const added=result.photos.find(p => !previous.has(p.id)) || result.photos.find(p => p.name === item.file.name);
      if (state.mainPhoto === item.key && added) state.mainPhoto=added.id;
      state.editing=result; state.pending.shift(); URL.revokeObjectURL(item.url); done++; renderPhotos();
    }
    if (state.mainPhoto && state.editing.photos.some(p => p.id === state.mainPhoto)) state.editing=await api(`/api/events/${encodeURIComponent(state.editing.id)}`,{method:'POST',body:JSON.stringify({revision:state.editing.revision,group_photo_id:state.mainPhoto})});
    state.quarter=state.editing.quarter;
    state.saving=false; closeForm(true); await load(); notify('Мероприятие сохранено. Материалы можно дополнить позже.');
  } catch (e) {
    error.textContent=`${e.message}${state.editing ? ' Уже сохраненные сведения и загруженные фото не потеряны.' : ''}`; error.hidden=false;
    renderPhotos();
  } finally {
    controls.forEach(control => control.disabled=false);
    state.saving=false; $('#save-event').disabled=false; $('#cancel-form').disabled=false; $('#close-form').disabled=false; $('#archive-event').disabled=false; $('#save-status').textContent='';
  }
}

hydrateIcons();
document.addEventListener('click',event => { if (event.target.closest('[data-report-update]')) updateReport(); });
$('#add-event').addEventListener('click',() => openForm());
$('#close-form').addEventListener('click',() => closeForm());
$('#cancel-form').addEventListener('click',() => closeForm());
$('#event-dialog').addEventListener('cancel',event => { event.preventDefault(); closeForm(); });
$('#event-form').addEventListener('input',() => state.changed=true);
$('#event-form').addEventListener('submit',saveForm);
$('#quarter-select').addEventListener('change',event => { state.quarter=event.target.value; state.filter='all'; render(); });
$('#search').addEventListener('input',event => { state.search=event.target.value; renderEvents(); });
$('#export-button').addEventListener('click',() => location.assign(`/api/export?quarter=${encodeURIComponent(state.quarter)}`));
$('#menu-toggle').addEventListener('click',() => $('#sidebar').classList.toggle('open'));
$$('.nav-item').forEach(el => el.addEventListener('click',() => { state.view=el.dataset.view; $('#sidebar').classList.remove('open'); render(); }));
$$('.tab').forEach(el => el.addEventListener('click',() => { state.filter=el.dataset.filter; renderEvents(); }));
$('#event-grid').addEventListener('click',event => { const edit=event.target.closest('[data-edit]'); if (edit) openForm(edit.dataset.edit); if (event.target.closest('[data-new]')) openForm(); });
$('#photo-input').addEventListener('change',event => addFiles([...event.target.files]));
const zone=$('#dropzone');
zone.addEventListener('dragover',event => { event.preventDefault(); zone.classList.add('dragover'); });
zone.addEventListener('dragleave',() => zone.classList.remove('dragover'));
zone.addEventListener('drop',event => { event.preventDefault(); zone.classList.remove('dragover'); addFiles([...event.dataTransfer.files]); });
$('#photo-list').addEventListener('change',event => { if (event.target.name === 'group_photo') { state.mainPhoto=event.target.value; state.changed=true; renderPhotos(); } });
$('#photo-list').addEventListener('click',event => { const el=event.target.closest('[data-remove]'); if (el) removePhoto(el.dataset.remove); });
$('#event-form').elements.date.addEventListener('change',event => {
  if (!event.target.value) return;
  const [year,month]=event.target.value.split('-');
  $('#event-form').elements.year.value=year; $('#event-form').elements.quarter_number.value=Math.floor((Number(month)-1)/3)+1;
});
$('#archive-event').addEventListener('click',async () => {
  if (!state.editing || state.saving) return;
  try {
    const archived=!state.editing.archived;
    await api(`/api/events/${encodeURIComponent(state.editing.id)}/archive`,{method:'POST',body:JSON.stringify({archived})});
    closeForm(true); await load(); notify(archived ? 'Карточка в архиве. Ее можно восстановить через фильтр «Архив».' : 'Карточка восстановлена.');
  } catch (e) { notify(e.message,true); }
});
window.addEventListener('beforeunload',event => { if (state.changed) { event.preventDefault(); event.returnValue=''; } });
load();
