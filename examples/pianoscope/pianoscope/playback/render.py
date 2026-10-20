"""Offline event-time rendering. A job exclusively owns its synthesizer."""

import numpy as np

from pianoscope.playback.budget import require_pcm_budget
from pianoscope.playback.synth import Synth


def audible_notes(score, config):
    tracks = {t["id"]: t for t in config["tracks"]}
    solo = any(t["solo"] for t in tracks.values())
    allowed = config.get("allowed_note_ids")
    allowed = set(allowed) if allowed is not None else None
    return [
        n
        for n in score.notes
        if (config["hand_mode"] == "both" or n.hand == config["hand_mode"])
        and (allowed is None or n.id in allowed)
        and not tracks[n.track_id]["muted"]
        and (not solo or tracks[n.track_id]["solo"])
    ]


def render(
    score, config, sample_rate, cancelled=lambda: False, progress=lambda _: None
):
    rate = config["rate"]
    count = round((score.duration_s / rate + 2) * sample_rate)
    require_pcm_budget(count * 8)
    notes = audible_notes(score, config)
    # Assign overlap lanes per track/pitch; different pitches share a channel safely.
    slots = {}
    routes = {}
    events = []
    channels = {}
    source_by_track = {t["id"]: t["source_channel"] for t in score.tracks}
    for n in sorted(notes, key=lambda n: n.start_s):
        ends = slots.setdefault((n.track_id, n.pitch), [])
        slot = next((i for i, e in enumerate(ends) if e <= n.start_s), len(ends))
        if slot == len(ends):
            ends.append(n.sustain_end_s)
        else:
            ends[slot] = n.sustain_end_s
        key = (n.track_id, slot)
        if key not in channels:
            channels[key] = len(channels)
        ch = channels[key]
        if ch >= 256:
            raise ValueError("同键重叠超过合成器虚拟通道容量")
        routes[n.id] = ch
        # Same-sample key-off precedes the next key-on, preserving re-articulation.
        start = round(n.start_s / rate * sample_rate)
        end = max(start + 1, round(n.sustain_end_s / rate * sample_rate))
        events.extend(
            [(start, 2, "on", ch, n.pitch, n.velocity), (end, 0, "off", ch, n.pitch, 0)]
        )
    for cc in score.controls:
        # CC64 is retained for provenance; sustain is already baked into note ends.
        if cc["control"] == 64:
            continue
        for (tid, slot), ch in channels.items():
            if source_by_track[tid] == cc["source_channel"]:
                events.append(
                    (
                        round(cc["time_s"] / rate * sample_rate),
                        1,
                        "cc",
                        ch,
                        cc["control"],
                        cc["value"],
                    )
                )
    events.sort(key=lambda e: e[:2])
    pcm = np.empty((count, 2), dtype=np.float32)
    with Synth(sample_rate) as synth:
        cursor = 0

        def fill(target):
            nonlocal cursor
            while cursor < target:
                if cancelled():
                    raise InterruptedError("已取消")
                end = min(target, cursor + 2048)
                pcm[cursor:end] = synth.samples(end - cursor)
                cursor = end
                progress(cursor / count)

        for frame, _, kind, ch, pitch, value in events:
            fill(min(frame, count))
            if kind == "on":
                synth.note_on(ch, pitch, value)
            elif kind == "off":
                synth.note_off(ch, pitch)
            else:
                synth.cc(ch, pitch, value)
        fill(count)
    np.clip(pcm, -1, 1, out=pcm)
    pcm.flags.writeable = False
    return pcm
