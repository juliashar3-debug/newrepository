'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = quarter => {const [year,q] = quarter.split('-Q'); return `${['','I','II','III','IV'][Number(q)]} квартал ${year}`;};
const state = {data:null,quarter:'',view:'events',search:''};
const titles = {events:'Мероприятия совета',report:'Квартальный отчет',plans:'Цели и задачи',help:'О журнале'};
function dateLabel(event) {
  const format = date => new Date(`${date}T12:00:00`).toLocaleDateString('ru-RU',{day:'numeric',month:'long'});
  return event.date ? `${format(event.date)}${event.date_end && event.date_end !== event.date ? ` — ${format(event.date_end)}` : ''}` : 'Дата уточняется';
}
function events() {
  const order = state.data.order[state.quarter] || [];
  return state.data.events.filter(e => e.quarter === state.quarter).sort((a,b) => {
    const ai=order.indexOf(a.id),bi=order.indexOf(b.id);
    return (ai<0?10000:ai)-(bi<0?10000:bi) || (a.date || '').localeCompare(b.date || '');
  });
}
function empty(text) {return `<div class="empty"><h2>${esc(text)}</h2><p>Материалы появятся после публикации владельцем журнала.</p></div>`;}
function render() {
  const selected=events();
  $('#page-title').textContent=titles[state.view]; $('#breadcrumb-current').textContent=titles[state.view];
  $('#nav-count').textContent=selected.length;
  $('#period-label').textContent=label(state.quarter);
  $$('.view').forEach(el => el.hidden=el.id!==`${state.view}-view`);
  $$('.nav-item').forEach(el => el.classList.toggle('active',el.dataset.view===state.view));
  if(state.view==='events') renderEvents(selected);
  if(state.view==='report') renderReport(selected);
  if(state.view==='plans') renderPlans();
  if(state.view==='help') $('#help-view').innerHTML='<section class="panel public-note"><h2>Мероприятия и отчеты СМС</h2><p>Здесь можно посмотреть опубликованные мероприятия, открыть фотографии и скачать готовые презентации и PDF.</p><p>Выберите квартал вверху страницы. Для подробностей нажмите «Открыть» на карточке.</p><p>Владелец ведет журнал и формирует отчеты в локальном приложении. Этот сайт показывает последнюю опубликованную версию. Изменения на компьютере владельца появятся здесь после новой публикации.</p></section>';
}
function renderEvents(selected) {
  const photos=selected.reduce((n,e)=>n+e.photos.length,0);
  const report=state.data.reports.find(r=>r.quarter===state.quarter);
  $('#stats').innerHTML=[['Мероприятий за квартал',selected.length],['Фотографий',photos],['Готовых форматов отчета',Object.keys(report?.files || {}).length]].map(([title,count])=>`<div class="stat"><div class="stat-top">${esc(title)}</div><div class="stat-value">${count}</div></div>`).join('');
  const shown=selected.filter(e=>`${e.name} ${e.organizer} ${e.description}`.toLocaleLowerCase('ru').includes(state.search));
  $('#event-grid').innerHTML=shown.length ? shown.map(e=>{
    const photo=e.photos.find(p=>p.group) || e.photos[0];
    return `<article class="event-card"><div class="card-image">${photo?`<img src="${esc(photo.url)}" alt="${esc(e.name)}" loading="lazy">`:'<div class="no-photo">Фотографии пока не опубликованы</div>'}<span class="photo-badge">${e.photos.length} фото</span></div><div class="card-body"><div class="card-date">${esc(dateLabel(e))}</div><h2>${esc(e.name)}</h2><p class="card-description">${esc(e.description)}</p><div class="card-counts"><div><strong>${e.total_attendance ?? '—'}</strong> в команде</div><div><strong>${e.sms_attendance ?? '—'}</strong> из СМС</div></div><div class="card-bottom"><span class="status green">В отчете</span><button class="open-card" data-event="${esc(e.id)}">Открыть →</button></div></div></article>`;
  }).join('') : empty(state.search?'Ничего не найдено':'За этот квартал пока нет опубликованных мероприятий');
}
function renderReport(selected) {
  const report=state.data.reports.find(r=>r.quarter===state.quarter);
  const ready=Boolean(report?.files.pdf || report?.files.pptx);
  $('#report-view').innerHTML=`<section class="panel"><p class="eyebrow">${esc(label(state.quarter))}</p><h2>${ready?'Отчет готов к скачиванию':'Отчет пока не опубликован'}</h2><p class="public-note">${ready?`Слайдов: ${report.slide_count ?? '—'} · Мероприятий в отчете: ${report.event_count ?? '—'}`:'Готовые файлы появятся после сборки и публикации владельцем.'}</p><div class="button-row">${Object.entries(report?.files || {}).map(([kind,url])=>`<a class="button ${kind==='pdf'?'primary':'secondary'}" href="${esc(url)}" download>Скачать ${kind.toUpperCase()}</a>`).join('')}</div><p class="download-note">Опубликованная версия. Правки локального журнала переносятся при следующей публикации.</p></section><section class="panel"><h2>Мероприятия квартала</h2><ol class="report-list">${selected.map(e=>`<li><button class="text-button" data-event="${esc(e.id)}">${esc(e.name)}</button></li>`).join('')}</ol></section>`;
}
function renderPlans() {
  const plan=state.data.plans.find(p=>p.report_quarter===state.quarter);
  $('#plans-view').innerHTML=plan?`<section class="panel"><p class="eyebrow">${plan.status==='proposed'?'ПРЕДЛОЖЕНИЯ':'ПЛАН'}</p><h2>На ${esc(label(plan.target_quarter))}</h2><p class="public-note">${plan.status==='proposed'?'Предложения для обсуждения; план пока не утвержден.':''}</p></section><div class="plan-grid">${plan.goals_and_tasks.map((p,i)=>`<section class="panel"><p class="eyebrow">ЦЕЛЬ ${i+1}</p><h2>${esc(p.goal)}</h2><p class="public-note">${esc(p.task)}</p></section>`).join('')}</div>`:empty('План пока не опубликован');
}
function openEvent(id) {
  const e=state.data.events.find(e=>e.id===id); if(!e)return;
  const photos=[...e.photos].sort((a,b)=>Number(b.group)-Number(a.group));
  $('#event-detail').innerHTML=`<div class="public-detail"><button class="icon-button public-close" id="close-detail" aria-label="Закрыть">✕</button><p class="eyebrow">${esc(label(e.quarter))}</p><h2 id="event-title">${esc(e.name)}</h2><p>${esc(dateLabel(e))}</p><p>${esc(e.description)}</p><dl><dt>Организатор</dt><dd>${esc(e.organizer || 'Уточняется')}</dd><dt>Всего в команде</dt><dd>${e.total_attendance ?? '—'}${e.total_type==='photo'?' · по фото':e.total_type==='calculated'?' · расчет':''}</dd><dt>Участников из СМС</dt><dd>${e.sms_attendance ?? '—'}${e.sms_type==='calculated'?' · расчет':''}</dd></dl>${e.effect?`<h3>Эффект мероприятия</h3><p>${esc(e.effect)}</p>`:''}<div class="public-gallery">${photos.map((p,i)=>`<a href="${esc(p.url)}" target="_blank" rel="noopener"><img src="${esc(p.url)}" alt="${esc(e.name)} — фото ${i+1}" loading="lazy"></a>`).join('')}</div></div>`;
  $('#close-detail').addEventListener('click',()=>$('#event-dialog').close());
  $('#event-dialog').showModal();
}
$$('.nav-item').forEach(button=>button.addEventListener('click',()=>{state.view=button.dataset.view;$('#sidebar').classList.remove('open');$('#menu-toggle').setAttribute('aria-expanded','false');render();}));
$('#menu-toggle').addEventListener('click',()=>{$('#sidebar').classList.toggle('open');$('#menu-toggle').setAttribute('aria-expanded',String($('#sidebar').classList.contains('open')));});
$('#quarter-select').addEventListener('change',e=>{state.quarter=e.target.value;render();});
$('#search').addEventListener('input',e=>{state.search=e.target.value.toLocaleLowerCase('ru');renderEvents(events());});
document.addEventListener('click',e=>{const button=e.target.closest('[data-event]');if(button)openEvent(button.dataset.event);});
(async()=>{
  try {
    const response=await fetch('./journal.json');if(!response.ok)throw new Error('Не удалось загрузить материалы.');
    state.data=await response.json();state.quarter=state.data.default_quarter;
    $('#quarter-select').innerHTML=[...state.data.quarters].sort().reverse().map(q=>`<option value="${esc(q)}">${esc(label(q))}</option>`).join('');
    $('#quarter-select').value=state.quarter;
    $('#publication-note').textContent=`Версия опубликована ${new Date(state.data.published_at).toLocaleString('ru-RU')}.`;
    render();
  }catch(error){$('#load-error').textContent=`${error.message} Попробуйте обновить страницу.`;$('#load-error').hidden=false;}
})();
