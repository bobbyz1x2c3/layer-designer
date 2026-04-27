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

**Note**: The `--remove-bg` flag now always triggers rembg when explicitly passed, regardless of detection result. This is a best-effort optimization — even if no solid background was detected, rembg may still produce usable results. True RGBA images with alpha==0 pixels are not re-processed (they already have transparency).

**Auto-padding for large-foreground layers**: When a UI control occupies most of the image (e.g., a full-width banner or large panel), rembg may misclassify the foreground as background. `check_transparency.py` automatically detects this condition (foreground > 70% of pixels) and adds temporary padding before matting, then crops back to the original size. The JSON output includes `"padded": true` when this happens. Use `--pad` to force padding, or `--no-pad` to disable it.

---

## Step 2: Generate Enhanced Layer Plan

**Script**: `generate_preview.py` (generates JSON + copies template)

Generate the `enhanced_layer_plan.json` and copy the generic preview template:

```bash
python scripts/generate_preview.py \
  --config config.json \
  --project {project_name} \
  --phase check
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

---

## Step 4: User Confirmation

**Wait for explicit user confirmation before proceeding.**

**User replies**:
- **"OK"** → Proceed to Phase 5 (Refinement Preview)
- **"EXIT" / "退出" / "不需要精修" / "直接交付"** → Proceed to Step 6 (Fast Delivery with rough layers)
- **"I want to edit myself" / no reply yet** → Wait. The user may open `preview.html`, adjust the layout, and export a new JSON.
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
