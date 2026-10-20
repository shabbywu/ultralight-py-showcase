"""Assignments are explicit and previewed; track names are hints only."""

from collections import Counter
from dataclasses import replace

VALID = {"left", "right", "unassigned"}


def preview(score, rule):
    kind = rule.get("type", "current")
    if kind not in ("current", "tracks", "pitch_split"):
        raise ValueError("未知的左右手分配方式")
    split = rule.get("pitch", 60)
    if kind == "pitch_split" and (
        not isinstance(split, (int, float)) or not 21 <= split <= 108
    ):
        raise ValueError("分界音需在 A0–C8 内")
    mapping = rule.get("tracks", {})
    if any(v not in VALID for v in mapping.values()):
        raise ValueError("无效的手别")
    values = {}
    for n in score.notes:
        values[n.id] = (
            n.hand
            if kind == "current"
            else mapping.get(n.track_id, "unassigned")
            if kind == "tracks"
            else "left"
            if n.pitch < split
            else "right"
        )
    return values, dict(Counter(values.values()))


def assigned(score, values, overrides):
    values = dict(values)
    ids = {n.id for n in score.notes}
    for nid, hand in overrides.items():
        if nid not in ids or hand not in VALID:
            raise ValueError("无效的音符或手别")
        values[nid] = hand
    notes = [replace(n, hand=values[n.id], hand_source="manual") for n in score.notes]
    status = "confirmed" if all(n.hand != "unassigned" for n in notes) else "partial"
    return replace(
        score,
        notes=notes,
        revision=score.revision + 1,
        hand_assignment={"status": status, "source": "manual"},
    )
