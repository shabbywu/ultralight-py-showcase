"""Hand labels reuse PCM; audible changes retain transactional preparation."""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from test_transactions import FIXTURES, load

from pianoscope.playback import budget as pcm_budget
from pianoscope.playback.render import audible_notes, render


def labels(c, reverse=False):
    return {
        e.id: ("left" if (e.staff_id.endswith(":2") != reverse) else "right")
        for e in c.plan.document.elements
        if e.pitch is not None
    }


def test_labels_undo_and_equivalent_scope_never_allocate_or_move_clock(
    controller, monkeypatch
):
    c = controller
    load(c, FIXTURES / "temporal.musicxml", engrave=False)
    c.audio.position = 3.25
    pcm, epoch, source, midi = (
        c.audio.pcm,
        c.audio.epoch,
        c.plan.document,
        c.plan.midi_bytes,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("metadata must not synthesize")

    monkeypatch.setattr("pianoscope.app.controller.render", forbidden)
    monkeypatch.setattr(pcm_budget, "PCM_BUDGET_BYTES", 1)
    p = c.preview_hands(labels(c))
    asyncio.run(c.apply_hands(p["preview_id"]))
    assert c.get_document()["hand_status"] == "confirmed"
    assert c.audio.pcm is pcm and c.audio.epoch == epoch and c.audio.position == 3.25
    assert c.plan.document is source and c.plan.midi_bytes == midi
    assert all(n.hand in ("left", "right") for n in c.score.notes)
    asyncio.run(
        c.configure({"staff_ids": c.get_document()["staff_ids"], "hand_mode": "both"})
    )
    asyncio.run(c.undo_hands())
    assert not c.hands and not c.hand_history and c.config["hand_mode"] == "both"
    assert c.audio.pcm is pcm and c.audio.epoch == epoch and c.audio.position == 3.25


def test_single_hand_reassignment_renders_actual_changed_selection(
    controller, monkeypatch
):
    import pianoscope.app.controller as session

    c = controller
    load(c, FIXTURES / "temporal.musicxml", engrave=False)
    p = c.preview_hands(labels(c))
    asyncio.run(c.apply_hands(p["preview_id"]))
    asyncio.run(c.configure({"hand_mode": "left"}))
    before = c.audio.pcm
    expected = {n.id for n in c.score.notes if n.hand == "right"}
    real = session.render
    calls = []

    def recorded(*args, **kwargs):
        calls.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "render", recorded)
    p = c.preview_hands(labels(c, True))
    asyncio.run(c.apply_hands(p["preview_id"]))
    assert (
        len(calls) == 1
        and c.audio.pcm is not before
        and not np.array_equal(before, c.audio.pcm)
    )
    assert {n.id for n in audible_notes(c.score, c.config)} == expected
    asyncio.run(c.undo_hands())
    assert len(calls) == 2 and np.array_equal(before, c.audio.pcm)


def test_failed_hand_sound_or_budget_preserves_labels_history_preview_and_pcm(
    controller, monkeypatch
):
    c = controller
    load(c, FIXTURES / "temporal.musicxml", engrave=False)
    p = c.preview_hands(labels(c))
    asyncio.run(c.apply_hands(p["preview_id"]))
    asyncio.run(c.configure({"hand_mode": "left"}))
    p = c.preview_hands(labels(c, True))
    original = (
        c.plan,
        c.score,
        c.audio.pcm,
        c.audio.epoch,
        dict(c.hands),
        list(c.hand_history),
        dict(c.config),
        c.hand_preview,
    )

    def broken(*args, **kwargs):
        raise RuntimeError("synthesis failure")

    monkeypatch.setattr("pianoscope.app.controller.render", broken)
    with pytest.raises(RuntimeError, match="synthesis failure"):
        asyncio.run(c.apply_hands(p["preview_id"]))
    assert (
        c.plan is original[0]
        and c.score is original[1]
        and c.audio.pcm is original[2]
        and c.audio.epoch == original[3]
    )
    assert (c.hands, c.hand_history, c.config, c.hand_preview) == original[4:]
    monkeypatch.setattr(pcm_budget, "PCM_BUDGET_BYTES", 1)
    with pytest.raises(ValueError, match="MiB"):
        asyncio.run(c.apply_hands(p["preview_id"]))
    assert (
        c.plan is original[0]
        and c.audio.pcm is original[2]
        and c.hand_history == original[5]
        and c.hand_preview is original[7]
    )


def test_metadata_waiting_for_command_lock_expires_without_partial_commit(controller):
    c = controller
    load(c, FIXTURES / "temporal.musicxml", engrave=False)
    old_plan, pcm = c.plan, c.audio.pcm
    preview = c.preview_hands(labels(c))

    async def race():
        await c.command_lock.acquire()
        assignment = asyncio.create_task(c.apply_hands(preview["preview_id"]))
        await asyncio.sleep(0.01)
        newer = asyncio.create_task(c.configure({"hand_mode": "both"}))
        await asyncio.sleep(0.01)
        c.command_lock.release()
        with pytest.raises(ValueError, match="过期"):
            await assignment
        await newer

    asyncio.run(race())
    assert (
        c.plan is old_plan and c.audio.pcm is pcm and not c.hands and not c.hand_history
    )


def test_shared_budget_allows_real_song_sizes_and_rejects_before_synthesis():
    limit = pcm_budget.PCM_BUDGET_BYTES
    assert limit == 512 * 1024**2
    one = round((290.63453272004153 + 2) * 44100) * 8
    slow = round((290.63453272004153 / 0.5 + 2) * 44100) * 8
    assert one * 2 > 192 * 1024**2
    pcm_budget.require_pcm_budget(one, one)
    pcm_budget.require_pcm_budget(slow, one)
    pcm_budget.require_pcm_budget(slow, slow)
    pcm_budget.require_pcm_budget(limit - one, one)
    with pytest.raises(ValueError, match="512 MiB"):
        pcm_budget.require_pcm_budget(limit - one + 1, one)
    with pytest.raises(ValueError, match="512 MiB"):
        render(SimpleNamespace(duration_s=10000), {"rate": 0.5}, 48000)
