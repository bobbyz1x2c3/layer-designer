# Layered Design Generator

Generate professional UI/UX designs as layered PSD-like outputs with transparent layers. Supports complete layered workflows from requirements → preview → rough design → check → refinement → output.

---

## 0. Setup & Installation

When the user says **"开始部署"**, **"开始安装"**, or asks how to set up the project, the agent MUST:

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

## 3. Model Capability Check

| Capability | Requirement | Default |
|-----------|-------------|---------|
| Image editing | `image-to-image` support | ✅ |
| Transparency | Alpha channel in output | ✅ |
| High resolution | >= 1024×1024 or 1792×1024 | ✅ |

If the agent's native image model supports image-to-image editing with transparency, use it directly. Otherwise fall back to `scripts/generate_image.py`.

---

## 4. Input Modes

| Mode | Description | When to Use |
|------|-------------|-------------|
| **Text-to-Image** (default) | User describes design, agent generates preview | No existing design |
| **Reference-Image** | User uploads wireframe/mockup, agent edits it | Have existing design |

In reference-image mode, save the uploaded image to `01-requirements/references/`.

---

## 5. Model Size Constraints (HARD — 502 if violated)

- **Max edge**: ≤ 3840px
- **Alignment**: Both edges must be multiples of 16
- **Aspect ratio**: ≤ 3:1
- **Min pixels**: ≥ 655,360 (~1024×640)
- **Max pixels**: ≤ 8,294,400 (~4K)

**Size validation is mandatory** before any image generation in Phase 1.

Script: `scripts/validate_size.py`

```bash
python scripts/validate_size.py \
  --config config.json \
  --project my-app \
  --width 1920 --height 1080
```

On invalid sizes: present violations + suggested nearest compliant size, ask user to confirm. **Do NOT silently adjust.**

Script: `scripts/validate_size.py` (`--config`, `--project`, `--width`, `--height`)

---

## 6. Workflow Overview

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

## 7. Fast Track Mode

| Feature | Standard Mode | Fast Track |
|--------|---------------|------------|
| Previews | 3 options | 1 option |
| Revisions | Unlimited | Unlimited |
| Phase 2 | Separate phase | Merged into Phase 1 Step 9 |
| Quality | Full detail | Simplified details |
| OK Checkpoints | 2 (Phase 1 + Phase 2) | 1 (after preview) |
| Best For | New designs | Quick iterations / known assets |

**How to choose**: At Phase 1 Step 4, ask the user:
> "Standard Mode (3 previews, full quality) or Fast Track Mode (1 preview, simplified details)?"

---

## 8. Iteration Limits

| Phase | Max Iterations | Configurable |
|-------|---------------|-------------|
| Phase 1 (Requirements) | Unlimited (until user OK) | No |
| Phase 4 (Rough Check) | 20 | Yes |
| All others | Single pass per layer | N/A |

---

## 9. Phase-by-Phase Reference Documents

**MANDATORY RULE**: When entering any phase, the agent MUST read the corresponding phase document from `references/` before executing any steps.

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

---

## 9. Script Usage Reference

| Script | Phase | Usage |
|--------|-------|-------|
| `validate_size.py` | Phase 1 | `--config`, `--project`, `--width`, `--height` |
| `generate_image.py` | Phase 1,3,5,6,8 | `generate` or `edit` subcommand |
| `check_transparency.py` | Phase 4 | `--config`, `--image` |
| `generate_preview.py` | Phase 4, 7 | `--config`, `--project`, `--phase` |
| `generate_variants.py` | Phase 8 | `--config`, `--image`, `--control-type`, `--states`, `--output-dir` |

**Always pass `--config` and `--project`** to scripts.

### Quick Invocation Examples

These are the exact commands verified against the configured API endpoint (`config.json`):

**Text-to-image (generate preview)**:
```bash
python scripts/generate_image.py generate \
  --config config.json \
  --prompt "A beautiful anime style UI dashboard, flat design, purple theme" \
  --output output/my-app/01-requirements/previews/preview_v1_001.png \
  --size 1024x1024 --quality medium --model gpt-image-2
```

**Image-to-image (edit / layer isolation)**:
```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image output/my-app/01-requirements/previews/preview_v1_001.png \
  --prompt "Extract ONLY the sidebar. Transparent background. Keep exact position." \
  --output output/my-app/03-rough-design/sidebar/sidebar_001.png \
  --size 1024x1024 --quality low --model gpt-image-2
```

**Multi-reference image-to-image** (pass multiple images directly to the API):
```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image ref_a.png ref_b.png \
  --prompt "Use the element from the first image. Match its size and proportions to the second image. Transparent background." \
  --output output.png --size 1024x1024 --quality high
```

> **Limit**: Maximum 5 reference images per call. For accuracy, explicitly reference images by order in the prompt (e.g., "first image", "second image", "Image 1", "Image 2").

