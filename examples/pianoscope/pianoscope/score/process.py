"""有界运行隔离乐谱工作器，负责取消、超时、内存限制和结果回收。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

from pianoscope.types import Cancelled, PathInput, PhaseProgress, Record


def run_preparation(
    directory: PathInput,
    cancelled: Cancelled = lambda: False,
    progress: PhaseProgress = lambda phase: None,
) -> Record:
    """启动 pianoscope.score.worker 并读取准备结果，返回附原生资源指标的清单。

    directory 必须已有 request.json；限制子进程 512 MiB／60 秒及产物 128 MiB。
    取消、超时或内存超限时终止并回收子进程；工作器错误保留源定位与错误码。
    """
    directory = Path(directory)
    started = time.monotonic()
    peak = 0
    progress("layout_and_compiling")
    with (directory / "worker.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "pianoscope.score.worker", str(directory)],
            stdout=log,
            stderr=log,
        )
        try:
            watched = psutil.Process(process.pid)
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError("已取消")
                try:
                    peak = max(peak, watched.memory_info().rss)
                except psutil.NoSuchProcess:
                    pass
                if peak > 512 * 1024**2:
                    raise ValueError("乐谱作业超过 512 MiB 内存限制")
                if time.monotonic() - started > 60:
                    raise TimeoutError("乐谱作业超过 60 秒限制")
                time.sleep(0.025)
            if cancelled():
                raise InterruptedError("已取消")
            result = json.loads((directory / "result.json").read_text())
            if process.returncode or result["status"] == "failed":
                from pianoscope.score.source import ScoreInputError

                error = ScoreInputError(
                    result.get("error", "原生乐谱准备失败"),
                    result.get("code", "SCORE_PREPARE_FAILED"),
                )
                error.issues = result.get("issues", error.issues)
                raise error
            size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
            if size > 128 * 1024**2:
                raise ValueError("乐谱作业产物超过 128 MiB")
            result["worker_metrics"] = dict(
                peak_rss_bytes=peak,
                elapsed_seconds=time.monotonic() - started,
                artifact_bytes=size,
                exit_code=process.returncode,
            )
            return result
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
