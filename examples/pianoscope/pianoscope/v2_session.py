"""MusicXML session transactions. Only the application thread publishes audio."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import asyncio
import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager,asynccontextmanager
from .score_player import ScorePlayer,serialized
from .score_source import read_source, source_from_bytes, ScoreInputError
from .score_model import parse_score
from .playback_plan import compile_plan
from .midi_compile import compile_midi, sound_score
from .score_mapping import json_value
from .score_process import run_preparation
from .render import render, audible_notes
from .pcm_budget import require_pcm_budget
from .analysis import overview, analyze
from .dialogs import choose_path, choose_score_path

ROOT = Path(__file__).resolve().parents[3]
DEMO = Path(__file__).parent / 'resources/demos'


class Controller(ScorePlayer):
    def __init__(self, audio=None):
        super().__init__(audio=audio)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='pianoscope-score')
        self.preparation_lock = threading.Lock()
        self.jobs, self.paths, self.targets = {}, {}, {}
        self.candidates, self.confirmations, self.layout_candidates = {}, {}, {}
        self.current_layout_job = None
        self.current_job = None
        self.generation = self.configuration_generation = self.folder_generation = 0
        self.active = None
        self.library = dict(folder_name='', songs=[])
        self.hands = {}
        self.hand_preview = None
        self.hand_history = []
        self.analysis_seq = 0
        self.workspace = Path(os.environ.get('PIANOSCOPE_TMP_DIR', ROOT / '.tmp/pianoscope')) / 'v2/jobs'
        self.workspace.mkdir(parents=True, exist_ok=True)

    def token_for_path(self, path):
        token = uuid.uuid4().hex
        self.paths[token] = Path(path).expanduser().resolve()
        return token

    def _path(self, token):
        if token in ('demo:first-light','demo:harmonics'):
            return DEMO / ('first-light.musicxml' if token.endswith('first-light') else 'temporal.musicxml')
        if token not in self.paths:
            raise ValueError('文件选择已过期，请重新打开乐谱')
        return self.paths[token]

    def choose_score(self, auto_cancel=False):
        path = choose_path(auto_cancel=auto_cancel,extensions=['musicxml','xml','mxl'],label='乐谱')
        return self.token_for_path(path) if path else None

    async def choose_score_folder(self, auto_cancel=False):
        path = choose_path(auto_cancel=auto_cancel,folder=True,label='乐谱')
        return await self.open_score_folder(str(path)) if path else None

    async def open_score_folder(self, path):
        # The native selector/CLI supplies paths; this method is not registered
        # publicly. JS only receives tokens, never arbitrary directory authority.
        self.folder_generation += 1
        generation = self.folder_generation
        def scan():
            directory = Path(path).expanduser().resolve()
            files = []
            for entry in directory.iterdir():
                if entry.is_file() and entry.suffix.lower() in ('.xml','.musicxml','.mxl'):
                    files.append(entry)
                    if len(files) > 1000:
                        raise ValueError('曲库超过 1,000 首，请选择较小的文件夹')
            return directory, sorted(files,key=lambda p:p.name.casefold())
        directory, files = await asyncio.to_thread(scan)
        if generation != self.folder_generation or self.closed:
            return self.get_score_library()
        self.library = dict(folder_name=directory.name, songs=[dict(name=p.name,file_token=self.token_for_path(p)) for p in files])
        return self.get_score_library()

    def get_score_library(self):
        return copy.deepcopy(self.library)

    def begin_score_load(self, token, settings=None):
        path = self._path(str(token))
        return self._begin_load(path, settings or {})

    def _begin_load(self, path, settings, snapshot=None):
        if self.closed:
            raise ValueError('应用已关闭')
        if self.current_job:
            self.cancel_job(self.current_job)
        if self.current_layout_job:
            self.cancel_job(self.current_layout_job)
        self.generation += 1
        self.configuration_generation+=1
        generation = self.generation
        jid = uuid.uuid4().hex
        folder = self.workspace / jid
        folder.mkdir()
        cancel = threading.Event()
        job = dict(job_id=jid,generation=generation,kind='load',phase='reading',done=False,cancelled=False,error=None,
                   cancel=cancel,lock=threading.Lock(),folder=folder,source_path=path,settings=copy.deepcopy(settings))
        self.jobs[jid] = job
        self.current_job = jid
        def check():
            return cancel.is_set() or self.closed or generation != self.generation
        def work():
            with self._preparing(check):
                if check():
                    raise InterruptedError('已取消')
                source = snapshot or read_source(path,check)
                document = parse_score(source,settings,check)
                document.revision += ':'+jid
                if document.needs_confirmation:
                    return dict(confirmation=True,source=source,required=document.needs_confirmation,title=document.title)
                job['phase'] = 'compiling'
                plan = compile_plan(document,settings,check)
                compile_midi(plan)
                # Playback can publish without engraving. No native notation
                # worker, PDF, page image, or image decode runs on this path.
                result = dict(manifest=dict(layout_revision=None,pages=[]))
                (folder/'score.mid').write_bytes(plan.midi_bytes)
                job['phase'] = 'synthesizing'
                config = dict(rate=1.,hand_mode='both',tracks=[dict(id=p['id'],muted=False,solo=False) for p in document.parts])
                count = round((plan.duration_s+2)*self.audio.sample_rate)*8
                current_bytes = self.audio.pcm.nbytes if self.audio.pcm is not None else 0
                require_pcm_budget(count,current_bytes)
                rendered_sample_rate=self.audio.sample_rate
                pcm = render(sound_score(plan),config,rendered_sample_rate,check)
                if check():
                    raise InterruptedError('已取消')
                return dict(plan=plan,pcm=pcm,data=result,folder=folder,source_path=path,
                            overview=overview(pcm,1400),config=config,sample_rate=rendered_sample_rate)
        job['future'] = self.pool.submit(work)
        self._prune()
        return dict(job_id=jid,generation=generation)

    @contextmanager
    def _preparing(self,cancelled):
        while not self.preparation_lock.acquire(timeout=.05):
            if cancelled():
                raise InterruptedError('已取消')
        try:
            if cancelled():
                raise InterruptedError('已取消')
            yield
        finally:
            self.preparation_lock.release()

    @asynccontextmanager
    async def _audio_candidate(self,cancelled):
        stop=threading.Event()
        acquired=threading.Event()
        def acquire():
            while not (stop.is_set() or cancelled()):
                if self.preparation_lock.acquire(timeout=.05):
                    acquired.set()
                    return
            raise InterruptedError('试听已过期')
        task=asyncio.create_task(asyncio.to_thread(acquire))
        try:
            await asyncio.shield(task)
            if cancelled():
                raise InterruptedError('试听已过期')
            yield
        finally:
            stop.set()
            try:
                await asyncio.shield(task)
            finally:
                if acquired.is_set():
                    self.preparation_lock.release()

    def _collect(self, job):
        future = job.get('future')
        if future is None or not future.done():
            return
        del job['future']
        try:
            candidate = future.result()
            if job['done'] or job['cancel'].is_set() or job['generation'] != self.generation:
                return
            if job['kind'] == 'layout':
                if job['snapshot'] is not self.active:
                    raise InterruptedError('谱面已过期')
                self.layout_candidates[job['job_id']] = candidate
                job.update(phase='layout_ready')
            elif candidate.get('confirmation'):
                self.confirmations[job['job_id']] = candidate
                job.update(phase='needs_confirmation',required=candidate['required'],source_sha256=candidate['source'].sha256,title=candidate['title'])
            else:
                self.candidates[job['job_id']] = candidate
                job.update(phase='candidate_ready',source_sha256=candidate['plan'].document.source.sha256)
        except InterruptedError:
            if not job['done']:
                job.update(done=True,cancelled=True,phase='cancelled')
        except Exception as exc:
            if not job['done']:
                job.update(done=True,phase='failed',error=dict(message=str(exc),code=getattr(exc,'code','SCORE_PREPARE_FAILED'),issues=getattr(exc,'issues',[])))

    def get_job(self, job_id):
        if job_id not in self.jobs:
            raise ValueError('作业已过期')
        job = self.jobs[job_id]
        self._collect(job)
        return {k:json_value(job[k]) for k in ('job_id','generation','kind','phase','done','cancelled','error','required','source_sha256','title','filename') if k in job}

    def cancel_job(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return False
        with job['lock']:
            if not job['done']:
                job['cancel'].set()
                job.update(done=True,cancelled=True,phase='cancelled')
                self.candidates.pop(job_id,None)
                self.layout_candidates.pop(job_id,None)
                self.confirmations.pop(job_id,None)
                future=job.pop('future',None)
                if future is not None:
                    future.cancel()
        return True

    def confirm_score_load(self, pending_id, source_sha256, settings):
        pending = self.confirmations.get(pending_id)
        job = self.jobs.get(pending_id)
        if not pending or not job or job['done'] or job['generation'] != self.generation or pending['source'].sha256 != source_sha256:
            raise ValueError('确认已过期，请重新打开乐谱')
        merged = dict(job['settings'],**settings)
        return self._begin_load(job['source_path'],merged,pending['source'])

    def _candidate(self, job_id):
        self.get_job(job_id)
        if job_id != self.current_job or job_id not in self.candidates or self.jobs[job_id]['done']:
            raise ValueError('候选已过期')
        return self.candidates[job_id]

    def get_candidate(self, job_id):
        c = self._candidate(job_id)
        manifest = c['data']['manifest']
        return dict(job_id=job_id,title=c['plan'].document.title,source_sha256=c['plan'].document.source.sha256,
                    source_revision=c['plan'].document.revision,layout_revision=manifest['layout_revision'],
                    playback_revision=c['plan'].revision,notes_count=len(c['plan'].instances),overview=c['overview'],
                    pages=[dict(page=i,width=p['width'],height=p['height'],resource=f'score-{job_id}-{i}.png') for i,p in enumerate(manifest['pages'])])

    def get_score_page(self, layout_id, page, candidate_id=None):
        c = (self._layout_candidate(candidate_id) if candidate_id in self.layout_candidates else self._candidate(candidate_id)) if candidate_id else self.active
        if not c or not layout_id or c['data']['manifest']['layout_revision'] != layout_id:
            raise ValueError('谱面版本已过期')
        page = int(page)
        pages = c['data']['manifest']['pages']
        if not 0 <= page < len(pages):
            raise ValueError('页码超出范围')
        return json_value(pages[page])

    def _prepare_layout(self, snapshot, folder, cancelled):
        source = snapshot['plan'].document.source
        folder.mkdir(exist_ok=True)
        input_path = folder / ('input' + Path(source.original_name).suffix.lower())
        input_path.write_bytes(source.original_bytes)
        request = dict(source_path=str(input_path),original_name=source.original_name,
                       settings=snapshot['plan'].settings,source_revision=snapshot['plan'].document.revision)
        (folder/'request.json').write_text(json.dumps(request,ensure_ascii=False))
        result = run_preparation(folder,cancelled)
        if result['source_sha256'] != source.sha256 or result['source_revision'] != request['source_revision'] or (folder/'score.mid').read_bytes() != snapshot['plan'].midi_bytes:
            raise ValueError('谱面与当前来源／播放编译不一致')
        return dict(data=result,folder=folder)

    def begin_score_layout(self, source_revision):
        if not self.active or self.plan.document.revision != source_revision:
            raise ValueError('乐谱已过期')
        if self.active['data']['manifest']['layout_revision']:
            return dict(ready=True,**self._layout_descriptor(self.active,None))
        if self.current_layout_job:
            job=self.jobs.get(self.current_layout_job)
            if job and not job['done'] and job['snapshot'] is self.active:
                return dict(job_id=job['job_id'],ready=False)
        snapshot=self.active
        jid=uuid.uuid4().hex
        folder=self.workspace/jid
        cancel=threading.Event()
        job=dict(job_id=jid,generation=self.generation,kind='layout',phase='engraving',done=False,
                 cancelled=False,error=None,cancel=cancel,lock=threading.Lock(),folder=folder,snapshot=snapshot)
        self.jobs[jid]=job
        self.current_layout_job=jid
        def check():
            return cancel.is_set() or self.closed or snapshot is not self.active or job['generation']!=self.generation
        def work():
            with self._preparing(check):
                return self._prepare_layout(snapshot,folder,check)
        job['future']=self.pool.submit(work)
        self._prune()
        return dict(job_id=jid,ready=False)

    def _layout_candidate(self, job_id):
        self.get_job(job_id)
        job=self.jobs[job_id]
        if job['done'] or job_id not in self.layout_candidates or job['snapshot'] is not self.active or job['generation']!=self.generation:
            raise ValueError('谱面候选已过期')
        return self.layout_candidates[job_id]

    def _layout_descriptor(self, candidate, candidate_id):
        manifest=candidate['data']['manifest']
        resource_id=candidate_id or candidate['layout_job_id']
        return dict(candidate_id=candidate_id,source_revision=manifest['source_revision'],layout_revision=manifest['layout_revision'],
                    pages=[dict(page=i,width=p['width'],height=p['height'],resource=f'score-{resource_id}-{i}.png') for i,p in enumerate(manifest['pages'])])

    def get_layout_candidate(self, job_id):
        return self._layout_descriptor(self._layout_candidate(job_id),job_id)

    def publish_score_layout(self, job_id, source_revision, layout_revision):
        candidate=self._layout_candidate(job_id)
        manifest=candidate['data']['manifest']
        if self.plan.document.revision!=source_revision or manifest['source_revision']!=source_revision or manifest['layout_revision']!=layout_revision:
            raise ValueError('谱面来源已过期')
        # Called only after all real page images decoded. Audio and playback
        # revisions/clock are untouched by this independently atomic commit.
        self.active.update(data=candidate['data'],layout_folder=candidate['folder'],layout_job_id=job_id)
        self.jobs[job_id].update(done=True,phase='completed')
        self.layout_candidates.pop(job_id)
        return self.get_document()

    def resource(self, name):
        candidates=list(self.layout_candidates.items())
        if self.active and self.active['data']['manifest']['layout_revision']:
            candidates.append((self.active['layout_job_id'],self.active))
        for jid,c in candidates:
            for i in range(len(c['data']['manifest']['pages'])):
                if name == f'score-{jid}-{i}.png':
                    return (c.get('layout_folder',c['folder'])/f'page-{i+1}.png').read_bytes()
        return None

    @serialized
    async def publish_score_load(self, job_id, source_sha256):
        c = self._candidate(job_id)
        if c['plan'].document.source.sha256 != source_sha256:
            raise ValueError('候选来源已过期')
        if c['sample_rate']!=self.audio.sample_rate:
            raise ValueError('声音设备采样率已改变，请重新打开乐谱')
        old = self.active
        position = self.audio.clock()[0]
        was_playing = self.audio.playing
        old_pcm, old_rate, old_duration = self.audio.pcm,self.audio.rate,self.audio.duration
        old_loop = dict(self.audio.loop)
        try:
            self.install(c['plan'],c['pcm'])
        except Exception:
            if old_pcm is not None:
                self.audio.install(old_pcm,old_rate,old_duration,position)
                self.audio.loop = old_loop
                if was_playing:
                    self.audio.start()
            raise
        c['job_id'] = job_id
        self.active = c
        self.hands,self.hand_history,self.hand_preview = {},[],None
        self.configuration_generation += 1
        self.jobs[job_id].update(done=True,phase='completed')
        del self.candidates[job_id]
        # The only retained PCM reference is the installed buffer.
        c.pop('pcm',None)
        if old:
            old.pop('pcm',None)
        return self.get_document()

    def get_document(self):
        if not self.active:
            return None
        plan, document = self.plan,self.plan.document
        return dict(title=document.title,original_name=document.source.original_name,source_sha256=document.source.sha256,
                    source_revision=document.revision,playback_revision=plan.revision,
                    layout_revision=self.active['data']['manifest']['layout_revision'],
                    duration_s=plan.duration_s,notes_count=len(plan.instances),source_notes=sum(e.pitch is not None for e in document.elements),
                    parts=document.parts,staff_ids=sorted({e.staff_id for e in document.elements}),
                    voices=sorted({e.part_id+':'+e.voice_id for e in document.elements}),
                    occurrences=json_value(plan.occurrences),hand_status='confirmed' if self.hands else 'unassigned',
                    used_pitches=sorted({e.pitch for e in document.elements if e.pitch is not None}),
                    pages=len(self.active['data']['manifest']['pages']),layout_ready=bool(self.active['data']['manifest']['layout_revision']),
                    diagnostics_count=len(plan.diagnostics)+len(self.active['data']['manifest'].get('layout_diagnostics',[])),ready=True)

    def get_capabilities(self):
        return dict(profile='V2-P0-2',formats=['musicxml','xml','mxl'],root='score-partwise',versions=['3.1','4.0'],
                    repeat='non-nested, first/second endings',midi_channels=15,ppqn_max=32767,
                    ornaments=['arpeggiate: bounded 1/16-quarter spread','measured tremolo: single or same-bar paired note/chord'],
                    unsupported=['grace','other-ornaments','unmeasured-or-cross-bar-tremolo','nested-repeat','DC/DS/Fine/Coda','microtones','nonzero-transpose','unpitched'])

    def get_diagnostics(self, cursor=0):
        if not self.plan:
            return dict(total=0,items=[],next_cursor=None)
        items=self.plan.diagnostics+self.active['data']['manifest'].get('layout_diagnostics',[])
        cursor=max(0,int(cursor))
        return dict(total=len(items),items=items[cursor:cursor+100],next_cursor=cursor+100 if cursor+100<len(items) else None)

    def get_notes(self, offset=0, limit=1000, candidate_id=None):
        plan=self._candidate(candidate_id)['plan'] if candidate_id else self.plan
        if not plan:
            return dict(notes=[],total=0)
        offset=max(0,int(offset));limit=max(1,min(2000,int(limit)))
        return dict(playback_revision=plan.revision,total=len(plan.instances),
                    notes=json_value(plan.instances[offset:offset+limit]))

    def get_overview(self):
        return self.active['overview'] if self.active else None

    def get_analysis(self):
        self.analysis_seq+=1
        return dict(analyze(self.audio.heard_window(),self.audio.sample_rate),seq=self.analysis_seq,clock_epoch=self.audio.epoch)

    def get_transport(self):
        result=super().get_transport()
        return dict(result,generation=self.generation,layout_revision=self.active['data']['manifest']['layout_revision'] if self.active else None,
                    hand_mode=self.config['hand_mode'] if self.config else 'both',hand_status='confirmed' if self.hands else 'unassigned')

    def _same_audio(self, next_score, next_config):
        # Labels and equivalent scope selections need no second PCM. The
        # synthesizer consumes these event fields, not hand/source labels.
        if self.audio.pcm is None or self.active['sample_rate']!=self.audio.sample_rate or self.config['rate']!=next_config['rate']:
            return False
        def events(score,config):
            return [(n.id,n.track_id,n.pitch,n.velocity,n.start_s,n.key_off_s,n.sustain_end_s)
                    for n in audible_notes(score,config)]
        return events(self.score,self.config)==events(next_score,next_config)

    async def configure(self, changes):
        if self.plan is None:
            raise ValueError('请先打开乐谱')
        if self.current_job and not self.jobs[self.current_job]['done']:
            raise ValueError('请先完成或取消乐谱准备，再更改试听')
        changes=dict(changes)
        if any(k not in ('rate','hand_mode','staff_ids','voice_ids') for k in changes):
            raise ValueError('未知试听设置')
        if changes.get('hand_mode','both') not in ('both','left','right'):
            raise ValueError('试听手别无效')
        if changes.get('hand_mode','both')!='both' and not self.hands:
            raise ValueError('请先预览并确认手别')
        document=self.get_document()
        for key,available in (('staff_ids',document['staff_ids']),('voice_ids',document['voices'])):
            if key in changes and changes[key] is not None and any(v not in available for v in changes[key]):
                raise ValueError('试听范围已过期')
        config=dict(self.config,**changes)
        if config['rate'] not in (.5,.75,1.):
            raise ValueError('仅支持 0.5×／0.75×／1×')
        config['allowed_note_ids']=[n['id'] for n in self.plan.instances
            if (config.get('staff_ids') is None or n['staff_id'] in config['staff_ids'])
            and (config.get('voice_ids') is None or n['part_id']+':'+n['voice_id'] in config['voice_ids'])]
        self.configuration_generation+=1
        generation=self.configuration_generation
        plan=self.plan
        def cancelled():
            return self.closed or self.plan is not plan or generation!=self.configuration_generation
        if self._same_audio(self.score,config):
            async with self.command_lock:
                if cancelled():raise ValueError('试听已过期')
                self.config=config
                return self.get_transport()
        def work():
            count=round((plan.duration_s/config['rate']+2)*self.audio.sample_rate)*8
            require_pcm_budget(count,self.audio.pcm.nbytes)
            return render(self.score,config,self.audio.sample_rate,cancelled)
        async with self._audio_candidate(cancelled):
            pcm=None
            try:
                pcm=await asyncio.to_thread(work)
                if cancelled():
                    raise ValueError('试听已过期')
                async with self.command_lock:
                    position=await self.audio.fade_halt()
                    if cancelled():
                        raise ValueError('试听已过期')
                    self.audio.install(pcm,config['rate'],plan.duration_s,position)
                    self.config=config
                    self.active['sample_rate']=self.audio.sample_rate
                    if self.phase=='playing':
                        self.audio.start()
                    return self.get_transport()
            finally:
                pcm=None

    def preview_hands(self, assignments):
        if not self.plan:
            raise ValueError('请先打开乐谱')
        known={e.id for e in self.plan.document.elements if e.pitch is not None}
        assignments={str(k):str(v) for k,v in assignments.items()}
        if any(k not in known or v not in ('left','right','unassigned') for k,v in assignments.items()):
            raise ValueError('手别指派包含未知源音符')
        merged=dict(self.hands,**assignments)
        preview_id=uuid.uuid4().hex
        self.hand_preview=dict(id=preview_id,source_revision=self.plan.document.revision,hands=merged)
        counts={h:sum(merged.get(e.id,'unassigned')==h for e in self.plan.document.elements if e.pitch is not None) for h in ('left','right','unassigned')}
        return dict(preview_id=preview_id,counts=counts)

    def get_source_elements(self):
        return [dict(element_id=e.id,staff_id=e.staff_id,voice_id=e.part_id+':'+e.voice_id) for e in self.plan.document.elements if e.pitch is not None] if self.plan else []

    def get_practice_settings(self):
        """Return the applied settings, including empty scopes and mixed labels."""
        if not self.plan:
            raise ValueError('请先打开乐谱')
        document=self.get_document()
        elements=[e for e in self.plan.document.elements if e.pitch is not None]
        staves=[]
        for index,ident in enumerate(document['staff_ids']):
            labels={self.hands.get(e.id,'unassigned') for e in elements if e.staff_id==ident}
            paired=len(document['staff_ids'])==2 or len(document['parts'])==1 and document['parts'][0]['staves']==2
            name=('上谱表' if index==0 else '下谱表') if paired else '谱表 '+str(index+1)
            staves.append(dict(id=ident,name=name,notes=sum(e.staff_id==ident for e in elements),
                               hand=next(iter(labels)) if len(labels)==1 else 'mixed' if labels else 'unassigned',
                               suggestion='right' if index==0 else 'left'))
        voices=[]
        for ident in document['voices']:
            sources={e.staff_id for e in elements if e.part_id+':'+e.voice_id==ident}
            staff_name=next((s['name'] for s in staves if s['id'] in sources),'') if len(sources)==1 else '跨谱表'
            voices.append(dict(id=ident,name=staff_name+' · 声部 '+ident.rsplit(':',1)[-1]))
        return dict(source_revision=self.plan.document.revision,staves=staves,voices=voices,
                    staff_ids=list(self.config.get('staff_ids')) if self.config.get('staff_ids') is not None else document['staff_ids'],
                    voice_ids=list(self.config.get('voice_ids')) if self.config.get('voice_ids') is not None else document['voices'],
                    hand_mode=self.config['hand_mode'],hand_status=document['hand_status'],can_undo=bool(self.hand_history))

    async def apply_hands(self, preview_id):
        preview=self.hand_preview
        if not preview or preview['id']!=preview_id or preview['source_revision']!=self.plan.document.revision:
            raise ValueError('手别预览已过期')
        old=dict(self.hands)
        await self._set_hands(preview['hands'])
        self.hand_history.append(old)
        self.hand_preview=None
        return self.get_document()

    async def _set_hands(self, assignments):
        if self.current_job and not self.jobs[self.current_job]['done']:
            raise ValueError('请先完成或取消乐谱准备，再更改手别')
        old_plan=self.plan
        next_plan=compile_plan(old_plan.document,dict(old_plan.settings,hands=assignments))
        compile_midi(next_plan)
        for n in next_plan.instances:
            n['hand']=assignments.get(n['element_ids'][0],'unassigned')
            n['hand_source']='confirmed_source_label' if n['hand']!='unassigned' else 'unknown'
        next_score=sound_score(next_plan)
        self.configuration_generation+=1
        generation=self.configuration_generation
        def cancelled():
            return self.closed or self.plan is not old_plan or generation!=self.configuration_generation
        config=copy.deepcopy(self.config)
        if not assignments:
            config['hand_mode']='both'
        if self._same_audio(next_score,config):
            async with self.command_lock:
                if cancelled():raise ValueError('手别预览已过期')
                self.plan,self.score,self.hands,self.config=next_plan,next_score,dict(assignments),config
                self.active['plan']=next_plan
                return
        def work():
            count=round((next_plan.duration_s/config['rate']+2)*self.audio.sample_rate)*8
            require_pcm_budget(count,self.audio.pcm.nbytes)
            return render(next_score,config,self.audio.sample_rate,cancelled)
        async with self._audio_candidate(cancelled):
            pcm=None
            try:
                pcm=await asyncio.to_thread(work)
                if cancelled():
                    raise ValueError('手别预览已过期')
                async with self.command_lock:
                    position=await self.audio.fade_halt()
                    if cancelled():
                        raise ValueError('手别预览已过期')
                    self.audio.install(pcm,config['rate'],next_plan.duration_s,position)
                    self.plan,self.score,self.hands,self.config=next_plan,next_score,dict(assignments),config
                    self.active['plan']=next_plan
                    self.active['sample_rate']=self.audio.sample_rate
                    if self.phase=='playing':
                        self.audio.start()
            finally:
                pcm=None

    async def undo_hands(self):
        if not self.hand_history:
            return self.get_document()
        old=self.hand_history[-1]
        await self._set_hands(old)
        self.hand_history.pop()
        return self.get_document()

    def choose_export(self, document_id, format, auto_cancel=False):
        if not self.active or document_id!=self.plan.document.revision or format not in ('pdf','source','midi'):
            raise ValueError('导出版本或格式已过期')
        snapshot=self.active
        suffix=Path(self.plan.document.source.original_name).suffix.lower().lstrip('.') if format=='source' else 'mid' if format=='midi' else 'pdf'
        path=choose_score_path(self.plan.document.title,suffix,auto_cancel=auto_cancel)
        if path is None:
            return None
        if self.active is not snapshot:
            raise ValueError('保存窗口期间曲目已改变，请重新导出')
        target=Path(path).resolve()
        source_path=snapshot['source_path']
        if target==source_path or target.exists() and source_path.exists() and os.path.samefile(target,source_path):
            raise ValueError('不能覆盖当前输入源文件')
        token=uuid.uuid4().hex
        self.targets[token]=dict(snapshot=snapshot,path=target,format=format)
        return dict(target_token=token,snapshot_id=document_id,format=format,filename=target.name)

    def begin_export(self, snapshot_id, format, target_token):
        target=self.targets.pop(target_token,None)
        if not target or target['snapshot'] is not self.active or snapshot_id!=self.plan.document.revision or target['format']!=format:
            raise ValueError('导出目标已过期，请重新保存')
        snapshot=target['snapshot']
        source=snapshot['plan'].document.source
        data=source.original_bytes if format=='source' else snapshot['plan'].midi_bytes if format=='midi' else None
        jid=uuid.uuid4().hex
        job=dict(job_id=jid,generation=self.generation,kind='export',phase='writing',done=False,cancelled=False,error=None,
                 cancel=threading.Event(),lock=threading.Lock(),filename=target['path'].name)
        self.jobs[jid]=job
        def work():
            temporary=None
            try:
                payload=data
                if format=='pdf':
                    job['phase']='engraving'
                    def cancelled():
                        return job['cancel'].is_set() or self.closed
                    # An export owns its immutable source snapshot even when
                    # the active song changes. It never publishes UI geometry.
                    with self._preparing(cancelled):
                        folder=self.workspace/jid
                        job['folder']=folder
                        self._prepare_layout(snapshot,folder,cancelled)
                        payload=(folder/'score.pdf').read_bytes()
                    job['phase']='writing'
                with tempfile.NamedTemporaryFile(prefix='.pianoscope-',dir=target['path'].parent,delete=False) as stream:
                    temporary=Path(stream.name)
                    for offset in range(0,len(payload),64*1024):
                        if job['cancel'].is_set() or self.closed:
                            raise InterruptedError('已取消')
                        stream.write(payload[offset:offset+64*1024])
                    stream.flush();os.fsync(stream.fileno())
                if hashlib.sha256(temporary.read_bytes()).digest()!=hashlib.sha256(payload).digest():
                    raise OSError('导出文件校验不一致')
                with job['lock']:
                    if job['cancel'].is_set() or self.closed:
                        raise InterruptedError('已取消')
                    os.replace(temporary,target['path'])
                    temporary=None
                    job.update(done=True,phase='completed')
            except InterruptedError:
                with job['lock']:
                    job.update(done=True,cancelled=True,phase='cancelled')
            except Exception as exc:
                with job['lock']:
                    if job['phase']!='completed':
                        job.update(done=True,phase='failed',error=dict(message=str(exc),code='EXPORT_FAILED'))
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        # No PCM-bearing future or result is retained by an export job.
        self.pool.submit(work)
        return dict(job_id=jid)

    async def retry_audio(self):
        if self.current_job and not self.jobs[self.current_job]['done']:
            raise ValueError('请先完成或取消乐谱准备，再重试设备')
        self.configuration_generation+=1
        generation=self.configuration_generation
        plan=self.plan
        def cancelled():
            return self.closed or self.plan is not plan or generation!=self.configuration_generation
        async with self._audio_candidate(cancelled):
            async with self.command_lock:
                position=await self.audio.fade_halt()
                before=self.active.get('sample_rate',self.audio.sample_rate) if self.active else self.audio.sample_rate
                self.audio.open()
                self.phase='paused' if plan else 'empty'
                if self.audio.ready and plan and self.audio.sample_rate!=before:
                    count=round((plan.duration_s/self.config['rate']+2)*self.audio.sample_rate)*8
                    try:
                        require_pcm_budget(count,self.audio.pcm.nbytes)
                    except ValueError as exc:
                        self.audio.ready=False
                        self.audio.error=str(exc)
                    else:
                        try:
                            pcm=await asyncio.to_thread(render,self.score,self.config,self.audio.sample_rate,cancelled)
                        except Exception as exc:
                            self.audio.ready=False
                            self.audio.error='新设备的声音准备失败：'+str(exc)
                            raise
                        if cancelled():
                            raise ValueError('设备准备已过期')
                        self.audio.install(pcm,self.config['rate'],plan.duration_s,position)
                        self.active['sample_rate']=self.audio.sample_rate
                elif plan:
                    self.audio.set_position(position)
                return self.get_transport()

    def _prune(self):
        for jid,job in list(self.jobs.items())[:-16]:
            if job['done'] and 'future' not in job:
                del self.jobs[jid]
                folder=job.get('folder')
                if folder and (not self.active or folder not in (self.active['folder'],self.active.get('layout_folder'))):
                    shutil.rmtree(folder,ignore_errors=True)

    def close(self):
        if self.closed:
            return
        self.closed=True
        for jid in list(self.jobs):
            self.cancel_job(jid)
        self.audio.close()
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.candidates.clear();self.confirmations.clear();self.layout_candidates.clear();self.active=None
