---
name: layered-design-generator
description: Generate professional UI/UX designs as layered PSD-like outputs with transparent layers. Supports complete 8-phase workflows from requirements to final output. Use when the user asks to create UI/UX designs, generate layered images, produce design mockups with transparent backgrounds, or work with any multi-layer design workflow including requirements gathering, preview generation, rough design, composition check, refinement, and state variants (hover/active/disabled).
---

# Layered Design Generator

Generate professional UI/UX designs as layered PSD-like outputs with transparent layers.

---

## 0. Setup & Installation

When the user says **"开始部署"**, **"开始安装"**, or asks how to set up the project:

1. Read [`references/setup-guide.md`](references/setup-guide.md) **before** performing any setup actions.
2. Follow the interactive setup flow in that document — do NOT silently run `setup.py` without user interaction.

Key interaction points:
- Ask about API configuration (provider, base_url, api_key, model)
- Ask which matting model to use (`u2net`, `birefnet-general`, etc.) with size/quality trade-offs
- If the user communicates in Chinese, explicitly ask whether to use a download mirror (e.g. `https://github.tbedu.top`)
- Install dependencies and download models according to user choices

---

## 1. Prerequisites

- Python 3.9+
- `openai` package (`pip install openai`)
- `Pillow` package (`pip install Pillow`)
- `config.json` with API endpoint and model configuration

No build system required. Run scripts directly via `python scripts/<script>.py`.

---

## 2. Configuration (`config.json`)

Single source of truth. Key sections:

| Section | Key Fields |
|---------|-----------|
| `api` | `model` (default `gpt-image-2`) |
| `model_constraints.gpt-image-2` | `max_edge: 3840`, `align: 16`, `max_ratio: 3.0`, `min_pixels: 655360`, `max_pixels: 8294400` |
| `workflow` | `downsize_early_phases`, `quality_adaptive`, `fast_workflow`, `parallel_generation`, `parallel_max_workers` |
| `paths` | `output_root`, `references_dir`, `output_dir` |

---

## 3. API Timeout Guidelines

When invoking `generate_image.py` (or any image generation API), set request timeouts according to quality and resolution to avoid premature failures:

| Quality | Resolution | Safe Timeout |
|---------|-----------|-----------------|
| `low` | ≤ 1024×1024 | **150 seconds** |
| `medium` | ≤ 1024×1024 | 150–180 seconds |
| `high` | ≤ 1024×1024 | 180-200 seconds |
| `low` | 2K (e.g. 1792×1024) | 180-200 seconds |
| `medium` | 2K | 200-250 seconds |
| `high` | 2K+ (e.g. 2048×2048, 4K) | **300+ seconds** |

**Rule of thumb**: Add ~100s for each quality tier step (low → medium → high) and ~100s for each resolution doubling (1K → 2K → 4K).

**Implementation**: Pass timeout via your HTTP client or async task poller configuration. For `generate_image.py` async mode, set `poll_interval` and `timeout` in `config.json` under `api.{provider}.async_config`.

---

## 4. Model Capability Check

| Capability | Requirement | Default |
|-----------|-------------|---------|
| Image editing | `image-to-image` support | ✅ |
| Transparency | Alpha channel in output | ✅ |
| High resolution | >= 1024×1024 or 1792×1024 | ✅ |

If the agent's native image model supports image-to-image editing with transparency, use it directly. Otherwise fall back to `scripts/generate_image.py`.

---

## 5. Input Modes

| Mode | Description | When to Use |
|------|-------------|-------------|
| **Text-to-Image** (default) | User describes design, agent generates preview | No existing design |
| **Reference-Image** | User uploads wireframe/mockup, agent edits it | Have existing design |

In reference-image mode, save the uploaded image to `01-requirements/references/`.

---

## 6. Model Size Constraints (HARD — 502 if violated)

- **Max edge**: ≤ 3840px
- **Alignment**: Both edges must be multiples of 16
- **Aspect ratio**: ≤ 3:1
- **Min pixels**: ≥ 655,360 (~1024×640)
- **Max pixels**: ≤ 8,294,400 (~4K)

**Size validation is mandatory** before any image generation in Phase 1. Run `scripts/validate_size.py` (`--config`, `--project`, `--width`, `--height`).

On invalid sizes: present violations + suggested nearest compliant size, ask user to confirm. **Do NOT silently adjust.**

---

