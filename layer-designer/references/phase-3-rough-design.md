# Phase 3: Rough Design

**Goal**: Generate each layer independently with transparent background.

**When to read this file**: Agent MUST read this file when entering Phase 3. This phase generates isolated layer images from the confirmed preview.

**Output Path Pattern**:
```
{output_root}/{project_name}/03-rough-design/
├── background/
│   ├── background_{timestamp}.png
│   └── ...
├── header/
│   ├── header_{timestamp}.png
│   └── ...
├── sidebar/
│   ├── sidebar_{timestamp}.png
│   └── ...
└── ... (one folder per layer)
```

---

## Step 1: Read Inputs

Before starting, ensure you have:
- `layer_plan.json` from Phase 2 (or Phase 1 Step 9 in Fast Track)
- `size_plan.json` with `early_size` for this phase
- Confirmed preview image from Phase 1
- `style_anchor` string

---

## Step 2: Generate Each Isolated Layer

**Scripts invoked in this phase**: `generate_image.py edit` (once per layer)

For each layer identified in `layer_plan.json`, in the documented stacking order:

1. Get layer path via `PathManager.get_layer_path(layer_name)`
2. Determine `quality`:
   - If `quality_adaptive` enabled: use the layer's assigned tier from `layer_plan.json` (default to `low`)
   - Otherwise: `low`
3. **Compute per-layer canvas size (MANDATORY — prevents API 502/400 errors)**:
   - For **non-background layers**: read `layout.width` and `layout.height` from `layer_plan.json`, then call `PathManager.compute_layer_size(layout.width, layout.height)`
   - This returns a **compliant canvas size matching the layer's aspect ratio**, maximizing area within model constraints
   - For **background layer**: use the full canvas `early_size` from `size_plan.json` (already validated in Phase 1)
   - **NEVER construct a size string manually** (e.g., `f"{w}x{h}"`) without going through `compute_layer_size()` or `validate_size.py` first
4. Generate isolated layer:

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {confirmed_preview_path} \
  --prompt "Extract ONLY the {layer_name}. {description}. Transparent background, PNG with alpha channel, only this element isolated. {style_anchor}. CRITICAL: STRICTLY maintain the element's original aspect ratio. Do NOT stretch, distort, or change proportions in any way. Scale the element proportionally to fill the entire canvas. The element should occupy the maximum possible area while preserving its exact original proportions." \
  --output {layer_path} --size {layer_w}x{layer_h} --quality {tier}
```

- **Native model path**: Use agent's image-to-image/editing tool. Pass preview as reference + layer isolation prompt + style anchor.
- **External API path**: Use `generate_image.py edit` (command above)
- `size`: per-layer compliant size from `compute_layer_size()` (background uses full `early_size`)
- `quality`: layer's quality tier
- Save output with timestamp in layer folder

**Extreme-ratio layer handling**:
- If `PathManager.is_extreme_ratio(layout.width, layout.height)` returns `True` (original ratio > model's `max_ratio`, e.g. > 3:1), the compliant canvas will be clamped to a different aspect ratio.
- The existing prompt already instructs the model to "STRICTLY maintain the element's original aspect ratio", so the element should remain proportionally correct inside the canvas.
- After generation and rembg, the layer image will have transparent padding on the shorter sides. **Agent MUST run auto-crop** to trim this padding:
  ```bash
  python scripts/check_transparency.py --config config.json --image {layer_path} --remove-bg --auto-crop --output {layer_path}
  ```
  This produces an additional `{layer_name}_cropped.png` with the element tightly cropped to its content bounding box.
- `generate_preview.py` automatically prefers `*_cropped.png` when available, so Phase 4 preview will show the element at its true proportions.

**Background layer exception**:
- Background layer does NOT need transparent background
- Use the full canvas `early_size` instead of `compute_layer_size()`
- Prompt should request full background fill instead of transparency

---

## Step 3: Parallel Execution (Optional)

If `parallel_generation` is enabled and the agent supports subagents:
- Spawn up to `parallel_max_workers` subagents, each handling one layer
- Each subagent invokes `generate_image.py edit` independently
- Master agent collects all results before proceeding to Phase 4

---

## Constraints

- All non-background layers SHOULD have transparent backgrounds (via API alpha output or rembg post-processing). Transparent output is preferred but not strictly mandatory.
- All layers MUST have identical dimensions (at the `early_size` used in this phase)
- Each layer saved in its own folder for version tracking
- Stacking order from `layer_plan.json` must be preserved

---

**Exit Condition**: All layers generated successfully.

**Output upon exit**:
- One image per layer in `03-rough-design/{layer_name}/`
