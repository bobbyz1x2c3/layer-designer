"""Local Binary Pattern (LBP) texture matcher.

Uses uniform LBP (8 neighbors, radius 1) to capture local texture
patterns, then matches via zero-mean normalized cross-correlation (ZNCC).
"""

import cv2
import numpy as np

from .base import BaseMatcher, MatchResult


class PatternLbpMatcher(BaseMatcher):
    """Uniform LBP texture matching via ZNCC.

    LBP is illumination-invariant and captures fine texture structure
    (e.g. fabric, noise patterns, repeated UI elements).
    """

    def __init__(self):
        super().__init__("pattern_lbp")

    def extract(self, template_rgb: np.ndarray, template_alpha: np.ndarray) -> np.ndarray:
        """Compute uniform LBP from grayscale; mask transparent regions."""
        gray = cv2.cvtColor(template_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        lbp = _uniform_lbp(gray)
        lbp[template_alpha < 0.02] = 0.0
        return lbp

    def match(
        self,
        roi_rgb: np.ndarray,
        descriptor: np.ndarray,
        scale: float,
    ) -> MatchResult:
        gray = cv2.cvtColor(roi_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        roi_lbp = _uniform_lbp(gray)
        tpl_lbp = descriptor

        ncc_map = _zncc_via_fft(roi_lbp, tpl_lbp)

        best_idx = np.unravel_index(np.argmax(ncc_map), ncc_map.shape)
        return MatchResult(
            score_map=ncc_map,
            scale=scale,
            best_score=float(ncc_map[best_idx]),
            best_y=int(best_idx[0]),
            best_x=int(best_idx[1]),
        )


# Precompute uniform LBP lookup table (0-255 -> 0-59, non-uniform = 59)
_UNIFORM_MAP = np.full(256, 59, dtype=np.uint8)
_uniform_idx = 0
for _code in range(256):
    _b = [(_code >> i) & 1 for i in range(8)]
    _transitions = sum(abs(_b[i] - _b[(i + 1) % 8]) for i in range(8))
    if _transitions <= 2:
        _UNIFORM_MAP[_code] = _uniform_idx
        _uniform_idx += 1


def _uniform_lbp(gray: np.ndarray) -> np.ndarray:
    """Compute uniform LBP (8 neighbors, radius 1).

    Returns an array of the same shape as input with 0-padding on the
    1-pixel border.
    """
    h, w = gray.shape
    if h < 3 or w < 3:
        return np.zeros((h, w), dtype=np.float32)

    center = gray[1:-1, 1:-1]

    # 8 neighbors in clockwise order starting from top-left
    neighbors = np.stack([
        gray[0:-2, 0:-2],   # top-left
        gray[0:-2, 1:-1],   # top
        gray[0:-2, 2:],     # top-right
        gray[1:-1, 2:],     # right
        gray[2:, 2:],       # bottom-right
        gray[2:, 1:-1],     # bottom
        gray[2:, 0:-2],     # bottom-left
        gray[1:-1, 0:-2],   # left
    ], axis=-1)  # (h-2, w-2, 8)

    bits = (neighbors > center[:, :, np.newaxis]).astype(np.uint8)

    # Compute 8-bit LBP code
    lbp = np.zeros((h - 2, w - 2), dtype=np.uint8)
    for i in range(8):
        lbp += bits[:, :, i] * (1 << i)

    # Map to uniform labels (0-59)
    result = _UNIFORM_MAP[lbp].astype(np.float32)

    # Pad back to original size
    padded = np.zeros((h, w), dtype=np.float32)
    padded[1:-1, 1:-1] = result
    return padded


def _zncc_via_fft(roi: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Zero-mean normalized cross-correlation via FFT.

    Returns NCC map of shape (H-h+1, W-w+1) with values in [-1, 1].
    """
    H, W = roi.shape
    h, w = tpl.shape
    N = h * w

    tpl_zm = tpl - tpl.mean()
    tpl_energy = float(np.sum(tpl_zm ** 2))
    if tpl_energy < 1e-12:
        return np.zeros((H - h + 1, W - w + 1), dtype=np.float64)

    pad_h = H + h - 1
    pad_w = W + w - 1

    # Cross-correlation: conv(roi, tpl_zm)
    roi_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    roi_padded[:H, :W] = roi
    tpl_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    tpl_padded[:h, :w] = tpl_zm[::-1, ::-1]

    f_roi = np.fft.fftn(roi_padded)
    f_tpl = np.fft.fftn(tpl_padded)
    cross = np.fft.ifftn(f_roi * f_tpl).real[h - 1 : H, w - 1 : W]

    # Local box filter (all-ones kernel) via FFT
    ones_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    ones_padded[:h, :w] = 1.0
    f_ones = np.fft.fftn(ones_padded)

    roi_sum = np.fft.ifftn(f_roi * f_ones).real[h - 1 : H, w - 1 : W]
    roi_mean = roi_sum / N

    roi_sq_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    roi_sq_padded[:H, :W] = roi ** 2
    f_roi_sq = np.fft.fftn(roi_sq_padded)
    roi_sq_sum = np.fft.ifftn(f_roi_sq * f_ones).real[h - 1 : H, w - 1 : W]

    roi_var = np.maximum(roi_sq_sum / N - roi_mean ** 2, 0.0)

    denom = np.sqrt(roi_var * N * tpl_energy)
    ncc = np.zeros_like(cross)
    mask = denom > 1e-9
    ncc[mask] = cross[mask] / denom[mask]

    np.clip(ncc, -1.0, 1.0, out=ncc)
    return ncc
