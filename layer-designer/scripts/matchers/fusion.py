"""Weighted multi-feature fusion matcher."""

from pathlib import Path

import numpy as np

from .base import BaseMatcher, MatchResult
from .color_hsv import ColorHsvMatcher
from .edge_canny import EdgeCannyMatcher
from .gradient import GradientMatcher
from .pattern_lbp import PatternLbpMatcher
from .rgb_ssd import RgbSsdMatcher


# Preset profiles shipped with the codebase
PRESET_PROFILES = {
    "default": {
        "rgb_ssd": {"weight": 0.25},
        "gradient": {"weight": 0.35},
        "edge_canny": {"weight": 0.40},
    },
    "structure_heavy": {
        "gradient": {"weight": 0.30},
        "edge_canny": {"weight": 0.70},
    },
    "color_heavy": {
        "color_hsv": {"weight": 0.50},
        "gradient": {"weight": 0.25},
        "edge_canny": {"weight": 0.25},
    },
    "texture_heavy": {
        "pattern_lbp": {"weight": 0.40},
        "gradient": {"weight": 0.35},
        "edge_canny": {"weight": 0.25},
    },
}

# Feature name → Matcher class (available now)
_MATCHER_REGISTRY: dict[str, type[BaseMatcher]] = {
    "rgb_ssd": RgbSsdMatcher,
    "gradient": GradientMatcher,
    "edge_canny": EdgeCannyMatcher,
    "color_hsv": ColorHsvMatcher,
    "pattern_lbp": PatternLbpMatcher,
}


def _resolve_profile(profile_arg: str | Path | dict | None, project_dir: Path | None = None) -> dict:
    """Resolve a profile from argument, file, or preset.

    Priority:
    1. dict → use directly
    2. path → load JSON
    3. preset name → use PRESET_PROFILES
    4. project_dir / match_profile.json → auto-detect
    5. None → default preset
    """
    if isinstance(profile_arg, dict):
        return profile_arg

    if isinstance(profile_arg, Path) or (isinstance(profile_arg, str) and Path(profile_arg).suffix == ".json"):
        path = Path(profile_arg)
        if path.exists():
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("features", data)

    if isinstance(profile_arg, str) and profile_arg in PRESET_PROFILES:
        return PRESET_PROFILES[profile_arg]

    # Auto-detect from project directory
    if project_dir is not None:
        auto_path = project_dir / "match_profile.json"
        if auto_path.exists():
            import json
            with open(auto_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("features", data)

    # Final fallback
    return PRESET_PROFILES["default"]


class FusionMatcher:
    """Orchestrates multiple feature matchers with weighted fusion.

    Not a BaseMatcher subclass — it manages multiple matchers internally.
    """

    def __init__(self, profile: dict, downsample: int = 4):
        self.downsample = downsample
        self.matchers: dict[str, BaseMatcher] = {}
        self.weights: dict[str, float] = {}

        for name, cfg in profile.items():
            cls = _MATCHER_REGISTRY.get(name)
            if cls is None:
                # Skip unimplemented features silently (e.g. edge_canny in Phase 1)
                continue
            self.matchers[name] = cls()
            self.weights[name] = cfg.get("weight", 1.0)

        if not self.matchers:
            # Absolutely nothing available — fall back to rgb_ssd
            self.matchers["rgb_ssd"] = RgbSsdMatcher()
            self.weights["rgb_ssd"] = 1.0

    def extract(self, template_rgb: np.ndarray, template_alpha: np.ndarray) -> dict[str, object]:
        """Extract descriptors from all configured matchers."""
        return {
            name: matcher.extract(template_rgb, template_alpha)
            for name, matcher in self.matchers.items()
        }

    def match(
        self,
        roi_rgb: np.ndarray,
        descriptors: dict[str, object],
        scale: float,
    ) -> MatchResult:
        """Run all matchers, normalize scores, fuse, and return best result."""
        results: dict[str, MatchResult] = {}
        for name, matcher in self.matchers.items():
            desc = descriptors[name]
            results[name] = matcher.match(roi_rgb, desc, scale)

        # Normalize each score map to [0, 1] then weighted sum
        # For single-feature mode, skip normalization so raw scores are comparable across scales
        fused = None
        total_weight = 0.0
        single_mode = len(results) == 1
        for name, res in results.items():
            w = self.weights[name]
            if single_mode:
                norm = res.score_map
            else:
                norm = _normalize_score(res.score_map)
            if fused is None:
                fused = w * norm
            else:
                fused += w * norm
            total_weight += w

        if total_weight > 0:
            fused /= total_weight

        best_idx = np.unravel_index(np.argmax(fused), fused.shape)
        return MatchResult(
            score_map=fused,
            scale=scale,
            best_score=float(fused[best_idx]),
            best_y=int(best_idx[0]),
            best_x=int(best_idx[1]),
        )


def _normalize_score(score_map: np.ndarray) -> np.ndarray:
    """Min-max normalize to [0, 1]."""
    smin = float(score_map.min())
    smax = float(score_map.max())
    if smax - smin < 1e-12:
        return np.zeros_like(score_map)
    return (score_map - smin) / (smax - smin)
