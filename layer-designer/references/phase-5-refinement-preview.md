# Phase 5: Refinement — Preview

**Goal**: Produce final high-quality full preview.

**When to read this file**: Agent MUST read this file when entering Phase 5. This phase generates the polished full-size preview image.

**Output Path Pattern**:
```
{output_root}/{project_name}/05-refinement-preview/
└── preview_{timestamp}.png
```

---

## Step 1: Read Inputs

- `full_size` from `01-requirements/size_plan.json`
- Phase 1 confirmed preview image (or Phase 4 web preview screenshot)
- `enhanced_layer_plan.json` with finalized layout from Phase 4
- `style_anchor` string

---

## Step 2: Generate High-Quality Preview

**Script**: `generate_image.py edit`

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {confirmed_preview_or_phase4_screenshot} \
  --prompt "Refine this UI design to high quality, polished final version. {style_anchor}. Enhance visual hierarchy, spacing consistency, color accuracy, shadow refinement. Maintain all elements and layout exactly." \
  --output {refined_preview_path} --size {full_w}x{full_h} --quality high
```

- `size`: `full_size` from `size_plan.json` (already validated in Phase 1 — do NOT modify)
- `quality`: `high`
- Save via `PathManager.get_refinement_preview_path()`

**Optimization — Preview Skip**:
If Phase 4 passed cleanly and the user is satisfied with the web preview, you may skip this separate Phase 5 preview generation and proceed directly to Phase 6. The final preview can be derived from the refined layers or the Phase 7 web preview.

---

**Exit Condition**: High-quality preview generated successfully.

**Output upon exit**:
- Refined preview image
