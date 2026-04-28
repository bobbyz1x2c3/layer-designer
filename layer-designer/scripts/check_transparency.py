#!/usr/bin/env python3
"""
Check if a PNG image has real transparent background or a solid-color background
that should be treated as transparent (common with AI-generated images that output
RGB mode with white/light fills instead of true alpha).

Optionally remove the solid background via auto-matting and save as true RGBA PNG.

Workflow phase where this script is invoked:
- Phase 4 (Rough Design Check): run on every non-background layer to verify
  real alpha transparency before compositing.

Returns exit code 0 if transparent pixels exist (or solid background detected),
1 if fully opaque or not PNG.
Prints JSON with details to stdout.

Usage:
    # Check only
    python check_transparency.py --config ../config.json --image input.png

    # Check + auto-remove solid background if detected
    python check_transparency.py --image input.png --remove-bg --output input_rgba.png
"""

import argparse
import json
import random
import sys
from pathlib import Path

from config_loader import load_config, get_transparency_config, get_matting_config

try:
    from PIL import Image
except ImportError:
    print(json.dumps({"error": "Pillow not installed. Run: pip install Pillow"}), file=sys.stderr)
    sys.exit(1)


def _sample_pixels(img: Image.Image, count: int = 2000) -> list:
    """Randomly sample pixel values from the image."""
    width, height = img.size
    pixels = img.load()
    total = width * height
    count = min(count, total)
    if count <= total // 2:
        coords = random.sample([(x, y) for x in range(width) for y in range(height)], count)
    else:
        coords = [(random.randrange(width), random.randrange(height)) for _ in range(count)]
    return [pixels[x, y] for x, y in coords]


