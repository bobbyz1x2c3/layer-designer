# Separate Mode（分离模式）

**Goal**: Generate layered UI designs from a user-provided reference image, bypassing the standard Phase 1 preview generation.

**When to read this file**: When the user says **"分离模式"**, **"separate mode"**, provides a reference image/ screenshot and asks to extract layers, or wants to skip preview generation and work directly from an existing design.

---

## Trigger Conditions

User input includes any of:
- "分离模式"
- "separate mode"
- "我有现成的设计图"
- "从这张截图提取图层"
- "直接分析这张图片"
- 上传了一张 UI 截图 / 设计稿 / 参考图，并明确要求提取图层

---

## Workflow Overview

分离模式与标准 8-phase 流程的关键差异：

| 步骤 | 标准模式 | 分离模式 |
|------|---------|---------|
| 输入 | 文字需求 → AI 生成预览 | **用户提供参考图** |
| Phase 1 | validate_size + generate 预览 | **跳过**（以图片尺寸为准） |
| Phase 2 | Agent 分析预览 → layer_plan | **Agent 分析参考图 → layer_plan**（全 PL 模式） |
| Phase 3 | 混合模式生成 | **全 PL 模式**生成（脚本自动化） |
| Phase 4 | 透明度检查 + 检测（需确认） | **自动**透明度检查 + 位置检测（脚本自动化） |
| 输出 | enhanced_layer_plan + preview.html | **enhanced_layer_plan.json**（Figma 导入） |

---

## Agent Responsibilities

### Step 1: Receive Reference Image

1. Save the user's reference image to `01-requirements/references/reference.png`
2. Read image dimensions using PIL
3. Check if dimensions are compliant; if not, inform the user of adjusted dimensions

### Step 2: Visual Analysis → layer_plan.json

Perform the same visual analysis as Phase 2, but with these differences:

**All non-background layers MUST have `precise_layout: true`**:
```json
{
  "name": "sidebar",
  "contents": "Left navigation bar with icons and labels",
  "layout": {"x": 0, "y": 80, "width": 240, "height": 1000},
  "opacity": 0.9,
  "precise_layout": true
}
```

**Why all PL mode**: In separate mode, layers are extracted from the reference image at their exact positions. PL mode ensures the element stays at its original position on the full canvas, which is required for accurate template matching against the reference.

**Background layer**: Keep `precise_layout: false` (or omit). Background uses the full canvas by default.

**Quality tier**: Default to `low` for all layers in separate mode. Override per layer only when visually justified.

**Layer plan output**: Save to `02-confirmation/layer_plan.json` via `PathManager.get_layer_plan_path()`.

### Step 3: Run separate_mode.py

Once layer_plan.json is ready, invoke the automation script:

```bash
python scripts/separate_mode.py \
  --config config.json \
  --project my-app \
  --reference-image 01-requirements/references/reference.png \
  --quality low
```

**The script automates**: PL generation → transparency check + rembg → position detection → enhanced_layer_plan.json.

**Optional flags**:
- `--parallel` — Generate layers in parallel (max 3 workers)
- `--skip-detection` — Skip position detection (if you already have accurate layouts)
- `--skip-matting` — Skip rembg matting (if API outputs true alpha)

### Step 4: Review Results

After the script completes:
1. Check `04-check/detected_layouts.json` for position detection results
2. Check `04-check/enhanced_layer_plan.json` for the final layout data
3. Import into Figma for visual review
4. If positions are off, the user can adjust in Figma or re-run with corrected layouts

---

## Size Handling

- **Reference image dimensions** = `full_size` = `early_size`
- If the image is non-compliant, `separate_mode.py` auto-adjusts to the nearest compliant size and logs a warning
- All PL layers are generated at the **full canvas size** (reference image dimensions)
- No downscaling — the reference image IS the canvas

---

## Output Structure

```
output/{project}/
├── 01-requirements/
│   └── references/
│       └── reference.png          # User's reference image
│   └── size_plan.json             # full_size = early_size = image dimensions
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

## Limitations

- **Template matching quality**: Depends on how well the generated layer matches the reference. Complex textures or AI-introduced variations may cause imperfect matches.
- **PL mode cost**: Each layer is generated at full canvas size, which is more expensive than normal mode per-layer cropping.
- **Opacity < 0.85 layers**: Template matching skips these automatically. The planned layout is used as fallback.
- **Repeat mode**: Supported (grid/list with carrier panels), but the parent layer must be visually distinctive for template matching.

---

## When to Use Separate Mode

| Use Case | Recommendation |
|----------|---------------|
| User has an existing UI screenshot/design | ✅ Separate mode |
| User wants to replicate an existing design | ✅ Separate mode |
| User describes a design from scratch | Standard 8-phase |
| User wants 3 preview options to choose from | Standard 8-phase |
| User wants to iterate on generated previews | Standard 8-phase |

---

## Common Commands

```bash
# Standard separate mode
python scripts/separate_mode.py \
  --config config.json --project my-app \
  --reference-image reference.png

# With parallel generation
python scripts/separate_mode.py \
  --config config.json --project my-app \
  --reference-image reference.png \
  --parallel --quality medium

# Skip detection (if layouts are already accurate)
python scripts/separate_mode.py \
  --config config.json --project my-app \
  --reference-image reference.png \
  --skip-detection
```
