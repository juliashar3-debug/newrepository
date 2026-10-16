'use strict';
const $ = s => document.querySelector(s);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let journal = {events: []}, editing = null, selected = null, uploads = [], objectURLs = [], saving = false;
const editor = $('#editor'), form = $('#event-form'), details = $('#details');
const quarterOf = day => `${day.slice(0,4)}-Q${Math.floor((Number(day.slice(5,7))-1)/3)+1}`;
const today = new Date().toLocaleDateString('sv-SE');
const currentQuarter = quarterOf(today);
const quarterLabel = value => value === 'all' ? 'Все кварталы' : `${['I','II','III','IV'][Number(value.slice(-1))-1]} квартал ${value.slice(0,4)}`;
const sourceText = value => typeof value === 'string' ? value : value ? JSON.stringify(value, null, 2) : '';
const photos = event => (event.photos || []).filter(p => p.repository_path && /^presentations\//.test(p.repository_path));
const photoURL = photo => '/photos/' + photo.repository_path.split('/').map(encodeURIComponent).join('/');
const isPending = e => ['date','organizer','sms_attendance','total_attendance'].some(k => e[k] === null || e[k] === undefined || e[k] === '');
function dateLabel(e) { if (!e.date) return 'Дата уточняется'; return new Date(e.date + 'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'}); }
function populateQuarters() {
  const set = new Set(journal.events.map(e=>e.reported_quarter).filter(Boolean));
  for(let y=Number(today.slice(0,4))-1;y<=Number(today.slice(0,4))+2;y++) for(let q=1;q<=4;q++) set.add(`${y}-Q${q}`);
  const keys = [...set].sort().reverse();
  const previous = $('#quarter').value || 'all';
  $('#quarter').innerHTML = '<option value="all">Все кварталы</option>' + keys.map(k=>`<option value="${escapeHTML(k)}">${quarterLabel(k)}</option>`).join('');
  $('#quarter').value = previous;
  form.elements.reported_quarter.innerHTML = keys.map(k=>`<option value="${escapeHTML(k)}">${quarterLabel(k)}</option>`).join('');
}
function render() {
  const q = $('#quarter').value;
  const period = journal.events.filter(e => q === 'all' || e.reported_quarter === q);
  $('#count-events').textContent = period.length;
  $('#count-included').textContent = period.filter(e=>e.included_in_current_report).length;
  $('#count-pending').textContent = period.filter(isPending).length;
  $('#count-photos').textContent = period.reduce((n,e)=>n+photos(e).length,0);
  const query = $('#search').value.toLocaleLowerCase('ru').trim(), status = $('#status').value;
  const events = period.filter(e => (!query || [e.name,e.organizer,e.description_draft].join(' ').toLocaleLowerCase('ru').includes(query)) && (status === 'all' || status === 'included' && e.included_in_current_report || status === 'draft' && !e.included_in_current_report || status === 'pending' && isPending(e))).sort((a,b)=>(b.date || '').localeCompare(a.date || ''));
  $('#list-count').textContent = events.length;
  $('#events').innerHTML = events.length ? events.map(e=>{
    const images = photos(e), pending = isPending(e), included = e.included_in_current_report;
    const statusLabel = included ? 'В отчёте' : pending ? 'Требует уточнения' : 'Черновик';
    return `<button class="event-card" data-id="${escapeHTML(e.id)}" type="button"><div class="card-image ${images.length?'':'placeholder'}">${images.length?`<img src="${photoURL(images[0])}" alt="${escapeHTML(e.name)}" loading="lazy">`:'<span class="graphic">▧</span><span class="no-photo-label">Фотографии ещё не добавлены</span>'}${images.length?`<span class="photo-count">▧ ${images.length}</span>`:''}</div><div class="card-body"><div class="card-meta"><span class="date">${escapeHTML(dateLabel(e))}</span><span class="badge ${included?'included':pending?'pending':''}">${statusLabel}</span></div><h3>${escapeHTML(e.name)}</h3><p class="description">${escapeHTML(e.description_draft || 'Описание можно добавить позже.')}</p><div class="card-metrics"><span><b>${e.sms_attendance ?? '—'}</b> из СМС</span><span><b>${e.total_attendance ?? '—'}</b> общий охват</span></div></div><div class="card-footer"><span>${escapeHTML(e.reported_quarter ? quarterLabel(e.reported_quarter) : 'Квартал не указан')}</span><span class="arrow">↗</span></div></button>`;
  }).join('') : '<div class="empty">Мероприятий пока нет.<br>Добавьте событие или измените фильтры.</div>';
}
async function reload() {
  const response = await fetch('/api/events', {cache:'no-store'});
  if (!response.ok) throw Error('Не удалось загрузить журнал. Проверьте, запущен ли сервер.');
  journal = await response.json();
  populateQuarters(); render();
}
function showError(message) { $('#form-error').textContent = message; $('#form-error').hidden = false; }
function cleanupUploads() { objectURLs.forEach(URL.revokeObjectURL); objectURLs = []; uploads = []; $('#photo-input').value = ''; }
function updatePreviews() {
  objectURLs.forEach(URL.revokeObjectURL); objectURLs = [];
  const existing = editing ? photos(editing) : [];
  $('#photo-previews').innerHTML = existing.map(p=>`<div class="photo-preview"><a href="${photoURL(p)}" target="_blank" rel="noopener"><img src="${photoURL(p)}" alt="Сохранённая фотография"></a><small>В репозитории</small></div>`).join('') + uploads.map((file,i)=>{
    const url = URL.createObjectURL(file); objectURLs.push(url);
    return `<div class="photo-preview"><img src="${url}" alt="${escapeHTML(file.name)}"><button type="button" data-remove="${i}" aria-label="Убрать ${escapeHTML(file.name)}">×</button><small>${escapeHTML(file.name)}</small></div>`;
  }).join('');
}
function addFiles(files) {
  $('#form-error').hidden = true;
  const list = [...files];
  if (uploads.length + list.length > 6) return showError('За одно сохранение можно добавить до 6 новых фото.');
  for (const file of list) {
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) return showError('Выберите фотографии JPEG, PNG или WebP.');
    if (file.size > 8*1024*1024 || !file.size) return showError('Каждая фотография должна быть не больше 8 МБ и не пустой.');
  }
  uploads.push(...list); updatePreviews(); $('#photo-input').value = '';
}
function openEditor(event = null) {
  editing = event; form.reset(); cleanupUploads(); $('#form-error').hidden = true;
  $('#editor-title').textContent = event ? 'Редактировать мероприятие' : 'Новое мероприятие';
  const fields = ['name','date','date_end','organizer','location','description_draft','effect_draft','sms_attendance','total_attendance','notes'];
  fields.forEach(k=> {form.elements[k].value = event ? (typeof event[k] === 'object' && event[k] !== null ? JSON.stringify(event[k]) : event[k] ?? '') : '';});
  form.elements.reported_quarter.value = event?.reported_quarter || ($('#quarter').value !== 'all' ? $('#quarter').value : currentQuarter);
  form.elements.included_in_current_report.checked = Boolean(event?.included_in_current_report);
  ['sms_attendance','total_attendance'].forEach(k=>{
    form.elements[k + '_source'].value = sourceText(event?.[k + '_source'] || (event?.[k] !== null && event?.[k] !== undefined ? event?.attendance_source : ''));
  });
  updatePreviews(); editor.showModal();
}
function closeEditor() { if(saving) return; editor.close(); cleanupUploads(); }
function openDetails(id) {
  selected = journal.events.find(e=>e.id===id); if (!selected) return;
  $('#detail-title').textContent = selected.name;
  const e = selected;
  const entries = [
    ['Дата',dateLabel(e)+(e.date_end ? ' — '+new Date(e.date_end+'T12:00:00').toLocaleDateString('ru-RU') : '')],
    ['Квартал',e.reported_quarter ? quarterLabel(e.reported_quarter) : 'Уточняется'],
    ['Организатор',e.organizer || 'Уточняется'],['Место проведения',typeof e.location === 'object' && e.location ? (e.location.city || sourceText(e.location)) : e.location || 'Не указано'],
    ['Участники из СМС',e.sms_attendance ?? 'Не указано'],['Общий охват',e.total_attendance ?? 'Не указано'],
    ['Источник числа участников СМС',sourceText(e.sms_attendance_source || e.attendance_source) || 'Не указан'],['Источник общего охвата',sourceText(e.total_attendance_source || e.attendance_source) || 'Не указан'],
    ['Краткое описание',e.description_draft || 'Не указано',true],['Эффект · формулировка для отчёта',e.effect_draft || 'Не указан',true],['Статус',e.included_in_current_report ? 'Включено в квартальный отчёт' : 'Черновик'],['Полнота данных',isPending(e)?'Есть сведения для уточнения':'Основные данные заполнены'],['Примечания',e.notes || 'Нет',true]
  ];
  $('#detail-content').innerHTML = '<dl class="detail-data">'+entries.map(([label,value,wide])=>`<div class="${wide?'detail-wide':''}"><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`).join('')+'</dl><div class="section-label">ФОТОГРАФИИ <span>Оригиналы</span></div><div class="detail-photos">'+photos(e).map(p=>`<a href="${photoURL(p)}" target="_blank" rel="noopener"><img src="${photoURL(p)}" alt="${escapeHTML(p.original_name || p.description || e.name)}" loading="lazy"></a>`).join('')+'</div>'+(photos(e).length?'':'<p class="hint">Фотографии пока не добавлены.</p>');
  details.showModal();
}
function fileBase64(file) { return new Promise((resolve,reject)=> { const r = new FileReader(); r.onload=()=>resolve(String(r.result).split(',')[1]); r.onerror=()=>reject(Error('Не удалось прочитать фотографию')); r.readAsDataURL(file); }); }
$('#new-event').addEventListener('click',()=>openEditor());
$('#close-editor').addEventListener('click',closeEditor); $('#cancel').addEventListener('click',closeEditor);
editor.addEventListener('cancel', e=>{if(saving)e.preventDefault();else cleanupUploads();});
$('#close-details').addEventListener('click',()=>details.close());
$('#edit-detail').addEventListener('click',()=>{details.close();openEditor(selected);});
$('#events').addEventListener('click',e=>{const card=e.target.closest('[data-id]');if(card)openDetails(card.dataset.id);});
['#search','#quarter','#status'].forEach(s=>$(s).addEventListener(s==='#search'?'input':'change',render));
form.elements.date.addEventListener('change',()=>{if(form.elements.date.value)form.elements.reported_quarter.value=quarterOf(form.elements.date.value);});
$('#photo-input').addEventListener('change',e=>addFiles(e.target.files));
$('#photo-previews').addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(b){uploads.splice(Number(b.dataset.remove),1);updatePreviews();}});
['dragenter','dragover'].forEach(name=>$('#dropzone').addEventListener(name,e=>{e.preventDefault();$('#dropzone').classList.add('drag');}));
['dragleave','drop'].forEach(name=>$('#dropzone').addEventListener(name,e=>{e.preventDefault();$('#dropzone').classList.remove('drag');if(name==='drop')addFiles(e.dataTransfer.files);}));
form.addEventListener('submit',async event=>{
  event.preventDefault(); if(saving)return; $('#form-error').hidden=true;
  const data=Object.fromEntries(new FormData(form));
  data.included_in_current_report=form.elements.included_in_current_report.checked;
  for(const k of ['sms_attendance','total_attendance']) data[k]=data[k]===''?null:Number(data[k]);
  if(data.date && quarterOf(data.date)!==data.reported_quarter) return showError('Квартал должен соответствовать дате мероприятия.');
  if(data.date_end && (!data.date || data.date_end<data.date)) return showError('Проверьте даты начала и окончания.');
  for(const k of ['sms_attendance','total_attendance']) if(data[k]!==null&&!data[k+'_source'].trim())return showError('Укажите источник для каждого численного значения.');
  if(data.sms_attendance!==null&&data.total_attendance!==null&&data.sms_attendance>data.total_attendance)return showError('Число участников СМС не может превышать общий охват.');
  saving=true;$('#save').disabled=true;$('#save').textContent='Сохраняем…';
  try{
    data.uploads=await Promise.all(uploads.map(async file=>({name:file.name,data:await fileBase64(file)})));
    const response=await fetch(editing?'/api/events/'+encodeURIComponent(editing.id):'/api/events',{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json(); if(!response.ok)throw Error(result.error||'Не удалось сохранить мероприятие');
    editor.close();cleanupUploads();
    $('#toast').textContent='Мероприятие сохранено в журнале';$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,4000);
    try{await reload();}catch(error){$('#load-error').textContent='Запись сохранена. '+error.message;$('#load-error').hidden=false;}
  }catch(error){showError(error.message);}finally{saving=false;$('#save').disabled=false;$('#save').textContent='Сохранить мероприятие';}
});
$('#export').addEventListener('click',()=>{
  const blob=new Blob([JSON.stringify(journal,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='sms-events.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
reload().catch(error=>{$('#events').innerHTML='';$('#load-error').textContent=error.message;$('#load-error').hidden=false;});
