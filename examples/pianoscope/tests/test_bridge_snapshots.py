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
