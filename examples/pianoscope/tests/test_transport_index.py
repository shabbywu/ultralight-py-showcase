from pianoscope.playback.model import Note, Score
from pianoscope.playback.player import _TransportIndex


def test_transport_index_tracks_attacks_sustain_and_backward_seek():
    score = Score(
        "index",
        4,
        [{"id": "P:1", "source_channel": 0}],
        [
            Note("a", "P:1", 60, 80, 0, 1, 1.5),
            Note("b", "P:1", 62, 80, 1, 2, 2),
            Note("c", "P:1", 64, 80, 3, 4, 4),
        ],
        [],
        [],
    )
    config = {
        "rate": 1.0,
        "hand_mode": "both",
        "tracks": [{"id": "P:1", "muted": False, "solo": False}],
    }
    index = _TransportIndex(score, config)

    assert index.at(0.5, True) == (["a"], [])
    assert index.at(1.25, True) == (["b"], ["a"])
    assert index.at(2.5, True) == ([], [])
    assert index.at(3.5, True) == (["c"], [])
    assert index.at(0.25, True) == (["a"], [])
    assert index.at(0.25, False) == ([], [])
