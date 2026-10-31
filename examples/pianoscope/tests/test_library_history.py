"""Persistent library and history behavior without a physical MIDI device."""

import asyncio
import sqlite3
from pathlib import Path

import pytest

from pianoscope.app.controller import Controller
from pianoscope.playback.audio import Audio
from pianoscope.practice.storage import PracticeStore

FIXTURES = Path(__file__).parent / "fixtures/musicxml"


def test_folder_index_survives_restart_and_metadata_does_not_prepare_audio(controller):
    c = controller
    asyncio.run(c.open_score_folder(FIXTURES))
    songs = c.get_score_library()["songs"]
    song = next(s for s in songs if s["name"] == "temporal.musicxml")
    detail = asyncio.run(c.get_library_detail(song["file_token"]))
    assert detail["notes_count"] > 0
    assert c.audio.pcm is None
    assert c.active is None
    assert not c.jobs
    another = Controller(audio=Audio())
    try:
        restored = next(
            s for s in another.get_score_library()["songs"] if s["id"] == song["id"]
        )
        assert restored["source_fingerprint"] == detail["source_sha256"]
        assert restored["file_token"] != song["file_token"]
        assert another.get_score_library()["sources"]
    finally:
        another.close()


def test_remove_and_relocate_keep_stable_identity_and_source(tmp_path):
    store = PracticeStore(tmp_path / "index.sqlite3")
    old, new = tmp_path / "old.xml", tmp_path / "new.xml"
    store.remember(str(old), old.name, "fingerprint")
    identity = store.library()[0]["id"]
    store.relocate(str(old), str(new))
    row = store.library()[0]
    assert row["id"] == identity
    assert row["fingerprint"] == "fingerprint"
    store.forget(str(new))
    assert store.library() == []


def test_existing_schema_is_upgraded_without_losing_results(tmp_path):
    database = tmp_path / "old.sqlite3"
    store = PracticeStore(database)
    with store._connect() as db:
        db.execute("PRAGMA user_version=1")
        db.execute(
            "INSERT INTO library(path,name,fingerprint,id) VALUES('score.xml','曲目','sha','fixed')"
        )
    upgraded = PracticeStore(database)
    assert upgraded.library()[0]["id"] == "fixed"
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4


def test_unknown_folder_authority_cannot_be_refreshed(controller):
    with pytest.raises(ValueError, match="来源"):
        asyncio.run(controller.refresh_library_source("arbitrary-path"))


def test_active_practice_locks_configuration_and_navigation(controller):
    controller.practice.state = "paused"
    with pytest.raises(ValueError, match="结束练习"):
        asyncio.run(controller.seek(0))
    with pytest.raises(ValueError, match="结束练习"):
        asyncio.run(controller.set_loop(True, 0, 4))
    with pytest.raises(ValueError, match="结束当前练习"):
        controller.set_mode("audition")
    controller.practice.state = "idle"


def test_reopen_restores_saved_hands_without_blocking_publication(controller):
    async def reopen():
        c = controller
        token = "demo:first-light"
        detail = await c.get_library_detail(token)
        job = c.begin_score_load(token)
        deadline = asyncio.get_running_loop().time() + 20
        while c.get_job(job["job_id"])["phase"] != "candidate_ready":
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        note = c.get_notes(0, 1, job["job_id"])["notes"][0]
        hands = {note["element_ids"][0]: "right"}
        c.cancel_job(job["job_id"])
        c.practice.store.preference("hands:" + detail["source_sha256"], hands)

        job = c.begin_score_load(token)
        while c.get_job(job["job_id"])["phase"] != "candidate_ready":
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        candidate = c.get_candidate(job["job_id"])
        prepared = c.get_notes(0, 1, job["job_id"])["notes"][0]
        assert prepared["hand"] == "right"
        document = await asyncio.wait_for(
            c.publish_score_load(job["job_id"], candidate["source_sha256"]), 2
        )
        assert document["hand_status"] == "confirmed"
        assert document["playback_revision"] == candidate["playback_revision"]
        assert c.hands == hands
        assert not c.command_lock.locked()

    asyncio.run(reopen())
