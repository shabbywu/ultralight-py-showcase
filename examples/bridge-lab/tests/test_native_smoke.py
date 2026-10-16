"""Opt in: BRIDGE_LAB_NATIVE=1 python -m pytest -q (requires native desktop)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.skipif(os.environ.get('BRIDGE_LAB_NATIVE') != '1', reason='Set BRIDGE_LAB_NATIVE=1 on a supported native desktop; not a headless test')
def test_native_smoke(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path/'report.json'
    proc = subprocess.run([sys.executable,str(root/'run.py'),'--smoke','--smoke-report',str(report)],cwd=tmp_path,capture_output=True,text=True,timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(report.read_text())
    assert result['success'] is True
    assert {r['scenario'] for r in result['results']} == {'sync','async','object','container','error','snapshot'}