## 7. Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    PHASE 1: REQUIREMENTS                     │
│     Collect requirements, validate size, generate preview    │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 2: CONFIRMATION                     │
│ Layer breakdown + layout + style anchor + opacity judgment   │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 3: ROUGH DESIGN                     │
│    Generate isolated layers (early_size) + HTML preview      │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 4: WEB COMPOSITION CHECK            │
│    Transparency check + web preview + screenshot check       │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 5: REFINEMENT                       │
│              Preview refinement (full_size)                  │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 6: LAYER REFINEMENT                 │
│    Final high-quality layers (full_size) + HTML preview      │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 7: OUTPUT                           │
│             Deliver final assets + ask variants              │
├─────────────────────────────────────────────────────────────┤
│                    PHASE 8: STATE VARIANTS                   │
│       Generate hover/active/disabled states (optional)       │
└─────────────────────────────────────────────────────────────┘
```

**Output path pattern**:
```
{output_root}/{project_name}/
├── 01-requirements/
│   ├── size_plan.json
│   └── references/              (if reference-image mode)
├── 02-confirmation/
│   └── layer_plan.json
├── 03-rough-design/
│   └── {layer_name}/            (one folder per layer)
├── 04-check/
│   ├── enhanced_layer_plan.json (layout + resource paths for preview)
│   ├── preview.html             (static interactive preview page)
│   ├── preview_check_screenshot.png
│   └── check_report.json
├── 05-refinement-preview/
│   └── preview_{timestamp}.png
├── 06-refinement-layers/
│   └── {layer_name}/            (one folder per layer)
├── 07-output/
│   ├── preview.html             (final interactive web preview)
│   ├── final_preview.png
│   ├── layers/                  (clean names, no timestamps)
│   └── manifest.json
└── 08-variants/                 (if Phase 8 executed)
    └── {control_name}/          (hover/active/disabled)
