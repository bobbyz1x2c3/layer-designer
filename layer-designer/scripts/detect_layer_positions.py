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


# Search scales around the planned size to handle crop_to_content drift
DEFAULT_SCALES = [0.65, 0.75, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.20, 1.30, 1.35]

# ROI expands planned size by this factor on each side (3.5 = ±250% margin)
ROI_FACTOR = 3.5

# Downsample factor for fast coarse matching
DOWNSAMPLE = 4

# Fine-search radius in original pixels around coarse match
FINE_RADIUS = 12

# SSD threshold: if best SSD is above this * template_pixels, treat as low confidence
SSD_CONFIDENCE_THRESHOLD = 20000.0  # per-pixel squared error tolerance (AI gen variance)


def _get_detection_config(config_path: str | None) -> dict:
    """Load detection settings from config.json with fallback defaults."""
    defaults = {
        "warn_offset_threshold": 0.30,
        "ssd_confidence_threshold": 20000.0,
        "roi_factor": 3.5,
        "search_scales": DEFAULT_SCALES,
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


def _match_scale(roi_rgb: np.ndarray, tpl_rgb: np.ndarray, tpl_alpha: np.ndarray,
                   downsample: int = 4, fine_radius: int = 12) -> tuple:
    """Match a single-scale template inside ROI. Returns (best_y, best_x, best_ssd, valid_pixels)."""
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
    tpl_d = _downsample(tpl_rgb * weight, downsample)
    # Alpha also downsampled for proper weighting (squeeze to 2D)
    w_d = _downsample(weight, downsample).squeeze()

    Hd, Wd = roi_d.shape[:2]
    hd, wd = tpl_d.shape[:2]
    if hd > Hd or wd > Wd:
        return None, None, float("inf"), 0

    # Fast SSD via strided sliding window on downsampled images
    from numpy.lib.stride_tricks import sliding_window_view

    ssd = np.zeros((Hd - hd + 1, Wd - wd + 1), dtype=np.float64)
    for c in range(3):
        patches = sliding_window_view(roi_d[:, :, c], (hd, wd))  # (h_out, w_out, hd, wd)
        # Both patch and template are multiplied by alpha so transparent
        # regions contribute exactly zero.
        diff = patches.astype(np.float64) * w_d - tpl_d[:, :, c].astype(np.float64)
        ssd += (diff ** 2).sum(axis=(2, 3))

    # Best coarse position (minimum SSD)
    cy_d, cx_d = np.unravel_index(np.argmin(ssd), ssd.shape)
    coarse_ssd = ssd[cy_d, cx_d]

    # --- Fine refinement at original resolution ---
    cy = cy_d * downsample
    cx = cx_d * downsample

    y_start = max(0, cy - fine_radius)
    y_end = min(H - h + 1, cy + fine_radius + 1)
    x_start = max(0, cx - fine_radius)
    x_end = min(W - w + 1, cx + fine_radius + 1)

    best_y, best_x = cy, cx
    best_ssd = float("inf")

    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            patch = roi_rgb[y:y + h, x:x + w]
            # Alpha-weighted diff: transparent pixels contribute exactly 0
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
) -> dict:
    """Detect a single layer's position via multi-scale template matching.

    Semitransparent layers (opacity < 0.85) are skipped because the preview
    shows a blended color (foreground + background) while the extracted
    layer is opaque, making pixel-level matching unreliable.
    """
    import math
    px = planned_layout.get("x", 0)
    py = planned_layout.get("y", 0)
    pw = planned_layout.get("width", canvas_w)
    ph = planned_layout.get("height", canvas_h)

    # Skip semitransparent layers — template vs preview color mismatch
    if opacity < 0.85:
        return {
            "detected": {"x": px, "y": py, "width": pw, "height": ph},
            "planned": {"x": px, "y": py, "width": pw, "height": ph},
            "ssd": 0.0,
            "scale": 1.0,
            "method": "skipped_semitransparent",
            "reason": f"opacity={opacity:.2f} < 0.85",
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

    best_result = None
    best_ssd = float("inf")
    best_scale = 1.0
    best_valid_pixels = 1

    for s in scales:
        target_w = max(1, int(pw * s))
        target_h = max(1, int(ph * s))

        # Resize template to target scale
        tpl_resized = np.array(
            Image.fromarray(tpl_rgb.astype(np.uint8)).resize((target_w, target_h), Image.LANCZOS),
            dtype=np.float32,
        )
        alpha_resized = np.array(
            Image.fromarray((tpl_alpha * 255).astype(np.uint8)).resize((target_w, target_h), Image.LANCZOS),
            dtype=np.float32,
        ) / 255.0

        # Clamp alpha: values below 0.02 treated as fully transparent
        alpha_resized[alpha_resized < 0.02] = 0.0

        # If almost all transparent, skip this scale
        if alpha_resized.sum() < 10:
            continue

        match_result = _match_scale(roi_rgb, tpl_resized, alpha_resized, downsample=downsample, fine_radius=fine_radius)
        if match_result[0] is None:
            continue
        my, mx, ssd_val, valid_pixels = match_result

        # Cross-scale comparison: normalize by TOTAL pixels + penalties
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
    }


