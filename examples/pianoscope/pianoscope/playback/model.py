"""由 MusicXML 编译器与原 SoundFont 内核共享的播放事件模型。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from pianoscope.types import Record


@dataclass
class Note:
    """供原 SoundFont 内核播放的单次起音，所有时间字段均为曲目秒数或显式 tick。"""

    id: str
    track_id: str
    pitch: int
    velocity: int
    start_s: float
    key_off_s: float
    sustain_end_s: float
    hand: str = "unassigned"
    hand_source: str = "unknown"
    start_tick: int = 0
    key_off_tick: int = 0
    source_event: str = ""


@dataclass
class Score:
    """声音内核使用的轨道、按键、控制器及来源快照。"""

    title: str
    duration_s: float
    tracks: list[Record]
    notes: list[Note]
    tempo_map: list[Record]
    meter_map: list[Record]
    controls: list[Record] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 1
    hand_assignment: dict[str, str] = field(
        default_factory=lambda: {"status": "unassigned", "source": "external"}
    )
    ppqn: int = 480
    source_fingerprint: str = ""
    key_map: list[Record] = field(default_factory=list)
    duration_tick: int = 0

    def metadata(self) -> Record:
        """返回播放事件的摘要、音域和来源元数据；要求至少存在一个音符。"""
        pitches = sorted({n.pitch for n in self.notes})
        return dict(
            score_id=self.score_id,
            revision=self.revision,
            title=self.title,
            duration_s=self.duration_s,
            tracks=self.tracks,
            notes_count=len(self.notes),
            pitch_min=min(pitches),
            pitch_max=max(pitches),
            used_pitches=pitches,
            tempo_map=self.tempo_map,
            meter_map=self.meter_map,
            hand_assignment=self.hand_assignment,
            warnings=self.warnings,
            ppqn=self.ppqn,
            source_fingerprint=self.source_fingerprint,
            key_map=self.key_map,
            duration_tick=self.duration_tick,
        )
