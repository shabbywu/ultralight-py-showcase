"""Bounded real PCM analysis; calibrated one-sided Hann amplitude spectrum."""

import numpy as np


def overview(pcm, points):
    points = max(1, min(2048, int(points)))
    boundaries = np.linspace(0, len(pcm), points + 1, dtype=int)
    lo = []
    hi = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        part = pcm[a : max(a + 1, b)]
        lo.append(float(part.min()) if len(part) else 0.0)
        hi.append(float(part.max()) if len(part) else 0.0)
    return {"min": lo, "max": hi}


def fft_amplitude(samples, sample_rate):
    x = np.asarray(samples, dtype=np.float64)
    window = np.hanning(len(x))
    amp = 2 * np.abs(np.fft.rfft(x * window)) / max(window.sum(), 1)
    amp[0] *= 0.5
    if len(x) % 2 == 0:
        amp[-1] *= 0.5
    return np.fft.rfftfreq(len(x), 1 / sample_rate), amp


def analyze(samples, sample_rate):
    x = np.zeros(4096, dtype=np.float32)
    source = np.asarray(samples)
    if source.ndim == 2:
        source = source.mean(axis=1)
    count = min(len(source), 4096)
    if count:
        x[-count:] = source[-count:]
    freq, amp = fft_amplitude(x, sample_rate)
    edges = np.geomspace(20, min(20000, sample_rate / 2), 129)
    bands = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        band = amp[(freq >= lo) & (freq < hi)]
        value = float(band.max()) if len(band) else 0
        bands.append(
            round(
                float(np.clip(20 * np.log10(max(value, 10 ** (-90 / 20))), -90, 0)), 2
            )
        )
    return dict(
        waveform=np.round(x.reshape(256, 16).mean(axis=1), 6).tolist(),
        spectrum_db=bands,
        frequency_min_hz=20,
        frequency_max_hz=min(20000, sample_rate / 2),
    )
