"""Adaptive multi-feature template matching matchers."""

from .base import BaseMatcher, MatchResult
from .edge_canny import EdgeCannyMatcher
from .fusion import FusionMatcher, _resolve_profile
from .gradient import GradientMatcher
from .rgb_ssd import RgbSsdMatcher

__all__ = [
    "BaseMatcher", "MatchResult", "EdgeCannyMatcher", "FusionMatcher",
    "GradientMatcher", "RgbSsdMatcher", "_resolve_profile",
]
