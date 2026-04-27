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

---

## Step 2: Generate State Variants

**Script**: `generate_variants.py` (recommended batch) or `generate_image.py edit` (individual)

For each requested control:
1. Identify which layer contains this control
2. Take the final refined layer image for that control
3. Determine needed states (hover, active, disabled, focused, checked, etc.)

**Batch generation** (recommended):
```bash
python scripts/generate_variants.py \
  --config config.json \
  --image {control_layer.png} --control-type button \
  --states hover active disabled \
  --output-dir {variant_dir} --size {full_w}x{full_h} --quality high
```

**Individual generation**:
```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {control_layer.png} \
  --prompt "This is a {control_type} in normal state. Generate the same control in {state} state. Maintain exact dimensions, colors, typography, border radius, shadow style. Changes for {state}: {state_specific_changes}. {style_anchor}. Transparent background." \
  --output {variant_path} --size {full_w}x{full_h} --quality high
```

- `size`: `full_size` from `size_plan.json` (already validated in Phase 1 — do NOT modify)
- `quality`: `high`
- Save via `PathManager.get_variant_path(control_name, state)`

---

## Step 3: Parallel Execution (Optional)

If enabled and supported:
- All control × state combinations are independent
- Spawn subagents up to `parallel_max_workers` to generate variants concurrently

---

## Step 4: Present Variants

Present all variant images organized by control and state.

---

**Exit Condition**: All variants generated and presented.

**Output upon exit**:
- State variant images in `08-variants/{control_name}/`
