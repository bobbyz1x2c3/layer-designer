"""Abstract base class for template matching features."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class MatchResult:
    """Result of a single-scale template match."""

    score_map: np.ndarray  # score at every position; higher = better match
    scale: float  # scale factor used for this match
    best_score: float  # maximum score value
    best_y: int  # y index of best score (in score_map coordinates)
    best_x: int  # x index of best score (in score_map coordinates)


class BaseMatcher(ABC):
    """Abstract matcher for a single visual feature.

    Subclasses implement:
    - extract(template): precompute feature descriptor from template
    - match(roi, descriptor, scale): compute score map for ROI at given scale
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def extract(self, template_rgb: np.ndarray, template_alpha: np.ndarray) -> object:
        """Extract feature descriptor from template.

        Args:
            template_rgb: float32 array (H, W, 3)
            template_alpha: float32 array (H, W) in [0, 1]

        Returns:
            An opaque descriptor object specific to this matcher.
        """
        ...

    @abstractmethod
    def match(
        self,
        roi_rgb: np.ndarray,
        descriptor: object,
        scale: float,
    ) -> MatchResult:
        """Match template descriptor against ROI at given scale.

        Args:
            roi_rgb: float32 array (H, W, 3)
            descriptor: object returned by extract()
            scale: scale factor applied to template (for logging)

        Returns:
            MatchResult with score_map where higher = better match.
        """
        ...
