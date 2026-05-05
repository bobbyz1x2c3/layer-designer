"""Canny edge + distance transform matcher."""

import cv2
import numpy as np

from .base import BaseMatcher, MatchResult


class EdgeCannyMatcher(BaseMatcher):
    """Canny edge detector + Chamfer-style matching via distance transform.

    Steps:
    1. Canny edge detection on template and ROI
    2. Distance transform on ROI edge map (every pixel = distance to nearest edge)
    3. Match = average distance of template edge pixels over the ROI distance map

    Color-invariant.  Very robust for structural shapes (buttons, cards, panels).

    SNR note: when callers pre-downsample RGB via box-averaging before passing
    to this matcher, fine edges (1-2 px wide) are blurred away and Canny finds
    nothing. To preserve edge SNR, pass `full_res_rgb` (and matching
    `full_res_alpha` for extract) plus `downsample_factor`. The matcher then
    runs Canny on the full-resolution input and box-downsamples the binary
    edge map; downstream distance transform / chamfer math sees the dense
    edge structure rather than a blurred shadow.
    """

    # Marker for FusionMatcher routing: this matcher accepts the full_res kwargs.
    supports_full_res = True

    def __init__(self, threshold1: int = 50, threshold2: int = 150):
        super().__init__("edge_canny")
        self.threshold1 = threshold1
        self.threshold2 = threshold2

    def extract(
        self,
        template_rgb: np.ndarray,
        template_alpha: np.ndarray,
        *,
        full_res_rgb: np.ndarray | None = None,
        full_res_alpha: np.ndarray | None = None,
        downsample_factor: int = 1,
    ) -> np.ndarray:
        """Return binary edge map descriptor."""
        if full_res_rgb is not None and downsample_factor > 1:
            gray_full = cv2.cvtColor(full_res_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
            edges_full = cv2.Canny(gray_full, self.threshold1, self.threshold2)
            if full_res_alpha is not None:
                edges_full[full_res_alpha < 0.02] = 0
            edges = _box_downsample_2d(edges_full.astype(np.float64), downsample_factor)
            th, tw = template_rgb.shape[:2]
            return edges[:th, :tw]

        gray = cv2.cvtColor(template_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, self.threshold1, self.threshold2)
        edges[template_alpha < 0.02] = 0
        return edges.astype(np.float64)

    def match(
        self,
        roi_rgb: np.ndarray,
        descriptor: np.ndarray,
        scale: float,
        *,
        full_res_rgb: np.ndarray | None = None,
        downsample_factor: int = 1,
    ) -> MatchResult:
        tpl_edges = descriptor  # (h, w) float64, binary-ish

        if full_res_rgb is not None and downsample_factor > 1:
            gray_full = cv2.cvtColor(full_res_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
            roi_edges_full = cv2.Canny(gray_full, self.threshold1, self.threshold2)
            roi_edges_ds = _box_downsample_2d(
                roi_edges_full.astype(np.float64), downsample_factor
            )
            Rh, Rw = roi_rgb.shape[:2]
            roi_edges_ds = roi_edges_ds[:Rh, :Rw]
            # Threshold the box-averaged edge mass back to a binary edge map
            # for distance transform.  Use any nonzero downsampled cell as edge.
            roi_edges_bin = (roi_edges_ds > 0).astype(np.uint8) * 255
            dist = cv2.distanceTransform(
                (255 - roi_edges_bin).astype(np.uint8),
                cv2.DIST_L2,
                5,
            ).astype(np.float64)
        else:
            gray = cv2.cvtColor(roi_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
            roi_edges = cv2.Canny(gray, self.threshold1, self.threshold2)
            dist = cv2.distanceTransform(
                (255 - roi_edges).astype(np.uint8),
                cv2.DIST_L2,
                5,
            ).astype(np.float64)

        # Chamfer matching via FFT:
        # score[y,x] = sum(dist[y:y+h, x:x+w] * tpl_edges) / sum(tpl_edges)
        score_map = _chamfer_fft(dist, tpl_edges)

        # Lower average distance = better match
        # Invert so higher = better (consistent with other matchers)
        score_map = -score_map

        best_idx = np.unravel_index(np.argmax(score_map), score_map.shape)
        return MatchResult(
            score_map=score_map,
            scale=scale,
            best_score=float(score_map[best_idx]),
            best_y=int(best_idx[0]),
            best_x=int(best_idx[1]),
        )


def _box_downsample_2d(arr: np.ndarray, factor: int) -> np.ndarray:
    """Box-mean downsample a 2-D array by integer factor."""
    if factor <= 1:
        return arr
    h, w = arr.shape[:2]
    h = (h // factor) * factor
    w = (w // factor) * factor
    arr = arr[:h, :w]
    return arr.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))


def _chamfer_fft(dist: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Compute average distance of template edge pixels at every position via FFT.

    Returns score map of shape (H-h+1, W-w+1) where lower = better.
    """
    H, W = dist.shape
    h, w = tpl.shape

    pad_h = H + h - 1
    pad_w = W + w - 1

    # conv(dist, tpl)
    dist_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    dist_padded[:H, :W] = dist
    tpl_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    tpl_padded[:h, :w] = tpl[::-1, ::-1]

    f_dist = np.fft.fftn(dist_padded)
    f_tpl = np.fft.fftn(tpl_padded)
    cross = np.fft.ifftn(f_dist * f_tpl).real[h - 1 : H, w - 1 : W]

    # conv(ones, tpl) = edge pixel count at each position
    ones_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    ones_padded[:h, :w] = 1.0
    f_ones = np.fft.fftn(ones_padded)
    count = np.fft.ifftn(f_dist * f_ones).real[h - 1 : H, w - 1 : W]
    # conv(ones_roi, tpl) = sum of template edge pixels at each position
    ones_roi_padded = np.zeros((pad_h, pad_w), dtype=np.float64)
    ones_roi_padded[:H, :W] = 1.0
    f_ones_roi = np.fft.fftn(ones_roi_padded)
    count = np.fft.ifftn(f_ones_roi * f_tpl).real[h - 1 : H, w - 1 : W]

    # Avoid division by zero
    count = np.maximum(count, 1e-9)
    return cross / count
