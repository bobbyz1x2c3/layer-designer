#!/usr/bin/env python3
"""
Crop a PNG image to its content bounding box using the alpha channel.

For layers with extreme aspect ratios, rembg/u2net may output a canvas whose
aspect ratio is capped at max_ratio (e.g. 3:1). The actual element, however,
keeps its original proportions and sits in the middle of the canvas with
transparent padding. This script detects the non-transparent pixel bounds and
crops the image to the tightest rectangle that contains all visible content.

Usage:
    python crop_to_content.py --input layer.png --output layer_cropped.png
    python crop_to_content.py --input layer.png --output layer_cropped.png --padding 10
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def crop_to_content(image_path: str, output_path: str, padding: int = 0) -> dict:
    """
    Crop image to the bounding box of non-transparent pixels.

    Args:
        image_path: Input PNG path
        output_path: Output PNG path
        padding: Extra pixels to keep around the content (default 0)

    Returns:
        dict with success, original_size, cropped_size, bbox, output_path
    """
    path = Path(image_path)
    if not path.exists():
        return {"error": f"File not found: {image_path}", "success": False}

    try:
        img = Image.open(image_path)
    except Exception as e:
        return {"error": str(e), "success": False}

    if img.mode not in ("RGBA", "LA", "P"):
        # Convert to RGBA if no alpha channel
        img = img.convert("RGBA")

    # Get alpha channel
    if img.mode == "RGBA":
        alpha = np.array(img.getchannel("A"))
    elif img.mode == "LA":
        alpha = np.array(img.getchannel("A"))
    elif img.mode == "P":
        img_rgba = img.convert("RGBA")
        alpha = np.array(img_rgba.getchannel("A"))
    else:
        return {"error": f"Unsupported mode: {img.mode}", "success": False}

    # Find non-transparent pixels (alpha > 0)
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)

    if not np.any(rows) or not np.any(cols):
        return {
            "success": False,
            "error": "Image is fully transparent — nothing to crop.",
            "original_size": img.size,
        }

    top = np.argmax(rows)
    bottom = len(rows) - np.argmax(rows[::-1])
    left = np.argmax(cols)
    right = len(cols) - np.argmax(cols[::-1])

    # Apply padding
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)

    # PIL crop() requires (left, top, right, bottom) — keep this for the actual crop op
    bbox_xyxy = (int(left), int(top), int(right), int(bottom))
    cropped = img.crop(bbox_xyxy)

    # Returned bbox is (x, y, width, height) so consumers don't have to subtract corners
    bbox = (int(left), int(top), int(right - left), int(bottom - top))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cropped.save(output_path)

    return {
        "success": True,
        "original_size": (int(img.width), int(img.height)),
        "cropped_size": (int(cropped.width), int(cropped.height)),
        "bbox": bbox,
        "output_path": output_path,
    }


def main():
    parser = argparse.ArgumentParser(description="Crop PNG to content bounding box via alpha channel")
    parser.add_argument("--input", "-i", required=True, help="Input PNG image path")
    parser.add_argument("--output", "-o", required=True, help="Output PNG image path")
    parser.add_argument("--padding", "-p", type=int, default=0, help="Padding around content in pixels (default 0)")
    parser.add_argument("--meta-output", "-m", help="Optional path to write crop metadata JSON (e.g., layer_meta.json)")
    args = parser.parse_args()

    result = crop_to_content(args.input, args.output, padding=args.padding)

    # Persist metadata if requested
    if args.meta_output and result.get("success"):
        import json
        meta = {
            "original_size": result["original_size"],
            "cropped_size": result["cropped_size"],
            "crop_bbox": result["bbox"],
            "padding": args.padding,
        }
        Path(args.meta_output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.meta_output, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    print(result)

    if result.get("error"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
