"""1D self-similarity matcher for grid/list periodic layouts.

For repeat layers (grid/list) we know in advance that the element repeats along
one or two axes.  We've validated the following pipeline against the
``memento-mori-backpack`` 3×3 inventory grid where the LLM-rendered slots sat
slightly outside the planned ROI:

1. **Period from 1D autocorrelation.**  Project the gradient magnitude onto
   each axis and look at the autocorrelation peaks.  The strongest autocorr
   peak occasionally lands on a sub-cell harmonic (inner-border distance), so
   when a hint period is supplied we keep all peaks within 50 % of the best
   and pick the closest to the hint.

2. **Phase via 1D comb filter.**  For each candidate offset φ ∈ [0, period)
   we sum the gradient profile at φ, φ+period, φ+2·period, ….  The maximum
   identifies where the cell outer-left/outer-top borders sit, regardless of
   whether the leftmost cell falls slightly inside, on, or just outside the
   ROI's edge.  This replaces the bounded 2D template SSD scheme that only
   succeeded when the leftmost cell was strictly inside the ROI.

3. **Cell size + gap.**  When a template (the cropped repeat element PNG) is
   provided, the alpha bounding box of the template resized to the planned
   cell-size gives an accurate ``cell_w/cell_h`` (and the LLM does not change
   the slot's aspect ratio dramatically). When no template is given we fall
   back to ``hints["cell_w"]`` / ``hints["cell_h"]``.  Either way we derive
   ``gap = period − cell_size``.

To accommodate cells that are slightly outside the planned ROI (because the
LLM nudged the grid), we expand the ROI by an internal margin (default
``period_hint`` if available, or the ROI's own short side / 4) before doing
detection.  Cells whose outer-left lies before the unexpanded ROI's left edge
are still emitted in canvas coordinates — downstream renderers can decide
whether to clip them.

Returns:
- origin (x, y): top-left of the first cell in canvas/preview coords
- cell_size (w, h)
- gap (gx, gy)
- rows, cols, cells[]
- per-axis confidence scores
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class AxisResult:
    period: int
    phase: int          # offset of first cell start within the ROI
    cell_size: int
    gap: int
    count: int          # number of cells along this axis
    confidence: float   # autocorrelation peak height in [0, 1]


@dataclass
class GridPeriodicityResult:
    mode: str           # "grid" or "list"
    origin_x: int
    origin_y: int
    cell_w: int
    cell_h: int
    gap_x: int
    gap_y: int
    rows: int
    cols: int
    cells: list[dict]
    confidence: float
    timing_ms: float
    per_axis: dict      # {"x": AxisResult, "y": AxisResult} as dicts


# ---------------------------------------------------------------------------
# Profile preparation
# ---------------------------------------------------------------------------

def _gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    """Cheap gradient magnitude via central differences."""
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    return np.sqrt(gx * gx + gy * gy)


def _smooth1d(x: np.ndarray, k: int = 3) -> np.ndarray:
    if k <= 1:
        return x
    kernel = np.ones(k, dtype=np.float64) / k
    return np.convolve(x, kernel, mode="same")


def _autocorr_fft(x: np.ndarray) -> np.ndarray:
    """Linear autocorrelation via zero-padded FFT, normalized so corr[0] = 1."""
    n = len(x)
    if n < 4:
        return np.zeros(n)
    pad = 1
    while pad < 2 * n:
        pad *= 2
    f = np.fft.rfft(x, n=pad)
    ac = np.fft.irfft(f * np.conj(f), n=pad)[:n]
    if ac[0] <= 0:
        return np.zeros(n)
    return ac / ac[0]


# ---------------------------------------------------------------------------
# Cell decomposition: hint-based fallback (used when no template is given)
# ---------------------------------------------------------------------------

def _hint_phase(profile: np.ndarray, period: int, cell_size: int) -> int:
    """Locate the first cell when only a cell_size hint is available (no
    template).  Picks the offset within [0, period) whose length-cell_size
    window has maximal centred energy — i.e. where the high-energy cell sits
    inside the window.
    """
    n = len(profile)
    if period <= 0 or cell_size <= 0 or cell_size > period or cell_size > n:
        return 0
    p = profile.astype(np.float64) - float(profile.mean())
    csum = np.cumsum(np.concatenate([[0.0], p]))
    upper = min(period, n - cell_size + 1)
    best_score = -np.inf
    best_shift = 0
    for shift in range(max(1, upper)):
        end = shift + cell_size
        s = float(csum[end] - csum[shift])
        if s > best_score:
            best_score = s
            best_shift = shift
    return int(best_shift)


def _comb_phase(profile: np.ndarray, period: int) -> tuple[int, float]:
    """Find the phase φ ∈ [0, period) that maximises the AVERAGE per-tooth
    response of a comb of teeth at period intervals.

    Intuition: cell outer-borders show up as gradient spikes at positions
    spaced exactly one period apart.  A comb with teeth at φ, φ+P, φ+2P, …
    aligned with the spikes has a high mean score; one offset by half a
    period sits in the gaps and scores low.

    We score by the *mean* per tooth (not the sum) because phases close to
    the ROI edges produce fewer teeth — using the sum biases toward phases
    near the left/top of the ROI even when those teeth aren't truly hitting
    cell borders.  The mean is comparable across phases.

    Returns (phase, mean_normalised_score) where the score is the mean of
    profile values divided by the profile's max — a value in [0, 1].
    """
    n = len(profile)
    if n < period or period <= 0:
        return 0, 0.0
    p = profile.astype(np.float64)
    pmax = float(p.max())
    if pmax <= 0:
        return 0, 0.0
    norm = p / pmax
    best_score = -np.inf
    best_phase = 0
    for phase in range(period):
        idx = np.arange(phase, n, period)
        if idx.size == 0:
            continue
        score = float(norm[idx].mean())
        if score > best_score:
            best_score = score
            best_phase = phase
    return int(best_phase), float(best_score)


# ---------------------------------------------------------------------------
# Template handling
# ---------------------------------------------------------------------------

def _alpha_bbox(alpha: np.ndarray, threshold: float = 0.05) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) of the alpha mask's content bbox."""
    mask = alpha > threshold
    if not mask.any():
        return 0, 0, alpha.shape[1], alpha.shape[0]
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    return int(cols[0]), int(rows[0]), int(cols[-1] + 1), int(rows[-1] + 1)


