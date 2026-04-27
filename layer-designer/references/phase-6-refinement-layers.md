# Phase 6: Refinement — Layers

**Goal**: Produce final high-quality individual layers at full resolution.

**When to read this file**: Agent MUST read this file when entering Phase 6. This phase regenerates every layer at full size with high quality.

**Output Path Pattern**:
```
{output_root}/{project_name}/06-refinement-layers/
├── background/
│   └── background_{timestamp}.png
├── header/
│   └── header_{timestamp}.png
└── ... (one folder per layer)
```

---

## Step 1: Read Inputs

- `full_size` from `01-requirements/size_plan.json`
- High-quality preview from Phase 5
- Latest rough version of each layer from Phase 3/4
- `enhanced_layer_plan.json` (or `layer_plan.json`) with quality tiers and finalized layout
- `style_anchor` string

---

## Step 2: Visual Complexity Assessment (Agent Visual Review)

**Before generating refined layers, the agent MUST visually inspect each layer's rough version** (from Phase 3/4 or Phase 5 preview) and re-evaluate its quality tier.

**Assessment criteria**:

| Tier | Visual Complexity | Examples |
|------|------------------|----------|
| `low` | Solid colors, simple gradients, basic geometric shapes, minimal text, no texture | Simple buttons, plain bars, solid backgrounds |
| `medium` | Textured surfaces, shadows/highlights, decorative patterns, multi-part elements | Textured panels, avatar frames, ornate borders |
| `high` | Extreme detail, dense textures, intricate patterns, complex lighting, detailed characters | Detailed characters, complex maps, heavily illustrated elements |

**Procedure**:
1. For each layer, read the existing rough layer image (e.g., `03-rough-design/{layer_name}/{layer_name}_001.png`)
2. Visually assess its complexity against the criteria above
3. Update `layer_plan.json` → set `quality_tier` for that layer
4. **Do NOT blindly reuse Phase 3 quality tiers** — visual inspection may reveal that a "simple" button actually has subtle textures requiring `medium`, or that a "complex" panel is actually flat and only needs `low`

> **Budget-conscious rule**: Default to `low` unless visual inspection clearly justifies `medium` or `high`. When in doubt, use `low`.

---

## Step 3: Generate Refined Layers

**Script**: `generate_image.py edit` (once per layer)

For each layer, **preserving the same stacking order from Phase 3**:

1. **Compute per-layer canvas size (MANDATORY — same compliance rules as Phase 3)**:
   - For **non-background layers**: read `layout.width` and `layout.height` from `layer_plan.json`, then call `PathManager.compute_layer_size(layout.width, layout.height)`
   - This returns a **compliant canvas size matching the layer's aspect ratio**, same sizing logic as Phase 3. Both phases use `compute_layer_size(layout.width, layout.height)` with identical inputs, so the canvas dimensions are the same. Only the `quality` tier is higher in Phase 6.
   - For **background layer**: use the full canvas `full_size` from `size_plan.json` (already validated in Phase 1)
   - **NEVER construct a size string manually** without going through `compute_layer_size()` first
2. Generate refined layer:

**Element layers** (non-background, requires transparency):

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {high_quality_preview} \
  --prompt "Extract ONLY the {layer_name}. {description}. High quality, polished, transparent background, isolated element. {style_anchor}. CRITICAL: STRICTLY maintain the element's original aspect ratio. Do NOT stretch, distort, or change proportions in any way. Scale the element proportionally to fill the entire canvas. The element should occupy the maximum possible area while preserving its exact original proportions." \
  --output {final_layer_path} --size {layer_w}x{layer_h} --quality {tier}
```

- `size`: per-layer compliant size from `compute_layer_size()`
- `quality`: **visually reassessed** quality tier from Step 2 (NOT blindly inherited from Phase 3)
- **Native model path**: Pass both preview and rough layer as references if multi-image input is supported; otherwise use preview + detailed description
- **External API path**: Use `generate_image.py edit` (command above)
- Save via `PathManager.get_final_layer_path(layer_name)`

**Background layer** (full canvas, NO transparency, NO UI elements):

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {high_quality_preview} \
  --prompt "From this UI design, extract ONLY the background layer. Include: {background_description}. Full canvas filled completely. NO transparent areas. NO UI elements, NO buttons, NO text, NO icons, NO overlays. Only the pure background fill, texture, gradient, or environment. {style_anchor}." \
  --output {final_layer_path} --size {full_w}x{full_h} --quality {tier}
```

- `size`: full canvas `full_size` from `size_plan.json` (do NOT use `compute_layer_size()`)
- `quality`: **visually reassessed** quality tier from Step 2
- Save via `PathManager.get_final_layer_path(layer_name)`

---

## Step 4: Transparency Check & Matte Generation

**Script**: `check_transparency.py`

For **every non-background layer**, verify it has real alpha transparency:

```bash
python scripts/check_transparency.py --config config.json --image {layer_path}
```

**If the result indicates no real transparency** (e.g., RGB mode with solid background):

1. **Keep the original** — do not delete or overwrite the source image from Step 2.

2. **Auto-remove background** via rembg, saving to a **new** matte file:
   ```bash
   python scripts/check_transparency.py --config config.json \
     --image {layer_path} --remove-bg --output {matte_path}
   ```
   - `{matte_path}` should be `{layer_dir}/{layer_name}_matte.png`
   - Uses skill-internal `models/u2net.onnx` (U²Net model)
   - Outputs true RGBA PNG with feathered edges
   - The original `{layer_path}` remains intact

3. **Verify the matte**:
   ```bash
   python scripts/check_transparency.py --config config.json --image {matte_path}
   ```
   - Confirm `has_transparency: true` and `detection_method` is not `solid_background_fallback`

**Background layer exception**: Skip transparency check — backgrounds do not require alpha.

> ⚠️ The API endpoint currently outputs RGB mode PNGs. It is **expected** that most non-background layers will need the `--remove-bg` step. Do not treat this as an error — it is standard post-processing.

---

## Step 5: Parallel Execution (Optional)

If enabled and supported:
- Spawn subagents for independent layers, up to `parallel_max_workers`
- Each subagent invokes `generate_image.py edit` independently
- **Each subagent must also run `check_transparency.py --remove-bg` if needed**
- Collect all refined layers before proceeding to Phase 7
- **Verify layer order matches Phase 3 stacking order**

---

**Exit Condition**: All refined layers generated successfully. Non-background layers SHOULD have transparent backgrounds (via alpha channel or rembg post-processing). Transparent output is preferred but not strictly mandatory — if rembg fails to produce a clean matte, the original layer may be used with user confirmation.

**Output upon exit**:
- One high-quality image per layer in `06-refinement-layers/{layer_name}/`
- Non-background layers SHOULD be RGBA PNGs with alpha transparency where possible
