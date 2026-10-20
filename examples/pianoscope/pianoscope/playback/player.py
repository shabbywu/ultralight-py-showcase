"""以同一 MusicXML 演奏计划驱动原 SoundFont PCM 和设备 DAC 时钟。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar

from pianoscope.playback.audio import Audio
from pianoscope.playback.budget import require_pcm_budget
from pianoscope.playback.render import audible_notes, render
from pianoscope.playback.types import PCM, PlaybackConfig
from pianoscope.score.mapping import json_value
from pianoscope.score.midi import sound_score
from pianoscope.score.plan import PlaybackPlan
from pianoscope.types import Record

P = ParamSpec("P")
R = TypeVar("R")
Player = TypeVar("Player", bound="ScorePlayer")


def serialized(
    method: Callable[Concatenate[Player, P], Awaitable[R]],
) -> Callable[Concatenate[Player, P], Awaitable[R]]:
    """把异步播放命令串行化；保留被装饰方法的参数和返回类型。

    关闭后的命令抛出 ValueError，锁只保护应用线程中的提交操作。
    """

    @wraps(method)
    async def command(self: Player, *args: P.args, **kwargs: P.kwargs) -> R:
        """获取当前播放器的命令锁，确认未关闭后执行原异步方法。"""
        async with self.command_lock:
            if self.closed:
                raise ValueError("应用已关闭")
            return await method(self, *args, **kwargs)

    return command


class ScorePlayer:
    """管理同一演奏语义和声音缓冲的设备播放命令。"""

    def __init__(
        self,
        plan: PlaybackPlan | None = None,
        pcm: PCM | None = None,
        audio: Audio | None = None,
    ) -> None:
        """建立唯一播放器；未注入 audio 时打开真实输出设备，可安装已准备的演奏计划。"""
        self.audio = audio or Audio()
        if audio is None:
            self.audio.open()
        self.plan = None
        self.score = None
        self.config = None
        self.seq = 0
        self.closed = False
        self.phase = "empty"
        self.command_lock = asyncio.Lock()
        if plan is not None:
            self.install(plan, pcm)

    def install(self, plan: PlaybackPlan, pcm: PCM) -> None:
        """安装同一语义编译的演奏计划与完成的 PCM，复位试听、循环和播放位置。"""
        score = sound_score(plan)
        config = dict(
            rate=1.0,
            hand_mode="both",
            tracks=[dict(id=t["id"], muted=False, solo=False) for t in score.tracks],
        )
        self.audio.install(pcm, 1.0, plan.duration_s, 0.0)
        self.audio.loop = dict(enabled=False, a_s=0.0, b_s=min(plan.duration_s, 4.0))
        self.plan, self.score, self.config = plan, score, config
        self.phase = "ready"

    @serialized
    async def play(self) -> Record:
        """从当前或循环区间起点启动设备，返回 DAC 传输状态；无曲目时抛出 ValueError。"""
        if self.closed or self.plan is None:
            raise ValueError("请先打开乐谱")
        if self.audio.clock()[2] or self.audio.position >= self.plan.duration_s:
            self.audio.set_position(0.0)
        if (
            self.audio.loop["enabled"]
            and not self.audio.loop["a_s"]
            <= self.audio.position
            < self.audio.loop["b_s"]
        ):
            self.audio.set_position(self.audio.loop["a_s"])
        self.audio.start()
        self.phase = "playing"
        return self.get_transport()

    @serialized
    async def pause(self) -> Record:
        """等待短淡出后暂停在可听位置，返回传输状态。"""
        await self.audio.fade_halt()
        if self.plan:
            self.phase = "paused"
        return self.get_transport()

    @serialized
    async def stop(self) -> Record:
        """淡出停止并回到曲首，保留循环区间，返回传输状态。"""
        await self.audio.fade_halt()
        if self.plan:
            self.audio.set_position(0.0)
            self.phase = "ready"
        return self.get_transport()

    @serialized
    async def seek(
        self, seconds: float, expected_playback_revision: str | None = None
    ) -> Record:
        """按曲目秒数跳转并保持播放状态，返回传输状态。

        位置限制在曲目或已启用循环内；指定演奏版本不匹配时拒绝过期跳转。
        """
        if self.plan is None:
            raise ValueError("请先打开乐谱")
        if (
            expected_playback_revision
            and self.plan.revision != expected_playback_revision
        ):
            raise ValueError("谱面跳转已过期")
        was_playing = self.audio.playing
        await self.audio.fade_halt()
        seconds = max(0.0, min(self.plan.duration_s, float(seconds)))
        if self.audio.loop["enabled"]:
            seconds = max(self.audio.loop["a_s"], min(self.audio.loop["b_s"], seconds))
        self.audio.set_position(seconds)
        if was_playing:
            self.audio.start()
        self.phase = "playing" if was_playing else "paused"
        return self.get_transport()

    async def seek_score(
        self, element_id: str, occurrence_id: str | None = None
    ) -> Record:
        """由源元素及可选反复遍次定位，返回传输状态与候选遍次信息。"""
        target = self.plan.seek_target(
            str(element_id), self.audio.clock()[0], occurrence_id
        )
        transport = await self.seek(target["start_s"], self.plan.revision)
        return dict(transport, seek_target=json_value(target))

    def set_volume(self, volume: float) -> Record:
        """设置 0–1 设备输出增益并返回状态；超出范围时抛出 ValueError。"""
        value = float(volume)
        if not 0 <= value <= 1:
            raise ValueError("音量必须在 0–1 内")
        self.audio.volume = value
        return self.get_transport()

    async def set_loop(self, enabled: bool, a_s: float, b_s: float) -> Record:
        """设置以曲目秒数表示的循环区间；区间至少 0.5 秒且必须位于曲目内。

        在命令锁中淡出、安装区间并恢复播放，不用前端定时器调度循环。
        """
        if self.plan is None:
            raise ValueError("请先打开乐谱")
        a, b = float(a_s), float(b_s)
        if not 0 <= a < b <= self.plan.duration_s or b - a < 0.5:
            raise ValueError("循环区间至少 0.5 秒，且不能超出曲目")
        async with self.command_lock:
            resume = self.audio.playing
            position = await self.audio.fade_halt()
            self.audio.loop = dict(enabled=bool(enabled), a_s=a, b_s=b)
            if enabled and not a <= position < b:
                position = a
            self.audio.set_position(position)
            if resume:
                self.audio.start()
            return self.get_transport()

    async def configure(self, changes: PlaybackConfig) -> Record:
        """先渲染候选速度和试听配置，再替换当前 PCM，返回传输状态。

        倍率限 0.5／0.75／1；候选预算失败保留旧声音，设备时钟始终由同一 Audio 提供。
        """
        config = dict(self.config, **changes)
        if config["rate"] not in (0.5, 0.75, 1.0):
            raise ValueError("支持 0.5×／0.75×／1×")
        # Prepare before touching the currently audible version.
        count = round(
            (self.plan.duration_s / config["rate"] + 2) * self.audio.sample_rate
        )
        require_pcm_budget(count * 8, self.audio.pcm.nbytes)
        pcm = await asyncio.to_thread(
            render, self.score, config, self.audio.sample_rate
        )
        was_playing = self.audio.playing
        position = await self.audio.fade_halt()
        self.audio.install(pcm, config["rate"], self.plan.duration_s, position)
        self.config = config
        if was_playing:
            self.audio.start()
        return self.get_transport()

    def get_transport(self) -> Record:
        """返回 DAC 驱动的位置、活动与延音实例、源映射及设备状态快照。

        发现设备停止或断开时记录错误；播放结束后固定到演奏时长。
        """
        seconds, tail, ended = self.audio.clock()
        if self.phase == "playing" and (
            not self.audio.ready
            or self.audio.stream is not None
            and not self.audio.stream.active
        ):
            self.audio.halt()
            self.audio.ready = False
            self.audio.error = "声音输出设备已断开"
            self.phase = "error"
        if ended:
            self.audio.halt()
            self.audio.position = self.plan.duration_s
            self.phase = "ended"
        self.seq += 1
        plan = self.plan
        audible = (
            audible_notes(self.score, self.config) if self.score is not None else []
        )
        active = (
            [n.id for n in audible if n.start_s <= seconds < n.key_off_s]
            if self.audio.playing and self.audio.volume > 0
            else []
        )
        sustained = (
            [n.id for n in audible if n.key_off_s <= seconds < n.sustain_end_s]
            if self.audio.playing and self.audio.volume > 0
            else []
        )
        spans = (
            [
                s
                for s in plan.display_spans
                if s["instance_id"] in active and s["start_s"] <= seconds < s["end_s"]
            ]
            if plan
            else []
        )
        occurrence = plan.occurrence_at(seconds) if plan else None
        return dict(
            seq=self.seq,
            clock_epoch=self.audio.epoch,
            phase=self.phase,
            position_s=seconds,
            duration_s=plan.duration_s if plan else 0.0,
            rate=self.config["rate"] if self.config else 1.0,
            volume=self.audio.volume,
            hand_mode=self.config["hand_mode"] if self.config else "both",
            loop=self.audio.loop,
            source_revision=plan.document.revision if plan else None,
            playback_revision=plan.revision if plan else None,
            occurrence_id=occurrence["id"] if occurrence else None,
            measure_number=occurrence["number"] if occurrence else None,
            visit_index=occurrence["visit_index"] if occurrence else None,
            measure_qn=plan.qn_at_seconds(seconds) - float(occurrence["start_qn"])
            if occurrence
            else 0.0,
            active_instance_ids=active,
            active_element_ids=[s["element_id"] for s in spans],
            sustained_instance_ids=sustained,
            audio_ready=self.audio.ready,
            audio_error=self.audio.error,
            underruns=self.audio.underruns,
            output_latency_s=float(self.audio.stream.latency)
            if self.audio.stream
            else None,
        )

    def close(self) -> None:
        """标记播放器已关闭，并关闭唯一音频输出及缓冲。"""
        self.closed = True
        self.audio.close()
