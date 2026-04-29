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
4. Build the layer prompt:
   - Base: `Extract ONLY the {layer_name}. {description}.`
   - **If `opacity` < 1.0 (semi-transparent layer in the full design)**: append color purity guidance:
     > "This element sits on top of a background in the full design. When extracting it, preserve the element's own intrinsic colors and texture cleanly — do NOT blend background colors into the element. The element should retain its intended solid appearance with pure, unmixed colors."
   - Always append: `Transparent background, PNG with alpha channel, only this element isolated. {style_anchor}. CRITICAL: STRICTLY maintain the element's original aspect ratio. Do NOT stretch, distort, or change proportions in any way. Scale the element proportionally to fit within the canvas while leaving a small transparent margin of approximately 3-5% on each side. Do NOT let the element touch or overlap the canvas boundary. This margin ensures clean background removal in post-processing.`

5. Generate isolated layer:

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {confirmed_preview_path} \
  --prompt "{layer_prompt}" \
  --output {layer_path} --size {layer_w}x{layer_h} --quality {tier}
```

- **Native model path**: Use agent's image-to-image/editing tool. Pass preview as reference + layer isolation prompt + style anchor.
- **External API path**: Use `generate_image.py edit` (command above)
- `size`: per-layer compliant size from `compute_layer_size()` (background uses full `early_size`)
- `quality`: layer's quality tier
- Save output with timestamp in layer folder

**Repeat-mode layer handling**:

For layers with `repeat_mode: "grid"` or `repeat_mode: "list"`, the generation strategy is:

| What to Generate | Count | Notes |
|-----------------|-------|-------|
| **Parent cell** | 1 | The single isolated element (e.g., "one product card") |
| **Panel background** (if `auto_panel.enabled`) | 1 | Container background covering the entire repeat area |
| **Instance cells** | 0 | Do NOT generate — these are created by `expand_repeats.py` for preview only |

**How it works:**
1. `expand_repeats.py` creates 3 types of layers in `expanded_layer_plan.json`:
   - `is_repeat_parent: true` — the original parent layer (needs generation)
   - `is_repeat_panel: true` — panel background (needs generation, if enabled)
   - `is_repeat_instance: true` — preview-only instances (NO generation)
2. In Phase 3, **only generate layers where `is_repeat_parent` or `is_repeat_panel` is true**.
3. Skip any layer with `is_repeat_instance: true` — these reuse the parent's PNG.

**Generation commands:**
```bash
# Parent cell (the template element)
python scripts/generate_image.py edit \
  --config config.json \
  --image {confirmed_preview_path} \
  --prompt "Extract ONLY one product card. {description}. Transparent background, isolated element. {style_anchor}. CRITICAL: STRICTLY maintain the element's original aspect ratio..." \
  --output {layer_path} --size {layer_w}x{layer_h} --quality {tier}

# Panel background (if auto_panel enabled)
python scripts/generate_image.py edit \
  --config config.json \
  --image {confirmed_preview_path} \
  --prompt "Extract ONLY the container panel background for the product card grid. White rounded rectangle panel, no cards, no elements inside. {style_anchor}." \
  --output {panel_path} --size {panel_w}x{panel_h} --quality low
```

**Extreme-ratio layer handling**:
- If `PathManager.is_extreme_ratio(layout.width, layout.height)` returns `True` (original ratio > model's `max_ratio`, e.g. > 3:1), the compliant canvas will be clamped to a different aspect ratio.
- The existing prompt already instructs the model to "STRICTLY maintain the element's original aspect ratio", so the element should remain proportionally correct inside the canvas.
- After generation, the layer image will have transparent padding on the shorter sides. **Do NOT auto-crop in Phase 3** — the element is not yet matted and the alpha channel may be unreliable.
- Instead, **record the `extreme_ratio: true` flag in `layer_plan.json`** for this layer. Phase 4 will handle auto-cropping **after** rembg produces a clean alpha channel.
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

### Async Task Fire-and-Forget Mode

When using an `async_task` provider (e.g., apimart), each generation may take several minutes. To avoid agent timeout with many layers, use `--no-wait` to submit tasks without blocking:

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {preview_path} \
  --prompt "{layer_prompt}" \
  --output {layer_path} --size {layer_w}x{layer_h} --quality {tier} \
  --no-wait
```

With `--no-wait`, the task is submitted, a pending record is saved to `03-rough-design/.pending_tasks.json`, and the script exits immediately.

**Poll for results**:
```bash
python scripts/generate_image.py poll \
  --pending-file 03-rough-design/.pending_tasks.json
```

**Agent timeout handling**: If the agent framework does not support cron/scheduling and the agent cannot retrieve all layer data within a single response after submitting tasks, the agent MUST include the following message in its reply:

> "由于当前框架限制，任务当前正在进行中，可以随时提醒我检查任务进度并继续"

The user can then remind the agent to check progress, and the agent will re-read the pending file and poll remaining tasks.

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
