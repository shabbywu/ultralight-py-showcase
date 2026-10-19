(() => {
'use strict';
const $=id=>document.getElementById(id),value=x=>Python.to_value(x),colors={left:'#80cfbf',right:'#efbd70',unassigned:'#b8b3c9'},handLabel={left:'左手',right:'右手',unassigned:'未分配'};
let score=null,notes=[],splitNotes=new Set(),transport=null,receivedAt=0,layout=null,mode='focused',showNames=true,overview=null,job=null,viewEpoch=0,analysisOpen=false,analysisSeq=0,analysisFrame=null,previewId=null,previewNotes=null,selected=new Set(),noteRects=[],drag=null,waveDrag=null,loopPreview=null,interacting=false,lastPoll=0,lastJob=0,refreshing=false,hiddenHint=false,starts=[],prefixEnd=[],prefixSustain=[],lastSignature='',fpsFrames=0,fpsAt=performance.now(),fps=0,analysisPoll=0,waveSignature='';
let strikeLift=0,strikeDragging=false;
try{const saved=Number(localStorage.getItem('strikeLift'));if(Number.isFinite(saved))strikeLift=Math.max(0,Math.min(60,saved))}catch(_){}
const metrics={frames:0,maxAlignmentError:0,modeSwitches:0};
try{mode=localStorage.getItem('keyboardMode')||'focused';let v=localStorage.getItem('volume');if(v!==null){piano.set_volume(Number(v));$('volume').value=Number(v)*100;$('volumeText').textContent=Math.round(Number(v)*100)+'%'}}catch(_){}
$('motion').checked=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function message(text){$('message').textContent=text||'';$('message').hidden=!text}
function safe(action){return async(...args)=>{message('');try{return await action(...args)}catch(e){message(String(e.message||e));return null}}}
function timeLabel(seconds){seconds=Math.max(0,Math.floor(seconds||0));return String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0')}
function setupCanvas(id){const c=$(id),r=c.getBoundingClientRect(),dpr=window.CPU_RENDERER?1:Math.min(window.devicePixelRatio||1,1.5),w=Math.max(1,r.width),h=Math.max(1,r.height);if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr)}const ctx=c.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);return {c,ctx,w,h}}
function positionStrikeLine(height){
 const strike=$('strikeLine');if(!strike)return;
 const top=(-3-height*strikeLift/100)+'px';if(strike.style.top!==top)strike.style.top=top;
 $('keys').classList.toggle('raised-strike',strikeLift>0);
 strike.classList.toggle('label-below',height*(1-strikeLift/100)<44);
}
function setStrikeLift(next){
 if(!Number.isFinite(next))return;strikeLift=Math.max(0,Math.min(60,Math.round(next)));
 $('strikePosition').value=strikeLift;$('strikePositionText').textContent=strikeLift+'%';
 try{localStorage.setItem('strikeLift',String(strikeLift))}catch(_){}
 positionStrikeLine($('roll').getBoundingClientRect().height);draw();
}
function buildKeyboard(){
 const root=$('keys');layout=new KeyboardLayout(score?score.used_pitches:[],mode,root.clientWidth);root.textContent='';
 layout.rects.forEach(k=>{const b=document.createElement('button');b.className='key '+(k.is_black?'black':'white')+(!k.is_used?' unused':'');b.style.left=k.x+'px';b.style.width=k.width+'px';b.dataset.midi=k.midi;b.setAttribute('aria-label',noteName(k.midi)+'，MIDI '+k.midi);b.title=noteName(k.midi)+' · MIDI '+k.midi;
 const name=document.createElement('span');name.className='keyname';name.textContent=showNames&&(mode!=='full'||k.midi%12===0||k.midi===21)?noteName(k.midi):'';b.appendChild(name);
 if(showNames&&mode!=='full'&&!k.is_black){const sol=document.createElement('span');sol.className='solfege';sol.textContent=Solfege[k.midi%12];b.appendChild(sol)}
 const hand=document.createElement('span');hand.className='hands';b.appendChild(hand);
 b.onclick=()=>{$('picked').textContent=noteName(k.midi)+' · MIDI '+k.midi+' · '+(440*2**((k.midi-69)/12)).toFixed(1)+' Hz'};root.appendChild(b)});
 const strike=document.createElement('div');strike.id='strikeLine';strike.setAttribute('role','img');strike.setAttribute('aria-label','现在，按键时刻。音符下缘到线时按下，上缘到线时松开。');
 const hits=document.createElement('span');hits.className='strike-hits';strike.appendChild(hits);
 const strikeLabel=document.createElement('span');strikeLabel.className='strike-label';strikeLabel.textContent='现在 · 按下';strikeLabel.title='上下拖动可调整位置；音符下缘到线时按下，上缘到线时松开。';strikeLabel.onmousedown=e=>{if(e.button!==0)return;strikeDragging=true;e.preventDefault();e.stopPropagation()};strike.appendChild(strikeLabel);root.appendChild(strike);positionStrikeLine($('roll').getBoundingClientRect().height);
 const central=$('central');central.textContent='';const c=layout.byMidi[60];if(c){const label=document.createElement('span');label.textContent='中央 C · C4';label.style.left=c.center+'px';central.appendChild(label)}else central.textContent='中央 C 在范围'+(layout.low>60?'左':'右')+'侧';
 $('full').classList.toggle('chosen',mode==='full');$('focused').classList.toggle('chosen',mode!=='full');$('full').setAttribute('aria-pressed',String(mode==='full'));$('focused').setAttribute('aria-pressed',String(mode!=='full'));lastSignature='';
}
function setMode(next){mode=next;metrics.modeSwitches++;try{localStorage.setItem('keyboardMode',mode)}catch(_){}buildKeyboard();draw()}
function indexNotes(){starts=notes.map(n=>n.start_s);let key=0,sustain=0;prefixEnd=notes.map(n=>key=Math.max(key,n.key_off_s));prefixSustain=notes.map(n=>sustain=Math.max(sustain,n.sustain_end_s));splitNotes.clear();
 const groups={};for(const n of notes){const key=n.pitch+':'+n.hand;if(!groups[key])groups[key]={starts:[],ends:[]};const g=groups[key];g.starts.push(n.start_s);g.ends.push(Math.max(n.key_off_s,g.ends.length?g.ends[g.ends.length-1]:0))}
 for(const n of notes){if(n.hand==='unassigned')continue;const g=groups[n.pitch+':'+(n.hand==='left'?'right':'left')];if(g){const i=lowerBound(g.starts,n.key_off_s)-1;if(i>=0&&g.ends[i]>n.start_s)splitNotes.add(n.id)}}
}
function lowerBound(arr,v,upper=false){let a=0,b=arr.length;while(a<b){let m=(a+b)>>1;if(upper?arr[m]<=v:arr[m]<v)a=m+1;else b=m}return a;}
function windowNotes(t,future=0,sustain=false){return (previewNotes||notes).slice(lowerBound(sustain?prefixSustain:prefixEnd,t),lowerBound(starts,t+future,true));}
function sourceTime(){
 if(!transport)return 0;if(waveDrag)return waveDrag.position;
 let t=transport.position_s;
 if(transport.phase==='playing'&&!transport.tail_active){const age=performance.now()-receivedAt;if(age<=250){t+=age/1000*transport.rate;const l=transport.loop;if(l.enabled&&t>=l.b_s)t=l.a_s+(t-l.a_s)%(l.b_s-l.a_s)}}
 return Math.min(transport.duration_s,t);
}
function audible(n){if(!transport||!score)return false;if(transport.hand_mode!=='both'&&transport.hand_mode!==n.hand)return false;const track=score.tracks.find(t=>t.id===n.track_id);return track&&!track.muted&&(!score.tracks.some(t=>t.solo)||track.solo)}
function updateTransport(t){
 if(transport&&t.seq<transport.seq)return;
 if(transport&&transport.clock_epoch!==t.clock_epoch)analysisFrame=null;
 transport=t;receivedAt=performance.now();$('play').textContent=t.phase==='playing'?'Ⅱ':'▶';$('play').setAttribute('aria-label',t.phase==='playing'?'暂停':'播放');$('play').title=t.phase==='playing'?'暂停':'播放';
 const busy=!!job||!score;['play','stop','loop','settings','tracks'].forEach(id=>$(id).disabled=busy);document.querySelectorAll('[data-rate],[data-hand]').forEach(b=>b.disabled=busy);
 $('deviceError').hidden=t.audio_ready||!score;
 document.querySelectorAll('[data-rate]').forEach(b=>b.classList.toggle('chosen',Number(b.dataset.rate)===t.rate));document.querySelectorAll('[data-hand]').forEach(b=>b.classList.toggle('chosen',b.dataset.hand===t.hand_mode));
 $('loop').setAttribute('aria-pressed',String(t.loop.enabled));$('loopInputs').hidden=!t.loop.enabled;
 if(!interacting&&document.activeElement!==$('loopA')&&document.activeElement!==$('loopB')){$('loopA').value=t.loop.a_s.toFixed(2);$('loopB').value=t.loop.b_s.toFixed(2)}
 $('unassignedHint').hidden=!t.unassigned_notes||hiddenHint;$('currentLabel').textContent=t.phase==='paused'?'暂停位置':'当前音符';
}
async function refresh(){
 const epoch=++viewEpoch;const s=value(piano.get_score());if(!s)return;
 const all=[];for(let offset=0;offset<s.notes_count;offset+=2000){const page=value(await piano.get_notes(offset,2000,null));if(epoch!==viewEpoch||page.score_id!==s.score_id||page.revision!==s.revision)return;all.push(...page.notes)}
 const o=value(await piano.get_overview(1400));if(epoch!==viewEpoch||!o||o.score_id!==s.score_id||o.revision!==s.revision)return;
 score=s;notes=all;indexNotes();overview=o;previewId=null;previewNotes=null;analysisFrame=null;selected=new Set();hiddenHint=false;lastSignature='';
 $('title').textContent=s.title;$('meta').textContent=s.tracks.length+' 轨道 · '+s.notes_count+' 个音符 · '+timeLabel(s.duration_s);$('range').textContent=noteName(s.pitch_min)+' — '+noteName(s.pitch_max);$('endtime').textContent=timeLabel(s.duration_s);
 $('warnings').textContent=s.warnings.join('；');document.querySelectorAll('[data-demo]').forEach(b=>b.classList.toggle('active',(b.dataset.demo==='demo:first-light'&&s.title==='初光')||(b.dataset.demo==='demo:harmonics'&&s.title==='泛音练习')));
 renderLibrary();$('external').textContent='';if(!['初光','泛音练习'].includes(s.title)&&!library?.songs.some(item=>item.file_token===s.source_token)){const b=document.createElement('button');b.className='demo active';b.textContent=s.title;$('external').appendChild(b)}
 buildKeyboard();renderTracks();updateSelection();updateTransport(value(piano.get_transport()));if(window.ScoreView)ScoreView.refresh();
}
function startJob(j){job=j;$('loading').hidden=false;message('');updateTransport(value(piano.get_transport()));return j}
async function load(source){return startJob(value(piano.begin_load(source)))}
async function waitJob(j){startJob(j);while((job&&job.job_id===j.job_id)||refreshing){await new Promise(r=>setTimeout(r,60))}if(!score)throw Error('曲目未准备成功');return score}
async function configure(rate=transport.rate,hand=transport.hand_mode,tracks=score.tracks){startJob(value(piano.configure(rate,tracks,hand)))}
async function togglePlay(){const t=value(await (transport&&transport.phase==='playing'?piano.pause():piano.play()));updateTransport(t)}
async function poll(){
 const now=performance.now();if(refreshing)return;
 try{
  if(job&&now-lastJob>=200){lastJob=now;const state=value(piano.get_job(job.job_id));$('loadLabel').textContent=state.phase==='loading'?'正在读取曲目':'正在生成钢琴声音';$('progress').value=state.progress;$('percent').textContent=Math.round(state.progress*100)+'%';if(state.done){job=null;$('loading').hidden=true;if(state.error)message(state.error.message);if(!state.cancelled&&!state.error){refreshing=true;try{await refresh()}finally{refreshing=false}}}}
  if(now-lastPoll>=(transport&&transport.phase==='playing'?50:500)){lastPoll=now;updateTransport(value(piano.get_transport()))}
  if(analysisOpen&&now-analysisPoll>=50){analysisPoll=now;const frame=value(piano.get_analysis(analysisSeq));if(frame&&score&&frame.score_id===score.score_id&&frame.revision===score.revision&&frame.generation===transport.generation&&frame.clock_epoch===transport.clock_epoch){analysisFrame=frame;analysisSeq=frame.seq}}
 }catch(e){message(String(e.message||e))}
}
function drawRoll(t){
 const {ctx,w,h}=setupCanvas('roll');if(!layout)return;
 const gradient=ctx.createLinearGradient(0,0,0,h);gradient.addColorStop(0,'#0d1c1f');gradient.addColorStop(1,'#19342e');ctx.fillStyle=window.CPU_RENDERER?'#102421':gradient;ctx.fillRect(0,0,w,h);
 ctx.lineWidth=1;
 layout.rects.filter(k=>!k.is_black).forEach(k=>{ctx.strokeStyle=k.midi%12===0?'#365347':'#223a34';ctx.beginPath();ctx.moveTo(k.x+.5,0);ctx.lineTo(k.x+.5,h);ctx.stroke()});
 const pps=90,strike=h*(1-strikeLift/100),history=(h-strike)/pps,drawNotes=windowNotes(t-history,h/pps);noteRects=[];positionStrikeLine(h);
 // Sorted start times bound future work; past long notes still retain their outlines.
 for(const n of drawNotes){const k=layout.byMidi[n.pitch];if(!k)continue;const r=layout.noteRect(n,strike,t,pps);if(r.y>h||r.bottom<0)continue;
  const canHear=audible(n);ctx.globalAlpha=(canHear?.42+n.velocity/127*.5:.17)*(n.key_off_s<t?.35:1);ctx.fillStyle=colors[n.hand];ctx.strokeStyle=colors[n.hand];ctx.lineWidth=selected.has(n.id)?2.5:1;
  if($('motion').checked){if(n.start_s>t+2||n.key_off_s<t)continue;r.y=20+(Math.floor(n.start_s*2)%4)*28;r.height=Math.max(6,Math.min(26,(n.key_off_s-n.start_s)*20))}
  ctx.save();if(splitNotes.has(n.id)){ctx.beginPath();ctx.rect(n.hand==='left'?r.x:k.center,0,r.width/2,h);ctx.clip()}
  const active=transport&&transport.phase==='playing'&&n.start_s<=t&&t<n.key_off_s&&canHear;
  if(active){ctx.shadowColor=colors[n.hand];ctx.shadowBlur=window.CPU_RENDERER?0:5}
  if(transport&&transport.phase==='paused'&&n.start_s<=t&&t<n.key_off_s){ctx.strokeRect(r.x+.5,r.y,r.width-1,r.height)}else{ctx.fillRect(r.x,r.y,r.width,r.height)}
  ctx.shadowBlur=0;
  if(selected.has(n.id)){ctx.strokeStyle='#fff8df';ctx.strokeRect(r.x-2,r.y-2,r.width+4,r.height+4)}
  if(r.width>19&&r.height>20){ctx.fillStyle='#15372c';ctx.font='10px sans-serif';ctx.textAlign='center';ctx.fillText(n.hand==='left'?'L':n.hand==='right'?'R':'—',k.center,Math.max(14,r.y+14))}
  ctx.restore();noteRects.push({...r,id:n.id,pitch:n.pitch});
 }
 ctx.globalAlpha=1;
 if(drag){ctx.fillStyle='#80cfbf22';ctx.strokeStyle='#80cfbf';ctx.fillRect(drag.x,drag.y,drag.endX-drag.x,drag.endY-drag.y);ctx.strokeRect(drag.x,drag.y,drag.endX-drag.x,drag.endY-drag.y)}
}
function updateKeys(t){
 const active=transport&&transport.phase==='playing'?windowNotes(t).filter(n=>audible(n)&&n.start_s<=t&&t<n.key_off_s):[];
 const sustained=transport&&transport.phase==='playing'?windowNotes(t,0,true).filter(n=>audible(n)&&n.key_off_s<=t&&t<n.sustain_end_s):[];
 const signature=active.map(n=>n.id).join(',')+'|'+sustained.map(n=>n.id).join(',')+'|'+(transport?transport.phase:'');if(signature===lastSignature)return;lastSignature=signature;
 const hits=$('strikeLine').querySelector('.strike-hits');hits.textContent='';
 for(const pitch of new Set(active.map(n=>n.pitch))){const k=layout.byMidi[pitch];if(!k)continue;const hands=new Set(active.filter(n=>n.pitch===pitch).map(n=>n.hand));const mark=document.createElement('span');mark.className='strike-hit '+(hands.has('left')&&hands.has('right')?'both':Array.from(hands)[0]);mark.dataset.midi=pitch;mark.style.left=k.center+'px';mark.style.width=Math.min(18,k.width*.8)+'px';hits.appendChild(mark)}
 document.querySelectorAll('.key').forEach(b=>{b.classList.remove('key-left','key-right','key-unassigned','key-both');b.style.outline='';const a=active.filter(n=>n.pitch===Number(b.dataset.midi)),hands=new Set(a.map(n=>n.hand));
 if(hands.size)b.classList.add(hands.has('left')&&hands.has('right')?'key-both':'key-'+Array.from(hands)[0]);
 else{const s=sustained.find(n=>n.pitch===Number(b.dataset.midi));if(s)b.style.outline='2px solid '+colors[s.hand]}
 b.querySelector('.hands').textContent=hands.has('left')&&hands.has('right')?'L / R':hands.has('left')?'L':hands.has('right')?'R':hands.size?'—':''});
 $('current').textContent='';const displayed=active.length?active:transport&&transport.phase==='paused'?windowNotes(t).filter(n=>audible(n)&&n.start_s<=t&&t<n.key_off_s):[];
 displayed.slice(0,12).forEach(n=>{const chip=document.createElement('span');chip.className='note-chip '+n.hand;chip.textContent=handLabel[n.hand]+' · '+noteName(n.pitch);const sol=document.createElement('small');sol.textContent=Solfege[n.pitch%12];chip.appendChild(sol);$('current').appendChild(chip)});
}
function drawOverview(t){
 const loop=loopPreview||transport&&transport.loop;const signature=(score?score.score_id+':'+score.revision:'')+':'+Math.round(t/(score?Math.max(score.duration_s,.001):1)*$('overview').clientWidth)+':'+JSON.stringify(loop)+':'+$('overview').clientWidth; if(signature===waveSignature)return;waveSignature=signature;
 const {ctx,w,h}=setupCanvas('overview');ctx.strokeStyle='#46645b';ctx.lineWidth=1;
 if(overview){ctx.beginPath();overview.min.forEach((low,i)=>{let x=i/(overview.min.length-1)*w;ctx.moveTo(x,h/2-low*h*2);ctx.lineTo(x,h/2-overview.max[i]*h*2)});ctx.stroke()}
 if(!score)return;const duration=Math.max(score.duration_s,.001);
 if(loop&&loop.b_s>loop.a_s){const a=loop.a_s/duration*w,b=loop.b_s/duration*w;ctx.fillStyle=loop.enabled?'#efbd7030':'#efbd7010';ctx.fillRect(a,0,b-a,h);ctx.strokeStyle='#efbd70';ctx.fillStyle='#efbd70';ctx.textAlign='left';ctx.font='10px sans-serif';for(const [x,label] of [[a,'A'],[b,'B']]){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();ctx.fillText(label,Math.min(w-10,x+4),12)}}
 const x=t/duration*w;ctx.strokeStyle='#e9e5d2';ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();ctx.fillStyle='#efbd70';ctx.beginPath();ctx.arc(x,3,3,0,Math.PI*2);ctx.fill();
}
function drawAnalysis(){
 const active=transport&&transport.phase==='playing'&&transport.volume>0&&analysisFrame&&score&&analysisFrame.revision===score.revision;
 let {ctx,w,h}=setupCanvas('wave');ctx.strokeStyle='#27423b';ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.stroke();ctx.strokeStyle=colors.left;ctx.beginPath();const samples=active?analysisFrame.waveform:Array(256).fill(0);samples.forEach((v,i)=>{const x=i/255*w,y=h/2-v*h*3;if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y)});ctx.stroke();
 ({ctx,w,h}=setupCanvas('spectrum'));const bands=active?analysisFrame.spectrum_db:Array(128).fill(-90);ctx.fillStyle=colors.right;bands.forEach((db,i)=>{const height=Math.max(1,(db+90)/90*h);ctx.globalAlpha=.3+(db+90)/180;ctx.fillRect(i*w/128,h-height,Math.max(1,w/128-1),height)});ctx.globalAlpha=1;
}
function draw(){const t=sourceTime();const syncText=transport&&transport.phase==='playing'&&performance.now()-receivedAt>250?'正在同步播放位置':'';if($('syncStatus').textContent!==syncText)$('syncStatus').textContent=syncText;if(window.ScoreView&&ScoreView.active)ScoreView.draw(transport);else drawRoll(t);updateKeys(t);drawOverview(t);const clockText=timeLabel(t)+' / '+timeLabel(score?score.duration_s:0);if($('clock').textContent!==clockText)$('clock').textContent=clockText;if(analysisOpen&&analysisFrame&&analysisFrame.seq!==metrics.analysisDrawn){drawAnalysis();metrics.analysisDrawn=analysisFrame.seq}}
function frame(now){metrics.frames++;fpsFrames++;if(now-fpsAt>=1000){fps=fpsFrames*1000/(now-fpsAt);fpsFrames=0;fpsAt=now}if(!document.hidden)draw();requestAnimationFrame(frame)}
function renderTracks(){
 $('trackSettings').textContent='';if(!score)return;
 score.tracks.forEach(t=>{const row=document.createElement('div');row.className='track-row';row.dataset.track=t.id;const name=document.createElement('span');name.textContent=t.name;name.title=t.name;row.appendChild(name);
 const select=document.createElement('select');select.className='assignTrack';select.setAttribute('aria-label',t.name+'手别');['unassigned','left','right'].forEach(hand=>{const o=document.createElement('option');o.value=hand;o.textContent=handLabel[hand];select.appendChild(o)});const hands=new Set(notes.filter(n=>n.track_id===t.id).map(n=>n.hand));select.value=hands.size===1?Array.from(hands)[0]:'unassigned';row.appendChild(select);
 for(const [key,label] of [['muted','静音'],['solo','独奏']]){const l=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.className=key;input.checked=t[key];l.className='track-only';l.appendChild(input);l.appendChild(document.createTextNode(' '+label));row.appendChild(l)}$('trackSettings').appendChild(row)});
}
function updateSelection(){const label=selected.size+' 个音符';$('selectionCount').textContent=label;$('selectedLabel').textContent=label;$('selectionBar').hidden=!selected.size;document.querySelector('#editor .selection-tools').hidden=!selected.size}
async function openSettings(){$('editor').classList.remove('track-editor');$('editorTitle').textContent='左右手设置';if(transport.phase==='playing')updateTransport(value(await piano.pause()));renderTracks();syncAssignment();if(compactSidebar())setSidebar(false);$('editor').hidden=false;$('closeEditor').focus()}
async function previewHands(){invalidateAssignment();const attempt=assignmentEpoch,originalScore=score;const rule={type:$('rule').value};if(rule.type==='pitch_split')rule.pitch=Number($('split').value);else{rule.tracks={};document.querySelectorAll('.track-row').forEach(row=>rule.tracks[row.dataset.track]=row.querySelector('.assignTrack').value)}
 const result=value(await piano.preview_hands(rule));if(attempt!==assignmentEpoch||score!==originalScore)return;const all=[];for(let i=0;i<score.notes_count;i+=2000){const page=value(await piano.get_notes(i,2000,result.preview_id));all.push(...page.notes)}if(attempt!==assignmentEpoch||score!==originalScore)return;previewId=result.preview_id;previewNotes=all;$('applyHands').disabled=false;$('previewHint').hidden=false;$('previewHint').textContent='这是初步建议，请检查后应用。 '+Object.keys(result.counts).map(h=>handLabel[h]+' '+result.counts[h]).join(' · ');}