```

---

## 8. Preview Quality Modes

Two independent choices at Phase 1:

### 8.1 Preview Quality (affects early_size and generation quality)

| Feature | Standard Preview | High-Quality Preview |
|--------|-----------------|---------------------|
| `downsize_ratio` | 0.5 | 0.775 |
| Early-phase area | ~25–40% of full | ~60% of full |
| Preview quality | `low` | `medium` |
| Generation speed | Fast (~150s for 1K) | Slower (~250s for 1K) |
| Token/cost | Lower | ~2× |
| Best For | Iterative exploration, quick drafts | Detail-critical designs, text-heavy UIs, fine textures |

**How to choose**: At Phase 1 Step 2, ask the user:
> "请选择预览质量模式：标准预览（默认，更快更省）或高质量预览（保留约 60% 面积细节，质量 medium）？"

### 8.2 Fast Track Mode (affects preview count only, independent of quality)

| Feature | Standard Workflow | Fast Track |
|--------|-------------------|------------|
| Previews | 3 options | 1 option |
| Revisions | Unlimited | Unlimited |
| Phase 2 | Required | Required (same as Standard) |
| OK Checkpoints | 2 (Phase 1 preview + Phase 2 layer plan) | 2 (same as Standard) |
| Best For | New designs, exploration | Quick iterations, known assets |

**How to choose**: At Phase 1 Step 2, ask the user:
> "是否启用快速通道？（是/否）" — 启用后只生成 1 张预览（而非 3 张），减少选择时间。Phase 2 图层方案确认仍然需要。

**Modes can be combined**: High-Quality + Fast Track = 1 high-quality preview, then Phase 2 confirmation. Standard + Standard Workflow = 3 low-quality previews, then Phase 2 confirmation.

---

## 9. Iteration Limits

| Phase | Max Iterations | Configurable |
|-------|---------------|-------------|
| Phase 1 (Requirements) | Unlimited (until user OK) | No |
| Phase 4 (Rough Check) | 20 | Yes |
| All others | Single pass per layer | N/A |

---

## 10. Phase-by-Phase Reference Documents

**MANDATORY RULE**: When entering any phase, read the corresponding phase document from `references/` before executing any steps.

| Phase | Document | Script Invoked |
|-------|----------|----------------|
| 1 — Requirements | [`references/phase-1-requirements.md`](references/phase-1-requirements.md) | `validate_size.py`, `generate_image.py` |
| 2 — Confirmation | [`references/phase-2-confirmation.md`](references/phase-2-confirmation.md) | (analysis + write `layer_plan.json` with layout + opacity) |
| 3 — Rough Design | [`references/phase-3-rough-design.md`](references/phase-3-rough-design.md) | `generate_image.py edit` |
| 4 — Web Composition Check | [`references/phase-4-check.md`](references/phase-4-check.md) | `check_transparency.py`, `generate_preview.py` |
| 5 — Refinement Preview | [`references/phase-5-refinement-preview.md`](references/phase-5-refinement-preview.md) | `generate_image.py edit` |
| 6 — Layer Refinement | [`references/phase-6-refinement-layers.md`](references/phase-6-refinement-layers.md) | `generate_image.py edit`, `check_transparency.py` |
| 7 — Output | [`references/phase-7-output.md`](references/phase-7-output.md) | `generate_preview.py` (copy + write manifest) |
| 8 — State Variants | [`references/phase-8-variants.md`](references/phase-8-variants.md) | `generate_variants.py` |

**Script usage examples**: See [`references/script-usage.md`](references/script-usage.md) for detailed invocation commands.

---

## 11. Key Rules

1. **Invoke scripts, don't reimplement**: If a script exists, the agent MUST call it and not duplicate logic inline.
2. **Size validation is mandatory for EVERY generation**:
   - Phase 1 preview: Run `validate_size.py` to produce `size_plan.json`
   - Phase 3 / Phase 6 per-layer generation: `compute_layer_size()` MUST be called for every non-background layer to guarantee a compliant canvas size matching the layer's aspect ratio
   - Phase 5 / Phase 8: Always use the already-validated `full_size` from `size_plan.json`
   - Never pass a raw user-provided or manually-constructed size string directly to `generate_image.py` without verifying it first
3. **Explicit OK required**: No phase transition without explicit "OK" confirmation.
4. **Style anchor persistence**: Extracted in Phase 2, must be included in ALL subsequent generation prompts.
5. **Per-layer canvas with matching aspect ratio**: For each non-background layer, compute a compliant canvas size that matches the layer's aspect ratio from `layer_plan.json` using `path_manager.compute_layer_size()`. The element is then prompted to fill this canvas proportionally.
6. **Quality adaptive**:
   - **API testing / validation**: Always use `quality=low` when testing or validating a new API endpoint or provider.
   - **Phase 3 (Rough Design)**: Use `low` for most controls. Use `medium` only for visually complex controls.
   - **Phase 6 (Layer Refinement)**: **Agent MUST visually inspect each layer** from Phase 3/4 before generating. Reassess quality per layer:
     - `low`: Solid colors, simple gradients, basic shapes, no texture
     - `medium`: Textured surfaces, shadows, decorative patterns, multi-part elements
     - `high`: Extreme detail, dense textures, intricate patterns, complex lighting, detailed characters
     - Default to `low` unless visual inspection clearly justifies higher.
   - **Preview phases (1, 5)**: Use `low` for initial previews, `medium`/`high` only for final confirmation.
7. **Transparent layers** (best-effort): Non-background layers SHOULD have transparent backgrounds where possible. Use `--remove-bg` with rembg as an optional optimization when the API does not output true alpha. If rembg fails to produce a clean result, the original layer may be kept with user confirmation.
8. **Preserve aspect ratio**: When fixing non-compliant sizes, always preserve the original aspect ratio.
9. **Image-to-image for modifications**: Any revision, fix, or incremental update MUST use `generate_image.py edit` (image-to-image) with the existing preview or layer as `--image`. Do NOT use `generate` (text-to-image) for modifications. Multiple `--image` paths are supported for multi-reference editing (images are combined horizontally, max 5 images).
10. **Layout extraction in Phase 2**: Every layer in `layer_plan.json` MUST include a `layout` object with `x`, `y`, `width`, `height` (full-size canvas coordinates). This is required for the HTML preview generator.
11. **Preview generation**: Phase 4 and Phase 7 use `generate_preview.py` to produce an interactive HTML preview. The Phase 4 preview supports drag/resize/export for layout fine-tuning.
    - **Algorithmic layer alignment** (`detect_layer_positions.py`): Offered when the user reports misaligned layers. By default runs on all eligible layers, but supports `--layer <id>` to target only specific layers — useful when only 1–2 layers need correction or when verifying detection quality on a single layer before batch processing.
    - **Adaptive multi-feature profiles** (`default`, `structure_heavy`, `color_heavy`, `texture_heavy`): The matcher fuses multiple visual features (RGB SSD, Sobel gradient, Canny edge, HSV color, LBP texture) weighted by a project-specific profile. The agent inspects the preview and selects the profile before detection. **General rule: use `default` unless the UI clearly falls into one of the specialized categories.** See [`references/matching-profiles.md`](references/matching-profiles.md) for the full selection guide. Enabled via `--profile <name>`.
    - **`--force` flag**: Bypasses opacity/background/repeat safety checks. Only use when the user **explicitly demands** detection on a layer that would normally be skipped (e.g., a semitransparent panel or a background shape the user wants aligned). Warn the user that forced detection may produce unreliable results.
12. **Repeat mode (grid/list)**: 
    - In **Phase 2**, the agent MUST visually inspect the confirmed preview for repeating patterns (grid/list) and ask the user before applying `repeat_mode`.
    - **High confidence** (visually identical elements): Auto-suggest with savings summary.
    - **Medium confidence** (similar structure but different content): Prompt user with options (enable / disable / mixed).
    - **User response**: "启用" → apply; "不启用" → skip; "只启用 XX" → selective apply.
    - Once confirmed, layers with `repeat_mode: "grid"` or `repeat_mode: "list"` and `repeat_config` reduce API calls from N per-cell to 1 per-parent.
    - **Carrier panel detection (MUST)**: When detecting repeat patterns, the agent **must** also check whether the grid/list has a **carrier panel** — a shared container that visually holds all repeating elements. This is NOT the main page background; it is a secondary container specific to the grid/list region, and may include:
      - Background shape (rounded rectangle, card, bar, pill)
      - Texture, gradient, or pattern fill on the shape
      - Decorative borders, ornamental framing, corner accents
      - Drop shadow, inner glow, or ambient occlusion around the container
      - Any visual element shared across all cells and positioned beneath them
      - If present → `auto_panel: {enabled: true, ...}` in `repeat_config`; `expand_repeats.py` generates it as a separate layer beneath instances
      - **`area_layout` as the default panel boundary**: `repeat_config.area_layout` should include `{"x", "y", "width", "height"}` to define the panel boundary. By default, this boundary IS the panel — `expand_repeats.py` uses `area_layout.width/height` directly as the panel dimensions. `repeat_config.padding` (single number or `{top, right, bottom, left}`) controls the inner offset between panel edge and cells. When `padding = 0`, cells sit flush against the panel edge (effectively no visual panel gap). **Negative padding is supported** — when cells visually extend beyond the panel edge (e.g., overflow tabs), negative values are preserved through detection and handled by the Figma plugin via expanded auto-frame sizing.
      - Cells are positioned at `area_layout.x + padding.left`, `area_layout.y + padding.top`, derived from the panel boundary plus padding offset
      - **`auto_panel.layout` override (rarely needed)**: Only configure `auto_panel.layout` when the panel needs to deviate from `area_layout` — e.g., the panel has a drop shadow that extends beyond `area_layout`, or the carrier shape is visually larger/smaller than the cell area. In the common case where the panel perfectly contains all cells, omit `auto_panel.layout` entirely; `area_layout` alone is sufficient
      - Panel layout resolution: `auto_panel.layout` (manual override, only when deviating) > `area_layout.width/height` (default panel boundary) > auto-calculate from `cols/rows/gap` (legacy fallback)
      - If absent → cells float on main background; omit `auto_panel`
    - **Phase 4 panel position refinement (automatic)**: When `auto_panel.enabled: true`, the panel PNG is template-matched in Phase 4 to refine the container position. Detected coordinates automatically update `area_layout` and shift all cells to align. This corrects imprecise Phase 2 estimates without manual intervention. See [`references/phase-4-check.md`](references/phase-4-check.md) for details.
    - **Generation scope**: `expand_repeats.py` produces 3 layer types in `expanded_layer_plan.json`:
      - `is_repeat_parent: true` — generate once in Phase 3/6
      - `is_repeat_panel: true` — generate once in Phase 3/6 (if enabled)
      - `is_repeat_instance: true` — do NOT generate, reuse parent's PNG
    - **State variants (Phase 8)**: Generate variants from the **parent layer** only. All instances automatically share the same state variants because they reference the parent's PNG path.

---

## 12. Additional References

- Setup & Installation: [`references/setup-guide.md`](references/setup-guide.md)
- Incremental Update Mode: [`references/incremental-update.md`](references/incremental-update.md)
- Prompt Templates: [`references/prompt-templates.md`](references/prompt-templates.md)
- Optimization Modes: [`references/optimization-modes.md`](references/optimization-modes.md)
- Workflow Overview (detailed): [`references/workflow-overview.md`](references/workflow-overview.md)
