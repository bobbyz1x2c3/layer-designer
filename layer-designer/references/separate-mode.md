# Separate Mode（分离模式）

**Goal**: Generate layered UI designs from a user-provided reference image, bypassing Phase 1 preview generation.

**When to read this file**: Agent MUST read this file when the user says **"分离模式"**, **"separate mode"**, provides a reference image/screenshot, or asks to extract layers from an existing design.

**How it differs from standard mode**:
| | Standard 8-phase | Separate Mode |
|---|---|---|
| Input | Text description → AI generates preview | **User provides reference image** |
| Phase 1 | `validate_size.py` + `generate_image.py generate` | **Skipped** (image dimensions = canvas) |
| Phase 2 | Agent analyzes AI preview → `layer_plan.json` | **Agent analyzes reference image** → `layer_plan.json` |
| Phase 3 | Mixed PL + normal mode generation | **All PL mode** generation |
| Phase 4 | Transparency check + on-demand detection | **Automatic** position detection |

**Output Path Pattern**:
```
{output_root}/{project_name}/
├── 01-requirements/
│   └── references/
│       └── reference.png          # User's reference image
│   └── size_plan.json             # full_size = compliant image dimensions (no early_size)
├── 02-confirmation/
│   └── layer_plan.json            # Agent-generated (all layers: precise_layout=true)
├── 03-rough-design/               # PL-generated layers (full canvas size)
│   ├── background/
│   ├── sidebar/
│   └── ...
└── 04-check/
    ├── detected_layouts.json      # Auto-detected positions
    └── enhanced_layer_plan.json   # Final output for Figma import
```

---

## Step 1: Save Reference Image

Save the user's reference image to:
```
{output_root}/{project_name}/01-requirements/references/reference.png
```

Use `PathManager.get_phase_dir("requirements") / "references" / "reference.png"`.

**Read image dimensions** using PIL and report to user:
```python
from PIL import Image
with Image.open(path) as img:
    width, height = img.size
```

If dimensions are non-compliant, inform user of adjusted dimensions (see Step 2).

---

## Step 2: Create size_plan.json

**Script**: `validate_size.py --downsize-ratio 1.0`

Run size validation with **downsize ratio = 1.0** (no downscaling — the reference image IS the canvas):

```bash
python scripts/validate_size.py \
  --config config.json \
  --project {project_name} \
  --width {img_width} \
  --height {img_height} \
  --downsize-ratio 1.0
```

**Why `--downsize-ratio 1.0`**: In separate mode, all layers are generated in PL mode on the full canvas. There is no "early phase" with downscaled previews, so both `full_size` and `early_size` equal the reference image dimensions.

**If image is non-compliant**: `validate_size.py` automatically adjusts to the nearest compliant size and reports it. Inform the user:
> "参考图尺寸 {img_width}x{img_height} 不合规，已自动调整为 {compliant_w}x{compliant_h}。后续生成将使用调整后尺寸。"

---

## Step 3: Visual Analysis → layer_plan.json

**This is the Agent's core responsibility** — no script exists for this step.

Analyze the reference image visually and produce `layer_plan.json` at:
```
{output_root}/{project_name}/02-confirmation/layer_plan.json
```

### Key differences from standard Phase 2:

**All non-background layers MUST have `precise_layout: true`**:
```json
{
  "name": "sidebar",
  "contents": "Left navigation bar with icons and labels",
  "layout": {"x": 0, "y": 80, "width": 240, "height": 1000},
  "opacity": 0.9,
  "precise_layout": true,
  "quality_tier": "low"
}
```

**Why all PL mode**: In separate mode, layers are extracted from the reference image at their exact positions. PL mode keeps the element at its original pixel region on the full canvas, which is required for accurate template matching against the reference.

**Background layer**: Keep `precise_layout: false` (or omit). Background uses the full canvas naturally.

**Quality tier**: Default to `low` for all layers. Override per layer only when visually justified (e.g. complex textures → `medium`).

**Repeat mode**: Grid/list detection follows the same rules as standard Phase 2.

---

## Step 4: Confirm layer_plan with User

**Wait for explicit user confirmation before proceeding.**

Present the generated `layer_plan.json` to the user with a summary:

> **图层方案已生成**
>
> 共 {N} 个图层：
> - background (1920×1080) @ (0, 0) — 背景层
> - sidebar (240×1000) @ (0, 80) — 左侧导航栏
> - header (1680×80) @ (240, 0) — 顶部标题栏
> - buttons (280×60) @ (1520, 960) — 按钮组
>
> **请确认图层方案是否正确。**
> - 回复 **OK** → 开始生成图层
> - 回复 **修改** → 告诉我需要调整的图层
> - 告诉我新增/删除/重命名的图层

**Important**: Do NOT proceed to Step 5 until the user explicitly replies **"OK"** or confirms.

---

## Step 5: Generate Layers (PL Mode)

**Script**: `generate_image.py edit` (once per layer)

For each layer in `layer_plan.json`:

### 4.1 Determine size

All layers use **full canvas size** (reference image dimensions):
```python
canvas_w = size_plan["full_size"]["width"]
canvas_h = size_plan["full_size"]["height"]
size_str = f"{canvas_w}x{canvas_h}"
```

### 4.2 Build PL mode prompt

**For non-background layers**:
```
Extract ONLY the {layer_name} from the source reference image. {description}. {style_anchor}.
CRITICAL: Preserve the element EXACTLY as it appears in the source reference image —
same position, same size, same proportions.
Do NOT center the element, do NOT enlarge it, do NOT reposition it.
The element should occupy the IDENTICAL pixel region it occupies in the source reference.
All other pixels (where the element does not appear in the source) MUST be fully transparent (alpha=0).
Output: PNG with alpha channel, same canvas dimensions as the source reference.
```

