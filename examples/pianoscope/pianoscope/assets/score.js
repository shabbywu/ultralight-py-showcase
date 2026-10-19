/* Native score pages and source-event mapping. Transport is the existing DAC
 * snapshot; this module never advances time or starts a second player. */
(() => {
'use strict';
const $=id=>document.getElementById(id),value=x=>Python.to_value(x);
const colors={left:'#80cfbf',right:'#efbd70',unassigned:'#b8b3c9'};
let active=false,display=null,applied=null,preview=null,pages=[],systems=[],epoch=0,scoreJob=null,exportJob=null,lastPoll=0,following=true,keyboard=true,zoom=1,exportFormat='pdf',warningOffset=0,warningCategory='all',lastDraw='',lastSystem=null,highlights=[],closedSettingsFocus=null,indexedNotes=null,noteIndex=new Map();
let failure=null,issueOffset=0,lastRequest=null;
function status(text,cancellable=false){$('scoreStatus').hidden=!text;$('scoreStatusText').textContent=text;$('cancelScoreJob').hidden=!cancellable}
function safe(action){return async(...args)=>{try{return await action(...args)}catch(e){status(String(e.message||e));$('notationError').textContent=String(e.message||e);return null}}}
function controls(){
 $('scoreControls').hidden=!active;$('viewRoll').classList.toggle('chosen',!active);$('viewScore').classList.toggle('chosen',active);
 $('viewRoll').setAttribute('aria-pressed',String(!active));$('viewScore').setAttribute('aria-pressed',String(active));
 $('shell').classList.toggle('score-mode',active);$('shell').classList.toggle('score-keyboard-hidden',active&&!keyboard);
 $('rollViewport').hidden=active;$('scoreViewport').hidden=!active;$('scoreEmpty').hidden=!!display;
 $('keyboardToggle').textContent=keyboard?'收起键盘':'显示键盘';$('autoFollow').checked=following;
 $('previewActions').hidden=!preview;$('applyNotation').disabled=!!scoreJob||!preview||preview.state==='stale'||!display||display.preview_id!==preview.preview_id;
 const exportable=!!applied&&applied.state==='applied';$('exportPDF').disabled=!exportable;$('exportXML').disabled=!exportable;
 $('previewSummary').title='声部是独立节奏线，一个声部可包含多个音的和弦，不等于同时按键数。';
 if(preview)$('previewSummary').textContent=`预览 · ${preview.measures} 小节 · ${preview.notes} 个音符`+(preview.profile===2?` · 已整理 ${preview.warnings_count} 个 · 待检查 ${preview.needs_review_count} 个 · 最多 ${Math.max(...Object.values(preview.voices))} 声部`:` · ${preview.warnings_count} 项量化提示`)+(preview.key_analysis?' · '+preview.key_analysis.key:'');
}
function setView(next){
 active=next==='score';
 if(active&&innerWidth<=850){keyboard=false;if(!lastSystem&&!$('analysis').hidden)$('analysisToggle').click()}
 controls();lastDraw='';PianoScope.draw();
 if(active&&!display&&!scoreJob)openSettings();
}
function suspendFollow(){following=false;$('autoFollow').checked=false}
function restoreFollow(){following=true;lastSystem=null;$('autoFollow').checked=true;lastDraw='';draw(PianoScope.transport)}
function currentAudible(g,t){
 const s=PianoScope.score,n=noteIndex.get(g.source_note_ids[0]);
 if(!n||!s||!t)return true;
 const track=s.tracks.find(track=>track.id===n.track_id);
 return !!track&&!track.muted&&(!s.tracks.some(track=>track.solo)||track.solo)&&(t.hand_mode==='both'||t.hand_mode===n.hand);
}
function rectWithin(point,b,slop=0){return point.x>=b[0]-slop&&point.x<=b[0]+b[2]+slop&&point.y>=b[1]-slop&&point.y<=b[1]+b[3]+slop}
function hit(system,clientX,clientY){
 const r=system.overlay.getBoundingClientRect(),scale=r.width/system.crop[2];
 const p={x:(clientX-r.left)/scale+system.crop[0],y:(clientY-r.top)/scale+system.crop[1]};
 const glyph=system.glyphs.find(g=>g.source_note_ids.length&&rectWithin(p,g.bbox,1/scale))||system.glyphs.find(g=>rectWithin(p,g.bbox,1/scale));
 if(glyph)return {time_s:glyph.seek_s,event_id:glyph.event_id};
 const measure=system.measures.find(m=>rectWithin(p,m.bbox));
 return measure?{time_s:measure.start_s,measure_id:measure.id}:null;
}
function paintBase(system){
 const dpr=window.CPU_RENDERER?1:Math.min(devicePixelRatio||1,2),width=system.crop[2]*system.scale;
 const w=Math.round(width*dpr),h=Math.round(system.crop[3]*system.scale*dpr);
 if(system.base.width===w&&system.base.height===h&&system.baseReady)return;
 for(const canvas of [system.base,system.overlay]){canvas.width=w;canvas.height=h}
 const ctx=system.base.getContext('2d'),scale=system.scale*dpr;ctx.setTransform(scale,0,0,scale,0,0);
 ctx.drawImage(system.image,system.crop[0]*system.imageScale,system.crop[1]*system.imageScale,system.crop[2]*system.imageScale,system.crop[3]*system.imageScale,0,0,system.crop[2],system.crop[3]);
 ctx.globalCompositeOperation='source-in';ctx.fillStyle='#e5e8d8';ctx.fillRect(0,0,system.crop[2],system.crop[3]);ctx.globalCompositeOperation='source-over';system.baseReady=true;
}
function resize(){
 if(!systems.length)return;
 const available=$('scoreViewport');
 for(const system of systems){
  const fitHeight=Math.max(0,available.clientHeight-24)/system.crop[3]*system.crop[2];
  const width=Math.max(650,Math.min(available.clientWidth-28,fitHeight))*zoom;
  system.scale=width/system.crop[2];system.node.style.width=width+'px';system.node.style.height=system.crop[3]*system.scale+'px';system.baseReady=false;
 }
 lastDraw='';draw(PianoScope.transport);
}
async function show(item){
 const token=++epoch;
 if(!item){display=null;pages=[];systems=[];$('scorePages').textContent='';controls();return}
 const prepared=[];
 for(let i=0;i<item.pages;i++){
  const page=value(piano.get_notation_page(item.notation_id,i));
  const image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('无法显示谱面，请重新生成。'));image.src=page.image_token});
  if(token!==epoch)return;prepared.push({page,image});
 }
 const fragment=document.createDocumentFragment(),newSystems=[];
 for(const {page,image} of prepared){
  for(let ri=0;ri<page.systems.length;ri++){
   const row=page.systems[ri],[x,y,w,h]=row.bbox,previous=page.systems[ri-1],next=page.systems[ri+1];
   const top=Math.max(page.page===0&&ri===0?y:0,y-Math.min(20,previous?Math.max(0,(y-previous.bbox[1]-previous.bbox[3])/2):20)),bottom=Math.min(page.height,y+h+Math.min(20,next?Math.max(0,(next.bbox[1]-y-h)/2):20));
   const crop=[Math.max(0,x-18),top,Math.min(page.width-x+18,w+36),bottom-top];
   const node=document.createElement('div');node.className='score-system';node.dataset.page=page.page;node.dataset.system=row.id;
   const base=document.createElement('canvas'),overlay=document.createElement('canvas');base.width=overlay.width=1;base.height=overlay.height=1;base.className='score-base';overlay.className='score-overlay';overlay.setAttribute('aria-label','点击音符或小节跳转');
   node.appendChild(base);node.appendChild(overlay);fragment.appendChild(node);
   const system={node,base,overlay,crop,image,imageScale:page.image_scale||2,page:page.page,id:row.id,glyphs:page.glyphs.filter(g=>g.system===row.id),measures:page.measures.filter(m=>m.system===row.id)};
   overlay.onclick=safe(async e=>{if(!display||display.state==='stale')return;const result=hit(system,e.clientX,e.clientY);if(result)await piano.seek(Math.min(PianoScope.score.duration_s,Math.max(0,result.time_s)))});
   newSystems.push(system);
  }
 }
 if(token!==epoch)return;
 display=item;pages=prepared.map(p=>p.page);systems=newSystems;lastSystem=null;$('scorePages').textContent='';$('scorePages').appendChild(fragment);controls();resize();
}
function draw(transport){
 if(!active||!transport||!display||!systems.length)return;
 const valid=display.state!=='stale'&&display.score_id===transport.score_id;
 if(indexedNotes!==PianoScope.notes){indexedNotes=PianoScope.notes;noteIndex=new Map(indexedNotes.map(n=>[n.id,n]))}
 const position=transport.position_s; // Actual DAC snapshot, no local time integration.
 const signature=[transport.seq,display.state,following,zoom].join(':');if(signature===lastDraw)return;lastDraw=signature;
 const ids=new Set(valid&&transport.phase==='playing'&&transport.volume>0?transport.active_note_ids:[]);highlights=[];
 const current=valid?systems.find(s=>s.measures.some(m=>m.start_s<=position&&(position<m.end_s||position===transport.duration_s&&position===m.end_s))):null;
 if(following&&current&&lastSystem!==current){lastSystem=current;$('scoreViewport').scrollTop=current.node.offsetTop-8}
 const vr=$('scoreViewport').getBoundingClientRect();
 for(const system of systems){
  const sr=system.node.getBoundingClientRect();
  if(sr.bottom<vr.top||sr.top>vr.bottom){if(system.baseReady){system.base.width=system.overlay.width=1;system.base.height=system.overlay.height=1;system.baseReady=false;system.painted=false}continue}paintBase(system);system.painted=true;
  const ctx=system.overlay.getContext('2d'),scale=system.overlay.width/system.crop[2];ctx.setTransform(scale,0,0,scale,0,0);ctx.clearRect(0,0,system.crop[2],system.crop[3]);
  ctx.translate(-system.crop[0],-system.crop[1]);
  if(!valid)continue;
  for(const glyph of system.glyphs){
   if(glyph.pitch===null)continue;
   const [x,y,w,h]=glyph.bbox,canHear=currentAudible(glyph,transport);
   if(!canHear){ctx.fillStyle='#182d2c';ctx.globalAlpha=.7;ctx.fillRect(x-1,y-1,w+2,h+2);ctx.globalAlpha=1;continue}
   const spans=glyph.source_display_spans;
   const pressed=spans.some(span=>ids.has(span.source_note_id)&&span.start_s<=position&&position<span.end_s);
   if(pressed){
    ctx.fillStyle=colors[glyph.hand];ctx.beginPath();ctx.ellipse(x+w/2,y+h/2,w/2+1,h/2+1,-.12,0,Math.PI*2);ctx.fill();highlights.push(glyph.event_id);
   }else if(transport.phase==='playing'&&transport.volume>0&&glyph.source_note_ids.some(id=>{
    const n=noteIndex.get(id);return n&&n.key_off_s<=position&&position<n.sustain_end_s&&spans.some(s=>s.end_s===n.key_off_s);
   })){
    ctx.strokeStyle=colors[glyph.hand];ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(x+w/2,y+h/2,w/2+2,h/2+2,0,0,Math.PI*2);ctx.stroke();
   }
  }
  for(const measure of system.measures){
   if(measure.start_s<=position&&(position<measure.end_s||position===transport.duration_s&&position===measure.end_s)){
    $('scorePosition').textContent='第 '+measure.number+' 小节'+(transport.notation_position&&transport.notation_position.notation_id===display.notation_id?' · '+transport.notation_position.beat.toFixed(1)+' 拍':'');
    let x=measure.bbox[0],anchors=measure.anchors;
    for(let i=0;i<anchors.length-1;i++)if(anchors[i].time_s<=position&&position<=anchors[i+1].time_s){const a=anchors[i],b=anchors[i+1];x=a.x+(b.x-a.x)*(position-a.time_s)/Math.max(1e-12,b.time_s-a.time_s);break}
    ctx.strokeStyle='#efbd70';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,measure.bbox[1]);ctx.lineTo(x,measure.bbox[1]+measure.bbox[3]);ctx.stroke();
   }
  }
 }

}
function refresh(){
 const next=value(piano.get_notation());applied=next;
 if(preview){const current=value(piano.get_notation_preview(preview.preview_id));preview=current||{...preview,state:'stale'};display=preview}
 else if(next){if(!display||display.notation_id!==next.notation_id)show(next).catch(e=>status(String(e)));else display=next}
 else if(display){display={...display,state:'stale'}}
 if(display&&display.state==='stale')status('谱面已过期，请重新生成');
 controls();lastDraw='';
}
function options(){
 const tracks=[],staff_tracks={};document.querySelectorAll('.notation-track').forEach(row=>{if(row.querySelector('input').checked)tracks.push(row.dataset.track);staff_tracks[row.dataset.track]=Number(row.querySelector('select').value)});
 if(!tracks.length)throw Error('请至少选择一条制谱轨道。');
 return {rhythm:$('rhythm').value,staff_mode:$('staffMode').value,split:Number($('staffSplit').value),tracks,staff_tracks,meter:$('notationMeter').value,key:$('notationKey').value,clef_mode:$('clefMode').value,pickup:$('pickup').value,confirm_defaults:$('confirmDefaults').checked,profile:$('rhythm').value==='auto'?2:1};
}
function warningPage(){
 if(!display)return;
 const result=value(piano.get_notation_warnings(display.notation_id,warningOffset,20,warningCategory)),root=$('notationWarnings');root.textContent='';
 const filter=document.createElement('select');filter.setAttribute('aria-label','整理提示分类');for(const [value,text] of [['all','全部整理'],['review','待检查'],['short_fill','短音补足']]){const o=document.createElement('option');o.value=value;o.textContent=text;filter.appendChild(o)}filter.value=warningCategory;filter.onchange=()=>{warningCategory=filter.value;warningOffset=0;warningPage()};root.appendChild(filter);
 const title=document.createElement('p');title.textContent=`整理提示 ${Math.min(warningOffset+1,result.total)}–${Math.min(warningOffset+20,result.total)} / ${result.total}`;root.appendChild(title);
 for(const warning of result.warnings){const b=document.createElement('button');b.className='warning-link';b.textContent=`第 ${warning.measure} 小节 · ${{short_fill:'短音补足',release_recovered:'整理音长',duration_aligned:'对齐时值',quantized:'对齐节奏'}[warning.kind]||'整理节奏'}${warning.normalization&&warning.normalization.needs_review?'（请检查）':''} · 起点 ${fraction(warning.start_delta)} 拍，松键 ${fraction(warning.end_delta)} 拍`;b.onclick=()=>{$('notationSettings').hidden=true;setView('score');suspendFollow();locateMeasure(warning.measure)};root.appendChild(b)}
 for(const [text,offset] of [['上一组',warningOffset-20],['下一组',warningOffset+20]]){const b=document.createElement('button');b.textContent=text;b.disabled=offset<0||offset>=result.total;b.onclick=()=>{warningOffset=offset;warningPage()};root.appendChild(b)}
}
function fraction(v){return (v[0]>0?'+':'')+(v[1]===1?v[0]:v[0]+'/'+v[1])}
function locateMeasure(number){const system=systems.find(s=>s.measures.some(m=>m.number===number));if(system){$('scoreViewport').scrollTop=system.node.offsetTop;lastSystem=null}}
function openSettings(){
 const score=PianoScope.score;if(!score)return;
 closedSettingsFocus=document.activeElement;if(innerWidth<=1100&&!$('sidebar').hidden)$('sidebarClose').click();$('notationError').textContent='';$('notationSettings').hidden=false;
 const old=lastRequest&&lastRequest.score_id===score.score_id?lastRequest.options:display&&display.score_id===score.score_id&&display.options;
 if(old){$('staffMode').value=old.staff_mode;$('staffSplit').value=old.split;$('rhythm').value=old.rhythm;$('notationMeter').value=old.meter;$('notationKey').value=old.key;$('clefMode').value=old.clef_mode||(old.profile===2?'auto_octaves':'standard');$('pickup').value=old.pickup;$('confirmDefaults').checked=old.confirm_defaults}
 if(!old){$('staffMode').value='hands';$('staffSplit').value=60;$('rhythm').value='auto';$('notationMeter').value='source';$('notationKey').value=score.key_map[0].source==='default'?'auto':'source';$('clefMode').value='auto_octaves';$('pickup').value='0';$('confirmDefaults').checked=false}
 const root=$('notationTracks');root.textContent='';
 for(const track of score.tracks){const row=document.createElement('div');row.className='notation-track';row.dataset.track=track.id;const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=!old||old.tracks.includes(track.id);label.appendChild(input);label.appendChild(document.createTextNode(' '+track.name));row.appendChild(label);const select=document.createElement('select');select.setAttribute('aria-label',track.name+'谱表');for(const [v,t] of [[1,'上谱表'],[2,'下谱表']]){const option=document.createElement('option');option.value=v;option.textContent=t;select.appendChild(option)}select.value=old&&old.staff_tracks[track.id]||((PianoScope.notes.filter(n=>n.track_id===track.id&&n.hand==='left').length>PianoScope.notes.filter(n=>n.track_id===track.id&&n.hand==='right').length)?2:1);row.appendChild(select);input.onchange=keySuggestion;root.appendChild(row)}
 const meter=score.meter_map[0],key=score.key_map[0],tempo=score.tempo_map[0];
 $('notationSources').textContent=`拍号：${meter.numerator}/${meter.denominator}（${meter.source==='default'?'默认':'原曲'}）；调号：${key.source==='default'?'无升降调号＋临时记号（默认）':key.key+'（原曲）'}；速度：♩ = ${Math.round(tempo.quarter_bpm)}（${tempo.source==='default'?'默认':'原曲'}）。弱起 0 表示无弱起。`;
 $('notationAssignment').textContent=`未分配手别：${PianoScope.notes.filter(n=>n.hand==='unassigned').length} 个音符。未分配音符按分界音建议谱表；谱表分配不改变左右手。`;
 syncStaffFields();keySuggestion();renderIssues();$('notationSettings').querySelector('.notation-scroll').scrollTop=0;warningOffset=0;warningCategory=display&&display.profile===2?'review':'all';if(display&&display.score_id===score.score_id)warningPage();else $('notationWarnings').textContent='';$('closeNotation').focus();
}
function keySuggestion(){
 const node=$('keySuggestion');node.hidden=$('notationKey').value!=='auto';if(node.hidden)return;
 const tracks=Array.from(document.querySelectorAll('.notation-track')).filter(r=>r.querySelector('input').checked).map(r=>r.dataset.track);
 if(!tracks.length){node.textContent='请选择需要制谱的轨道。';return}
 const result=value(piano.get_key_suggestion(tracks)),name=k=>k.endsWith('m')?k.slice(0,-1)+' 小调':k+' 大调';
 node.textContent='建议 '+name(result.key)+'，关系调为 '+name(result.relative_key)+'；可手动改选。调号是全曲音高分布的建议，不能保证还原原谱。';
}
$('notationKey').onchange=safe(keySuggestion);
function syncStaffFields(){
 const mode=$('staffMode').value,unassigned=PianoScope.notes.some(n=>n.hand==='unassigned');
 $('staffSplitField').hidden=!(mode==='pitch'||mode==='hands'&&unassigned);
 document.querySelectorAll('.notation-track select').forEach(select=>select.hidden=mode!=='tracks');
}
function renderIssues(){
 const root=$('notationIssues');root.textContent='';if(!failure||!PianoScope.score||failure.score_id!==PianoScope.score.score_id)return;
 const error=failure.error,issues=error.issues||[];$('notationError').textContent=error.message;
 if(!issues.length)return;
 const hint=document.createElement('p');hint.className='hint';hint.textContent=lastRequest&&lastRequest.options.profile===2?'点击问题可暂停并跳到原曲位置。可检查上下谱的分配或选择需要的轨道；重叠音符和复杂节奏仍可能超出可完整表示的范围。':'点击问题可暂停并跳到原曲位置。可尝试“自动整理”，或选择含八分三连音。严格模式不会补足零时值或整理超出容差的节奏。';root.appendChild(hint);
 const trackName=id=>{const t=PianoScope.score.tracks.find(t=>t.id===id);return t?t.name:id};
 const list=document.createElement('div');list.className='issue-list';root.appendChild(list);
 for(const issue of issues.slice(issueOffset,issueOffset+20)){
  const b=document.createElement('button');const id=issue.source_note_id||(issue.source_note_ids||[])[0],note=PianoScope.notes.find(n=>n.id===id);
  b.textContent=`第 ${issue.measure} 小节 · ${issue.track_id?trackName(issue.track_id)+' · ':''}${note?noteName(note.pitch)+' · ':''}${issue.reason} · ${id||''}`;
  b.title=issue.source_event?`${issue.source_event} · tick ${issue.start_tick}–${issue.key_off_tick}`:'';
  b.onclick=safe(async()=>{if(!failure||failure.score_id!==PianoScope.score.score_id)throw Error('曲目已改变，请重新生成');if(!note)return;await piano.pause();await piano.seek(note.start_s);closeSettings();setView('roll');PianoScope.draw()});list.appendChild(b);
 }
 const nav=document.createElement('div');nav.className='issue-navigation';root.appendChild(nav);const count=document.createElement('span');count.textContent=`问题 ${issueOffset+1}–${Math.min(issueOffset+20,issues.length)} / ${issues.length}`;nav.appendChild(count);
 for(const [label,offset] of [['上一组',issueOffset-20],['下一组',issueOffset+20]]){const b=document.createElement('button');b.textContent=label;b.disabled=offset<0||offset>=issues.length;b.onclick=()=>{issueOffset=offset;renderIssues()};nav.appendChild(b)}
}
$('staffMode').onchange=syncStaffFields;
function closeSettings(){$('notationSettings').hidden=true;if(closedSettingsFocus&&closedSettingsFocus.offsetParent!==null)closedSettingsFocus.focus();else $('sidebarToggle').focus()}
async function generate(){
 const request=options();lastRequest={score_id:PianoScope.score.score_id,options:request};failure=null;renderIssues();$('notationError').textContent='';const result=value(piano.begin_notation(request));scoreJob=result;closeSettings();status('正在生成五线谱',true);
}
async function apply(){
 if(!preview)return;
 const result=value(piano.apply_notation(preview.preview_id,preview.source_revision));applied=result;preview=null;display=result;status('');controls();lastDraw='';
}
async function discard(){preview=null;await show(applied);status('');controls()}
function exportCheck(format){
 refresh();if(!applied||applied.state!=='applied'){status('谱面已过期，请重新生成');return}
 exportFormat=format;$('exportTitle').textContent=$('saveNotation').textContent='导出 '+(format==='pdf'?'PDF':'MusicXML');
 $('exportSummary').textContent=`${applied.title} · ${applied.tracks} 条制谱轨道 · ${applied.notes} 个音符 · ${applied.measures} 小节`+(format==='pdf'?` · A4 纵向 · ${applied.pages} 页`:'')+'。使用已应用的谱面与原曲速度。'+(applied.profile===2?`节奏已自动整理，短音补足 ${applied.normalization_counts.short_fill||0} 个。`:'');
 $('exportCheck').hidden=false;$('saveNotation').focus();
}
async function save(){
 const snapshot=applied;if(!snapshot)return;const format=exportFormat;
 const token=value(await piano.choose_score_export(format));if(!token)return;
 exportJob=value(piano.begin_score_export(snapshot.notation_id,format,token.target_token));$('exportCheck').hidden=true;status('正在导出',true);
}
function poll(){
 if(performance.now()-lastPoll<150)return;lastPoll=performance.now();
 try{
  if(scoreJob){const job=value(piano.get_notation_job(scoreJob.job_id));if(job.done){scoreJob=null;if(job.error){const text=job.error.message;failure={score_id:lastRequest&&lastRequest.score_id,error:job.error};issueOffset=0;status(text);if(PianoScope.score&&failure.score_id===PianoScope.score.score_id)openSettings()}else if(job.phase==='stale'){status('谱面已过期，请重新生成')}else if(!job.cancelled&&job.result){preview=job.result;show(preview).then(()=>{if(!active&&innerWidth<=850)keyboard=false;active=true;controls();status('');resize()}).catch(e=>status(String(e)))}else status('');controls()}}
  if(exportJob){const job=value(piano.get_notation_job(exportJob.job_id));if(job.done){exportJob=null;status(job.error?'导出失败，请重试。'+job.error.message:job.cancelled?'':`已导出 ${job.result.filename}`);controls()}}
 }catch(e){status(String(e.message||e))}
}
$('viewRoll').onclick=()=>setView('roll');$('viewScore').onclick=()=>setView('score');
$('scoreSettings').onclick=$('scoreStart').onclick=$('reviewNotation').onclick=openSettings;
$('closeNotation').onclick=$('dismissNotation').onclick=closeSettings;
$('generateNotation').onclick=safe(generate);$('applyNotation').onclick=safe(apply);$('discardNotation').onclick=safe(discard);
$('exportPDF').onclick=()=>exportCheck('pdf');$('exportXML').onclick=()=>exportCheck('musicxml');$('saveNotation').onclick=safe(save);
$('closeExport').onclick=$('dismissExport').onclick=()=>{$('exportCheck').hidden=true;$('sidebarToggle').focus()};
$('autoFollow').onchange=()=>{$('autoFollow').checked?restoreFollow():suspendFollow()};$('backToScore').onclick=restoreFollow;
$('keyboardToggle').onclick=()=>{keyboard=!keyboard;controls();resize()};$('scoreZoom').onchange=()=>{zoom=Number($('scoreZoom').value);resize();lastSystem=null};
$('cancelScoreJob').onclick=safe(()=>{for(const job of [scoreJob,exportJob])if(job)piano.cancel_notation_job(job.job_id);scoreJob=null;exportJob=null;status('');controls()});
$('scoreViewport').addEventListener('scroll',()=>{lastDraw='';draw(PianoScope.transport)},{passive:true});
$('scoreViewport').addEventListener('wheel',suspendFollow,{passive:true});$('scoreViewport').addEventListener('touchstart',suspendFollow,{passive:true});
$('scoreViewport').addEventListener('mousedown',e=>{const r=$('scoreViewport').getBoundingClientRect();if(e.clientX>=r.right-18||e.clientY>=r.bottom-18)suspendFollow()});
$('scoreViewport').addEventListener('keydown',e=>{if(['PageUp','PageDown','Home','End','ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(e.key)){suspendFollow();e.stopPropagation()}});
document.addEventListener('keydown',e=>{
 const modal=!$('notationSettings').hidden?$('notationSettings'):!$('exportCheck').hidden?$('exportCheck'):null;if(!modal)return;
 if(e.key==='Escape'){modal.hidden=true;$('sidebarToggle').focus();e.preventDefault();e.stopImmediatePropagation()}
 if(e.key==='Tab'){const list=Array.from(modal.querySelectorAll('button:not(:disabled),input,select')).filter(x=>x.offsetParent!==null);const a=list[0],b=list[list.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();b.focus()}else if(!e.shiftKey&&document.activeElement===b){e.preventDefault();a.focus()}}
 if(e.code==='Space'||e.key==='Home'||e.key.startsWith('Arrow'))e.stopImmediatePropagation();
},true);
window.addEventListener('resize',resize);if(window.ResizeObserver)new ResizeObserver(resize).observe($('scoreViewport'));
window.ScoreView={setView,refresh,show,generate,apply,discard,draw,restoreFollow,suspendFollow,hit,resize,openSettings,exportCheck,
 get active(){return active},get display(){return display},get preview(){return preview},get applied(){return applied},get systems(){return systems},get highlights(){return highlights},get following(){return following},get job(){return scoreJob},get exportJob(){return exportJob},get drawSignature(){return lastDraw}};
setInterval(poll,50);controls();
})();
