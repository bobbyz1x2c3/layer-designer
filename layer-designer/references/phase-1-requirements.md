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
   - **快速通道**：启用后只生成 1 张预览（默认关闭）

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
- User explicitly says "yes" / "启用" / "快速模式" → Fast Track (generate 1 preview instead of 3)
- No response or "no" → Standard workflow (generate 3 previews)

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

**Fast Track mode**: Generate **1 preview image** only (instead of 3). Same quality rules. Phase 2 is still required after preview confirmation — the only difference is fewer preview options.

---

**If `text-to-image` mode** (default, no reference image):

```bash
python scripts/generate_image.py generate \
  --config config.json \
  --prompt "{overall composition + style + key elements}" \
  --output {preview_path} --size {early_w}x{early_h} --quality {preview_quality}
```

- **Standard**: Invoke 3 times (or once with `--n 3` if API supports it)
- **Fast Track**: Invoke 1 time only (single preview)
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
- **Fast Track**: Invoke 1 time only (single preview)
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
3. After user confirms, proceed to Phase 2 (same as Standard mode).

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
4. Revisions are unlimited. If user repeatedly asks for major changes, suggest switching to standard mode.
5. After user confirms, proceed to Phase 2 (same as Standard mode).

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

---

### Repeat Mode Detection (Grid / List)

During visual analysis, identify whether any regions contain **multiple identical or near-identical elements arranged in a grid or list**:

| Pattern | `repeat_mode` | Examples |
|---------|--------------|----------|
| Grid (rows × columns) | `grid` | Icon matrix, card grid, photo gallery |
| Horizontal list | `list` + `direction: horizontal` | Tab bar, navigation pills, toolbar buttons |
| Vertical list | `list` + `direction: vertical` | Sidebar menu, settings list, vertical tabs |

**When to use repeat_mode:**
- Elements are **visually identical** (same shape, size, style)
- Only content differs slightly (text label, icon) — content can be handled separately
- Using `repeat_mode` reduces API calls from N (one per cell) to 1 (one per parent)

**When NOT to use repeat_mode:**
- Each element has **distinctly different visuals** (e.g., each card has a unique product photo)
- Elements vary significantly in size or shape

**Carrier panel detection (MUST be done alongside repeat detection):**

When you detect a grid/list, always check whether the repeating elements sit inside a **shared carrier panel**:

| Panel Evidence | Description | `auto_panel` Action |
|---------------|-------------|---------------------|
| **Background shape** | Rounded rectangle, card, bar, pill behind all cells | `enabled: true` |
| **Texture / pattern fill** | Gradient, noise, fabric, glass, or decorative texture on the container | `enabled: true` |
| **Decorative border** | Outline, ornamental frame, corner accents, gold trim | `enabled: true` |
| **Shadow / glow** | Drop shadow, inner glow, ambient occlusion around the container | `enabled: true` |
| **No shared container** | Cells float directly on the main background, each has its own isolated background | Omit `auto_panel` |
| **Uncertain** | Partial background or ambiguous edges | Ask user |

The carrier panel is **NOT** the main page background — it is a secondary container that exists specifically to hold the grid/list items. It must be extracted as a separate layer so that the repeat parent layer (the single cell) can be composited on top of it cleanly.

**`repeat_config` fields:**

For `grid`:
| Field | Description | Example |
|-------|-------------|---------|
| `cols` | Number of columns | `3` |
| `rows` | Number of rows | `2` |
| `area_layout` | **Default panel boundary** `{x, y, width, height}`. Defines the full container area and serves as the panel dimensions by default. When `width/height` are provided, cells are positioned inside this area subject to `padding`, and the panel itself uses these exact dimensions. Only use `auto_panel.layout` if the panel needs to deviate from this boundary. When `width/height` are omitted, falls back to legacy mode where `x/y` is the direct cell start. | `{"x": 200, "y": 150, "width": 620, "height": 420}` |
| `padding` | Inner padding between panel edge and cells. Can be a single number (all sides) or `{top, right, bottom, left}`. Defaults to `0`. When `0`, `area_layout` is the exact cell area (no panel gap). | `24` or `{"top": 24, "right": 24, "bottom": 24, "left": 24}` |
| `gap_x` | Horizontal gap between cells (px) | `20` |
| `gap_y` | Vertical gap between cells (px) | `20` |
| `auto_panel` | Optional panel background config. Only needed when the panel deviates from `area_layout`. | See below |

For `list`:
| Field | Description | Example |
|-------|-------------|---------|
| `direction` | `horizontal` or `vertical` | `horizontal` |
| `count` | Number of items | `5` |
| `area_layout` | **Default panel boundary** `{x, y, width, height}`. Defines the full container area and serves as the panel dimensions by default. When `width/height` are provided, cells are positioned inside this area subject to `padding`, and the panel itself uses these exact dimensions. Only use `auto_panel.layout` if the panel needs to deviate from this boundary. When `width/height` are omitted, falls back to legacy mode where `x/y` is the direct cell start. | `{"x": 100, "y": 300, "width": 500, "height": 80}` |
| `padding` | Inner padding between panel edge and cells. Can be a single number (all sides) or `{top, right, bottom, left}`. Defaults to `0`. When `0`, `area_layout` is the exact cell area (no panel gap). | `16` or `{"top": 16, "right": 16, "bottom": 16, "left": 16}` |
| `gap` | Gap between items (px) | `16` |
| `auto_panel` | Optional panel background config. Only needed when the panel deviates from `area_layout`. | See below |

