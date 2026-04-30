# Adaptive Matching Profiles

## Overview

`detect_layer_positions.py` uses a **profile-based multi-feature matching system**. Instead of relying solely on RGB SSD (which is color-sensitive), the matcher can fuse multiple visual features weighted by a profile selected for the UI style.

## How It Works

1. **Agent inspects the preview** (`preview_check_screenshot.png` or `preview.html`)
2. **Classifies the UI style** into one of the preset profiles below
3. **Writes `match_profile.json`** to `output/{project}/match_profile.json`
4. **Detection script reads the profile** and computes only the configured features

If no profile exists, the script falls back to the `default` profile.

## Preset Profiles

### `default` — General UI (safe fallback)

```json
{"profile": "default", "features": {
  "rgb_ssd":    {"weight": 0.25},
  "gradient":   {"weight": 0.35},
  "edge_canny": {"weight": 0.40}
}}
```

Best for: Mixed UIs where no single feature clearly dominates.

### `structure_heavy` — Flat / Minimal / Monochrome

```json
{"profile": "structure_heavy", "features": {
  "gradient":   {"weight": 0.30},
  "edge_canny": {"weight": 0.70}
}}
```

Best for: Flat design, monochrome game UIs, wireframe-like layouts where color is unreliable and structural edges are the primary differentiator.

### `color_heavy` — Colorful / Branded

```json
{"profile": "color_heavy", "features": {
  "color_hsv":  {"weight": 0.50},
  "gradient":   {"weight": 0.25},
  "edge_canny": {"weight": 0.25}
}}
```

Best for: UIs with strong brand colors, gradient buttons, colorful icons where hue is distinctive. When RGB and HSV results diverge significantly, it usually means the preview has global color shifts (e.g. warm/cool tint) that HSV handles better.

### `texture_heavy` — Photographic / Ornate

```json
{"profile": "texture_heavy", "features": {
  "pattern_lbp": {"weight": 0.40},
  "gradient":    {"weight": 0.35},
  "edge_canny":  {"weight": 0.25}
}}
```

Best for: Photographic elements, ornate patterns, detailed artwork where local texture is more informative than global color. Can be less reliable on flat, low-texture regions (e.g. solid-color cards, simple text bars) because LBP has little structure to latch onto.

## Agent Selection Guide

When the user triggers algorithmic alignment ("尝试算法对齐"), the agent MUST:

1. Open `04-check/preview_check_screenshot.png` or `preview.html`
2. Visually assess the dominant visual characteristics
3. Choose the profile using this decision tree:

```
Is the UI mostly flat, monochrome, or wireframe-like?
  ├─ YES → structure_heavy
  └─ NO → Are colors strong, branded, or highly saturated?
       ├─ YES → color_heavy
       └─ NO → Are there photographic textures or ornate patterns?
            ├─ YES → texture_heavy
            └─ NO → default
```

### Visual Cues

| Profile | Visual Cues in Preview |
|---------|----------------------|
| `structure_heavy` | Thin outlines, wireframes, monochrome palette, card boundaries, divider lines |
| `color_heavy` | Vibrant buttons, gradient backgrounds, colorful icons, strong brand colors |
| `texture_heavy` | Photographic portraits, ornate frames, wood/metal textures, fabric patterns |
| `default` | Mixed: some color + some structure + some texture, or hard to categorize |

## Feature Reference

| Feature | What It Captures | Color Invariant | Best For |
|---------|-----------------|-----------------|----------|
| `rgb_ssd` | Raw pixel colors (alpha-weighted) | ❌ No | Exact color matching, brand-specific controls |
| `gradient` | Sobel gradient magnitude | ✅ Yes | Edge presence, shape boundaries |
| `edge_canny` | Canny edge → distance transform | ✅ Yes | Precise structural alignment, thin outlines |
| `color_hsv` | Hue-Saturation histogram | Partial | Color-branding, themed controls |
| `pattern_lbp` | Local Binary Pattern texture | ✅ Yes | Photographic surfaces, ornate details |

## Single-Feature Quick Reference

When in doubt, **always use `default`**. Only switch to a specialized profile when the preview clearly falls into one of the categories below.

| Profile | When to Use | When NOT to Use |
|---------|-------------|-----------------|
| **`default`** | General-purpose fallback. Mixed UIs with color + structure + some texture. | — |
| `structure_heavy` | Flat/minimal/monochrome UIs; thin outlines and card boundaries dominate. | Colorful branded UIs, photographic content, or where edges are soft/blurred. |
| `color_heavy` | Strong brand colors, saturated gradients, colorful icons; hue is the clearest cue. | Monochrome or low-saturation UIs where color is unreliable. |
| `texture_heavy` | Photographic portraits, ornate frames, wood/metal/fabric textures. | Flat solid-color regions, simple text bars, or low-texture panels. |

### Why `default` is usually best

`default` fuses `rgb_ssd` (0.25) + `gradient` (0.35) + `edge_canny` (0.40). In practice:
- If **one feature fails** (e.g. edge_canny on a soft-gradient banner), the other two still vote correctly.
- If **two features agree** (e.g. rgb_ssd + gradient both point to the same location), that location is very likely correct.
- Single-feature profiles are mainly useful for **diagnosis** ("which feature is causing the misalignment?") rather than production use.

## Implementation Status

| Feature | Status |
|---------|--------|
| `rgb_ssd` | ✅ Implemented |
| `gradient` | ✅ Implemented |
| `edge_canny` | ✅ Implemented |
| `color_hsv` | ✅ Implemented |
| `pattern_lbp` | ✅ Implemented |

## File Format

`output/{project}/match_profile.json`:

```json
{
  "profile": "structure_heavy",
  "features": {
    "gradient": {"weight": 0.30},
    "edge_canny": {"weight": 0.70}
  }
}
```

- `profile`: Human-readable name (for logging)
- `features`: Map of feature name → `{weight: float}`
- Weights are normalized internally; they do not need to sum to 1.0