let assignmentEpoch=0;
function invalidateAssignment(){assignmentEpoch++;previewId=null;previewNotes=null;$('previewHint').hidden=true;$('applyHands').disabled=true;lastSignature=''}
function syncAssignment(){
 const pitch=$('rule').value==='pitch_split';$('splitField').hidden=!pitch;$('splitSummary').hidden=!pitch;
 if(!$('editor').classList.contains('track-editor'))$('trackSettings').hidden=pitch;
 $('assignmentHelp').textContent=pitch?'适合左右手混在同一轨道的曲目。低于分界音归左手，其余归右手；可在预览后逐音微调。':'为每条轨道选择左手或右手。轨道名称仅供参考，混合轨道可改用按音高初分。';
 if(score){const count=notes.filter(n=>n.pitch<Number($('split').value)).length;$('splitSummary').textContent='左手 '+count+' 个音符 · 右手 '+(notes.length-count)+' 个音符（含分界音）'}
}
let library=null;
function renderLibrary(){
 const root=$('librarySongs');root.textContent='';const songs=library?library.songs:[],query=$('songSearch').value.trim().toLocaleLowerCase();
 $('libraryTitle').textContent=library?library.folder_name+' · '+songs.length+' 首':'我的曲目';$('songSearch').hidden=!songs.length;
 const filtered=songs.filter(item=>item.filename.toLocaleLowerCase().includes(query));
 $('libraryHint').hidden=!!filtered.length;$('libraryHint').textContent=!library?'选择文件夹后，在这里切换曲目。':!songs.length?'此文件夹没有 MIDI 文件；请选择其他文件夹。': '没有匹配的曲目。';
 for(const item of filtered){const b=document.createElement('button');b.className='demo';b.textContent=item.title;b.title=item.filename;b.classList.toggle('active',!!score&&score.source_token===item.file_token);b.onclick=safe(async()=>{await load({file_token:item.file_token});if(compactSidebar())setSidebar(false)});root.appendChild(b)}
}
async function chooseFolder(){const result=value(await piano.choose_midi_folder());if(result){library=result;$('songSearch').value='';renderLibrary()}}
$('openFolder').onclick=safe(chooseFolder);$('songSearch').oninput=renderLibrary;
$('rule').onchange=()=>{invalidateAssignment();syncAssignment()};$('split').onchange=()=>{invalidateAssignment();syncAssignment()};$('trackSettings').onchange=invalidateAssignment;
async function assignSelected(hand){if(!selected.size)return;if(transport.phase==='playing')updateTransport(value(await piano.pause()));const p=value(await piano.preview_hands({type:'current'}));const overrides={};selected.forEach(id=>overrides[id]=hand);startJob(value(piano.apply_hands(p.preview_id,overrides)));$('editor').hidden=true}
async function choose(){const token=value(await piano.choose_midi());if(token){await load(token);if(compactSidebar())setSidebar(false)}}
let sidebarDockedOpen=true,sidebarDrawerOpen=false;
function compactSidebar(){return window.matchMedia('(max-width:1100px)').matches}
function syncSidebar(){
 const compact=compactSidebar(),open=compact?sidebarDrawerOpen:sidebarDockedOpen;
 $('sidebar').hidden=!open;$('shell').classList.toggle('drawer-open',compact&&open);
 $('sidebarToggle').setAttribute('aria-expanded',String(open));$('sidebarToggle').setAttribute('aria-label',open?'收起侧栏':'展开侧栏');
 if(compact&&open){$('sidebar').setAttribute('role','dialog');$('sidebar').setAttribute('aria-modal','true')}else{$('sidebar').removeAttribute('role');$('sidebar').removeAttribute('aria-modal')}
}
function setSidebar(open){
 if(compactSidebar())sidebarDrawerOpen=open;else sidebarDockedOpen=open;
 syncSidebar();if(open&&compactSidebar())$('sidebarClose').focus();else if(!open)$('sidebarToggle').focus();
 buildKeyboard();draw();
}
$('sidebarToggle').onclick=()=>setSidebar($('sidebar').hidden);
$('sidebarClose').onclick=$('sidebarBackdrop').onclick=()=>setSidebar(false);
syncSidebar();
$('open').onclick=safe(async()=>{try{await choose()}catch(e){$('pathFallback').hidden=false;throw e}});$('other').onclick=$('open').onclick;
$('loadPath').onclick=safe(async()=>{const token=value(await piano.open_path($('filePath').value));await load(token);$('pathFallback').hidden=true});$('closePath').onclick=()=>{$('pathFallback').hidden=true};
 document.querySelectorAll('[data-demo]').forEach(b=>b.onclick=safe(async()=>{await load(b.dataset.demo);if(compactSidebar())setSidebar(false)}));
