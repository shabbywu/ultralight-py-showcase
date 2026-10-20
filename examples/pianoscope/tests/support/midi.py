"""Legacy MIDI reader used only by sound-engine regression tests."""

import bisect
import hashlib
import io
from collections import defaultdict, deque
from pathlib import Path

import mido

from pianoscope.playback.model import Note, Score


class ScoreError(ValueError):
    pass


class TempoMap:
    def __init__(self, ppqn, changes):
        self.ppqn = ppqn
        self.ticks = [0]
        self.seconds = [0.0]
        self.tempos = [500000]
        for tick, tempo in changes:
            if tempo <= 0:
                raise ScoreError("速度值必须大于零")
            secs = self.at(tick)
            if tick == self.ticks[-1]:
                self.tempos[-1] = tempo
            else:
                self.ticks.append(tick)
                self.seconds.append(secs)
                self.tempos.append(tempo)

    def at(self, tick):
        i = bisect.bisect_right(self.ticks, tick) - 1
        return (
            self.seconds[i] + (tick - self.ticks[i]) * self.tempos[i] / self.ppqn / 1e6
        )

    def tick_at(self, seconds):
        i = max(0, bisect.bisect_right(self.seconds, seconds) - 1)
        return (
            self.ticks[i]
            + (seconds - self.seconds[i]) * self.ppqn * 1e6 / self.tempos[i]
        )


