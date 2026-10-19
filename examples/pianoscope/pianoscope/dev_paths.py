"""Local development inputs/output; never used for playback or score timing."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
LOCAL_ROOT = Path(os.environ.get('PIANOSCOPE_TMP_DIR', WORKSPACE_ROOT / '.tmp/pianoscope')).expanduser().resolve()
MIDI_ROOT = Path(os.environ.get('PIANOSCOPE_MIDI_DIR', LOCAL_ROOT / 'midi')).expanduser().resolve()


def artifact_dir(section):
    """Create one directory under the ignored local validation area."""
    path = LOCAL_ROOT / 'validation' / section
    path.mkdir(parents=True, exist_ok=True)
    return path
