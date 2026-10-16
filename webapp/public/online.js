/* GitHub Pages adapter. Credentials live only in this page's memory. */
'use strict';
window.smsOnline = (() => {
  const owner='juliashar3-debug', repo='newrepository', branch='main';
  const base=`https://api.github.com/repos/${owner}/${repo}`;
  const ledgerPath='presentations/online-journal.json', reportsPath='presentations/online-reports.json';
  const requestPath='presentations/report-request.json';
  const encPath=p=>p.split('/').map(encodeURIComponent).join('/');
  const raw=(p,ref=branch)=>`https://raw.githubusercontent.com/${owner}/${repo}/${ref}/${encPath(p)}`;
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone=v=>structuredClone(v);
  let token='', connected=false, ledger=null, reports={}, inflight=null, fetched=0, authPromise=null;
  const jobs=new Map();
  const conflict='Журнал изменился в другой вкладке. Закройте карточку, обновите страницу и откройте её снова. Ваши несохранённые правки пока остаются в форме.';
  function clearCache(){fetched=0;inflight=null;}
  async function gh(path,method='GET',body,credential=token){
    const url=path==='/user'?'https://api.github.com/user':base+path;
    const response=await fetch(url,{method,cache:'no-store',headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',...(credential?{Authorization:`Bearer ${credential}`}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const result=response.status===204?{}:await response.json();
    if(!response.ok){
      const error=new Error(response.status===401?'Ключ GitHub недействителен или истёк. Подключите владельца заново.':response.status===409||response.status===422?conflict:response.status===403?'GitHub отказал в доступе. Проверьте права ключа: Contents — Read and write, Actions — Read-only, репозиторий newrepository. При превышении лимита повторите позже.':`GitHub: ${result.message||response.status}`);
      error.status=response.status;throw error;
    }
    return result;
  }
  async function readJSON(path,ref=branch){
    if(connected){
      const file=await gh(`/contents/${encPath(path)}?ref=${encodeURIComponent(ref)}`);
      return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(file.content.replace(/\s/g,'')),c=>c.charCodeAt(0))));
    }
    const response=await fetch(raw(path,ref)+`?v=${Date.now()}`,{cache:'no-store'});
    if(!response.ok)throw new Error('Не удалось загрузить свежие материалы GitHub.');
    return response.json();
  }
  async function refresh(){
    if(ledger&&Date.now()-fetched<1500)return;
    if(inflight)return inflight;
    inflight=(async()=>{
      try{[ledger,reports]=await Promise.all([readJSON(ledgerPath),readJSON(reportsPath)]);}
      catch(error){
        if(connected)throw error;
        const response=await fetch('online-snapshot.json',{cache:'no-store'});
        if(!response.ok)throw error;
        const snapshot=await response.json();ledger=snapshot.journal;reports=snapshot.reports;
      }
      fetched=Date.now();
    })();
    try{await inflight;}finally{inflight=null;}
  }
  function decorate(event){
    const e=clone(event);e.issues=[];
    for(const [key,label]of Object.entries({date:'дата',organizer:'организатор',description:'описание',sms_attendance:'участники из СМС',total_attendance:'численность команды'}))if(e[key]===null||e[key]===undefined||e[key]==='')e.issues.push(label);
    if(!e.photos.length)e.issues.push('фотографии');
    e.photos=e.photos.map(p=>({...p,url:raw(p.repository_path),thumbnail:raw(p.repository_path)}));
    return e;
  }
  function metadata(){
    const quarters=[...new Set(['2026-Q3','2026-Q4','2027-Q1',...ledger.events.map(e=>e.quarter),...Object.keys(reports)])].sort().reverse();
    return {quarters,default_quarter:ledger.default_quarter,plans:ledger.plans,order:ledger.order,
      report_builder:{ready:true,message:'Отчёт формируется в GitHub Actions'},
      reports:quarters.map(quarter=>{
        const report=reports[quarter]||{},before=report.revisions||{};
        const after=Object.fromEntries(ledger.events.filter(e=>e.quarter===quarter&&e.include&&!e.archived).map(e=>[e.id,e.revision]));
        const changed=[...new Set([...Object.keys(before),...Object.keys(after)])].filter(k=>before[k]!==after[k]).length;
        return {...report,quarter,changed,can_build:true,available:{pdf:!!report.pdf,pptx:!!report.pptx},job:jobs.get(quarter)||{state:'idle'}};
      })};
  }
  function help(){return `<section class="panel"><h2>Полный журнал на GitHub</h2><p>Нажмите «Подключить владельца» вверху страницы. После подключения можно добавлять и редактировать мероприятия, загружать фото, выбирать общий снимок и восстанавливать карточки из архива.</p><p>После сохранения нажмите «Обновить PPTX и PDF». Для нового квартала кнопка называется «Сформировать». Сборка выполняется в GitHub Actions и обычно занимает несколько минут. Прежние файлы доступны до её успешного завершения.</p><p>Материалы сохраняются в открытом репозитории newrepository и доступны посетителям. Ключ доступа не сохраняется: после закрытия или перезагрузки страницы подключите владельца снова. Изменения локального журнала 127.0.0.1 автоматически сюда не переносятся.</p><p>«Выгрузить журнал» скачивает JSON, «Материалы квартала · ZIP» — описание и оригиналы фото. В архиве карточку можно восстановить. Удаление снимка из карточки сохраняет оригинал в истории GitHub.</p><p><a href="https://github.com/${owner}/${repo}/actions/workflows/build-online-report.yml" target="_blank" rel="noopener">Ход и история сборок отчёта</a></p></section>`;}
  function ensureOwner(){
    if(connected)return Promise.resolve();
    if(authPromise)return authPromise;
    const dialog=document.getElementById('owner-dialog');dialog.showModal();
    authPromise=new Promise((resolve,reject)=>{
      const form=document.getElementById('owner-form'),error=document.getElementById('owner-error');
      const submit=async event=>{
        event.preventDefault();const field=form.elements.key,button=form.querySelector('[type=submit]');
        button.disabled=true;error.hidden=true;
        const candidate=field.value.trim();field.value='';
        try{
          const user=await gh('/user','GET',null,candidate);
          if(user.login.toLowerCase()!==owner)throw new Error('Редактировать этот журнал может только владелец juliashar3-debug.');
          const repository=await gh('','GET',null,candidate);
          if(!repository.permissions?.push)throw new Error('У ключа нет доступа на запись в newrepository. Выберите Contents → Read and write.');
          token=candidate;connected=true;clearCache();dialog.close('connected');
          document.getElementById('owner-connect').textContent='Отключить владельца';
          window.dispatchEvent(new Event('sms-online-connected'));
        }catch(e){error.textContent=e.message;error.hidden=false;}finally{button.disabled=false;}
      };
      form.addEventListener('submit',submit);
      dialog.addEventListener('close',()=>{form.removeEventListener('submit',submit);form.reset();authPromise=null;connected?resolve():reject(new Error('Подключение владельца отменено.'));},{once:true});
    });return authPromise;
  }
  async function head(){const ref=await gh(`/git/ref/heads/${branch}`);const commit=await gh(`/git/commits/${ref.object.sha}`);return {sha:ref.object.sha,tree:commit.tree.sha};}
  function b64(bytes){let value='';for(let i=0;i<bytes.length;i+=32768)value+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(value);}
  async function commitFiles(parent,files,message){
    const tree=[];
    for(const file of files){const blob=await gh('/git/blobs','POST',{content:typeof file.content==='string'?file.content:b64(file.content),encoding:typeof file.content==='string'?'utf-8':'base64'});tree.push({path:file.path,mode:'100644',type:'blob',sha:blob.sha});}
    const built=await gh('/git/trees','POST',{base_tree:parent.tree,tree});
    const commit=await gh('/git/commits','POST',{message,tree:built.sha,parents:[parent.sha]});
    await gh(`/git/refs/heads/${branch}`,'PATCH',{sha:commit.sha,force:false});clearCache();return commit.sha;
  }
  function validate(p){
    for(const [key,max]of Object.entries({name:250,organizer:1000,description:6000,effect:6000,formula:1000,notes:6000}))if(typeof p[key]!=='string'||p[key].length>max)throw new Error(`Проверьте поле ${key}.`);
    if(!p.name.trim())throw new Error('Укажите название мероприятия.');
    if(!/^20\d{2}-Q[1-4]$/.test(p.quarter))throw new Error('Выберите квартал.');
    for(const key of ['date','date_end'])if(p[key]&&(!/^\d{4}-\d{2}-\d{2}$/.test(p[key])||new Date(p[key]+'T12:00:00Z').toISOString().slice(0,10)!==p[key]))throw new Error('Проверьте дату мероприятия.');
    if(p.date&&`${p.date.slice(0,4)}-Q${Math.ceil(Number(p.date.slice(5,7))/3)}`!==p.quarter)throw new Error('Дата не соответствует выбранному кварталу.');
    if(p.date_end&&(!p.date||p.date_end<p.date))throw new Error('Дата окончания должна быть не раньше даты начала.');
    for(const k of ['sms_attendance','total_attendance'])if(p[k]!==null&&(!Number.isInteger(p[k])||p[k]<0||p[k]>1000000))throw new Error('Укажите целое неотрицательное количество участников.');
    if(p.sms_attendance!==null&&p.total_attendance!==null&&p.sms_attendance>p.total_attendance)throw new Error('Участников СМС не может быть больше команды.');
    if(!['confirmed','calculated'].includes(p.sms_type)||!['confirmed','calculated','photo'].includes(p.total_type))throw new Error('Укажите источник численности.');
    if(((p.sms_type==='calculated'&&p.sms_attendance!==null)||(p.total_type==='calculated'&&p.total_attendance!==null))&&!p.formula.trim())throw new Error('Укажите формулу для расчетной численности.');
  }
  async function saveCard(payload,{event,pending,removed,mainPhoto}){
    await ensureOwner();validate(payload);
    const parent=await head(),fresh=await readJSON(ledgerPath,parent.sha);
    const previous=event?fresh.events.find(e=>e.id===event.id):null;
    if(event&&(!previous||previous.revision!==event.revision))throw new Error(conflict);
    let photos=clone(previous?.photos||[]).filter(p=>!removed.includes(p.id));const files=[];
    if(photos.length+pending.length>30)throw new Error('Допустимо до 30 фотографий.');
    for(const item of pending){
      if(item.file.size>20*1024*1024)throw new Error('Фотография превышает 20 МБ.');
      const bytes=new Uint8Array(await item.file.arrayBuffer());
      const ext=bytes[0]===255&&bytes[1]===216&&bytes[2]===255?'jpg':bytes[0]===137&&bytes[1]===80&&bytes[2]===78&&bytes[3]===71?'png':String.fromCharCode(...bytes.subarray(0,4))==='RIFF'&&String.fromCharCode(...bytes.subarray(8,12))==='WEBP'?'webp':null;
      if(!ext)throw new Error('Нужен настоящий файл JPG, PNG или WebP.');
      const image=await createImageBitmap(item.file);if(image.width*image.height>100000000){image.close();throw new Error('Слишком большое разрешение фотографии.');}image.close();
      const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
      const id=digest.slice(0,24),path=`presentations/online-uploads/${digest}.${ext}`;
      if(!photos.some(p=>p.id===id)){photos.push({id,name:item.file.name,description:'',group:false,repository_path:path});files.push({path,content:bytes});}
      if(mainPhoto===item.key)mainPhoto=id;
    }
    if(!photos.some(p=>p.id===mainPhoto))mainPhoto=photos[0]?.id;
    photos.forEach(p=>p.group=p.id===mainPhoto);
    const saved={...previous,...payload,id:previous?.id||crypto.randomUUID(),photos,revision:(previous?.revision||0)+1,archived:previous?.archived||false,updated_at:new Date().toISOString()};
    delete saved.group_photo_id;
    if(previous)fresh.events[fresh.events.findIndex(e=>e.id===previous.id)]=saved;else fresh.events.push(saved);
    files.push({path:ledgerPath,content:JSON.stringify(fresh,null,2)+'\n'});
    await commitFiles(parent,files,`SMS: ${previous?'update':'add'} event ${saved.id}`);
    ledger=fresh;return decorate(saved);
  }
  async function archive(id,archived){
    await ensureOwner();const seen=ledger.events.find(e=>e.id===id);
    const parent=await head(),fresh=await readJSON(ledgerPath,parent.sha),event=fresh.events.find(e=>e.id===id);
    if(!event||event.revision!==seen?.revision)throw new Error(conflict);
    event.archived=!!archived;event.revision++;event.updated_at=new Date().toISOString();
    await commitFiles(parent,[{path:ledgerPath,content:JSON.stringify(fresh,null,2)+'\n'}],`SMS: ${archived?'archive':'restore'} ${id}`);
    ledger=fresh;return decorate(event);
  }
  async function rebuild(quarter){
    await ensureOwner();if(!/^20\d{2}-Q[1-4]$/.test(quarter))throw new Error('Неверный квартал.');
    if(jobs.get(quarter)?.state==='running')return jobs.get(quarter);
    const parent=await head(),request={quarter,request_id:crypto.randomUUID(),requested_at:new Date().toISOString()};
    const sha=await commitFiles(parent,[{path:requestPath,content:JSON.stringify(request,null,2)+'\n'}],`SMS: build ${quarter} ${request.request_id}`);
    const job={...request,sha,state:'running',message:'GitHub получил запрос. Ожидаем начало сборки…'};jobs.set(quarter,job);return job;
  }
  async function status(quarter){
    let job=jobs.get(quarter);
    if(!job)return {state:'idle'};
    const latest=await readJSON(reportsPath);
    if(latest[quarter]?.request_id===job.request_id){reports=latest;job={...job,state:'success',message:'Презентация и PDF готовы.'};clearCache();}
    else{
      const result=await gh(`/actions/workflows/build-online-report.yml/runs?head_sha=${encodeURIComponent(job.sha)}&per_page=10`);
      const run=result.workflow_runs?.[0];
      if(run){
        if(run.status==='completed')job={...job,state:'error',message:`Сборка ${run.conclusion==='success'?'завершилась, но новая пара файлов пока не найдена. Обновите страницу через минуту.':'не завершена успешно. Прежние файлы сохранены.'} Подробности: ${run.html_url}`};
        else job={...job,message:run.status==='queued'?'Сборка ожидает свободный сервер GitHub…':'GitHub формирует презентацию и PDF. Обычно это занимает несколько минут.'};
      }else if(Date.now()-Date.parse(job.requested_at)>180000)job={...job,state:'error',message:`GitHub не запустил сборку. Откройте https://github.com/${owner}/${repo}/actions и проверьте, включены ли Actions. Повторите запрос после включения.`};
    }
    jobs.set(quarter,job);return job;
  }
  async function api(url,options={}){
    const parsed=new URL(url,location.origin),body=options.body?JSON.parse(options.body):{};
    if(parsed.pathname==='/api/report/rebuild')return rebuild(body.quarter);
    if(parsed.pathname==='/api/report/status')return status(parsed.searchParams.get('quarter'));
    const match=parsed.pathname.match(/^\/api\/events\/([^/]+)\/archive$/);
    if(match)return archive(decodeURIComponent(match[1]),body.archived);
    await refresh();
    if(parsed.pathname==='/api/events')return {events:ledger.events.map(decorate)};
    if(parsed.pathname==='/api/meta')return metadata();
    throw new Error('Действие не поддерживается онлайн-журналом.');
  }
  function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
  // ZIP STORE: JPEG/PNG/PPTX are already compressed; no external script is needed.
  const crcTable=Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
  function zip(entries){
    const local=[],central=[];let offset=0,centralLength=0;
    for(const [name,bytes]of entries){
      const n=new TextEncoder().encode(name);let crc=0xffffffff;for(const b of bytes)crc=crcTable[(crc^b)&255]^(crc>>>8);crc=(crc^0xffffffff)>>>0;
      const header=new Uint8Array(30+n.length),h=new DataView(header.buffer);
      h.setUint32(0,0x04034b50,true);h.setUint16(4,20,true);h.setUint16(6,0x800,true);h.setUint32(14,crc,true);h.setUint32(18,bytes.length,true);h.setUint32(22,bytes.length,true);h.setUint16(26,n.length,true);header.set(n,30);local.push(header,bytes);
      const dir=new Uint8Array(46+n.length),d=new DataView(dir.buffer);d.setUint32(0,0x02014b50,true);d.setUint16(4,20,true);d.setUint16(6,20,true);d.setUint16(8,0x800,true);d.setUint32(16,crc,true);d.setUint32(20,bytes.length,true);d.setUint32(24,bytes.length,true);d.setUint16(28,n.length,true);d.setUint32(42,offset,true);dir.set(n,46);central.push(dir);centralLength+=dir.length;offset+=header.length+bytes.length;
    }
    const end=new Uint8Array(22),e=new DataView(end.buffer);e.setUint32(0,0x06054b50,true);e.setUint16(8,entries.length,true);e.setUint16(10,entries.length,true);e.setUint32(12,centralLength,true);e.setUint32(16,offset,true);
    return new Blob([...local,...central,end],{type:'application/zip'});
  }
  async function exportQuarter(quarter,withPhotos){
    await refresh();const data={schema_version:1,quarter,exported_at:new Date().toISOString(),events:clone(ledger.events.filter(e=>e.quarter===quarter&&!e.archived)),plans:ledger.plans.filter(p=>p.report_quarter===quarter),order:ledger.order[quarter]||[]};
    const entries=[],photos=new Map();
    if(withPhotos)for(const event of data.events)for(const photo of event.photos){const path=`photos/${photo.id}.${photo.repository_path.split('.').pop()}`;photos.set(path,photo.repository_path);photo.archive_path=path;}
    entries.push(['journal.json',new TextEncoder().encode(JSON.stringify(data,null,2))]);
    for(const [path,source]of photos){const response=await fetch(raw(source));if(!response.ok)throw new Error('Не удалось скачать фотографию. Повторите выгрузку.');entries.push([path,new Uint8Array(await response.arrayBuffer())]);}
    download(withPhotos?zip(entries):new Blob([entries[0][1]],{type:'application/json'}),`sms-${quarter}.${withPhotos?'zip':'json'}`);
  }
  function viewCard(event){
    if(!event)return;const dialog=document.getElementById('public-card');
    dialog.innerHTML=`<div class="panel"><button class="button secondary" id="public-close">Закрыть</button><h2>${escape(event.name)}</h2><p>${escape(event.date||'Дата не указана')}</p><p>${escape(event.organizer)}</p><p>${escape(event.description)}</p><p>${escape(event.effect)}</p><p>Команда: ${escape(event.total_attendance??'—')} · Из СМС: ${escape(event.sms_attendance??'—')}</p><div class="public-photos">${event.photos.map(p=>`<a href="${escape(p.url)}" target="_blank" rel="noopener"><img src="${escape(p.thumbnail)}" alt="${escape(p.name)}" loading="lazy"></a>`).join('')}</div><button class="button primary" id="public-edit">Редактировать мероприятие</button></div>`;
    dialog.querySelector('#public-close').onclick=()=>dialog.close();
    dialog.querySelector('#public-edit').onclick=async()=>{dialog.close();try{await ensureOwner();window.dispatchEvent(new CustomEvent('sms-online-edit',{detail:event.id}));}catch{}};
    dialog.showModal();
  }
  document.getElementById('owner-connect').onclick=()=>{
    if(connected){token='';connected=false;clearCache();document.getElementById('owner-connect').textContent='Подключить владельца';window.dispatchEvent(new Event('sms-online-connected'));}
    else ensureOwner().catch(()=>{});
  };
  document.getElementById('owner-cancel').onclick=()=>document.getElementById('owner-dialog').close();
  return {api,ensureOwner,isOwner:()=>connected,saveCard,viewCard,help,exportQuarter,reportUrl:(quarter,kind)=>raw(reports[quarter][kind])+`?v=${encodeURIComponent(reports[quarter].request_id||'initial')}`};
})();