**Size validation (run BEFORE any generation)**:
```bash
python scripts/validate_size.py \
  --config config.json --project my-app \
  --width 1920 --height 1080
```

**Transparency check**:
```bash
python scripts/check_transparency.py \
  --config config.json \
  --image output/my-app/03-rough-design/sidebar/sidebar_001.png
```

**Generate interactive web preview** (Phase 4 / Phase 7):
```bash
python scripts/generate_preview.py \
  --config config.json \
  --project my-app \
  --phase check
```



---

## 10. Key Rules

1. **Invoke scripts, don't reimplement**: If a script exists, the agent MUST call it and not duplicate logic inline.
2. **Size validation is mandatory for EVERY generation**:
   - Phase 1 preview: Run `validate_size.py` to produce `size_plan.json`
   - Phase 3 / Phase 6 per-layer generation: `compute_layer_size()` MUST be called for every non-background layer to guarantee a compliant canvas size matching the layer's aspect ratio
   - Phase 5 / Phase 8: Always use the already-validated `full_size` from `size_plan.json`
   - Never pass a raw user-provided or manually-constructed size string directly to `generate_image.py` without verifying it first
3. **Explicit OK required**: No phase transition without explicit "OK" confirmation (except Fast Track single-checkpoint).
4. **Style anchor persistence**: Extracted in Phase 2 (or Phase 1 Step 9), must be included in ALL subsequent generation prompts.
5. **Per-layer canvas with matching aspect ratio**: For each non-background layer, compute a compliant canvas size that matches the layer's aspect ratio from `layer_plan.json` using `path_manager.compute_layer_size()`. The element is then prompted to fill this canvas proportionally. This minimizes transparent padding (easier rembg) while keeping the image size compliant.
6. **Quality adaptive**:
   - **API testing / validation**: Always use `quality=low` when testing or validating a new API endpoint or provider.
   - **Phase 3 (Rough Design)**: Use `low` for most controls. Use `medium` only for visually complex controls (e.g., heavily textured panels, detailed characters, intricate maps).
   - **Phase 6 (Layer Refinement)**: **Agent MUST visually inspect each layer** from Phase 3/4 before generating. Reassess quality per layer based on actual visual complexity:
     - `low`: Solid colors, simple gradients, basic shapes, no texture
     - `medium`: Textured surfaces, shadows, decorative patterns, multi-part elements
     - `high`: Extreme detail, dense textures, intricate patterns, complex lighting, detailed characters
     - Default to `low` unless visual inspection clearly justifies higher.
   - **Preview phases (1, 5)**: Use `low` for initial previews, `medium`/`high` only for final confirmation.
7. **Transparent layers** (best-effort): Non-background layers SHOULD have transparent backgrounds where possible. Use `--remove-bg` with rembg as an optional optimization when the API does not output true alpha. If rembg fails to produce a clean result, the original layer may be kept with user confirmation.
8. **Preserve aspect ratio**: When fixing non-compliant sizes, always preserve the original aspect ratio.
9. **Image-to-image for modifications**: Any revision, fix, or incremental update MUST use `generate_image.py edit` (image-to-image) with the existing preview or layer as `--image`. Do NOT use `generate` (text-to-image) for modifications. Multiple `--image` paths are supported for multi-reference editing (images are combined horizontally).
10. **Layout extraction in Phase 2**: Every layer in `layer_plan.json` MUST include a `layout` object with `x`, `y`, `width`, `height` (full-size canvas coordinates). This is required for the HTML preview generator.
11. **Preview generation**: Phase 4 and Phase 7 use `generate_preview.py` to produce an interactive HTML preview. The Phase 4 preview supports drag/resize/export for layout fine-tuning.

---

## 11. References

- Phase 1 — Requirements: [`references/phase-1-requirements.md`](references/phase-1-requirements.md)
- Phase 2 — Confirmation: [`references/phase-2-confirmation.md`](references/phase-2-confirmation.md)
- Phase 3 — Rough Design: [`references/phase-3-rough-design.md`](references/phase-3-rough-design.md)
- Phase 4 — Rough Check: [`references/phase-4-check.md`](references/phase-4-check.md)
- Phase 5 — Refinement Preview: [`references/phase-5-refinement-preview.md`](references/phase-5-refinement-preview.md)
- Phase 6 — Layer Refinement: [`references/phase-6-refinement-layers.md`](references/phase-6-refinement-layers.md)
- Phase 7 — Output: [`references/phase-7-output.md`](references/phase-7-output.md)
- Phase 8 — State Variants: [`references/phase-8-variants.md`](references/phase-8-variants.md)
- Setup & Installation: [`references/setup-guide.md`](references/setup-guide.md)
- Incremental Update Mode: [`references/incremental-update.md`](references/incremental-update.md)

