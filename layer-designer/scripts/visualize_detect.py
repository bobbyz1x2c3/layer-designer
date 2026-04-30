#!/usr/bin/env python3
"""Visualize detected vs planned layouts on preview image."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# Color scheme per detection method
METHOD_COLORS = {
    "template_match": (0, 255, 0),       # green
    "planned_fallback": (255, 255, 0),   # yellow
    "skipped_semitransparent": (128, 128, 128),  # gray
    "skipped_background": (128, 128, 128),
    "skipped_repeat": (128, 128, 128),
    "skipped_no_dir": (128, 128, 128),
    "skipped_no_png": (128, 128, 128),
}

PLANNED_COLOR = (255, 0, 0)   # red


def _get_font(size: int = 12):
    """Try to get a decent font; fall back to default."""
    for name in ["arial.ttf", "DejaVuSans.ttf", "msyh.ttc"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_layout_viz(
    preview_path: Path,
    detected_path: Path,
    output_path: Path,
    layer_filter: list[str] | None = None,
) -> Path:
    """Draw planned (red) vs detected (colored by method) rectangles on preview.

    Returns the output path.
    """
    preview = Image.open(preview_path).convert("RGB")
    draw = ImageDraw.Draw(preview)
    font = _get_font(11)
    small_font = _get_font(9)

    with open(detected_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    filter_set = {f.lower() for f in layer_filter} if layer_filter else None

    for layer_id, result in data["layers"].items():
        if filter_set and layer_id.lower() not in filter_set:
            continue

        planned = result["planned"]
        detected = result["detected"]
        method = result.get("method", "unknown")
        score = result.get("ssd", 0.0)
        scale = result.get("scale", 1.0)
        reason = result.get("reason", "")

        color = METHOD_COLORS.get(method, (0, 200, 255))

        # Planned: red dashed-like (two rectangles, one thicker semi-transparent)
        draw.rectangle(
            [planned["x"], planned["y"], planned["x"] + planned["width"], planned["y"] + planned["height"]],
            outline=PLANNED_COLOR,
            width=2,
        )

        # Detected: method-colored
        draw.rectangle(
            [detected["x"], detected["y"], detected["x"] + detected["width"], detected["y"] + detected["height"]],
            outline=color,
            width=3,
        )

        # Info label above detected box
        label_y = max(0, detected["y"] - 28)
        label_x = detected["x"]

        # Layer name
        draw.text((label_x, label_y), layer_id, fill=color, font=font)

        # Score / scale / method line
        info_parts = []
        if method == "template_match":
            info_parts.append(f"ssd={score:.0f}")
            info_parts.append(f"s={scale:.2f}")
        elif method.startswith("skipped"):
            info_parts.append(reason)
        else:
            info_parts.append(method)
            if reason:
                info_parts.append(reason)
        info_text = " | ".join(info_parts)
        draw.text((label_x, label_y + 12), info_text, fill=color, font=small_font)

    # Legend
    legend_x = 10
    legend_y = preview.height - 70
    legend_items = [
        (PLANNED_COLOR, "planned"),
        (METHOD_COLORS["template_match"], "matched"),
        (METHOD_COLORS["planned_fallback"], "fallback"),
        (METHOD_COLORS["skipped_background"], "skipped"),
    ]
    for i, (col, text) in enumerate(legend_items):
        draw.rectangle([legend_x + i * 90, legend_y, legend_x + i * 90 + 10, legend_y + 10], fill=col, outline=(255, 255, 255))
        draw.text((legend_x + i * 90 + 14, legend_y - 2), text, fill=(255, 255, 255), font=small_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path, quality=95)
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", "-p", required=True)
    parser.add_argument("--preview", default=None, help="Preview image path")
    parser.add_argument("--input", "-i", default=None, help="Detected layouts JSON path")
    parser.add_argument("--output", "-o", default=None, help="Output visualization path")
    parser.add_argument("--layer", "-l", action="append", default=None,
                        help="Visualize only specific layer(s)")
    args = parser.parse_args()

    proj = args.project
    if args.preview:
        preview_path = Path(args.preview)
    else:
        candidates = sorted(Path(f"output/{proj}/01-requirements/previews").glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        preview_path = candidates[0] if candidates else None

    if args.input:
        detected_path = Path(args.input)
    else:
        detected_path = Path(f"output/{proj}/04-check/detected_layouts.json")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(f"output/{proj}/04-check/detection_viz_{timestamp}.png")

    out = draw_layout_viz(preview_path, detected_path, output_path, layer_filter=args.layer)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
