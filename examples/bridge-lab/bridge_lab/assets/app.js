(() => {
const $=id=>document.getElementById(id), drafts=SAMPLES.map(s=>s.code), pythonDrafts=PYTHON_SOURCES.slice(), logs=[];
let selected=0,busy=false,ready=false,sequence=0,alive=true,pythonModule=null;
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
function format(v){if(v instanceof Error)return v.stack||v.message;if(typeof v==='string')return v;try{return JSON.stringify(v)??String(v)}catch(_){return String(v)}}
function log(level,values,runId=sequence,scenario=SAMPLES[selected].id){
 if(!alive)return;const row={time:new Date().toISOString(),runId,scenario,level,message:values.map(format).join(' ').slice(0,4000)};
 logs.push(row);if(logs.length>300)logs.shift();
 const node=document.createElement('div');node.className='entry '+level;
 const meta=document.createElement('small');meta.textContent=`${row.time} · #${runId} · ${scenario} · ${level}`;
 node.appendChild(meta);node.appendChild(document.createTextNode(row.message));$('logs').appendChild(node);
 while($('logs').children.length>300)$('logs').firstChild.remove();$('logs').scrollTop=$('logs').scrollHeight;
}
function saveDrafts(){drafts[selected]=$('editor').value;pythonDrafts[selected]=$('source').value}
function sourceMode(){ $('source').readOnly=busy;$('sourceLabel').textContent='Python · 可编辑 · 运行时先加载';$('pythonHint').textContent='可使用正常 Python 语法、导入、函数与类。公开名称通过 JS 的 lab 对象访问；Python print 输出到启动终端。';}

function controls(){sourceMode(); $('run').disabled=busy||!ready;$('reset').disabled=busy||!ready;$('editor').readOnly=busy;document.querySelectorAll('#cases button').forEach(b=>b.disabled=busy||!ready); }
function inspect(state){const status=Python.to_value(lab.get_status());const counter=pythonModule ? pythonModule.counter : null;$('inspector').textContent=JSON.stringify({bridgeReady:status.ready,scenario:SAMPLES[selected].id,state,pythonLoaded:pythonModule!==null,counter:counter?counter.value:null,history:counter?Python.to_value(counter.history):null},null,2);$('status').textContent=state+' · '+SAMPLES[selected].id+' · AppCore / 本地资源';}

function select(i){if(busy||!ready)return false;saveDrafts();if(selected!==i)pythonModule=null;selected=i;$('editor').value=drafts[i];$('source').value=pythonDrafts[i];sourceMode();$('title').textContent=`0${i+1} · ${SAMPLES[i].title}`;$('expected').textContent='预期：'+SAMPLES[i].expected;document.querySelectorAll('#cases button').forEach((b,j)=>b.classList.toggle('active',i===j));inspect('就绪');return true;}
async function run(){
 if(!ready||busy)return null;busy=true;controls();const runId=++sequence,scenario=SAMPLES[selected].id,output=[],start=performance.now();let success=false,error=null,phase='JS';
 const print=(...v)=>{if(alive){output.push(v.map(format).join(' '));log('log',v,runId,scenario)}};
 const console={log:print,warn:(...v)=>log('warn',v,runId,scenario),error:(...v)=>log('error',v,runId,scenario)};
 try{inspect('运行中');log('log',['开始（重新加载当前 Python 模块）']);saveDrafts();phase='Python 加载';pythonModule=lab.run_python(pythonDrafts[selected]);log('log',['Python 已加载；现在执行 JS'],runId,scenario);phase='JS';const result=await new AsyncFunction('print','console','lab','py',drafts[selected])(print,console,pythonModule,pythonModule);if(result!==undefined)print(result);success=true;}
 catch(e){error=phase+'失败：'+String(e.message||e)+'\n'+String(e.stack||'');log('error',[error],runId,scenario);}
 finally{busy=false;if(alive){controls();inspect(success?'完成':'失败');}}
 const elapsed=performance.now()-start;log(success?'log':'error',[success?'完成':'失败',elapsed.toFixed(2)+' ms'],runId,scenario);return {runId,scenario,success,output,error,elapsed};
}
function reset(){if(busy||!ready)return false;lab.reset_counter();drafts[selected]=SAMPLES[selected].code;pythonDrafts[selected]=PYTHON_SOURCES[selected];pythonModule=null;$('source').value=pythonDrafts[selected];$('editor').value=drafts[selected];inspect('已重置');return true;}
function copy(id){const t=$(id),start=t.selectionStart,end=t.selectionEnd;t.focus();t.select();const ok=document.execCommand('copy');t.setSelectionRange(start,end);log(ok?'log':'warn',[ok?'已复制':'请手动选择后复制']);}
SAMPLES.forEach((s,i)=>{const b=document.createElement('button');b.textContent=`0${i+1} · ${s.title}`;b.onclick=()=>select(i);$('cases').appendChild(b)});
$('run').onclick=run;$('reset').onclick=reset;$('copy').onclick=()=>copy('editor');$('copyPython').onclick=()=>copy('source');$('clear').onclick=()=>{logs.length=0;$('logs').textContent=''};
['editor','source'].forEach(id=>$(id).addEventListener('keydown',e=>{if(e.key==='Tab'&&!$(id).readOnly){e.preventDefault();document.execCommand('insertText',false,id==='source'?'    ':'  ')}}));
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();run()}});
window.addEventListener('pagehide',()=>{alive=false;ready=false;window.BRIDGE_LAB_READY=false});
window.BridgeLab={run,select,reset,logs,get busy(){return busy},get python(){return pythonModule}};
try{const status=Python.to_value(lab.get_status());if(status.ready!==true||lab.add(1,2)!==3)throw Error('Bridge 实际检查失败');ready=true;$('editor').value=drafts[0];$('source').value=pythonDrafts[0];select(0);controls();window.BRIDGE_LAB_READY=true;log('log',['真实 Python Bridge ready'])}catch(e){log('error',[e]);$('status').textContent='Bridge 初始化失败'}
})();
