# Phase 4: Rough Design Check

**Goal**: Verify layer transparency and generate the interactive web preview data for user review.

**When to read this file**: Agent MUST read this file when entering Phase 4. Do not skip this phase — it catches transparency issues and provides the layout review checkpoint before refinement.

**Output Path Pattern**:
```
{output_root}/{project_name}/04-check/
├── enhanced_layer_plan.json     # layout + resource paths for the preview
├── preview.html                 # generic static preview page (from templates/)
└── check_report.json
```

---

## Step 1: Transparency Check

**Script**: `check_transparency.py`

For every non-background layer:

```bash
python scripts/check_transparency.py --config config.json --image {layer_path}
```

- Exit 0 = has transparency (real alpha or solid background detected)
- Exit 1 = opaque or error

### Handling Non-Transparent Layers

The API endpoint currently outputs RGB mode PNGs (no real alpha channel). When `check_transparency.py` reports a layer lacks true transparency, the agent MUST follow this workflow:

1. **Report to user**:
   > "图层 `{layer_name}` 没有真实的 Alpha 透明底（API 端点目前只输出 RGB 模式）。检测到纯色背景，可以使用 U²Net 深度学习模型自动扣除背景。"

2. **Auto-remove background** via rembg:
   ```bash
   python scripts/check_transparency.py --config config.json \
     --image {layer_path} --remove-bg --output {layer_path}_matte.png
   ```
   - Uses skill-internal `models/u2net.onnx` (U²Net model)
   - Outputs true RGBA PNG with feathered edges
   - The script JSON output will include `"matte"` field with details

3. **Ask user for confirmation**:
   > "已自动扣除背景并生成透明 PNG。是否继续？"

4. **If user confirms**: Replace the original layer with the matte version and proceed to Step 2.

5. **If user declines**: Skip this layer (treat as opaque) or return to Phase 3 to regenerate.

### Post-matte auto-crop for all non-background layers

After all layers have been matted (step 2 above), **run auto-crop on every non-background layer**:

```bash
python scripts/crop_to_content.py \
  --input {matte_path} --output {cropped_path} --padding 4
```

- `{matte_path}`: the rembg output from step 2 (e.g. `{layer_name}_matte.png`)
- `{cropped_path}`: `{layer_dir}/{layer_name}_cropped.png`
- `--padding 4`: leaves a small 4px transparent margin around the element for clean edge compositing
- This runs **after** rembg because `crop_to_content` needs a reliable alpha channel to detect content bounds. Cropping before matting is unreliable.
- Layers whose content already fills the entire canvas will keep their original size (bbox equals full image) — no harm done.
- Replace the matte version with the cropped version in `enhanced_layer_plan.json` source paths.

**Why uniform cropping**: The updated Phase 3 prompt instructs the model to leave a 3-5% transparent margin around the element. After rembg, this margin becomes transparent padding that should be trimmed for tighter compositing.

**`extreme_ratio` layers**: Layers flagged with `extreme_ratio: true` in `layer_plan.json` are also cropped here. The flag is preserved for informational purposes (e.g. debugging aspect ratio issues) but no longer triggers a separate crop path.

**Note**: The `--remove-bg` flag now always triggers rembg when explicitly passed, regardless of detection result. This is a best-effort optimization — even if no solid background was detected, rembg may still produce usable results. True RGBA images with alpha==0 pixels are not re-processed (they already have transparency).

**Auto-padding for large-foreground layers**: When a UI control occupies most of the image (e.g., a full-width banner or large panel), rembg may misclassify the foreground as background. `check_transparency.py` automatically detects this condition (foreground > 70% of pixels) and adds temporary padding before matting, then crops back to the original size. The JSON output includes `"padded": true` when this happens. Use `--pad` to force padding, or `--no-pad` to disable it.

---

## Step 2: Detect Layer Positions (On-Demand — Algorithmic Layout Refinement) 【实验性的】

**Script**: `detect_layer_positions.py`

This step is **not run by default** and is currently **experimental**. It is offered to the user in Step 3 when they report that layers look misaligned in the preview.

**What it does**:
1. Reads each layer PNG (post-rembg/crop) as a template
2. Searches a large ROI around the planned position (±200% margin)
3. Tries multiple scales (0.65×–1.35× planned size) to handle `crop_to_content` drift
4. Matches via downsampled SSD + fine refinement
5. Outputs `04-check/detected_layouts.json`

**Adaptive multi-feature profiles**: The matcher fuses multiple visual features weighted by a profile. The agent inspects the preview, selects a profile, writes `match_profile.json`, and the detection script reads it. **General rule: use `default` unless the UI clearly falls into a specialized category.** See [`references/matching-profiles.md`](references/matching-profiles.md) for the full selection guide. Use `--profile <name>` to enable.

**Limitations** — tell the user before offering:
- Layers with **high transparency** (opacity < 0.85) are skipped automatically because the preview shows blended colors while the extracted layer is opaque
- Layers with **very few visible pixels** (e.g., a small icon on a large transparent canvas) may not match accurately
- Independent AI-generated layers can have color differences from the preview, causing imperfect matches

