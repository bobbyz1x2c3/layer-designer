"""Adaptive multi-feature template matching matchers."""

from .base import BaseMatcher, MatchResult
from .fusion import FusionMatcher, _resolve_profile
from .rgb_ssd import RgbSsdMatcher
from .gradient import GradientMatcher

__all__ = ["BaseMatcher", "MatchResult", "FusionMatcher", "RgbSsdMatcher", "GradientMatcher", "_resolve_profile"]
