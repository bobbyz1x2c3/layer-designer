# Phase 1: Requirements

**Goal**: Collect all user requirements, validate dimensions, determine workflow mode, and produce preview candidates for user selection.

**When to read this file**: Agent MUST read this file when entering Phase 1 of the workflow. Do not proceed with Phase 1 operations without reading this document first.

**Output Path Pattern**:
```
{output_root}/{project_name}/01-requirements/
├── previews/
│   ├── preview_v1_001_{timestamp}.png
│   ├── preview_v1_002_{timestamp}.png
│   ├── preview_v1_003_{timestamp}.png
│   ├── preview_v2_001_{timestamp}.png  (revisions)
│   └── ...
├── references/
│   └── ref_image_{timestamp}.png       (only if user provided reference image)
├── size_plan.json                      (produced by validate_size.py)
└── conversation_log.json
```

---

## Step 1: Send Onboarding Message

When the user first invokes this skill, send a structured onboarding message. Do NOT jump straight to generation.

**Agent message template**:
```
你好！我是分层设计生成助手。我会通过 8 个阶段为你生成分层的 UI 设计资产：

1. 需求确认 → 2. 图层拆分方案 → 3. 粗稿分层 → 4. 网页预览校验
→ 5. 精修预览 → 6. 精修图层 → 7. 最终交付 → 8. 状态变体（可选）

每个图层都会输出带真实透明通道（Alpha）的 PNG，方便你后续单独使用或二次编辑。

为了开始，请提供以下信息：

━━━━━━━━━━━━━━━━━━━━
【必需】
1. 目标尺寸（宽 × 高，单位像素）：
   例如：1920×1080、1024×1024、375×812
   （我会自动验证尺寸是否符合生成模型要求，如不符合会给出建议）

━━━━━━━━━━━━━━━━━━━━
【强烈建议提供】
2. 应用类型与用途：
   例如：电商后台管理面板、SaaS 仪表盘、游戏 HUD、移动端设置页

3. 视觉风格偏好：
   例如：扁平化 / 毛玻璃 (Glassmorphism) / 新拟态 (Neumorphism)
         / 暗色主题 / 极简风 / Material Design 等

4. UI 基本规则与设计规范：
   如果有设计系统文档、组件库规范、品牌指南，请直接粘贴或上传

5. 参考图 / 原型图：
   如果有线框图、手绘草图、竞品截图或现有 UI 截图，请上传
   → 我会基于参考图生成预览（图生图模式），更贴近你的预期

6. 预览质量模式：
   - **标准预览**（默认）：early_size ≈ 25–40% 面积，quality = low，成本低、速度快
   - **高质量预览**：early_size ≈ 60% 面积，quality = medium，细节更丰富，适合对精细度要求高的设计
   - **快速通道**：启用后 Phase 1~2 合并，只需确认 1 张预览即可进入分层阶段（默认关闭）

7. 重复元素模式（可选，Phase 2 自动检测）：
   - 如果设计中有大量重复的相同元素（如卡片网格、图标矩阵、列表项），我会在 Phase 2 自动检测并提示你启用「复用模式」
   - 复用模式可以大幅减少生成时间和成本（例如 3×3 卡片网格从 9 次生成降到 1 次）
   - 你也可以提前告诉我是否有重复元素，方便我提前规划
━━━━━━━━━━━━━━━━━━━━

你可以逐项回复，也可以一次性提供所有信息。收到后我会立即开始工作。
```

---

## Step 2: Collect Requirements

Gather the following from the user's response. Use clarifying questions if any item is missing or vague.

| # | Item | Required | Clarifying Question if Missing |
|---|------|----------|-------------------------------|
| 1 | **Dimensions** (width × height) | ✅ Required | "请提供目标尺寸（宽×高，单位像素），这是必需的。" |
| 2 | **App type & purpose** | Recommended | "这个 UI 是用在什么场景里的？（Web / App / 游戏 / 其他）" |
| 3 | **Visual style** | Recommended | "你希望是什么视觉风格？可以发参考图给我。" |
| 4 | **Design spec / rules** | Optional | — |
| 5 | **Reference image** | Optional | — |
| 6 | **Preview quality mode** | Optional (default: standard) | "请选择预览质量模式：标准预览（默认）或高质量预览？" |
| 7 | **Fast workflow** | Optional (default: off) | "是否启用快速通道？（是/否）" |
| 8 | **Repeat elements** | Optional | "设计中是否有大量重复的相同元素？（如卡片网格、图标矩阵、列表项）" |

