"""以唯一 DAC 时钟驱动的 MIDI 练习、轮次判定及历史持久化。"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

from pianoscope.practice.midi import MidiEvent, MidiInput
from pianoscope.practice.storage import PracticeStore
from pianoscope.types import Record


class PracticeManager:
    """将 MIDI 事件匹配到不可变的练习目标，逐轮提交结果。"""

    MATCH_WINDOW_S = 0.150
    HIT_WINDOW_S = 0.050

    def __init__(self, database: Path) -> None:
        """建立练习服务，不自动打开 MIDI 端口。"""
        self.midi = MidiInput()
        self.store = PracticeStore(database)
        self.session_id: str | None = None
        self.state = "idle"
        self.metadata: Record = {}
        self.expected: list[Record] = []
        self.matched: set[tuple[int, str]] = set()
        self.results: list[Record] = []
        self.counts: Counter = Counter()
        self.round_index = 1
        self.completed_rounds = 0
        self.ordinal = 0
        self.delta_total = 0.0
        self.delta_count = 0
        self.latest: Record | None = None
        self.summary: Record = {}
        self.last_position = 0.0
        self.active_inputs: dict[int, Record] = {}

    def midi_inputs(self) -> Record:
        """返回输入设备及当前连接状态。"""
        return dict(self.midi.list_inputs(), **self.midi.status())

    def select_midi_input(self, name: str | None) -> Record:
        """选择输入设备，活动会话中由控制器约束。"""
        return self.midi.select(name)

    def start(self, plan: Any, config: Record, transport: Record) -> Record:
        """锁定目标与配置，并建立一条可包含多轮的会话。"""
        if self.state in ("playing", "paused", "countdown", "preparing"):
            raise ValueError("已有练习会话正在进行")
        loop = transport["loop"]
        a, b = (loop["a_s"], loop["b_s"]) if loop["enabled"] else (0.0, plan.duration_s)
        options = config.get("practice_options", {})
        if not loop["enabled"] and options.get("range_enabled"):
            a, b = options["range_a_s"], options["range_b_s"]
        allowed = config.get("allowed_note_ids")
        occurrences = {r["id"]: r for r in getattr(plan, "occurrences", [])}
        self.expected = []
        for note in plan.instances:
            if (
                not a <= note["onset_s"] < b
                or allowed is not None
                and note["id"] not in allowed
            ):
                continue
            occurrence_id = (note.get("occurrence_ids") or [None])[0]
            occurrence = occurrences.get(occurrence_id, {})
            self.expected.append(
                dict(
                    instance_id=note["id"],
                    pitch=note["pitch"],
                    onset_s=note["onset_s"],
                    occurrence_id=occurrence_id,
                    locator=(
                        "小节 "
                        + str(occurrence["number"])
                        + " · 第 "
                        + str(occurrence["visit_index"])
                        + " 遍"
                    )
                    if occurrence
                    else "",
                )
            )
        if not self.expected:
            raise ValueError("练习片段内没有目标音符")
        self.expected.sort(key=lambda n: (n["onset_s"], n["pitch"], n["instance_id"]))
        self.metadata = dict(
            source_fingerprint=plan.document.source.sha256,
            source_revision=plan.document.revision,
            playback_revision=plan.revision,
            rate=config["rate"],
            hand_mode=config.get("hand_mode", "both"),
            staff_ids=config.get("staff_ids") or [],
            voice_ids=config.get("voice_ids") or [],
            loop_a_s=a,
            loop_b_s=b,
            loop_enabled=loop["enabled"],
            expected_count=len(self.expected),
            title=config.get("title", ""),
            device=config.get("device", ""),
            options=config.get("practice_options", {}),
            original_name=getattr(plan.document.source, "original_name", ""),
            rules_version=1,
        )
        self.session_id = self.store.create(self.metadata)
        self.matched.clear()
        self.results.clear()
        self.counts.clear()
        self.active_inputs.clear()
        self.round_index = 1
        self.base_round = transport.get("loop_round", 0)
        self.completed_rounds = self.ordinal = self.delta_count = 0
        self.delta_total = 0.0
        self.latest = None
        self.summary = {}
        self.state = "playing"
        self.last_position = a
        return self.snapshot(transport)

    def _append(self, result: Record) -> None:
        """为结果加轮次、序号并更新累计指标。"""
        result.setdefault("round_index", self.round_index)
        result["ordinal"] = self.ordinal
        self.ordinal += 1
        self.results.append(result)
        self.counts[result["result"]] += 1
        if "delta_ms" in result:
            self.delta_total += abs(result["delta_ms"])
            self.delta_count += 1
        self.latest = result

    def _misses(self, position: float, round_index: int | None = None) -> None:
        """只将已超过真实时间匹配窗口的目标标为漏音。"""
        round_index = round_index or self.round_index
        window = self.MATCH_WINDOW_S * self.metadata["rate"]
        for target in self.expected:
            if (round_index, target["instance_id"]) not in self.matched and target[
                "onset_s"
            ] + window < position:
                self.matched.add((round_index, target["instance_id"]))
                self._append(
                    dict(
                        result="miss",
                        round_index=round_index,
                        expected_instance_id=target["instance_id"],
                        occurrence_id=target["occurrence_id"],
                        expected_pitch=target["pitch"],
                        expected_s=target["onset_s"],
                        locator=target["locator"],
                    )
                )

    def _flush(self, status: str) -> None:
        """原子提交本轮增量和会话累计指标，限制内存占用。"""
        evaluated = sum(self.counts[k] for k in ("hit", "early", "late", "miss"))
        self.summary = dict(
            hit_count=self.counts["hit"],
            early_count=self.counts["early"],
            late_count=self.counts["late"],
            miss_count=self.counts["miss"],
            extra_count=self.counts["extra"],
            evaluated_count=evaluated,
            completed_rounds=self.completed_rounds,
            mean_abs_delta_ms=self.delta_total / self.delta_count
            if self.delta_count
            else None,
            status=status,
        )
        if self.session_id:
            self.store.finish(self.session_id, self.summary, self.results)
        self.results.clear()

    def _advance(self, round_index: int) -> None:
        """按 DAC 已听到的循环编号结算完整轮次。"""
        self.round_index = max(self.round_index, round_index)

    def _finalize_rounds(self, position: float, stopping: bool = False) -> None:
        """等待跨循环边界的滞后窗口结束后，才结算上一轮。"""
        last = self.round_index - 1
        if (
            not stopping
            and position
            < self.metadata["loop_a_s"] + self.MATCH_WINDOW_S * self.metadata["rate"]
        ):
            last -= 1
        while self.completed_rounds < last:
            index = self.completed_rounds + 1
            self._misses(
                self.metadata["loop_b_s"]
                + self.MATCH_WINDOW_S * self.metadata["rate"]
                + 0.001,
                index,
            )
            self.completed_rounds += 1
            self._flush("playing")
            self.matched = {key for key in self.matched if key[0] > index}

    def _event(
        self, event: MidiEvent, position: float, event_round: int | None = None
    ) -> None:
        """处理一个时间映射后的输入，先匹配再推进漏音。"""
        if event.kind != "note_on":
            result = self.active_inputs.pop(event.pitch, None)
            if result is not None:
                if result not in self.results:
                    self.results.append(result)
                result["actual_duration_ms"] = max(
                    0,
                    (event.timestamp_ns - result.pop("_started_ns", event.timestamp_ns))
                    / 1_000_000,
                )
            return
        event_round = event_round or self.round_index
        candidates = []
        span = self.metadata["loop_b_s"] - self.metadata["loop_a_s"]
        rounds = [event_round]
        if (
            self.metadata["loop_enabled"]
            and event_round > 1
            and event_round - 1 > self.completed_rounds
        ):
            rounds.append(event_round - 1)
        for index in rounds:
            for n in self.expected:
                delta = (
                    position + (event_round - index) * span - n["onset_s"]
                ) / self.metadata["rate"]
                if (
                    (index, n["instance_id"]) not in self.matched
                    and n["pitch"] == event.pitch
                    and abs(delta) <= self.MATCH_WINDOW_S
                ):
                    candidates.append((n, index, delta))
        result = dict(
            result="extra",
            actual_pitch=event.pitch,
            actual_s=position,
            velocity=event.velocity,
            round_index=event_round,
        )
        if candidates:
            target, target_round, delta = min(candidates, key=lambda item: abs(item[2]))
            self.matched.add((target_round, target["instance_id"]))
            result["round_index"] = target_round
            result.update(
                result="hit"
                if abs(delta) <= self.HIT_WINDOW_S
                else "early"
                if delta < 0
                else "late",
                expected_instance_id=target["instance_id"],
                occurrence_id=target["occurrence_id"],
                expected_pitch=target["pitch"],
                expected_s=target["onset_s"],
                delta_ms=delta * 1000,
                locator=target["locator"],
            )
        self._append(result)
        result["_started_ns"] = event.timestamp_ns
        self.active_inputs[event.pitch] = result

    def update(self, transport: Record) -> Record:
        """由后端调度推进判定，前端读取不会产生重复结果。"""
        if self.state != "playing":
            return self.snapshot(transport)
        position = transport["position_s"]
        loop = self.metadata["loop_enabled"]
        a, b = self.metadata["loop_a_s"], self.metadata["loop_b_s"]
        round_index = 1 + max(
            0, transport.get("loop_round", self.base_round) - self.base_round
        )
        now = time.monotonic_ns()
        for event in self.midi.drain():
            elapsed = (
                max(0, (now - event.timestamp_ns) / 1_000_000_000)
                * self.metadata["rate"]
                if transport["phase"] == "playing"
                else 0
            )
            absolute = (round_index - 1) * (b - a) + position - a - elapsed
            event_round = max(1, int(absolute // (b - a)) + 1) if loop else 1
            if (
                event_round < self.round_index
                or absolute < -self.MATCH_WINDOW_S * self.metadata["rate"]
            ):
                continue
            self._advance(event_round)
            event_position = (
                a + absolute - (event_round - 1) * (b - a)
                if loop
                else position - elapsed
            )
            self._event(event, event_position, event_round)
        self._advance(round_index)
        self._finalize_rounds(position)
        self._misses(position)
        self.last_position = position
        if transport["phase"] == "ended":
            return self.finish(transport)
        return self.snapshot(transport)

    def finish(self, transport: Record, reason: str | None = None) -> Record:
        """保存部分结果，未经过的目标保持未评估。"""
        if self.state in ("idle", "finished"):
            return self.snapshot(transport)
        self._finalize_rounds(transport["position_s"], stopping=True)
        self._misses(
            transport["position_s"]
            + (
                self.MATCH_WINDOW_S * self.metadata["rate"] + 0.001
                if transport["phase"] == "ended"
                else 0
            )
        )
        if transport["phase"] == "ended":
            self.completed_rounds += 1
        self._flush(
            reason or ("finished" if transport["phase"] == "ended" else "stopped")
        )
        self.state = "finished"
        return self.snapshot(transport)

    def snapshot(self, transport: Record) -> Record:
        """返回实时指标和已保存摘要。"""
        return dict(
            state=self.state,
            session_id=self.session_id,
            round_index=self.round_index,
            completed_rounds=self.completed_rounds,
            expected_count=len(self.expected),
            matched_count=sum(self.counts[k] for k in ("hit", "early", "late")),
            hit_count=self.counts["hit"],
            early_count=self.counts["early"],
            late_count=self.counts["late"],
            miss_count=self.counts["miss"],
            extra_count=self.counts["extra"],
            latest_event=self.latest,
            summary=self.summary,
            elapsed_s=max(
                0, transport["position_s"] - self.metadata.get("loop_a_s", 0)
            ),
        )

    def results_page(self, session_id: str, offset: int, limit: int) -> Record:
        """分页读取持久化逐音符报告。"""
        return self.store.results(session_id, offset, limit)

    def close(self) -> None:
        """关闭 MIDI 服务。"""
        self.midi.close()