**`auto_panel` — 容器背景层（可选）**

当 grid/list 有明确的容器背景（如卡片矩阵的底板、标签栏的底条）时，可以在 `repeat_config` 中配置 `auto_panel`：

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `enabled` | ✅ | `true` to generate panel | `true` |
| `id` | Optional | Panel layer directory-safe ID | `"card_panel"` |
| `name` | Optional | Display name | `"卡片底板"` |
| `description` | Optional | Content for prompt generation | `"White rounded panel background"` |
| `opacity` | Optional | Panel opacity | `1.0` |
| `quality_tier` | Optional | Generation quality | `"low"` |
| `layout` | Optional | **Override** for panel position/size. Use ONLY when the panel needs to deviate from `area_layout` — e.g., the carrier shape has a drop shadow extending beyond the cell area, or the panel is visually offset from the cell grid. In the common case where the panel perfectly matches the cell area, omit this field and let `area_layout` define the boundary. | `{"x": 190, "y": 140, "width": 620, "height": 420}` |

> ⚠️ **Naming convention for `auto_panel.id`**: MUST use `{parent_id}_panel` format with **underscore** (`_`).
> 
> - Correct: `"equipment_panel"`, `"card_panel"`, `"sidebar_panel"`
> - Incorrect: `"equipment-panel"`, `"card panel"`, `"equipmentPanel"`
> 
> The underscore separator is required because `expand_repeats.py` uses `f"{parent_id}_panel"` as the default panel ID, and downstream scripts (PathManager, generate_preview, Figma plugin) rely on this convention to locate the panel directory and PNG files. Using hyphens or other separators will cause source path mismatches.

**Panel layout 计算方式（优先级从高到低）：**

| 优先级 | 来源 | 说明 |
|--------|------|------|
| **1. 手动覆盖** | `auto_panel.layout` | 最高优先级，直接覆盖所有计算 |
| **2. area_layout** | `repeat_config.area_layout.width/height` | `area_layout` 显式定义 panel 边界时，直接使用其 `width/height` |
| **3. 自动推导** | `cols/rows/gap` 或 `count/direction/gap` | 从 cell 数量和间距推导 panel 大小（向后兼容） |

**Cells 定位规则：**

| 条件 | 行为 |
|------|------|
| `area_layout` 有 `width/height` | `area_layout` 就是 panel 边界（默认）；cells 起始位置 = `area_layout.x + padding.left`, `area_layout.y + padding.top` |
| `area_layout` 只有 `x/y`（legacy） | `area_layout.x/y` 就是 cells 的直接起始位置；无 panel 概念 |
| `padding = 0`（或无 padding） | cells 紧贴 `area_layout` 边缘，panel 和内容区重合 |
| 需要 panel 偏离 `area_layout` | 配置 `auto_panel.layout` 覆盖；此时 panel 用覆盖值，cells 仍按 `area_layout + padding` 定位 |

> **原则**：`area_layout` 就是 panel 的默认边界。只有在视觉上 panel 比 cell 区域大（如阴影外扩）或小（如内凹底板）时，才需要 `auto_panel.layout`。常规情况下完全不需要配置 `auto_panel.layout`。

Panel 在 `stacking_order` 中自动置于实例**下方**。

**Example `layer_plan.json` with repeat_mode + auto_panel:**
```json
{
  "name": "商品卡片",
  "id": "product_card",
  "description": "Product card with image, title, price",
  "layout": {"x": 0, "y": 0, "width": 180, "height": 240},
  "quality_tier": "medium",
  "opacity": 1.0,
  "repeat_mode": "grid",
  "repeat_config": {
    "cols": 3,
    "rows": 2,
    "area_layout": {"x": 200, "y": 150, "width": 620, "height": 420},
    "padding": {"top": 24, "right": 24, "bottom": 24, "left": 24},
    "gap_x": 20,
    "gap_y": 20,
    "auto_panel": {
      "enabled": true,
      "id": "card_panel",
      "name": "卡片底板",
      "description": "White rounded rectangle panel background for card grid",
      "opacity": 1.0,
      "quality_tier": "low"
    }
  }
}
```

---

3. **Save `layer_plan.json`** via `PathManager.get_layer_plan_path()` — no user confirmation needed


4. **Present the layer plan to the user** (informational only, for transparency):
包含图层信息，图层尺寸大小，如果有重复模式，需要告知重复模式的类型和是否有底板
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

**Output upon exit (both modes)**:
- Confirmed preview image path
- `size_plan.json` with validated dimensions (from Step 3)

---

**Exit Condition (both Standard and Fast Track)**: User replies "OK" (and names the chosen preview image for Standard). Proceed to Phase 2.

> ⚠️ **Phase 2 is required for both modes.** Fast Track only reduces the number of previews in Phase 1 (1 vs 3). It does NOT skip Phase 2 layer plan confirmation.
