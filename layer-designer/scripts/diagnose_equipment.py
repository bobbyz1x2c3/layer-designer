"""Diagnostic for zzz-character-equipment grid detection.

Loads the preview, extracts the equipment_slot ROI, and reports:
- All autocorrelation peaks along X axis with their correlations
- Comb-phase score for several candidate periods
- Profile energy in each cell at the chosen period

Use this to decide whether the bug is in period selection or walk-back.
"""
from pathlib import Path

import numpy as np
from PIL import Image

from matchers.grid_periodicity import (
    _autocorr_fft,
    _comb_phase,
    _gradient_magnitude,
    _smooth1d,
)


PROJECT_DIR = Path(__file__).resolve().parents[1] / "output" / "zzz-character-equipment"
PREVIEW = PROJECT_DIR / "01-requirements" / "previews" / "preview_v2_002.png"

# ROI (post-padding) for equipment_slot in preview coords
RX, RY = 390, 249
RW, RH = 929, 513


def main() -> None:
    img = np.array(Image.open(PREVIEW).convert("RGB"), dtype=np.float32)
    sub = img[RY:RY + RH, RX:RX + RW]
    gray = sub.mean(axis=2)
    grad = _gradient_magnitude(gray)
    prof_x = grad.sum(axis=0)

    print(f"ROI: x={RX} y={RY} w={RW} h={RH}")
    print(f"prof_x.shape={prof_x.shape} max={prof_x.max():.0f} sum={prof_x.sum():.0f}")

    # Autocorrelation peaks
    centered = prof_x.astype(np.float64) - prof_x.mean()
    smoothed = _smooth1d(centered, k=3)
    ac = _autocorr_fft(smoothed)
    n = len(ac)
    lo, hi = max(2, 85), min(n - 2, RW)  # cell_w_hint=171 → min_period=85

    peaks = []
    for i in range(lo, hi + 1):
        v = float(ac[i])
        if v < 0.10:
            continue
        if v >= ac[i - 1] and v >= ac[i + 1]:
            peaks.append((i, v))
    peaks.sort(key=lambda p: -p[1])
    print(f"\nTop autocorrelation peaks (period, correlation):")
    for p, c in peaks[:15]:
        cnt = max(1, int(round(RW / p)))
        print(f"  period={p:4d}  corr={c:.4f}  count={cnt}")

    # Comb-phase scores for candidate periods
    print(f"\nComb-phase scores per candidate period:")
    for cand in [162, 189, 232]:
        if cand <= 0 or cand >= n:
            continue
        phase, score = _comb_phase(prof_x, cand)
        canvas_origin_x = RX + phase
        cnt = 0
        cx = canvas_origin_x
        cell_w = min(171, cand)
        while cx + cell_w // 2 <= RX + RW:
            cnt += 1
            cx += cand
        print(f"  period={cand:4d}  phase={phase:3d}  comb={score:.4f}  cell_origin={canvas_origin_x}  forward_count={cnt}")

    # Energy density per in-ROI cell at period=162, phase=108
    print(f"\nProfile energy density per cell (period=162, phase=108):")
    period = 162
    phase = 108
    cell_w = 162
    for k in range(-2, 7):
        start = phase + k * period
        end = start + cell_w
        if end <= 0 or start >= len(prof_x):
            continue
        s = max(0, start)
        e = min(len(prof_x), end)
        if e <= s:
            continue
        seg = prof_x[s:e]
        density = seg.sum() / max(1, len(seg))
        canvas_x = RX + start
        marker = "  <-- walked-back" if k < 0 else ""
        print(f"  cell {k:+d}: canvas_x={canvas_x}  prof[{s}:{e}]  len={e-s}  density={density:.1f}{marker}")


if __name__ == "__main__":
    main()
