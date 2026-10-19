(()=>{'use strict';
const $=id=>document.getElementById(id),value=x=>Python.to_value(x),colors={left:'#80cfbf',right:'#efbd70',unassigned:'#b8b3c9'};
let doc=null,notes=[],pages=[],rows=[],transport=null,received=0,loadJob=null,exportJob=null,loadEpoch=0,zoom=1,view='roll',follow=true,keyboardMode='focused',keyboardLayout=null,overview=null,analysis=null,analysisOpen=false,lastClick=null,library={songs:[]},lastFollow=null,lift=0,drag=null;
let sheetRequest=null,sheetEpoch=0;
const metrics={windows:[],frames:0,start:performance.now(),windowStart:performance.now(),windowFrames:0};let measurement=null,noteById=new Map(),chipSignature='',overviewCache=null,rateBusy=false,keySignature='',lastPaint={seq:0,ids:[]};
const rollPainter=new PianoRollRenderer(colors,!!window.CPU_RENDERER);
function message(text){$('message').textContent=text||'';$('message').hidden=!text}
function safe(action){return async(...args)=>{try{return await action(...args)}catch(e){const text=String(e.message||e);if(!$('modal').hidden){let error=$('modalError');if(!error){error=document.createElement('p');error.id='modalError';error.className='practice-status error';error.setAttribute('role','alert');$('modalBody').prepend(error)}error.textContent=text}else message(text);return null}}}
function label(t){t=Math.floor(Math.max(0,t||0));return String(Math.floor(t/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0')}
function qn(pair){return pair[0]/pair[1]}
function sidebar(open){if(innerWidth<=1100){document.body.classList.toggle('sidebar-open',open);$('shade').hidden=!open}else document.body.classList.toggle('sidebar-closed',!open);setTimeout(resize,0)}
function modal(title,body,actions=[]){$('modalTitle').textContent=title;$('modalBody').textContent='';if(typeof body==='string')$('modalBody').textContent=body;else $('modalBody').appendChild(body);$('modalActions').textContent='';for(const [name,action] of actions){const b=document.createElement('button');b.textContent=name;b.onclick=safe(action);if(name.startsWith('确认')||name.startsWith('应用'))b.className='primary';$('modalActions').appendChild(b)}$('modal').hidden=false;$('closeModal').focus()}
function closeModal(){$('modal').hidden=true;$('menu').focus()}
function button(text,action){const b=document.createElement('button');b.textContent=text;b.onclick=safe(action);return b}

function setChoice(group, selected) {
  group.value=String(selected);
  if(group.dataset.selectedValue===String(selected))return;
  group.dataset.selectedValue=String(selected);
  for(const b of group.querySelectorAll('button[role=radio]')) {
    const chosen=Number.isFinite(Number(selected))&&Number.isFinite(Number(b.value))?Number(b.value)===Number(selected):b.value===String(selected);
    b.classList.toggle('chosen',chosen);b.setAttribute('aria-checked',String(chosen));b.tabIndex=chosen?0:-1;
  }
}
function disableChoice(group, disabled) {
  if(group.getAttribute('aria-disabled')===String(disabled))return;
  group.setAttribute('aria-disabled',String(disabled));
  for(const b of group.querySelectorAll('button'))b.disabled=disabled;
}
function wireChoice(group, initial) {
  if(group.dataset.wired)return;
  group.dataset.wired='true';
  setChoice(group,initial===undefined?group.dataset.value:initial);
  group.addEventListener('click',event=>{
    const b=event.target.closest('button[role=radio]');
    if(!b||b.disabled||b.closest('[role=radiogroup]')!==group)return;
    setChoice(group,b.value);b.focus();group.dispatchEvent(new Event('change',{bubbles:true}));
  });
  group.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    const buttons=Array.from(group.querySelectorAll('button[role=radio]')).filter(b=>!b.disabled);
    if(!buttons.length)return;
    event.preventDefault();event.stopPropagation();
    let at=buttons.indexOf(document.activeElement);
    at=event.key==='Home'?0:event.key==='End'?buttons.length-1:(at+(event.key==='ArrowLeft'||event.key==='ArrowUp'?-1:1)+buttons.length)%buttons.length;
    buttons[at].click();buttons[at].focus();
  });
}
function choices(name, options, selected, changed) {
  const group=document.createElement('div');group.className='segmented';group.setAttribute('role','radiogroup');group.setAttribute('aria-label',name);
  for(const [id,text] of options){const b=document.createElement('button');b.type='button';b.value=id;b.textContent=text;b.setAttribute('role','radio');group.appendChild(b)}
  wireChoice(group,selected);group.onchange=()=>changed(group.value);return group;
}
function practiceSection(parent,title) {
  const section=document.createElement('section');section.className='practice-section';
  const heading=document.createElement('h3');heading.textContent=title;section.appendChild(heading);parent.appendChild(section);return section;
}
function appliedPractice() {
  const state=value(piano.get_practice_settings());
  if(!doc||state.source_revision!==doc.source_revision)throw Error('乐谱已变化，请重新打开设置');
  return state;
}
function sameSource(state) {
  if(!doc||state.source_revision!==doc.source_revision)throw Error('乐谱已变化，请重新打开设置');
}
function modalBusy(busy) {
  for(const el of [...$('modalActions').querySelectorAll('button'),...$('modalBody').querySelectorAll('button,input')]) {
    if(busy){el.dataset.beforeBusyDisabled=String(el.disabled);el.disabled=true}
    else if(el.dataset.beforeBusyDisabled!==undefined){el.disabled=el.dataset.beforeBusyDisabled==='true';delete el.dataset.beforeBusyDisabled}
  }
}

function setup(canvas,w,h,clear=true){const dpr=window.CPU_RENDERER&&!canvas.classList.contains('score-base')?1:Math.min(2,devicePixelRatio||1);const pw=Math.max(1,Math.round(w*dpr)),ph=Math.max(1,Math.round(h*dpr));if(canvas.width!==pw||canvas.height!==ph){canvas.width=pw;canvas.height=ph}const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);if(clear)ctx.clearRect(0,0,w,h);return ctx}
function sourceTime(){if(!transport)return 0;const age=performance.now()-received;let t=transport.position_s;if(transport.phase==='playing'&&age<=250){t+=age/1000*transport.rate;if(transport.loop.enabled&&t>=transport.loop.b_s)t=transport.loop.a_s+(t-transport.loop.a_s)%(transport.loop.b_s-transport.loop.a_s)}return Math.min(transport.duration_s,t)}
function setFollow(on){follow=on;$('follow').setAttribute('aria-pressed',String(on));if(on)lastFollow=null}
function buildKeyboard(){rollPainter.clearEffects();keySignature='';const root=$('keys');root.textContent='';keyboardLayout=new KeyboardLayout(doc?doc.used_pitches:[],keyboardMode,root.clientWidth);for(const k of keyboardLayout.rects){const b=document.createElement('button');b.className='key '+(k.is_black?'black':'white')+(k.is_used?'':' unused');b.style.left=k.x+'px';b.style.width=k.width+'px';b.dataset.pitch=k.midi;b.setAttribute('aria-label',noteName(k.midi)+'，MIDI '+k.midi);const text=document.createElement('span');text.textContent=$('names').checked&&(keyboardMode!=='full'||k.midi%12===0||k.midi===21)?noteName(k.midi):'';b.appendChild(text);b.onclick=()=>{$('picked').textContent=noteName(k.midi)+' · MIDI '+k.midi+' · '+(440*2**((k.midi-69)/12)).toFixed(1)+' Hz'};root.appendChild(b)}setChoice($('keyboardMode'),keyboardMode)}
function resize(){if(!rows.length)return buildKeyboard();const width=Math.max(480,$('sheet').clientWidth-26)*zoom;for(const r of rows){const box=r.system.bbox,p=r.page;r.scale=width/p.width;r.top=Math.max(0,box[1]-24);r.height=box[3]+48;r.div.style.width=width+'px';r.canvas.style.height=r.height*r.scale+'px';r.base.style.height=r.height*r.scale+'px';r.baseReady=false}buildKeyboard();draw()}
function makeRows(nextPages){const list=[];for(const p of nextPages)for(const system of p.data.systems){const div=document.createElement('div'),base=document.createElement('canvas'),canvas=document.createElement('canvas');div.className='system';base.className='score-base';canvas.className='overlay';div.appendChild(base);div.appendChild(canvas);const row={page:p.data,image:p.image,system,div,base,canvas,scale:1,top:0,height:0};canvas.onclick=safe(event=>clickScore(row,event));list.push(row)}return list}
async function clickScore(row,event){if(!doc)return;const rect=row.canvas.getBoundingClientRect(),x=(event.clientX-rect.left)/row.scale,y=(event.clientY-rect.top)/row.scale+row.top;let found=row.page.glyphs.find(g=>g.system===row.system.id&&x>=g.bbox[0]&&x<=g.bbox[0]+g.bbox[2]&&y>=g.bbox[1]&&y<=g.bbox[1]+g.bbox[3]);if(!found){found=row.page.measures.find(m=>m.system===row.system.id&&x>=m.bbox[0]&&x<=m.bbox[0]+m.bbox[2]);if(found)found={element_id:found.measure_uid}}if(!found)return;lastClick=found.element_id;const result=value(await piano.seek_score(lastClick,null));updateTransport(result);const choices=result.seek_target.choices;$('occurrence').textContent='';delete $('occurrence').dataset.selectedValue;for(const c of choices){const o=doc.occurrences.find(o=>o.id===c.occurrence_id),b=document.createElement('button');b.type='button';b.value=c.occurrence_id;b.setAttribute('role','radio');b.textContent='第 '+o.visit_index+' 遍 · '+label(c.position_s);$('occurrence').appendChild(b)}wireChoice($('occurrence'),result.seek_target.occurrence_id);setChoice($('occurrence'),result.seek_target.occurrence_id);$('occurrence').hidden=choices.length<2;}
function drawSheet(){if(view!=='sheet'||!doc)return;lastPaint={seq:transport?transport.seq:0,received_to_paint_ms:performance.now()-received,ids:[]};const viewport=$('sheet').getBoundingClientRect(),active=new Set(transport&&doc&&transport.playback_revision===doc.playback_revision?transport.active_element_ids:[]),sustained=new Set(transport?transport.sustained_instance_ids:[]);let currentRow=null;for(const r of rows){const rect=r.div.getBoundingClientRect();if(rect.bottom<viewport.top-40||rect.top>viewport.bottom+40){if(r.canvas.width!==1){r.canvas.width=1;r.canvas.height=1;r.base.width=1;r.base.height=1;r.baseReady=false}continue}const w=r.page.width*r.scale,h=r.height*r.scale,ctx=setup(r.canvas,w,h);if(!r.baseReady){const baseContext=setup(r.base,w,h);baseContext.drawImage(r.image,0,r.top*r.page.image_scale,r.page.width*r.page.image_scale,r.height*r.page.image_scale,0,0,w,h);baseContext.globalCompositeOperation='source-in';baseContext.fillStyle='#eae7d8';baseContext.fillRect(0,0,w,h);baseContext.globalCompositeOperation='destination-over';baseContext.fillStyle='#182d2c';baseContext.fillRect(0,0,w,h);baseContext.globalCompositeOperation='source-over';r.baseReady=true;}for(const g of r.page.glyphs){if(g.system!==r.system.id)continue;const tails=g.spans.filter(s=>sustained.has(s.instance_id)),on=active.has(g.element_id);if(!on&&!tails.length)continue;const span=g.spans.find(s=>(transport.active_instance_ids||[]).includes(s.instance_id)||sustained.has(s.instance_id)),n=span?noteById.get(span.instance_id):null,b=g.bbox;ctx.fillStyle=colors[n?n.hand:'unassigned'];ctx.strokeStyle=ctx.fillStyle;ctx.globalAlpha=.7;if(on){ctx.fillRect(b[0]*r.scale,(b[1]-r.top)*r.scale,b[2]*r.scale,b[3]*r.scale);lastPaint.ids.push(g.element_id);}else ctx.strokeRect(b[0]*r.scale,(b[1]-r.top)*r.scale,b[2]*r.scale,b[3]*r.scale);ctx.globalAlpha=1}if(transport){const m=r.page.measures.find(m=>m.system===r.system.id&&m.occurrences.some(o=>o.id===transport.occurrence_id));if(m){currentRow=r;let x=m.bbox[0];const anchors=m.anchors||[];for(let i=0;i<anchors.length-1;i++){const a=anchors[i],b=anchors[i+1],q=transport.measure_qn;if(q>=qn(a.qn)&&q<=qn(b.qn)){x=a.x+(b.x-a.x)*(q-qn(a.qn))/(qn(b.qn)-qn(a.qn));break}}ctx.strokeStyle='#efbd70';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x*r.scale,(m.bbox[1]-r.top-7)*r.scale);ctx.lineTo(x*r.scale,(m.bbox[1]+m.bbox[3]-r.top+7)*r.scale);ctx.stroke()}}}if(follow&&transport&&lastFollow!==transport.occurrence_id){if(!currentRow)currentRow=rows.find(r=>r.page.measures.some(m=>m.system===r.system.id&&m.occurrences.some(o=>o.id===transport.occurrence_id)));if(currentRow){const b=currentRow.div.getBoundingClientRect();if(b.top<viewport.top||b.bottom>viewport.bottom)$('sheet').scrollTop+=b.top-viewport.top-12;lastFollow=transport.occurrence_id}}}
function drawRoll(){if(view!=='roll'||!keyboardLayout)return;const c=$('roll'),r=c.getBoundingClientRect(),ctx=setup(c,r.width,r.height,false);const line=rollPainter.paint(ctx,keyboardLayout,r.width,r.height,sourceTime(),transport,lift,performance.now());const strike=$('strike'),top=line+'px';if(strike.style.top!==top)strike.style.top=top;strike.classList.toggle('flow',!!transport&&transport.phase==='playing'&&transport.volume>0&&rollPainter.enabled&&!rollPainter.reducedMotion)}
function drawKeys(){if($('keyboard').hidden||!transport)return;if(doc&&transport.playback_revision!==doc.playback_revision)return;const signature=transport.active_instance_ids.join(',')+'|'+transport.sustained_instance_ids.join(',')+'|'+(doc?doc.playback_revision:'');if(signature===keySignature)return;keySignature=signature;const byPitch=new Map(),tailPitch=new Set();for(const id of transport.active_instance_ids){const n=noteById.get(id);if(n){if(!byPitch.has(n.pitch))byPitch.set(n.pitch,[]);byPitch.get(n.pitch).push(n)}}for(const id of transport.sustained_instance_ids){const n=noteById.get(id);if(n)tailPitch.add(n.pitch)}for(const key of $('keys').children){const pitch=Number(key.dataset.pitch),matching=byPitch.get(pitch)||[],hands=new Set(matching.map(n=>n.hand));key.classList.remove('left','right','both','unassigned','sustain');if(matching.length)key.classList.add(hands.has('left')&&hands.has('right')?'both':matching[0].hand);if(tailPitch.has(pitch))key.classList.add('sustain')}}
function drawOverview() {
  const c=$('overview'),r=c.getBoundingClientRect(),ctx=setup(c,r.width,r.height);
  if(!overviewCache||overviewCache.source!==overview||overviewCache.width!==r.width||overviewCache.height!==r.height){
    const base=document.createElement('canvas'),paint=setup(base,r.width,r.height);
    paint.fillStyle='#0e1e1f';paint.fillRect(0,0,r.width,r.height);
    if(overview&&doc){paint.strokeStyle='#5e9c8c';paint.beginPath();for(let i=0;i<overview.min.length;i++){const x=i/overview.min.length*r.width;paint.moveTo(x,r.height/2-overview.max[i]*r.height);paint.lineTo(x,r.height/2-overview.min[i]*r.height)}paint.stroke()}
    overviewCache={source:overview,width:r.width,height:r.height,canvas:base};
  }
  ctx.drawImage(overviewCache.canvas,0,0,r.width,r.height);
  if(!overview||!doc||!transport)return;
  const t=transport;
  if(t.loop.enabled){ctx.fillStyle='#d6b26b22';ctx.fillRect(t.loop.a_s/doc.duration_s*r.width,0,(t.loop.b_s-t.loop.a_s)/doc.duration_s*r.width,r.height);for(const [v,text] of [[t.loop.a_s,'A'],[t.loop.b_s,'B']]){const x=v/doc.duration_s*r.width;ctx.fillStyle='#e3bb71';ctx.fillText(text,x+3,10);ctx.fillRect(x,0,1,r.height)}}
  ctx.fillStyle='#f0d29a';ctx.fillRect(t.position_s/doc.duration_s*r.width,0,2,r.height);
}
function drawAnalysis(){if(!analysisOpen||!analysis)return;for(const [id,data] of [['wave',analysis.waveform],['spectrum',analysis.spectrum_db]]){const c=$(id),r=c.getBoundingClientRect(),ctx=setup(c,r.width,r.height);ctx.strokeStyle='#80cfbf';ctx.beginPath();for(let i=0;i<data.length;i++){const x=i/data.length*r.width,y=id==='wave'?r.height/2-data[i]*r.height*.9:r.height-(data[i]+90)/90*r.height;i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()}}
function drawCurrent(){if(!transport)return;const signature=transport.active_instance_ids.join(',')+'|'+transport.playback_revision;if(signature===chipSignature)return;chipSignature=signature;$('currentNotes').textContent='';const played=new Set();for(const id of transport.active_instance_ids){const n=noteById.get(id);if(!n||played.has(n.pitch+':'+n.hand))continue;played.add(n.pitch+':'+n.hand);const chip=document.createElement('span');chip.className='note-chip '+n.hand;chip.textContent=(n.hand==='left'?'左手 · ':n.hand==='right'?'右手 · ':'')+noteName(n.pitch);$('currentNotes').appendChild(chip)}}
function draw(){drawSheet();drawRoll();drawKeys();drawCurrent();drawOverview();drawAnalysis()}
function updateTransport(next) {
  if(transport&&next.seq<transport.seq)return;
  transport=next;received=performance.now();rollPainter.observe(next,view==='roll',received);
  const playing=next.phase==='playing';if($('play').textContent!==(playing?'Ⅱ':'▶'))$('play').textContent=playing?'Ⅱ':'▶';
  $('play').setAttribute('aria-label',next.phase==='playing'?'暂停':'播放');$('play').title=next.phase==='playing'?'暂停':'播放';
  if($('position').textContent!==label(next.position_s))$('position').textContent=label(next.position_s);
  if(document.activeElement!==$('seek'))$('seek').value=next.position_s;
  setChoice($('rate'),next.rate);disableChoice($('rate'),!doc||rateBusy);
  setChoice($('handQuick'),next.hand_mode||'both');disableChoice($('handQuick'),!doc||rateBusy);
  $('volumeText').textContent=Math.round(next.volume*100)+'%';$('overview').setAttribute('aria-valuenow',String(next.position_s));$('overview').setAttribute('aria-valuemax',String(next.duration_s));
  $('loop').setAttribute('aria-pressed',String(next.loop.enabled));$('loopInputs').hidden=!next.loop.enabled;
  if(doc){const occurrenceAt=s=>doc.occurrences.find(o=>o.start_s<=s&&s<o.end_s)||doc.occurrences[doc.occurrences.length-1],a=occurrenceAt(next.loop.a_s),b=occurrenceAt(Math.max(0,next.loop.b_s-1e-8));if(a&&b)$('loopVisits').textContent='A：小节 '+a.number+'／第 '+a.visit_index+' 遍　B：小节 '+b.number+'／第 '+b.visit_index+' 遍'}
  $('deviceError').hidden=next.audio_ready||!doc;
  $('visitText').textContent=doc?'小节 '+next.measure_number+' · 第 '+next.visit_index+' 遍':'';
  for(const id of ['play','stop','loop','export','audition','hands'])$(id).disabled=!doc;
}
function updateDocumentLabels(){ $('diagnostics').textContent='乐谱提示'+(doc.diagnostics_count?' · '+doc.diagnostics_count:'');$('title').textContent=doc.title;$('meta').textContent=doc.staff_ids.length+' 谱表 · '+doc.source_notes+' 个音符 · '+label(doc.duration_s);$('duration').textContent=label(doc.duration_s);$('seek').max=doc.duration_s;$('loopB').max=doc.duration_s;$('handHint').textContent=doc.hand_status==='confirmed'?'左右手已确认，可单独试听。':'上下谱表仅为建议，确认后可单手试听。';chipSignature='';}
async function refresh(){doc=value(piano.get_document());if(!doc)return;notes=[];for(let offset=0;offset<doc.notes_count;offset+=1000){const page=value(piano.get_notes(offset,1000));if(page.playback_revision!==doc.playback_revision)throw Error('曲目版本已变化');notes.push(...page.notes)}noteById=new Map(notes.map(n=>[n.id,n]));rollPainter.setNotes(notes,doc.playback_revision);keySignature='';overview=value(piano.get_overview());updateDocumentLabels();updateTransport(value(piano.get_transport()));buildKeyboard()}
function cancelSheet(){sheetEpoch++;if(sheetRequest&&sheetRequest.job_id)piano.cancel_job(sheetRequest.job_id);sheetRequest=null}
function sheetStatus(text,actionText,action){const box=document.createElement('div');box.className='sheet-status';const p=document.createElement('p');p.textContent=text;box.appendChild(p);if(actionText)box.appendChild(button(actionText,action));$('sheet').replaceChildren(box)}
async function decodeLayout(layout,valid){
  const next=[];
  for(const descriptor of layout.pages){
    if(!valid())return null;
    const data=value(piano.get_score_page(layout.layout_revision,descriptor.page,layout.candidate_id)),image=new Image();
    await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('乐谱底图加载超时')),15000);image.onload=()=>{clearTimeout(timeout);resolve()};image.onerror=()=>{clearTimeout(timeout);reject(Error('乐谱底图加载失败'))};image.src=descriptor.resource});
    if(!valid())return null;
    next.push({data,image});
  }
  return next;
}
async function ensureSheet(){
  if(!doc||rows.length||sheetRequest||view!=='sheet'||loadJob)return;
  const request={epoch:sheetEpoch,revision:doc.source_revision,job_id:null};sheetRequest=request;
  const valid=()=>sheetRequest===request&&sheetEpoch===request.epoch&&doc&&doc.source_revision===request.revision&&view==='sheet'&&!loadJob;
  message('');
  sheetStatus('正在排版五线谱，播放可继续…','取消排版',()=>{cancelSheet();sheetStatus('排版已取消。','重新排版',ensureSheet)});
  try{
    let result=value(piano.begin_score_layout(request.revision));
    if(!result.ready){
      request.job_id=result.job_id;
      while(valid()){
        const state=value(piano.get_job(request.job_id));
        if(state.phase==='layout_ready'){result=value(piano.get_layout_candidate(request.job_id));break}
        if(state.done)throw Error(state.error?state.error.message:'排版已取消');
        await new Promise(resolve=>setTimeout(resolve,50));
      }
    }
    if(!valid())return;
    const next=await decodeLayout(result,valid);
    if(!next||!valid())return;
    const preparedRows=makeRows(next);
    doc=result.candidate_id?value(piano.publish_score_layout(result.candidate_id,request.revision,result.layout_revision)):value(piano.get_document());
    pages=next;rows=preparedRows;$('sheet').textContent='';for(const row of rows)$('sheet').appendChild(row.div);
    lastFollow=null;updateDocumentLabels();resize();
  }catch(e){
    if(request.job_id)piano.cancel_job(request.job_id);
    if(valid()){sheetStatus(String(e.message||e),'重新排版',()=>{sheetRequest=null;ensureSheet()});message('五线谱暂不可用，仍可使用下落音符与播放：'+String(e.message||e))}
  }finally{if(sheetRequest===request)sheetRequest=null}
}
async function load(token){cancelSheet();loadEpoch++;const epoch=loadEpoch;loadJob=value(piano.begin_score_load(token,{}));loadJob.epoch=epoch;$('loading').hidden=false;message('');if(innerWidth<=1100)sidebar(false)}
async function candidateReady(job){
  const epoch=job.epoch,c=value(piano.get_candidate(job.job_id)),preparedNotes=[];
  for(let offset=0;offset<c.notes_count;offset+=1000){const page=value(piano.get_notes(offset,1000,job.job_id));if(epoch!==loadEpoch)return;if(page.playback_revision!==c.playback_revision)throw Error('候选播放版本已过期');preparedNotes.push(...page.notes)}
  if(epoch!==loadEpoch)return;
  const published=value(await piano.publish_score_load(job.job_id,c.source_sha256));
  if(epoch!==loadEpoch)return;
  doc=published;notes=preparedNotes;noteById=new Map(notes.map(n=>[n.id,n]));rollPainter.setNotes(notes,doc.playback_revision);keySignature='';overview=c.overview;
  pages=[];rows=[];$('sheet').textContent='';loadJob=null;$('loading').hidden=true;lastClick=null;$('occurrence').hidden=true;lastFollow=null;setFollow(true);closeModal();updateDocumentLabels();updateTransport(value(piano.get_transport()));resize();window.PIANOSCOPE_READY=true;

  if(view==='sheet')ensureSheet();
}
function confirmation(job,state){const box=document.createElement('div');let tempo=null,group=null;const p=document.createElement('p');p.textContent=state.title;box.appendChild(p);if(state.required.default_tempo){const l=document.createElement('label');l.textContent=state.required.default_tempo;tempo=document.createElement('input');tempo.type='number';tempo.min=10;tempo.max=1000;tempo.value=120;l.appendChild(tempo);box.appendChild(l)}if(state.required.piano_group_confirmed){const l=document.createElement('label');group=document.createElement('input');group.type='checkbox';l.appendChild(group);l.appendChild(document.createTextNode('确认这两个分部组成同一钢琴组'));box.appendChild(l)}modal('确认播放设置',box,[['取消',()=>{piano.cancel_job(job.job_id);loadJob=null;loadEpoch++;$('loading').hidden=true;closeModal()}],['确认并继续',()=>{if(group&&!group.checked)throw Error('请确认钢琴分部');const settings={};if(tempo)settings.default_tempo=Number(tempo.value);if(group)settings.piano_group_confirmed=true;const next=value(piano.confirm_score_load(job.job_id,state.source_sha256,settings));next.epoch=++loadEpoch;loadJob=next;closeModal()}]]);job.confirmedShown=true}
async function poll(){try{if(loadJob&&!loadJob.decoding){const job=loadJob,state=value(piano.get_job(job.job_id));const phases={reading:'正在读取乐谱',needs_confirmation:'等待确认播放设置',compiling:'正在准备播放数据',synthesizing:'正在准备钢琴声音',candidate_ready:'正在打开曲目'};$('loadLabel').textContent=phases[state.phase]||state.phase;if(state.phase==='needs_confirmation'&&!job.confirmedShown)confirmation(job,state);else if(state.phase==='candidate_ready'){job.decoding=true;try{await candidateReady(job)}catch(e){if(job.epoch===loadEpoch){piano.cancel_job(job.job_id);loadJob=null;$('loading').hidden=true;ensureSheet();throw e}}}else if(state.done){if(loadJob===job){loadJob=null;$('loading').hidden=true;if(state.error)message(state.error.message+(state.error.issues||[]).map(i=>i.source_locator?'\n'+i.source_locator:'').join(''));ensureSheet()}}}if(exportJob){const s=value(piano.get_job(exportJob.job_id));if(s.done){exportJob=null;if(s.error)message(s.error.message);else message(s.cancelled?'导出已取消':'导出完成：'+s.filename)}}updateTransport(value(piano.get_transport()));if(analysisOpen)analysis=value(piano.get_analysis())}catch(e){message(String(e.message||e))}setTimeout(poll,25)}
function renderLibrary(){const query=$('search').value.toLowerCase();$('folderName').textContent=library.folder_name||'当前文件夹';$('library').textContent='';for(const song of library.songs.filter(s=>s.name.toLowerCase().includes(query))){$('library').appendChild(button(song.name,()=>load(song.file_token)))}}
async function audition() {
  if(!doc)return;
  if(innerWidth<=1100)sidebar(false);
  const state=appliedPractice(),box=document.createElement('div'),voices=[];
  let selectedStaffs=state.staff_ids.slice();
  const intro=document.createElement('p');intro.className='hint';intro.textContent='选择要听的谱表。只改变声音，不修改乐谱或导出。';box.appendChild(intro);
  const section=practiceSection(box,'试听谱表'),status=document.createElement('p');status.className='practice-status';status.setAttribute('role','status');
  function updateStatus(){const hand=state.hand_mode==='left'?'（当前只听左手）':state.hand_mode==='right'?'（当前只听右手）':'';status.textContent=selectedStaffs.length&&voices.some(v=>v.check.checked)?'应用后试听所选部分'+hand+'。':'当前未选声音，应用后将静音。'}
  const options=[['all','全部']];for(let i=0;i<state.staves.length;i++)options.push([String(i),state.staves[i].name]);options.push(['none','静音']);
  const current=selectedStaffs.length===state.staves.length?'all':selectedStaffs.length===1?String(state.staves.findIndex(s=>s.id===selectedStaffs[0])):'none';
  const presets=choices('试听谱表',options,current,mode=>{selectedStaffs=mode==='all'?state.staves.map(s=>s.id):mode==='none'?[]:[state.staves[Number(mode)].id];updateStatus()});section.appendChild(presets);
  const detail=document.createElement('details'),heading=document.createElement('summary');detail.className='practice-section';detail.appendChild(heading);box.appendChild(detail);
  function voiceSummary(){heading.textContent='按声部筛选 · 已选 '+voices.filter(v=>v.check.checked).length+' / '+state.voices.length;updateStatus()}
  const voiceOptions=document.createElement('div');voiceOptions.className='practice-options';detail.appendChild(voiceOptions);
  for(const voice of state.voices){const label=document.createElement('label'),input=document.createElement('input');label.className='check-option';input.type='checkbox';input.checked=state.voice_ids.includes(voice.id);input.dataset.sourceId=voice.id;input.onchange=voiceSummary;label.append(input,document.createTextNode(voice.name));voiceOptions.appendChild(label);voices.push({id:voice.id,check:input})}
  box.appendChild(status);voiceSummary();
  modal('试听范围',box,[['恢复全部范围',()=>{selectedStaffs=state.staves.map(s=>s.id);for(const v of voices)v.check.checked=true;setChoice(presets,'all');voiceSummary()}],['取消',closeModal],['应用试听',async()=>{sameSource(state);modalBusy(true);status.textContent='正在准备声音…';try{updateTransport(value(await piano.configure({staff_ids:selectedStaffs,voice_ids:voices.filter(v=>v.check.checked).map(v=>v.id)})));closeModal()}finally{modalBusy(false)}}]]);
}
async function hands() {
  if(!doc)return;
  if(innerWidth<=1100)sidebar(false);
  const state=appliedPractice(),box=document.createElement('div'),elements=value(piano.get_source_elements()),groups=[];
  const intro=document.createElement('p');intro.className='hint';intro.textContent=state.hand_status==='confirmed'?'以下为已保存的分配。更改后确认即可，原谱保持不变。':'按谱表给出初始建议；确认前不会当作已分手，也不会改变声音。';box.appendChild(intro);
  const section=practiceSection(box,'谱表与左右手'),status=document.createElement('p');status.className='practice-status';status.setAttribute('role','status');let preview=null;
  function previewLabels(){sameSource(state);const assignments=Object.create(null);for(const element of elements){const group=groups.find(g=>g.id===element.staff_id);if(group&&group.value!=='keep')assignments[element.element_id]=group.value}preview=value(piano.preview_hands(assignments));status.textContent='分配预览：左手 '+preview.counts.left+' 个音符，右手 '+preview.counts.right+' 个，未分配 '+preview.counts.unassigned+' 个。确认后生效。'}
  for(const staff of state.staves){const row=document.createElement('div');row.className='practice-row';const label=document.createElement('span'),name=document.createElement('b'),count=document.createElement('small');name.textContent=staff.name;count.textContent=staff.notes+' 个音符';label.append(name,count);const current=staff.hand==='mixed'?'keep':state.hand_status==='confirmed'?staff.hand:staff.suggestion;const group={id:staff.id,value:current};groups.push(group);const options=[['unassigned','未分配'],['left','左手'],['right','右手']];if(staff.hand==='mixed')options.push(['keep','保留逐音符分配']);const control=choices(staff.name+'手别',options,current,v=>{group.value=v;previewLabels()});row.append(label,control);section.appendChild(row)}
  box.appendChild(status);
  modal('左右手设置',box,[['撤销上次分配',async()=>{sameSource(state);modalBusy(true);try{await piano.undo_hands();await refresh();await hands()}finally{modalBusy(false)}}],['取消',closeModal],['确认分配',async()=>{sameSource(state);modalBusy(true);status.textContent='正在应用分配…';try{await piano.apply_hands(preview.preview_id);await refresh();closeModal()}finally{modalBusy(false)}}]]);
  $('modalActions').firstElementChild.disabled=!state.can_undo;
  previewLabels();
}
async function diagnostics(cursor=0){const data=value(piano.get_diagnostics(cursor)),box=document.createElement('div'),p=document.createElement('p');p.textContent='共 '+data.total+' 条提示；原文件完整保留。';box.appendChild(p);for(const issue of data.items){const item=document.createElement('div');item.className='issue';item.textContent=issue.message;const small=document.createElement('small');small.textContent=issue.source_locator||issue.element_id||'';item.appendChild(small);box.appendChild(item)}modal('乐谱提示',box,data.next_cursor===null?[]:[['下一页',()=>diagnostics(data.next_cursor)]])}
function exporting(){if(!doc)return;modal('导出 '+doc.original_name,'默认导出完整乐谱。PDF 为打印谱面，原文件副本保持原字节，MIDI 使用乐谱基准速度；试听范围、音量与慢速设置不会改变导出。',['pdf','source','midi'].map((format,i)=>[['PDF','原文件副本','MIDI'][i],()=>{const target=value(piano.choose_export(doc.source_revision,format));if(target){exportJob=value(piano.begin_export(target.snapshot_id,format,target.target_token));message('正在导出：'+target.filename)}closeModal()}]))}
const toggle=safe(async()=>updateTransport(value(await(transport&&transport.phase==='playing'?piano.pause():piano.play()))));
$('open').onclick=$('emptyOpen').onclick=safe(()=>{const token=value(piano.choose_score());if(token)return load(token)});$('folder').onclick=safe(async()=>{const next=value(await piano.choose_score_folder());if(next){library=next;renderLibrary()}});$('search').oninput=renderLibrary;document.querySelectorAll('[data-demo]').forEach(b=>b.onclick=safe(()=>load(b.dataset.demo)));$('menu').onclick=()=>sidebar(innerWidth<=1100?!document.body.classList.contains('sidebar-open'):document.body.classList.contains('sidebar-closed'));$('closeSidebar').onclick=$('shade').onclick=()=>sidebar(false);$('closeModal').onclick=closeModal;
$('play').onclick=toggle;$('stop').onclick=safe(async()=>updateTransport(value(await piano.stop())));$('seek').onchange=safe(async()=>updateTransport(value(await piano.seek(Number($('seek').value)))));$('volume').oninput=safe(()=>{const v=Number($('volume').value);try{localStorage.setItem('volume',String(v))}catch(_){}updateTransport(value(piano.set_volume(v)))});$('rate').onchange=safe(async()=>{const rate=Number($('rate').value);rateBusy=true;disableChoice($('rate'),true);try{updateTransport(value(await piano.configure({rate})))}finally{rateBusy=false;updateTransport(value(piano.get_transport()))}});$('retry').onclick=safe(async()=>updateTransport(value(await piano.retry_audio())));
$('loop').onclick=safe(async()=>{if(!doc)return;const current=transport.loop,a=current.a_s,b=current.b_s>a+.49?current.b_s:Math.min(doc.duration_s,a+4);updateTransport(value(await piano.set_loop(!current.enabled,a,b)));$('loopA').value=a;$('loopB').value=b});$('applyLoop').onclick=safe(async()=>updateTransport(value(await piano.set_loop(true,Number($('loopA').value),Number($('loopB').value)))));
$('sheetMode').onclick=()=>setView('sheet');$('rollMode').onclick=()=>setView('roll');function setView(mode){if(view!==mode){rollPainter.reset();if(mode==='roll')cancelSheet()}view=mode;if(transport)rollPainter.observe(transport,mode==='roll',performance.now());$('sheet').hidden=mode!=='sheet';$('rollArea').hidden=mode!=='roll';setChoice($('sheetMode').parentElement,mode);document.body.classList.toggle('roll-view',mode==='roll');document.querySelector('.score-tools').hidden=mode!=='sheet';if(mode==='roll')$('keyboard').hidden=false;resize();if(mode==='sheet')ensureSheet()}
$('follow').onclick=()=>setFollow(!follow);$('current').onclick=()=>setFollow(true);$('sheet').addEventListener('wheel',()=>setFollow(false),{passive:true});$('sheet').addEventListener('touchmove',()=>setFollow(false),{passive:true});$('sheet').addEventListener('pointerdown',event=>{if(event.target===$('sheet'))setFollow(false)});$('zoom').onchange=()=>{zoom=Number($('zoom').value);setChoice($('zoom'),zoom);resize()};$('occurrence').onchange=safe(async()=>updateTransport(value(await piano.seek_score(lastClick,$('occurrence').value))));$('keyboardToggle').onclick=()=>{$('keyboard').hidden=!$('keyboard').hidden;$('keyboardToggle').textContent=$('keyboard').hidden?'显示键盘':'收起键盘';resize()};$('analysisToggle').onclick=()=>{analysisOpen=!analysisOpen;$('analysis').hidden=!analysisOpen;$('analysisToggle').textContent=analysisOpen?'收起频谱':'查看频谱';resize()};$('full').onclick=()=>{keyboardMode='full';try{localStorage.setItem('keyboardMode',keyboardMode)}catch(_){}buildKeyboard()};$('focused').onclick=()=>{keyboardMode='focused';try{localStorage.setItem('keyboardMode',keyboardMode)}catch(_){}buildKeyboard()};$('names').onchange=buildKeyboard;
function setLift(n){lift=Math.max(0,Math.min(60,Math.round(n)));$('lift').value=lift;$('liftText').textContent=lift+'%';try{localStorage.setItem('strikeLift',String(lift))}catch(_){}}$('lift').oninput=()=>setLift(Number($('lift').value));$('strikeLabel').onpointerdown=e=>{drag={kind:'lift'};e.preventDefault()};
$('overview').onpointerdown=e=>{if(!doc)return;const r=$('overview').getBoundingClientRect(),t=(e.clientX-r.left)/r.width*doc.duration_s;drag={kind:'seek',seconds:t};if(transport.loop.enabled){if(Math.abs(t-transport.loop.a_s)/doc.duration_s*r.width<12)drag.kind='a';else if(Math.abs(t-transport.loop.b_s)/doc.duration_s*r.width<12)drag.kind='b'}};window.addEventListener('pointermove',e=>{if(!drag)return;if(drag.kind==='lift'){const r=$('rollArea').getBoundingClientRect();setLift((r.bottom-e.clientY)/r.height*100)}else{const r=$('overview').getBoundingClientRect();drag.seconds=Math.max(0,Math.min(doc.duration_s,(e.clientX-r.left)/r.width*doc.duration_s))}});window.addEventListener('pointerup',safe(async()=>{const d=drag;drag=null;if(!d||d.kind==='lift')return;if(d.kind==='seek')updateTransport(value(await piano.seek(d.seconds)));else{const loop=transport.loop,a=d.kind==='a'?Math.min(d.seconds,loop.b_s-.5):loop.a_s,b=d.kind==='b'?Math.max(d.seconds,loop.a_s+.5):loop.b_s;updateTransport(value(await piano.set_loop(true,a,b)));$('loopA').value=a;$('loopB').value=b}}));
$('audition').onclick=safe(audition);$('hands').onclick=safe(hands);$('handQuick').onchange=safe(async()=>{const chosen=$('handQuick').value;if(!doc)return;if(doc.hand_status!=='confirmed'&&chosen!=='both'){setChoice($('handQuick'),transport.hand_mode||'both');return hands()}rateBusy=true;try{updateTransport(value(await piano.configure({hand_mode:chosen})))}finally{rateBusy=false;updateTransport(value(piano.get_transport()))}});$('export').onclick=exporting;$('diagnostics').onclick=safe(()=>diagnostics());$('cancelLoad').onclick=safe(()=>{if(loadJob)piano.cancel_job(loadJob.job_id);loadJob=null;loadEpoch++;$('loading').hidden=true;closeModal();ensureSheet()});
window.addEventListener('keydown',safe(async e=>{if(e.key==='Escape'){if(!$('modal').hidden)closeModal();else sidebar(false);return}if(!$('modal').hidden){if(e.key==='Tab'){const focus=Array.from($('modal').querySelectorAll('button,input,select')).filter(el=>!el.disabled&&!el.hidden&&el.tabIndex>=0&&el.getClientRects().length),at=focus.indexOf(document.activeElement);if((!e.shiftKey&&at===focus.length-1)||(e.shiftKey&&at===0)){e.preventDefault();focus[e.shiftKey?focus.length-1:0].focus()}}return}if(e.target.closest('input,select,textarea,button'))return;if(e.key===' '){e.preventDefault();await toggle()}else if(e.key==='Home'){e.preventDefault();updateTransport(value(await piano.seek(0)))}else if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();updateTransport(value(await piano.seek((transport?transport.position_s:0)+(e.key==='ArrowRight'?2:-2))))}else if(['PageDown','PageUp'].includes(e.key)){e.preventDefault();setFollow(false);$('sheet').scrollTop+=(e.key==='PageDown'?1:-1)*$('sheet').clientHeight*.85}}));window.addEventListener('resize',resize);
function frame(now){draw();if(measurement){const bin=Math.floor((now-measurement.started)/1000);if(bin>=0&&bin<measurement.frames.length){measurement.frames[bin]++;measurement.max_received_to_paint_ms=Math.max(measurement.max_received_to_paint_ms,performance.now()-received);}}metrics.frames++;metrics.windowFrames++;if(now-metrics.windowStart>=1000){metrics.windows.push({start:metrics.windowStart,end:now,frames:metrics.windowFrames});metrics.windowStart=now;metrics.windowFrames=0;if(metrics.windows.length>600)metrics.windows.shift()}requestAnimationFrame(frame)}
document.querySelectorAll('[role=radiogroup]').forEach(group=>wireChoice(group));
$('rollEffects').onclick=()=>{rollPainter.setEnabled(!rollPainter.enabled);$('rollEffects').setAttribute('aria-pressed',String(rollPainter.enabled));try{localStorage.setItem('rollEffects',rollPainter.enabled?'on':'off')}catch(_){}};
try{rollPainter.setEnabled(localStorage.getItem('rollEffects')!=='off');$('rollEffects').setAttribute('aria-pressed',String(rollPainter.enabled));setLift(Number(localStorage.getItem('strikeLift')||0));keyboardMode=localStorage.getItem('keyboardMode')==='full'?'full':'focused';const v=Number(localStorage.getItem('volume')||.65);if(Number.isFinite(v)&&v>=0&&v<=1){piano.set_volume(v);$('volume').value=v}}catch(_){}sidebar(innerWidth>1100);$('keyboard').hidden=false;buildKeyboard();updateTransport(value(piano.get_transport()));poll();requestAnimationFrame(frame);window.App={beginMeasure(seconds){measurement={started:performance.now(),seconds,max_received_to_paint_ms:0,frames:Array(Math.floor(seconds)).fill(0)}},get rollDiagnostics(){return rollPainter.inspect()},get measurement(){return measurement},get lastPaint(){return lastPaint},get document(){return doc},get transport(){return transport},get rows(){return rows},get notes(){return notes},get loadJob(){return loadJob},get sheetRequest(){return sheetRequest},get view(){return view},get follow(){return follow},get keyboardLayout(){return keyboardLayout},metrics,load,setView,setFollow,refresh,resize,draw};window.PIANOSCOPE_READY=false;if(window.INITIAL_SOURCE)safe(()=>load(window.INITIAL_SOURCE))();
})();
