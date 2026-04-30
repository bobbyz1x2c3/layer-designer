#!/usr/bin/env python3
"""
Expand repeat_mode layers (grid / list) into individual instances.

Reads layer_plan.json, detects layers with repeat_mode != "none",
computes per-instance layouts, and writes expanded_layer_plan.json.

Key design:
- Parent layer is PRESERVED in the layers list (marked is_repeat_parent)
  so Phase 3/6 can generate it once, and Phase 8 can generate state variants.
- Panel background layer is added if auto_panel is enabled.
- Instance layers are added for preview rendering only (no separate generation).
- Stacking order: panel (if any) + instances. Parent is NOT in stacking_order
  to avoid overlapping the first instance.

Usage:
    python expand_repeats.py \
        --config config.json \
        --project my-app \
        --input 02-confirmation/layer_plan.json \
        --output 04-check/expanded_layer_plan.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from path_manager import PathManager


def _resolve_padding(config: dict) -> tuple[int, int, int, int]:
    """Resolve padding from config into (top, right, bottom, left).

    Supports:
    - Single number: padding applies to all 4 sides
    - Dict with keys: top, right, bottom, left
    - Missing/None: defaults to 0 for all sides
    """
    padding = config.get("padding")
    if padding is None:
        return 0, 0, 0, 0
    if isinstance(padding, (int, float)):
        p = int(padding)
        return p, p, p, p
    return (
        padding.get("top", 0),
        padding.get("right", 0),
        padding.get("bottom", 0),
        padding.get("left", 0),
    )


def _compute_panel_layout(parent: dict, config: dict) -> dict | None:
    """Compute the bounding box of the entire repeat area (panel).

    Priority:
    1. If auto_panel.layout is explicitly provided, use it directly.
    2. If area_layout has width/height, use it as the panel boundary.
    3. Otherwise, auto-calculate from cols/rows/gap or count/direction/gap.
    """
    panel_cfg = config.get("auto_panel", {})

    # 1. Manual override: highest priority
    manual_layout = panel_cfg.get("layout")
    if manual_layout and all(k in manual_layout for k in ("x", "y", "width", "height")):
        return {
            "x": manual_layout["x"],
            "y": manual_layout["y"],
            "width": manual_layout["width"],
            "height": manual_layout["height"],
        }

    # 2. area_layout with width/height → panel boundary
    area = config.get("area_layout", {})
    if area.get("width") is not None and area.get("height") is not None:
        return {
            "x": area.get("x", 0),
            "y": area.get("y", 0),
            "width": area["width"],
            "height": area["height"],
        }

    # 3. Auto-calculate from repeat geometry (legacy fallback)
    repeat_mode = parent.get("repeat_mode", "none")
    parent_layout = parent.get("layout", {})
    cell_w = parent_layout.get("width", 100)
    cell_h = parent_layout.get("height", 100)

    start_x = area.get("x", parent_layout.get("x", 0))
    start_y = area.get("y", parent_layout.get("y", 0))

    if repeat_mode == "grid":
        cols = config.get("cols", 1)
        rows = config.get("rows", 1)
        gap_x = config.get("gap_x", 0)
        gap_y = config.get("gap_y", 0)
        total_w = cols * cell_w + max(0, cols - 1) * gap_x
        total_h = rows * cell_h + max(0, rows - 1) * gap_y
    elif repeat_mode == "list":
        count = config.get("count", 1)
        gap = config.get("gap", 0)
        direction = config.get("direction", "horizontal")
        if direction == "horizontal":
            total_w = count * cell_w + max(0, count - 1) * gap
            total_h = cell_h
        else:
            total_w = cell_w
            total_h = count * cell_h + max(0, count - 1) * gap
    else:
        return None

    return {"x": start_x, "y": start_y, "width": total_w, "height": total_h}


def _compute_frame_layout(parent: dict, instances: list[dict], config: dict,
                           panel_layout: dict | None = None) -> dict:
    """Compute the container frame layout (parent becomes the whole frame).

    Matches Figma import logic:
    - If area_layout has width/height, use it directly as frame bounds.
    - If panel exists, use panel bounds as frame bounds.
    - Otherwise, use first instance position as origin, content + padding as size.
    """
    area = config.get("area_layout", {})

    # 1. area_layout defines the full frame boundary
    if area.get("width") is not None and area.get("height") is not None:
        return {
            "x": area.get("x", 0),
            "y": area.get("y", 0),
            "width": area["width"],
            "height": area["height"],
        }

    # 2. Panel exists → frame matches panel
    if panel_layout:
        return {
            "x": panel_layout.get("x", 0),
            "y": panel_layout.get("y", 0),
            "width": panel_layout.get("width", 100),
            "height": panel_layout.get("height", 100),
        }

    # 3. No panel, no area_layout → compute from instances (legacy)
    if not instances:
        return dict(parent.get("layout", {}))

    first_inst = instances[0]
    min_x = first_inst["layout"]["x"]
    min_y = first_inst["layout"]["y"]
    max_right = max(inst["layout"]["x"] + inst["layout"]["width"] for inst in instances)
    max_bottom = max(inst["layout"]["y"] + inst["layout"]["height"] for inst in instances)

    pt, pr, pb, pl = _resolve_padding(config)

    return {
        "x": min_x,
        "y": min_y,
        "width": (max_right - min_x) + pl + pr,
        "height": (max_bottom - min_y) + pt + pb,
    }


def _build_panel_layer(parent: dict, config: dict) -> dict | None:
    """Build a panel background layer if auto_panel is enabled."""
    panel_cfg = config.get("auto_panel", {})
    if not panel_cfg or not panel_cfg.get("enabled", False):
        return None

    panel_layout = _compute_panel_layout(parent, config)
    if not panel_layout:
        return None

    parent_id = parent.get("id", parent.get("name", "unknown"))
    parent_name = parent.get("name", parent_id)
    panel_id = panel_cfg.get("id", f"{parent_id}_panel")
    panel_name = panel_cfg.get("name", f"{parent_name} 背景")

    return {
        "id": panel_id,
        "name": panel_name,
        "content": panel_cfg.get("description", f"Panel background container for {parent_name}"),
        "layout": panel_layout,
        "source": "",
        "opacity": panel_cfg.get("opacity", 1.0),
        "quality_tier": panel_cfg.get("quality_tier", "low"),
        "is_repeat_panel": True,
        "repeat_parent_id": parent_id,
    }


def _build_instances(parent: dict, config: dict) -> list[dict]:
    """Build all repeat instance layers for a parent."""
    parent_layout = parent.get("layout", {})
    cell_w = parent_layout.get("width", 100)
    cell_h = parent_layout.get("height", 100)
    area = config.get("area_layout", {})
    pt, pr, pb, pl = _resolve_padding(config)
    repeat_mode = parent.get("repeat_mode", "none")
    parent_id = parent.get("id", parent.get("name", "unknown"))
    parent_name = parent.get("name", parent_id)

    # Determine cell start position
    # If area_layout has width/height, it's a panel boundary; apply padding offset.
    # Otherwise (legacy), area_layout.x/y is the direct cell start.
    if area.get("width") is not None and area.get("height") is not None:
        start_x = area.get("x", parent_layout.get("x", 0)) + pl
        start_y = area.get("y", parent_layout.get("y", 0)) + pt
    else:
        start_x = area.get("x", parent_layout.get("x", 0))
        start_y = area.get("y", parent_layout.get("y", 0))

    instances = []

    if repeat_mode == "grid":
        cols = config.get("cols", 1)
        rows = config.get("rows", 1)
        gap_x = config.get("gap_x", 0)
        gap_y = config.get("gap_y", 0)
        idx = 0
        for row in range(rows):
            for col in range(cols):
                x = start_x + col * (cell_w + gap_x)
                y = start_y + row * (cell_h + gap_y)
                instances.append({
                    "id": f"{parent_id}_cell_{row}_{col}",
                    "name": f"{parent_name} ({row + 1},{col + 1})",
                    "content": parent.get("description", parent.get("contents", "")),
                    "layout": {"x": x, "y": y, "width": cell_w, "height": cell_h},
                    "source": "",  # Points to parent's PNG
                    "opacity": parent.get("opacity", 1.0),
                    "quality_tier": parent.get("quality_tier", "low"),
                    "is_repeat_instance": True,
                    "parent_id": parent_id,
                    "parent_name": parent_name,
                    "repeat_mode": "grid",
                    "cell_index": idx,
                    "cell_row": row,
                    "cell_col": col,
                })
                idx += 1

    elif repeat_mode == "list":
        count = config.get("count", 1)
        gap = config.get("gap", 0)
        direction = config.get("direction", "horizontal")
        for i in range(count):
            if direction == "horizontal":
                x = start_x + i * (cell_w + gap)
                y = start_y
            else:
                x = start_x
                y = start_y + i * (cell_h + gap)
            instances.append({
                "id": f"{parent_id}_item_{i}",
                "name": f"{parent_name} [{i + 1}]",
                "content": parent.get("description", parent.get("contents", "")),
                "layout": {"x": x, "y": y, "width": cell_w, "height": cell_h},
                "source": "",  # Points to parent's PNG
                "opacity": parent.get("opacity", 1.0),
                "quality_tier": parent.get("quality_tier", "low"),
                "is_repeat_instance": True,
                "parent_id": parent_id,
                "parent_name": parent_name,
                "repeat_mode": "list",
                "cell_index": i,
                "cell_row": i if direction == "vertical" else 0,
                "cell_col": i if direction == "horizontal" else 0,
            })

    return instances


def expand_layer_plan(layer_plan: dict, phase: str = "rough") -> dict:
    """
    Expand repeat_mode layers.

    Returns a dict where:
    - Parent layers are preserved (is_repeat_parent=True) for generation
    - Panel layers are added (is_repeat_panel=True) if auto_panel enabled
    - Instance layers are added (is_repeat_instance=True) for preview only
    - Stacking_order contains panel + instances (parent excluded to avoid overlap)
    """
    result = {
        "project": layer_plan.get("project", ""),
        "dimensions": layer_plan.get("dimensions", {}),
        "style_anchor": layer_plan.get("style_anchor", ""),
        "layers": [],
        "stacking_order": [],
        "repeat_meta": [],
    }

    original_layers = layer_plan.get("layers", [])
    original_order = layer_plan.get("stacking_order", [])

    expanded_layers = []
    repeat_meta = []

    for layer in original_layers:
        repeat_mode = layer.get("repeat_mode", "none") or "none"
        config = layer.get("repeat_config", {})

        if repeat_mode in ("grid", "list") and config:
            parent_id = layer.get("id", layer.get("name", ""))

            # 1. Build instances first (uses original parent layout as cell size)
            instances = _build_instances(layer, config)

            # 2. Build panel if enabled (before computing frame layout)
            panel = _build_panel_layer(layer, config)

            # 3. Compute frame layout: parent becomes the whole container frame
            panel_layout = panel.get("layout") if panel else None
            frame_layout = _compute_frame_layout(layer, instances, config, panel_layout)

            # 4. Update parent layout to frame bounds
            parent_copy = dict(layer)
            parent_copy["is_repeat_parent"] = True
            parent_copy["layout"] = frame_layout
            expanded_layers.append(parent_copy)

            # 5. Update panel to match frame bounds
            if panel:
                panel["layout"] = dict(frame_layout)
                expanded_layers.append(panel)

            # 6. Add instances
            expanded_layers.extend(instances)

            meta = {
                "parent_id": parent_id,
                "parent_name": layer.get("name", ""),
                "repeat_mode": repeat_mode,
                "repeat_config": config,
                "instance_count": len(instances),
                "has_panel": panel is not None,
            }
            if panel:
                meta["panel_id"] = panel["id"]
                meta["panel_name"] = panel["name"]
            repeat_meta.append(meta)
        else:
            expanded_layers.append(layer)

    result["layers"] = expanded_layers
    result["repeat_meta"] = repeat_meta

    # Build stacking_order: panel + instances for each repeat parent;
    # non-repeat layers stay as-is.
    parent_to_instances: dict[str, list[str]] = {}
    parent_to_panel: dict[str, str] = {}
    for inst in expanded_layers:
        if inst.get("is_repeat_instance"):
            pid = inst["parent_id"]
            parent_to_instances.setdefault(pid, []).append(inst["name"])
        elif inst.get("is_repeat_panel"):
            pid = inst["repeat_parent_id"]
            parent_to_panel[pid] = inst["name"]

    new_order = []
    for name in original_order:
        parent_id = None
        for layer in original_layers:
            if layer.get("name") == name or layer.get("id") == name:
                if layer.get("repeat_mode") in ("grid", "list"):
                    parent_id = layer.get("id", layer.get("name", ""))
                break

        if parent_id and parent_id in parent_to_instances:
            if parent_id in parent_to_panel:
                new_order.append(parent_to_panel[parent_id])
            new_order.extend(parent_to_instances[parent_id])
        elif name not in parent_to_panel.values():
            new_order.append(name)

    # Append any layers not yet in stacking_order
    existing = set(new_order)
    for layer in expanded_layers:
        lname = layer.get("name", "")
        lid = layer.get("id", "")
        # Skip parents (they're templates, not rendered)
        if layer.get("is_repeat_parent"):
            continue
        if lname not in existing and lid not in existing:
            new_order.append(lname or lid)

    result["stacking_order"] = new_order
    return result


def main():
    parser = argparse.ArgumentParser(description="Expand repeat_mode layers into instances")
    parser.add_argument("--config", "-c", help="Path to config.json")
    parser.add_argument("--project", "-p", required=True, help="Project name")
    parser.add_argument("--input", "-i", help="Input layer_plan.json path")
    parser.add_argument("--output", "-o", help="Output expanded_layer_plan.json path")
    parser.add_argument("--phase", choices=["rough", "check", "refinement", "output"],
                        default="check", help="Phase context (default: check)")
    args = parser.parse_args()

    pm = PathManager(args.project, config_path=args.config)

    input_path = Path(args.input) if args.input else pm.get_layer_plan_path()
    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        layer_plan = json.load(f)

    expanded = expand_layer_plan(layer_plan, phase=args.phase)

    if args.output:
        output_path = Path(args.output)
    elif args.phase == "refinement":
        output_path = pm.get_phase_dir("refinement_layers") / "expanded_layer_plan.json"
    elif args.phase == "output":
        output_path = pm.get_output_dir() / "expanded_layer_plan.json"
    else:
        output_path = pm.get_check_dir() / "expanded_layer_plan.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(expanded, f, indent=2, ensure_ascii=False)

    total_instances = sum(m["instance_count"] for m in expanded["repeat_meta"])
    total_parents = len(expanded["repeat_meta"])
    total_panels = sum(1 for m in expanded["repeat_meta"] if m.get("has_panel"))
    print(f"[OK] Expanded layer plan saved to: {output_path}")
    print(f"     Total layers: {len(expanded['layers'])} ({len(layer_plan.get('layers', []))} original)")
    print(f"     Rendered layers (stacking_order): {len(expanded['stacking_order'])}")
    if total_parents > 0:
        print(f"     Repeat parents: {total_parents} -> {total_instances} instances")
        if total_panels > 0:
            print(f"     Panel backgrounds: {total_panels}")
        for meta in expanded["repeat_meta"]:
            panel_info = f" + panel ({meta['panel_name']})" if meta.get("has_panel") else ""
            print(f"       - {meta['parent_name']} ({meta['repeat_mode']}): {meta['instance_count']} instances{panel_info}")
    else:
        print("     No repeat_mode layers found.")


if __name__ == "__main__":
    main()
