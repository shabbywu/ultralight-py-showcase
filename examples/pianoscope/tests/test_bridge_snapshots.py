"""SDK container inputs must be detached before coroutine and worker execution."""

from collections import UserDict, UserList

import pytest

from pianoscope.app.data import snapshot_record


def test_snapshot_copies_nested_mapping_and_sequence_views():
    staff_ids = UserList(["upper"])
    settings = UserDict(dict(staff_ids=staff_ids, nested=UserDict(dict(flags=[True]))))
    copied = snapshot_record(settings)
    staff_ids.append("lower")
    settings["nested"]["flags"][0] = False
    assert copied == dict(staff_ids=["upper"], nested=dict(flags=[True]))
    assert type(copied) is dict
    assert type(copied["staff_ids"]) is list


def test_snapshot_rejects_cycles_and_non_data_values():
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="嵌套"):
        snapshot_record(cyclic)
    with pytest.raises(ValueError, match="基础数据"):
        snapshot_record(dict(callback=lambda: None))


def test_bridge_captures_configuration_before_coroutine_starts():
    import asyncio

    from pianoscope.app.bridge import register

    class API:
        def __init__(self):
            self.commands = {}

        def register(self, command):
            self.commands[command.__name__] = command

    class Controller:
        def __getattr__(self, name):
            def command():
                return None

            command.__name__ = name
            return command

        async def configure(self, changes):
            await asyncio.sleep(0)
            self.received = changes
            return changes

    c = Controller()
    api = API()
    register(api, c)
    selection = UserList(["upper"])
    request = UserDict(dict(staff_ids=selection))
    pending = api.commands["configure"](request)
    selection.append("lower")
    asyncio.run(pending)
    assert c.received == dict(staff_ids=["upper"])


def test_score_load_does_not_leave_shared_settings_in_worker(controller, monkeypatch):
    import threading

    import pianoscope.app.controller as session

    entered, release = threading.Event(), threading.Event()
    received = {}

    def parse(source, settings, check):
        entered.set()
        assert release.wait(5)
        received.update(settings)
        raise ValueError("test worker stopped before rendering")

    monkeypatch.setattr(session, "parse_score", parse)
    settings = UserDict(dict(nested=UserDict(dict(flags=UserList([True])))))
    job = controller.begin_score_load("demo:first-light", settings)
    future = controller.jobs[job["job_id"]]["future"]
    try:
        assert entered.wait(5)
        settings["nested"]["flags"][0] = False
    finally:
        release.set()
    with pytest.raises(ValueError, match="test worker stopped"):
        future.result(timeout=5)
    assert received == dict(nested=dict(flags=[True]))
    assert type(received["nested"]) is dict
    assert type(received["nested"]["flags"]) is list


def test_ui_snapshot_reuses_analysis_until_audio_changes(controller):
    first = controller.get_ui_snapshot(True)
    second = controller.get_ui_snapshot(True)
    assert first["transport"]["seq"] < second["transport"]["seq"]
    assert first["analysis"]["seq"] == second["analysis"]["seq"]

    controller.audio.serial += 1
    third = controller.get_ui_snapshot(True)
    assert third["analysis"]["seq"] > second["analysis"]["seq"]


def test_semantic_parse_cache_is_bounded_and_reuses_same_settings(
    controller, monkeypatch
):
    import pianoscope.app.controller as session
    from pianoscope.score.source import source_from_bytes

    source = source_from_bytes(
        b'<score-partwise version="4.0"><part-list><score-part id="P"/>'
        b'</part-list><part id="P"><measure number="1"><attributes>'
        b"<divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type>"
        b"</time><staves>2</staves><clef><sign>G</sign></clef><clef number='2'>"
        b"<sign>F</sign></clef></attributes><sound tempo='120'/><note id='n'>"
        b"<pitch><step>C</step><octave>4</octave></pitch><duration>4</duration>"
        b"<voice>1</voice><type>whole</type><staff>1</staff></note></measure>"
        b"</part></score-partwise>"
    )
    calls = 0
    real_parse = session.parse_score

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(session, "parse_score", counted)
    controller._cached_parse(source, {}, lambda: False)
    controller._cached_parse(source, {}, lambda: False)
    assert calls == 1
