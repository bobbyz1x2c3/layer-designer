#!/usr/bin/env python3
"""
Size validation and planning script for Layered Design Generator.

Workflow phase where this script is invoked:
- Phase 1 (Requirements): REQUIRED before any image generation. Validates user
  dimensions against model constraints, suggests nearest compliant alternatives,
  computes early-phase vs full-phase sizes, and saves the plan for reuse.

Checks user-requested dimensions against gpt-image-2 model constraints.
If non-compliant, suggests the nearest compliant size.
If compliant, computes both full-size and early-phase (downsized) dimensions.
Saves the size plan to the project's workflow record for later reuse.

Usage:
    # Validate size and save to project
    python validate_size.py --project my-dashboard --width 1920 --height 1080

    # Validate only (no save)
    python validate_size.py --width 4000 --height 1000

    # With custom config
    python validate_size.py --config ../config.json --project my-dashboard --width 1024 --height 1024
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from path_manager import PathManager


def compute_nearest_compliant_size(
    width: int,
    height: int,
    max_edge: int = 3840,
    align: int = 16,
    max_ratio: float = 3.0,
    min_pixels: int = 655360,
    max_pixels: int = 8294400,
) -> tuple[int, int]:
    """
    Find the compliant size closest to the user's requested dimensions.

    Strategy:
    1. Round both dimensions to nearest multiples of `align`
    2. Check compliance
    3. If not compliant, search nearby aligned values within a radius,
       preferring sizes closest to the original pixel count.
    """
    def align_round(v: int) -> int:
        return round(v / align) * align

    def align_up(v: int) -> int:
        return ((v + align - 1) // align) * align

    def align_down(v: int) -> int:
        return (v // align) * align

    # Start with rounded values
    candidates = []
    base_w = align_round(width)
    base_h = align_round(height)

    # Search radius: try ±N aligned steps in each dimension
    radius = 20
    for dw in range(-radius, radius + 1):
        w = base_w + dw * align
        if w < align or w > max_edge:
            continue
        for dh in range(-radius, radius + 1):
            h = base_h + dh * align
            if h < align or h > max_edge:
                continue

            pixels = w * h
            if pixels < min_pixels or pixels > max_pixels:
                continue

            ratio = max(w, h) / min(w, h)
            if ratio > max_ratio:
                continue

            # Score: prefer closest aspect ratio, then closest pixel count, then closest dimensions
            original_ratio = max(width, height) / min(width, height) if min(width, height) > 0 else 1.0
            ratio_diff = abs(ratio - original_ratio)
            original_pixels = width * height
            pixel_diff = abs(pixels - original_pixels)
            dim_diff = abs(w - width) + abs(h - height)
            candidates.append((ratio_diff, pixel_diff, dim_diff, w, h))

    if candidates:
        candidates.sort()
        return candidates[0][3], candidates[0][4]

    # Fallback: use the smallest compliant size preserving ratio
    return PathManager.compute_compliant_size(
        width, height,
        max_edge=max_edge, align=align, max_ratio=max_ratio,
        min_pixels=min_pixels, max_pixels=max_pixels,
    )


def check_compliance_issues(
    width: int,
    height: int,
    max_edge: int = 3840,
    align: int = 16,
    max_ratio: float = 3.0,
    min_pixels: int = 655360,
    max_pixels: int = 8294400,
) -> list[str]:
    """Return a list of human-readable compliance issue descriptions."""
    issues = []
    if width <= 0 or height <= 0:
        issues.append("宽度和高度必须是正整数")
        return issues

    if width % align != 0:
        issues.append(f"宽度 {width} 不是 {align} 的倍数")
    if height % align != 0:
        issues.append(f"高度 {height} 不是 {align} 的倍数")
    if width > max_edge:
        issues.append(f"宽度 {width}px 超过最大边长 {max_edge}px")
    if height > max_edge:
        issues.append(f"高度 {height}px 超过最大边长 {max_edge}px")

    ratio = max(width, height) / min(width, height) if min(width, height) > 0 else float("inf")
    if ratio > max_ratio:
        issues.append(f"宽高比 {ratio:.2f}:1 超过最大允许 {max_ratio}:1")

    pixels = width * height
    if pixels < min_pixels:
        issues.append(f"总像素 {pixels:,} 低于最小要求 {min_pixels:,}")
    if pixels > max_pixels:
        issues.append(f"总像素 {pixels:,} 超过最大允许 {max_pixels:,}")

    return issues


def validate_and_plan_size(
    width: int,
    height: int,
    project_name: str | None = None,
    config_path: str | None = None,
    downsize_ratio: float = 0.5,
    max_edge: int = 3840,
    align: int = 16,
    max_ratio: float = 3.0,
    min_pixels: int = 655360,
    max_pixels: int = 8294400,
) -> dict:
    """
    Validate user-requested dimensions and produce a size plan.

    Returns:
        {
            "valid": bool,
            "user_requested": {"width": int, "height": int},
            "messages": [str],           # Human-readable lines for agent to present
            "full_size": {"width": int, "height": int},
            "early_size": {"width": int, "height": int},
            "saved_to": str | None,
        }
    """
    result = {
        "valid": False,
        "user_requested": {"width": width, "height": height},
        "messages": [],
        "full_size": None,
        "early_size": None,
        "saved_to": None,
    }

    # --- 1. Check compliance of user input ---
    issues = check_compliance_issues(
        width, height, max_edge, align, max_ratio, min_pixels, max_pixels
    )

    if issues:
        # Non-compliant: compute nearest compliant size for full size
        compliant_w, compliant_h = compute_nearest_compliant_size(
            width, height,
            max_edge=max_edge, align=align, max_ratio=max_ratio,
            min_pixels=min_pixels, max_pixels=max_pixels,
        )

        ratio = max(compliant_w, compliant_h) / min(compliant_w, compliant_h)
        result["messages"] = [
            f"[INVALID] 尺寸 {width}×{height} 不符合 gpt-image-2 约束：",
            *[f"  - {issue}" for issue in issues],
            "",
            f"[SUGGESTION] 建议的最接近合规尺寸：{compliant_w}×{compliant_h}",
            f"   （宽高比 {ratio:.3f}，总像素 {compliant_w * compliant_h:,}）",
            "",
            "请确认使用建议尺寸，或提供其他尺寸。",
        ]
        result["full_size"] = {"width": compliant_w, "height": compliant_h}
    else:
        # Compliant
        ratio = max(width, height) / min(width, height)
        result["valid"] = True
        result["messages"] = [
            f"[VALID] 尺寸 {width}×{height} 符合 gpt-image-2 约束。"
            f"   （总像素 {width * height:,}，宽高比 {ratio:.3f}）",
        ]
        result["full_size"] = {"width": width, "height": height}

    # --- 2. Compute early-phase size from the FULL size ---
    fw, fh = result["full_size"]["width"], result["full_size"]["height"]
    early_w, early_h = PathManager.compute_early_phase_size(
        fw, fh,
        downsize_ratio=downsize_ratio,
        threshold_w=300, threshold_h=200, threshold_pixels=60000,
        max_edge=max_edge, align=align, max_ratio=max_ratio,
        min_pixels=min_pixels, max_pixels=max_pixels,
    )
    result["early_size"] = {"width": early_w, "height": early_h}

    # --- 3. Save to project record ---
    if project_name:
        pm = PathManager(project_name, config_path=config_path)
        plan = {
            "timestamp": datetime.now().isoformat(),
            "user_requested": result["user_requested"],
            "full_size": result["full_size"],
            "early_size": result["early_size"],
            "valid": result["valid"],
        }
        save_path = pm.get_phase_dir("requirements") / "size_plan.json"
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        result["saved_to"] = str(save_path)

    return result


def format_output(result: dict) -> str:
    """Format the result dict into a human-readable string for CLI output."""
    lines = result["messages"][:]
    lines.append("")
    if result["full_size"]:
        fs = result["full_size"]
        lines.append(f"Full size (Phase 5~8):  {fs['width']}×{fs['height']}")
    if result["early_size"]:
        es = result["early_size"]
        lines.append(f"Early size (Phase 1~4): {es['width']}×{es['height']}")
    if result["saved_to"]:
        lines.append(f"Saved to: {result['saved_to']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Validate and plan image generation sizes")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--project", "-p", help="Project name (to save size_plan.json)")
    parser.add_argument("--width", "-W", type=int, required=True, help="Requested width in pixels")
    parser.add_argument("--height", "-H", type=int, required=True, help="Requested height in pixels")
    args = parser.parse_args()

    result = validate_and_plan_size(
        width=args.width,
        height=args.height,
        project_name=args.project,
        config_path=args.config,
    )

    print(format_output(result))

    # Exit code: 0 if valid, 1 if invalid (for scripting use)
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
