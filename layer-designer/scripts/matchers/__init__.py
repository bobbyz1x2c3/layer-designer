"""Adaptive multi-feature template matching matchers."""

from .base import BaseMatcher, MatchResult
from .fusion import FusionMatcher
from .rgb_ssd import RgbSsdMatcher
from .gradient import GradientMatcher

__all__ = ["BaseMatcher", "MatchResult", "FusionMatcher", "RgbSsdMatcher", "GradientMatcher"]