def _resize_template(
    template_rgba: np.ndarray, target_w: int, target_h: int
) -> tuple[np.ndarray, np.ndarray]:
    """Resize an RGBA template (H,W,4 uint8 or float) to target_w/target_h.

    Returns (rgb float32 in [0,255], alpha float32 in [0,1]).
    """
    if template_rgba.dtype != np.uint8:
        rgba_u8 = np.clip(template_rgba, 0, 255).astype(np.uint8)
    else:
        rgba_u8 = template_rgba

    img = Image.fromarray(rgba_u8, mode="RGBA")
    img = img.resize((max(1, int(target_w)), max(1, int(target_h))), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float32)
    rgb = arr[..., :3]
    alpha = arr[..., 3] / 255.0
    rgb[alpha < 0.02] = 0.0
    return rgb, alpha


def _template_axis_kernels(
    template_rgba: np.ndarray, cell_w_hint: int, cell_h_hint: int
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, tuple[int, int]]:
    """Resize the template to (cell_w_hint, cell_h_hint) and return (rgb,
    alpha, alpha_bbox-cropped flag, (cell_w, cell_h)) where cell_w/h is the
    alpha bbox inside the resized template.

    Returns (rgb, alpha, _, (cell_w, cell_h)) — `_` is unused but kept for
    backwards compatibility.
    """
    if cell_w_hint < 4 or cell_h_hint < 4:
        return None, None, None, (cell_w_hint, cell_h_hint)
    if template_rgba is None:
        return None, None, None, (cell_w_hint, cell_h_hint)

    rgb, alpha = _resize_template(template_rgba, cell_w_hint, cell_h_hint)
    x0, y0, x1, y1 = _alpha_bbox(alpha)
    cell_w = max(1, x1 - x0)
    cell_h = max(1, y1 - y0)
    rgb_c = rgb[y0:y1, x0:x1]
    alpha_c = alpha[y0:y1, x0:x1]
    return rgb_c, alpha_c, None, (cell_w, cell_h)


