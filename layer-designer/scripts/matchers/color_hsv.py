"""HSV color space matcher.

Converts RGB to HSV and performs alpha-weighted SSD matching.
Hue is treated linearly for simplicity; most real-world UI elements
avoid the 0/360° boundary in their dominant colors.
"""

import cv2
import numpy as np

from .base import BaseMatcher, MatchResult


class ColorHsvMatcher(BaseMatcher):
    """HSV color-space matching via alpha-weighted SSD.

    Hue (0-360), Saturation (0-255), Value (0-255).
    SSD is computed per-channel; the score is negative per-pixel SSD
    so higher = better (consistent with all matchers).
    """

    def __init__(self):
        super().__init__("color_hsv")

    def extract(self, template_rgb: np.ndarray, template_alpha: np.ndarray) -> tuple:
        """Return (hsv_image, alpha) as the descriptor."""
        hsv = cv2.cvtColor(template_rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        # OpenCV 8-bit HSV: H=0-179, S=0-255, V=0-255
        # Scale hue to 0-360 for intuitive range
        hsv[:, :, 0] *= 2.0
        # Mask out transparent regions
        hsv[template_alpha < 0.02] = 0.0
        return hsv, template_alpha

    def match(
        self,
        roi_rgb: np.ndarray,
        descriptor: tuple,
        scale: float,
    ) -> MatchResult:
        hsv_tpl, tpl_alpha = descriptor

        # Convert ROI to HSV
        hsv_roi = cv2.cvtColor(roi_rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv_roi[:, :, 0] *= 2.0

        # Alpha-weighted SSD in HSV space
        ssd_map = _hsv_ssd_via_fft(hsv_roi, hsv_tpl, tpl_alpha)

        # Normalize by valid pixel count so scores are comparable across scales
        valid_pixels = max(1, float(tpl_alpha.sum()))
        score_map = -ssd_map / valid_pixels

        best_idx = np.unravel_index(np.argmax(score_map), score_map.shape)
        return MatchResult(
            score_map=score_map,
            scale=scale,
            best_score=float(score_map[best_idx]),
            best_y=int(best_idx[0]),
            best_x=int(best_idx[1]),
        )


def _hsv_ssd_via_fft(roi_hsv: np.ndarray, tpl_hsv: np.ndarray, tpl_alpha: np.ndarray) -> np.ndarray:
    """Alpha-weighted SSD map in HSV space via FFT convolution.

    Returns SSD map of shape (H-h+1, W-w+1).
    """
    H, W = roi_hsv.shape[:2]
    h, w = tpl_hsv.shape[:2]

    alpha_sq = tpl_alpha ** 2

    # Term 3: template energy (constant)
    tpl_energy = float(np.sum(alpha_sq[:, :, np.newaxis] * (tpl_hsv ** 2)))

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
        roi_sq_padded[:H, :W] = roi_hsv[:, :, c] ** 2
        f_roi_sq = np.fft.fftn(roi_sq_padded)
        term1 += np.fft.ifftn(f_roi_sq * f_alpha_sq).real
        roi_sq_padded[:H, :W] = 0.0

    # Term 2: 2 * sum_c conv2d(I_c, alpha^2 * T_c)
    cross = np.zeros((pad_h, pad_w), dtype=np.float64)
    tpl_w_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    for c in range(3):
        roi_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
        roi_padded[:H, :W] = roi_hsv[:, :, c]

        tpl_w = alpha_sq * tpl_hsv[:, :, c]
        tpl_w_padded[:h, :w] = tpl_w[::-1, ::-1]

        f_roi = np.fft.fftn(roi_padded)
        f_tpl = np.fft.fftn(tpl_w_padded)
        cross += np.fft.ifftn(f_roi * f_tpl).real

        tpl_w_padded[:h, :w] = 0.0

    # Extract valid region
    term1 = term1[h - 1 : H, w - 1 : W]
    cross = cross[h - 1 : H, w - 1 : W]

    ssd_map = term1 - 2.0 * cross + tpl_energy
    np.maximum(ssd_map, 0.0, out=ssd_map)
    return ssd_map