$('play').onclick=safe(togglePlay);$('stop').onclick=safe(async()=>updateTransport(value(await piano.stop())));
$('full').onclick=()=>setMode('full');$('focused').onclick=()=>setMode('focused');$('names').onchange=()=>{showNames=$('names').checked;buildKeyboard()};$('motion').onchange=()=>draw();
$('strikePosition').value=strikeLift;$('strikePositionText').textContent=strikeLift+'%';$('strikePosition').oninput=()=>setStrikeLift(Number($('strikePosition').value));
document.querySelectorAll('[data-rate]').forEach(b=>b.onclick=safe(()=>configure(Number(b.dataset.rate))));document.querySelectorAll('[data-hand]').forEach(b=>b.onclick=safe(()=>configure(transport.rate,b.dataset.hand)));
$('volume').oninput=safe(()=>{const v=Number($('volume').value)/100;piano.set_volume(v);$('volumeText').textContent=Math.round(v*100)+'%';if(transport)transport.volume=v;try{localStorage.setItem('volume',String(v))}catch(_){}});
$('analysisToggle').onclick=()=>{message('');analysisOpen=!analysisOpen;$('analysis').hidden=!analysisOpen;$('shell').classList.toggle('analysis-open',analysisOpen);$('analysisToggle').textContent=analysisOpen?'▥ 收起频谱':'▥ 查看频谱';buildKeyboard()};
$('cancel').onclick=safe(()=>{if(job){piano.cancel_job(job.job_id);job=null;$('loading').hidden=true;updateTransport(value(piano.get_transport()))}});
$('retry').onclick=safe(async()=>updateTransport(value(await piano.retry_audio())));$('dismissHint').onclick=()=>{hiddenHint=true;$('unassignedHint').hidden=true};
$('loop').onclick=safe(async()=>{if(score.duration_s<.5)throw Error('曲目不足 0.5 秒，无法循环');let l=transport.loop;if(l.b_s-l.a_s<.5){let a=Math.min(sourceTime(),score.duration_s-.5);l={a_s:a,b_s:Math.min(a+8,score.duration_s)}}updateTransport(value(await piano.set_loop(!transport.loop.enabled,l.a_s,l.b_s)))});
$('applyLoop').onclick=safe(async()=>{try{updateTransport(value(await piano.set_loop(transport.loop.enabled,Number($('loopA').value),Number($('loopB').value))))}catch(e){$('loopA').value=transport.loop.a_s.toFixed(2);$('loopB').value=transport.loop.b_s.toFixed(2);throw e}});
$('settings').onclick=safe(openSettings);$('tracks').onclick=()=>{renderTracks();$('trackSettings').hidden=false;$('editor').classList.add('track-editor');$('editorTitle').textContent='轨道设置';if(compactSidebar())setSidebar(false);$('editor').hidden=false;$('closeEditor').focus()};function closeEditor(){$('editor').hidden=true;invalidateAssignment();($('sidebar').hidden?$('sidebarToggle'):$('settings')).focus()}$('closeEditor').onclick=closeEditor;
$('editNotes').onclick=()=>{$('editor').hidden=true;previewNotes=null;$('roll').focus()};
for(let p=21;p<=108;p++){const option=document.createElement('option');option.value=p;option.textContent=noteName(p);$('split').appendChild(option)}$('split').value=60;
$('preview').onclick=safe(previewHands);$('applyHands').onclick=safe(()=>{if(previewId){startJob(value(piano.apply_hands(previewId,{})));$('editor').hidden=true}});$('undo').onclick=safe(()=>{startJob(value(piano.undo_hands()));$('editor').hidden=true});
$('applyTracks').onclick=safe(()=>{const tracks=score.tracks.map(t=>{const row=Array.from(document.querySelectorAll('.track-row')).find(r=>r.dataset.track===t.id);return {...t,muted:row.querySelector('.muted').checked,solo:row.querySelector('.solo').checked}});$('editor').hidden=true;return configure(transport.rate,transport.hand_mode,tracks)});
document.querySelectorAll('[data-assign]').forEach(b=>b.onclick=safe(()=>assignSelected(b.dataset.assign)));$('selectionClear').onclick=()=>{selected.clear();updateSelection()};
function point(e,c){const r=c.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top}}
$('roll').onmousedown=safe(async e=>{if(!score||job)return;if(transport.phase==='playing')updateTransport(value(await piano.pause()));const p=point(e,$('roll'));drag={x:p.x,y:p.y,endX:p.x,endY:p.y,add:e.shiftKey};e.preventDefault()});
$('overview').onmousedown=safe(async e=>{if(!score||job)return;const c=$('overview'),x=point(e,c).x,t=x/c.clientWidth*score.duration_s,l=transport.loop,nearA=Math.abs(t-l.a_s)*c.clientWidth/score.duration_s<12,nearB=Math.abs(t-l.b_s)*c.clientWidth/score.duration_s<12;const resume=transport.phase==='playing';waveDrag={position:t,resume,kind:l.b_s>l.a_s&&(nearA||nearB)?nearA?'a_s':'b_s':'seek'};interacting=true;loopPreview={...l};if(resume)updateTransport(value(await piano.pause()));e.preventDefault()});
document.addEventListener('mousemove',e=>{if(strikeDragging){const r=$('roll').getBoundingClientRect();setStrikeLift((r.bottom-e.clientY)/Math.max(1,r.height)*100);return}if(drag){const p=point(e,$('roll'));drag.endX=p.x;drag.endY=p.y}if(waveDrag&&score){let t=Math.max(0,Math.min(score.duration_s,point(e,$('overview')).x/$('overview').clientWidth*score.duration_s));if(waveDrag.kind==='seek')waveDrag.position=t;else loopPreview[waveDrag.kind]=t}});
document.addEventListener('mouseup',safe(async()=>{if(strikeDragging){strikeDragging=false;return}if(drag){if(!drag.add)selected.clear();const left=Math.min(drag.x,drag.endX),right=Math.max(drag.x,drag.endX),top=Math.min(drag.y,drag.endY),bottom=Math.max(drag.y,drag.endY);const click=right-left<4&&bottom-top<4;for(const r of noteRects){if(click?r.x<=left&&left<=r.x+r.width&&r.y<=top&&top<=r.y+r.height:r.x<right&&r.x+r.width>left&&r.y<bottom&&r.y+r.height>top)selected.add(r.id)}drag=null;updateSelection()}
 if(waveDrag){const d=waveDrag;waveDrag=null;try{if(d.kind==='seek')updateTransport(value(await piano.seek(d.position)));else updateTransport(value(await piano.set_loop(transport.loop.enabled,loopPreview.a_s,loopPreview.b_s)));}finally{interacting=false;loopPreview=null;if(d.resume)updateTransport(value(await piano.play()))}}}));
