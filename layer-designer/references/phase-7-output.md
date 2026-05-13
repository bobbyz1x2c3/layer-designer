# Phase 7: Output

**Goal**: Deliver final assets to user.

**When to read this file**: Agent MUST read this file when entering Phase 7. This is the final delivery phase.

**Output Path Pattern**:
```
{output_root}/{project_name}/07-output/
├── enhanced_layer_plan.json     # layout + resource paths for Figma import
├── final_preview.png
├── layers/
│   ├── background.png
│   ├── header.png
│   └── ... (clean names, no timestamps)
└── manifest.json
```

---

## Step 1: Present Final Preview

Present the final high-quality preview image to the user.

---

## Step 2: Present All Layers

Present all final layer images with their names. Explain:
- Each layer is a transparent PNG (except background)
- Layers are in stacking order (background → foreground)
- User can use them individually or composite them together
- Import into Figma using the Figma plugin for precise layout review

---

## Step 3: Ask About Variants

Ask the user:
```
所有图层已交付。是否需要生成控件状态变体图？
例如：hover、active、disabled 等状态。
如果需要，请告诉我哪些控件需要状态变体。
```

If user declines: workflow ends.

If user specifies controls: proceed to Phase 8.

---

## Step 4: Generate Final Layer Plan

Generate the final `enhanced_layer_plan.json` for delivery:

```bash
python scripts/generate_preview.py \
  --config config.json \
  --project {project_name} \
  --phase output
```

This generates `07-output/enhanced_layer_plan.json` with `source` paths pointing to `layers/{layer_name}.png`.

This is the **deliverable layout data** the Figma plugin reads for precise layer placement.

---

## Step 5: Save Final Output

Copy refined layers to `07-output/` with stable names (no timestamps):
- Preview image → `final_preview.png` (if available)
- Each layer → `layers/{layer_name}.png`

**Repeat-mode layer output:**

When copying refined layers from `06-refinement-layers/`, include:
| Layer Type | Source | Destination |
|-----------|--------|-------------|
| Normal layers | `06-refinement-layers/{id}/{id}_*.png` | `07-output/layers/{id}.png` |
| **Parent** (`is_repeat_parent`) | `06-refinement-layers/{parent_id}/{parent_id}_*.png` | `07-output/layers/{parent_id}.png` |
| **Panel** (`is_repeat_panel`) | `06-refinement-layers/{panel_id}/{panel_id}_*.png` | `07-output/layers/{panel_id}.png` |

Instance layers do NOT need to be copied — they share the parent's PNG via `source` path in `enhanced_layer_plan.json`.

Generate `manifest.json` via `PathManager.write_manifest()`:
```json
{
  "project": "my-dashboard",
  "dimensions": {"width": 1920, "height": 1080},
  "style_anchor": "...",
  "style_ref": {
    "name": "saas-blue",
    "dir": "styles/saas-blue",
    "schema_version": "1.0"
  },
  "layers": [
    {
      "name": "background",
      "layout": {"x": 0, "y": 0, "width": 1920, "height": 1080},
      "control_type": null,
      "states": []
    },
    {
      "name": "submit_button",
      "layout": {"x": 1640, "y": 980, "width": 200, "height": 48},
      "control_type": "button",
      "states": []
    }
  ],
  "stacking_order": ["background", "..."],
  "refinement_skipped": false,
  "variants_requested": false
}
```

**Style Library fields** (only present when Phase 2 ran with `--style`):

- Top-level `style_ref` — copied verbatim from `layer_plan.style_ref` / `enhanced_layer_plan.style_ref`. Lets downstream consumers (Figma plugin, design-system audits) trace which style produced these layers.
- Per-layer `control_type` — copied from the corresponding entry in the enhanced plan. Values are drawn from the union of `style.image_refs[*].use_for` (e.g., `"button"`, `"sidebar"`, `"card"`) or `null`.

When `--style` was not used, omit both fields entirely. Downstream code treats their absence as "no style in play" — no special-case handling required.

---

**Exit Condition**: User declines variants OR user requests variants and proceeds to Phase 8.

**Output upon exit**:
- `final_preview.png`
- `layers/*.png`
- `manifest.json`
- `enhanced_layer_plan.json` — layout data for Figma import
