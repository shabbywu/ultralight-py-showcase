"""声音数组、试听配置和设备回调的类型约定，时间单位为秒。"""

from __future__ import annotations

from typing import Literal, Protocol, TypeAlias, TypedDict

import numpy as np
from numpy.typing import NDArray

PCM: TypeAlias = NDArray[np.float32]
FloatArray: TypeAlias = NDArray[np.float64]
AudioRecord: TypeAlias = tuple[int, int, float, list[tuple[int, int, int]]]
AudibleEvent: TypeAlias = tuple[str, str, int, int, float, float, float]


class TrackSelection(TypedDict):
    """单个轨道的静音及独奏选择。"""

    id: str
    muted: bool
    solo: bool


class PlaybackConfig(TypedDict, total=False):
    """已校验的试听配置；省略 allowed_note_ids 表示不按音符 ID 过滤。"""

    rate: float
    hand_mode: Literal["both", "left", "right"]
    tracks: list[TrackSelection]
    allowed_note_ids: list[str] | set[str] | None
    staff_ids: list[str]
    voice_ids: list[str]


class Overview(TypedDict):
    """按时间分桶的振幅极值；双声道共同保留峰值。"""

    min: list[float]
    max: list[float]


class Analysis(TypedDict):
    """供前端绘图的波形均值与单边频谱，频率单位为 Hz。"""

    waveform: list[float]
    spectrum_db: list[float]
    frequency_min_hz: float
    frequency_max_hz: float


class CallbackTime(Protocol):
    """PortAudio 提供的输出缓冲预计到达 DAC 的绝对时间。"""

    outputBufferDacTime: float