**Determine preview quality mode**:
- User says "高质量" / "high quality" / "细节丰富" → High-Quality Preview mode
  - `downsize_ratio = 0.775` (~60% area for early_size)
  - Preview generation `quality = medium`
- No response or "标准" / "standard" / "默认" → Standard mode
  - `downsize_ratio = 0.5` (~25% area for early_size)
  - Preview generation `quality = low`

**Determine input mode** based on whether a reference image was provided:
- **No reference image** → `text-to-image` mode (default)
- **Reference image provided** → `reference-image` mode

**Determine fast track** based on user response:
- User explicitly says "yes" / "启用" / "快速模式" → Fast Track (merge Phase 1~2)
- No response or "no" → Standard workflow

---

## Step 3: Validate Dimensions (REQUIRED)

**Before any image generation, ALWAYS invoke `validate_size.py`.**

```bash
python scripts/validate_size.py --project {project_name} --width {W} --height {H}
```

**What the script does**:
1. Checks dimensions against `gpt-image-2` model constraints (max edge ≤ 3840, multiple of 16, aspect ratio ≤ 3:1, min pixels ≥ 655,360)
2. If invalid: computes the nearest compliant size preserving aspect ratio
3. Computes `early_size` (for Phase 1~4) and `full_size` (for Phase 5~8)
4. Saves the plan to `01-requirements/size_plan.json`

**If invalid** (exit code 1):
- Present the script output to the user:
  - Which constraints were violated
  - Recommended nearest compliant size
  - Early-phase and full-phase dimensions
- Ask user to confirm the suggested size or provide a different one
- **Repeat Step 3** with the new dimensions until valid
- **Do NOT proceed to preview generation while dimensions are invalid**

**If valid** (exit code 0):
- Confirm to user: "尺寸 W×H 已验证通过。"
- Report: "粗稿阶段尺寸：W'×H'（Phase 1~4）｜精修阶段尺寸：W×H（Phase 5~8）"
- The size plan is now saved and will be reused by all subsequent phases

**Example dialog (invalid → valid)**:
> User: "4000×1000"  
> Agent: *[runs `validate_size.py --width 4000 --height 1000`]*  
> Agent: "尺寸 4000×1000 不符合 gpt-image-2 约束：
> - 最大边长超过 3840px
> - 宽高比 4:1 超过最大允许 3:1
> 建议的最接近合规尺寸：3696×1232（宽高比 3.00）
> 粗稿阶段将使用：1440×480
> 请确认使用该尺寸，或提供其他尺寸。"  
> User: "确认用 3696×1232"  
> Agent: "尺寸已确认。3696×1232 验证通过。粗稿阶段：1440×480。"

---

## Step 4: Read Size Plan

After validation succeeds, read `01-requirements/size_plan.json` to obtain:
- `full_size`: target dimensions for Phase 5~8
- `early_size`: reduced dimensions for Phase 1~4

**Early-phase size logic** (handled automatically by `validate_size.py`):
- If `downsize_early_phases` is enabled and target is not tiny: the script computes a downscaled size based on the selected preview quality mode
- If the downscaled size violates model constraints (e.g., below min pixels), the script finds the **smallest compliant size** that preserves aspect ratio
- If target is tiny (`W < 300` or `H < 200` or `W×H < 60000`): no downsize is applied

**Preview quality mode differences**:

| Mode | downsize_ratio | Preview quality | When to use |
|------|---------------|-----------------|-------------|
| **Standard** | 0.5 | `low` | Default. Faster, lower cost. Good for iterative exploration. |
| **High-Quality** | 0.775 | `medium` | When fine details matter. ~60% area retains more texture, text legibility, and element sharpness. Costs ~2× tokens/time. |

