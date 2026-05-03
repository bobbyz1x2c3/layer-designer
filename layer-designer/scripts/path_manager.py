#!/usr/bin/env python3
"""
Standardized path manager for Layered Design Generator output.
Organizes all generated assets by workflow phase with timestamped versioning.
Also provides model size constraint utilities (compliance checking, downsizing,
and computing gpt-image-2 compliant dimensions).

Workflow role:
- Imported and used in ALL phases that read/write files.
- Used by `validate_size.py` for compliance checking and size planning.
- Agents should import `PathManager` rather than constructing paths manually.

Usage:
    from path_manager import PathManager
    pm = PathManager("my-dashboard", config_path="config.json")
    preview_path = pm.get_preview_path(version=1, index=1)
    layer_dir = pm.get_layer_dir("header")
    early_w, early_h = pm.compute_early_phase_size(1920, 1080)
"""

import json
from datetime import datetime
from pathlib import Path

from config_loader import load_config, get_paths_config


class PathManager:
    """Manages standardized output paths for a design project."""

    PHASES = {
        "requirements": "01-requirements",
        "confirmation": "02-confirmation",
        "rough_design": "03-rough-design",
        "check": "04-check",
        "refinement_preview": "05-refinement-preview",
        "refinement_layers": "06-refinement-layers",
        "output": "07-output",
        "variants": "08-variants",
        "cache": "cache",
    }

    def __init__(self, project_name: str, base_dir: str | None = None, config_path: str | None = None):
        """
        Initialize path manager for a project.

        Args:
            project_name: Unique project identifier (used as root folder name)
            base_dir: Override base output directory. If None, uses config.paths output root
            config_path: Path to config.json
        """
        self.project_name = self._sanitize_name(project_name)
        self.config_path = config_path

        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            try:
                cfg = get_paths_config(load_config(config_path))
                self.base_dir = Path(cfg.get("output_root", "./output"))
            except Exception:
                self.base_dir = Path("./output")

        self.project_dir = self.base_dir / self.project_name

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize project name for filesystem safety."""
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("._")

    @staticmethod
    def timestamp() -> str:
        """Generate timestamp string for versioning."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def compute_downsized_size(width: int, height: int, ratio: float = 0.5,
                                threshold_w: int = 300, threshold_h: int = 200,
                                threshold_pixels: int = 60000) -> tuple[int, int]:
        """
        Compute downsized dimensions for early-phase generation.

        If the original size is already small (below thresholds), returns original.
        Otherwise returns width * ratio, height * ratio (rounded to even integers).

        Returns:
            (target_width, target_height)
        """
        pixels = width * height
        if width < threshold_w or height < threshold_h or pixels < threshold_pixels:
            return width, height
        new_w = max(2, int(width * ratio))
        new_h = max(2, int(height * ratio))
        # Ensure even numbers for compatibility with some encoders
        new_w = new_w if new_w % 2 == 0 else new_w + 1
        new_h = new_h if new_h % 2 == 0 else new_h + 1
        return new_w, new_h

    @staticmethod
    def is_size_compliant(width: int, height: int,
                          max_edge: int = 3840,
                          align: int = 16,
                          max_ratio: float = 3.0,
                          min_pixels: int = 655360,
                          max_pixels: int = 8294400) -> bool:
        """
        Check if dimensions comply with model constraints.

        Args:
            width: Image width in pixels
            height: Image height in pixels
            max_edge: Maximum allowed edge length
            align: Both dimensions must be multiples of this value
            max_ratio: Maximum allowed aspect ratio (long_edge / short_edge)
            min_pixels: Minimum total pixel count
            max_pixels: Maximum total pixel count

        Returns:
            True if compliant, False otherwise
        """
        if width <= 0 or height <= 0:
            return False
        if width % align != 0 or height % align != 0:
            return False
        if width > max_edge or height > max_edge:
            return False
        pixels = width * height
        if pixels < min_pixels or pixels > max_pixels:
            return False
        ratio = max(width, height) / min(width, height)
        if ratio > max_ratio:
            return False
        return True

    @staticmethod
    def compute_compliant_size(
        width: int,
        height: int,
        max_edge: int = 3840,
        align: int = 16,
        max_ratio: float = 3.0,
        min_pixels: int = 655360,
        max_pixels: int = 8294400,
    ) -> tuple[int, int]:
        """
        Compute the smallest compliant size that preserves aspect ratio.

        When the user's requested size (or its downscaled version) violates
        gpt-image-2 constraints, this function finds the smallest valid size
        with approximately the same aspect ratio.

        Constraints enforced:
        - Both dimensions are multiples of `align`
        - Neither dimension exceeds `max_edge`
        - Aspect ratio (long/short) <= `max_ratio`
        - Total pixels between `min_pixels` and `max_pixels`

        Args:
            width: Target width
            height: Target height

        Returns:
            (compliant_width, compliant_height)
        """
        # Validate positive dimensions
        if width <= 0 or height <= 0:
            raise ValueError(f"Dimensions must be positive, got {width}x{height}")

        # Calculate target aspect ratio and cap it
        r = width / height
        if r > max_ratio:
            r = max_ratio
        elif r < 1 / max_ratio:
            r = 1 / max_ratio

        best_size: tuple[int, int] | None = None
        best_score: tuple[int, float] | None = None

        # Search over all possible heights that are multiples of align
        for h in range(align, max_edge + 1, align):
            # Ideal width for this height to match the target ratio
            w_ideal = h * r
            # Round to nearest multiple of align
            w = round(w_ideal / align) * align
            if w <= 0 or w > max_edge:
                continue

            pixels = w * h
            if pixels < min_pixels or pixels > max_pixels:
                continue

            actual_r = w / h if w >= h else h / w
            if actual_r > max_ratio:
                continue

            # Score: prefer smaller area, then closer ratio match
            ratio_diff = abs((w / h) - r) / r if r > 0 else 0
            score = (pixels, ratio_diff)

            if best_score is None or score < best_score:
                best_size = (w, h)
                best_score = score

        if best_size is None:
            # Fallback to safe standard sizes
            if abs(r - 1.0) < 0.01:
                return (1024, 1024)
            elif r >= 1.0:
                return (1024, 640)
            else:
                return (640, 1024)

        return best_size

    @staticmethod
    def is_extreme_ratio(
        layer_w: int,
        layer_h: int,
        max_ratio: float = 3.0,
    ) -> bool:
        """
        Check if a layer's aspect ratio exceeds the model's max_ratio limit.

        When True, compute_layer_size() will clamp the ratio, meaning the
        generated canvas will NOT match the layer's true proportions. The
        caller may want to flag this layer for post-generation cropping.

        Args:
            layer_w, layer_h: Layer dimensions from layer_plan layout
            max_ratio: Maximum allowed aspect ratio (long/short)

        Returns:
            True if original ratio exceeds max_ratio and will be clamped.
        """
        if layer_w <= 0 or layer_h <= 0:
            return False
        ratio = max(layer_w, layer_h) / min(layer_w, layer_h)
        return ratio > max_ratio

    @staticmethod
    def compute_layer_size(
        layer_w: int,
        layer_h: int,
        max_edge: int = 3840,
        align: int = 16,
        max_ratio: float = 3.0,
        min_pixels: int = 655360,
        max_pixels: int = 8294400,
    ) -> tuple[int, int]:
        """
        Compute a compliant canvas size for an isolated layer based on its
        original dimensions from layer_plan.json.

        Strategy:
        1. Preserve the layer's original aspect ratio as closely as possible
        2. Stay as close to the original size as possible (minimize pixel diff)
        3. Ensure full compliance with model constraints

        Args:
            layer_w, layer_h: Layer dimensions from layer_plan layout

        Returns:
            (compliant_width, compliant_height)
        """
        if layer_w <= 0 or layer_h <= 0:
            raise ValueError(
                f"Layer dimensions must be positive, got {layer_w}x{layer_h}"
            )

        ratio = layer_w / layer_h

        # Clamp ratio to max_ratio if the original exceeds it
        if ratio > max_ratio:
            ratio = max_ratio
        elif ratio < 1 / max_ratio:
            ratio = 1 / max_ratio

        best_size: tuple[int, int] | None = None
        best_score: tuple[int, int, float] | None = None
        original_pixels = layer_w * layer_h

        # Iterate over possible widths, compute height from ratio
        for candidate_w in range(align, max_edge + 1, align):
            candidate_h = round(candidate_w / ratio / align) * align
            candidate_h = max(align, candidate_h)

            if candidate_h > max_edge:
                continue

            pixels = candidate_w * candidate_h
            if pixels < min_pixels or pixels > max_pixels:
                continue

            actual_ratio = (
                max(candidate_w, candidate_h) / min(candidate_w, candidate_h)
            )
            if actual_ratio > max_ratio:
                continue

            # Score: prefer closest pixel count to original, then closest dimensions
            pixel_diff = abs(pixels - original_pixels)
            dim_diff = abs(candidate_w - layer_w) + abs(candidate_h - layer_h)
            ratio_diff = (
                abs((candidate_w / candidate_h) - ratio) / ratio
                if ratio > 0 else 0
            )
            score = (pixel_diff, dim_diff, ratio_diff)

            if best_score is None or score < best_score:
                best_size = (candidate_w, candidate_h)
                best_score = score

        if best_size is None:
            # Fallback to safe standard sizes
            if abs(ratio - 1.0) < 0.01:
                return (1024, 1024)
            elif ratio >= 1.0:
                return (1024, 640)
            else:
                return (640, 1024)

        return best_size

    @staticmethod
    def compute_early_phase_size(
        width: int,
        height: int,
        downsize_ratio: float = 0.5,
        threshold_w: int = 300,
        threshold_h: int = 200,
        threshold_pixels: int = 60000,
        max_edge: int = 3840,
        align: int = 16,
        max_ratio: float = 3.0,
        min_pixels: int = 655360,
        max_pixels: int = 8294400,
    ) -> tuple[int, int]:
        """
        Compute early-phase generation size with gpt-image-2 compliance.

        Logic:
        1. Apply downsize_ratio to the target dimensions
        2. If the result is already compliant, use it
        3. If not compliant (e.g., below min_pixels), find the smallest
           compliant size that preserves the aspect ratio
        4. If original is below thresholds, use original (if compliant)
           or find smallest compliant size for original

        Returns:
            (early_phase_width, early_phase_height)
        """
        # Step 1: Check if original is below downsize thresholds
        original_pixels = width * height
        skip_downsize = (
            width < threshold_w
            or height < threshold_h
            or original_pixels < threshold_pixels
        )

        if skip_downsize:
            candidate_w, candidate_h = width, height
        else:
            candidate_w = max(2, int(width * downsize_ratio))
            candidate_h = max(2, int(height * downsize_ratio))
            # Align to model's alignment requirement (e.g. 16 for gpt-image-2)
            candidate_w = ((candidate_w + align - 1) // align) * align
            candidate_h = ((candidate_h + align - 1) // align) * align

        # Step 2: Check compliance
        if PathManager.is_size_compliant(
            candidate_w, candidate_h,
            max_edge=max_edge, align=align, max_ratio=max_ratio,
            min_pixels=min_pixels, max_pixels=max_pixels,
        ):
            return candidate_w, candidate_h

        # Step 3: Find smallest compliant size preserving the downscaled ratio
        compliant_w, compliant_h = PathManager.compute_compliant_size(
            candidate_w, candidate_h,
            max_edge=max_edge, align=align, max_ratio=max_ratio,
            min_pixels=min_pixels, max_pixels=max_pixels,
        )

        # If we downscaled and the compliant size is larger than original,
        # that's a sign the original itself is too small. Still return
        # the compliant size since it's the minimum that works.
        return compliant_w, compliant_h

    @staticmethod
    def size_to_str(width: int, height: int) -> str:
        """Convert dimensions to API size string (e.g., '1024x1024')."""
        return f"{width}x{height}"

    def get_phase_dir(self, phase: str) -> Path:
        """Get directory for a workflow phase."""
        phase_folder = self.PHASES.get(phase, phase)
        path = self.project_dir / phase_folder
        path.mkdir(parents=True, exist_ok=True)
        return path

    # Phase 1: Requirements
    def get_preview_dir(self) -> Path:
        """Get preview images directory."""
        path = self.get_phase_dir("requirements") / "previews"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_preview_path(self, version: int, index: int, timestamp_str: str | None = None) -> Path:
        """
        Get path for a preview image.

        Naming: preview_v{version}_{index:03d}_{timestamp}.png
        """
        ts = timestamp_str or self.timestamp()
        return self.get_preview_dir() / f"preview_v{version}_{index:03d}_{ts}.png"

    def get_conversation_log_path(self) -> Path:
        """Get path for requirements phase conversation log."""
        return self.get_phase_dir("requirements") / "conversation_log.json"

    # Phase 2: Confirmation
    def get_layer_plan_path(self) -> Path:
        """Get path for layer plan JSON."""
        return self.get_phase_dir("confirmation") / "layer_plan.json"

    # Phase 3: Rough Design
    def get_layer_dir(self, layer_name: str) -> Path:
        """Get directory for a specific layer (holds all versions)."""
        path = self.get_phase_dir("rough_design") / self._sanitize_name(layer_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_layer_path(self, layer_name: str, timestamp_str: str | None = None) -> Path:
        """
        Get path for a layer image.

        Naming: {layer_name}_{timestamp}.png
        """
        ts = timestamp_str or self.timestamp()
        return self.get_layer_dir(layer_name) / f"{self._sanitize_name(layer_name)}_{ts}.png"

    def get_layer_meta_path(self, layer_name: str, phase: str = "rough_design") -> Path:
        """Get path for layer metadata JSON (e.g., crop bbox info from PL mode).

        Args:
            layer_name: Layer identifier
            phase: Which phase the layer belongs to ("rough_design" or "refinement_layers")

        Returns:
            Path to {layer_name}_meta.json in the layer's directory
        """
        if phase in ("rough", "check", "rough_design"):
            layer_dir = self.get_phase_dir("rough_design") / self._sanitize_name(layer_name)
        elif phase in ("refinement", "refinement_layers"):
            layer_dir = self.get_phase_dir("refinement_layers") / self._sanitize_name(layer_name)
        else:
            layer_dir = self.get_phase_dir("rough_design") / self._sanitize_name(layer_name)
        layer_dir.mkdir(parents=True, exist_ok=True)
        return layer_dir / f"{self._sanitize_name(layer_name)}_meta.json"

    # Phase 4: Check
    def get_check_dir(self) -> Path:
        """Get check phase directory."""
        return self.get_phase_dir("check")

    def get_check_report_path(self) -> Path:
        """Get path for check report JSON."""
        return self.get_check_dir() / "check_report.json"

    def get_expanded_layer_plan_path(self, phase: str = "check") -> Path:
        """Get path for expanded_layer_plan.json (repeat_mode expanded)."""
        if phase == "refinement":
            return self.get_phase_dir("refinement_layers") / "expanded_layer_plan.json"
        elif phase == "output":
            return self.get_output_dir() / "expanded_layer_plan.json"
        return self.get_check_dir() / "expanded_layer_plan.json"

    # Phase 5: Refinement Preview
    def get_refinement_preview_path(self, timestamp_str: str | None = None) -> Path:
        """Get path for high-quality refined preview."""
        ts = timestamp_str or self.timestamp()
        return self.get_phase_dir("refinement_preview") / f"preview_{ts}.png"

    # Phase 6: Refinement Layers
    def get_final_layer_dir(self, layer_name: str) -> Path:
        """Get directory for a refined/final layer."""
        path = self.get_phase_dir("refinement_layers") / self._sanitize_name(layer_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_final_layer_path(self, layer_name: str, timestamp_str: str | None = None) -> Path:
        """Get path for a refined layer image."""
        ts = timestamp_str or self.timestamp()
        return self.get_final_layer_dir(layer_name) / f"{self._sanitize_name(layer_name)}_{ts}.png"

    # Phase 7: Output
    def get_output_dir(self) -> Path:
        """Get final output directory."""
        return self.get_phase_dir("output")

    def get_output_preview_path(self) -> Path:
        """Get path for final output preview (stable name, no timestamp)."""
        return self.get_output_dir() / "final_preview.png"

    def get_output_layer_dir(self, layer_name: str) -> Path:
        """Get directory for final output layer copy."""
        path = self.get_output_dir() / "layers" / self._sanitize_name(layer_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_output_layer_path(self, layer_name: str) -> Path:
        """Get path for final output layer (stable name)."""
        return self.get_output_layer_dir(layer_name) / f"{self._sanitize_name(layer_name)}.png"

    def get_manifest_path(self) -> Path:
        """Get path for output manifest JSON."""
        return self.get_output_dir() / "manifest.json"

    # Phase 8: Variants
    def get_variant_dir(self, control_name: str) -> Path:
        """Get directory for control state variants."""
        path = self.get_phase_dir("variants") / self._sanitize_name(control_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_variant_path(self, control_name: str, state: str, timestamp_str: str | None = None) -> Path:
        """Get path for a specific control state variant."""
        ts = timestamp_str or self.timestamp()
        return self.get_variant_dir(control_name) / f"{self._sanitize_name(control_name)}_{state}_{ts}.png"

    # Cache
    def get_cache_dir(self) -> Path:
        """Get cache directory for temporary files."""
        path = self.project_dir / self.PHASES["cache"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_temp_generation_dir(self) -> Path:
        """Get temporary generation cache directory."""
        path = self.get_cache_dir() / "temp_generations"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_temp_path(self, prefix: str = "temp", ext: str = ".png") -> Path:
        """Get a temporary file path."""
        return self.get_temp_generation_dir() / f"{prefix}_{self.timestamp()}{ext}"

    # Utility
    def get_latest_file(self, directory: Path, pattern: str = "*.png") -> Path | None:
        """Get the most recently modified file matching pattern in directory."""
        files = list(directory.glob(pattern))
        if not files:
            return None
        return max(files, key=lambda p: p.stat().st_mtime)

    def list_phase_dirs(self) -> dict[str, Path]:
        """List all phase directories for this project."""
        return {phase: self.project_dir / folder for phase, folder in self.PHASES.items()}

    def write_manifest(self, data: dict):
        """Write manifest JSON to output phase."""
        path = self.get_manifest_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Path Manager - show example paths")
    parser.add_argument("--project", default="demo-project", help="Project name")
    parser.add_argument("--config", help="Path to config.json")
    args = parser.parse_args()

    pm = PathManager(args.project, config_path=args.config)
    print(f"Project: {pm.project_name}")
    print(f"Project Dir: {pm.project_dir}")
    print()
    print("Example paths:")
    print(f"  Preview:      {pm.get_preview_path(1, 1)}")
    print(f"  Layer Plan:   {pm.get_layer_plan_path()}")
    print(f"  Layer (bg):   {pm.get_layer_path('background')}")
    print(f"  Refined Prev: {pm.get_refinement_preview_path()}")
    print(f"  Final Layer:  {pm.get_final_layer_path('button_primary')}")
    print(f"  Output Prev:  {pm.get_output_preview_path()}")
    print(f"  Variant:      {pm.get_variant_path('submit_btn', 'hover')}")
    print(f"  Temp:         {pm.get_temp_path()}")
    print(f"  Manifest:     {pm.get_manifest_path()}")
    print()
    print("Size computation examples:")
    # Downsized early phase size
    dw, dh = PathManager.compute_downsized_size(1920, 1080)
    print(f"  1920x1080 downsize (0.5): {dw}x{dh}")
    # Model compliance check
    print(f"  960x540 compliant? {PathManager.is_size_compliant(960, 540)}")
    # Smallest compliant size for 16:9
    cw, ch = PathManager.compute_compliant_size(1920, 1080)
    print(f"  1920x1080 min compliant:  {cw}x{ch}")
    # Early phase with compliance
    ew, eh = PathManager.compute_early_phase_size(1920, 1080)
    print(f"  1920x1080 early phase:    {ew}x{eh}")
    # 1:1 example
    ew, eh = PathManager.compute_early_phase_size(1024, 1024)
    print(f"  1024x1024 early phase:    {ew}x{eh}")
    # 4:3 example
    ew, eh = PathManager.compute_early_phase_size(800, 600)
    print(f"  800x600 early phase:      {ew}x{eh}")


if __name__ == "__main__":
    main()
