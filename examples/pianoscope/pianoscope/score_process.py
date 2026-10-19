"""Bounded, cancellable native score worker. No View calls off the app thread."""
from pathlib import Path
import json
import subprocess
import sys
import time
import psutil


def run_preparation(directory, cancelled=lambda: False, progress=lambda phase: None):
    directory = Path(directory)
    started = time.monotonic()
    peak = 0
    progress('layout_and_compiling')
    with (directory / 'worker.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'pianoscope.v2_worker', str(directory)],
                                   stdout=log, stderr=log)
        try:
            watched = psutil.Process(process.pid)
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError('已取消')
                try:
                    peak = max(peak, watched.memory_info().rss)
                except psutil.NoSuchProcess:
                    pass
                if peak > 512 * 1024**2:
                    raise ValueError('乐谱作业超过 512 MiB 内存限制')
                if time.monotonic() - started > 60:
                    raise TimeoutError('乐谱作业超过 60 秒限制')
                time.sleep(.025)
            if cancelled():
                raise InterruptedError('已取消')
            result = json.loads((directory / 'result.json').read_text())
            if process.returncode or result['status'] == 'failed':
                from .score_source import ScoreInputError
                error = ScoreInputError(result.get('error', '原生乐谱准备失败'), result.get('code', 'SCORE_PREPARE_FAILED'))
                error.issues = result.get('issues', error.issues)
                raise error
            size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
            if size > 128 * 1024**2:
                raise ValueError('乐谱作业产物超过 128 MiB')
            result['worker_metrics'] = dict(peak_rss_bytes=peak, elapsed_seconds=time.monotonic()-started,
                                           artifact_bytes=size, exit_code=process.returncode)
            return result
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
