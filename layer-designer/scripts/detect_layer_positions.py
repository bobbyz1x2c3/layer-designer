#!/usr/bin/env python3
"""Detect precise layer positions in a preview image via multi-scale template matching.

Uses each layer's actual PNG (post-rembg/crop) as a template, searches for it inside
the confirmed preview image, and produces detected_layouts.json with precise (x,y,w,h).

layer_plan.json layout serves as the reference origin + scale:
- planned (x,y) is the search ROI center
- planned (w,h) is the template resize target and scale reference

Fallback: if match confidence is low (SSD too high / NCC too low), uses planned layout.

Usage:
    python detect_layer_positions.py \
        --project tst --config config.json \
        --preview output/tst/01-requirements/previews/preview_v2_001.png \
        --phase rough
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from path_manager import PathManager

from matchers import FusionMatcher, _resolve_profile
from matchers.grid_periodicity import detect_grid_periodicity
from visualize_detect import draw_layout_viz


# Relative scale factors around the "contain-fit" base scale.
# Base scale is computed per-layer as min(plan_w / tpl_w, plan_h / tpl_h)
# so that scale=1.0 means the template fits exactly inside the planned rect
# while preserving its original aspect ratio (object-fit: contain).
DEFAULT_RELATIVE_SCALES = [0.70, 0.85, 0.95, 1.00, 1.05, 1.15, 1.30]

# ROI expands planned size by this factor on each side (3.5 = ±250% margin)
ROI_FACTOR = 3.5

# Downsample factor for fast coarse matching
DOWNSAMPLE = 4

# Fine-search radius in original pixels around coarse match
FINE_RADIUS = 12

# SSD threshold: if best SSD is above this * template_pixels, treat as low confidence
SSD_CONFIDENCE_THRESHOLD = 20000.0  # per-pixel squared error tolerance (AI gen variance)

# Pyramid pre-screening: ultra-coarse downsample to quickly eliminate bad scales
COARSE_DOWNSAMPLE = 8
# Max candidate scales to pass from coarse to fine matching
COARSE_TOP_K = 3


def _get_detection_config(config_path: str | None) -> dict:
    """Load detection settings from config.json with fallback defaults."""
    defaults = {
        "warn_offset_threshold": 0.30,
        "ssd_confidence_threshold": 20000.0,
        "roi_factor": 3.5,
        "search_scales": DEFAULT_RELATIVE_SCALES,
        "fine_radius": 12,
        "downsample": 4,
    }
    if not config_path:
        return defaults
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        user = cfg.get("detection", {})
        return {**defaults, **user}
    except Exception:
        return defaults


def _load_image_rgb(path: str) -> np.ndarray:
    """Load image as RGB float32 numpy array."""
    img = Image.open(path)
    if img.mode == "RGBA":
        # Composite onto white background so transparent areas don't confuse matching
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img, dtype=np.float32)


def _load_image_rgba(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Load image as RGB float32 + alpha mask (0-1).

    Fully-transparent pixels have their RGB forced to 0 so they never
    contribute to template matching, regardless of weight precision.
    """
    img = Image.open(path)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    arr = np.array(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3] / 255.0
    # Force RGB to 0 where fully transparent — eliminates phantom residuals
    rgb[alpha < 0.02] = 0.0
    return rgb, alpha


