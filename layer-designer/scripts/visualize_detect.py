#!/usr/bin/env python3
"""Visualize detected vs planned layouts on preview image."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", "-p", required=True)
    parser.add_argument("--preview", default=None, help="Preview image path")
    args = parser.parse_args()

    proj = args.project
    if args.preview:
        preview_path = Path(args.preview)
    else:
        candidates = sorted(Path(f"output/{proj}/01-requirements/previews").glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        preview_path = candidates[0] if candidates else None

    detected_path = Path(f"output/{proj}/04-check/detected_layouts.json")

    preview = Image.open(preview_path).convert("RGB")
    draw = ImageDraw.Draw(preview)

    with open(detected_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for layer_id, result in data["layers"].items():
        planned = result["planned"]
        detected = result["detected"]

        # Planned: red
        draw.rectangle(
            [planned["x"], planned["y"], planned["x"] + planned["width"], planned["y"] + planned["height"]],
            outline="red",
            width=2,
        )

        # Detected: green
        draw.rectangle(
            [detected["x"], detected["y"], detected["x"] + detected["width"], detected["y"] + detected["height"]],
            outline="lime",
            width=2,
        )

        # Label
        draw.text((detected["x"], max(0, detected["y"] - 10)), layer_id, fill="lime")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(f"output/{proj}/04-check/detection_viz_{timestamp}.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
