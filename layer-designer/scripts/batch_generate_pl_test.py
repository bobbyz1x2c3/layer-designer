#!/usr/bin/env python3
"""Batch generate layers for PL1TEST project."""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from path_manager import PathManager


def run_generation(cmd, layer_name):
    """Run a single generation command and return result."""
    print(f"[START] {layer_name}")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            print(f"[DONE]  {layer_name}")
            return (layer_name, True, result.stdout)
        else:
            print(f"[FAIL]  {layer_name}: {result.stderr}")
            return (layer_name, False, result.stderr)
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {layer_name}")
        return (layer_name, False, "timeout")
    except Exception as e:
        print(f"[ERROR] {layer_name}: {e}")
        return (layer_name, False, str(e))


def main():
    ap = argparse.ArgumentParser(description="Batch generate layers for PL1TEST")
    ap.add_argument("--pl-only", action="store_true",
                    help="Only generate layers with precise_layout: true (skip background and non-PL layers).")
    args = ap.parse_args()

    project = "PL1TEST"
    config_path = r"h:\AI-skills\LD\layer-designer\layer-designer\config.json"
    preview_path = r"h:\AI-skills\LD\layer-designer\layer-designer\output\PL1TEST\01-requirements\previews\preview_v3_002.png"
    base_dir = r"h:\AI-skills\LD\layer-designer\layer-designer\output"
    pm = PathManager(project, base_dir=base_dir, config_path=config_path)

    # Load layer plan
    layer_plan_path = pm.get_layer_plan_path()
    with open(layer_plan_path, "r", encoding="utf-8") as f:
        layer_plan = json.load(f)

    style_anchor = layer_plan.get("style_anchor", "")
    layers = layer_plan.get("layers", [])

    if args.pl_only:
        layers = [l for l in layers if l.get("precise_layout", False)]
        print(f"[FILTER] --pl-only: {len(layers)} PL layers selected")

    # Load size plan for early_size
    size_plan_path = pm.get_phase_dir("requirements") / "size_plan.json"
    early_w, early_h = 1280, 720
    if size_plan_path.exists():
        with open(size_plan_path, "r", encoding="utf-8") as f:
            sp = json.load(f)
        early_w = sp.get("early_size", {}).get("width", 1280)
        early_h = sp.get("early_size", {}).get("height", 720)

    commands = []

    for layer in layers:
        layer_id = layer.get("id", "")
        is_bg = layer_id == "background"
        is_pl = layer.get("precise_layout", False)
        layout = layer.get("layout", {})
        description = layer.get("contents", "")
        tier = layer.get("quality_tier", "low")

        # Compute size
        if is_bg:
            size_str = f"{early_w}x{early_h}"
        elif is_pl:
            size_str = f"{early_w}x{early_h}"
        else:
            lw = layout.get("width", 2560)
            lh = layout.get("height", 1440)
            cw, ch = PathManager.compute_layer_size(lw, lh)
            size_str = f"{cw}x{ch}"

        # Build prompt
        base = f"Extract ONLY the {layer_id}. {description}."
        if layer.get("opacity", 1.0) < 1.0:
            base += " This element sits on top of a background in the full design. When extracting it, preserve the element's own intrinsic colors and texture cleanly — do NOT blend background colors into the element. The element should retain its intended solid appearance with pure, unmixed colors."

        if is_bg:
            prompt = (
                f"From this UI design, extract ONLY the background layer. "
                f"Include: {description}. Full canvas filled completely. "
                f"NO transparent areas. NO UI elements, NO buttons, NO text, NO icons, NO overlays. "
                f"Only the pure background fill, texture, gradient, or environment. {style_anchor}."
            )
        elif is_pl:
            prompt = (
                f"Extract ONLY the {layer_id} from the source reference image. {description}. {style_anchor}. "
                f"CRITICAL: Preserve the element EXACTLY as it appears in the source reference image — "
                f"same position, same size, same proportions. "
                f"Do NOT center the element, do NOT enlarge it, do NOT reposition it. "
                f"The element should occupy the IDENTICAL pixel region it occupies in the source reference. "
                f"All other pixels (where the element does not appear in the source) MUST be fully transparent (alpha=0). "
                f"Output: PNG with alpha channel, same canvas dimensions as the source reference."
            )
        else:
            prompt = (
                f"{base} Transparent background, PNG with alpha channel, only this element isolated. {style_anchor}. "
                f"CRITICAL: STRICTLY maintain the element's original aspect ratio. Do NOT stretch, distort, or change proportions in any way. "
                f"Scale the element proportionally to fit within the canvas while leaving a small transparent margin of approximately 3-5% on each side. "
                f"Do NOT let the element touch or overlap the canvas boundary. This margin ensures clean background removal in post-processing."
            )

        out_dir = pm.get_layer_dir(layer_id)
        out_path = pm.get_layer_path(layer_id)

        cmd = (
            f'python "{Path(__file__).parent / "generate_image.py"}" edit '
            f'--config "{config_path}" '
            f'--image "{preview_path}" '
            f'--prompt "{prompt}" '
            f'--output "{out_path}" '
            f'--size {size_str} '
            f'--quality {tier}'
        )

        commands.append((layer_id, cmd))
        print(f"[PLAN] {layer_id}: size={size_str}, pl={is_pl}, bg={is_bg}")

    # Parallel execution
    max_workers = 3
    print(f"\n[INFO] Submitting {len(commands)} layers with max_workers={max_workers}\n")

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_generation, cmd, name): name
            for name, cmd in commands
        }
        for future in as_completed(futures):
            name = futures[future]
            layer_name, success, output = future.result()
            results[layer_name] = (success, output)

    # Summary
    print("\n" + "=" * 50)
    print("GENERATION SUMMARY")
    print("=" * 50)
    for name, (success, output) in results.items():
        status = "[OK]" if success else "[FAIL]"
        print(f"{status} {name}")
    print("=" * 50)

    failed = [n for n, (s, _) in results.items() if not s]
    if failed:
        print(f"\nFailed layers: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("\nAll layers generated successfully!")


if __name__ == "__main__":
    main()
