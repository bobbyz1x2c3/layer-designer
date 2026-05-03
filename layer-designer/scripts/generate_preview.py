#!/usr/bin/env python3
"""
Generate enhanced_layer_plan.json for Phase 4 interactive web preview.

This script:
1. Reads layer_plan.json and size_plan.json
2. Scans the layer directories to find the latest PNG for each layer
3. Produces enhanced_layer_plan.json with layout + resource paths
4. Copies the generic preview.html template into the check directory

The resulting files in 04-check/:
- enhanced_layer_plan.json  → data source for the preview
- preview.html              → generic static preview page (copied from templates/)

Usage:
    python generate_preview.py --config config.json --project my-app --phase check
    python generate_preview.py --config config.json --project my-app --phase refinement
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from config_loader import load_config, get_paths_config
from path_manager import PathManager


def _get_latest_layer_png(layer_dir: Path, prefer_cropped: bool = True) -> Path | None:
    """Get the most recent PNG file in a layer directory.

    If prefer_cropped is True and a *_cropped.png exists, prefer it over
    the original (for extreme-ratio layers that were auto-cropped).
    """
    if not layer_dir.exists():
        return None

    # Try glob first
    pngs = sorted(layer_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)

    # Prefer cropped version if available
    if prefer_cropped and pngs:
        cropped = [p for p in pngs if p.stem.endswith("_cropped")]
        if cropped:
            return cropped[0]

    if pngs:
        # Filter out cropped versions if we want the original
        originals = [p for p in pngs if not p.stem.endswith("_cropped")]
        if originals:
            return originals[0]
        return pngs[0]

    # Fallback: iterdir for case-insensitive or encoding edge cases
    try:
        all_files = list(layer_dir.iterdir())
        pngs = sorted(
            [f for f in all_files if f.suffix.lower() == ".png"],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if prefer_cropped and pngs:
            cropped = [p for p in pngs if p.stem.endswith("_cropped")]
            if cropped:
                return cropped[0]
        originals = [p for p in pngs if not p.stem.endswith("_cropped")]
        return originals[0] if originals else (pngs[0] if pngs else None)
    except Exception:
        return None


def generate_enhanced_plan(
    project_name: str,
    phase: str,
    config_path: str | None = None,
    apply_detected_layouts: bool = False,
) -> tuple[str, str]:
    """
    Generate enhanced_layer_plan.json and copy preview template.

    Returns:
        (enhanced_plan_path, preview_html_path)
    """
    pm = PathManager(project_name, config_path=config_path)

    # Determine layer source directory and output phase first
    if phase in ("rough", "check"):
        layer_root = pm.get_phase_dir("rough_design")
        output_phase = "check"
    elif phase == "refinement":
        layer_root = pm.get_phase_dir("refinement_layers")
        output_phase = "refinement"
    elif phase == "output":
        layer_root = pm.get_phase_dir("refinement_layers")
        output_phase = "output"
    else:
        raise ValueError(f"Unknown phase: {phase}")

    output_dir = pm.get_phase_dir(output_phase)

    # Read layer plan (prefer expanded_layer_plan.json if it exists)
    expanded_plan_path = pm.get_expanded_layer_plan_path(phase=output_phase)
    # Fallback: for output phase, also check check-phase expanded plan
    fallback_expanded_path = pm.get_expanded_layer_plan_path(phase="check")
    layer_plan_path = pm.get_layer_plan_path()

    if expanded_plan_path.exists():
        with open(expanded_plan_path, "r", encoding="utf-8") as f:
            layer_plan = json.load(f)
    elif output_phase == "output" and fallback_expanded_path.exists():
        with open(fallback_expanded_path, "r", encoding="utf-8") as f:
            layer_plan = json.load(f)
    elif layer_plan_path.exists():
        with open(layer_plan_path, "r", encoding="utf-8") as f:
            layer_plan = json.load(f)
    else:
        raise FileNotFoundError(f"layer_plan.json not found: {layer_plan_path}")

    # Determine scaling
    size_plan_path = pm.get_phase_dir("requirements") / "size_plan.json"
    scale_ratio = 1.0
    canvas_w = canvas_h = 1024
    if size_plan_path.exists():
        with open(size_plan_path, "r", encoding="utf-8") as f:
            size_plan = json.load(f)
        full = size_plan.get("full_size", {})
        early = size_plan.get("early_size", {})
        if phase in ("rough", "check") and early:
            canvas_w = early.get("width", 1024)
            canvas_h = early.get("height", 1024)
            if full:
                scale_ratio = round(early.get("width", canvas_w) / full.get("width", canvas_w), 3)
        elif full:
            canvas_w = full.get("width", 1920)
            canvas_h = full.get("height", 1080)
    else:
        dims = layer_plan.get("dimensions", {})
        canvas_w = dims.get("width", 1024)
        canvas_h = dims.get("height", 1024)

    # Load detection config (with defaults)
    detection_cfg = {}
    try:
        cfg = load_config(config_path) if config_path else {}
        detection_cfg = cfg.get("detection", {})
    except Exception:
        pass
    warn_offset_threshold = detection_cfg.get("warn_offset_threshold", 0.30)

    # Load detected layouts only when explicitly requested
    detected_layouts = {}
    if apply_detected_layouts:
        detected_path = output_dir / "detected_layouts.json"
        if detected_path.exists():
            with open(detected_path, "r", encoding="utf-8") as f:
                detected_data = json.load(f)
            detected_layouts = detected_data.get("layers", {})

    # Build enhanced layers list
    layers = layer_plan.get("layers", [])
    # Support both top-level 'stacking_order' and per-layer 'stack_order'
    stacking = layer_plan.get("stacking_order", [])
    if not stacking and layers:
        # Build from per-layer stack_order, using display name
        ordered = sorted(
            layers,
            key=lambda l: l.get("stack_order", 9999),
        )
        stacking = [l.get("name", l.get("id", "")) for l in ordered]
    enhanced_layers = []

    for layer_info in layers:
        # Support both 'id' (directory name) and 'name' (display name)
        layer_id = layer_info.get("id", "") or layer_info.get("name", "")
        display_name = layer_info.get("name", "") or layer_info.get("id", "")
        layout = layer_info.get("layout", {})

        # Determine lookup directory for PNG
        lookup_id = layer_id
        parent_id = layer_info.get("parent_id", "")
        repeat_parent_id = layer_info.get("repeat_parent_id", "")

        if layer_info.get("is_repeat_instance") and parent_id:
            lookup_id = parent_id
        elif layer_info.get("is_repeat_panel") and repeat_parent_id:
            lookup_id = layer_id  # panel has its own directory

        layer_dir = layer_root / lookup_id
        png_path = _get_latest_layer_png(layer_dir)

        # Relative path from output_dir to PNG
        if layer_info.get("is_repeat_parent"):
            # Parent is a generation template, not rendered in preview
            rel_path = ""
        elif phase == "output":
            # Phase 7: source points to cleaned layer files in layers/ folder
            if layer_info.get("is_repeat_instance") and parent_id:
                output_layer_id = parent_id
            else:
                output_layer_id = layer_id
            rel_path = f"layers/{output_layer_id}.png" if output_layer_id else ""
        elif png_path:
            import os
            rel_path = Path(os.path.relpath(png_path, output_dir)).as_posix()
        else:
            rel_path = ""

        # Scale layout for rough/check phases
        if scale_ratio != 1.0 and layout:
            scaled_layout = {
                "x": int(round(layout.get("x", 0) * scale_ratio)),
                "y": int(round(layout.get("y", 0) * scale_ratio)),
                "width": int(round(layout.get("width", canvas_w) * scale_ratio)),
                "height": int(round(layout.get("height", canvas_h) * scale_ratio)),
            }
        else:
            scaled_layout = layout

        is_precise_layout = layer_info.get("precise_layout", False)

        # Determine final layout
        final_layout = scaled_layout

        if is_precise_layout:
            # PL mode priority: detected layout > crop_bbox > scaled_layout (fallback)
            pl_layout_source = "planned_fallback"

            # 1. Try detected layout (most accurate)
            if apply_detected_layouts and layer_id in detected_layouts:
                dl = detected_layouts[layer_id]
                if dl.get("method") in ("template_match", "template_match_precise"):
                    final_layout = dl["detected"]
                    pl_layout_source = "detected"
            else:
                # 2. Try crop_bbox from layer_meta.json
                meta_path = layer_dir / "layer_meta.json"
                # If in refinement/output phase, fallback to rough_design metadata
                if not meta_path.exists() and output_phase in ("refinement", "output"):
                    rough_layer_dir = pm.get_phase_dir("rough_design") / lookup_id
                    meta_path = rough_layer_dir / "layer_meta.json"

                if meta_path.exists():
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        bbox = meta.get("crop_bbox")
                        # crop_bbox is (x, y, width, height) — see crop_to_content.py
                        if bbox and len(bbox) == 4:
                            final_layout = {
                                "x": bbox[0],
                                "y": bbox[1],
                                "width": bbox[2],
                                "height": bbox[3],
                            }
                            pl_layout_source = "crop_bbox"
                    except Exception:
                        pass  # fallback to scaled_layout

            if pl_layout_source == "planned_fallback":
                print(f"  [WARN] {layer_id}: PL mode layer has no crop metadata or detected layout. "
                      f"Falling back to planned layout — position may be inaccurate.")
        else:
            # Normal layer: use detected layout only when explicitly applied
            if apply_detected_layouts and layer_id in detected_layouts:
                dl = detected_layouts[layer_id]
                if dl.get("method") == "template_match":
                    detected_layout = dl["detected"]
                    # Warn if detected position deviates significantly from planned
                    dx = detected_layout.get("x", 0) - scaled_layout.get("x", 0)
                    dy = detected_layout.get("y", 0) - scaled_layout.get("y", 0)
                    offset_dist = (dx * dx + dy * dy) ** 0.5
                    avg_size = (scaled_layout.get("width", 1) + scaled_layout.get("height", 1)) / 2
                    if avg_size > 0 and offset_dist / avg_size > warn_offset_threshold:
                        print(f"  [WARN] {layer_id}: detected position deviates {offset_dist:.0f}px "
                              f"({offset_dist/avg_size*100:.0f}%) from planned layout")
                    final_layout = detected_layout

        # Support both 'description' and 'contents' for content field
        content = layer_info.get("description", "") or layer_info.get("contents", "")

        layer_entry = {
            "id": layer_id,
            "name": display_name,
            "content": content,
            "status": layer_info.get("status", "active"),
            "layout": final_layout,
            "source": rel_path,
            "opacity": layer_info.get("opacity", 1.0),
        }
        if is_precise_layout:
            layer_entry["precise_layout"] = True
        # Preserve repeat_mode metadata for preview rendering
        if layer_info.get("is_repeat_parent"):
            layer_entry["is_repeat_parent"] = True
            layer_entry["repeat_mode"] = layer_info.get("repeat_mode", "")
            layer_entry["repeat_config"] = layer_info.get("repeat_config", {})
        if layer_info.get("is_repeat_instance"):
            layer_entry["is_repeat_instance"] = True
            layer_entry["parent_id"] = layer_info.get("parent_id", "")
            layer_entry["repeat_mode"] = layer_info.get("repeat_mode", "")
            layer_entry["cell_index"] = layer_info.get("cell_index", 0)
            layer_entry["cell_row"] = layer_info.get("cell_row", 0)
            layer_entry["cell_col"] = layer_info.get("cell_col", 0)
        if layer_info.get("is_repeat_panel"):
            layer_entry["is_repeat_panel"] = True
            layer_entry["repeat_parent_id"] = layer_info.get("repeat_parent_id", "")
        enhanced_layers.append(layer_entry)

    enhanced_plan = {
        "project": project_name,
        "phase": output_phase,
        "dimensions": {"width": canvas_w, "height": canvas_h},
        "style_anchor": layer_plan.get("style_anchor", ""),
        "layers": enhanced_layers,
        "stacking_order": stacking,
        "repeat_meta": layer_plan.get("repeat_meta", []),
    }

    # Save enhanced_layer_plan.json with UTF-8 BOM for Windows compatibility
    plan_path = output_dir / "enhanced_layer_plan.json"

    # Backup existing plan before overwriting with detected layouts
    if apply_detected_layouts and detected_layouts and plan_path.exists():
        from datetime import datetime
        backup_path = plan_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        shutil.copy2(plan_path, backup_path)
        print(f"[BACKUP] Saved previous plan to {backup_path.name}")

    with open(plan_path, "w", encoding="utf-8-sig") as f:
        json.dump(enhanced_plan, f, indent=2, ensure_ascii=False)

    # Copy generic preview template
    script_dir = Path(__file__).parent.resolve()
    template_path = script_dir.parent / "templates" / "preview.html"
    preview_path = output_dir / "preview.html"

    if template_path.exists():
        shutil.copy2(template_path, preview_path)
    else:
        # Fallback: write a minimal placeholder
        preview_path.write_text(
            '<!DOCTYPE html><html><body><h1>Preview template not found</h1>'
            f'<p>Expected: {template_path}</p></body></html>',
            encoding="utf-8"
        )

    return str(plan_path), str(preview_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate enhanced_layer_plan.json and copy preview template"
    )
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--project", "-p", required=True, help="Project name")
    parser.add_argument("--phase", choices=["rough", "refinement", "check", "output"], default="check",
                        help="Which phase (default: check)")
    parser.add_argument("--apply-detected-layouts", action="store_true",
                        help="Apply algorithmically detected layouts from detected_layouts.json")
    args = parser.parse_args()

    try:
        plan_path, preview_path = generate_enhanced_plan(
            args.project, args.phase, config_path=args.config,
            apply_detected_layouts=args.apply_detected_layouts,
        )
        print(f"PLAN:    {plan_path}")
        print(f"PREVIEW: {preview_path}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
