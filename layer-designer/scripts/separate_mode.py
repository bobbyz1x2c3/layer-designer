#!/usr/bin/env python3
"""
Separate Mode — Optional one-step automation script.

**Primary workflow**: Agents should follow `references/separate-mode.md` step-by-step
to avoid timeouts and enable per-step retry. This script is provided as a convenience
for automation scenarios where all steps can run unattended.

What it does (runs Steps 2–8 from separate-mode.md):
1. Create size_plan.json from reference image dimensions
2. Generate all layers in PL mode from the reference image
3. Run transparency check + rembg matting on all layers
4. Run detect_layer_positions.py for position matching
5. Generate enhanced_layer_plan.json with detected layouts

Usage:
    python scripts/separate_mode.py \
        --config config.json \
        --project my-app \
        --reference-image path/to/reference.png \
        --quality low

For step-by-step execution (recommended), see `references/separate-mode.md`.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Add script directory to path for imports
_script_dir = Path(__file__).parent.resolve()
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from config_loader import load_config
from path_manager import PathManager
import style_loader


def _log(msg: str, *, important: bool = False) -> None:
    """Print a log message."""
    print(msg)


def _run_cmd(cmd: list[str], *, timeout: int = 300, quiet: bool = False) -> tuple[bool, str]:
    """Run a command and return (success, output_or_error)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            if not quiet:
                _log(result.stdout.strip())
            return True, result.stdout
        return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def _get_image_size(image_path: Path) -> tuple[int, int]:
    """Get image dimensions using PIL."""
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return img.size
    except Exception as e:
        _log(f"[ERROR] Cannot read image dimensions: {e}", important=True)
        sys.exit(1)


