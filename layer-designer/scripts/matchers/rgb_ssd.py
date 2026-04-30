"""RGB alpha-weighted SSD matcher (legacy, fast via FFT)."""

import numpy as np

from .base import BaseMatcher, MatchResult


class RgbSsdMatcher(BaseMatcher):
    """Alpha-weighted Sum-of-Squared-Differences on RGB channels.

    Lower SSD = better match.  Score map is returned as negative SSD
    so that higher values always mean better matches across all matchers.
    """

    def __init__(self):
        super().__init__("rgb_ssd")

    def extract(self, template_rgb: np.ndarray, template_alpha: np.ndarray) -> tuple:
        """Return (tpl_rgb, tpl_alpha) as the descriptor."""
        return template_rgb, template_alpha

    def match(
        self,
        roi_rgb: np.ndarray,
        descriptor: tuple,
        scale: float,
    ) -> MatchResult:
        tpl_rgb, tpl_alpha = descriptor
        ssd_map = _ssd_via_fft(roi_rgb, tpl_rgb, tpl_alpha)
        # Normalize by valid pixel count so scores are comparable across scales
        valid_pixels = max(1, float(tpl_alpha.sum()))
        # Convert SSD to score: lower SSD → higher score
        score_map = -ssd_map / valid_pixels
        best_idx = np.unravel_index(np.argmax(score_map), score_map.shape)
        return MatchResult(
            score_map=score_map,
            scale=scale,
            best_score=float(score_map[best_idx]),
            best_y=int(best_idx[0]),
            best_x=int(best_idx[1]),
        )


def _ssd_via_fft(roi_rgb: np.ndarray, tpl_rgb: np.ndarray, tpl_alpha: np.ndarray) -> np.ndarray:
    """Alpha-weighted SSD map via FFT convolution.

    Computes SSD(y,x) = sum_c sum_{i,j} alpha[i,j]^2 * (I[y+i,x+j,c] - T[i,j,c])^2
    efficiently using FFT for the cross-correlation terms.

    Returns SSD map of shape (H-h+1, W-w+1).
    """
    H, W = roi_rgb.shape[:2]
    h, w = tpl_rgb.shape[:2]

    alpha_sq = tpl_alpha ** 2  # (h, w)

    # Term 3: template energy (constant)
    tpl_energy = float(np.sum(alpha_sq[:, :, np.newaxis] * (tpl_rgb ** 2)))

    # Pad size for linear convolution via FFT
    pad_h = H + h - 1
    pad_w = W + w - 1

    # Precompute FFT of flipped alpha^2 (reused for term1)
    alpha_sq_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    alpha_sq_padded[:h, :w] = alpha_sq[::-1, ::-1]
    f_alpha_sq = np.fft.fftn(alpha_sq_padded)

    # Term 1: sum_c conv2d(I_c^2, alpha^2)
    term1 = np.zeros((pad_h, pad_w), dtype=np.float64)
    roi_sq_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    for c in range(3):
        roi_sq_padded[:H, :W] = roi_rgb[:, :, c] ** 2
        f_roi_sq = np.fft.fftn(roi_sq_padded)
        term1 += np.fft.ifftn(f_roi_sq * f_alpha_sq).real
        roi_sq_padded[:H, :W] = 0.0

    # Term 2: 2 * sum_c conv2d(I_c, alpha^2 * T_c)
    cross = np.zeros((pad_h, pad_w), dtype=np.float64)
    tpl_w_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    for c in range(3):
        roi_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
        roi_padded[:H, :W] = roi_rgb[:, :, c]

        tpl_w = alpha_sq * tpl_rgb[:, :, c]  # (h, w)
        tpl_w_padded[:h, :w] = tpl_w[::-1, ::-1]

        f_roi = np.fft.fftn(roi_padded)
        f_tpl = np.fft.fftn(tpl_w_padded)
        cross += np.fft.ifftn(f_roi * f_tpl).real

        tpl_w_padded[:h, :w] = 0.0

    # Extract valid region: indices [h-1:H, w-1:W] correspond to positions (0,0) to (H-h, W-w)
    term1 = term1[h - 1 : H, w - 1 : W]
    cross = cross[h - 1 : H, w - 1 : W]

    ssd_map = term1 - 2.0 * cross + tpl_energy
    # Numerical noise may produce tiny negatives; clamp to 0
    np.maximum(ssd_map, 0.0, out=ssd_map)
    return ssd_map
