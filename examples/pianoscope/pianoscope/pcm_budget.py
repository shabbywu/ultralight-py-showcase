"""Shared resident PCM budget, excluding the synth/renderer process memory."""

PCM_BUDGET_BYTES = 512 * 1024**2


def require_pcm_budget(candidate_bytes, current_bytes=0):
    total = candidate_bytes + current_bytes
    if total > PCM_BUDGET_BYTES:
        scope = '当前与候选声音缓冲合计' if current_bytes else '声音缓冲'
        raise ValueError(f'{scope}约 {total/1024**2:.1f} MiB，超过 {PCM_BUDGET_BYTES/1024**2:g} MiB 限制')
