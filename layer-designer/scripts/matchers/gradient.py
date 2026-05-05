"""Sobel gradient magnitude matcher with zero-mean NCC via FFT."""

import numpy as np
from scipy import ndimage

from .base import BaseMatcher, MatchResult


class GradientMatcher(BaseMatcher):
    """Sobel gradient magnitude + zero-mean normalized cross-correlation (ZNCC).

    Color-invariant: relies on edge strength, not absolute pixel colors.

    SNR note: when callers pre-downsample RGB via box-averaging before passing
    to this matcher, the high-frequency content Sobel relies on is destroyed.
    To preserve edge SNR, pass `full_res_rgb` (and matching `full_res_alpha`
    for extract) plus `downsample_factor`. The matcher then computes Sobel on
    the full-resolution input and box-downsamples the gradient *magnitude*
    instead of downsampling the RGB and computing Sobel on a blurred surface.
    """

    # Marker for FusionMatcher routing: this matcher accepts the full_res kwargs.
    supports_full_res = True

    def __init__(self):
        super().__init__("gradient")

    def extract(
        self,
        template_rgb: np.ndarray,
        template_alpha: np.ndarray,
        *,
        full_res_rgb: np.ndarray | None = None,
        full_res_alpha: np.ndarray | None = None,
        downsample_factor: int = 1,
    ) -> np.ndarray:
        """Compute Sobel gradient magnitude descriptor.

        Default (no full_res): Sobel on `template_rgb` directly.
        High-SNR (full_res given): Sobel on full-res, box-downsample magnitude
        to match `template_rgb`'s spatial dims.
        """
        if full_res_rgb is not None and downsample_factor > 1:
            grad_full = _sobel_magnitude(full_res_rgb)
            if full_res_alpha is not None:
                grad_full[full_res_alpha < 0.02] = 0.0
            grad = _box_downsample_2d(grad_full, downsample_factor)
            # Crop to descriptor shape so it matches the (already-downsampled)
            # template_rgb geometry the caller expects.
            th, tw = template_rgb.shape[:2]
            grad = grad[:th, :tw]
            return grad

        grad = _sobel_magnitude(template_rgb)
        grad[template_alpha < 0.02] = 0.0
        return grad

    def match(
        self,
        roi_rgb: np.ndarray,
        descriptor: np.ndarray,
        scale: float,
        *,
        full_res_rgb: np.ndarray | None = None,
        downsample_factor: int = 1,
    ) -> MatchResult:
        if full_res_rgb is not None and downsample_factor > 1:
            roi_grad_full = _sobel_magnitude(full_res_rgb)
            roi_grad = _box_downsample_2d(roi_grad_full, downsample_factor)
            # Match descriptor coord system: crop to roi_rgb's downsampled dims.
            Rh, Rw = roi_rgb.shape[:2]
            roi_grad = roi_grad[:Rh, :Rw]
        else:
            roi_grad = _sobel_magnitude(roi_rgb)

        tpl_grad = descriptor
        ncc_map = _zncc_via_fft(roi_grad, tpl_grad)
        # ncc_map is in [-1, 1]; higher = better
        best_idx = np.unravel_index(np.argmax(ncc_map), ncc_map.shape)
        return MatchResult(
            score_map=ncc_map,
            scale=scale,
            best_score=float(ncc_map[best_idx]),
            best_y=int(best_idx[0]),
            best_x=int(best_idx[1]),
        )


def _sobel_magnitude(rgb: np.ndarray) -> np.ndarray:
    """Per-channel Sobel gradient magnitude, then max across channels."""
    mag = np.zeros(rgb.shape[:2], dtype=np.float32)
    for c in range(3):
        gx = ndimage.sobel(rgb[:, :, c], axis=1)
        gy = ndimage.sobel(rgb[:, :, c], axis=0)
        mag = np.maximum(mag, np.hypot(gx, gy))
    return mag


def _box_downsample_2d(arr: np.ndarray, factor: int) -> np.ndarray:
    """Box-mean downsample a 2-D array by integer factor.

    Mirrors detect_layer_positions._downsample but for a single channel.
    """
    if factor <= 1:
        return arr
    h, w = arr.shape[:2]
    h = (h // factor) * factor
    w = (w // factor) * factor
    arr = arr[:h, :w]
    return arr.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))


def _zncc_via_fft(roi: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Zero-mean normalized cross-correlation via FFT.

    Returns NCC map of shape (H-h+1, W-w+1) with values in [-1, 1].
    """
    H, W = roi.shape
    h, w = tpl.shape
    N = h * w

    # Zero-mean template
    tpl_zm = tpl - tpl.mean()
    tpl_energy = float(np.sum(tpl_zm ** 2))
    if tpl_energy < 1e-12:
        # Uniform template → undefined NCC; return zeros
        return np.zeros((H - h + 1, W - w + 1), dtype=np.float64)

    pad_h = H + h - 1
    pad_w = W + w - 1

    # --- Cross-correlation: conv(roi, tpl_zm) ---
    roi_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    roi_padded[:H, :W] = roi
    tpl_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    tpl_padded[:h, :w] = tpl_zm[::-1, ::-1]

    f_roi = np.fft.fftn(roi_padded)
    f_tpl = np.fft.fftn(tpl_padded)
    cross = np.fft.ifftn(f_roi * f_tpl).real[h - 1 : H, w - 1 : W]

    # --- Local box filter (all-ones kernel) via FFT ---
    ones_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    ones_padded[:h, :w] = 1.0
    f_ones = np.fft.fftn(ones_padded)

    # Local sum of ROI
    roi_sum = np.fft.ifftn(f_roi * f_ones).real[h - 1 : H, w - 1 : W]
    roi_mean = roi_sum / N

    # Local sum of ROI^2
    roi_sq_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    roi_sq_padded[:H, :W] = roi ** 2
    f_roi_sq = np.fft.fftn(roi_sq_padded)
    roi_sq_sum = np.fft.ifftn(f_roi_sq * f_ones).real[h - 1 : H, w - 1 : W]

    # Local variance = E[x^2] - E[x]^2
    roi_var = np.maximum(roi_sq_sum / N - roi_mean ** 2, 0.0)

    # ZNCC = cross / sqrt(N * roi_var * tpl_energy)
    denom = np.sqrt(roi_var * N * tpl_energy)
    ncc = np.zeros_like(cross)
    mask = denom > 1e-9
    ncc[mask] = cross[mask] / denom[mask]

    # Clamp to [-1, 1] for numerical safety
    np.clip(ncc, -1.0, 1.0, out=ncc)
    return ncc
