"""Shared real-controller fixtures for transaction tests."""

import pytest

from pianoscope.app.controller import Controller
from pianoscope.playback.audio import Audio


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("PIANOSCOPE_TMP_DIR", str(tmp_path / "work"))
    c = Controller(audio=Audio())
    yield c
    c.close()