def detect_all_layers(
    project_name: str,
    preview_path: str,
    phase: str = "rough",
    config_path: str | None = None,
    scales: list[float] | None = None,
) -> dict:
    """Run detection for all non-background layers."""
    pm = PathManager(project_name, config_path=config_path)
    det_cfg = _get_detection_config(config_path)

    # Read layer plan
    layer_plan_path = pm.get_layer_plan_path()
    if not layer_plan_path.exists():
        raise FileNotFoundError(f"layer_plan.json not found: {layer_plan_path}")

    with open(layer_plan_path, "r", encoding="utf-8") as f:
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

    scales = scales or det_cfg.get("search_scales", DEFAULT_SCALES)
    roi_factor = det_cfg.get("roi_factor", 3.5)
    ssd_threshold = det_cfg.get("ssd_confidence_threshold", 20000.0)
    downsample = det_cfg.get("downsample", 4)
    fine_radius = det_cfg.get("fine_radius", 12)
    results = {}

    layers = layer_plan.get("layers", [])
    for layer_info in layers:
        if layer_info.get("is_background", False):
            continue

        layer_id = layer_info.get("id", "") or layer_info.get("name", "")
        if not layer_id:
            continue

        layer_dir = layer_root / layer_id
        if not layer_dir.exists():
            print(f"  [SKIP] {layer_id}: directory not found")
            continue

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
            print(f"  [SKIP] {layer_id}: no PNG found")
            continue

        raw_planned = layer_info.get("layout", {})
        planned = {
            "x": int(round(raw_planned.get("x", 0) * layout_scale_x * scale_x)),
            "y": int(round(raw_planned.get("y", 0) * layout_scale_y * scale_y)),
            "width": int(round(raw_planned.get("width", canvas_w) * layout_scale_x * scale_x)),
            "height": int(round(raw_planned.get("height", canvas_h) * layout_scale_y * scale_y)),
        }
        print(f"  [DETECT] {layer_id}: {png_path.name} @ planned {planned}")

        layer_opacity = layer_info.get("opacity", 1.0)
        result = detect_layer(
            layer_id, png_path, preview_rgb, planned,
            canvas_w, canvas_h, scales,
            roi_factor=roi_factor,
            ssd_threshold=ssd_threshold,
            downsample=downsample,
            fine_radius=fine_radius,
            opacity=layer_opacity,
        )
        results[layer_id] = result
        print(f"    → {result['method']}: detected={result['detected']}, ssd={result['ssd']}, scale={result['scale']}")

    return {
        "project": project_name,
        "preview_source": preview_path,
        "canvas_size": {"width": canvas_w, "height": canvas_h},
        "scales": scales,
        "layers": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Detect layer positions via template matching")
    parser.add_argument("--project", "-p", required=True)
    parser.add_argument("--config", "-c", default="config.json")
    parser.add_argument("--preview", "-i", required=True, help="Path to preview image")
    parser.add_argument("--phase", choices=["rough", "check", "refinement"], default="rough")
    parser.add_argument("--output", "-o", help="Output JSON path (default: 04-check/detected_layouts.json)")
    parser.add_argument("--scales", type=float, nargs="+", default=None,
                        help="Custom scale factors to try (default: 0.8 0.9 0.95 1.0 1.05 1.1 1.2)")
    args = parser.parse_args()

    # Default output path
    if args.output:
        output_path = Path(args.output)
    else:
        pm = PathManager(args.project, config_path=args.config)
        output_path = pm.get_phase_dir("check") / "detected_layouts.json"

    print(f"[DETECT] Project: {args.project}")
    print(f"[DETECT] Preview: {args.preview}")
    print(f"[DETECT] Phase: {args.phase}")
    print("-" * 60)

    result = detect_all_layers(
        args.project, args.preview, args.phase,
        config_path=args.config, scales=args.scales,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    detected_count = sum(1 for r in result["layers"].values() if r["method"] == "template_match")
    total_count = len(result["layers"])
    print("-" * 60)
    print(f"[DONE] {detected_count}/{total_count} layers matched successfully")
    print(f"[SAVE] {output_path}")


if __name__ == "__main__":
    main()
