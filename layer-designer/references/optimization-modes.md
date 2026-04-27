# Optimization Modes

## Table of Contents
1. [Parallel Generation](#parallel-generation)
2. [Downsized Early Phases](#downsized-early-phases)
3. [Incremental Update](#incremental-update)
4. [Quality Adaptive](#quality-adaptive)
5. [Style Anchor Hint](#style-anchor-hint)
6. [Configuration Summary](#configuration-summary)

---

## Parallel Generation

**Goal**: Reduce wall-clock time by generating independent images concurrently.

**Applicable phases**:
- Phase 3 (Rough Design): All N layers are independent
- Phase 4 (Rework): All problematic layers can be regenerated in parallel
- Phase 6 (Refinement Layers): All N layers are independent
- Phase 8 (Variants/States): All M×K control states are independent

**Implementation**:
- If the agent has subagent/session creation capability:
  - Spawn one subagent per independent generation task
  - Each subagent receives: prompt, reference image, output path, size, quality
  - Master agent waits for all subagents to complete, then proceeds
- If no subagent capability:
  - Fall back to sequential generation
  - No functional difference, only slower

**Benefit**: Wall-clock time reduced by ~60% for multi-layer designs.

**Config**:
```json
"parallel_generation": true,
"parallel_max_workers": 8
```

---

## Downsized Early Phases

**Goal**: Reduce generation cost and latency in early phases by using a reduced resolution, while ensuring the result remains compatible with the image generation model's constraints.


### gpt-image-2 Model Size Constraints

When using `gpt-image-2` (or any model with similar constraints), all generation requests must satisfy:

| Constraint | Value | Violation Result |
|-----------|-------|-----------------|
| **Max edge** | ≤ 3840 px | 502 Bad Gateway |
| **Edge alignment** | Must be multiple of 16 | 502 Bad Gateway |
| **Max aspect ratio** | long/short ≤ 3:1 | 502 Bad Gateway |
| **Min total pixels** | ≥ 655,360 (~1024×640) | 502 Bad Gateway |
| **Max total pixels** | ≤ 8,294,400 (~4K) | 502 Bad Gateway |

### Early-Phase Compliance Behavior

If the downscaled size `(W/2) × (H/2)` violates model constraints, the system **does NOT fall back to full size**. Instead, it computes the **smallest compliant size** that preserves the original aspect ratio. This keeps early-phase costs low while avoiding API errors.

**Example**:

| User Request | Raw Downsize (0.5×) | Compliant? | Actual Phase 1~4 Size | Phase 5~8 Size |
|-------------|---------------------|-----------|----------------------|---------------|
| 1920 × 1080 | 960 × 540 | ❌ (below min pixels) | **1088 × 608** | 1920 × 1080 |
| 1024 × 1024 | 512 × 512 | ❌ (below min pixels) | **816 × 816** | 1024 × 1024 |
| 1280 × 720 | 640 × 360 | ❌ (below min pixels) | **704 × 400** | 1280 × 720 |
| 800 × 600 | 400 × 300 | ❌ (below min pixels) | **944 × 704** | 800 × 600 |
| 3840 × 2160 | 1920 × 1080 | ✅ | 1920 × 1080 | 3840 × 2160 |
| 200 × 150 | — | — | **640 × 480** | **640 × 480** |

> **Note**: For 200×150, the original is below thresholds so no downsize is applied, but the original itself violates min-pixel constraint. The system returns the smallest compliant size (640×480).

### When User Requests an Invalid Size

If the user's requested target size itself violates model constraints (e.g., aspect ratio > 3:1, or dimensions not multiples of 16):
1. **Do NOT silently adjust.** Inform the user of the constraint violation.
2. Present the nearest valid size options (preserving their intended aspect ratio as closely as possible).
3. Ask the user to confirm or revise before proceeding.

**Example dialog**:
> User: "I want a 4000×1000 banner."
> Agent: "The requested size 4000×1000 exceeds gpt-image-2 constraints:
> - Max edge is 3840px (you requested 4000px)
> - Aspect ratio is 4:1, max allowed is 3:1
> Suggested alternatives:
> - 3840 × 960 (preserves 4:1 ratio → capped at 3:1 → 3840 × 1280)
> - 3840 × 1280 (3:1 ratio)
> - 3840 × 1920 (2:1 ratio)
> Please confirm which size to use."

**Implementation**:
```python
from path_manager import PathManager

# Check if a size is compliant
compliant = PathManager.is_size_compliant(960, 540)
# → False (960×540 = 518,400 < 655,360 min pixels)

# Find smallest compliant size preserving ratio
cw, ch = PathManager.compute_compliant_size(1920, 1080)
# → (1088, 608)

# Compute early-phase size (handles downsize + compliance in one call)
ew, eh = PathManager.compute_early_phase_size(1920, 1080)
# → (1088, 608)
```

**Config**:
```json
"model_constraints": {
  "gpt-image-2": {
    "max_edge": 3840,
    "align": 16,
    "max_ratio": 3.0,
    "min_pixels": 655360,
    "max_pixels": 8294400
  }
},
"downsize_early_phases": true,
"downsize_ratio": 0.5,
"downsize_threshold_width": 300,
"downsize_threshold_height": 200,
"downsize_threshold_pixels": 60000
```

---

## Incremental Update

**Goal**: When user requests a small change, regenerate only the affected subset instead of the full workflow.

**Trigger**: User input indicates a partial modification, e.g.:
- "Change the button color to red"
- "Add a search icon to the header"
- "Remove the sidebar"
- "Add a disabled state for the submit button"

**Process**:
1. Parse user request to identify affected scope:
   - Single layer modification → only that layer
   - Single control state addition → only that control's variant
   - Style-only change → Phase 1 preview + Phase 5~6 (skip Phase 3 if layout unchanged)
2. Load existing `manifest.json` from `07-output/` (or latest available phase)
3. Diff against current state to determine minimal regeneration set
4. Execute only necessary phases for the affected items
5. Generate final web preview with reused + new layers

**Benefit**: Small changes drop from ~28 images to 3~5 images.

**Config**:
```json
"incremental_update": true
```

---

## Quality Adaptive

**Goal**: Reduce API cost by matching `quality` parameter to actual content complexity.

**Tier Assignment** (during Phase 2 Confirmation):

| Layer Content | Rough Design (Phase 3) | Refinement (Phase 6) |
|--------------|----------------------|---------------------|
| Solid color / simple gradient background | low | medium |
| Simple geometric shapes (cards, dividers) | low | high |
| Text-heavy elements (labels, headers) | medium | high |
| Complex icons / illustrations | medium | high |
| Photographic / detailed artwork | medium | high |

**Why**: Simple layers do not benefit from `high` quality; the visual difference is imperceptible but API cost is significantly higher.

**Implementation**: During Phase 2 layer planning, assign `quality_tier` to each layer. Scripts read this tier when calling generation.

**Config**:
```json
"quality_adaptive": true
```

---

## Style Anchor Hint

**Goal**: Implicitly improve style consistency without adding an explicit pre-generation step.

**Method**: During Phase 2 Confirmation, include a **style summary** in the `layer_plan.json`:
```json
{
  "style_anchor": "Flat design, primary blue #3B82F6, Inter font, 8px grid, rounded 12px corners, soft shadows",
  "style_reference_image": "01-requirements/previews/preview_v2_001_20250424_163000.png"
}
```

All subsequent generation prompts (Phase 3~8) **must prefix or append** this style anchor. This is not a separate generation step—just a prompt engineering discipline extracted from the confirmed preview.

**Benefit**: Reduces Phase 4 rework rate without costing an extra image generation.

---

## Configuration Summary

All optimization settings live in `config.json` under the `"workflow"` section:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `parallel_generation` | bool | true | Enable parallel subagent generation |
| `parallel_max_workers` | int | 8 | Max concurrent subagents |
| `downsize_early_phases` | bool | true | Use half-resolution in Phase 1~4 |
| `downsize_ratio` | float | 0.5 | Scale factor for early phases |
| `downsize_threshold_width` | int | 300 | Min width to trigger downsize |
| `downsize_threshold_height` | int | 200 | Min height to trigger downsize |
| `downsize_threshold_pixels` | int | 60000 | Min pixel count to trigger downsize |
| `incremental_update` | bool | true | Enable incremental update for small changes |
| `quality_adaptive` | bool | true | Enable per-layer quality tier assignment |