def _ssd_2d(
    sub_rgb: np.ndarray, tpl_rgb: np.ndarray, tpl_alpha: np.ndarray,
    max_y: int, max_x: int,
) -> tuple[int, int, float]:
    """Brute-force alpha-weighted SSD over a search window.

    Slides `tpl_rgb` over `sub_rgb[0:max_y+th-1, 0:max_x+tw-1]` and returns
    the (y, x) of the minimum-SSD position plus the SSD value.  `max_y`/
    `max_x` are exclusive upper bounds of the *origin* search range (so we
    consider origins (y, x) for 0 ≤ y < max_y and 0 ≤ x < max_x).

    For our use case the search window is at most one period in each axis
    (~110×110) and the template is ~90×95 — totals ~10K positions, which is
    a few million ops at np.float64 speed: well under 100 ms.
    """
    H, W = sub_rgb.shape[:2]
    th, tw = tpl_rgb.shape[:2]
    if th > H or tw > W or max_y <= 0 or max_x <= 0:
        return 0, 0, float("inf")

    weight = tpl_alpha[..., np.newaxis] if tpl_rgb.ndim == 3 else tpl_alpha
    weighted_tpl = weight * tpl_rgb if tpl_rgb.ndim == 3 else weight * tpl_rgb

    best_ssd = float("inf")
    best_y = 0
    best_x = 0
    upper_y = min(max_y, H - th + 1)
    upper_x = min(max_x, W - tw + 1)
    for y in range(upper_y):
        for x in range(upper_x):
            patch = sub_rgb[y:y + th, x:x + tw]
            diff = (patch - tpl_rgb) * weight if tpl_rgb.ndim == 3 else (patch - tpl_rgb) * weight
            ssd = float(np.sum(diff * diff))
            if ssd < best_ssd:
                best_ssd = ssd
                best_y = y
                best_x = x
    return best_y, best_x, best_ssd


# ---------------------------------------------------------------------------
# Per-axis period analysis
# ---------------------------------------------------------------------------

