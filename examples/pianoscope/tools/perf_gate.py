"""Deterministic transport hot-path benchmark without a native audio device."""

from __future__ import annotations

import argparse
import json
import time
from statistics import quantiles
from types import SimpleNamespace

import numpy as np

from pianoscope.playback.audio import Audio
from pianoscope.playback.model import Note, Score
from pianoscope.playback.player import ScorePlayer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=int, default=20_000)
    parser.add_argument("--iterations", type=int, default=2_000)
    args = parser.parse_args()

    notes = [
        Note(
            str(index),
            "P:1",
            21 + index % 88,
            80,
            index / 100,
            index / 100 + 0.05,
            index / 100 + 0.1,
        )
        for index in range(args.notes)
    ]
    score = Score(
        "benchmark",
        max(20.0, args.notes / 100),
        [{"id": "P:1", "source_channel": 0}],
        notes,
        [],
        [],
    )
    audio = Audio()
    audio.pcm = np.zeros((1, 2), np.float32)
    audio.duration = score.duration_s
    audio.ready = True
    audio.playing = True
    player = ScorePlayer(audio=audio)
    player.score = score
    player.config = dict(
        rate=1.0,
        hand_mode="both",
        tracks=[{"id": "P:1", "muted": False, "solo": False}],
    )
    player.plan = SimpleNamespace(
        duration_s=score.duration_s,
        revision="benchmark",
        document=SimpleNamespace(revision="benchmark"),
        display_spans=[],
        occurrence_at=lambda _seconds: None,
        qn_at_seconds=lambda _seconds: 0.0,
    )
    player._rebuild_transport_index()
    samples = []
    for index in range(args.iterations):
        audio.position = (index % max(1, int(score.duration_s * 100))) / 100
        started = time.perf_counter()
        player.get_transport()
        samples.append((time.perf_counter() - started) * 1000)
    player.close()
    p95 = quantiles(samples, n=20)[18] if len(samples) >= 20 else max(samples)
    print(
        json.dumps(
            {
                "notes": args.notes,
                "iterations": args.iterations,
                "mean_ms": sum(samples) / len(samples),
                "p95_ms": p95,
                "max_ms": max(samples),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
