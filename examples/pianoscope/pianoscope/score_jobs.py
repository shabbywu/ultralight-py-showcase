"""Preview/application/export transactions, separate from audio generations."""
from concurrent.futures import ThreadPoolExecutor,Future
from dataclasses import asdict
from collections import Counter
from pathlib import Path
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from .notation import dependency,NotationError,Options

class ScoreJobs:
    def __init__(self,controller):
        self.controller=controller;self.root=Path(tempfile.mkdtemp(prefix='pianoscope-score-'))
        self.pool=ThreadPoolExecutor(1,thread_name_prefix='pianoscope-score')
        self.jobs={};self.previews={};self.applied=None;self.targets={};self.closed=False
        self.lock=threading.RLock();self.latest=None;self.resources={};self.position_cache=None

    def _current(self):
        if self.closed or not self.controller.score:raise NotationError('请先打开 MIDI。','NOTATION_OPTIONS_REQUIRED')
        return self.controller.score

    def _new_job(self,kind):
        # Bound retained status/results; keep at most one live job of each kind.
        for old in list(self.jobs.values()):
            if not old['done'] and old['kind']==kind:self.cancel(old['job_id'])
        while len(self.jobs)>=16:
            key=next(k for k,j in self.jobs.items() if j['done'] and (not j.get('future') or j['future'].done()));self.jobs.pop(key)
        job=dict(job_id=uuid.uuid4().hex,kind=kind,phase='generating' if kind=='preview' else 'exporting',done=False,
                 cancelled=False,error=None,cancel=threading.Event(),started=time.perf_counter(),result=None)
        self.jobs[job['job_id']]=job
        return job

    def begin(self,options):
        score=self._current();normalized=Options.read(options,score)
        job=self._new_job('preview');self.latest=job['job_id']
        snapshot=asdict(score);dep=dependency(score);directory=self.root/job['job_id'];directory.mkdir()
        job['source_dependency']=dep
        # Warm immutable cache: separate directories own hard links to artifacts.
        candidates=list(self.previews.values())+([self.applied] if self.applied else [])
        key=json.dumps(vars(normalized),sort_keys=True)
        cached=next((p for p in candidates if p['source_dependency']==dep and json.dumps(p['document']['options'],sort_keys=True)==key),None)
        if cached:
            for path in cached['directory'].iterdir():
                if path.is_file():
                    try:os.link(path,directory/path.name)
                    except OSError:shutil.copy2(path,directory/path.name)
            future=Future();future.set_result(dict(cached,preview_id=job['job_id'],directory=directory))
            job['future']=future;job['cached']=True
            return dict(job_id=job['job_id'],source_revision=dep)
        # Small immutable request; no PCM or audio device enters this process.
        (directory/'request.json').write_text(json.dumps(dict(score=snapshot,options=options),ensure_ascii=False),encoding='utf-8')
        def work():
            import psutil
            log=(directory/'worker.log').open('wb')
            try:
                process=subprocess.Popen([sys.executable,'-m','pianoscope.score_worker',str(directory)],
                                         stdout=subprocess.DEVNULL,stderr=log)
            except OSError as exc:
                log.close()
                raise NotationError('无法启动本地制谱进程，请检查 Python 与安装依赖。','NOTATION_ENGINE_UNAVAILABLE') from exc
            try:
                while process.poll() is None:
                    if job['cancel'].wait(.04):raise InterruptedError('已取消')
                    if time.perf_counter()-job['started']>60:raise NotationError('制谱超过 60 秒限制，请减少范围。')
                    if log.tell()>1024*1024:raise NotationError('排版器报告过多异常，请检查曲目。')
                    try:
                        if psutil.Process(process.pid).memory_info().rss>512*1024*1024:raise NotationError('排版内存超过 512 MiB 限制。')
                    except psutil.NoSuchProcess:pass
                process.wait();log.flush()
                if (directory/'worker.log').stat().st_size:logging.getLogger('pianoscope').info('Score worker: %s',(directory/'worker.log').read_text(errors='replace')[-16384:])
                if job['cancel'].is_set():raise InterruptedError('已取消')
                if not (directory/'result.json').exists():raise NotationError('原生排版进程未完成，请检查依赖。','NOTATION_ENGINE_UNAVAILABLE')
                status=json.loads((directory/'result.json').read_text())
                if not status['success']:
                    e=status['error'];raise NotationError(e['message'],e['code'],e.get('issues'))
                size=sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                if size>128*1024*1024:raise NotationError('谱面作业产物超过 128 MiB 限制。')
                doc=json.loads((directory/'document.json').read_text());manifest=json.loads((directory/'manifest.json').read_text())
                return dict(preview_id=job['job_id'],directory=directory,document=doc,manifest=manifest,source_dependency=dep,
                            score_id=score.score_id,notation_id=doc['id'],notation_revision=doc['notation_revision'])
            finally:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                log.close()
        job['future']=self.pool.submit(work)
        return dict(job_id=job['job_id'],source_revision=dep)

    def _publish(self,job):
        if job['done'] or not job.get('future') or not job['future'].done():return
        future=job.pop('future')
        with self.lock:
            if job['done']:return
            job['done']=True;job['seconds']=time.perf_counter()-job['started']
            try:
                result=future.result()
                if self.closed or job['cancel'].is_set():raise InterruptedError('已取消')
                if job['kind']=='preview':
                    if dependency(self._current())!=result['source_dependency'] or self.latest!=job['job_id']:
                        job['phase']='stale';return
                    self.previews[job['job_id']]=result;job['result']=self.summary(result);job['phase']='preview_ready'
                    self._prune()
                # Export worker commits its status while holding lock.
            except InterruptedError:job['phase']='cancelled';job['cancelled']=True
            except Exception as exc:
                # An old failure must not open diagnostics over a different song.
                if job['kind']=='preview' and (self.latest!=job['job_id'] or not self.controller.score or dependency(self.controller.score)!=job['source_dependency']):
                    job['phase']='stale';return
                logging.getLogger('pianoscope').exception('Score job failed')
                job['phase']='failed';job['error']=dict(code=getattr(exc,'code','EXPORT_FAILED' if job['kind']=='export' else 'NOTATION_ENGINE_UNAVAILABLE'),message=str(exc),issues=getattr(exc,'issues',[]),recoverable=True)

    def get(self,job_id):
        if job_id not in self.jobs:raise ValueError('制谱作业已失效')
        job=self.jobs[job_id];self._publish(job)
        if job['done'] and job.get('future') and job['future'].done():job.pop('future')
        self._prune()
        return {k:job.get(k) for k in ('job_id','kind','phase','done','cancelled','error','result','seconds')}

    def cancel(self,job_id):
        with self.lock:
            job=self.jobs.get(job_id)
            if not job or job['done']:return False
            # Completed export has already atomically published under this lock.
            job['cancel'].set();job['cancelled']=True;job['done']=True;job['phase']='cancelled'
            future=job.get('future')
            if future:future.cancel()
            return True

    def summary(self,item):
        doc=item['document'];stale=not self.controller.score or dependency(self.controller.score)!=item['source_dependency'] or (self.applied is not item and item['preview_id']!=self.latest)
        return dict(preview_id=item['preview_id'],notation_id=item['notation_id'],notation_revision=item['notation_revision'],
            layout_revision=item['manifest']['layout_revision'],source_revision=item['source_dependency'],score_id=item['score_id'],
            needs_review_count=sum(bool((v.get('normalization') or {}).get('needs_review')) for v in doc['source_note_index'].values()),
            profile=doc['profile'],voices=doc['voices'],normalization_counts=dict(Counter((v.get('normalization') or {}).get('kind','quantized') for v in doc['source_note_index'].values())),
            key_analysis=doc.get('key_analysis'),
            title=doc['title'],state='stale' if stale else 'applied' if self.applied is item else 'preview_ready',
            measures=len(doc['measures']),pages=len(item['manifest']['pages']),notes=len(doc['source_note_index']),
            tracks=len(doc['options']['tracks']),unassigned_notes=doc['unassigned_notes'],warnings=doc['warnings'][:100],
            warnings_count=len(doc['warnings']),options=doc['options'],metadata_sources=doc['metadata_sources'])

    def apply(self,preview_id,expected_source_revision):
        self._current()
        with self.lock:
            item=self.previews.get(preview_id)
            if not item or expected_source_revision!=item['source_dependency'] or dependency(self.controller.score)!=item['source_dependency'] or preview_id!=self.latest:
                raise NotationError('谱面已过期，请重新生成。','NOTATION_STALE')
            self.applied=item;self._prune();return self.summary(item)

    def _item(self,notation_id):
        items=list(self.previews.values())+([self.applied] if self.applied else [])
        item=next((p for p in reversed(items) if p['notation_id']==notation_id),None)
        if not item:raise NotationError('谱面已失效，请重新生成。','NOTATION_STALE')
        return item

    def page(self,notation_id,index):
        item=self._item(notation_id);pages=item['manifest']['pages'];index=int(index)
        if not 0<=index<len(pages):raise ValueError('无效谱面页码')
        token=f'notation-{item["preview_id"]}-{index+1}.png'
        self.resources[token]=item['directory']/f'page-{index+1}.png'
        return dict(pages[index],image_token=token,notation_id=notation_id,layout_revision=item['manifest']['layout_revision'],page=index)

    def resource(self,name):
        path=self.resources.get(name)
        if path and path.is_file():return path.read_bytes()
        return None

    def target(self,notation_id,format,path):
        if format not in ('pdf','musicxml'):raise ValueError('无效导出格式')
        item=self._item(notation_id)
        if item is not self.applied or self.summary(item)['state']=='stale':raise NotationError('谱面已过期，请重新生成。','NOTATION_STALE')
        token=uuid.uuid4().hex;self.targets[token]=dict(item=item,format=format,path=Path(path).resolve())
        self.targets=dict(list(self.targets.items())[-8:]);return dict(target_token=token,notation_id=notation_id,format=format)

    def export(self,notation_id,format,target_token):
        item=self._item(notation_id);target=self.targets.pop(target_token,None)
        if not target or target['item'] is not item or target['format']!=format or item is not self.applied or self.summary(item)['state']=='stale':
            raise NotationError('保存期间曲目或谱面已改变，请重新导出。','NOTATION_STALE')
        job=self._new_job('export');job['title']=item['document']['title'];job['notation_id']=notation_id
        job['snapshot_id']=item['preview_id']
        def work():
            temp=None
            try:
                path=target['path']
                with tempfile.NamedTemporaryFile(prefix='.pianoscope-',suffix='.tmp',dir=path.parent,delete=False) as stream:
                    temp=Path(stream.name)
                    with (item['directory']/('score.'+format)).open('rb') as src:
                        while True:
                            block=src.read(1024*256)
                            if not block:break
                            if job['cancel'].is_set():raise InterruptedError('已取消')
                            stream.write(block)
                    stream.flush();os.fsync(stream.fileno())
                with self.lock:
                    if self.closed or job['cancel'].is_set():raise InterruptedError('已取消')
                    os.replace(temp,path);temp=None
                    job.update(done=True,phase='completed',seconds=time.perf_counter()-job['started'],result=dict(title=job['title'],notation_id=notation_id,format=format,filename=path.name))
                return job['result']
            finally:
                if temp:temp.unlink(missing_ok=True)
        job['future']=self.pool.submit(work);return dict(job_id=job['job_id'],title=job['title'],notation_id=notation_id)

    def _prune(self):
        keep={self.latest}
        if self.applied:keep.add(self.applied['preview_id'])
        keep.update(t['item']['preview_id'] for t in self.targets.values())
        keep.update(j.get('snapshot_id') for j in self.jobs.values() if not j['done'])
        keep.update(jid for jid,j in self.jobs.items() if j.get('future') and not j['future'].done())
        for jid,item in list(self.previews.items()):
            if jid not in keep:
                self.previews.pop(jid);shutil.rmtree(item['directory'],ignore_errors=True)
        for directory in self.root.iterdir():
            if directory.is_dir() and directory.name not in keep and directory.name not in self.previews:shutil.rmtree(directory,ignore_errors=True)
        self.resources={k:p for k,p in self.resources.items() if p.parent.exists()}

    def position(self,source_s):
        if not self.applied or not self.controller.score or self.applied['score_id']!=self.controller.score.score_id:return None
        from bisect import bisect_right
        from fractions import Fraction
        from .notation import tempo_for
        doc=self.applied['document'];measures=doc['measures']
        key=(id(self.applied),id(self.controller.score.tempo_map))
        if not self.position_cache or self.position_cache[0]!=key:
            self.position_cache=(key,tempo_for(self.controller.score),[float(Fraction(*m['start'])) for m in measures])
        _,tempo,starts=self.position_cache
        qn=tempo.tick_at(source_s)/doc['ppqn']
        index=max(0,min(len(measures)-1,bisect_right(starts,qn)-1));m=measures[index]
        unit=4/m['meter']['denominator']
        return dict(notation_id=self.applied['notation_id'],measure=m['number'],beat=1+(qn-starts[index])/unit)

    def close(self):
        self.closed=True
        for jid in self.jobs:self.cancel(jid)
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.targets.clear();self.previews.clear();self.resources.clear();self.applied=None
        shutil.rmtree(self.root,ignore_errors=True)