def create_size_plan(pm: PathManager, config_path: str, img_width: int, img_height: int) -> dict:
    """Create size_plan.json by calling validate_size.py --downsize-ratio 1.0.

    In separate mode, both full_size and early_size equal the reference image
    dimensions (no downscaling). Use --downsize-ratio 1.0 to achieve this.
    """
    _log(f"\n[SIZE] Reference image: {img_width}x{img_height}")

    cmd = [
        sys.executable,
        str(_script_dir / "validate_size.py"),
        "--config", config_path,
        "--project", pm.project_name,
        "--width", str(img_width),
        "--height", str(img_height),
        "--downsize-ratio", "1.0",
    ]

    success, output = _run_cmd(cmd, timeout=30)

    if not success:
        _log(f"[WARN] validate_size.py failed: {output}", important=True)
        _log("[FALLBACK] Creating size_plan manually", important=True)
        # Fallback: create manually
        is_compliant = PathManager.is_size_compliant(img_width, img_height)
        if is_compliant:
            full_w, full_h = img_width, img_height
        else:
            full_w, full_h = PathManager.compute_compliant_size(img_width, img_height)
        plan = {
            "timestamp": datetime.now().isoformat(),
            "user_requested": {"width": img_width, "height": img_height},
            "full_size": {"width": full_w, "height": full_h},
            "early_size": {"width": full_w, "height": full_h},
            "valid": True,
            "separate_mode": True,
        }
        size_plan_path = pm.get_phase_dir("requirements") / "size_plan.json"
        size_plan_path.parent.mkdir(parents=True, exist_ok=True)
        with open(size_plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        return plan

    # Read the generated size_plan.json
    size_plan_path = pm.get_phase_dir("requirements") / "size_plan.json"
    with open(size_plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    _log(f"[OK] Created size_plan.json via validate_size.py")
    _log(f"       full_size:  {plan['full_size']['width']}x{plan['full_size']['height']}")
    _log(f"       early_size: {plan['early_size']['width']}x{plan['early_size']['height']}")
    return plan


def _build_pl_prompt(layer_id: str, description: str, style_anchor: str,
                     opacity: float, style_active: bool = False) -> str:
    """Build PL mode prompt for layer extraction.

    When `style_active` is True, the textual style anchor is NOT inlined here
    because `generate_image.py --style` will prepend the full style block
    (anchor + rules + tagged refs) at subprocess invocation time.
    """
    base = f"Extract ONLY the {layer_id} from the source reference image. {description}."

    if opacity < 1.0:
        base += (
            " This element sits on top of a background in the full design. "
            "When extracting it, preserve the element's own intrinsic colors and texture cleanly "
            "— do NOT blend background colors into the element. "
            "The element should retain its intended solid appearance with pure, unmixed colors."
        )

    anchor_suffix = "" if style_active else f" {style_anchor}."
    prompt = (
        f"{base}{anchor_suffix} "
        f"CRITICAL: Preserve the element EXACTLY as it appears in the source reference image — "
        f"same position, same size, same proportions. "
        f"Do NOT center the element, do NOT enlarge it, do NOT reposition it. "
        f"The element should occupy the IDENTICAL pixel region it occupies in the source reference. "
        f"All other pixels (where the element does not appear in the source) MUST be fully transparent (alpha=0). "
        f"Output: PNG with alpha channel, same canvas dimensions as the source reference."
    )
    return prompt


def _build_bg_prompt(layer_id: str, description: str, style_anchor: str,
                     style_active: bool = False) -> str:
    """Build prompt for background layer extraction.

    When `style_active` is True, the anchor is omitted (added later by
    generate_image.py --style).
    """
    anchor_suffix = "" if style_active else f" {style_anchor}."
    return (
        f"From this UI design, extract ONLY the background layer. "
        f"Include: {description}. Full canvas filled completely. "
        f"NO transparent areas. NO UI elements, NO buttons, NO text, NO icons, NO overlays. "
        f"Only the pure background fill, texture, gradient, or environment.{anchor_suffix}"
    )


def generate_layer(
    layer_info: dict,
    reference_path: str,
    config_path: str,
    pm: PathManager,
    canvas_w: int,
    canvas_h: int,
    quality: str,
    style_dir: str | None = None,
) -> tuple[str, bool, str]:
    """Generate a single layer in PL mode."""
    layer_id = layer_info.get("id", "") or layer_info.get("name", "")
    is_bg = layer_id == "background"
    description = layer_info.get("contents", "") or layer_info.get("description", "")
    style_anchor = layer_info.get("style_anchor", "")
    opacity = layer_info.get("opacity", 1.0)
    control_type = layer_info.get("control_type")
    style_active = style_dir is not None

    # Use full canvas size for all layers in separate mode
    size_str = f"{canvas_w}x{canvas_h}"

    # Build prompt
    if is_bg:
        prompt = _build_bg_prompt(layer_id, description, style_anchor, style_active=style_active)
    else:
        prompt = _build_pl_prompt(layer_id, description, style_anchor, opacity, style_active=style_active)

    out_dir = pm.get_layer_dir(layer_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = pm.get_layer_path(layer_id)

    cmd = [
        sys.executable,
        str(_script_dir / "generate_image.py"),
        "edit",
        "--config", config_path,
        "--image", reference_path,
        "--prompt", prompt,
        "--output", str(out_path),
        "--size", size_str,
        "--quality", quality,
    ]

    if style_active:
        cmd += ["--style-from", style_dir, "--phase", "layer"]
        if control_type:
            cmd += ["--control-type", control_type]

    _log(f"[GEN] {layer_id}: size={size_str}, bg={is_bg}, control_type={control_type}, style={style_active}")
    success, output = _run_cmd(cmd, timeout=300)

    if success:
        _log(f"[OK] {layer_id}")
    else:
        _log(f"[FAIL] {layer_id}: {output}", important=True)

    return layer_id, success, output


def run_transparency_check(
    layer_id: str,
    config_path: str,
    pm: PathManager,
) -> tuple[str, bool, str]:
    """Run check_transparency.py with --remove-bg --auto-crop --pl-mode."""
    layer_dir = pm.get_layer_dir(layer_id)
    layer_path = pm.get_layer_path(layer_id)

    if not layer_path.exists():
        return layer_id, False, "layer file not found"

    # Output path: same directory, _matte suffix
    matte_path = layer_path.with_suffix(".matte.png")

    cmd = [
        sys.executable,
        str(_script_dir / "check_transparency.py"),
        "--config", config_path,
        "--image", str(layer_path),
        "--remove-bg",
        "--output", str(matte_path),
        "--pl-mode",
    ]

    _log(f"[MATTE] {layer_id}")
    success, output = _run_cmd(cmd, timeout=120)

    if success:
        _log(f"[OK] {layer_id} matted")
        # Replace original with matte
        if matte_path.exists():
            backup_path = layer_path.with_suffix(".original.png")
            shutil.move(str(layer_path), str(backup_path))
            shutil.move(str(matte_path), str(layer_path))
    else:
        _log(f"[WARN] {layer_id} matting failed: {output}", important=True)

    return layer_id, success, output


def run_position_detection(
    config_path: str,
    project: str,
    reference_path: str,
) -> tuple[bool, str]:
    """Run detect_layer_positions.py."""
    _log("\n[DETECT] Running position detection...")

    cmd = [
        sys.executable,
        str(_script_dir / "detect_layer_positions.py"),
        "--config", config_path,
        "--project", project,
        "--preview", reference_path,
        "--phase", "rough",
    ]

    success, output = _run_cmd(cmd, timeout=600)

    if success:
        _log("[OK] Position detection complete")
    else:
        _log(f"[WARN] Position detection failed: {output}", important=True)

    return success, output


def run_generate_preview(
    config_path: str,
    project: str,
) -> tuple[bool, str]:
    """Run generate_preview.py with detected layouts applied."""
    _log("\n[PLAN] Generating enhanced layer plan...")

    cmd = [
        sys.executable,
        str(_script_dir / "generate_preview.py"),
        "--config", config_path,
        "--project", project,
        "--phase", "check",
        "--apply-detected-layouts",
    ]

    success, output = _run_cmd(cmd, timeout=60)

    if success:
        _log("[OK] Enhanced layer plan generated")
    else:
        _log(f"[WARN] Plan generation failed: {output}", important=True)

    return success, output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Separate Mode: Generate layers from a reference image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/separate_mode.py \\\n"
            "    --config config.json --project my-app \\\n"
            "    --reference-image reference.png\n"
            "\n"
            "  python scripts/separate_mode.py \\\n"
            "    --config config.json --project my-app \\\n"
            "    --reference-image reference.png \\\n"
            "    --layer-plan custom/layer_plan.json \\\n"
            "    --quality medium --parallel\n"
        ),
    )
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--project", "-p", required=True, help="Project name")
    parser.add_argument(
        "--reference-image", "-i", required=True,
        help="Path to reference image (used as source for PL generation and detection)",
    )
    parser.add_argument(
        "--layer-plan",
        help="Path to layer_plan.json (default: 02-confirmation/layer_plan.json)",
    )
    parser.add_argument(
        "--quality", choices=["low", "medium", "high"], default="low",
        help="Generation quality tier (default: low)",
    )
    parser.add_argument(
        "--parallel", action="store_true",
        help="Generate layers in parallel (max 3 workers)",
    )
    parser.add_argument(
        "--skip-detection", action="store_true",
        help="Skip position detection (useful when detection is not needed)",
    )
    parser.add_argument(
        "--skip-matting", action="store_true",
        help="Skip transparency check and rembg matting",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Reduce log verbosity",
    )
    style_group = parser.add_mutually_exclusive_group()
    style_group.add_argument(
        "--style", default=None,
        help="Style library name (resolved under workspace/styles/{name}/).",
    )
    style_group.add_argument(
        "--style-from", default=None,
        help="Explicit path to a style directory (containing style.json).",
    )

    args = parser.parse_args()

    # ── 1. Validate inputs ──────────────────────────────────────────
    reference_path = Path(args.reference_image).resolve()
    if not reference_path.exists():
        print(f"[ERROR] Reference image not found: {reference_path}")
        sys.exit(1)

    config_path = args.config
    project = args.project

    pm = PathManager(project, config_path=config_path)

    # Layer plan
    if args.layer_plan:
        layer_plan_path = Path(args.layer_plan).resolve()
    else:
        layer_plan_path = pm.get_layer_plan_path()

    if not layer_plan_path.exists():
        print(f"[ERROR] layer_plan.json not found: {layer_plan_path}")
        print("  In separate mode, layer_plan.json must be generated by agent visual analysis first.")
        sys.exit(1)

    with open(layer_plan_path, "r", encoding="utf-8") as f:
        layer_plan = json.load(f)

    layers = layer_plan.get("layers", [])
    if not layers:
        print("[ERROR] No layers found in layer_plan.json")
        sys.exit(1)

    style_anchor = layer_plan.get("style_anchor", "")

    # ── Resolve active style (CLI override > layer_plan.style_ref) ──
    style_dir: Path | None = None
    style_name_for_log: str | None = None
    if args.style_from:
        style_dir = Path(args.style_from).resolve()
        if not (style_dir / "style.json").exists():
            print(f"[ERROR] style.json not found in {style_dir}")
            sys.exit(1)
        style_name_for_log = style_dir.name
    elif args.style:
        try:
            style_dir = style_loader.resolve(args.style)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        style_name_for_log = args.style
    else:
        # Fall back to layer_plan.style_ref if present
        style_ref = layer_plan.get("style_ref") or {}
        if isinstance(style_ref, dict):
            ref_dir = style_ref.get("dir")
            ref_name = style_ref.get("name")
            try:
                if ref_dir:
                    candidate = Path(ref_dir)
                    if not candidate.is_absolute():
                        candidate = (PathManager.get_workspace_root() / candidate).resolve()
                    if (candidate / "style.json").exists():
                        style_dir = candidate
                        style_name_for_log = ref_name or candidate.name
                elif ref_name:
                    style_dir = style_loader.resolve(ref_name)
                    style_name_for_log = ref_name
            except FileNotFoundError:
                _log(
                    f"[WARN] layer_plan.style_ref references missing style "
                    f"({ref_name or ref_dir}); continuing without style.",
                    important=True,
                )
                style_dir = None

    _log("=" * 60)
    _log("  Separate Mode")
    _log("=" * 60)
    _log(f"Project: {project}")
    _log(f"Reference: {reference_path}")
    _log(f"Layers: {len(layers)}")
    _log(f"Quality: {args.quality}")
    if style_dir is not None:
        _log(f"Style: {style_name_for_log} ({style_dir})")

    # ── 2. Create size_plan.json ────────────────────────────────────
    img_w, img_h = _get_image_size(reference_path)
    size_plan = create_size_plan(pm, config_path, img_w, img_h)
    canvas_w = size_plan["full_size"]["width"]
    canvas_h = size_plan["full_size"]["height"]

    # Copy reference image to project directory
    ref_dest = pm.get_phase_dir("requirements") / "references" / "reference.png"
    ref_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(reference_path, ref_dest)
    _log(f"[OK] Copied reference image to: {ref_dest}")

    # ── 3. Generate layers (PL mode) ────────────────────────────────
    _log("\n" + "=" * 60)
    _log("STEP 1: Generate layers (PL mode)")
    _log("=" * 60)

    gen_commands = []
    style_dir_str = str(style_dir) if style_dir is not None else None
    for layer in layers:
        layer["style_anchor"] = style_anchor  # Inject style_anchor into each layer
        gen_commands.append((
            layer, str(ref_dest), config_path, pm,
            canvas_w, canvas_h, args.quality, style_dir_str,
        ))

    gen_results = {}
    if args.parallel:
        max_workers = 3
        _log(f"[INFO] Parallel generation with {max_workers} workers\n")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(generate_layer, *cmd): cmd[0].get("id", "")
                for cmd in gen_commands
            }
            for future in as_completed(futures):
                layer_id, success, output = future.result()
                gen_results[layer_id] = (success, output)
    else:
        for cmd in gen_commands:
            layer_id, success, output = generate_layer(*cmd)
            gen_results[layer_id] = (success, output)

    # Check for failures
    failed_gen = [lid for lid, (s, _) in gen_results.items() if not s]
    if failed_gen:
        _log(f"\n[ERROR] {len(failed_gen)} layer(s) failed to generate:", important=True)
        for lid in failed_gen:
            _log(f"  - {lid}", important=True)
        sys.exit(1)

    _log(f"\n[OK] All {len(layers)} layers generated")

    # ── 4. Transparency check + matting ─────────────────────────────
    if not args.skip_matting:
        _log("\n" + "=" * 60)
        _log("STEP 2: Transparency check + rembg matting")
        _log("=" * 60)

        matte_results = {}
        non_bg_layers = [l for l in layers if (l.get("id", "") or l.get("name", "")) != "background"]

        for layer in non_bg_layers:
            layer_id = layer.get("id", "") or layer.get("name", "")
            lid, success, output = run_transparency_check(layer_id, config_path, pm)
            matte_results[lid] = (success, output)

        failed_matte = [lid for lid, (s, _) in matte_results.items() if not s]
        if failed_matte:
            _log(f"\n[WARN] {len(failed_matte)} layer(s) failed matting (continuing):", important=True)
            for lid in failed_matte:
                _log(f"  - {lid}", important=True)
    else:
        _log("\n[SKIP] Skipping matting (--skip-matting)")

    # ── 5. Position detection ───────────────────────────────────────
    if not args.skip_detection:
        success, _ = run_position_detection(config_path, project, str(ref_dest))
        if not success:
            _log("[WARN] Position detection had issues, continuing with planned layouts", important=True)
    else:
        _log("\n[SKIP] Skipping position detection (--skip-detection)")

    # ── 6. Generate enhanced_layer_plan.json ────────────────────────
    _log("\n" + "=" * 60)
    _log("STEP 3: Generate enhanced layer plan")
    _log("=" * 60)

    success, _ = run_generate_preview(config_path, project)
    if not success:
        _log("[WARN] Enhanced plan generation had issues", important=True)

    # ── 7. Summary ──────────────────────────────────────────────────
    _log("\n" + "=" * 60)
    _log("SEPARATE MODE COMPLETE")
    _log("=" * 60)

    output_dir = pm.get_phase_dir("check")
    enhanced_plan = output_dir / "enhanced_layer_plan.json"
    detected_layouts = output_dir / "detected_layouts.json"

    _log(f"\nOutput files:")
    _log(f"  size_plan.json:        {pm.get_phase_dir('requirements') / 'size_plan.json'}")
    _log(f"  layer_plan.json:       {layer_plan_path}")
    _log(f"  generated layers:      {pm.get_phase_dir('rough_design')}")
    if enhanced_plan.exists():
        _log(f"  enhanced_layer_plan:   {enhanced_plan}")
    if detected_layouts.exists():
        _log(f"  detected_layouts:      {detected_layouts}")

    _log(f"\nNext steps:")
    _log(f"  1. Import into Figma using the Figma plugin")
    _log(f"  2. Review layer positions and adjust if needed")
    _log(f"  3. Generate state variants (Phase 8) if needed")


if __name__ == "__main__":
    main()