**Example sizes (Standard vs High-Quality)**:
| User Request | Full Size | Standard Early | High-Quality Early | Notes |
|-------------|-----------|---------------|-------------------|-------|
| 1920 × 1080 | 1920 × 1080 | 1088 × 608 | 1392 × 784 | HQ preserves ~60% area vs ~38% |
| 1024 × 1024 | 1024 × 1024 | 816 × 816 | 1024 × 1024 | 0.775× = 784×784 < min_pixels → falls back to full size |
| 3840 × 2160 | 3840 × 2160 | 1920 × 1080 | 2960 × 1664 | HQ retains significantly more detail |

---

## Step 5: Generate Preview Candidates

**Standard mode**: Generate **3 preview images** using the `early_size` from Step 4.
- Standard preview quality: `low`
- High-quality preview quality: `medium`

**Fast Track mode**: Generate **1 preview image** only. Same quality rules.

---

**If `text-to-image` mode** (default, no reference image):

```bash
python scripts/generate_image.py generate \
  --config config.json \
  --prompt "{overall composition + style + key elements}" \
  --output {preview_path} --size {early_w}x{early_h} --quality {preview_quality}
```

- **Standard**: Invoke 3 times (or once with `--n 3` if API supports it)
- **Fast Track**: Invoke 1 time only
- Prompt: see [references/prompt-templates.md](references/prompt-templates.md) "Phase 1: Preview Generation"
- Save each via `PathManager.get_preview_path(version=1, index=N)`

**If `reference-image` mode** (user provided reference image):

1. Save the reference image to `01-requirements/references/ref_image_{timestamp}.png`
2. Generate from reference:

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image {reference_image_path} \
  --prompt "{reference interpretation + refinement prompt}" \
  --output {preview_path} --size {early_w}x{early_h} --quality {preview_quality}
