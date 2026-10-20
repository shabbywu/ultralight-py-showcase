"""当前与候选 PCM 共用的字节预算，在声音分配前校验。"""

from __future__ import annotations

PCM_BUDGET_BYTES = 512 * 1024**2


def require_pcm_budget(candidate_bytes: int, current_bytes: int = 0) -> None:
    """校验候选与当前 PCM 的字节数合计，超过共享预算时抛出 ValueError。

    调用方应在分配候选缓冲前调用；这里只计 PCM，不代表进程总内存上限。
    """
    total = candidate_bytes + current_bytes
    if total > PCM_BUDGET_BYTES:
        scope = "当前与候选声音缓冲合计" if current_bytes else "声音缓冲"
        raise ValueError(
            f"{scope}约 {total / 1024**2:.1f} MiB，超过 {PCM_BUDGET_BYTES / 1024**2:g} MiB 限制"
        )
