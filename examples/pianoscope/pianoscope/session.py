"""Main-thread controller. Workers return data; publication happens on the UI thread."""
import asyncio
import bisect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import copy
import hashlib
import json
import math
import logging
from pathlib import Path
import threading
import time
import uuid
from .audio import Audio
from .midi import parse_midi
from .render import render, audible_notes
from .analysis import analyze, overview
from .hands import preview, assigned
from .dialogs import choose_path

DEMO_ROOT=Path(__file__).parent/'resources/demos'
DEMOS={'demo:first-light':'first-light','demo:harmonics':'harmonics'}

class SessionProxy:
    def __init__(self,owner):self._owner=owner
    @property
    def phase(self):return self._owner.phase
    @property
    def score_id(self):return self._owner.score.score_id if self._owner.score else None
    @property
    def revision(self):return self._owner.score.revision if self._owner.score else 0
    @property
    def generation(self):return self._owner.generation
    @property
    def ready(self):return self._owner.score is not None and self.phase not in ('loading','preparing','closing','closed')
    @property
    def hand_status(self):return self._owner.score.hand_assignment['status'] if self._owner.score else 'unassigned'

class Controller:
    def __init__(self):
        self.audio=Audio();self.audio.open()
        self.score=None;self.config=None;self.phase='empty';self.generation=0;self.error=None
        self.jobs={};self.current_job=None;self.pool=ThreadPoolExecutor(1,thread_name_prefix='pianoscope-render')
        self.analysis_pool=ThreadPoolExecutor(1,thread_name_prefix='pianoscope-analysis');self.analysis_future=None;self.analysis_frame=None
        self.tokens={};self.library_tokens={};self.library=None;self.library_epoch=0;self.loaded_source=None
        self.previews={};self.history=[];self.seq=0;self.analysis_seq=0
        self.session=SessionProxy(self);self.command_lock=asyncio.Lock();self.closed=False
        self.audible=[];self.note_starts=[];self.note_ends=[]
        self.prepare_seconds=0;self.analysis_last_at=0
        from .score_jobs import ScoreJobs
        self.notation=ScoreJobs(self)
    def begin_notation(self,options):return self.notation.begin(options)
    def get_notation_job(self,job_id):return self.notation.get(job_id)
    def cancel_notation_job(self,job_id):return self.notation.cancel(job_id)
    def apply_notation(self,preview_id,expected_source_revision):return self.notation.apply(preview_id,expected_source_revision)
    def get_notation(self):return self.notation.summary(self.notation.applied) if self.notation.applied else None
    def get_key_suggestion(self,tracks):
        self._available()
        valid={t['id'] for t in self.score.tracks}
        if not tracks or len(set(tracks))!=len(tracks) or not set(tracks)<=valid:raise ValueError('请检查制谱轨道。')
        from .score_spelling import suggest_key
        return suggest_key([n for n in self.score.notes if n.track_id in tracks],self.score.ppqn)
    def get_notation_preview(self,preview_id):
        item=self.notation.previews.get(preview_id)
        return self.notation.summary(item) if item else None
    def get_notation_warnings(self,notation_id,offset,limit,category='all'):
        offset=int(offset);limit=int(limit)
        if offset<0 or not 1<=limit<=100:raise ValueError('无效提示页码')
        values=self.notation._item(notation_id)['document']['warnings']
        if category not in ('all','review','short_fill'):raise ValueError('无效整理提示分类')
        if category=='review':values=[w for w in values if (w.get('normalization') or {}).get('needs_review')]
        elif category=='short_fill':values=[w for w in values if w.get('kind')=='short_fill']
        return dict(offset=offset,total=len(values),warnings=values[offset:offset+limit])
    def get_notation_page(self,notation_id,page):return self.notation.page(notation_id,page)
    async def choose_score_export(self,format):
        from .dialogs import choose_score_path
        item=self.notation.applied
        if not item:raise ValueError('请先应用谱面。')
        if self.notation.summary(item)['state']=='stale':raise ValueError('谱面已过期，请重新生成。')
        path=choose_score_path(item['document']['title'],format)
        if not path:return None
        if self.notation.applied is not item:raise ValueError('保存期间谱面已改变，请重新导出。')
        return self.notation.target(item['notation_id'],format,path)
    def begin_score_export(self,notation_id,format,target_token):return self.notation.export(notation_id,format,target_token)
    def token_for_path(self,path):
        path=Path(path).expanduser().resolve()
        if path.suffix.lower() not in ('.mid','.midi'):raise ValueError('请选择 .mid 或 .midi 文件')
        token=uuid.uuid4().hex;self.tokens[token]=path
        self.tokens=dict(list(self.tokens.items())[-16:])
        return {'file_token':token}
    async def choose_midi(self):
        path=choose_path()
        return self.token_for_path(path) if path else None
    async def open_path(self,path):
        return self.token_for_path(path)
    async def choose_midi_folder(self):
        path=choose_path(folder=True)
        return await self.open_midi_folder(path) if path else None
    async def open_midi_folder(self,path):
        self.library_epoch+=1;epoch=self.library_epoch
        def scan():
            root=Path(path).expanduser().resolve()
            if not root.is_dir():raise ValueError('请选择一个 MIDI 文件夹。')
            paths=[]
            for item in root.iterdir():
                if item.suffix.lower() in ('.mid','.midi') and item.is_file():paths.append(item)
                if len(paths)>1000:raise ValueError('文件夹超过 1,000 首曲目，请选择较小的文件夹。')
            paths.sort(key=lambda p:(p.name.casefold(),p.name))
            entries=[dict(file_token=uuid.uuid4().hex,title=p.stem,filename=p.name) for p in paths]
            return dict(folder_name=root.name,songs=entries),{e['file_token']:p for e,p in zip(entries,paths)}
        library,tokens=await asyncio.to_thread(scan)
        if epoch!=self.library_epoch or self.closed:raise ValueError('文件夹选择已改变，请重试。')
        self.library=library;self.library_tokens=tokens
        return library
    def get_midi_library(self):return self.library
    def _begin(self,operation,phase='preparing',resume=False,history=None):
        if self.closed:raise ValueError('应用已关闭')
        if self.current_job:self.cancel_job(self.current_job)
        position=self.audio.halt();self.generation+=1;generation=self.generation
        jid=uuid.uuid4().hex;cancel=threading.Event();started=time.perf_counter();sample_rate=self.audio.sample_rate
        job=dict(job_id=jid,generation=generation,phase=phase,progress=0.,done=False,cancelled=False,error=None,
                 cancel=cancel,position=position,resume=resume,history=history,started=started)
        self.jobs[jid]=job;self.current_job=jid;self.phase=phase;self.error=None
        def update(value,stage='preparing'):
            job['phase']=stage;job['progress']=float(value)
        def work():
            if cancel.is_set():raise InterruptedError('已取消')
            score,config,is_load=operation(cancel.is_set,update)
            pcm=render(score,config,sample_rate,cancel.is_set,lambda v:update(.1+.9*v))
            return score,config,pcm,is_load
        job['future']=self.pool.submit(work)
        for old in list(self.jobs)[:-16]:
            if self.jobs[old]['done']:del self.jobs[old]
        return dict(job_id=jid,generation=generation)
    def begin_load(self,source):
        if isinstance(source,dict):source=source.get('file_token')
        slug=DEMOS.get(source);path=DEMO_ROOT/(slug+'.mid') if slug else self.library_tokens.get(source,self.tokens.get(source))
        if path is None:raise ValueError('文件选择已失效，请重新打开 MIDI')
        def operation(cancel,update):
            score=parse_midi(path,cancel,lambda v:update(v*.1,'loading'))
            if slug:
                side=json.loads(path.with_suffix('.hands.json').read_text())
                if hashlib.sha256(path.read_bytes()).hexdigest()!=side['sha256']:raise ValueError('示例曲校验失败')
                score.title=side['title'];score.hand_assignment={'status':'confirmed','source':'bundled'}
                score.notes=[replace(n,hand=side['tracks'][n.track_id],hand_source='bundled') for n in score.notes]
            return score,dict(rate=1.,tracks=copy.deepcopy(score.tracks),hand_mode='both'),True
        result=self._begin(operation,'loading');self.jobs[result['job_id']]['load_source']=source
        return result
    def _publish(self,job):
        if job['done']:return
        future=job['future']
        if not future.done():return
        job['done']=True
        if job['generation']!=self.generation or job['cancel'].is_set():
            job['cancelled']=True;job.pop('future',None);return
        try:
            score,config,pcm,is_load=future.result()
            if job['history'] is not None:
                action,values=job['history']
                if action=='push':self.history.append(values);self.history=self.history[-8:]
                else:self.history.pop()
            self.score=score;self.config=config
            self.score.tracks=copy.deepcopy(config['tracks'])
            self.audible=sorted(audible_notes(score,config),key=lambda n:n.start_s)
            self.note_starts=[n.start_s for n in self.audible];last=0;self.note_ends=[]
            for n in self.audible:
                last=max(last,n.key_off_s);self.note_ends.append(last)
            if is_load:
                self.loaded_source=job.get('load_source')
                self.history=[];self.previews={};self.audio.loop={'enabled':False,'a_s':0.,'b_s':0.}
            self.audio.install(pcm,config['rate'],score.duration_s,0 if is_load else min(job['position'],score.duration_s))
            self.phase='ready' if is_load else 'paused';self.error=None
            self.analysis_frame=None;self.analysis_future=None
            if job['resume'] and self.audio.ready:self.audio.start();self.phase='playing'
            job['progress']=1.;job['phase']='ready';self.prepare_seconds=time.perf_counter()-job['started']
        except Exception as exc:
            logging.getLogger('pianoscope').exception('Preparation failed')
            text='无法读取所选文件，请检查文件是否存在或访问权限。' if isinstance(exc,OSError) else str(exc)
            job['error']={'code':'PREPARATION_FAILED','message':text,'recoverable':True}
            self.error=job['error'];self.phase='paused' if self.score else 'empty'
        job.pop('future',None)
        self.current_job=None
    def get_job(self,job_id):
        job=self.jobs[job_id];self._publish(job)
        return {k:job[k] for k in ('job_id','generation','phase','progress','done','cancelled','error')}
    def cancel_job(self,job_id):
        job=self.jobs.get(job_id)
        if not job or job['done']:return False
        job['cancel'].set();future=job.pop('future',None)
        if future:future.cancel()
        job['cancelled']=True;job['done']=True
        if self.current_job==job_id:
            self.generation+=1;self.current_job=None;self.phase='paused' if self.score else 'empty'
        return True
    def get_score(self):return dict(self.score.metadata(),source_token=self.loaded_source) if self.score else None
    async def get_notes(self,offset,limit,preview_id=None):
        if not self.score:return None
        offset=int(offset);limit=int(limit)
        if offset<0 or not 1<=limit<=2000:raise ValueError('音符分页范围无效')
        score=self.score;generation=self.generation
        values=self.previews[preview_id]['values'] if preview_id else None
        def extract():
            notes=[asdict(n) for n in score.notes[offset:offset+limit]]
            if values:
                for n in notes:n['hand']=values[n['id']]
            return dict(score_id=score.score_id,revision=score.revision,generation=generation,notes=notes,total=len(score.notes))
        return await asyncio.to_thread(extract)
    async def get_overview(self,points):
        if not self.score:return None
        score=self.score;pcm=self.audio.pcm;generation=self.generation
        source_frames=round(score.duration_s/self.config['rate']*self.audio.sample_rate)
        result=await asyncio.to_thread(overview,pcm[:source_frames],points)
        return dict(result,score_id=score.score_id,revision=score.revision,generation=generation)
    def _available(self):
        if not self.score:raise ValueError('请先选择曲目')
        if self.current_job:raise ValueError('声音正在准备，请稍候或取消')
    async def play(self):
        async with self.command_lock:
            self._available()
            if self.audio.playing:return self.get_transport()
            if not self.audio.ready:
                self._audio_error('未找到声音输出设备');return self.get_transport()
            pos=self.audio.position
            loop=self.audio.loop
            if loop['enabled'] and not loop['a_s']<=pos<loop['b_s']:pos=loop['a_s']
            elif pos>=self.score.duration_s:pos=0
            self.audio.set_position(pos)
            try:self.audio.start();self.phase='playing';self.error=None
            except Exception:self._audio_error('未找到声音输出设备')
            return self.get_transport()
    async def pause(self):
        async with self.command_lock:
            self._available();await self.audio.fade_halt();self.phase='paused'
            return self.get_transport()
    async def stop(self):
        async with self.command_lock:
            self._available();await self.audio.fade_halt();self.audio.set_position(0);self.phase='ready'
            return self.get_transport()
    async def seek(self,position_s):
        async with self.command_lock:
            self._available();position_s=float(position_s)
            if not math.isfinite(position_s) or not 0<=position_s<=self.score.duration_s:raise ValueError('跳转时间超出曲目范围')
            resume=self.audio.playing;await self.audio.fade_halt();loop=self.audio.loop
            if loop['enabled']:position_s=min(max(position_s,loop['a_s']),loop['b_s']-self.config['rate']/self.audio.sample_rate)
            self.audio.set_position(position_s)
            if resume:self.audio.start();self.phase='playing'
            elif self.phase=='ended':self.phase='paused'
            return self.get_transport()
    def configure(self,rate,tracks,hand_mode):
        self._available()
        if rate not in (.5,.75,1):raise ValueError('速度需为 0.5、0.75 或 1')
        if hand_mode not in ('both','left','right'):raise ValueError('无效的试听手别')
        if len(tracks)!=len(self.score.tracks) or {t['id'] for t in tracks}!={t['id'] for t in self.score.tracks}:raise ValueError('轨道配置不完整')
        settings={t['id']:t for t in tracks}
        cfg=dict(rate=float(rate),hand_mode=hand_mode,tracks=[dict(t,muted=bool(settings[t['id']]['muted']),solo=bool(settings[t['id']]['solo'])) for t in self.score.tracks])
        score=replace(self.score,revision=self.score.revision+1)
        return self._begin(lambda cancel,update:(score,cfg,False),resume=self.audio.playing)
    async def preview_hands(self,rule):
        self._available();score=self.score
        values,counts=await asyncio.to_thread(preview,score,rule)
        if self.score is not score:raise ValueError('曲目已改变，请重新预览')
        pid=uuid.uuid4().hex;self.previews[pid]={'score_id':score.score_id,'revision':score.revision,'values':values}
        self.previews={k:v for k,v in list(self.previews.items())[-8:]}
        return dict(preview_id=pid,counts=counts,score_id=score.score_id,revision=score.revision,generation=self.generation)
    def apply_hands(self,preview_id,overrides):
        self._available();p=self.previews.get(preview_id)
        if not p or p['score_id']!=self.score.score_id or p['revision']!=self.score.revision:raise ValueError('分配预览已过期')
        score=assigned(self.score,p['values'],overrides);cfg=copy.deepcopy(self.config)
        return self._begin(lambda cancel,update:(score,cfg,False),history=('push',dict(values={n.id:n.hand for n in self.score.notes},sources={n.id:n.hand_source for n in self.score.notes},assignment=copy.deepcopy(self.score.hand_assignment))))
    def undo_hands(self):
        self._available()
        if not self.history:raise ValueError('没有可撤销的分配')
        previous=self.history[-1];score=assigned(self.score,previous['values'],{})
        score.notes=[replace(n,hand_source=previous['sources'][n.id]) for n in score.notes];score.hand_assignment=previous['assignment']
        cfg=copy.deepcopy(self.config)
        return self._begin(lambda cancel,update:(score,cfg,False),history=('pop',None))
    async def set_loop(self,enabled,a_s,b_s):
        async with self.command_lock:
            self._available();a_s=float(a_s);b_s=float(b_s)
            if not math.isfinite(a_s+b_s) or not 0<=a_s<b_s<=self.score.duration_s or b_s-a_s<.5:raise ValueError('循环范围需在曲目内，且至少 0.5 秒')
            resume=self.audio.playing;pos=await self.audio.fade_halt()
            self.audio.loop=dict(enabled=bool(enabled),a_s=a_s,b_s=b_s)
            if enabled and not a_s<=pos<b_s:pos=a_s
            self.audio.set_position(pos)
            if resume:self.audio.start()
            return self.get_transport()
    def set_volume(self,value):
        value=float(value)
        if not math.isfinite(value) or not 0<=value<=1:raise ValueError('音量需在 0–100% 内')
        self.audio.volume=value;return value
    def _audio_error(self,message):
        self.audio.halt();self.audio.ready=False;self.phase='error'
        self.error=dict(code='AUDIO_DEVICE_UNAVAILABLE',message=message,recoverable=True)
    async def retry_audio(self):
        async with self.command_lock:
            if self.current_job:raise ValueError('声音正在准备，请稍候或取消')
            old_sr=self.audio.sample_rate;self.audio.halt()
            if self.audio.open():
                self.error=None;self.phase='paused' if self.score else 'empty'
                if self.score and old_sr!=self.audio.sample_rate:
                    self._begin(lambda cancel,update:(self.score,copy.deepcopy(self.config),False))
            else:self._audio_error('未找到声音输出设备')
            return self.get_transport()
    def get_transport(self):
        pos,tail,ended=self.audio.clock()
        if self.phase=='playing' and (not self.audio.ready or self.audio.stream and not self.audio.stream.active):
            self._audio_error('声音输出设备已断开')
        if ended:
            self.audio.halt();self.audio.position=self.score.duration_s;self.phase='ended'
        self.seq+=1;score=self.score
        active=[]
        if self.audio.playing and score:
            lo=bisect.bisect_right(self.note_ends,pos);hi=bisect.bisect_right(self.note_starts,pos)
            active=[n.id for n in self.audible[lo:hi] if n.start_s<=pos<n.key_off_s]
        return dict(phase=self.phase,score_id=score.score_id if score else None,revision=score.revision if score else 0,generation=self.generation,
            seq=self.seq,clock_epoch=self.audio.epoch,position_s=pos,duration_s=score.duration_s if score else 0,rate=self.config['rate'] if self.config else 1.,
            loop=self.audio.loop,volume=self.audio.volume,active_note_ids=active,notation_position=self.notation.position(pos),output_latency_s=float(self.audio.stream.latency) if self.audio.stream else None,
            hand_mode=self.config['hand_mode'] if self.config else 'both',hand_status=self.session.hand_status,
            unassigned_notes=sum(n.hand=='unassigned' for n in score.notes) if score else 0,tail_active=tail,audio_ready=self.audio.ready,error=self.error)
    def get_analysis(self,after_seq):
        if not self.score:return None
        now=time.monotonic();key=(self.score.score_id,self.score.revision,self.generation,self.audio.epoch)
        if self.analysis_future and self.analysis_future.done():
            data,fkey,pos=self.analysis_future.result();self.analysis_future=None
            if fkey==key:
                self.analysis_seq+=1;self.analysis_frame=dict(data,seq=self.analysis_seq,score_id=key[0],revision=key[1],generation=key[2],clock_epoch=key[3],position_s=pos)
        if self.analysis_future is None and now-self.analysis_last_at>=.05:
            data=self.audio.heard_window();sr=self.audio.sample_rate;pos=self.audio.clock()[0]
            self.analysis_future=self.analysis_pool.submit(lambda:(analyze(data,sr),key,pos));self.analysis_last_at=now
        if not self.audio.playing or not self.audio.volume:
            self.analysis_seq+=1
            return dict(seq=self.analysis_seq,score_id=key[0],revision=key[1],generation=key[2],clock_epoch=key[3],position_s=self.audio.position,waveform=[0.]*256,spectrum_db=[-90.]*128,frequency_min_hz=20,frequency_max_hz=min(20000,self.audio.sample_rate/2))
        if self.analysis_frame and self.analysis_frame['seq']>after_seq and self.analysis_frame['generation']==self.generation and self.analysis_frame['clock_epoch']==self.audio.epoch:
            if not self.audio.playing or not self.audio.volume:
                return dict(self.analysis_frame,waveform=[0.]*256,spectrum_db=[-90.]*128)
            return self.analysis_frame
        return None
    def close(self):
        if self.closed:return
        self.closed=True;self.phase='closing';self.generation+=1;self.audio.close();self.notation.close()
        for job in self.jobs.values():job['cancel'].set()
        self.pool.shutdown(wait=True,cancel_futures=True);self.analysis_pool.shutdown(wait=True,cancel_futures=True)
        self.score=None;self.phase='closed'