```

- **Standard**: Invoke 3 times
- **Fast Track**: Invoke 1 time only
- Prompt: see [references/prompt-templates.md](references/prompt-templates.md) "Phase 1: Reference-Image Preview Generation"
- Save each via `PathManager.get_preview_path(version=1, index=N)`

---

## Step 6: Present & Collect Feedback

**Standard mode**:
1. Present all 3 preview images to the user with labels (A, B, C or 1, 2, 3)
2. Ask: "请选择最喜欢的一张，或告诉我需要修改的地方。"

**Fast Track mode**:
1. Present the single preview image to the user
2. Ask: "这是根据你的需求生成的预览，请确认或提出修改意见。"

3. Maintain a conversation log of all previews and feedback (append to requirements phase log)

---

## Step 7: Revision Loop (if needed)

**Standard mode**:
If user requests changes (NOT "OK"):
1. Generate **2 revised previews** per round incorporating user's feedback
2. **MUST use `generate_image.py edit`** (image-to-image), passing the **selected base preview** as `--image`:
   ```bash
   python scripts/generate_image.py edit \
     --config config.json \
     --image {selected_preview_path} \
     --prompt "Based on this UI design, modify: {user's change requests}. Keep the overall layout and style consistent. {style_anchor if already extracted}." \
     --output {revised_preview_path} --size {early_w}x{early_h} --quality {preview_quality}
   ```
   - **Default**: Use the selected preview as base
   - **Major structural changes only**: May use the original reference image as base instead
3. Same parameters as Step 5, but with updated prompt reflecting feedback
4. Increment version number (`version=2, 3, ...`)
5. Present revised previews and repeat

**Revision prompt template**:
```
Based on this UI design, modify: {user's change requests}.
Keep the overall layout and style consistent.
{style_anchor if already extracted}
```

**Max revision rounds**: Unlimited (until user says "OK"). In practice, most workflows complete within 1~3 rounds.

**Fast Track mode**:
If user requests changes (NOT "OK"):
1. Generate **1 revised preview** incorporating feedback
2. **MUST use `generate_image.py edit`** (image-to-image), passing the confirmed preview as `--image`:
   ```bash
   python scripts/generate_image.py edit \
     --config config.json \
     --image {confirmed_preview_path} \
     --prompt "Based on this UI design, modify: {user's change requests}. Keep the overall layout and style consistent. {style_anchor}." \
     --output {revised_preview_path} --size {early_w}x{early_h} --quality {preview_quality}
   ```
3. Present the revised preview and ask for confirmation
4. In fast track, revisions are unlimited. If user repeatedly asks for major changes, suggest switching to standard mode.

**Parallel execution** (if `parallel_generation` enabled and agent supports subagents):
- Multiple independent revisions can be spawned concurrently
- Each subagent invokes `generate_image.py` with its own prompt variation
- Master agent collects all results before presenting to user

---

## Step 8: Wait for "OK" (Preview Confirmation)

**Require explicit "OK"** from user to confirm the preview. The confirmation must include:
- The word "OK" (or equivalent confirmation)
- In standard mode: identification of the chosen preview (e.g., "OK, 选第2张")

**If user is not satisfied** after multiple revision rounds:
- Offer to return to Step 5 and generate a new set of previews
- Or offer to switch input mode (e.g., suggest uploading a reference image)

---

## Step 9: Phase 2 — Layer Plan (Fast Track Only)

> **In Fast Track mode, Phase 2 is merged into Phase 1 and executed automatically after preview confirmation.**
> **In Standard mode, skip this step and proceed to the separate Phase 2 document.**

**⚠️ CRITICAL: Fast Track does NOT skip `layer_plan.json`.** The layer plan is just as essential as in Standard mode — it drives Phase 3 layer isolation, Phase 4 preview, and all subsequent phases.

**Fast Track requires only ONE user confirmation** (Step 8 preview OK). After that, the agent automatically generates and saves the layer plan — **no second OK needed**.

After the user confirms the preview (Step 8 OK):

1. **Visually analyze the confirmed preview** using the agent's visual understanding capability
2. Produce a **complete `layer_plan.json`** directly from the preview. The JSON must include:

| Field | Required | Description |
|-------|----------|-------------|
| `project` | ✅ | Project name |
| `dimensions` | ✅ | `{"width": W, "height": H}` — full canvas size |
| `layers` | ✅ | Array of layer objects (see below) |
| `stacking_order` | ✅ | Array of layer names, bottom → top |
| `style_anchor` | ✅ | Style summary string for all prompts |

**Each layer object must contain**:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Display name (can be Chinese or English) |
| `id` | ✅ | Directory-safe identifier (English, kebab/snake case). Used as folder name in `03-rough-design/` and `06-refinement-layers/`. |
| `description` | ✅ | Content description for prompt generation |
| `layout` | ✅ | `{"x", "y", "width", "height"}` — bounding box in full canvas coordinates |
| `quality_tier` | ✅ | `low` / `medium` / `high` |
| `opacity` | ✅ | `0.2` ~ `1.0` — visual opacity when stacked over other layers (see judgment rules below) |
| `is_background` | Optional | `true` for background layer |
| `stack_order` | Optional | Integer position in stack (used if no top-level `stacking_order`) |
| `states` | Optional | Array of state names (e.g., `["hover", "active"]`) |
| `repeat_mode` | Optional | `"grid"` or `"list"` — see Phase 2 Step 5 for detection rules |
| `repeat_config` | Optional | Configuration dict for repeat expansion (see Phase 2) |

**Visual Opacity Judgment** (same as Standard Mode Phase 2 Step 5):

For each layer, visually judge whether it should be **semi-transparent** when stacked over other layers:

| Opacity | Visual Type | Examples |
|---------|-------------|----------|
| `1.0` | Fully opaque | Solid backgrounds, characters, icons, text labels |
| `0.75–0.9` | Slightly translucent | Frosted glass panels, card backgrounds with blur |
| `0.5–0.7` | Moderately transparent | Floating overlays, HUD elements, modal backdrops |
| `0.2–0.4` | Highly transparent | Glow effects, particle layers, vignettes |

**How to judge**:
- Use the agent's visual understanding on the confirmed preview
- A glass panel that shows underlying content underneath → translucent
- A solid button or icon with no visible background bleed → opaque
- A glow or shadow effect → highly transparent

**Example `layer_plan.json` structure**:
```json
{
  "project": "my-dashboard",
  "dimensions": {"width": 1920, "height": 1080},
  "style_anchor": "Flat design, primary blue #3B82F6, Inter font, 8px grid, rounded 12px corners, soft shadows",
  "layers": [
    {
      "id": "background",
      "name": "背景",
      "description": "Solid dark navy fill with subtle gradient texture",
      "is_background": true,
      "quality_tier": "low",
      "opacity": 1.0,
      "layout": {"x": 0, "y": 0, "width": 1920, "height": 1080}
    },
    {
      "id": "sidebar",
      "name": "侧边栏",
      "description": "Left navigation bar with icons and labels",
      "quality_tier": "medium",
      "opacity": 0.9,
      "layout": {"x": 0, "y": 80, "width": 240, "height": 1000}
    },
    {
      "id": "header",
      "name": "顶部标题栏",
      "description": "Top bar with logo, search input, avatar",
      "quality_tier": "medium",
      "opacity": 1.0,
      "layout": {"x": 240, "y": 0, "width": 1680, "height": 80}
    }
  ],
  "stacking_order": ["background", "sidebar", "header"]
}
```

3. **Save `layer_plan.json`** via `PathManager.get_layer_plan_path()` — no user confirmation needed

4. **Detect repeat patterns** (same as Standard Mode Phase 2 Step 5):
   - Inspect the confirmed preview for grid/list patterns
   - **Panel / carrier detection**: When repeat patterns are detected, also check whether the grid/list has a **carrier panel** — a visible container that holds the repeating elements, including:
     - Background shape (rounded rectangle, card, bar, pill)
     - Texture or pattern fill on that shape
     - Decorative borders, outlines, or ornamental framing
     - Drop shadow, inner glow, or ambient occlusion around the container
     - Any visual element that is **shared across all cells** and **positioned beneath them**
   - If a carrier panel exists → include `auto_panel: {enabled: true, ...}` in `repeat_config`
   - If cells float directly on the main background with no shared container → omit `auto_panel`
   - If uncertain → ask user: "检测到重复布局，该区域的子项是否共享一个容器面板（底板/卡片/条）？"
   - If user confirmed in Phase 1 Step 2 ("是否有大量重复元素"), use that as a hint but still verify visually

5. **Present the layer plan to the user** (informational only, for transparency):
```
预览已确认。我已自动生成分层方案，即将进入粗稿分层阶段：

图层列表（从底到顶）：
1. background — 渐变背景
2. sidebar — 左侧导航栏
3. header — 顶部标题栏
4. card_container — 数据卡片容器
5. chart — 折线图
6. buttons — 操作按钮组

Style Anchor: 暗色主题，圆角 8px，蓝色主色调 #3B82F6...

如需要调整图层方案，可随时告知。现在开始生成粗稿图层。
```

**Output upon exit (Fast Track)**:
- Confirmed preview image path
- **`layer_plan.json`** saved to `02-confirmation/` (⚠️ **REQUIRED** for all downstream phases)
- `size_plan.json` with validated dimensions (from Step 3)
- `style_anchor` string for all subsequent prompts

---

**Exit Condition (Standard mode)**: User replies "OK" and names the chosen preview image. Proceed to separate Phase 2.

**Exit Condition (Fast Track mode)**: **After Step 8 user OK, automatically execute Step 9 and enter Phase 3.** No second confirmation required. Ensure the following before proceeding:

1. ✅ `layer_plan.json` is **saved** to `02-confirmation/layer_plan.json`
2. ✅ `size_plan.json` exists in `01-requirements/` (from Step 3)
3. ✅ `style_anchor` is extracted and written to `layer_plan.json`

> ⚠️ **Do NOT enter Phase 3 if `layer_plan.json` is missing or incomplete.** Phase 3 requires `layer_plan.json` to know which layers to generate, their `layout` for per-layer sizing, and their `id` for folder naming. Without it, the workflow cannot proceed.

**Pre-Phase-3 checklist (Fast Track)**:
```
□ layer_plan.json exists and contains: dimensions, layers[], stacking_order[], style_anchor
□ size_plan.json exists and contains: full_size, early_size
□ style_anchor string is non-empty
□ All layer objects have: id, name, description, layout, quality_tier, opacity
```

Only after all checks pass: proceed to Phase 3.