**When to run**: Only after the user confirms they want it. The agent should NOT run this automatically.

**Detection Workflow**:
```bash
# 1. User confirms they want algorithmic alignment
# 2. Run detection (read-only, does not modify any layer images)
#    By default, all non-background, non-repeat layers are processed.
python scripts/detect_layer_positions.py \
  --project my-app --config config.json \
  --preview output/my-app/01-requirements/previews/preview_v2_001.png \
  --phase rough

# 2b. Detect only specific layers (useful when only a few layers are misaligned)
python scripts/detect_layer_positions.py \
  --project my-app --config config.json \
  --preview output/my-app/01-requirements/previews/preview_v2_001.png \
  --phase rough \
  --layer sidebar \
  --layer header

# 2c. Override matching profile manually
python scripts/detect_layer_positions.py \
  --project my-app --config config.json \
  --preview output/my-app/01-requirements/previews/preview_v2_001.png \
  --phase rough \
  --profile structure_heavy

# 4. Apply detected layouts (backs up existing enhanced_layer_plan.json)
python scripts/generate_preview.py \
  --config config.json \
  --project my-app \
  --phase check \
  --apply-detected-layouts
```

**Per-layer detection**: The `--layer` / `-l` flag accepts a layer `id` or `name` and can be used multiple times. Only the specified layers will be template-matched; others are skipped. This is useful when:
- The user reports only 1–2 specific layers are misaligned
- You want to quickly verify a single layer's detection quality before running on all layers
- Running on all layers is too slow and only a subset needs correction

**Force mode** (`--force`): Bypasses all safety checks (opacity < 0.85, background, repeat) and attempts template matching on every requested layer. Use **only** when the user explicitly demands it — e.g., a semitransparent panel that the user insists on aligning, or a repeat parent whose single-cell template happens to be distinctive enough to match. Warn the user that forced detection may produce unreliable results.
```bash
# Force detect a semitransparent layer that is normally skipped
python scripts/detect_layer_positions.py \
  --project my-app --config config.json \
  --preview output/my-app/01-requirements/previews/preview_v2_001.png \
  --phase rough \
  --layer glass_panel \
  --force
```

---

## Step 2: Expand Repeat Mode Layers (if applicable)

**Script**: `expand_repeats.py`

If `layer_plan.json` contains layers with `repeat_mode: "grid"` or `repeat_mode: "list"`, expand them into individual instances before generating the preview:

```bash
python scripts/expand_repeats.py \
  --config config.json \
  --project {project_name} \
  --input 02-confirmation/layer_plan.json \
  --output 04-check/expanded_layer_plan.json
```