def _compute_roi(px: int, py: int, pw: int, ph: int, canvas_w: int, canvas_h: int) -> tuple:
    """Compute search ROI centered on planned position."""
    roi_w = int(pw * ROI_FACTOR)
    roi_h = int(ph * ROI_FACTOR)
    roi_x = max(0, px - (roi_w - pw) // 2)
    roi_y = max(0, py - (roi_h - ph) // 2)
    roi_w = min(roi_w, canvas_w - roi_x)
    roi_h = min(roi_h, canvas_h - roi_y)
    return roi_x, roi_y, roi_w, roi_h


def _downsample(arr: np.ndarray, factor: int) -> np.ndarray:
    """Simple box downsample by integer factor."""
    h, w = arr.shape[:2]
    h = (h // factor) * factor
    w = (w // factor) * factor
    arr = arr[:h, :w]
    if arr.ndim == 3:
        return arr.reshape(h // factor, factor, w // factor, factor, arr.shape[2]).mean(axis=(1, 3))
    return arr.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))


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


def _subpixel_refinement(ssd_map: np.ndarray, cy: int, cx: int) -> tuple[float, float]:
    """Parabolic fit for subpixel minimum estimation on an SSD map.

    Fits a 1D parabola separately in x and y directions using the 3×3
    neighborhood around (cy, cx). Returns (subpixel_y, subpixel_x) offsets
    in downsampled coordinates, clamped to [-0.5, 0.5].

    Falls back to (0.0, 0.0) if the minimum is at the boundary or if the
    parabola opens downward (unreliable fit).
    """
    H, W = ssd_map.shape
    if cy <= 0 or cy >= H - 1 or cx <= 0 or cx >= W - 1:
        return 0.0, 0.0

    center = ssd_map[cy, cx]
    left = ssd_map[cy, cx - 1]
    right = ssd_map[cy, cx + 1]
    top = ssd_map[cy - 1, cx]
    bottom = ssd_map[cy + 1, cx]

    # x direction: dx = (left - right) / (2 * (left + right - 2*center))
    denom_x = 2.0 * (left + right - 2.0 * center)
    dx = (left - right) / denom_x if denom_x > 0 else 0.0
    dx = max(-0.5, min(0.5, dx))

    # y direction: dy = (top - bottom) / (2 * (top + bottom - 2*center))
    denom_y = 2.0 * (top + bottom - 2.0 * center)
    dy = (top - bottom) / denom_y if denom_y > 0 else 0.0
    dy = max(-0.5, min(0.5, dy))

    return dy, dx


def _match_scale(roi_rgb: np.ndarray, tpl_rgb: np.ndarray, tpl_alpha: np.ndarray,
                   downsample: int = 4, fine_radius: int = 12,
                   fusion_matcher=None, scale: float = 1.0) -> tuple:
    """Match a single-scale template inside ROI. Returns (best_y, best_x, best_ssd, valid_pixels).

    If ``fusion_matcher`` is provided, the downsampled coarse match uses the
    fused feature score (higher = better) instead of pure SSD.  The ±1px
    confirmation still computes SSD for confidence consistency.
    """
    H, W = roi_rgb.shape[:2]
    h, w = tpl_rgb.shape[:2]

    if h > H or w > W:
        # Template larger than ROI — can't match
        return None, None, float("inf"), 0

    # Build alpha weight mask: (h, w, 1)
    weight = tpl_alpha[:, :, np.newaxis]
    valid_pixels = max(1, int(tpl_alpha.sum()))

    # --- Coarse match at 1/downsample resolution ---
    roi_d = _downsample(roi_rgb, downsample)
    tpl_d = _downsample(tpl_rgb, downsample)
    alpha_d = _downsample(tpl_alpha, downsample)

    Hd, Wd = roi_d.shape[:2]
    hd, wd = tpl_d.shape[:2]
    if hd > Hd or wd > Wd:
        return None, None, float("inf"), 0

    if fusion_matcher is not None:
        # Fusion-based coarse matching (higher score = better)
        # Pass full-res RGB/alpha so SNR-aware matchers (gradient, edge_canny)
        # compute their feature on the unblurred surface, then downsample the
        # feature map.  This preserves high-frequency edge content that box-
        # averaging at the RGB level would otherwise destroy.
        desc = fusion_matcher.extract(
            tpl_d, alpha_d,
            full_res_rgb=tpl_rgb, full_res_alpha=tpl_alpha,
            downsample_factor=downsample,
        )
        result = fusion_matcher.match(
            roi_d, desc, scale,
            full_res_roi=roi_rgb, downsample_factor=downsample,
        )
        score_map = result.score_map
        cy_d, cx_d = np.unravel_index(np.argmax(score_map), score_map.shape)
        # Subpixel refinement on inverted map (turn max → min)
        sub_y, sub_x = _subpixel_refinement(-score_map, cy_d, cx_d)
    else:
        # Legacy SSD-based coarse matching (lower = better)
        ssd_map = _ssd_via_fft(roi_d, tpl_d, alpha_d)
        cy_d, cx_d = np.unravel_index(np.argmin(ssd_map), ssd_map.shape)
        sub_y, sub_x = _subpixel_refinement(ssd_map, cy_d, cx_d)

    # Map subpixel position back to original resolution
    fine_y = int(round((cy_d + sub_y) * downsample))
    fine_x = int(round((cx_d + sub_x) * downsample))

    # Clamp to valid search range
    fine_y = max(0, min(fine_y, H - h))
    fine_x = max(0, min(fine_x, W - w))

    # --- ±1px confirmation search (SSD for cross-scale confidence consistency) ---
    best_y, best_x = fine_y, fine_x
    best_ssd = float("inf")

    for dy in range(-1, 2):
        for dx in range(-1, 2):
            y = fine_y + dy
            x = fine_x + dx
            if y < 0 or y > H - h or x < 0 or x > W - w:
                continue
            patch = roi_rgb[y:y + h, x:x + w]
            diff = patch * weight - tpl_rgb * weight
            ssd_val = float(np.sum(diff ** 2))
            if ssd_val < best_ssd:
                best_ssd = ssd_val
                best_y, best_x = y, x

    return best_y, best_x, best_ssd, valid_pixels


def detect_layer(
    layer_id: str,
    layer_png_path: Path,
    preview_rgb: np.ndarray,
    planned_layout: dict,
    canvas_w: int,
    canvas_h: int,
    scales: list[float],
    roi_factor: float = 3.5,
    ssd_threshold: float = 20000.0,
    downsample: int = 4,
    fine_radius: int = 12,
    opacity: float = 1.0,
    force: bool = False,
    fusion_matcher: FusionMatcher | None = None,
) -> dict:
    """Detect a single layer's position via multi-scale template matching.

    Semitransparent layers (opacity < 0.85) are skipped because the preview
    shows a blended color (foreground + background) while the extracted
    layer is opaque, making pixel-level matching unreliable.

    Use ``force=True`` to bypass the opacity safety check (user explicitly
    requests detection on a semitransparent layer).
    """
    import math
    import time
    t_start = time.perf_counter()

    px = planned_layout.get("x", 0)
    py = planned_layout.get("y", 0)
    pw = planned_layout.get("width", canvas_w)
    ph = planned_layout.get("height", canvas_h)

    # Skip semitransparent layers — template vs preview color mismatch
    if not force and opacity < 0.85:
        return {
            "detected": {"x": px, "y": py, "width": pw, "height": ph},
            "planned": {"x": px, "y": py, "width": pw, "height": ph},
            "ssd": 0.0,
            "scale": 1.0,
            "method": "skipped_semitransparent",
            "reason": f"opacity={opacity:.2f} < 0.85",
            "timing_ms": 0.0,
        }

    # Load template (with alpha)
    tpl_rgb, tpl_alpha = _load_image_rgba(str(layer_png_path))
    tpl_h, tpl_w = tpl_rgb.shape[:2]

    # Compute ROI
    roi_w = int(pw * roi_factor)
    roi_h = int(ph * roi_factor)
    roi_x = max(0, px - (roi_w - pw) // 2)
    roi_y = max(0, py - (roi_h - ph) // 2)
    roi_w = min(roi_w, canvas_w - roi_x)
    roi_h = min(roi_h, canvas_h - roi_y)

    roi_rgb = preview_rgb[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]

    # --- Pyramid Level 0: Ultra-coarse pre-screening ---
    # Optimization: downsample the ORIGINAL template once, then resize only
    # the downsampled version. Resize area drops by COARSE_DOWNSAMPLE^2 (~64x).
    t_coarse_start = time.perf_counter()
    roi_coarse = _downsample(roi_rgb, COARSE_DOWNSAMPLE)
    tpl_base = _downsample(tpl_rgb, COARSE_DOWNSAMPLE)
    alpha_base = _downsample(tpl_alpha, COARSE_DOWNSAMPLE)
    base_h, base_w = tpl_base.shape[:2]

    coarse_scores = []
    # Compute base scale so that template fits inside planned rect (contain)
    tpl_orig_h, tpl_orig_w = tpl_rgb.shape[:2]
    base_scale = min(pw / max(1, tpl_orig_w), ph / max(1, tpl_orig_h))
    base_scale = max(0.05, min(5.0, base_scale))

    # Convert relative scales to absolute scales
    abs_scales = [base_scale * s for s in scales]

    for s in abs_scales:
        target_w = max(1, int(base_w * s))
        target_h = max(1, int(base_h * s))

        # Resize downsampled template (area ~64x smaller than original)
        tpl_coarse = np.array(
            Image.fromarray(tpl_base.astype(np.uint8)).resize((target_w, target_h), Image.BILINEAR),
            dtype=np.float32,
        )
        alpha_coarse = np.array(
            Image.fromarray((alpha_base * 255).astype(np.uint8)).resize((target_w, target_h), Image.BILINEAR),
            dtype=np.float32,
        ) / 255.0
        alpha_coarse[alpha_coarse < 0.02] = 0.0

        if alpha_coarse.sum() < 10:
            continue

        Hc, Wc = roi_coarse.shape[:2]
        hc, wc = tpl_coarse.shape[:2]
        if hc > Hc or wc > Wc:
            continue

        # Store the FULL-resolution resized template for fine matching later.
        # CRITICAL: use the template's ORIGINAL aspect ratio, NOT the planned size.
        # Planned size is an estimate; the cropped PNG's actual proportions are the
        # ground truth for matching. Scaling the original template preserves its
        # true shape and avoids aspect-ratio distortion that kills matching.
        tpl_orig_h, tpl_orig_w = tpl_rgb.shape[:2]
        full_target_w = max(1, int(tpl_orig_w * s))
        full_target_h = max(1, int(tpl_orig_h * s))
        tpl_resized = np.array(
            Image.fromarray(tpl_rgb.astype(np.uint8)).resize((full_target_w, full_target_h), Image.LANCZOS),
            dtype=np.float32,
        )
        alpha_resized = np.array(
            Image.fromarray((tpl_alpha * 255).astype(np.uint8)).resize((full_target_w, full_target_h), Image.LANCZOS),
            dtype=np.float32,
        ) / 255.0
        alpha_resized[alpha_resized < 0.02] = 0.0

        if fusion_matcher is not None:
            # Fusion-based coarse scoring (higher = better).
            # Pass the full-resolution resized template + ROI so SNR-aware
            # matchers (gradient, edge_canny) get high-frequency content.
            desc = fusion_matcher.extract(
                tpl_coarse, alpha_coarse,
                full_res_rgb=tpl_resized, full_res_alpha=alpha_resized,
                downsample_factor=COARSE_DOWNSAMPLE,
            )
            result = fusion_matcher.match(
                roi_coarse, desc, s,
                full_res_roi=roi_rgb, downsample_factor=COARSE_DOWNSAMPLE,
            )
            # DEBUG: print per-feature best position
            if hasattr(fusion_matcher, 'matchers') and len(fusion_matcher.matchers) == 1:
                feat_name = list(fusion_matcher.matchers.keys())[0]
                print(f"       [COARSE-{feat_name}] scale={s:.3f} best=({result.best_y},{result.best_x}) score={result.best_score:.4f}")
            coarse_scores.append((result.best_score, s, tpl_resized, alpha_resized))
        else:
            # Legacy SSD-based coarse scoring (lower = better)
            ssd_map = _ssd_via_fft(roi_coarse, tpl_coarse, alpha_coarse)
            min_ssd = float(ssd_map.min())
            cy, cx = np.unravel_index(np.argmin(ssd_map), ssd_map.shape)
            print(f"       [COARSE-SSD] scale={s:.3f} best=({cy},{cx}) ssd={min_ssd:.2f}")
            coarse_scores.append((min_ssd, s, tpl_resized, alpha_resized))

    # Keep top-K candidates
    if fusion_matcher is not None:
        coarse_scores.sort(key=lambda x: x[0], reverse=True)
    else:
        coarse_scores.sort(key=lambda x: x[0])
    candidate_scales = coarse_scores[:COARSE_TOP_K]
    t_coarse_elapsed = (time.perf_counter() - t_coarse_start) * 1000

    if not candidate_scales:
        t_total = (time.perf_counter() - t_start) * 1000
        return {
            "detected": {"x": px, "y": py, "width": pw, "height": ph},
            "planned": {"x": px, "y": py, "width": pw, "height": ph},
            "ssd": float("inf"),
            "scale": 1.0,
            "method": "planned_fallback",
            "reason": "no_scale_passed_coarse_screening",
            "timing_ms": round(t_total, 2),
        }

    # --- Pyramid Level 1: Fine matching on top candidates ---
    t_fine_start = time.perf_counter()
    best_result = None
    best_ssd = float("inf")
    best_scale = 1.0
    best_valid_pixels = 1
    scale_timings = []

    for _coarse_ssd, s, tpl_resized, alpha_resized in candidate_scales:
        t_scale_start = time.perf_counter()
        match_result = _match_scale(roi_rgb, tpl_resized, alpha_resized,
                                     downsample=downsample, fine_radius=fine_radius,
                                     fusion_matcher=fusion_matcher, scale=s)
        t_scale_elapsed = (time.perf_counter() - t_scale_start) * 1000
        scale_timings.append(round(t_scale_elapsed, 2))

        if match_result[0] is None:
            continue
        my, mx, ssd_val, valid_pixels = match_result

        target_h, target_w = tpl_resized.shape[:2]

        # Cross-scale comparison: normalize by pixel count with mild penalties
        total_pixels = max(1, target_h * target_w)
        base_norm = ssd_val / total_pixels

        # Mild scale penalty (0.5x or 2x gets ~7% penalty)
        scale_penalty = 1.0 + 0.15 * abs(s - 1.0)

        # Position offset penalty: farther from planned position = higher cost
        planned_mx = px - roi_x
        planned_my = py - roi_y
        offset_dist = math.sqrt((mx - planned_mx) ** 2 + (my - planned_my) ** 2)
        offset_penalty = 1.0 + 0.3 * (offset_dist / max(1, (pw + ph) / 2))

        norm_ssd = base_norm * scale_penalty * offset_penalty
        best_norm = (
            (best_ssd / max(1, best_result[2] * best_result[3]))
            * (1.0 + 0.15 * abs(best_scale - 1.0))
            * (1.0 + 0.3 * (math.sqrt((best_result[1] - planned_mx) ** 2 + (best_result[0] - planned_my) ** 2) / max(1, (pw + ph) / 2)))
        ) if best_result else float("inf")

        # Prefer better normalized+penalized SSD; tie-break toward scale=1.0
        ssd_improved = norm_ssd < best_norm * 0.99
        ssd_similar = abs(norm_ssd - best_norm) / max(1e-6, best_norm) < 0.05 if best_norm < 1e6 else (norm_ssd < 1e6)
        scale_better = abs(s - 1.0) < abs(best_scale - 1.0)
        if ssd_improved or (ssd_similar and scale_better):
            best_ssd = ssd_val
            best_scale = s
            best_result = (my, mx, target_h, target_w)
            best_valid_pixels = valid_pixels

    t_fine_elapsed = (time.perf_counter() - t_fine_start) * 1000
    t_total = (time.perf_counter() - t_start) * 1000

    # Compute per-pixel SSD for confidence using VALID (non-transparent) pixels
    if best_result is not None:
        _, _, th, tw = best_result
        per_pixel_ssd = best_ssd / max(1, best_valid_pixels)
    else:
        per_pixel_ssd = float("inf")

    # Determine confidence
    if best_result is None or per_pixel_ssd > ssd_threshold:
        # Low confidence: fallback to planned
        return {
            "detected": {"x": px, "y": py, "width": pw, "height": ph},
            "planned": {"x": px, "y": py, "width": pw, "height": ph},
            "ssd": round(per_pixel_ssd, 2),
            "scale": 1.0,
            "method": "planned_fallback",
            "reason": "match_failed_or_low_confidence" if best_result is None else "ssd_too_high",
            "timing_ms": round(t_total, 2),
        }

    my, mx, th, tw = best_result
    detected_x = roi_x + mx
    detected_y = roi_y + my

    return {
        "detected": {"x": detected_x, "y": detected_y, "width": tw, "height": th},
        "planned": {"x": px, "y": py, "width": pw, "height": ph},
        "ssd": round(per_pixel_ssd, 2),
        "scale": round(best_scale, 3),
        "method": "template_match",
        "timing_ms": round(t_total, 2),
        "timing_detail_ms": {
            "coarse_screening": round(t_coarse_elapsed, 2),
            "fine_matching": round(t_fine_elapsed, 2),
            "per_scale": scale_timings,
        },
    }


def _prepare_detection(
    project_name: str,
    preview_path: str,
    phase: str,
    config_path: str | None = None,
    scales: list[float] | None = None,
) -> dict:
    """Prepare shared resources for layer position detection.

    Returns a context dict with all common data needed by both single-layer
    and multi-layer detection.
    """
    pm = PathManager(project_name, config_path=config_path)
    det_cfg = _get_detection_config(config_path)

    # Read layer plan.  Prefer the expanded plan if it exists (it has the
    # per-cell instances we need to populate per-instance detected positions
    # for grid/list parents).  Falls back to the un-expanded plan.
    expanded_path = pm.get_expanded_layer_plan_path(phase="check")
    layer_plan_path = pm.get_layer_plan_path()
    chosen_path = expanded_path if expanded_path.exists() else layer_plan_path
    if not chosen_path.exists():
        raise FileNotFoundError(f"layer_plan.json not found: {chosen_path}")
    with open(chosen_path, "r", encoding="utf-8-sig") as f:
        layer_plan = json.load(f)

    # Determine canvas size and layer root
    size_plan_path = pm.get_phase_dir("requirements") / "size_plan.json"
    layout_scale_x = layout_scale_y = 1.0
    if size_plan_path.exists():
        with open(size_plan_path, "r", encoding="utf-8") as f:
            size_plan = json.load(f)
        full = size_plan.get("full_size", {})
        early = size_plan.get("early_size", {})
        if full and early:
            canvas_w = early.get("width", 1024)
            canvas_h = early.get("height", 1024)
            layout_scale_x = canvas_w / full.get("width", canvas_w)
            layout_scale_y = canvas_h / full.get("height", canvas_h)
        else:
            canvas_w = early.get("width", 1024) if early else full.get("width", 1024)
            canvas_h = early.get("height", 1024) if early else full.get("height", 1024)
    else:
        dims = layer_plan.get("dimensions", {})
        canvas_w = dims.get("width", 1024)
        canvas_h = dims.get("height", 1024)

    if phase in ("rough", "check"):
        layer_root = pm.get_phase_dir("rough_design")
    elif phase == "refinement":
        layer_root = pm.get_phase_dir("refinement_layers")
    else:
        raise ValueError(f"Unknown phase: {phase}")

    # Load preview
    preview_rgb = _load_image_rgb(preview_path)
    preview_w, preview_h = preview_rgb.shape[1], preview_rgb.shape[0]
    scale_x = scale_y = 1.0
    if preview_w != canvas_w or preview_h != canvas_h:
        print(f"[WARN] Preview size {preview_w}x{preview_h} "
              f"does not match canvas {canvas_w}x{canvas_h}. Scaling layouts to preview size.")
        scale_x = preview_w / canvas_w
        scale_y = preview_h / canvas_h
        canvas_w, canvas_h = preview_w, preview_h

    scales = scales or det_cfg.get("search_scales", DEFAULT_RELATIVE_SCALES)
    roi_factor = det_cfg.get("roi_factor", 3.5)
    ssd_threshold = det_cfg.get("ssd_confidence_threshold", 20000.0)
    downsample = det_cfg.get("downsample", 4)
    fine_radius = det_cfg.get("fine_radius", 12)

    return {
        "pm": pm,
        "layer_plan": layer_plan,
        "preview_rgb": preview_rgb,
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "layout_scale_x": layout_scale_x,
        "layout_scale_y": layout_scale_y,
        "layer_root": layer_root,
        "scales": scales,
        "roi_factor": roi_factor,
        "ssd_threshold": ssd_threshold,
        "downsample": downsample,
        "fine_radius": fine_radius,
    }


def _resolve_layer(
    layer_info: dict,
    context: dict,
    force: bool = False,
) -> tuple[str, Path | None, dict, float, str | None] | None:
    """Resolve a single layer for detection.

    Returns (layer_id, png_path, planned_layout, opacity, skip_reason) or None.
    - skip_reason is a string if this layer should not be template-matched
      (background, repeat, missing PNG, etc.). png_path will be None.
    - skip_reason is None for detectable layers.
    - Returns None if the layer has no valid id/name.

    Use ``force=True`` to bypass background/repeat safety checks.
    """
    layer_id = layer_info.get("id", "") or layer_info.get("name", "")
    if not layer_id:
        return None

    canvas_w = context["canvas_w"]
    canvas_h = context["canvas_h"]
    scale_x = context["scale_x"]
    scale_y = context["scale_y"]
    layout_scale_x = context["layout_scale_x"]
    layout_scale_y = context["layout_scale_y"]

    # Compute planned layout (needed for all layers, even skipped ones)
    raw_planned = layer_info.get("layout", {})
    planned = {
        "x": int(round(raw_planned.get("x", 0) * layout_scale_x * scale_x)),
        "y": int(round(raw_planned.get("y", 0) * layout_scale_y * scale_y)),
        "width": int(round(raw_planned.get("width", canvas_w) * layout_scale_x * scale_x)),
        "height": int(round(raw_planned.get("height", canvas_h) * layout_scale_y * scale_y)),
    }

    # PL mode: override planned with crop_bbox from layer_meta.json when available.
    # Rationale: layer_plan.layout for PL layers is the agent's visual estimate (often
    # very inaccurate). crop_bbox tracks where the AI actually placed the element on
    # the full early-size canvas (which equals the preview canvas for PL mode), giving
    # a much better ROI center, base scale, and position-penalty anchor.
    if layer_info.get("precise_layout", False):
        layer_root = context["layer_root"]
        meta_path = layer_root / layer_id / "layer_meta.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8-sig") as f:
                    meta = json.load(f)
                bbox = meta.get("crop_bbox")
                # crop_bbox is (x, y, width, height) — see crop_to_content.py
                if bbox and len(bbox) == 4:
                    planned = {
                        "x": int(bbox[0]),
                        "y": int(bbox[1]),
                        "width": int(bbox[2]),
                        "height": int(bbox[3]),
                    }
            except Exception:
                pass  # fall back to layer_plan layout

    # Background layers are not matched (unless forced)
    if not force and layer_info.get("is_background", False):
        return layer_id, None, planned, 1.0, "background"

    # Repeat-related layers are not matched (unless forced).
    # Repeat panels are allowed through so their detected bbox can refine
    # the container position instead of relying solely on the planner.
    repeat_mode = layer_info.get("repeat_mode")
    is_repeat = (
        repeat_mode in ("grid", "list")
        or layer_info.get("is_repeat_instance", False)
        or layer_info.get("is_repeat_parent", False)
    )
    if not force and is_repeat:
        reason = f"repeat_mode={repeat_mode}" if repeat_mode else "repeat-related"
        return layer_id, None, planned, 1.0, reason

    # Skip repeat panels when no source PNG is available
    if layer_info.get("is_repeat_panel", False):
        layer_root = context["layer_root"]
        layer_dir = layer_root / layer_id
        has_png = bool(
            sorted(layer_dir.glob("*_cropped.png"))
            or sorted(layer_dir.glob("*.png"))
        )
        if not has_png:
            return layer_id, None, planned, 1.0, "repeat-related"

    layer_root = context["layer_root"]
    layer_dir = layer_root / layer_id
    if not layer_dir.exists():
        return layer_id, None, planned, 1.0, "directory_not_found"

    # Select PNG using same logic as Phase 4 generate_preview.py
    png_files = sorted(layer_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    png_path = None
    for p in png_files:
        if p.stem.endswith("_cropped"):
            png_path = p
            break
    if png_path is None:
        candidates = [p for p in png_files
                      if not p.stem.endswith("_raw")
                      and not p.stem.endswith("_stage1")
                      and not p.stem.endswith("_stage2")]
        png_path = candidates[0] if candidates else (png_files[0] if png_files else None)

    if png_path is None:
        return layer_id, None, planned, 1.0, "no_png_found"

    opacity = layer_info.get("opacity", 1.0)
    return layer_id, png_path, planned, opacity, None


def _resolve_padding(padding) -> tuple[int, int, int, int]:
    """Normalise a repeat_config padding spec into (top, right, bottom, left).

    Accepts:
      - 0 / None / falsy → (0, 0, 0, 0)
      - int → uniform padding on all sides
      - dict with any of "top"/"right"/"bottom"/"left" keys (missing → 0)
    Anything else falls back to (0, 0, 0, 0).
    """
    if not padding:
        return 0, 0, 0, 0
    if isinstance(padding, (int, float)):
        v = int(padding)
        return v, v, v, v
    if isinstance(padding, dict):
        return (
            int(padding.get("top", 0) or 0),
            int(padding.get("right", 0) or 0),
            int(padding.get("bottom", 0) or 0),
            int(padding.get("left", 0) or 0),
        )
    return 0, 0, 0, 0


def _is_grid_parent(layer_info: dict) -> bool:
    """A layer drives periodic detection when it's a grid/list parent.

    Two valid shapes:

    - Post-expansion (rough/check): ``repeat_mode in ('grid', 'list')`` and
      ``is_repeat_parent=True``.  Instances and panels are siblings.
    - Pre-expansion (raw plan): ``repeat_mode in ('grid', 'list')`` and the
      layer has a ``repeat_config`` block.  No instances exist yet.

    In either case we exclude entries that are explicitly an instance or
    panel.
    """
    if layer_info.get("is_repeat_instance"):
        return False
    if layer_info.get("is_repeat_panel"):
        return False
    if layer_info.get("repeat_mode") not in ("grid", "list"):
        return False
    if layer_info.get("is_repeat_parent"):
        return True
    return bool(layer_info.get("repeat_config"))


def _load_grid_template(layer_root: Path, layer_id: str) -> np.ndarray | None:
    """Load the cropped template PNG (RGBA) for a grid/list parent layer."""
    layer_dir = layer_root / layer_id
    if not layer_dir.exists():
        return None
    pngs = sorted(layer_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pngs:
        return None
    template_path = None
    for p in pngs:
        if p.stem.endswith("_cropped"):
            template_path = p
            break
    if template_path is None:
        cand = [
            p for p in pngs
            if not p.stem.endswith("_raw")
            and not p.stem.endswith("_stage1")
            and not p.stem.endswith("_stage2")
        ]
        template_path = cand[0] if cand else pngs[0]
    img = Image.open(str(template_path))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return np.array(img)


def _detect_grid_layer(
    layer_info: dict,
    context: dict,
) -> list[tuple[str, dict]] | None:
    """Run 1D self-similarity detection on a grid/list parent layer.

    Returns a list of ``(layer_id, result)`` pairs:
    - First entry is the parent layer with the enclosing bbox plus a
      ``cells`` list, ``cell_size``, ``gap``, ``rows``, ``cols``.
    - Following entries are per-cell instance updates whose detected
      position has been swapped in from the periodic match.
    """
    layer_id = layer_info.get("id", "") or layer_info.get("name", "")
    if not layer_id:
        return None
    repeat_mode = layer_info.get("repeat_mode", "grid")
    repeat_config = layer_info.get("repeat_config") or {}

    layout_scale_x = context["layout_scale_x"] * context["scale_x"]
    layout_scale_y = context["layout_scale_y"] * context["scale_y"]

    # ROI = area_layout MINUS the planner's padding (when supplied).  The
    # padding describes the gutter between the auto-panel's outer frame and
    # the first row/column of cells.  Including the gutter in the ROI lets
    # the panel's bevel/edge gradients dominate the autocorrelation, which
    # often produces a wrong period (e.g. a sub-cell harmonic of the panel
    # decoration).  Stripping the padding constrains detection to the inner
    # cell tiling area — exactly what we want for periodicity analysis.
    area = repeat_config.get("area_layout") or layer_info.get("layout", {})

    # Auto-derive padding from the auto_panel sibling when the planner left
    # `repeat_config.padding` empty/zero.  When `auto_panel.enabled=true` is
    # set but padding is missing, the LLM-rendered panel often doesn't fill
    # the full area_layout (or its bevel/title bar eats into where the
    # cells actually sit), and autocorrelation on the unstripped ROI sees
    # the panel's bevel gradient and locks onto a wrong harmonic.
    # Reusing the panel sibling's already-detected bbox lets us shrink the
    # ROI to where the cells truly tile, without an extra template match
    # in the cheap path.
    raw_padding = repeat_config.get("padding")
    padding_is_empty = (
        not raw_padding
        or (isinstance(raw_padding, (int, float)) and raw_padding == 0)
        or (
            isinstance(raw_padding, dict)
            and not any(
                int(raw_padding.get(k, 0) or 0) > 0
                for k in ("top", "right", "bottom", "left")
            )
        )
    )
    auto_panel_cfg = repeat_config.get("auto_panel")
    if isinstance(auto_panel_cfg, dict):
        auto_panel_enabled = bool(auto_panel_cfg.get("enabled", True))
    else:
        auto_panel_enabled = bool(auto_panel_cfg)
    derived_padding = None
    if padding_is_empty and auto_panel_enabled and area:
        # Resolve panel sibling id: explicit `auto_panel.id` first, fall
        # back to the `<layer>_panel` naming convention so older plans
        # without the explicit field still benefit.
        panel_id = ""
        if isinstance(auto_panel_cfg, dict):
            panel_id = (
                auto_panel_cfg.get("id")
                or auto_panel_cfg.get("name")
                or ""
            )
        if not panel_id:
            panel_id = f"{layer_id}_panel"

        # Cheap path: a previous step in the same run already detected the
        # panel and stuffed the result into context.  We don't currently
        # populate this from `detect_all_layers`, but plumbing through
        # `context["detection_results_so_far"]` (or the running `results`)
        # would let us skip the in-place template match below.
        panel_bbox_scaled = None
        prior_results = context.get("detection_results_so_far")
        if not isinstance(prior_results, dict):
            prior_results = context.get("results")
        if isinstance(prior_results, dict):
            prior = prior_results.get(panel_id)
            if isinstance(prior, dict):
                method = prior.get("method", "")
                bb = prior.get("detected") or {}
                if (
                    method == "template_match"
                    and bb.get("width", 0) > 0
                    and bb.get("height", 0) > 0
                ):
                    panel_bbox_scaled = bb

        # Fallback: template-match the panel sibling in place.  More
        # expensive than reusing a prior result, but self-contained and
        # only fires when the planner left padding unspecified.
        if panel_bbox_scaled is None:
            panel_layer = next(
                (
                    l
                    for l in context["layer_plan"].get("layers", [])
                    if (l.get("id") or l.get("name")) == panel_id
                ),
                None,
            )
            if panel_layer is not None and not panel_layer.get(
                "is_repeat_instance"
            ):
                panel_pl = panel_layer.get("layout") or {}
                panel_planned = {
                    "x": int(round(panel_pl.get("x", 0) * layout_scale_x)),
                    "y": int(round(panel_pl.get("y", 0) * layout_scale_y)),
                    "width": int(round(panel_pl.get("width", 0) * layout_scale_x)),
                    "height": int(round(panel_pl.get("height", 0) * layout_scale_y)),
                }
                panel_dir = context["layer_root"] / panel_id
                if panel_dir.exists() and panel_planned["width"] > 0 and panel_planned["height"] > 0:
                    pngs = (
                        sorted(panel_dir.glob("*_cropped.png"))
                        or [
                            p
                            for p in sorted(
                                panel_dir.glob("*.png"),
                                key=lambda p: p.stat().st_mtime,
                                reverse=True,
                            )
                            if not p.stem.endswith("_raw")
                            and not p.stem.endswith("_stage1")
                            and not p.stem.endswith("_stage2")
                            and not p.stem.endswith("_matte")
                        ]
                    )
                    if pngs:
                        try:
                            panel_match = detect_layer(
                                panel_id,
                                pngs[0],
                                context["preview_rgb"],
                                panel_planned,
                                context["canvas_w"],
                                context["canvas_h"],
                                context["scales"],
                                roi_factor=context["roi_factor"],
                                ssd_threshold=context["ssd_threshold"],
                                downsample=context["downsample"],
                                fine_radius=context["fine_radius"],
                                opacity=panel_layer.get("opacity", 1.0),
                                force=False,
                                fusion_matcher=None,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"  [AUTO-PAD] {layer_id}: in-place panel match failed "
                                f"({panel_id}): {exc}"
                            )
                            panel_match = None
                        if (
                            isinstance(panel_match, dict)
                            and panel_match.get("method") == "template_match"
                        ):
                            bb = panel_match.get("detected") or {}
                            if bb.get("width", 0) > 0 and bb.get("height", 0) > 0:
                                panel_bbox_scaled = bb

        if panel_bbox_scaled is not None and layout_scale_x and layout_scale_y:
            # Convert the panel's detected bbox (scaled preview pixels) back
            # into plan coordinates so we can express insets relative to
            # area_layout — _resolve_padding's contract.
            inv_lsx = 1.0 / layout_scale_x
            inv_lsy = 1.0 / layout_scale_y
            panel_plan_x = panel_bbox_scaled["x"] * inv_lsx
            panel_plan_y = panel_bbox_scaled["y"] * inv_lsy
            panel_plan_x2 = (
                panel_bbox_scaled["x"] + panel_bbox_scaled["width"]
            ) * inv_lsx
            panel_plan_y2 = (
                panel_bbox_scaled["y"] + panel_bbox_scaled["height"]
            ) * inv_lsy
            area_x = area.get("x", 0)
            area_y = area.get("y", 0)
            area_x2 = area_x + area.get("width", 0)
            area_y2 = area_y + area.get("height", 0)
            candidate = {
                "top": max(0, int(round(panel_plan_y - area_y))),
                "left": max(0, int(round(panel_plan_x - area_x))),
                "right": max(0, int(round(area_x2 - panel_plan_x2))),
                "bottom": max(0, int(round(area_y2 - panel_plan_y2))),
            }
            if any(candidate[k] > 0 for k in candidate):
                derived_padding = candidate
                print(
                    f"  [AUTO-PAD] {layer_id}: derived padding={candidate} "
                    f"from panel '{panel_id}'"
                )

    pad_top, pad_right, pad_bottom, pad_left = _resolve_padding(
        derived_padding if derived_padding is not None else repeat_config.get("padding")
    )
    # Use the FULL area_layout as ROI so grid_periodicity can detect the true
    # distance between cells and the container boundary.  The planner's padding
    # is passed as a hint instead of being subtracted from the ROI.
    roi = {
        "x": int(round(area.get("x", 0) * layout_scale_x)),
        "y": int(round(area.get("y", 0) * layout_scale_y)),
        "width": int(round(area.get("width", 0) * layout_scale_x)),
        "height": int(round(area.get("height", 0) * layout_scale_y)),
    }
    if roi["width"] <= 0 or roi["height"] <= 0:
        return None

    # Cell size hint: prefer the first instance's layout (post-expansion);
    # fall back to repeat_config-implied size or the parent layout itself.
    cell_w_full = 0
    cell_h_full = 0
    layers_all = context["layer_plan"].get("layers", [])
    for child in layers_all:
        if child.get("is_repeat_instance") and child.get("parent_id") == layer_id:
            cl = child.get("layout", {})
            cell_w_full = cl.get("width", 0)
            cell_h_full = cl.get("height", 0)
            break
    if cell_w_full <= 0 or cell_h_full <= 0:
        # Pre-expansion: parent layout is the cell size
        pl = layer_info.get("layout", {})
        cell_w_full = pl.get("width", cell_w_full)
        cell_h_full = pl.get("height", cell_h_full)

    # Normalise hints across the two repeat_config dialects:
    #   grid → {cols, rows, gap_x, gap_y}
    #   list → {direction, count, gap}
    # Translating list-mode hints to the same {cols, rows, gap_x, gap_y}
    # shape lets downstream walk-back / count gating treat both modes
    # uniformly without having to re-parse the original config.
    cols_hint = int(repeat_config.get("cols", 0) or 0)
    rows_hint = int(repeat_config.get("rows", 0) or 0)
    gap_x_hint = repeat_config.get("gap_x", 0) or 0
    gap_y_hint = repeat_config.get("gap_y", 0) or 0
    if repeat_mode == "list":
        direction = str(repeat_config.get("direction", "vertical")).lower()
        count = int(repeat_config.get("count", 0) or 0)
        gap = repeat_config.get("gap", 0) or 0
        if direction == "horizontal":
            if cols_hint <= 0 and count > 0:
                cols_hint = count
            if rows_hint <= 0:
                rows_hint = 1
            if not gap_x_hint:
                gap_x_hint = gap
        else:
            if rows_hint <= 0 and count > 0:
                rows_hint = count
            if cols_hint <= 0:
                cols_hint = 1
            if not gap_y_hint:
                gap_y_hint = gap

    hints = {
        "cell_w": int(round(cell_w_full * layout_scale_x)),
        "cell_h": int(round(cell_h_full * layout_scale_y)),
        "gap_x": int(round(gap_x_hint * layout_scale_x)),
        "gap_y": int(round(gap_y_hint * layout_scale_y)),
        "cols": cols_hint,
        "rows": rows_hint,
    }

    # List orientation heuristic.  Priority order:
    #   1) cols/rows hints (cols>1 → horizontal, rows>1 → vertical)
    #   2) ROI aspect ratio when both counts are unknown — wide bands list
    #      horizontally, tall bands list vertically
    #   3) Cell aspect vs ROI aspect when ratios are ambiguous
    #   4) Default vertical
    list_axis = "y"
    if repeat_mode == "list":
        if hints["rows"] <= 1 and hints["cols"] > 1:
            list_axis = "x"
        elif hints["cols"] <= 1 and hints["rows"] > 1:
            list_axis = "y"
        else:
            roi_aspect = (roi["width"] / max(1, roi["height"]))
            if roi_aspect >= 1.5:
                list_axis = "x"
            elif roi_aspect <= 1.0 / 1.5:
                list_axis = "y"
            else:
                cw = max(1, hints["cell_w"])
                ch = max(1, hints["cell_h"])
                # Tall cells inside a roughly-square ROI ⇒ horizontal list.
                list_axis = "x" if (ch / cw) > 1.0 else "y"

    template_rgba = _load_grid_template(context["layer_root"], layer_id)

    result = detect_grid_periodicity(
        context["preview_rgb"],
        roi,
        mode="grid" if repeat_mode == "grid" else "list",
        list_axis=list_axis,
        template_rgba=template_rgba,
        hints=hints,
    )
    if result is None:
        return None

    # Use the FULL ROI as the parent detected area so padding can reflect the
    # true distance between cells and the container boundary.  Cells may fall
    # inside the area (positive padding) or spill outside (negative padding).
    bbox = {
        "x": roi["x"],
        "y": roi["y"],
        "width": roi["width"],
        "height": roi["height"],
    }

    parent_planned = roi
    method_name = f"{result.mode}_periodicity"

    out: list[tuple[str, dict]] = []
    out.append((layer_id, {
        "detected": bbox,
        "planned": parent_planned,
        "ssd": 0.0,
        "scale": 1.0,
        "method": method_name,
        "cells": result.cells,
        "cell_size": {"width": result.cell_w, "height": result.cell_h},
        "gap": {"x": result.gap_x, "y": result.gap_y},
        "rows": result.rows,
        "cols": result.cols,
        "confidence": result.confidence,
        "timing_ms": result.timing_ms,
        "per_axis": result.per_axis,
    }))

    # Map per-instance results: walk the expanded plan and for each
    # is_repeat_instance child of this parent, look up the matching cell
    # by (row, col) -> swap in the detected position.
    for child in layers_all:
        if not (child.get("is_repeat_instance") and child.get("parent_id") == layer_id):
            continue
        row = child.get("cell_row")
        col = child.get("cell_col")
        if row is None or col is None:
            continue
        match = next(
            (c for c in result.cells if c.get("row") == row and c.get("col") == col),
            None,
        )
        if match is None:
            continue
        cl = child.get("layout", {})
        child_planned = {
            "x": int(round(cl.get("x", 0) * layout_scale_x)),
            "y": int(round(cl.get("y", 0) * layout_scale_y)),
            "width": int(round(cl.get("width", 0) * layout_scale_x)),
            "height": int(round(cl.get("height", 0) * layout_scale_y)),
        }
        out.append((child.get("id", ""), {
            "detected": {
                "x": int(match["x"]),
                "y": int(match["y"]),
                "width": int(match["width"]),
                "height": int(match["height"]),
            },
            "planned": child_planned,
            "ssd": 0.0,
            "scale": 1.0,
            "method": f"{method_name}_cell",
            "row": int(row),
            "col": int(col),
            "confidence": result.confidence,
            "timing_ms": 0.0,
        }))

    return out


def detect_all_layers(
    project_name: str,
    preview_path: str,
    phase: str = "rough",
    config_path: str | None = None,
    scales: list[float] | None = None,
    layer_filter: list[str] | None = None,
    force: bool = False,
    profile: str | Path | dict | None = None,
) -> dict:
    """Run detection for selected layers.

    Args:
        layer_filter: If provided, only detect layers whose id or name matches
                      (case-insensitive). Supports both id and display name.
        force: If True, bypass opacity/background/repeat safety checks.
               Use only when the user explicitly requests detection on
               layers that would normally be skipped.
    """
    context = _prepare_detection(project_name, preview_path, phase, config_path, scales)
    layer_plan = context["layer_plan"]

    # Initialize fusion matcher if a profile is configured
    pm = PathManager(project_name, config_path=config_path)
    profile_cfg = _resolve_profile(profile, project_dir=pm.get_output_dir())
    fusion_matcher = FusionMatcher(profile_cfg) if profile_cfg else None

    results = {}
    layers = layer_plan.get("layers", [])

    # Normalize filter for case-insensitive matching
    filter_set = None
    if layer_filter:
        filter_set = {f.lower() for f in layer_filter}

    for layer_info in layers:
        layer_id = layer_info.get("id", "") or layer_info.get("name", "")

        # Apply filter if specified
        if filter_set and layer_id.lower() not in filter_set:
            continue

        # If a previous grid/list parent already emitted this layer (e.g. a
        # cell instance), keep the periodic-detection result instead of
        # overwriting it with the generic skip path.
        if layer_id in results:
            method = results[layer_id].get("method", "")
            if method.startswith("grid_periodicity") or method.startswith("list_periodicity"):
                continue

        # Background layers are skipped before the grid-parent branch so a
        # background mistakenly tagged as a grid parent never enters
        # periodicity detection. Honors --force for manual override.
        is_background = (
            layer_info.get("is_background", False) is True
            or layer_id == "background"
        )
        if not force and is_background:
            lsx = context["layout_scale_x"] * context["scale_x"]
            lsy = context["layout_scale_y"] * context["scale_y"]
            layout = layer_info.get("layout", {})
            planned = {
                "x": int(round(layout.get("x", 0) * lsx)),
                "y": int(round(layout.get("y", 0) * lsy)),
                "width": int(round(layout.get("width", 0) * lsx)),
                "height": int(round(layout.get("height", 0) * lsy)),
            }
            results[layer_id] = {
                "detected": planned,
                "planned": planned,
                "ssd": 0.0,
                "scale": 1.0,
                "method": "skipped_background",
                "reason": "background",
                "timing_ms": 0.0,
            }
            print(f"  [SKIP] {layer_id}: background")
            continue

        # Grid/list parents → 1D self-similarity detection.  This emits
        # the parent enclosing bbox (with cell metadata) plus per-instance
        # detected positions in one go.
        if _is_grid_parent(layer_info):
            print(f"  [GRID] {layer_id}: running periodicity detection")
            grid_results = _detect_grid_layer(layer_info, context)
            if grid_results:
                for child_id, child_result in grid_results:
                    if not child_id:
                        continue
                    if filter_set and child_id.lower() not in filter_set and child_id != layer_id:
                        # Still emit per-cell entries even if filter only
                        # named the parent; users expect them as a unit.
                        pass
                    results[child_id] = child_result
                head = grid_results[0][1]
                print(f"    → {head['method']}: rows={head['rows']} cols={head['cols']} "
                      f"cell={head['cell_size']} gap={head['gap']} "
                      f"conf={head['confidence']:.3f} time={head['timing_ms']:.1f}ms")
            else:
                # Detection failed: fall back to planned area_layout.
                area = layer_info.get("repeat_config", {}).get("area_layout") or layer_info.get("layout", {})
                lsx = context["layout_scale_x"] * context["scale_x"]
                lsy = context["layout_scale_y"] * context["scale_y"]
                planned = {
                    "x": int(round(area.get("x", 0) * lsx)),
                    "y": int(round(area.get("y", 0) * lsy)),
                    "width": int(round(area.get("width", 0) * lsx)),
                    "height": int(round(area.get("height", 0) * lsy)),
                }
                results[layer_id] = {
                    "detected": planned,
                    "planned": planned,
                    "ssd": 0.0,
                    "scale": 1.0,
                    "method": "grid_periodicity_fallback",
                    "reason": "detection_failed",
                    "timing_ms": 0.0,
                }
                print(f"    → grid_periodicity_fallback (detection returned None)")
            continue

        resolved = _resolve_layer(layer_info, context, force=force)
        if resolved is None:
            continue

        lid, png_path, planned, opacity, skip_reason = resolved

        if skip_reason:
            method_map = {
                "background": "skipped_background",
                "directory_not_found": "skipped_no_dir",
                "no_png_found": "skipped_no_png",
            }
            if skip_reason.startswith("repeat"):
                method = "skipped_repeat"
            else:
                method = method_map.get(skip_reason, "skipped")

            results[lid] = {
                "detected": planned,
                "planned": planned,
                "ssd": 0.0,
                "scale": 1.0,
                "method": method,
                "reason": skip_reason,
                "timing_ms": 0.0,
            }
            print(f"  [SKIP] {lid}: {skip_reason}")
            continue

        print(f"  [DETECT] {lid}: {png_path.name} @ planned {planned}")
        result = detect_layer(
            lid, png_path, context["preview_rgb"], planned,
            context["canvas_w"], context["canvas_h"], context["scales"],
            roi_factor=context["roi_factor"],
            ssd_threshold=context["ssd_threshold"],
            downsample=context["downsample"],
            fine_radius=context["fine_radius"],
            opacity=opacity,
            force=force,
            fusion_matcher=fusion_matcher,
        )
        results[lid] = result
        timing = result.get("timing_ms", 0)
        timing_detail = result.get("timing_detail_ms", {})
        print(f"    → {result['method']}: detected={result['detected']}, ssd={result['ssd']}, scale={result['scale']}, time={timing}ms")
        if timing_detail:
            print(f"       coarse={timing_detail.get('coarse_screening', 0)}ms, fine={timing_detail.get('fine_matching', 0)}ms, per_scale={timing_detail.get('per_scale', [])}")

    total_time = sum(r.get("timing_ms", 0) for r in results.values())
    matched_count = sum(
        1 for r in results.values()
        if r["method"] in ("template_match", "grid_periodicity", "list_periodicity")
        or r["method"].endswith("_periodicity_cell")
    )
    print(f"[TOTAL] Detection time: {total_time:.1f}ms ({matched_count}/{len(results)} layer(s) matched)")

    return {
        "project": project_name,
        "preview_source": preview_path,
        "canvas_size": {"width": context["canvas_w"], "height": context["canvas_h"]},
        "scales": context["scales"],
        "layers": results,
    }


def _build_enhanced_layer_plan(
    layer_plan: dict,
    detected_result: dict,
    pm: PathManager,
) -> dict:
    """Build an enhanced_layer_plan in preview coordinates from detection results."""
    dl = detected_result["layers"]
    canvas_w = detected_result["canvas_size"]["width"]
    canvas_h = detected_result["canvas_size"]["height"]
    full_w = layer_plan.get("dimensions", {}).get("width", canvas_w)
    full_h = layer_plan.get("dimensions", {}).get("height", canvas_h)
    sx = canvas_w / full_w if full_w else 1.0
    sy = canvas_h / full_h if full_h else 1.0

    def _sanitize(name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("._")

    def _find_source(layer_id: str) -> str:
        layer_dir = pm.get_layer_dir(layer_id)
        name = _sanitize(layer_id)
        # Prefer _cropped.png, fallback to plain .png
        cropped = sorted(layer_dir.glob(f"{name}_*_cropped.png"))
        if cropped:
            return f"../03-rough-design/{name}/{cropped[-1].name}"
        plain = sorted(layer_dir.glob(f"{name}_*.png"))
        if plain:
            return f"../03-rough-design/{name}/{plain[-1].name}"
        return ""

    def _to_preview_rect(r: dict) -> dict:
        return {
            "x": round(r["x"] * sx),
            "y": round(r["y"] * sy),
            "width": round(r["width"] * sx),
            "height": round(r["height"] * sy),
        }

    enhanced = {
        "project": layer_plan.get("project", ""),
        "phase": "check",
        "dimensions": {"width": canvas_w, "height": canvas_h},
        "style_anchor": layer_plan.get("style_anchor", ""),
        "layers": [],
        "stacking_order": [],
        "repeat_meta": [],
    }

    for layer in layer_plan.get("layers", []):
        layer_id = layer["id"]
        d = dl.get(layer_id, {})

        new_layer = {
            "id": layer_id,
            "name": layer.get("name", layer_id),
            "content": layer.get("description", layer.get("content", "")),
            "status": "active",
            "layout": {},
            "source": "",
            "opacity": layer.get("opacity", 1.0),
        }

        if layer.get("is_background"):
            # Background fills the preview canvas; it is not part of detection
            new_layer["layout"] = {"x": 0, "y": 0, "width": canvas_w, "height": canvas_h}
            new_layer["source"] = _find_source(layer_id)
            enhanced["layers"].append(new_layer)
            continue

        if "detected" in d:
            det = d["detected"]
            new_layer["layout"] = {
                "x": det["x"], "y": det["y"],
                "width": det["width"], "height": det["height"],
            }
        else:
            new_layer["layout"] = _to_preview_rect(layer["layout"])

        if layer.get("repeat_mode"):
            new_layer["is_repeat_parent"] = True
            new_layer["repeat_mode"] = layer["repeat_mode"]
            rc = dict(layer.get("repeat_config", {}))

            if "detected" in d:
                det = d["detected"]
                rc["area_layout"] = {
                    "x": det["x"], "y": det["y"],
                    "width": det["width"], "height": det["height"],
                }
            else:
                rc["area_layout"] = _to_preview_rect(rc.get("area_layout", layer["layout"]))

            cells = d.get("cells", [])
            if cells:
                gap = d.get("gap", {})
                area = rc["area_layout"]
                first = cells[0]
                last = cells[-1]
                padding = {
                    "top": first["y"] - area["y"],
                    "left": first["x"] - area["x"],
                    "right": (area["x"] + area["width"]) - (last["x"] + last["width"]),
                    "bottom": (area["y"] + area["height"]) - (last["y"] + last["height"]),
                }
                rc["padding"] = padding
                if layer["repeat_mode"] == "grid":
                    rc["gap_x"] = gap.get("x", 0)
                    rc["gap_y"] = gap.get("y", 0)
                    rc.pop("gap", None)
                else:
                    gx = gap.get("x", 0)
                    gy = gap.get("y", 0)
                    rc["gap"] = gy if gy > 0 else gx

            new_layer["repeat_config"] = rc
            auto_panel_cfg = layer.get("repeat_config", {}).get("auto_panel")
            if auto_panel_cfg is not None:
                new_layer["repeat_config"]["auto_panel"] = auto_panel_cfg

            enhanced["layers"].append(new_layer)

            if isinstance(auto_panel_cfg, dict) and auto_panel_cfg.get("enabled"):
                panel_id = auto_panel_cfg["id"]
                panel_d = dl.get(panel_id, {})
                if "detected" in panel_d:
                    pdet = panel_d["detected"]
                    panel_layout = {
                        "x": pdet["x"], "y": pdet["y"],
                        "width": pdet["width"], "height": pdet["height"],
                    }
                    # Validate panel bbox against cells before using it for the
                    # parent container.  Template matching can lock onto the
                    # panel's inner dark texture rather than the true border,
                    # producing a bbox that mis-aligns with the cells detected
                    # by periodicity.  If the panel center deviates from the
                    # cell-bbox center by more than ~30 % of the panel size,
                    # we trust the cells (and original area_layout) for the
                    # container position, but still keep the panel layer at
                    # its detected position.
                    use_panel_for_parent = True
                    if cells:
                        min_cx = min(c["x"] for c in cells)
                        min_cy = min(c["y"] for c in cells)
                        max_cx = max(c["x"] + c["width"] for c in cells)
                        max_cy = max(c["y"] + c["height"] for c in cells)
                        cell_cx = (min_cx + max_cx) / 2
                        cell_cy = (min_cy + max_cy) / 2
                        panel_cx = pdet["x"] + pdet["width"] / 2
                        panel_cy = pdet["y"] + pdet["height"] / 2
                        max_dev = max(pdet["width"], pdet["height"]) * 0.30
                        if abs(panel_cx - cell_cx) > max_dev or abs(panel_cy - cell_cy) > max_dev:
                            use_panel_for_parent = False
                            print(
                                f"  [WARN] Panel '{panel_id}' center deviates too far from "
                                f"cells bbox (dx={abs(panel_cx - cell_cx):.0f}, dy={abs(panel_cy - cell_cy):.0f}); "
                                f"ignoring panel bbox for parent container layout."
                            )
                    if use_panel_for_parent:
                        if cells:
                            # Shift cells so they align with the detected panel.
                            # grid_periodicity is run against the planned area_layout;
                            # when the planned area_layout is offset from the actual
                            # panel position, the detected cell coordinates inherit
                            # that offset.  Shifting by the delta between panel and
                            # area_layout brings cells into the true container.
                            area = rc.get("area_layout") or _to_preview_rect(layer["layout"])
                            dx = pdet["x"] - area["x"]
                            dy = pdet["y"] - area["y"]
                            for cell in cells:
                                cell["x"] += dx
                                cell["y"] += dy

                            # Container size = panel bbox expanded to enclose all
                            # shifted cells.  This keeps the container tight while
                            # still ensuring every cell is inside.
                            min_cx = min(c["x"] for c in cells)
                            max_cx = max(c["x"] + c["width"] for c in cells)
                            min_cy = min(c["y"] for c in cells)
                            max_cy = max(c["y"] + c["height"] for c in cells)
                            container_layout = {
                                "x": pdet["x"],
                                "y": pdet["y"],
                                "width": max(pdet["width"], max_cx - pdet["x"]),
                                "height": max(pdet["height"], max_cy - pdet["y"]),
                            }

                            # Recompute padding with the aligned cells + container
                            first = cells[0]
                            last = cells[-1]
                            area = container_layout
                            padding = {
                                "top": first["y"] - area["y"],
                                "left": first["x"] - area["x"],
                                "right": (area["x"] + area["width"]) - (last["x"] + last["width"]),
                                "bottom": (area["y"] + area["height"]) - (last["y"] + last["height"]),
                            }
                            rc["padding"] = padding
                        else:
                            # No cells detected — trust the panel bbox alone
                            container_layout = {
                                "x": pdet["x"],
                                "y": pdet["y"],
                                "width": pdet["width"],
                                "height": pdet["height"],
                            }
                        new_layer["layout"] = container_layout
                        rc["area_layout"] = container_layout
                else:
                    panel_layout = dict(new_layer["layout"])

                panel_layer = {
                    "id": panel_id,
                    "name": auto_panel_cfg.get("name", panel_id),
                    "content": "",
                    "status": "active",
                    "layout": panel_layout,
                    "source": _find_source(panel_id),
                    "opacity": auto_panel_cfg.get("opacity", 0.95),
                    "is_repeat_panel": True,
                    "repeat_parent_id": layer_id,
                }
                enhanced["layers"].append(panel_layer)

            for cell in cells:
                cell_id = f"{layer_id}_cell_{cell['row']}_{cell['col']}"
                cell_layer = {
                    "id": cell_id,
                    "name": f"{layer.get('name', layer_id)} ({cell['row']+1},{cell['col']+1})",
                    "content": "",
                    "status": "active",
                    "layout": {
                        "x": cell["x"], "y": cell["y"],
                        "width": cell["width"], "height": cell["height"],
                    },
                    "source": _find_source(layer_id),
                    "opacity": 1.0,
                    "is_repeat_instance": True,
                    "parent_id": layer_id,
                    "repeat_mode": layer["repeat_mode"],
                    "cell_index": cell["row"] * layer.get("repeat_config", {}).get("cols", 1) + cell["col"],
                    "cell_row": cell["row"],
                    "cell_col": cell["col"],
                }
                enhanced["layers"].append(cell_layer)
        else:
            new_layer["source"] = _find_source(layer_id)
            enhanced["layers"].append(new_layer)

    for layer in enhanced["layers"]:
        if not layer.get("is_repeat_parent"):
            enhanced["stacking_order"].append(layer.get("name", layer["id"]))

    for layer in layer_plan.get("layers", []):
        if layer.get("repeat_mode"):
            rc = layer.get("repeat_config", {})
            enhanced["repeat_meta"].append({
                "parent_id": layer["id"],
                "parent_name": layer.get("name", layer["id"]),
                "repeat_mode": layer["repeat_mode"],
                "repeat_config": rc,
                "instance_count": len([
                    l for l in enhanced["layers"]
                    if l.get("parent_id") == layer["id"]
                ]),
                "has_panel": "auto_panel" in layer,
                "panel_id": layer.get("auto_panel", {}).get("id") if "auto_panel" in layer else None,
                "panel_name": layer.get("auto_panel", {}).get("name") if "auto_panel" in layer else None,
            })

    return enhanced


def main():
    parser = argparse.ArgumentParser(description="Detect layer positions via template matching")
    parser.add_argument("--project", "-p", required=True)
    parser.add_argument("--config", "-c", default="config.json")
    parser.add_argument("--preview", "-i", required=True, help="Path to preview image")
    parser.add_argument("--phase", choices=["rough", "check", "refinement"], default="rough")
    parser.add_argument("--output", "-o", help="Output JSON path (default: 04-check/detected_layouts.json)")
    parser.add_argument("--scales", type=float, nargs="+", default=None,
                        help="Custom scale factors to try")
    parser.add_argument("--layer", "-l", action="append", default=None,
                        help="Detect only specific layer(s) by id or name. Can be used multiple times.")
    parser.add_argument("--force", action="store_true",
                        help="Force detection on all requested layers, skipping opacity/background/repeat safety checks. "
                             "Use only when the user explicitly requests it.")
    parser.add_argument("--profile", default=None,
                        help="Matching profile: preset name (default, structure_heavy, color_heavy, texture_heavy) "
                             "or path to a JSON profile file. Auto-detects match_profile.json in output dir if omitted.")
    parser.add_argument("--visualize", "-v", action="store_true",
                        help="Generate a visualization image after detection showing planned (red) vs detected (green/yellow) positions.")
    args = parser.parse_args()

    # Default output path
    if args.output:
        output_path = Path(args.output)
    else:
        pm = PathManager(args.project, config_path=args.config)
        output_path = pm.get_phase_dir("check") / "detected_layouts.json"

    filter_msg = f", layers={args.layer}" if args.layer else ", all layers"
    print(f"[DETECT] Project: {args.project}")
    print(f"[DETECT] Preview: {args.preview}")
    print(f"[DETECT] Phase: {args.phase}{filter_msg}")
    print("-" * 60)

    result = detect_all_layers(
        args.project, args.preview, args.phase,
        config_path=args.config, scales=args.scales,
        layer_filter=args.layer,
        force=args.force,
        profile=args.profile,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    detected_count = sum(
        1 for r in result["layers"].values()
        if r["method"] in ("template_match", "grid_periodicity", "list_periodicity")
        or r["method"].endswith("_periodicity_cell")
    )
    total_count = len(result["layers"])
    print("-" * 60)
    print(f"[DONE] {detected_count}/{total_count} layers matched successfully")
    print(f"[SAVE] {output_path}")

    # Auto-generate enhanced_layer_plan.json in preview coordinates
    try:
        pm = PathManager(args.project, config_path=args.config)
        layer_plan_path = pm.get_layer_plan_path()
        with open(layer_plan_path, "r", encoding="utf-8-sig") as f:
            layer_plan = json.load(f)
        enhanced = _build_enhanced_layer_plan(layer_plan, result, pm)
        enhanced_path = output_path.parent / "enhanced_layer_plan.json"
        with open(enhanced_path, "w", encoding="utf-8") as f:
            json.dump(enhanced, f, indent=2, ensure_ascii=False)
        print(f"[SAVE] {enhanced_path}")
    except Exception as e:
        print(f"[WARN] Failed to generate enhanced_layer_plan: {e}")

    if args.visualize:
        try:
            viz_path = output_path.parent / f"detection_viz_{output_path.stem}.png"
            out = draw_layout_viz(
                preview_path=Path(args.preview),
                detected_path=output_path,
                output_path=viz_path,
                layer_filter=args.layer,
            )
            print(f"[VIZ]  {out}")
        except Exception as e:
            print(f"[VIZ]  Visualization failed: {e}")


if __name__ == "__main__":
    main()
