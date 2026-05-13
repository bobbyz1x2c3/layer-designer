# Phase 8: State Variants (Optional)

**Goal**: Generate state variations for UI controls (hover, active, disabled, etc.).

**When to read this file**: Agent MUST read this file when entering Phase 8. Only read this if the user explicitly requested state variants in Phase 7.

> **Scope**: This phase is for **UI/UX controls only**. Game asset states and animation frames are handled by a separate skill and are NOT generated here.

**Output Path Pattern**:
```
{output_root}/{project_name}/08-variants/
├── submit_button/
│   ├── submit_button_hover_{timestamp}.png
│   ├── submit_button_active_{timestamp}.png
│   └── submit_button_disabled_{timestamp}.png
└── ... (one folder per control)
```

---

## Step 1: Read Inputs

- `full_size` from `01-requirements/size_plan.json`
- Final refined layer images from Phase 6/7
- `enhanced_layer_plan.json` (or `layer_plan.json`) to identify which layers contain controls
- `style_anchor` string
- **(Optional)** `style_ref` (top-level) + per-layer `control_type` from `enhanced_layer_plan.json` if Phase 2 ran with `--style`. The variant phase reads `control_type` to pick the matching reference image and to filter rules to the `interaction` category.

---

## Step 2: Generate State Variants

**Script**: `generate_variants.py` (recommended batch) or `generate_image.py edit` (individual)

For each requested control:
1. Identify which layer contains this control:
   - For **repeat-mode controls** (grid/list): use the **parent layer** (`is_repeat_parent: true`) as the base image
   - The generated state variants will be shared by all instances automatically
2. Read the control's `layout.width` and `layout.height` from `layer_plan.json`
3. **Compute compliant control size** (same logic as Phase 3 / Phase 6):
   ```python
   from path_manager import PathManager
   control_w, control_h = PathManager.compute_layer_size(layout.width, layout.height)
   ```
   This returns a **compliant canvas size matching the control's aspect ratio**.
4. Take the final refined layer image for that control (parent layer for repeat-mode)
5. Determine needed states (hover, active, disabled, focused, checked, etc.)

**Batch generation** (recommended):
```bash
python scripts/generate_variants.py \
  --config config.json \
  --image {control_layer.png} --control-type button \
  --states hover active disabled \
  --output-dir {variant_dir} --size {control_w}x{control_h} --quality high
```

> `generate_variants.py` automatically resolves the model from `api.phase_models.variant`, falling back to the default provider's `default_model`. Pass `--model <spec>` (plain or `provider/model`) only when you need to override the configured choice.

> For **repeat-mode controls**: `{control_layer.png}` is the **parent layer** (e.g., `06-refinement-layers/product_card/product_card_xxx.png`). All instances automatically share the same state variants because they all reference the parent's PNG in `enhanced_layer_plan.json`.

**Individual generation**:
```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {control_layer.png} \
  --prompt "This is a {control_type} in normal state. Generate the same control in {state} state. Maintain exact dimensions, colors, typography, border radius, shadow style. Changes for {state}: {state_specific_changes}. {style_anchor}. Transparent background. CRITICAL: STRICTLY maintain the element's original aspect ratio. Do NOT stretch, distort, or change proportions." \
  --output {variant_path} --size {control_w}x{control_h} --quality high --phase variant
```

- `size`: **per-control compliant size** from `compute_layer_size()` — usually NOT `full_size`
- `quality`: **inherit the control's `quality_tier` from `layer_plan.json`** — do NOT blindly use `high`. If the control was assigned `low` or `medium` in Phase 2/6, use that tier for variants too.
- Save via `PathManager.get_variant_path(control_name, state)`

**Style Library Integration** (only when `--style` was active in Phase 2):

If `enhanced_layer_plan.style_ref` is present, every variant invocation MUST forward the style:

```bash
# Batch (preferred)
python scripts/generate_variants.py \
  --config config.json \
  --image {control_layer.png} --control-type {layer.control_type} \
  --states hover active disabled \
  --output-dir {variant_dir} --size {control_w}x{control_h} --quality {tier} \
  --style {style_ref.name}

# Individual
python scripts/generate_image.py edit \
  --config config.json \
  --image {control_layer.png} \
  --prompt "Generate the {state} state of this {control_type}. Maintain dimensions, palette, typography, base shape." \
  --output {variant_path} --size {control_w}x{control_h} --quality {tier} \
  --phase variant \
  --style {style_ref.name} \
  --control-type {layer.control_type}
```

- `--phase variant` triggers the variant-phase prompt composer in `style_loader.build_prompt()`. Differences from layer phase:
  - The base image (Image1) is the **finished control PNG**, not the preview, and it carries a `[control_type]` tag because it is itself an instance of that type.
  - Rules are filtered to the `interaction` category only — layout/typography rules are noise for state changes.
- `--control-type` is **mandatory** for batch mode. It is also the same value already required by `generate_variants.py` for picking the state-transition wording, so this is not a new requirement — just remember to pull it from `enhanced_layer_plan.json` instead of hard-coding.
- If the control's `control_type` is `null` or no `image_refs` in the style match, `generate_variants.py` still works — the prompt simply has no Image2 reference, and only rules + anchor are injected.
- If `style_ref` is missing from the plan, omit all style flags. Phase 8 then behaves exactly as before.

See `references/style-library.md` § 4c "Variant phase prompt assembly" for the full prompt template.

---

## Step 3: Transparency Check & Matte Generation

**Script**: `check_transparency.py`

For **every generated state variant**, verify it has real alpha transparency:

```bash
python scripts/check_transparency.py --config config.json --image {variant_path}
```

**If the result indicates no real transparency** (e.g., RGB mode with solid background):

1. **Keep the original** — do not delete or overwrite the source variant image.

2. **Auto-remove background** via rembg, saving to a **new** matte file:
   ```bash
   python scripts/check_transparency.py --config config.json \
     --image {variant_path} --remove-bg --output {matte_path}
   ```
   - `{matte_path}` should be `{variant_dir}/{control_name}_{state}_matte.png`
   - Uses the configured matting model from `config.json`
   - Outputs true RGBA PNG with feathered edges
   - The original variant image remains intact

3. **Verify the matte**:
   ```bash
   python scripts/check_transparency.py --config config.json --image {matte_path}
   ```
   - Confirm `has_transparency: true` and `detection_method` is not `solid_background_fallback`

> ⚠️ Same as Phase 6: it is **expected** that most API endpoints output RGB mode PNGs. The `--remove-bg` step is standard post-processing, not an error.

---

## Step 4: Parallel Execution (Optional)

If enabled and supported:
- All control × state combinations are independent
- Transparency check and matte generation can also run in parallel per variant
- Spawn subagents up to `parallel_max_workers` to generate variants and process mattes concurrently

---

## Step 5: Present Variants

Present all variant images organized by control and state.
Use matte versions (`*_matte.png`) as the final deliverable if they pass transparency verification.

---

**Exit Condition**: All variants generated, transparency-checked, and matte-processed.

**Output upon exit**:
- State variant images in `08-variants/{control_name}/`
- Matte versions (`*_matte.png`) for variants that lacked native alpha transparency