This script:
- Reads `layer_plan.json` and detects `repeat_mode` layers
- Computes per-instance layouts based on `repeat_config`
- Writes `expanded_layer_plan.json` with all instances as individual layer entries
- Each instance shares the same `source` path (pointing to the parent layer's PNG)

**When to run**: Always run before `generate_preview.py` if `repeat_mode` is present. If no `repeat_mode` layers exist, the script outputs a no-op message and `generate_preview.py` will fall back to `layer_plan.json`.

---

## Step 3: Generate Enhanced Layer Plan

**Script**: `generate_preview.py` (generates JSON + copies template)

Generate the `enhanced_layer_plan.json` and copy the generic preview template:

```bash
# Standard (scaled planned layouts, auto-prefers expanded_layer_plan.json)
python scripts/generate_preview.py \
  --config config.json \
  --project {project_name} \
  --phase check

# Apply algorithmically detected layouts (only after user confirms)
python scripts/generate_preview.py \
  --config config.json \
  --project {project_name} \
  --phase check \
  --apply-detected-layouts
```

This produces:
- `04-check/enhanced_layer_plan.json` — contains layout, resource paths, and metadata
- `04-check/preview.html` — static preview page copied from `templates/preview.html`

### `enhanced_layer_plan.json` format

```json
{
  "project": "my-dashboard",
  "phase": "check",
  "dimensions": {"width": 1024, "height": 640},
  "style_anchor": "Flat design, primary blue #3B82F6...",
  "layers": [
    {
      "name": "sidebar",
      "content": "Left navigation bar with icons and labels",
      "status": "active",
      "layout": {"x": 0, "y": 80, "width": 240, "height": 560},
      "source": "03-rough-design/sidebar/sidebar_20260425_001.png"
    }
  ],
  "stacking_order": ["background", "sidebar", "header", "buttons"]
}
```

The `source` field is the relative path from `04-check/` to the layer PNG. The `layout` values are scaled to `early_size` for the rough phase.

---

## Step 3: Notify User

Send a message to the user with:
1. The location of `enhanced_layer_plan.json`
2. The location of `preview.html`
3. A summary of the layer list

**Example message**:
> **Phase 4 布局预览已生成**
>
> 📁 数据文件：`04-check/enhanced_layer_plan.json`
> 🌐 预览网页：`04-check/preview.html`
>
> 当前图层（共 4 个）：
> - background (1920×1080) @ (0, 0)
> - sidebar (240×1000) @ (0, 80)
> - header (1680×80) @ (240, 0)
> - buttons (280×60) @ (1520, 960)
>
> **请打开 `preview.html` 查看布局效果。**
> 你可以直接在浏览器中：
> - 拖拽图层调整位置
> - 拖拽边角手柄调整大小
> - 在右侧面板修改 Name / Content / Status / Layout 数值
> - 点击 **💾 Save JSON** 导出修改后的 `enhanced_layer_plan.json`
>
> 导出的 JSON 可以：
> - 直接替换 `04-check/enhanced_layer_plan.json`
> - 或发送给我，由我来替换
>
> 如果布局满意，请选择：
> - 回复 **OK** → 进入精修阶段（Phase 5~7，高质量最终输出）
> - 回复 **EXIT** → 不需要精修，直接使用当前粗稿图层交付（适合只需要效果图/预览的场景）
> - 告诉我具体问题，或自行调整后导出 JSON。
>
> **布局偏移？** 如果发现某些图层位置不对，我可以尝试用多尺度模板匹配算法在预览图中找到更准确的位置。
> - 适用于：不透明控件、角色立绘、按钮等**内容明确**的图层
> - 不适用于：半透明面板（opacity < 0.85）、大面积透明只剩小图标的图层、启用了grid或list的控件
> - 需要时请回复：**"尝试算法对齐"**

---

## Step 4: User Confirmation

**Wait for explicit user confirmation before proceeding.**

**User replies**:
- **"OK"** → Proceed to Phase 5 (Refinement Preview)
- **"EXIT" / "退出" / "不需要精修" / "直接交付"** → Proceed to Step 6 (Fast Delivery with rough layers)
- **"I want to edit myself" / no reply yet** → Wait. The user may open `preview.html`, adjust the layout, and export a new JSON.
- **"尝试算法对齐"** / **"use algorithm"** / **"align layers"** → Run Step 2 (`detect_layer_positions.py`), then re-run `generate_preview.py --apply-detected-layouts` (backs up the previous plan automatically), show the updated preview, and ask for confirmation again.
- **Provides a new `enhanced_layer_plan.json`** → Replace the existing one in `04-check/`, optionally re-run `generate_preview.py` to refresh, then ask for confirmation again.
- **Adjustment request** (describes issues) → Go to Step 5 (Batch Fix)

**Important**: The agent MUST receive an explicit "OK" or "EXIT" before leaving Phase 4. Do NOT proceed automatically.

---

## Step 5: Batch Fix (if issues found)

If the user reports visual issues:

1. **Batch collection**: Identify ALL problematic layers in one pass, document each issue
2. **Update layout if needed**: The user may provide an updated `enhanced_layer_plan.json` with corrected positions
3. **Batch regeneration**: Return ALL problematic content layers to Phase 3 simultaneously
   - Reinvoke `generate_image.py edit` for each problematic layer with optimized prompt:
     - Original preview image
     - Description of the issue to fix
   - If `parallel_generation` enabled: regenerate all problem layers in parallel
4. Save new versions with timestamps in respective layer folders
5. Re-run Phase 4 (transparency check → generate enhanced plan → notify user → wait for OK)
6. Iterate until clean or max iterations reached

**Max Iterations**: 20 (configurable, default 20)

---

## Step 6: Fast Delivery (if user exits at Phase 4)

If the user chooses **EXIT** without entering refinement (Phase 5~7), deliver the rough layers directly:

1. **Copy rough layers** from `03-rough-design/{layer_name}/` to `07-output/layers/` with clean names (no timestamps):
   - `background_001.png` → `background.png`
   - `sidebar_001.png` → `sidebar.png`
   - etc.

2. **Copy preview** from `04-check/preview.html` to `07-output/preview.html`

3. **Copy `enhanced_layer_plan.json`** to `07-output/enhanced_layer_plan.json`

4. **Generate `manifest.json`**:
   ```json
   {
     "project": "my-dashboard",
     "dimensions": {"width": 1920, "height": 1080},
     "style_anchor": "...",
     "layers": [...],
     "stacking_order": [...],
     "previews": {
       "check": "04-check/preview.html",
       "final": "07-output/preview.html"
     },
     "refinement_skipped": true,
     "variants_requested": false
   }
   ```

5. **Present to user**:
   > "已直接交付粗稿图层（未进入精修阶段）。所有图层位于 `07-output/layers/`，预览网页为 `07-output/preview.html`。"

**Use case**: User only needs preview-quality assets or reference images, not pixel-perfect final deliverables.

---

**Exit Condition**: All layers pass transparency check AND user replies **"OK"** or **"EXIT"**.

**Output upon exit (OK path)**:
- `04-check/enhanced_layer_plan.json` — final layout data (may have been user-edited)
- `04-check/preview.html` — static preview page
- `04-check/check_report.json` — issue log and fix history

**Output upon exit (EXIT path)**:
- `07-output/layers/*.png` — rough layers with clean names
- `07-output/preview.html` — web preview
- `07-output/enhanced_layer_plan.json` — layout data
- `07-output/manifest.json` — delivery manifest with `refinement_skipped: true`
