#!/usr/bin/env python3
"""
根据 detected_layouts.json 中的实际 cell 位置，
反推 repeat_config.padding 和 gap 并修正到 enhanced_layer_plan.json。
不修改原始 layer_plan，只修改输出阶段的 enhanced_layer_plan。
"""
import json
import shutil
from pathlib import Path
from datetime import datetime


def calculate_padding_from_detection(area_layout, first_cell, cols, rows, gap_x, gap_y, cell_w, cell_h):
    """
    从检测出的 cells 位置和 area_layout 反推 padding。
    所有坐标都在同一坐标系下（scaled preview pixels）。
    """
    area_x = area_layout.get("x", 0)
    area_y = area_layout.get("y", 0)
    area_w = area_layout.get("width", 0)
    area_h = area_layout.get("height", 0)

    cell_x = first_cell.get("x", 0)
    cell_y = first_cell.get("y", 0)

    cells_right = cell_x + cols * cell_w + (cols - 1) * gap_x
    cells_bottom = cell_y + rows * cell_h + (rows - 1) * gap_y

    left = max(0, round(cell_x - area_x))
    top = max(0, round(cell_y - area_y))
    right = max(0, round((area_x + area_w) - cells_right))
    bottom = max(0, round((area_y + area_h) - cells_bottom))

    return {"top": top, "right": right, "bottom": bottom, "left": left}


def correct_padding(plan_path, detected_path, output_path=None):
    plan_path = Path(plan_path)
    detected_path = Path(detected_path)

    with open(plan_path, "r", encoding="utf-8-sig") as f:
        plan = json.load(f)

    with open(detected_path, "r", encoding="utf-8") as f:
        detected = json.load(f)

    detected_layers = detected.get("layers", {})

    corrected_count = 0
    for layer in plan.get("layers", []):
        layer_id = layer.get("id")
        if not layer_id:
            continue
        if not layer.get("is_repeat_parent"):
            continue

        det = detected_layers.get(layer_id)
        if not det:
            continue
        if det.get("method") not in ("grid_periodicity", "list_periodicity"):
            continue

        cells = det.get("cells", [])
        if not cells:
            continue

        first_cell = cells[0]
        cols = det.get("cols", 1)
        rows = det.get("rows", 1)
        gap = det.get("gap", {})
        gap_x = gap.get("x", 0)
        gap_y = gap.get("y", 0)
        cell_w = det.get("cell_size", {}).get("width", first_cell.get("width", 0))
        cell_h = det.get("cell_size", {}).get("height", first_cell.get("height", 0))

        area_layout = layer.get("layout", {})

        new_padding = calculate_padding_from_detection(
            area_layout, first_cell, cols, rows, gap_x, gap_y, cell_w, cell_h
        )

        rc = layer.setdefault("repeat_config", {})
        old_padding = rc.get("padding", 0)
        old_gap_x = rc.get("gap_x", 0)
        old_gap_y = rc.get("gap_y", 0)
        old_gap = rc.get("gap", 0)

        rc["padding"] = new_padding

        # 同时修正 gap
        if layer.get("repeat_mode") == "grid":
            rc["gap_x"] = gap_x
            rc["gap_y"] = gap_y
        elif layer.get("repeat_mode") == "list":
            direction = rc.get("direction", "horizontal")
            if direction == "horizontal":
                rc["gap"] = gap_x
            else:
                rc["gap"] = gap_y

        corrected_count += 1

        print(f"  [PADDING+GAP] {layer_id}:")
        print(f"    padding: {old_padding} -> {new_padding}")
        if layer.get("repeat_mode") == "grid":
            print(f"    gap_x: {old_gap_x} -> {gap_x}")
            print(f"    gap_y: {old_gap_y} -> {gap_y}")
        else:
            print(f"    gap: {old_gap} -> {gap_x if rc.get('direction')=='horizontal' else gap_y}")

    if output_path is None:
        output_path = plan_path
    else:
        output_path = Path(output_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = plan_path.parent / f"{plan_path.stem}.backup_{timestamp}{plan_path.suffix}"
    shutil.copy2(plan_path, backup_path)
    print(f"[BACKUP] {backup_path}")

    with open(output_path, "w", encoding="utf-8-sig") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"[WRITE] {output_path} ({corrected_count} layers corrected)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, help="Path to enhanced_layer_plan.json")
    parser.add_argument("--detected", required=True, help="Path to detected_layouts.json")
    parser.add_argument("--output", help="Output path (default: overwrite --plan)")
    args = parser.parse_args()
    correct_padding(args.plan, args.detected, args.output)
