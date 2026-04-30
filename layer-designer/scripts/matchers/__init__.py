"""Adaptive multi-feature template matching matchers."""

from .base import BaseMatcher, MatchResult
from .color_hsv import ColorHsvMatcher
from .edge_canny import EdgeCannyMatcher
from .fusion import FusionMatcher, _resolve_profile
from .gradient import GradientMatcher
from .pattern_lbp import PatternLbpMatcher
from .rgb_ssd import RgbSsdMatcher

__all__ = [
    "BaseMatcher", "MatchResult",
    "ColorHsvMatcher", "EdgeCannyMatcher",
    "FusionMatcher", "GradientMatcher",
    "PatternLbpMatcher", "RgbSsdMatcher",
    "_resolve_profile",
]