**For background layer**:
```
From this UI design, extract ONLY the background layer.
Include: {description}. Full canvas filled completely.
NO transparent areas. NO UI elements, NO buttons, NO text, NO icons, NO overlays.
Only the pure background fill, texture, gradient, or environment. {style_anchor}.
```

**For semi-transparent layers** (opacity < 1.0):
Append to the prompt:
```
This element sits on top of a background in the full design.
When extracting it, preserve the element's own intrinsic colors and texture cleanly
— do NOT blend background colors into the element.
```

### 4.3 Invoke generation

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {reference_image_path} \
  --prompt "{prompt}" \
  --output output/{project}/03-rough-design/{layer_name}/{layer_name}_001.png \
  --size {canvas_w}x{canvas_h} \
  --quality {tier}
```

**Timeout guideline**: PL mode at full canvas size:
- `low` quality: **200-250 seconds**
- `medium` quality: **250-300 seconds**
- `high` quality: **300+ seconds**

**Parallel generation**: If `workflow.parallel_generation` is enabled, generate layers in parallel (max 3 workers).

---

## Step 6: Transparency Check + Rembg Matting

**Script**: `check_transparency.py`

For every non-background layer:

```bash
python scripts/check_transparency.py \
  --config config.json \
  --image output/{project}/03-rough-design/{layer_name}/{layer_name}_001.png \
  --remove-bg \
  --auto-crop \
  --crop-padding 4 \
  --output output/{project}/03-rough-design/{layer_name}/{layer_name}_matte.png \
  --pl-mode
```

**Why `--auto-crop --crop-padding 4` is REQUIRED for PL mode**:
- After rembg, the layer has a transparent background but may still have excess transparent padding
- `--auto-crop` trims to the content bounding box and writes `crop_bbox` to `layer_meta.json`
- This `crop_bbox` becomes the **planned layout** for `detect_layer_positions.py`
- Without it, PL mode layers have no accurate position metadata for template matching

After matting, replace the original with the matte/cropped version:
```bash
# Rename original → backup
mv {layer_name}_001.png {layer_name}_001.original.png
mv {layer_name}_matte.png {layer_name}_001.png
```

**PL mode flag**: Always pass `--pl-mode` so the stage2 padding heuristic is disabled (PL layers are intentionally sparse on the canvas).

**Timeout**: 120 seconds per layer.

---

## Step 7: Verify crop_bbox in layer_meta.json

After Step 6, verify that `layer_meta.json` exists and contains `crop_bbox`:

```json
{
  "crop_bbox": [100, 200, 150, 50],
  "cropped_size": {"width": 150, "height": 50}
}
```

The `crop_bbox` is `[x, y, width, height]` in the full canvas coordinate system. This is the **fallback layout** used by `detect_layer_positions.py` when no detected layout is available.

If `layer_meta.json` is missing or lacks `crop_bbox`, re-run `check_transparency.py` with `--auto-crop`.

---

## Step 8: Position Detection

**Script**: `detect_layer_positions.py`

Run template matching to find each layer's exact position in the reference image:

```bash
python scripts/detect_layer_positions.py \
  --config config.json \
  --project {project_name} \
  --preview output/{project}/01-requirements/references/reference.png \
  --phase rough
```

**What it does**:
- Reads each layer PNG (post-matting/crop) as template
- Searches the reference image around planned position (±250% margin)
- Tries multiple scales (0.70×–1.30×)
- Outputs `04-check/detected_layouts.json`

**Timeout**: 600 seconds (depends on layer count and image size).

**PL mode advantage**: Since layers were generated on the full canvas at original position, the template should match the reference image with high accuracy.

---

## Step 9: Generate Enhanced Layer Plan

**Script**: `generate_preview.py`

```bash
python scripts/generate_preview.py \
  --config config.json \
  --project {project_name} \
  --phase check \
  --apply-detected-layouts
```

This produces `04-check/enhanced_layer_plan.json` with:
- Layout from `detected_layouts.json` (detected positions)
- Resource paths pointing to `03-rough-design/{layer}/{layer}_001.png`

---

## Step 10: Notify User

Send a summary to the user:

> **分离模式完成**
>
> 📁 输出文件：
> - `04-check/enhanced_layer_plan.json` — Figma 导入数据
> - `04-check/detected_layouts.json` — 位置检测结果
>
> 当前图层（共 {N} 个）：
> - background ({w}×{h}) @ (0, 0)
> - ...
>
> **请使用 Figma 插件导入查看布局效果。**
>
> 如果布局满意，请选择：
> - 回复 **OK** → 进入 Phase 5~7 精修阶段（如果需要）
> - 回复 **EXIT** → 直接交付当前图层

---

## Size Handling Summary

| Parameter | Value |
|-----------|-------|
| `full_size` | Compliant reference image dimensions |
| `early_size` | Same as `full_size` (`--downsize-ratio 1.0`) |
| Layer canvas size | `full_size` (all PL mode) |
| Alignment | Both dimensions must be multiples of 16 (auto-adjusted) |

---

## Limitations

- **Template matching quality**: Depends on how closely the generated layer matches the reference. AI-introduced variations may cause imperfect matches.
- **Cost**: Full canvas per layer = higher token/cost than normal mode per-layer cropping.
- **Opacity < 0.85**: These layers are skipped by detection automatically; planned layout is used as fallback.
- **Repeat mode**: Supported, but parent layer must be visually distinctive for reliable template matching.