document.addEventListener('keydown',safe(async e=>{if(e.key==='Escape'){if($('shell').classList.contains('drawer-open')){setSidebar(false);return}closeEditor();$('pathFallback').hidden=true;return}if(e.key==='Tab'&&$('shell').classList.contains('drawer-open')){const focusable=Array.from($('sidebar').querySelectorAll('button:not(:disabled),input,select')).filter(x=>x.offsetParent!==null);const first=focusable[0],last=focusable[focusable.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}return}if(e.key==='Tab'&&!$('editor').hidden){const focusable=Array.from($('editor').querySelectorAll('button:not(:disabled),select,input')).filter(x=>x.offsetParent!==null);const first=focusable[0],last=focusable[focusable.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}return}if(e.ctrlKey||e.metaKey||e.altKey||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName)||!$('editor').hidden||job||!score)return;if(e.code==='Space'){e.preventDefault();await togglePlay()}else if(e.key==='Home'){e.preventDefault();updateTransport(value(await piano.seek(0)))}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();updateTransport(value(await piano.seek(Math.max(0,Math.min(score.duration_s,sourceTime()+(e.key==='ArrowRight'?2:-2))))))}}));
window.addEventListener('resize',()=>{syncSidebar();buildKeyboard()});if(window.ResizeObserver)new ResizeObserver(buildKeyboard).observe($('keys'));
function geometry(modeTest,width){const l=new KeyboardLayout(score?score.used_pitches:[60,61,64,67],modeTest,width);let max=0;for(const k of l.rects){const r=l.noteRect({pitch:k.midi,start_s:0,key_off_s:1},200,0,90);max=Math.max(max,Math.abs(r.center-k.center),Math.abs(r.x+r.width/2-k.center))}return {keys:l.rects.length,whites:l.rects.filter(k=>!k.is_black).length,blacks:l.rects.filter(k=>k.is_black).length,error:max,low:l.low,high:l.high}}
window.PianoScope={load,waitJob,refresh,setMode,configure,togglePlay,setLibrary(result){library=result;$('songSearch').value='';renderLibrary()},get score(){return score},get notes(){return notes},get transport(){return transport},get job(){return job},get interacting(){return interacting},geometry,metrics,get fps(){return fps},draw,sourceTime};
try{const t=value(piano.get_transport());if(piano.session.phase!==t.phase)throw Error('播放器初始化失败');updateTransport(t);buildKeyboard();window.PIANOSCOPE_READY=true;setInterval(poll,25);requestAnimationFrame(frame);load(window.INITIAL_SOURCE||'demo:first-light').catch(e=>message(String(e.message||e)))}catch(e){message(String(e.message||e));window.PIANOSCOPE_READY=false}
})();
