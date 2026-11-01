"""曲目、谱面、试听与导出的可取消事务；只由应用线程提交活动候选。"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from pianoscope.app.data import snapshot_record
from pianoscope.app.dialogs import choose_path, choose_score_path
from pianoscope.paths import RESOURCES, data_root, work_root
from pianoscope.playback.analysis import analyze, overview
from pianoscope.playback.audio import Audio
from pianoscope.playback.budget import require_pcm_budget
from pianoscope.playback.model import Score
from pianoscope.playback.monitor import MidiMonitor
from pianoscope.playback.player import ScorePlayer, serialized
from pianoscope.playback.render import audible_notes, render
from pianoscope.playback.types import PCM, AudibleEvent, Overview, PlaybackConfig
from pianoscope.practice import PracticeManager
from pianoscope.practice.follow import FollowSession, follow_notes
from pianoscope.score.mapping import json_value
from pianoscope.score.midi import compile_midi, sound_score
from pianoscope.score.model import ScoreDocument, parse_score
from pianoscope.score.plan import compile_plan
from pianoscope.score.process import run_preparation
from pianoscope.score.source import SourceDocument, read_source
from pianoscope.types import Cancelled, HandAssignments, PathInput, Record

DEMO = RESOURCES / "demos"


class Controller(ScorePlayer):
    """应用会话与候选作业的所有者，只在应用线程原子发布声音和谱面。"""

    def __init__(self, audio: Audio | None = None) -> None:
        """建立曲目、谱面、声音和导出事务状态，并创建本地作业目录。"""
        super().__init__(audio=audio)
        self.pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="pianoscope-score"
        )
        self.preparation_lock = threading.Lock()
        self.semantic_cache_lock = threading.Lock()
        self.semantic_cache: OrderedDict[str, ScoreDocument] = OrderedDict()
        self.jobs, self.paths, self.targets = {}, {}, {}
        self.candidates, self.confirmations, self.layout_candidates = {}, {}, {}
        self.current_layout_job = None
        self.current_job = None
        self.generation = self.configuration_generation = self.folder_generation = 0
        self.active = None
        self.library = dict(folder_name="", songs=[])
        self.hands = {}
        self.hand_preview = None
        self.hand_history = []
        self.analysis_seq = 0
        self._analysis_cache_key: tuple[int, int, bool, float] | None = None
        self._analysis_cache: Record | None = None
        self.workspace = work_root() / "jobs"
        self.workspace.mkdir(parents=True, exist_ok=True)
        database = data_root() / "practice.sqlite3"
        database.parent.mkdir(parents=True, exist_ok=True)
        legacy = work_root() / "practice.sqlite3"
        if not database.exists() and legacy.exists():
            import sqlite3

            with sqlite3.connect(legacy) as source, sqlite3.connect(database) as target:
                source.backup(target)
        self.practice = PracticeManager(database)
        self.monitor = MidiMonitor()
        self.practice.midi.listener = self.monitor.submit
        self.practice.midi.on_reset = self.monitor.silence
        monitor_options = self.practice.store.preference("midi_monitor") or {}
        self.monitor.volume = monitor_options.get("volume", 0.65)
        self._midi_preview = None
        self._practice_task = None
        self.follow: FollowSession | None = None
        self._follow_session_id = None
        self._follow_task = None
        self._practice_epoch = 0
        self._countdown_deadline = 0.0
        self._audition_config = None
        self.mode = "audition"
        self.practice_options = dict(count_in=True, target="all", accompaniment="all")
        for song in self.practice.store.library():
            self.library["songs"].append(
                dict(
                    name=song["name"],
                    file_token=self.token_for_path(song["path"]),
                    missing=not Path(song["path"]).is_file(),
                )
            )

    def _cached_parse(
        self, source: SourceDocument, settings: Record, cancelled: Cancelled
    ) -> ScoreDocument:
        """Reuse bounded immutable semantic parses for repeated opens/confirmations."""
        fingerprint = json.dumps(
            settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        key = source.sha256 + ":" + fingerprint
        with self.semantic_cache_lock:
            cached = self.semantic_cache.get(key)
            if cached is not None:
                self.semantic_cache.move_to_end(key)
                return copy.deepcopy(cached)
        document = parse_score(source, settings, cancelled)
        with self.semantic_cache_lock:
            self.semantic_cache[key] = copy.deepcopy(document)
            self.semantic_cache.move_to_end(key)
            while len(self.semantic_cache) > 2:
                self.semantic_cache.popitem(last=False)
        return document

    def token_for_path(self, path: PathInput) -> str:
        """登记真实路径并返回不透明令牌；路径仅保存在 Python 侧。"""
        token = uuid.uuid4().hex
        self.paths[token] = Path(path).expanduser().resolve()
        return token

    def _path(self, token: str) -> Path:
        """解析内置曲目或已登记文件令牌；未知或过期令牌抛出 ValueError。"""
        if token in ("demo:first-light", "demo:harmonics"):
            return DEMO / (
                "first-light.musicxml"
                if token.endswith("first-light")
                else "temporal.musicxml"
            )
        if token not in self.paths:
            raise ValueError("文件选择已过期，请重新打开乐谱")
        return self.paths[token]

    def choose_score(self, auto_cancel: bool = False) -> str | None:
        """用原生窗口选择 MusicXML／MXL，返回文件令牌；取消返回 None。"""
        path = choose_path(
            auto_cancel=auto_cancel, extensions=["musicxml", "xml", "mxl"], label="乐谱"
        )
        if path:
            self.practice.store.remember(str(Path(path).resolve()), Path(path).name)
            token = self.token_for_path(path)
            self.library["songs"] = [
                dict(name=r["name"], file_token=self.token_for_path(r["path"]))
                for r in self.practice.store.library()
            ]
            return token
        return None

    async def choose_score_folder(self, auto_cancel: bool = False) -> Record | None:
        """用原生窗口选择曲库目录并异步扫描；取消返回 None。"""
        path = choose_path(auto_cancel=auto_cancel, folder=True, label="乐谱")
        return await self.open_score_folder(str(path)) if path else None

    async def open_score_folder(self, path: PathInput) -> Record:
        # The native selector/CLI supplies paths; this method is not registered
        # publicly. JS only receives tokens, never arbitrary directory authority.
        """仅扫描当前目录的支持文件并返回曲库；最多 1000 首，不递归或解析曲目。

        较新的扫描或关闭会使旧结果失效；扫描失败保留当前曲库和播放。
        """
        self.folder_generation += 1
        generation = self.folder_generation

        def scan() -> tuple[Path, list[Path]]:
            """扫描支持的直接子文件，超过曲目上限时抛出 ValueError。"""
            directory = Path(path).expanduser().resolve()
            files = []
            for entry in directory.iterdir():
                if entry.is_file() and entry.suffix.lower() in (
                    ".xml",
                    ".musicxml",
                    ".mxl",
                ):
                    files.append(entry)
                    if len(files) > 1000:
                        raise ValueError("曲库超过 1,000 首，请选择较小的文件夹")
            return directory, sorted(files, key=lambda p: p.name.casefold())

        directory, files = await asyncio.to_thread(scan)
        if generation != self.folder_generation or self.closed:
            return self.get_score_library()
        self.practice.store.sources(str(directory))
        for path in files:
            self.practice.store.remember(str(path), path.name)
        self.library = dict(
            folder_name=directory.name,
            songs=[
                dict(name=r["name"], file_token=self.token_for_path(r["path"]))
                for r in self.practice.store.library()
            ],
        )
        return self.get_score_library()

    def get_score_library(self) -> Record:
        """返回稳定曲目 ID、临时文件令牌和文件状态，不暴露原路径。"""
        previous = {str(path): token for token, path in self.paths.items()}
        songs = []
        for row in self.practice.store.library():
            path = row["path"]
            songs.append(
                dict(
                    id=row["id"],
                    source_id=hashlib.sha256(
                        str(Path(path).parent).encode()
                    ).hexdigest(),
                    last_practiced=row["last_practiced"],
                    name=row["name"],
                    file_token=previous.get(path) or self.token_for_path(path),
                    source_fingerprint=row["fingerprint"],
                    missing=not Path(path).is_file(),
                )
            )
        self.library["songs"] = songs
        self.library["sources"] = [
            dict(id=hashlib.sha256(path.encode()).hexdigest(), name=Path(path).name)
            for path in self.practice.store.sources()
        ]
        return copy.deepcopy(self.library)

    async def refresh_library_source(self, source_id: str) -> Record:
        """只重新扫描已经授权并持久化的文件夹。"""
        path = next(
            (
                p
                for p in self.practice.store.sources()
                if hashlib.sha256(p.encode()).hexdigest() == source_id
            ),
            None,
        )
        if path is None:
            raise ValueError("文件夹来源已失效")
        return await self.open_score_folder(path)

    async def get_library_detail(self, token: str) -> Record:
        """仅解析语义和播放计划，选曲时不合成声音、不排版。"""
        path = self._path(str(token))

        def read() -> Record:
            """在工作线程解析有界曲目，并保留原有源校验。"""
            source = read_source(path)
            document = self._cached_parse(source, {}, lambda: self.closed)
            plan = compile_plan(document)
            return dict(
                title=document.title,
                original_name=source.original_name,
                source_sha256=source.sha256,
                source_revision=document.revision,
                duration_s=plan.duration_s,
                notes_count=len(plan.instances),
                staff_ids=sorted({n["staff_id"] for n in plan.instances}),
                voices=sorted(
                    {n["part_id"] + ":" + n["voice_id"] for n in plan.instances}
                ),
            )

        result = await asyncio.to_thread(read)
        if not str(token).startswith("demo:"):
            self.practice.store.remember(str(path), path.name, result["source_sha256"])
        return result

    def remove_library_song(self, token: str) -> Record:
        """从曲库移除引用，保留原文件与历史。"""
        self.practice.store.forget(str(self._path(str(token))))
        return self.get_score_library()

    def relocate_library_song(self, token: str) -> Record | None:
        """用原生选择器重新定位同内容曲目，拒绝错误文件。"""
        old = self._path(str(token))
        row = next(
            (r for r in self.practice.store.library() if r["path"] == str(old)), None
        )
        path = choose_path(extensions=["musicxml", "xml", "mxl"], label="重新定位乐谱")
        if not path or row is None:
            return None
        source = read_source(path)
        if row["fingerprint"] and row["fingerprint"] != source.sha256:
            raise ValueError("所选文件内容不同，请通过打开乐谱加入新曲目")
        self.practice.store.relocate(str(old), str(Path(path).resolve()))
        return self.get_score_library()

    def begin_score_load(self, token: str, settings: Record | None = None) -> Record:
        """解析文件令牌并启动候选曲目作业，返回 job_id 与世代。"""
        self._require_unlocked()
        path = self._path(str(token))
        return self._begin_load(path, settings or {})

    def _begin_load(
        self, path: PathInput, settings: Record, snapshot: SourceDocument | None = None
    ) -> Record:
        """取消旧加载并编译源快照、真实 MIDI 与候选 PCM，暂不排版或发布。

        确认后沿用不可变源快照；后台工作不替换当前曲目，只有应用线程可原子提交。
        """
        settings = snapshot_record(settings)
        if self.closed:
            raise ValueError("应用已关闭")
        if self.current_job:
            self.cancel_job(self.current_job)
        if self.current_layout_job:
            self.cancel_job(self.current_layout_job)
        self.generation += 1
        self.configuration_generation += 1
        generation = self.generation
        jid = uuid.uuid4().hex
        folder = self.workspace / jid
        folder.mkdir()
        cancel = threading.Event()
        job = dict(
            job_id=jid,
            generation=generation,
            kind="load",
            phase="reading",
            done=False,
            cancelled=False,
            error=None,
            cancel=cancel,
            lock=threading.Lock(),
            folder=folder,
            source_path=path,
            settings=settings,
            timings={},
        )
        self.jobs[jid] = job
        self.current_job = jid

        def check() -> bool:
            """判断当前加载是否已取消、关闭或被新世代替代。"""
            return cancel.is_set() or self.closed or generation != self.generation

        def work() -> Record:
            """独占准备资源并产生确认请求或完整声音候选；预算超限时保留旧曲目。"""
            with self._preparing(check):
                if check():
                    raise InterruptedError("已取消")
                started = time.perf_counter()
                source = snapshot or read_source(path, check)
                job["timings"]["read_s"] = time.perf_counter() - started
                started = time.perf_counter()
                document = self._cached_parse(source, settings, check)
                job["timings"]["parse_s"] = time.perf_counter() - started
                document.revision += ":" + jid
                if document.needs_confirmation:
                    return dict(
                        confirmation=True,
                        source=source,
                        required=document.needs_confirmation,
                        title=document.title,
                    )
                job["phase"] = "compiling"
                started = time.perf_counter()
                saved_hands = self.practice.store.preference("hands:" + source.sha256)
                plan = compile_plan(
                    document,
                    dict(settings, hands=saved_hands) if saved_hands else settings,
                    check,
                )
                if saved_hands:
                    for note in plan.instances:
                        note["hand"] = saved_hands.get(
                            note["element_ids"][0], "unassigned"
                        )
                        note["hand_source"] = (
                            "confirmed_source_label"
                            if note["hand"] != "unassigned"
                            else "unknown"
                        )
                job["timings"]["plan_s"] = time.perf_counter() - started
                started = time.perf_counter()
                compile_midi(plan)
                job["timings"]["midi_s"] = time.perf_counter() - started
                # Playback can publish without engraving. No native notation
                # worker, PDF, page image, or image decode runs on this path.
                result = dict(manifest=dict(layout_revision=None, pages=[]))
                (folder / "score.mid").write_bytes(plan.midi_bytes)
                job["phase"] = "synthesizing"
                config = dict(
                    rate=1.0,
                    hand_mode="both",
                    tracks=[
                        dict(id=p["id"], muted=False, solo=False)
                        for p in document.parts
                    ],
                )
                count = round((plan.duration_s + 2) * self.audio.sample_rate) * 8
                current_bytes = (
                    self.audio.pcm.nbytes if self.audio.pcm is not None else 0
                )
                require_pcm_budget(count, current_bytes)
                rendered_sample_rate = self.audio.sample_rate
                started = time.perf_counter()
                pcm = render(sound_score(plan), config, rendered_sample_rate, check)
                job["timings"]["render_s"] = time.perf_counter() - started
                if check():
                    raise InterruptedError("已取消")
                started = time.perf_counter()
                waveform = overview(pcm, 1400)
                job["timings"]["overview_s"] = time.perf_counter() - started
                return dict(
                    plan=plan,
                    pcm=pcm,
                    data=result,
                    folder=folder,
                    source_path=path,
                    overview=waveform,
                    config=config,
                    sample_rate=rendered_sample_rate,
                    hands=saved_hands or {},
                )

        job["future"] = self.pool.submit(work)
        self._prune()
        return dict(job_id=jid, generation=generation)

    @contextmanager
    def _preparing(self, cancelled: Cancelled) -> Iterator[None]:
        """可取消地获取准备锁，退出上下文时始终释放，避免并行候选占用超预算内存。"""
        while not self.preparation_lock.acquire(timeout=0.05):
            if cancelled():
                raise InterruptedError("已取消")
        try:
            if cancelled():
                raise InterruptedError("已取消")
            yield
        finally:
            self.preparation_lock.release()

    @asynccontextmanager
    async def _audio_candidate(self, cancelled: Cancelled) -> AsyncIterator[None]:
        """异步等待同一准备锁；取消期间仍回收获取任务并释放已持有的锁。"""
        stop = threading.Event()
        acquired = threading.Event()

        def acquire() -> None:
            """在工作线程有界等待准备锁；停止或过期时抛出 InterruptedError。"""
            while not (stop.is_set() or cancelled()):
                if self.preparation_lock.acquire(timeout=0.05):
                    acquired.set()
                    return
            raise InterruptedError("试听已过期")

        task = asyncio.create_task(asyncio.to_thread(acquire))
        try:
            await asyncio.shield(task)
            if cancelled():
                raise InterruptedError("试听已过期")
            yield
        finally:
            stop.set()
            try:
                await asyncio.shield(task)
            finally:
                if acquired.is_set():
                    self.preparation_lock.release()

    def _collect(self, job: Record) -> None:
        """收集已结束的后台结果，丢弃过期候选并更新确认、失败或就绪状态。"""
        future = job.get("future")
        if future is None or not future.done():
            return
        del job["future"]
        try:
            candidate = future.result()
            if (
                job["done"]
                or job["cancel"].is_set()
                or job["generation"] != self.generation
            ):
                return
            if job["kind"] == "layout":
                if job["snapshot"] is not self.active:
                    raise InterruptedError("谱面已过期")
                self.layout_candidates[job["job_id"]] = candidate
                job.update(phase="layout_ready")
            elif candidate.get("confirmation"):
                self.confirmations[job["job_id"]] = candidate
                job.update(
                    phase="needs_confirmation",
                    required=candidate["required"],
                    source_sha256=candidate["source"].sha256,
                    title=candidate["title"],
                )
            else:
                self.candidates[job["job_id"]] = candidate
                job.update(
                    phase="candidate_ready",
                    source_sha256=candidate["plan"].document.source.sha256,
                )
        except InterruptedError:
            if not job["done"]:
                job.update(done=True, cancelled=True, phase="cancelled")
        except Exception as exc:
            if not job["done"]:
                job.update(
                    done=True,
                    phase="failed",
                    error=dict(
                        message=str(exc),
                        code=getattr(exc, "code", "SCORE_PREPARE_FAILED"),
                        issues=getattr(exc, "issues", []),
                    ),
                )

    def get_job(self, job_id: str) -> Record:
        """收集指定作业并返回可序列化进度，不暴露 Future、锁或路径；未知 ID 拒绝。"""
        if job_id not in self.jobs:
            raise ValueError("作业已过期")
        job = self.jobs[job_id]
        self._collect(job)
        return {
            k: json_value(job[k])
            for k in (
                "job_id",
                "generation",
                "kind",
                "phase",
                "done",
                "cancelled",
                "error",
                "required",
                "source_sha256",
                "title",
                "filename",
                "timings",
            )
            if k in job
        }

    def cancel_job(self, job_id: str) -> bool:
        """取消未完成作业并清除候选，返回该作业是否存在；已完成导出保持完成状态。"""
        job = self.jobs.get(job_id)
        if not job:
            return False
        with job["lock"]:
            if not job["done"]:
                job["cancel"].set()
                job.update(done=True, cancelled=True, phase="cancelled")
                self.candidates.pop(job_id, None)
                self.layout_candidates.pop(job_id, None)
                self.confirmations.pop(job_id, None)
                future = job.pop("future", None)
                if future is not None:
                    future.cancel()
                    future.add_done_callback(lambda _: self._cleanup_job_folder(job))
        return True

    def confirm_score_load(
        self, pending_id: str, source_sha256: str, settings: Record
    ) -> Record:
        """校验确认请求的源哈希与世代，使用原始快照重新准备；过期确认抛出 ValueError。"""
        pending = self.confirmations.get(pending_id)
        job = self.jobs.get(pending_id)
        if (
            not pending
            or not job
            or job["done"]
            or job["generation"] != self.generation
            or pending["source"].sha256 != source_sha256
        ):
            raise ValueError("确认已过期，请重新打开乐谱")
        merged = dict(job["settings"], **settings)
        return self._begin_load(job["source_path"], merged, pending["source"])

    def _candidate(self, job_id: str) -> Record:
        """返回当前有效的加载候选；已取消、过期或被新作业替代时拒绝。"""
        self.get_job(job_id)
        if (
            job_id != self.current_job
            or job_id not in self.candidates
            or self.jobs[job_id]["done"]
        ):
            raise ValueError("候选已过期")
        return self.candidates[job_id]

    def get_candidate(self, job_id: str) -> Record:
        """返回候选曲目摘要、声音概览和页描述，隐藏内部 PCM 与文件路径。"""
        c = self._candidate(job_id)
        manifest = c["data"]["manifest"]
        return dict(
            job_id=job_id,
            title=c["plan"].document.title,
            source_sha256=c["plan"].document.source.sha256,
            source_revision=c["plan"].document.revision,
            layout_revision=manifest["layout_revision"],
            playback_revision=c["plan"].revision,
            notes_count=len(c["plan"].instances),
            overview=c["overview"],
            pages=[
                dict(
                    page=i,
                    width=p["width"],
                    height=p["height"],
                    resource=f"score-{job_id}-{i}.png",
                )
                for i, p in enumerate(manifest["pages"])
            ],
        )

    def get_score_page(
        self, layout_id: str, page: int, candidate_id: str | None = None
    ) -> Record:
        """返回指定排版版本的零基页几何；过期版本或越界页码抛出 ValueError。"""
        c = (
            (
                self._layout_candidate(candidate_id)
                if candidate_id in self.layout_candidates
                else self._candidate(candidate_id)
            )
            if candidate_id
            else self.active
        )
        if (
            not c
            or not layout_id
            or c["data"]["manifest"]["layout_revision"] != layout_id
        ):
            raise ValueError("谱面版本已过期")
        page = int(page)
        pages = c["data"]["manifest"]["pages"]
        if not 0 <= page < len(pages):
            raise ValueError("页码超出范围")
        return json_value(pages[page])

    def _prepare_layout(
        self, snapshot: Record, folder: Path, cancelled: Cancelled
    ) -> Record:
        """把不可变源快照送入隔离排版进程，返回验证后的谱面候选与产物目录。"""
        source = snapshot["plan"].document.source
        folder.mkdir(exist_ok=True)
        input_path = folder / ("input" + Path(source.original_name).suffix.lower())
        input_path.write_bytes(source.original_bytes)
        request = dict(
            source_path=str(input_path),
            original_name=source.original_name,
            settings=snapshot["plan"].settings,
            source_revision=snapshot["plan"].document.revision,
        )
        (folder / "request.json").write_text(json.dumps(request, ensure_ascii=False))
        result = run_preparation(folder, cancelled)
        if (
            result["source_sha256"] != source.sha256
            or result["source_revision"] != request["source_revision"]
            or (folder / "score.mid").read_bytes() != snapshot["plan"].midi_bytes
        ):
            raise ValueError("谱面与当前来源／播放编译不一致")
        return dict(data=result, folder=folder)

    def begin_score_layout(self, source_revision: str) -> Record:
        """按需启动当前源版本的谱面排版；可复用已准备结果，不触碰正在播放的声音。"""
        if not self.active or self.plan.document.revision != source_revision:
            raise ValueError("乐谱已过期")
        if self.active["data"]["manifest"]["layout_revision"]:
            return dict(ready=True, **self._layout_descriptor(self.active, None))
        if self.current_layout_job:
            job = self.jobs.get(self.current_layout_job)
            if job and not job["done"] and job["snapshot"] is self.active:
                return dict(job_id=job["job_id"], ready=False)
        snapshot = self.active
        jid = uuid.uuid4().hex
        folder = self.workspace / jid
        cancel = threading.Event()
        job = dict(
            job_id=jid,
            generation=self.generation,
            kind="layout",
            phase="engraving",
            done=False,
            cancelled=False,
            error=None,
            cancel=cancel,
            lock=threading.Lock(),
            folder=folder,
            snapshot=snapshot,
        )
        self.jobs[jid] = job
        self.current_layout_job = jid

        def check() -> bool:
            """检查排版请求的取消、关闭、世代及活动源快照是否仍匹配。"""
            return (
                cancel.is_set()
                or self.closed
                or snapshot is not self.active
                or job["generation"] != self.generation
            )

        def work() -> Record:
            """在准备锁内执行当前源快照的隔离排版，过期时停止工作。"""
            with self._preparing(check):
                return self._prepare_layout(snapshot, folder, check)

        job["future"] = self.pool.submit(work)
        self._prune()
        return dict(job_id=jid, ready=False)

    def _layout_candidate(self, job_id: str) -> Record:
        """返回与当前活动源匹配的排版候选；已过期或已消费的候选拒绝。"""
        self.get_job(job_id)
        job = self.jobs[job_id]
        if (
            job["done"]
            or job_id not in self.layout_candidates
            or job["snapshot"] is not self.active
            or job["generation"] != self.generation
        ):
            raise ValueError("谱面候选已过期")
        return self.layout_candidates[job_id]

    def _layout_descriptor(self, candidate: Record, candidate_id: str | None) -> Record:
        """把排版候选转换为前端可解码的页资源与版本描述。"""
        manifest = candidate["data"]["manifest"]
        resource_id = candidate_id or candidate["layout_job_id"]
        return dict(
            candidate_id=candidate_id,
            source_revision=manifest["source_revision"],
            layout_revision=manifest["layout_revision"],
            pages=[
                dict(
                    page=i,
                    width=p["width"],
                    height=p["height"],
                    resource=f"score-{resource_id}-{i}.png",
                )
                for i, p in enumerate(manifest["pages"])
            ],
        )

    def get_layout_candidate(self, job_id: str) -> Record:
        """校验排版作业并返回候选页描述，供前端解码完成后申请发布。"""
        return self._layout_descriptor(self._layout_candidate(job_id), job_id)

    def publish_score_layout(
        self, job_id: str, source_revision: str, layout_revision: str
    ) -> Record:
        """校验作业、源和谱面版本后原子提交真实谱面，返回当前文档。

        调用方须先解码所有页图；不修改 PCM、播放位置或设备时钟世代。
        """
        candidate = self._layout_candidate(job_id)
        manifest = candidate["data"]["manifest"]
        if (
            self.plan.document.revision != source_revision
            or manifest["source_revision"] != source_revision
            or manifest["layout_revision"] != layout_revision
        ):
            raise ValueError("谱面来源已过期")
        # Called only after all real page images decoded. Audio and playback
        # revisions/clock are untouched by this independently atomic commit.
        self.active.update(
            data=candidate["data"],
            layout_folder=candidate["folder"],
            layout_job_id=job_id,
        )
        self.jobs[job_id].update(done=True, phase="completed")
        self.layout_candidates.pop(job_id)
        return self.get_document()

    def resource(self, name: str) -> bytes | None:
        """只为有效谱面页资源名返回 PNG 字节，其他资源名返回 None。"""
        candidates = list(self.layout_candidates.items())
        if self.active and self.active["data"]["manifest"]["layout_revision"]:
            candidates.append((self.active["layout_job_id"], self.active))
        for jid, c in candidates:
            for i in range(len(c["data"]["manifest"]["pages"])):
                if name == f"score-{jid}-{i}.png":
                    return (
                        c.get("layout_folder", c["folder"]) / f"page-{i + 1}.png"
                    ).read_bytes()
        return None

    @serialized
    async def publish_score_load(self, job_id: str, source_sha256: str) -> Record:
        """在应用线程和命令锁中原子发布已核验的曲目、MIDI 语义与 PCM 候选。

        过期、取消或源哈希不匹配时拒绝提交，保留旧曲目；成功后清除已消费候选。
        """
        c = self._candidate(job_id)
        if c["plan"].document.source.sha256 != source_sha256:
            raise ValueError("候选来源已过期")
        if c["sample_rate"] != self.audio.sample_rate:
            raise ValueError("声音设备采样率已改变，请重新打开乐谱")
        old = self.active
        position = self.audio.clock()[0]
        was_playing = self.audio.playing
        old_pcm, old_rate, old_duration = (
            self.audio.pcm,
            self.audio.rate,
            self.audio.duration,
        )
        old_loop = dict(self.audio.loop)
        try:
            self.install(c["plan"], c["pcm"])
        except Exception:
            if old_pcm is not None:
                self.audio.install(old_pcm, old_rate, old_duration, position)
                self.audio.loop = old_loop
                if was_playing:
                    self.audio.start()
            raise
        c["job_id"] = job_id
        self.active = c
        self.hands, self.hand_history, self.hand_preview = c["hands"], [], None
        self.configuration_generation += 1
        self.jobs[job_id].update(done=True, phase="completed")
        del self.candidates[job_id]
        # The only retained PCM reference is the installed buffer.
        c.pop("pcm", None)
        if old:
            old.pop("pcm", None)
        source = self.plan.document.source
        for path in self.paths.values():
            if path.name == source.original_name and any(
                r["path"] == str(path) for r in self.practice.store.library()
            ):
                self.practice.store.remember(
                    str(path), self.plan.document.title, source.sha256
                )
                break
        self._audition_config = None
        self.practice.state = "idle"
        return self.get_document()

    def get_document(self) -> Record | None:
        """返回已发布曲目的语义、版本、手别及谱面状态；尚无曲目时返回 None。"""
        if not self.active:
            return None
        plan, document = self.plan, self.plan.document
        return dict(
            title=document.title,
            original_name=document.source.original_name,
            source_sha256=document.source.sha256,
            source_revision=document.revision,
            playback_revision=plan.revision,
            layout_revision=self.active["data"]["manifest"]["layout_revision"],
            duration_s=plan.duration_s,
            notes_count=len(plan.instances),
            source_notes=sum(e.pitch is not None for e in document.elements),
            parts=document.parts,
            staff_ids=sorted({e.staff_id for e in document.elements}),
            voices=sorted({e.part_id + ":" + e.voice_id for e in document.elements}),
            occurrences=json_value(plan.occurrences),
            hand_status="confirmed" if self.hands else "unassigned",
            used_pitches=sorted(
                {e.pitch for e in document.elements if e.pitch is not None}
            ),
            pages=len(self.active["data"]["manifest"]["pages"]),
            layout_ready=bool(self.active["data"]["manifest"]["layout_revision"]),
            diagnostics_count=len(plan.diagnostics)
            + len(self.active["data"]["manifest"].get("layout_diagnostics", [])),
            ready=True,
        )

    def get_capabilities(self) -> Record:
        """返回当前实现支持的导入、导出和视图能力，供本地前端决定可用操作。"""
        return dict(
            profile="V2-P0-2",
            formats=["musicxml", "xml", "mxl"],
            root="score-partwise",
            versions=["3.1", "4.0"],
            repeat="non-nested, first/second endings",
            midi_channels=15,
            ppqn_max=32767,
            ornaments=[
                "arpeggiate: bounded 1/16-quarter spread",
                "measured tremolo: single or same-bar paired note/chord",
            ],
            unsupported=[
                "grace",
                "other-ornaments",
                "unmeasured-or-cross-bar-tremolo",
                "nested-repeat",
                "DC/DS/Fine/Coda",
                "microtones",
                "nonzero-transpose",
                "unpitched",
            ],
        )

    def get_diagnostics(self, cursor: int = 0) -> Record:
        """从非负 cursor 起分页返回最多 100 条源语义与排版提示。"""
        if not self.plan:
            return dict(total=0, items=[], next_cursor=None)
        items = self.plan.diagnostics + self.active["data"]["manifest"].get(
            "layout_diagnostics", []
        )
        cursor = max(0, int(cursor))
        return dict(
            total=len(items),
            items=items[cursor : cursor + 100],
            next_cursor=cursor + 100 if cursor + 100 < len(items) else None,
        )

    def get_notes(
        self, offset: int = 0, limit: int = 1000, candidate_id: str | None = None
    ) -> Record:
        """分页返回已发布或有效候选的真实演奏实例；每页最多 2000 项。"""
        plan = self._candidate(candidate_id)["plan"] if candidate_id else self.plan
        if not plan:
            return dict(notes=[], total=0)
        offset = max(0, int(offset))
        limit = max(1, min(2000, int(limit)))
        return dict(
            playback_revision=plan.revision,
            total=len(plan.instances),
            notes=json_value(plan.instances[offset : offset + limit]),
        )

    def get_overview(self) -> Overview | None:
        """返回当前声音的峰值概览；尚无已发布声音时返回 None。"""
        return self.active["overview"] if self.active else None

    def get_analysis(self) -> Record:
        """分析已到达 DAC 的声音窗口并附序号与时钟世代，不分析未听见的候选 PCM。"""
        self.analysis_seq += 1
        return dict(
            analyze(self.audio.heard_window(), self.audio.sample_rate),
            seq=self.analysis_seq,
            clock_epoch=self.audio.epoch,
        )

    def get_ui_snapshot(self, include_analysis: bool = False) -> Record:
        """返回一次 UI 所需的传输与可选声音分析快照。"""
        transport = self.get_transport()
        result: Record = dict(
            transport=transport,
            analysis=None,
            practice=self.practice.update(transport),
        )
        if not include_analysis:
            return result
        key = (
            self.audio.epoch,
            self.audio.serial,
            self.audio.playing,
            self.audio.volume,
        )
        if self._analysis_cache_key != key or self._analysis_cache is None:
            self.analysis_seq += 1
            self._analysis_cache = dict(
                analyze(self.audio.heard_window(), self.audio.sample_rate),
                seq=self.analysis_seq,
                clock_epoch=self.audio.epoch,
            )
            self._analysis_cache_key = key
        result["analysis"] = dict(self._analysis_cache)
        return result

    def get_midi_inputs(self) -> Record:
        """列出可用 MIDI 输入设备及当前选择。"""
        result = self.practice.midi_inputs()
        if not result["opened"] or result.get("selected") not in {
            row["name"] for row in result.get("inputs", [])
        }:
            self.monitor.silence()
        if (
            self.practice.state not in ("playing", "countdown", "preparing")
            and not self._following()
        ):
            for event in self.practice.midi.drain():
                if event.kind == "note_on":
                    self._midi_preview = dict(
                        pitch=event.pitch, velocity=event.velocity
                    )
        result["latest_input"] = self._midi_preview
        result["monitor"] = self.monitor.status()
        return result

    async def set_midi_monitor(self, enabled: bool, volume: float = 0.65) -> Record:
        """Enable independent live piano output and persist its volume."""
        volume = float(volume)
        if not 0 <= volume <= 1:
            raise ValueError("演奏音量必须在 0–1 内")
        self.monitor.volume = volume
        if enabled and not self.monitor.ready:
            await asyncio.to_thread(self.monitor.start)
        elif not enabled:
            await asyncio.to_thread(self.monitor.close)
        self.practice.store.preference("midi_monitor", dict(volume=volume))
        return self.monitor.status()

    def silence_midi_monitor(self) -> Record:
        """Immediately request live piano all-sound-off."""
        self.monitor.silence()
        return self.monitor.status()

    def select_midi_input(self, name: str | None) -> Record:
        """选择或关闭 MIDI 输入设备。"""
        return self.practice.select_midi_input(str(name) if name else None)

    def _require_unlocked(self) -> None:
        """活动练习期间禁止改变不可变目标和时间轴。"""
        if self._following() or self.practice.state in (
            "playing",
            "paused",
            "preparing",
            "countdown",
        ):
            raise ValueError("请先结束练习，再调整配置或定位")

    async def seek(
        self, seconds: float, expected_playback_revision: str | None = None
    ) -> Record:
        """仅在练习未运行时允许定位。"""
        self._require_unlocked()
        return await super().seek(seconds, expected_playback_revision)

    async def set_loop(self, enabled: bool, a_s: float, b_s: float) -> Record:
        """仅在练习未运行时改变循环区间。"""
        self._require_unlocked()
        return await super().set_loop(enabled, a_s, b_s)

    def set_mode(self, mode: str, options: Record | None = None) -> Record:
        """设置统一播放模式及独立的目标和伴奏偏好。"""
        if self._following() or self.practice.state in (
            "playing",
            "paused",
            "countdown",
            "preparing",
        ):
            raise ValueError("请先结束当前练习")
        if mode not in ("audition", "practice", "follow"):
            raise ValueError("未知模式")
        if self.audio.playing:
            raise ValueError("请先暂停播放，再切换模式")
        options = snapshot_record(options or {})
        if options.get("target", "all") not in (
            "all",
            "left",
            "right",
            "custom",
        ) or options.get("accompaniment", "all") not in (
            "all",
            "other",
            "none",
            "custom",
        ):
            raise ValueError("练习范围无效")
        if self.follow is not None:
            self.audio.halt()
            self.audio.follow_position = None
            self.audio.set_position(self.follow.position)
            self.follow = None
        self.mode = mode
        self.practice_options.update(options)
        return dict(mode=self.mode, options=self.practice_options)

    def get_practice_history(self, fingerprint: str = "", offset: int = 0) -> Record:
        """查询曲目历史与未关联历史。"""
        return self.practice.store.history(str(fingerprint), int(offset))

    async def play(self) -> Record:
        """由共用播放入口启动或继续试听与 MIDI 练习。"""
        if (
            self.mode == "follow"
            and self.follow is not None
            and self.follow.state == "paused"
        ):
            self.practice.midi.drain(4096)
            self.follow.resume(time.monotonic_ns())
            return self.get_transport()
        if self.mode == "follow" and self._following():
            return self.get_transport()
        if self.mode not in ("practice", "follow"):
            if self._audition_config is not None:
                saved, self._audition_config = self._audition_config, None
                await self.configure(saved)
            return await super().play()
        if self.practice.state == "paused":
            self.practice.midi.drain(4096)
            self.practice.state = "playing"
            return await super().play()
        if self.practice.state == "playing":
            return self.get_transport()
        if self.practice.state in ("countdown", "preparing"):
            return self.get_transport()
        self._practice_epoch += 1
        epoch = self._practice_epoch
        self.practice.state = "preparing"
        try:
            return await self._prepare_practice(epoch)
        except BaseException:
            if epoch == self._practice_epoch:
                self.practice.state = "idle"
            raise

    async def _prepare_practice(self, epoch: int) -> Record:
        """准备独立伴奏、可取消倒计时和练习快照。"""
        device = self.practice.midi.status()
        if not device["opened"]:
            raise ValueError("请先在首页连接 MIDI 输入设备")
        if self.plan is None:
            raise ValueError("请先选择曲目")
        target = self.practice_options.get("target", "all")
        selected = [
            n["id"]
            for n in self.plan.instances
            if (
                target in ("all", "custom")
                or self.hands.get(n["element_ids"][0]) == target
            )
            and (
                target != "custom"
                or self.practice_options.get("staff_ids") is None
                or n["staff_id"] in self.practice_options["staff_ids"]
            )
            and (
                target != "custom"
                or self.practice_options.get("voice_ids") is None
                or n["part_id"] + ":" + n["voice_id"]
                in self.practice_options["voice_ids"]
            )
        ]
        if not selected:
            raise ValueError("练习目标为空，请确认左右手分配或选择全部")
        loop = self.audio.loop
        options = self.practice_options
        a, b = (
            (loop["a_s"], loop["b_s"])
            if loop["enabled"]
            else (
                float(options.get("range_a_s", 0)),
                float(options.get("range_b_s", self.plan.duration_s)),
            )
            if options.get("range_enabled")
            else (0, self.plan.duration_s)
        )
        if not 0 <= a < b <= self.plan.duration_s or b - a < 0.5:
            raise ValueError("练习片段至少 0.5 秒且不能超出曲目")
        if not any(
            n["id"] in selected
            and (
                n["onset_s"] < b and n["key_off_s"] > a
                if self.mode == "follow"
                else a <= n["onset_s"] < b
            )
            for n in self.plan.instances
        ):
            raise ValueError("练习片段内没有目标音符")
        accompaniment = self.practice_options.get("accompaniment", "all")
        if self._audition_config is None:
            self._audition_config = {
                k: self.config.get(k)
                for k in ("rate", "hand_mode", "staff_ids", "voice_ids")
            }
        audible = [
            n["id"]
            for n in self.plan.instances
            if accompaniment == "all"
            or accompaniment == "other"
            and n["id"] not in selected
            or accompaniment == "custom"
            and (
                self.practice_options.get("accompaniment_staff_ids") is None
                or n["staff_id"] in self.practice_options["accompaniment_staff_ids"]
            )
            and (
                self.practice_options.get("accompaniment_voice_ids") is None
                or n["part_id"] + ":" + n["voice_id"]
                in self.practice_options["accompaniment_voice_ids"]
            )
        ]
        await self.configure(dict(hand_mode="both", allowed_note_ids=audible))
        if epoch != self._practice_epoch:
            return self.get_transport()
        await super().seek(a)
        self.practice.state = "countdown"
        self._countdown_deadline = time.monotonic() + (
            3
            if self.mode != "follow" and self.practice_options.get("count_in", True)
            else 0
        )
        while time.monotonic() < self._countdown_deadline:
            await asyncio.sleep(0.05)
            if epoch != self._practice_epoch:
                return self.get_transport()
        config = dict(self.config, allowed_note_ids=selected)
        self.practice.midi.drain(4096)
        config.update(title=self.plan.document.title, device=device["selected"])
        config["practice_options"] = snapshot_record(self.practice_options)
        self.practice.state = "idle"
        if self.mode == "follow":
            self.follow = FollowSession(
                follow_notes(self.plan, selected),
                a,
                b,
                self.config["rate"],
                loop["enabled"],
            )
            self.follow.advance(time.monotonic_ns())
            self.audio.follow_position = a
            self.audio.start()
            self.phase = "playing"
            metadata = dict(
                source_fingerprint=self.plan.document.source.sha256,
                source_revision=self.plan.document.revision,
                playback_revision=self.plan.revision,
                rate=self.config["rate"],
                hand_mode="both",
                loop_a_s=a,
                loop_b_s=b,
                expected_count=len(self.follow.notes),
                title=self.plan.document.title,
                device=device["selected"],
                mode="follow",
                options=dict(self.practice_options, mode="follow"),
            )
            self._follow_session_id = self.practice.store.create(metadata)
            self._follow_task = asyncio.create_task(self._follow_tick())
            return self.get_transport()
        transport = await super().play()
        self.practice.start(self.plan, config, transport)
        self.practice.metadata.update(
            title=self.plan.document.title, device=device["selected"]
        )
        if self._practice_task is None or self._practice_task.done():
            self._practice_task = asyncio.create_task(self._practice_tick())
        return self.get_transport()

    def _following(self) -> bool:
        """Whether an immutable follow session owns the score transport."""
        return self.follow is not None and self.follow.state in ("playing", "paused")

    def _save_follow(self, status: str) -> None:
        """Persist non-rhythmic progress separately from timing accuracy."""
        if self.follow is None or self._follow_session_id is None:
            return
        snapshot = self.follow.snapshot()
        self.practice.store.finish(
            self._follow_session_id,
            dict(
                hit_count=0,
                miss_count=0,
                extra_count=0,
                mean_abs_delta_ms=None,
                completed_rounds=self.follow.completed_rounds,
                status=status,
            ),
            [],
        )
        self.practice.store.follow_progress(self._follow_session_id, snapshot)

    async def _follow_tick(self) -> None:
        """Drive gated audio independently of page polling, with bounded progress."""
        checked = saved = time.monotonic()
        try:
            while not self.closed and self._following():
                follow = self.follow
                if follow.state == "playing":
                    for event in self.practice.midi.drain(4096):
                        follow.event(event)
                    follow.advance(time.monotonic_ns())
                    if follow.position < (self.audio.follow_position or 0):
                        self.audio.halt()
                        self.audio.set_position(follow.position)
                        self.audio.follow_position = follow.position
                        self.audio.start()
                    else:
                        self.audio.follow_position = follow.position
                    if follow.state == "finished":
                        self.audio.halt()
                        self._save_follow("finished")
                        self.phase = "ended"
                        break
                    if (
                        not self.audio.ready
                        or self.audio.stream is None
                        or not self.audio.stream.active
                    ):
                        follow.pause(time.monotonic_ns())
                    if time.monotonic() - saved >= 1:
                        self._save_follow("playing")
                        saved = time.monotonic()
                if time.monotonic() - checked >= 1:
                    device = self.practice.midi.status()
                    names = [
                        r["name"]
                        for r in self.practice.midi.list_inputs().get("inputs", [])
                    ]
                    if not device["opened"] or device["selected"] not in names:
                        follow.pause(time.monotonic_ns())
                        self.audio.follow_position = follow.position
                        self.monitor.silence()
                    checked = time.monotonic()
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            pass
        except Exception:
            if self.follow is not None:
                self.follow.pause(time.monotonic_ns())
                self.follow.state = "finished"
                self._save_follow("interrupted")
            self.audio.halt()

    async def _practice_tick(self) -> None:
        """后台推进 MIDI 判定，不依赖页面轮询或可见性。"""
        try:
            checked = saved = time.monotonic()
            while not self.closed and self.practice.state in ("playing", "paused"):
                transport = self.get_transport()
                if self.practice.state == "playing":
                    self.practice.update(transport)
                    if (
                        self.practice.state == "playing"
                        and not self.practice.metadata["loop_enabled"]
                        and transport["position_s"]
                        >= self.practice.metadata["loop_b_s"]
                    ):
                        await super().pause()
                        transport.update(
                            phase="ended", position_s=self.practice.metadata["loop_b_s"]
                        )
                        self.practice.finish(transport)
                        self.phase = "ended"
                    if transport["phase"] == "error":
                        self.practice.state = "paused"
                    if (
                        self.practice.state == "playing"
                        and time.monotonic() - saved >= 1
                    ):
                        self.practice._flush("playing")
                        saved = time.monotonic()
                if time.monotonic() - checked >= 1:
                    device = self.practice.midi.status()
                    names = [
                        r["name"]
                        for r in self.practice.midi.list_inputs().get("inputs", [])
                    ]
                    if not device["opened"] or device["selected"] not in names:
                        await self.pause()
                    checked = time.monotonic()
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass
        except Exception:
            self.practice.finish(self.get_transport(), "interrupted")

    async def pause(self) -> Record:
        """暂停统一传输，保留练习会话。"""
        if self._following():
            self.follow.pause(time.monotonic_ns())
            self.audio.follow_position = self.follow.position
            return self.get_transport()
        transport = await super().pause()
        if self.practice.state == "playing":
            self.practice.update(transport)
            self.practice.state = "paused"
        return transport

    async def stop(self) -> Record:
        """停止统一传输并保存练习结果。"""
        if self._following():
            self.follow.pause(time.monotonic_ns())
            self.follow.state = "finished"
            self._save_follow("stopped")
        if self._follow_task is not None:
            self._follow_task.cancel()
            self._follow_task = None
        self.audio.follow_position = None
        self.follow = None
        self._practice_epoch += 1
        if self.practice.state in ("preparing", "countdown"):
            self.practice.state = "idle"
        transport = await super().pause()
        if self.practice.state in ("playing", "paused"):
            self.practice.update(transport)
            self.practice.finish(transport)
        return await super().stop()

    async def start_practice(self, options: Record | None = None) -> Record:
        """兼容旧入口，通过统一播放开始练习。"""
        options = snapshot_record(options or {})
        if "midi_port" in options:
            self.practice.select_midi_input(options["midi_port"])
        self.set_mode("practice", options)
        await self.play()
        return self.get_practice_snapshot()

    async def stop_practice(self) -> Record:
        """兼容旧入口，通过统一停止保存练习。"""
        await self.stop()
        return self.get_practice_snapshot()

    def get_practice_snapshot(self) -> Record:
        """返回当前练习状态和最近一条匹配结果。"""
        return self.practice.update(self.get_transport())

    def get_practice_results(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 200,
        filters: Record | None = None,
    ) -> Record:
        """按轮次与判定类型分页读取历史结果。"""
        result = self.practice.store.results(
            str(session_id), offset, limit, snapshot_record(filters or {})
        )
        result["comparison"] = self.practice.store.comparison(str(session_id))
        return result

    def get_transport(self) -> Record:
        """在基础 DAC 传输状态上附曲目世代、谱面版本与手别确认状态。"""
        result = super().get_transport()
        follow = (
            self.follow.snapshot() if self.mode == "follow" and self.follow else None
        )
        if follow is not None:
            result.update(
                phase="ended"
                if follow["state"] == "finished"
                else "paused"
                if follow["state"] == "paused"
                else "playing",
                position_s=follow["position_s"],
                active_instance_ids=follow["target_ids"],
                active_element_ids=[
                    e
                    for n in self.plan.instances
                    if n["id"] in follow["target_ids"]
                    for e in n["element_ids"]
                ],
                sustained_instance_ids=[],
            )
        return dict(
            result,
            generation=self.generation,
            layout_revision=self.active["data"]["manifest"]["layout_revision"]
            if self.active
            else None,
            hand_mode=self.config["hand_mode"] if self.config else "both",
            hand_status="confirmed" if self.hands else "unassigned",
            mode=self.mode,
            follow=follow,
            practice_locked=self._following()
            or self.practice.state in ("playing", "paused", "preparing", "countdown"),
            countdown_remaining=max(0, self._countdown_deadline - time.monotonic())
            if self.practice.state == "countdown"
            else None,
        )

    def _same_audio(self, next_score: Score, next_config: PlaybackConfig) -> bool:
        # Labels and equivalent scope selections need no second PCM. The
        # synthesizer consumes these event fields, not hand/source labels.
        """比较设备采样率、倍率及实际可听事件，判断当前 PCM 是否可直接复用。

        仅标签或等效筛选改变时返回 True，避免分配第二份缓冲或重置时钟。
        """
        if (
            self.audio.pcm is None
            or self.active["sample_rate"] != self.audio.sample_rate
            or self.config["rate"] != next_config["rate"]
        ):
            return False

        def events(score: Score, config: PlaybackConfig) -> list[AudibleEvent]:
            """提取会影响可听内容的事件字段，忽略手别标签等纯元数据。"""
            return [
                (
                    n.id,
                    n.track_id,
                    n.pitch,
                    n.velocity,
                    n.start_s,
                    n.key_off_s,
                    n.sustain_end_s,
                )
                for n in audible_notes(score, config)
            ]

        return events(self.score, self.config) == events(next_score, next_config)

    async def configure(self, changes: PlaybackConfig) -> Record:
        """校验速度、手别和源范围，原子应用试听配置并返回传输状态。

        声音等效时复用 PCM；否则先完成候选合成。取消、过期或失败不部分提交设置。
        """
        if self.plan is None:
            raise ValueError("请先打开乐谱")
        if self.current_job and not self.jobs[self.current_job]["done"]:
            raise ValueError("请先完成或取消乐谱准备，再更改试听")
        if self._following() or self.practice.state in (
            "playing",
            "paused",
            "countdown",
        ):
            raise ValueError("请先结束练习，再调整配置")
        changes = snapshot_record(changes)
        if any(
            k not in ("rate", "hand_mode", "staff_ids", "voice_ids", "allowed_note_ids")
            for k in changes
        ):
            raise ValueError("未知试听设置")
        if changes.get("hand_mode", "both") not in ("both", "left", "right"):
            raise ValueError("试听手别无效")
        if changes.get("hand_mode", "both") != "both" and not self.hands:
            raise ValueError("请先预览并确认手别")
        document = self.get_document()
        for key, available in (
            ("staff_ids", document["staff_ids"]),
            ("voice_ids", document["voices"]),
        ):
            if (
                key in changes
                and changes[key] is not None
                and any(v not in available for v in changes[key])
            ):
                raise ValueError("试听范围已过期")
        restoring_audition = (
            self._audition_config is not None
            and self.practice.state
            not in ("preparing", "countdown", "playing", "paused")
        )
        config = dict(
            self.config,
            **(self._audition_config if restoring_audition else {}),
        )
        config.update(changes)
        if config["rate"] not in (0.5, 0.75, 1.0):
            raise ValueError("仅支持 0.5×／0.75×／1×")
        config["allowed_note_ids"] = changes.get(
            "allowed_note_ids",
            [
                n["id"]
                for n in self.plan.instances
                if (
                    config.get("staff_ids") is None
                    or n["staff_id"] in config["staff_ids"]
                )
                and (
                    config.get("voice_ids") is None
                    or n["part_id"] + ":" + n["voice_id"] in config["voice_ids"]
                )
            ],
        )
        self.configuration_generation += 1
        generation = self.configuration_generation
        plan = self.plan

        def cancelled() -> bool:
            """检查试听候选的曲目快照、配置世代和应用关闭状态。"""
            return (
                self.closed
                or self.plan is not plan
                or generation != self.configuration_generation
            )

        if self._same_audio(self.score, config):
            async with self.command_lock:
                if cancelled():
                    raise ValueError("试听已过期")
                self.config = config
                if restoring_audition:
                    self._audition_config = None
                self._rebuild_transport_index()
                return self.get_transport()

        def work() -> PCM:
            """在总预算检查后离线生成试听候选，不修改活动 PCM。"""
            count = (
                round((plan.duration_s / config["rate"] + 2) * self.audio.sample_rate)
                * 8
            )
            require_pcm_budget(count, self.audio.pcm.nbytes)
            return render(self.score, config, self.audio.sample_rate, cancelled)

        async with self._audio_candidate(cancelled):
            pcm = None
            try:
                pcm = await asyncio.to_thread(work)
                if cancelled():
                    raise ValueError("试听已过期")
                async with self.command_lock:
                    position = await self.audio.fade_halt()
                    if cancelled():
                        raise ValueError("试听已过期")
                    self.audio.install(pcm, config["rate"], plan.duration_s, position)
                    self.config = config
                    if restoring_audition:
                        self._audition_config = None
                    self._rebuild_transport_index()
                    self.active["sample_rate"] = self.audio.sample_rate
                    if self.phase == "playing":
                        self.audio.start()
                    return self.get_transport()
            finally:
                pcm = None

    def preview_hands(self, assignments: HandAssignments) -> Record:
        """校验源音符手别并创建预览令牌与计数；不立即改变实际声音或标签。"""
        if not self.plan:
            raise ValueError("请先打开乐谱")
        known = {e.id for e in self.plan.document.elements if e.pitch is not None}
        assignments = {str(k): str(v) for k, v in assignments.items()}
        if any(
            k not in known or v not in ("left", "right", "unassigned")
            for k, v in assignments.items()
        ):
            raise ValueError("手别指派包含未知源音符")
        merged = dict(self.hands, **assignments)
        preview_id = uuid.uuid4().hex
        self.hand_preview = dict(
            id=preview_id, source_revision=self.plan.document.revision, hands=merged
        )
        counts = {
            h: sum(
                merged.get(e.id, "unassigned") == h
                for e in self.plan.document.elements
                if e.pitch is not None
            )
            for h in ("left", "right", "unassigned")
        }
        return dict(preview_id=preview_id, counts=counts)

    def get_source_elements(self) -> list[Record]:
        """返回可分配手别的源音符、谱表和声部身份，无曲目时返回空列表。"""
        return (
            [
                dict(
                    element_id=e.id,
                    staff_id=e.staff_id,
                    voice_id=e.part_id + ":" + e.voice_id,
                )
                for e in self.plan.document.elements
                if e.pitch is not None
            ]
            if self.plan
            else []
        )

    def get_practice_settings(self) -> Record:
        """返回已应用试听范围、谱表建议与混合手别，保留空范围及撤销状态。"""
        if not self.plan:
            raise ValueError("请先打开乐谱")
        document = self.get_document()
        elements = [e for e in self.plan.document.elements if e.pitch is not None]
        staves = []
        for index, ident in enumerate(document["staff_ids"]):
            labels = {
                self.hands.get(e.id, "unassigned")
                for e in elements
                if e.staff_id == ident
            }
            paired = (
                len(document["staff_ids"]) == 2
                or len(document["parts"]) == 1
                and document["parts"][0]["staves"] == 2
            )
            name = (
                ("上谱表" if index == 0 else "下谱表")
                if paired
                else "谱表 " + str(index + 1)
            )
            staves.append(
                dict(
                    id=ident,
                    name=name,
                    notes=sum(e.staff_id == ident for e in elements),
                    hand=next(iter(labels))
                    if len(labels) == 1
                    else "mixed"
                    if labels
                    else "unassigned",
                    suggestion="right" if index == 0 else "left",
                )
            )
        voices = []
        for ident in document["voices"]:
            sources = {
                e.staff_id for e in elements if e.part_id + ":" + e.voice_id == ident
            }
            staff_name = (
                next((s["name"] for s in staves if s["id"] in sources), "")
                if len(sources) == 1
                else "跨谱表"
            )
            voices.append(
                dict(id=ident, name=staff_name + " · 声部 " + ident.rsplit(":", 1)[-1])
            )
        return dict(
            source_revision=self.plan.document.revision,
            staves=staves,
            voices=voices,
            staff_ids=list(self.config.get("staff_ids"))
            if self.config.get("staff_ids") is not None
            else document["staff_ids"],
            voice_ids=list(self.config.get("voice_ids"))
            if self.config.get("voice_ids") is not None
            else document["voices"],
            hand_mode=self.config["hand_mode"],
            hand_status=document["hand_status"],
            can_undo=bool(self.hand_history),
        )

    async def apply_hands(self, preview_id: str) -> Record:
        """确认仍匹配当前源的手别预览，提交成功后记录撤销历史并返回文档。"""
        preview = self.hand_preview
        if (
            not preview
            or preview["id"] != preview_id
            or preview["source_revision"] != self.plan.document.revision
        ):
            raise ValueError("手别预览已过期")
        self._require_unlocked()
        old = dict(self.hands)
        await self._set_hands(preview["hands"])
        self.practice.store.preference(
            "hands:" + self.plan.document.source.sha256, self.hands
        )
        self.hand_history.append(old)
        self.hand_preview = None
        return self.get_document()

    async def _set_hands(self, assignments: HandAssignments) -> None:
        """按源音符重建手别元数据；声音等效时复用 PCM，否则完成候选后一起提交。

        声音准备、预算或版本校验失败时保留标签、历史、配置及旧 PCM。
        """
        if self.current_job and not self.jobs[self.current_job]["done"]:
            raise ValueError("请先完成或取消乐谱准备，再更改手别")
        old_plan = self.plan
        next_plan = compile_plan(
            old_plan.document, dict(old_plan.settings, hands=assignments)
        )
        compile_midi(next_plan)
        for n in next_plan.instances:
            n["hand"] = assignments.get(n["element_ids"][0], "unassigned")
            n["hand_source"] = (
                "confirmed_source_label" if n["hand"] != "unassigned" else "unknown"
            )
        next_score = sound_score(next_plan)
        self.configuration_generation += 1
        generation = self.configuration_generation

        def cancelled() -> bool:
            """判断手别候选是否因关闭、换曲或新配置世代而过期。"""
            return (
                self.closed
                or self.plan is not old_plan
                or generation != self.configuration_generation
            )

        config = copy.deepcopy(self.config)
        if not assignments:
            config["hand_mode"] = "both"
        if self._same_audio(next_score, config):
            async with self.command_lock:
                if cancelled():
                    raise ValueError("手别预览已过期")
                self.plan, self.score, self.hands, self.config = (
                    next_plan,
                    next_score,
                    dict(assignments),
                    config,
                )
                self._rebuild_transport_index()
                self.active["plan"] = next_plan
                return

        def work() -> PCM:
            """按新的实际可听事件合成候选 PCM，并在分配前核验共享预算。"""
            count = (
                round(
                    (next_plan.duration_s / config["rate"] + 2) * self.audio.sample_rate
                )
                * 8
            )
            require_pcm_budget(count, self.audio.pcm.nbytes)
            return render(next_score, config, self.audio.sample_rate, cancelled)

        async with self._audio_candidate(cancelled):
            pcm = None
            try:
                pcm = await asyncio.to_thread(work)
                if cancelled():
                    raise ValueError("手别预览已过期")
                async with self.command_lock:
                    position = await self.audio.fade_halt()
                    if cancelled():
                        raise ValueError("手别预览已过期")
                    self.audio.install(
                        pcm, config["rate"], next_plan.duration_s, position
                    )
                    self.plan, self.score, self.hands, self.config = (
                        next_plan,
                        next_score,
                        dict(assignments),
                        config,
                    )
                    self._rebuild_transport_index()
                    self.active["plan"] = next_plan
                    self.active["sample_rate"] = self.audio.sample_rate
                    if self.phase == "playing":
                        self.audio.start()
            finally:
                pcm = None

    async def undo_hands(self) -> Record | None:
        """应用上一份手别快照，成功后移除该撤销记录；无历史时返回当前文档。"""
        if not self.hand_history:
            return self.get_document()
        self._require_unlocked()
        old = self.hand_history[-1]
        await self._set_hands(old)
        self.practice.store.preference(
            "hands:" + self.plan.document.source.sha256, self.hands
        )
        self.hand_history.pop()
        return self.get_document()

    def choose_export(
        self, document_id: str, format: str, auto_cancel: bool = False
    ) -> Record | None:
        """为指定源版本选择 PDF、源副本或 MIDI 的目标并绑定不可变快照。

        取消返回 None；窗口期间换曲、格式无效或目标覆盖当前输入源时拒绝。
        """
        if (
            not self.active
            or document_id != self.plan.document.revision
            or format not in ("pdf", "source", "midi")
        ):
            raise ValueError("导出版本或格式已过期")
        snapshot = self.active
        suffix = (
            Path(self.plan.document.source.original_name).suffix.lower().lstrip(".")
            if format == "source"
            else "mid"
            if format == "midi"
            else "pdf"
        )
        path = choose_score_path(
            self.plan.document.title, suffix, auto_cancel=auto_cancel
        )
        if path is None:
            return None
        if self.active is not snapshot:
            raise ValueError("保存窗口期间曲目已改变，请重新导出")
        target = Path(path).resolve()
        source_path = snapshot["source_path"]
        if (
            target == source_path
            or target.exists()
            and source_path.exists()
            and os.path.samefile(target, source_path)
        ):
            raise ValueError("不能覆盖当前输入源文件")
        token = uuid.uuid4().hex
        self.targets[token] = dict(snapshot=snapshot, path=target, format=format)
        return dict(
            target_token=token,
            snapshot_id=document_id,
            format=format,
            filename=target.name,
        )

    def begin_export(self, snapshot_id: str, format: str, target_token: str) -> Record:
        """校验已选目标及快照并启动导出；开始后换曲不改变本次导出内容。

        先写同目录临时文件并校验、fsync，再 os.replace；取消或失败保留原目标。
        """
        target = self.targets.pop(target_token, None)
        if (
            not target
            or target["snapshot"] is not self.active
            or snapshot_id != self.plan.document.revision
            or target["format"] != format
        ):
            raise ValueError("导出目标已过期，请重新保存")
        snapshot = target["snapshot"]
        source = snapshot["plan"].document.source
        data = (
            source.original_bytes
            if format == "source"
            else snapshot["plan"].midi_bytes
            if format == "midi"
            else None
        )
        jid = uuid.uuid4().hex
        job = dict(
            job_id=jid,
            generation=self.generation,
            kind="export",
            phase="writing",
            done=False,
            cancelled=False,
            error=None,
            cancel=threading.Event(),
            lock=threading.Lock(),
            filename=target["path"].name,
        )
        self.jobs[jid] = job

        def work() -> None:
            """生成快照导出字节并原子落盘，记录完成、取消或失败，始终清理未提交临时文件。"""
            temporary = None
            try:
                payload = data
                if format == "pdf":
                    job["phase"] = "engraving"

                    def cancelled() -> bool:
                        """只按导出自身取消或应用关闭停止，不因活动曲目改变而丢弃已确认快照。"""
                        return job["cancel"].is_set() or self.closed

                    # An export owns its immutable source snapshot even when
                    # the active song changes. It never publishes UI geometry.
                    with self._preparing(cancelled):
                        folder = self.workspace / jid
                        job["folder"] = folder
                        self._prepare_layout(snapshot, folder, cancelled)
                        payload = (folder / "score.pdf").read_bytes()
                    job["phase"] = "writing"
                with tempfile.NamedTemporaryFile(
                    prefix=".pianoscope-", dir=target["path"].parent, delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    for offset in range(0, len(payload), 64 * 1024):
                        if job["cancel"].is_set() or self.closed:
                            raise InterruptedError("已取消")
                        stream.write(payload[offset : offset + 64 * 1024])
                    stream.flush()
                    os.fsync(stream.fileno())
                if (
                    hashlib.sha256(temporary.read_bytes()).digest()
                    != hashlib.sha256(payload).digest()
                ):
                    raise OSError("导出文件校验不一致")
                with job["lock"]:
                    if job["cancel"].is_set() or self.closed:
                        raise InterruptedError("已取消")
                    os.replace(temporary, target["path"])
                    temporary = None
                    job.update(done=True, phase="completed")
            except InterruptedError:
                with job["lock"]:
                    job.update(done=True, cancelled=True, phase="cancelled")
            except Exception as exc:
                with job["lock"]:
                    if job["phase"] != "completed":
                        job.update(
                            done=True,
                            phase="failed",
                            error=dict(message=str(exc), code="EXPORT_FAILED"),
                        )
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)

        # No PCM-bearing future or result is retained by an export job.
        self.pool.submit(work)
        return dict(job_id=jid)

    async def retry_audio(self) -> Record:
        """重新打开设备；采样率改变时先重渲染当前语义，返回更新后的设备传输状态。

        准备进行中时拒绝重试；候选预算或生成失败时保留可诊断的错误状态。
        """
        if self._following():
            raise ValueError("请先结束跟弹，再重试声音设备")
        if self.current_job and not self.jobs[self.current_job]["done"]:
            raise ValueError("请先完成或取消乐谱准备，再重试设备")
        self.configuration_generation += 1
        generation = self.configuration_generation
        plan = self.plan

        def cancelled() -> bool:
            """检查设备恢复是否因关闭、换曲或新配置而过期。"""
            return (
                self.closed
                or self.plan is not plan
                or generation != self.configuration_generation
            )

        async with self._audio_candidate(cancelled):
            async with self.command_lock:
                position = await self.audio.fade_halt()
                before = (
                    self.active.get("sample_rate", self.audio.sample_rate)
                    if self.active
                    else self.audio.sample_rate
                )
                self.audio.open()
                self.phase = "paused" if plan else "empty"
                if self.audio.ready and plan and self.audio.sample_rate != before:
                    count = (
                        round(
                            (plan.duration_s / self.config["rate"] + 2)
                            * self.audio.sample_rate
                        )
                        * 8
                    )
                    try:
                        require_pcm_budget(count, self.audio.pcm.nbytes)
                    except ValueError as exc:
                        self.audio.ready = False
                        self.audio.error = str(exc)
                    else:
                        try:
                            pcm = await asyncio.to_thread(
                                render,
                                self.score,
                                self.config,
                                self.audio.sample_rate,
                                cancelled,
                            )
                        except Exception as exc:
                            self.audio.ready = False
                            self.audio.error = "新设备的声音准备失败：" + str(exc)
                            raise
                        if cancelled():
                            raise ValueError("设备准备已过期")
                        self.audio.install(
                            pcm, self.config["rate"], plan.duration_s, position
                        )
                        self.active["sample_rate"] = self.audio.sample_rate
                elif plan:
                    self.audio.set_position(position)
                return self.get_transport()

    def _cleanup_job_folder(self, job: Record) -> None:
        """Remove a job directory once no active snapshot still references it."""
        folder = job.get("folder")
        active_folders = (
            {self.active["folder"], self.active.get("layout_folder")}
            if self.active
            else set()
        )
        if folder and folder not in active_folders:
            shutil.rmtree(folder, ignore_errors=True)

    def _prune(self) -> None:
        """清理较早的已完成作业及无活动引用的临时目录，保留当前源与谱面。"""
        for jid, job in list(self.jobs.items())[:-16]:
            if job["done"] and "future" not in job:
                del self.jobs[jid]
                self._cleanup_job_folder(job)

    def close(self) -> None:
        """幂等取消全部作业、关闭音频并等待工作线程回收，释放所有候选与活动引用。"""
        if self.closed:
            return
        self._practice_epoch += 1
        if self._following():
            self.follow.pause(time.monotonic_ns())
            self._save_follow("interrupted")
        if self._follow_task is not None:
            self._follow_task.cancel()
        if self._practice_task is not None:
            self._practice_task.cancel()
        self.closed = True
        for jid in list(self.jobs):
            self.cancel_job(jid)
        if self.practice.state in ("playing", "paused"):
            self.practice.finish(self.get_transport(), "interrupted")
        self.audio.close()
        self.pool.shutdown(wait=True, cancel_futures=True)
        for job in self.jobs.values():
            self._cleanup_job_folder(job)
        self.candidates.clear()
        self.confirmations.clear()
        self.layout_candidates.clear()
        with self.semantic_cache_lock:
            self.semantic_cache.clear()
        self.practice.close()
        self.monitor.close()
        self.active = None
        for job in self.jobs.values():
            self._cleanup_job_folder(job)
