"""Playback events shared by the MusicXML compiler and sound engine."""

import uuid
from dataclasses import dataclass, field


@dataclass
class Note:
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
    title: str
    duration_s: float
    tracks: list
    notes: list
    tempo_map: list
    meter_map: list
    controls: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    score_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 1
    hand_assignment: dict = field(
        default_factory=lambda: {"status": "unassigned", "source": "external"}
    )
    ppqn: int = 480
    source_fingerprint: str = ""
    key_map: list = field(default_factory=list)
    duration_tick: int = 0

    def metadata(self):
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
