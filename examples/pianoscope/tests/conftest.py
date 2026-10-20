"""Shared real-controller fixtures for transaction tests."""

import pytest

from pianoscope.audio import Audio
from pianoscope.v2_session import Controller


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("PIANOSCOPE_TMP_DIR", str(tmp_path / "work"))
    c = Controller(audio=Audio())
    yield c
    c.close()