def _detect_large_foreground(img: Image.Image, stage1_ratio: float = 0.70) -> tuple[tuple[int, ...], float]:
    """Detect if the foreground dominates the image.

    Samples edge pixels (narrow border) to estimate background color,
    then counts how many pixels differ significantly from that color.

    Args:
        img: Input image
        border_ratio: Fraction of width/height to use as edge border.
                      Default 0.02 (2%) — small enough to avoid sampling
                      the foreground itself when it dominates the image.

    Returns:
        (edge_color_tuple, foreground_ratio)
    """
    width, height = img.size
    # Convert to RGB for uniform handling
    rgb = img.convert("RGB")
    pixels = rgb.load()

    # Sample edge pixels: narrow border (default 2%)
    edge_pixels = []
    border_ratio = max(0.01, 0.4 * (1 - stage1_ratio))
    border_x = max(1, int(width * border_ratio))
    border_y = max(1, int(height * border_ratio))
    for y in range(height):
        for x in range(width):
            if x < border_x or x >= width - border_x or y < border_y or y >= height - border_y:
                edge_pixels.append(pixels[x, y])

    if not edge_pixels:
        return ((255, 255, 255), 1.0)

    # Average edge color
    r = sum(p[0] for p in edge_pixels) // len(edge_pixels)
    g = sum(p[1] for p in edge_pixels) // len(edge_pixels)
    b = sum(p[2] for p in edge_pixels) // len(edge_pixels)
    edge_color = (r, g, b)

    # Count pixels that differ significantly from edge color
    diff_threshold = 30  # RGB delta threshold
    different_count = 0
    sample_step = max(1, (width * height) // 2000)
    for y in range(0, height, sample_step):
        for x in range(0, width, sample_step):
            p = pixels[x, y]
            delta = abs(p[0] - r) + abs(p[1] - g) + abs(p[2] - b)
            if delta > diff_threshold:
                different_count += 1

    total_samples = ((width + sample_step - 1) // sample_step) * ((height + sample_step - 1) // sample_step)
    fg_ratio = different_count / total_samples if total_samples > 0 else 1.0
    return (edge_color, fg_ratio)


def remove_background(image_path: str, output_path: str, matting_config: dict | None = None, auto_pad: bool = True) -> dict:
    """
    Auto-matte: remove background using rembg (configurable deep-learning model).

    The ONNX model is loaded from the skill's internal models/ directory
    (relative to this script's location), not from the user's home directory.
    Supported models depend on the installed rembg version; common choices:
    "u2net", "birefnet-general", "birefnet-general-lite", "birefnet-portrait", etc.

    Args:
        image_path: Input image path
        output_path: Output RGBA PNG path
        matting_config: Optional matting configuration dict from get_matting_config()

    Returns:
        dict with success, transparent_pixels, output_path
    """
    import os
    import numpy as np
    from pathlib import Path

    # Point rembg to the skill-internal models directory
    script_dir = Path(__file__).parent.resolve()
    model_dir = script_dir.parent / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(model_dir)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    cfg = matting_config or {}
    model_name = cfg.get("model", "u2net")
    model_file = cfg.get("model_file", "")
    alpha_matting = cfg.get("alpha_matting", True)
    fg_threshold = cfg.get("alpha_matting_foreground_threshold", 240)
    bg_threshold = cfg.get("alpha_matting_background_threshold", 10)
    erode_size = cfg.get("alpha_matting_erode_size", 10)

    # If user specified a custom model_file, create a hard link so rembg can find it
    expected_path = model_dir / f"{model_name}.onnx"
    if model_file and not expected_path.exists():
        custom_path = model_dir / model_file
        if custom_path.exists():
            try:
                os.link(str(custom_path), str(expected_path))
                print(f"[OK] Linked {model_file} -> {model_name}.onnx")
            except Exception as e:
                print(f"[WARNING] Could not link model file: {e}")
        else:
            print(f"[WARNING] Configured model_file not found: {custom_path}")

    from rembg import remove, new_session

    original_img = Image.open(image_path)
    original_size = original_img.size
    total_pixels = original_size[0] * original_size[1]

    def _matte(img: Image.Image) -> Image.Image:
        """Run rembg on a Pillow image and return RGBA result."""
        session = new_session(model_name)
        return remove(
            img,
            session=session,
            alpha_matting=alpha_matting,
            alpha_matting_foreground_threshold=fg_threshold,
            alpha_matting_background_threshold=bg_threshold,
            alpha_matting_erode_size=erode_size,
        )

    def _count_transparent(img: Image.Image) -> int:
        """Count fully transparent pixels (alpha == 0)."""
        alpha = np.array(img.getchannel("A"))
        return int(np.sum(alpha == 0))

    def _pad_and_matte_square(img: Image.Image, long_edge_ratio: float, edge_color):
        """Pad to a square where the long edge is expanded by the given ratio.
        The short edge is padded to match the new long edge length.
        Then matte and crop back to original size."""
        w, h = original_size
        long_edge = max(w, h)
        new_size = int(long_edge * (1 + long_edge_ratio))
        # Ensure square is large enough for both dimensions
        new_size = max(new_size, w, h)

        pad_left = (new_size - w) // 2
        pad_top = (new_size - h) // 2

        padded_img = Image.new(img.mode, (new_size, new_size), edge_color)
        padded_img.paste(img, (pad_left, pad_top))

        result = _matte(padded_img)
        crop_x = (result.width - w) // 2
        crop_y = (result.height - h) // 2
        return result.crop((crop_x, crop_y, crop_x + w, crop_y + h))

    # --- Stage 1: Normal matting ---
    result_stage1 = _matte(original_img)
    stage1_transparent = _count_transparent(result_stage1)
    stage1_ratio = stage1_transparent / total_pixels
    transparent_count = stage1_transparent
    transparent_ratio = stage1_ratio
    padded = False
    skipped = False

    method_name = f"rembg_{model_name}"
    if alpha_matting:
        method_name += "_alpha_matting"

    # --- Stage 2: square padding (long edge +40%) retry if >85% transparent ---
    if auto_pad and stage1_ratio > 0.85:
        edge_color, _ = _detect_large_foreground(original_img, stage1_ratio)
        result_stage2 = _pad_and_matte_square(original_img, 0.40, edge_color)
        stage2_transparent = _count_transparent(result_stage2)
        stage2_ratio = stage2_transparent / total_pixels
        padded = True

        # Save both stage results for manual inspection
        base_path = Path(output_path).with_suffix("")
        stage1_path = str(base_path) + "_stage1.png"
        stage2_path = str(base_path) + "_stage2.png"
        result_stage1.save(stage1_path)
        result_stage2.save(stage2_path)

        # Default output: stage1 result (preserves downstream compatibility)
        result_stage1.save(output_path)

        return {
            "success": True,
            "method": method_name,
            "warning": (
                f"High transparent ratio detected (stage1={stage1_ratio:.2%}). "
                f"Both stage1 ({stage1_ratio:.2%} transparent) and stage2 ({stage2_ratio:.2%} transparent) "
                f"matte results saved. Please manually inspect and choose the better output. "
                f"Stage1: {stage1_path} | Stage2: {stage2_path}"
            ),
            "stage1_ratio": round(stage1_ratio, 4),
            "stage2_ratio": round(stage2_ratio, 4),
            "output_path": output_path,
            "stage1_path": stage1_path,
            "stage2_path": stage2_path,
            "padded": True,
            "skipped": False,
            "transparent_pixels": stage1_transparent,
            "transparent_ratio": round(stage1_ratio, 4),
        }

    # Normal path: save stage1 result directly
    result_stage1.save(output_path)

    return {
        "success": True,
        "method": method_name,
        "transparent_pixels": stage1_transparent,
        "output_path": output_path,
        "padded": False,
        "skipped": False,
        "transparent_ratio": round(stage1_ratio, 4),
    }


def check_transparency(image_path: str, threshold: int = 10, sample_rate: float = 1.0):
    """
    Check if image has transparent pixels or a solid-color background.

    Two detection strategies:
    1. RGBA mode: random sample pixels, count alpha==0. If >= 2, transparent.
    2. RGB/L/P mode (fallback): random sample pixels, detect if background is
       a near-uniform light color (typical of AI-generated images without alpha).
       If >50% of sampled pixels are nearly identical and light-colored,
       treat as "has transparent background".

    Args:
        image_path: Path to image file
        threshold: Legacy param (ignored); kept for CLI compat
        sample_rate: Legacy param (ignored); kept for CLI compat

    Returns:
        dict with has_transparency, transparent_pixels, width, height, mode
    """
    path = Path(image_path)
    if not path.exists():
        return {"error": f"File not found: {image_path}", "has_transparency": False}

    try:
        img = Image.open(image_path)
    except Exception as e:
        return {"error": str(e), "has_transparency": False}

    if img.format != "PNG":
        return {
            "error": f"Not a PNG file (format: {img.format})",
            "has_transparency": False,
            "format": img.format,
        }

    width, height = img.size
    original_mode = img.mode

    # ------------------------------------------------------------------
    # Strategy 1: RGBA mode — check for alpha=0 pixels via random sampling
    # ------------------------------------------------------------------
    if img.mode == "RGBA":
        pixels = img.load()
        total = width * height
        sample_count = min(2000, total)
        transparent_count = 0
        for _ in range(sample_count):
            x = random.randrange(width)
            y = random.randrange(height)
            r, g, b, a = pixels[x, y]
            if a == 0:
                transparent_count += 1
                if transparent_count >= 2:
                    break

        has_transparency = transparent_count >= 2
        result = {
            "has_transparency": has_transparency,
            "transparent_pixels": transparent_count,
            "sampled_pixels": sample_count,
            "width": width,
            "height": height,
            "mode": original_mode,
            "format": "PNG",
            "detection_method": "alpha_sampling",
        }
        if not has_transparency:
            result["recommend_matte"] = False
            result["message"] = "Image is RGBA but has no fully transparent pixels (alpha==0). The API endpoint did not output a true transparent PNG."
        return result

    # ------------------------------------------------------------------
    # Strategy 2: RGB/L/P mode — no background color detection.
    # We skip the unreliable light/uniform heuristics (proven to fail on
    # dark backgrounds and large foregrounds) and always recommend rembg.
    # ------------------------------------------------------------------
    if img.mode in ("L", "RGB", "P"):
        return {
            "has_transparency": False,
            "width": width,
            "height": height,
            "mode": original_mode,
            "format": "PNG",
            "detection_method": "no_alpha",
            "recommend_matte": True,
            "message": "Image has no alpha channel. Use --remove-bg to auto-remove background via rembg.",
        }

    return {
        "has_transparency": False,
        "error": f"Unsupported image mode: {img.mode}",
        "width": width,
        "height": height,
        "mode": original_mode,
        "format": "PNG",
    }


def main():
    parser = argparse.ArgumentParser(description="Check PNG transparency")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--image", "-i", required=True, help="Input PNG image path")
    parser.add_argument("--threshold", "-t", type=int, default=None,
                        help="Alpha threshold (legacy, ignored)")
    parser.add_argument("--sample-rate", "-s", type=float, default=None,
                        help="Sampling rate (legacy, ignored)")
    parser.add_argument("--remove-bg", action="store_true",
                        help="Auto-remove solid background and save as RGBA PNG")
    parser.add_argument("--output", "-o", help="Output path for --remove-bg result")
    parser.add_argument("--tolerance", type=int, default=20,
                        help="Background removal tolerance (0-255), default 20")
    parser.add_argument("--auto-crop", action="store_true",
                        help="After background removal, crop image to content bounding box (for extreme-ratio layers)")
    parser.add_argument("--crop-padding", type=int, default=0,
                        help="Padding in pixels when auto-cropping (default 0)")
    parser.add_argument("--pad", action="store_true",
                        help="Force padding mode for large-foreground images before matting")
    parser.add_argument("--no-pad", action="store_true",
                        help="Disable auto-padding for large-foreground images")
    args = parser.parse_args()

    # Load config defaults
    threshold = args.threshold
    sample_rate = args.sample_rate
    matting_cfg = {}
    if args.config or (threshold is None or sample_rate is None):
        try:
            config = load_config(args.config)
            cfg = get_transparency_config(config)
            if threshold is None:
                threshold = cfg.get("threshold", 10)
            if sample_rate is None:
                sample_rate = cfg.get("sample_rate", 1.0)
            matting_cfg = get_matting_config(config)
        except Exception:
            if threshold is None:
                threshold = 10
            if sample_rate is None:
                sample_rate = 1.0
    else:
        try:
            matting_cfg = get_matting_config(load_config(args.config))
        except Exception:
            pass

    # 1. Run transparency check
    result = check_transparency(args.image, threshold=threshold, sample_rate=sample_rate)

    # 2. Auto-remove background if requested
    #    When --remove-bg is explicitly passed, always attempt rembg regardless of
    #    detection result. This is an optional best-effort optimization, not a
    #    mandatory requirement. Even if no solid background was detected, rembg
    #    may still produce usable results on complex backgrounds.
    if args.remove_bg:
        output_path = args.output
        if not output_path:
            p = Path(args.image)
            output_path = str(p.with_suffix("")) + "_rgba.png"

        auto_pad = True
        if args.pad:
            auto_pad = True
        elif args.no_pad:
            auto_pad = False
        matte_result = remove_background(args.image, output_path, matting_cfg, auto_pad=auto_pad)
        result["matte"] = matte_result
        # Override has_transparency since we now have a matte output
        if matte_result.get("transparent_pixels", 0) > 0:
            result["has_transparency"] = True
            result["detection_method"] = "rembg_forced"
            result["note"] = "Background removed via forced rembg (best-effort)"

        # Auto-crop to content bounding box if requested
        if args.auto_crop and matte_result.get("success"):
            crop_output = str(Path(output_path).with_suffix("")) + "_cropped.png"
            try:
                from crop_to_content import crop_to_content
                crop_result = crop_to_content(output_path, crop_output, padding=args.crop_padding)
                result["crop"] = crop_result
                if crop_result.get("success"):
                    result["note"] += "; auto-cropped to content bounding box"
            except Exception as e:
                result["crop_error"] = str(e)

    print(json.dumps(result, indent=2))

    if result.get("error") and not result.get("has_transparency") and not result.get("recommend_matte"):
        sys.exit(1)
    sys.exit(0 if result["has_transparency"] or result.get("recommend_matte") else 1)


if __name__ == "__main__":
    main()