def parse_midi(path, cancelled=lambda: False, progress=lambda _: None):
    path = Path(path)
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ScoreError("文件超过 5 MiB 限制")
    data = path.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise ScoreError("不是有效的 MIDI 文件头")
    division = int.from_bytes(data[12:14], "big")
    if division & 0x8000:
        raise ScoreError("暂不支持 SMPTE 时间格式")
    if not division:
        raise ScoreError("无效的 PPQN 时间格式")
    try:
        mid = mido.MidiFile(file=io.BytesIO(data))
    except Exception as exc:
        raise ScoreError("MIDI 文件损坏或事件不完整") from exc
    if mid.type not in (0, 1):
        raise ScoreError("暂不支持 MIDI Type 2 独立序列")
    events = []
    names = {}
    warnings = []
    on_count = 0
    for ti, track in enumerate(mid.tracks):
        tick = 0
        for ei, msg in enumerate(track):
            tick += msg.time
            events.append((tick, ti, ei, msg))
            if msg.type == "track_name":
                names[ti] = msg.name
            if msg.type == "note_on" and msg.velocity:
                on_count += 1
            if len(events) > 200000:
                raise ScoreError("总事件超过 200,000 限制")
            if on_count > 50000:
                raise ScoreError("音符超过 50,000 限制")
        if cancelled():
            raise InterruptedError("已取消")
    events.sort(key=lambda e: e[:3])
    changes = []
    tempo_ticks = set()
    for tick, _, _, msg in events:
        if msg.type == "set_tempo":
            if tick in tempo_ticks:
                warnings.append("同一时刻存在多个速度，采用最后一项。")
            tempo_ticks.add(tick)
            changes.append((tick, msg.tempo))
    tempo = TempoMap(division, changes)
    duration = tempo.at(events[-1][0]) if events else 0
    if duration > 600:
        raise ScoreError("源曲时长超过 600 秒限制")
    tracks = {}
    notes = []
    active = defaultdict(deque)
    pedal = defaultdict(bool)
    held = defaultdict(list)
    controls = []
    meters = []
    keys = []
    outside = 0
    drums = 0
    unsupported = set()

    def release(key, time, tick):
        queue = active[key]
        if not queue:
            warnings.append("忽略孤立的松键事件。")
            return
        note = queue.popleft()
        note.key_off_s = time
        note.key_off_tick = tick
        if pedal[key[1]]:
            held[key[1]].append(note)
        else:
            note.sustain_end_s = time

    for index, (tick, ti, ei, msg) in enumerate(events):
        if index % 1024 == 0:
            if cancelled():
                raise InterruptedError("已取消")
            progress(index / max(1, len(events)))
        time = tempo.at(tick)
        if msg.type == "time_signature":
            meters.append(
                dict(
                    tick=tick,
                    time_s=time,
                    numerator=msg.numerator,
                    denominator=msg.denominator,
                    source="midi",
                )
            )
        if msg.type == "key_signature":
            keys.append(dict(tick=tick, time_s=time, key=msg.key, source="midi"))
        if msg.type == "sysex":
            unsupported.add("系统专用消息／自定义调律")
        if not hasattr(msg, "channel"):
            continue
        ch = msg.channel
        tid = f"t{ti}c{ch}"
        if msg.type == "note_on" and msg.velocity:
            if ch == 9:
                drums += 1
                continue
            if not 21 <= msg.note <= 108:
                outside += 1
                continue
            if tid not in tracks:
                name = names.get(ti, f"轨道 {ti + 1}")
                hint = (
                    "left"
                    if name.lower() in ("left", "lh")
                    else "right"
                    if name.lower() in ("right", "rh")
                    else None
                )
                tracks[tid] = dict(
                    id=tid,
                    name=name,
                    source_track=ti,
                    source_channel=ch,
                    suggested_hand=hint,
                    muted=False,
                    solo=False,
                )
            n = Note(
                f"n{len(notes)}",
                tid,
                msg.note,
                msg.velocity,
                time,
                duration,
                duration,
                start_tick=tick,
                key_off_tick=events[-1][0],
                source_event=f"t{ti}:e{ei}",
            )
            notes.append(n)
            active[(ti, ch, msg.note)].append(n)
        elif msg.type in ("note_off", "note_on"):
            if ch != 9 and 21 <= msg.note <= 108:
                release((ti, ch, msg.note), time, tick)
        elif msg.type == "control_change":
            if msg.control == 64:
                controls.append(
                    dict(
                        tick=tick,
                        time_s=time,
                        source_channel=ch,
                        control=64,
                        value=msg.value,
                        source_event=f"t{ti}:e{ei}",
                    )
                )
            if msg.control == 64:
                if pedal[ch] and msg.value < 64:
                    for n in held[ch]:
                        n.sustain_end_s = time
                    held[ch].clear()
                pedal[ch] = msg.value >= 64
            elif msg.control in (7, 11):
                controls.append(
                    dict(
                        tick=tick,
                        time_s=time,
                        source_channel=ch,
                        control=msg.control,
                        value=msg.value,
                    )
                )
            elif msg.control in (120, 123):
                for key, q in active.items():
                    if key[1] == ch:
                        while q:
                            n = q.popleft()
                            n.key_off_s = time
                            n.key_off_tick = tick
                            if msg.control == 123 and pedal[ch]:
                                held[ch].append(n)
                            else:
                                n.sustain_end_s = time
                if msg.control == 120:
                    controls.append(
                        dict(time_s=time, source_channel=ch, control=120, value=0)
                    )
                    for n in held[ch]:
                        n.sustain_end_s = time
                    held[ch].clear()
            else:
                unsupported.add("其他控制器")
        elif msg.type == "program_change":
            unsupported.add("音色切换（固定钢琴）")
        elif msg.type in ("pitchwheel", "aftertouch", "polytouch"):
            unsupported.add("弯音／触后")
    if any(active.values()):
        warnings.append("缺少松键事件，已在曲尾释放。")
    if outside:
        warnings.append(f"{outside} 个音符超出 A0–C8，已排除。")
    if drums:
        warnings.append(f"{drums} 个打击乐音符已排除。")
    if unsupported:
        warnings.append("未还原：" + "、".join(sorted(unsupported)))
    if not notes:
        raise ScoreError("EMPTY_SCORE：没有可播放的钢琴音符")
    if len(tracks) > 16:
        raise ScoreError("发声轨道超过 16 个限制")
    if not meters or meters[0]["tick"] > 0:
        meters.insert(
            0, dict(tick=0, time_s=0, numerator=4, denominator=4, source="default")
        )
    if not keys or keys[0]["tick"] > 0:
        keys.insert(0, dict(tick=0, time_s=0, key="C", source="default"))
    explicit_tempos = {t for t, _ in changes}
    return Score(
        path.stem,
        duration,
        list(tracks.values()),
        notes,
        [
            dict(
                tick=tick,
                time_s=s,
                quarter_bpm=60e6 / t,
                tempo_us=t,
                source="midi" if tick in explicit_tempos else "default",
            )
            for tick, s, t in zip(tempo.ticks, tempo.seconds, tempo.tempos)
        ],
        meters,
        controls,
        list(dict.fromkeys(warnings)),
        ppqn=division,
        source_fingerprint=hashlib.sha256(data).hexdigest(),
        key_map=keys,
        duration_tick=events[-1][0],
    )