def _axis_period(
    profile: np.ndarray,
    min_period: int,
    max_period: int,
    hint_period: int | None,
    min_corr: float,
    count_hint: int = 0,
    roi_extent: int = 0,
) -> tuple[int, float]:
    """Run autocorrelation on a 1D profile and return (period, confidence).

    When a `hint_period` is provided, prefer the autocorrelation peak nearest
    to the hint among any peak whose correlation is at least 50 % of the
    overall best — this lets us slip past a stronger sub-period harmonic when
    the planner has a reasonable estimate of the true period.

    When `count_hint > 1` and `roi_extent > 0` are both supplied (e.g. a
    `cols`/`rows` from the planner), we additionally prefer peaks whose period
    would yield a cell count within ±1 of the hint over peaks that are close
    to the hint period but produce wildly different counts.  This is the lever
    that defeats auto-panel border harmonics: the panel often spawns a strong
    peak at a period that is between the true cell period and the next
    sub-harmonic, which is "close" to the hint period but produces a clearly
    wrong count.
    """
    profile = profile.astype(np.float64)
    if profile.size < 4:
        return 0, 0.0
    centered = profile - profile.mean()
    smoothed = _smooth1d(centered, k=3)
    ac = _autocorr_fft(smoothed)
    n = len(ac)
    lo = max(2, min_period)
    hi = min(n - 2, max_period)
    if lo >= hi:
        return 0, 0.0

    peaks: list[tuple[int, float]] = []
    for i in range(lo, hi + 1):
        v = ac[i]
        if v < min_corr:
            continue
        if v >= ac[i - 1] and v >= ac[i + 1]:
            peaks.append((i, float(v)))
    if not peaks:
        return 0, 0.0

    peaks.sort(key=lambda p: -p[1])
    best_corr = peaks[0][1]
    if hint_period is not None and hint_period > 0:
        # Peaks within 50 % of the best — wider net than the period-only
        # mode, since the strongest peak can be a sub-cell harmonic.
        candidates = [p for p in peaks if p[1] >= 0.50 * best_corr]

        # AUTO-PANEL DEFENSE.  When an auto-panel surrounds the cells, the
        # panel's outer border can produce a globally dominant autocorr peak
        # at a period spanning the entire ROI (count ≈ 1) — clearly NOT the
        # cell period.  Detect that case (strongest peak's estimated count is
        # absurdly small relative to the planner's count hint) and fall back
        # to the strongest peak whose count is plausible.  We deliberately
        # do NOT use count_hint as a hard "must match exactly" filter: when
        # the LLM renders ±1 cell from the planner's count, the strongest
        # autocorr peak is still the right answer — overriding to a
        # 5x-weaker peak just to make the integer count match would be a
        # net regression.
        if count_hint > 1 and roi_extent > 0:
            def _count_for(period: int) -> int:
                return max(1, int(round(roi_extent / max(1, period))))

            best_period = peaks[0][0]
            best_count = _count_for(best_period)
            best_absurd = (
                best_count <= 1                         # panel-global period
                or best_count > max(2, count_hint * 3)  # tiny sub-cell harmonic
            )
            if best_absurd:
                # Look across ALL peaks for a count-plausible alternative
                # (delta ≤ 1 from hint).  This is what defeats the auto-panel
                # whole-ROI peak in memento-mori-backpack's inventory grid.
                plausible: list[tuple[int, float]] = []
                for p, c in peaks:
                    delta = abs(_count_for(p) - count_hint)
                    if delta <= 1:
                        plausible.append((p, c))
                if plausible:
                    # Prefer the strongest among count-plausible peaks; if
                    # there's a near tie, the one closest to hint_period wins.
                    plausible.sort(
                        key=lambda pc: (-pc[1], abs(pc[0] - hint_period))
                    )
                    return plausible[0]

        candidates.sort(key=lambda p: abs(p[0] - hint_period))
        return candidates[0]
    return peaks[0]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def detect_grid_periodicity(
    preview_rgb: np.ndarray,
    roi: dict,
    mode: str = "grid",
    list_axis: str = "y",
    template_rgba: np.ndarray | None = None,
    hints: dict | None = None,
) -> GridPeriodicityResult | None:
    """Detect grid/list periodicity inside an ROI of the preview.

    Args:
        preview_rgb: float32 array (H, W, 3) in [0, 255], or uint8 (H, W, 3).
        roi: {"x", "y", "width", "height"} in preview coords.
        mode: "grid" or "list".
        list_axis: For list mode only — "x" (horizontal list) or "y" (vertical list).
        template_rgba: Optional cropped repeat-element PNG (H, W, 4) — when
            provided, anchors first-cell origin + exact cell size.
        hints: Optional dict with any of:
            - cell_w, cell_h: planned cell size (drives template scaling, also
              used as a fallback when no template is provided)
            - gap_x, gap_y: planned gap (used only to derive period hint)
            - rows, cols: expected counts (only used for sanity)
            - min_period_x, max_period_x, min_period_y, max_period_y
            - min_corr: minimum autocorrelation peak (default 0.10)
            - margin: pixels to expand the ROI on each side before detection
              (default: max(period_hint, short_side/4)) — lets the algorithm
              find cells that the LLM rendered slightly outside the planned
              area_layout

    Returns:
        GridPeriodicityResult or None if detection fails along required axes.
    """
    import time
    t0 = time.time()

    if preview_rgb.dtype != np.float32 and preview_rgb.dtype != np.float64:
        img = preview_rgb.astype(np.float32)
    else:
        img = preview_rgb
    H, W = img.shape[:2]

    rx = max(0, int(roi.get("x", 0)))
    ry = max(0, int(roi.get("y", 0)))
    rw = int(roi.get("width", W))
    rh = int(roi.get("height", H))
    rx_end = min(W, rx + rw)
    ry_end = min(H, ry + rh)
    if rx_end <= rx or ry_end <= ry:
        return None

    hints = hints or {}
    min_corr = float(hints.get("min_corr", 0.10))

    cell_w_hint = int(hints["cell_w"]) if "cell_w" in hints else 0
    cell_h_hint = int(hints["cell_h"]) if "cell_h" in hints else 0
    gap_x_hint = int(hints.get("gap_x", 0))
    gap_y_hint = int(hints.get("gap_y", 0))
    hint_period_x = cell_w_hint + gap_x_hint if cell_w_hint else None
    hint_period_y = cell_h_hint + gap_y_hint if cell_h_hint else None

    # Period detection runs on the *original* ROI: extending past the planned
    # area_layout often pulls in unrelated content (titles, decorations) and
    # corrupts the autocorrelation peaks.  Phase detection separately runs on
    # a slightly expanded ROI so cells the LLM nudged just outside the
    # planned bounds still get found.
    sub = img[ry:ry_end, rx:rx_end]
    gray = sub.mean(axis=2) if sub.ndim == 3 else sub
    grad = _gradient_magnitude(gray)
    sub_h, sub_w = grad.shape

    # Default search ranges. min_period rejects sub-cell harmonics; max_period
    # caps at the ROI extent so single-row/single-col layouts can still match.
    min_period_x = int(hints.get("min_period_x", max(8, cell_w_hint // 2 if cell_w_hint else 16)))
    max_period_x = int(hints.get("max_period_x", sub_w))
    min_period_y = int(hints.get("min_period_y", max(8, cell_h_hint // 2 if cell_h_hint else 16)))
    max_period_y = int(hints.get("max_period_y", sub_h))

    need_x = mode == "grid" or (mode == "list" and list_axis == "x")
    need_y = mode == "grid" or (mode == "list" and list_axis == "y")

    cols_hint_for_period = int(hints.get("cols", 0) or 0)
    rows_hint_for_period = int(hints.get("rows", 0) or 0)

    # ---- Step 1: Period from 1D autocorrelation along each needed axis ----
    period_x = period_y = 0
    conf_x = conf_y = 0.0
    prof_x_orig = grad.sum(axis=0)
    prof_y_orig = grad.sum(axis=1)
    if need_x:
        period_x, conf_x = _axis_period(
            prof_x_orig, min_period_x, max_period_x, hint_period_x, min_corr,
            count_hint=cols_hint_for_period, roi_extent=sub_w,
        )
        if period_x <= 0:
            return None
    if need_y:
        period_y, conf_y = _axis_period(
            prof_y_orig, min_period_y, max_period_y, hint_period_y, min_corr,
            count_hint=rows_hint_for_period, roi_extent=sub_h,
        )
        if period_y <= 0:
            return None

    if not need_x:
        period_x = max(1, sub_w)
    if not need_y:
        period_y = max(1, sub_h)

    # ---- Step 2: Phase from 1D comb filter on the original ROI ------------
    # We use the original ROI (not an expanded one) for phase detection: the
    # autocorrelation has already locked in the period, and a slightly wider
    # window often pulls in unrelated content (e.g. a section title above the
    # grid) whose edge produces a spurious phase win.  After finding the best
    # phase inside the ROI we extrapolate backward by `period` so cells the
    # LLM rendered just before the ROI's edge are still emitted.
    phase_x = phase_y = 0
    comb_x = comb_y = 0.0
    if need_x:
        phase_x, comb_x = _comb_phase(prof_x_orig, period_x)
    if need_y:
        phase_y, comb_y = _comb_phase(prof_y_orig, period_y)

    # The "phase margin" controls how far the cell *centre* may sit outside
    # the ROI before we reject it.  A quarter cell is permissive enough to
    # absorb LLM-rendered cells that drift one or two dozen pixels past the
    # planned area while staying tight enough to suppress phantom rows
    # extrapolated into a different content region (e.g. a title above the
    # grid).
    phase_margin_x = int(hints.get("phase_margin_x", cell_w_hint // 4 if cell_w_hint else 16))
    phase_margin_y = int(hints.get("phase_margin_y", cell_h_hint // 4 if cell_h_hint else 16))

    # ---- Step 3: Cell size --------------------------------------------------
    # Prefer the template's alpha bbox at the planned cell size.  When no
    # template is provided we fall back to the cell_w/cell_h hint, capped to
    # the period (gap ≥ 0).
    cell_w = cell_h = 0
    used_template = False
    if template_rgba is not None and cell_w_hint > 0 and cell_h_hint > 0:
        _, _, _, (tpl_cell_w, tpl_cell_h) = _template_axis_kernels(
            template_rgba, cell_w_hint, cell_h_hint
        )
        if tpl_cell_w >= 4 and tpl_cell_h >= 4:
            cell_w = min(int(tpl_cell_w), period_x) if need_x else int(tpl_cell_w)
            cell_h = min(int(tpl_cell_h), period_y) if need_y else int(tpl_cell_h)
            used_template = True
    if cell_w <= 0:
        if cell_w_hint > 0:
            cell_w = min(cell_w_hint, period_x) if need_x else cell_w_hint
        elif need_x:
            cell_w = max(1, period_x - max(0, gap_x_hint))
        else:
            cell_w = sub_w
    if cell_h <= 0:
        if cell_h_hint > 0:
            cell_h = min(cell_h_hint, period_y) if need_y else cell_h_hint
        elif need_y:
            cell_h = max(1, period_y - max(0, gap_y_hint))
        else:
            cell_h = sub_h

    gap_x = max(0, period_x - cell_w) if need_x else 0
    gap_y = max(0, period_y - cell_h) if need_y else 0

    # ---- Step 4: Tile cells.  The first cell sits at phase_(x|y) within
    # the ROI.  Walk *backwards* by period as long as the previous cell's
    # centre would still be within `phase_margin` of the original ROI
    # (catches cells the LLM rendered slightly before the planned bounds).
    # Walk forward up to the ROI's far edge.
    canvas_origin_x = rx + phase_x
    canvas_origin_y = ry + phase_y

    # Count how many cells fit going strictly FORWARD from the comb-phase
    # origin — without backward extrapolation.  This is our trusted
    # baseline: the comb-phase already chose the maximum-energy alignment
    # within the ROI, so any cell starting at canvas_origin_x + k·period
    # for k ≥ 0 with its centre inside the ROI corresponds to a peak the
    # comb actually saw.  Walk-back is only safe when this baseline is
    # SHORT of the planner's count — otherwise we manufacture phantom
    # cells from the panel's left/top decoration (e.g. zzz-equipment's
    # equipment_panel produces a strong gradient that the comb already
    # accounted for; walking back one extra period puts a "cell" on the
    # panel's bevel where there is no slot).
    def _forward_count(origin: int, period: int, cell_dim: int, roi_end: int) -> int:
        cnt = 0
        cur = origin
        while cur + cell_dim // 2 <= roi_end:
            cnt += 1
            cur += period
        return cnt

    cols_hint_for_walk = int(hints.get("cols", 0) or 0)
    rows_hint_for_walk = int(hints.get("rows", 0) or 0)

    if need_x:
        forward_x = _forward_count(canvas_origin_x, period_x, cell_w, rx_end)
        # Maximum number of cells we'd accept; default to "no cap" when no hint.
        max_back_x = max(0, cols_hint_for_walk - forward_x) if cols_hint_for_walk > 0 else 10**6
        steps = 0
        while (
            steps < max_back_x
            and canvas_origin_x - period_x + cell_w // 2 >= rx - phase_margin_x
        ):
            canvas_origin_x -= period_x
            steps += 1
    if need_y:
        forward_y = _forward_count(canvas_origin_y, period_y, cell_h, ry_end)
        max_back_y = max(0, rows_hint_for_walk - forward_y) if rows_hint_for_walk > 0 else 10**6
        steps = 0
        while (
            steps < max_back_y
            and canvas_origin_y - period_y + cell_h // 2 >= ry - phase_margin_y
        ):
            canvas_origin_y -= period_y
            steps += 1

    cells: list[dict] = []
    rows_hint = int(hints.get("rows", 0))
    cols_hint = int(hints.get("cols", 0))
    cols = 0
    cx = canvas_origin_x
    while True:
        # Cell is kept if its centre lies inside the ROI (strict forward —
        # we don't extrapolate past the planned right/bottom edge because
        # the LLM more often renders fewer cells than planned, not more).
        if cx + cell_w // 2 > rx_end:
            break
        # Respect the planner's count hint: don't emit ghost columns/rows
        # caused by panel borders or decorative elements outside the true grid.
        if cols_hint > 0 and cols >= cols_hint:
            break
        cols += 1
        cx += period_x
        if not need_x:
            break
    rows = 0
    cy = canvas_origin_y
    while True:
        if cy + cell_h // 2 > ry_end:
            break
        if rows_hint > 0 and rows >= rows_hint:
            break
        rows += 1
        cy += period_y
        if not need_y:
            break
    rows = max(1, rows)
    cols = max(1, cols)

    for r in range(rows):
        for c in range(cols):
            cell_x = canvas_origin_x + c * period_x
            cell_y = canvas_origin_y + r * period_y
            cells.append({
                "row": r,
                "col": c,
                "x": int(cell_x),
                "y": int(cell_y),
                "width": int(cell_w),
                "height": int(cell_h),
            })

    confidence = (
        (conf_x + conf_y) / 2.0 if mode == "grid"
        else (conf_x if list_axis == "x" else conf_y)
    )
    timing_ms = (time.time() - t0) * 1000.0

    axis_x = AxisResult(
        period=int(period_x),
        phase=int(canvas_origin_x - rx) if need_x else 0,
        cell_size=int(cell_w),
        gap=int(gap_x),
        count=int(cols),
        confidence=float(conf_x),
    )
    axis_y = AxisResult(
        period=int(period_y),
        phase=int(canvas_origin_y - ry) if need_y else 0,
        cell_size=int(cell_h),
        gap=int(gap_y),
        count=int(rows),
        confidence=float(conf_y),
    )

    return GridPeriodicityResult(
        mode=mode,
        origin_x=int(canvas_origin_x),
        origin_y=int(canvas_origin_y),
        cell_w=int(cell_w),
        cell_h=int(cell_h),
        gap_x=int(gap_x),
        gap_y=int(gap_y),
        rows=int(rows),
        cols=int(cols),
        cells=cells,
        confidence=float(confidence),
        timing_ms=float(timing_ms),
        per_axis={
            "x": axis_x.__dict__,
            "y": axis_y.__dict__,
            "used_template": used_template,
            "comb_score_x": float(comb_x),
            "comb_score_y": float(comb_y),
            "phase_margin_x": int(phase_margin_x),
            "phase_margin_y": int(phase_margin_y),
        },
    )


def detect_grid_from_paths(
    preview_path: str,
    roi: dict,
    mode: str = "grid",
    list_axis: str = "y",
    template_path: str | None = None,
    hints: dict | None = None,
) -> GridPeriodicityResult | None:
    """Convenience wrapper that opens images by path and calls
    detect_grid_periodicity."""
    img = np.array(Image.open(preview_path).convert("RGB"))
    template_rgba = None
    if template_path:
        tpl = Image.open(template_path)
        if tpl.mode != "RGBA":
            tpl = tpl.convert("RGBA")
        template_rgba = np.array(tpl)
    return detect_grid_periodicity(
        img, roi, mode=mode, list_axis=list_axis,
        template_rgba=template_rgba, hints=hints,
    )
