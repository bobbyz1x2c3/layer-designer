# Phase 2: Confirmation

**Goal**: Analyze the confirmed preview visually and produce a formal layer breakdown plan.

**When to read this file**: Agent MUST read this file when entering Phase 2 of the workflow. This phase is **required for both Standard and Fast Track modes** — Fast Track only reduces the number of previews in Phase 1 (1 vs 3), but does NOT skip Phase 2.

**Input**: The preview image confirmed in Phase 1 Step 8.

**Output Path Pattern**:
```
{output_root}/{project_name}/02-confirmation/
└── layer_plan.json
```

---

## Step 1: Visual Analysis

Use the agent's visual understanding capability to inspect the confirmed preview:
- Identify all distinct visual regions / components
- Determine which elements should be on separate layers
- Note the stacking order (what is behind what)
- **Detect repeat patterns** (grid/list): Look for multiple identical or near-identical elements arranged in a pattern
- **Detect carrier panels** for repeats: Check whether any grid/list has a **shared container panel** that carries the repeating elements. A carrier panel includes:
  - Background shape (rounded rectangle, card, bar, pill, etc.)
  - Texture, gradient, or pattern fill on that shape
  - Decorative borders, outlines, ornamental framing
  - Drop shadow, inner glow, ambient occlusion
  - Any visual element that is **shared across all cells** and **positioned beneath them**
  - If present → this panel becomes a separate layer with `auto_panel`
  - If absent → cells float directly on the main background

---

## Step 2: Define Layer Breakdown

For each layer, document:

| Field | Description | Example |
|-------|-------------|---------|
| **Layer name** | kebab-case or snake_case | `sidebar`, `header`, `card_container` |
| **Layer contents** | What elements this layer contains | "Left navigation bar with icons and labels" |
| **Controls** | Buttons, inputs, toggles in this layer | `submit_btn`, `search_input` |
| **States per control** | hover, active, disabled, focused, checked | `["hover", "active", "disabled"]` |
| **Quality tier** | If `quality_adaptive` enabled | See table below |

**Quality tier assignment** (if `quality_adaptive` enabled):

| Layer Content | Rough (Phase 3) | Refinement (Phase 6) |
|--------------|----------------|---------------------|
| Solid color / simple gradient background | `low` | `medium` |
| Simple geometric shapes | `low` | `high` |
| Text-heavy elements | `medium` | `high` |
| Complex icons / illustrations | `medium` | `high` |
| Photographic / detailed artwork | `medium` | `high` |

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
| `padding` | Inner padding between panel edge and cells. Can be a single number (all sides) or `{top, right, bottom, left}`. Defaults to `0`. When `0`, `area_layout` is the exact cell area (no panel gap). **Can be negative** when cells visually extend beyond the panel edge (e.g., tabs that overflow the tab bar). Negative values are preserved through detection and handled by the Figma plugin via expanded auto-frame sizing. | `24` or `{"top": -8, "right": 24, "bottom": 24, "left": -8}` |
| `gap_x` | Horizontal gap between cells (px) | `20` |
| `gap_y` | Vertical gap between cells (px) | `20` |
| `auto_panel` | Optional panel background config. Only needed when the panel deviates from `area_layout`. | See below |

For `list`:
| Field | Description | Example |
|-------|-------------|---------|
| `direction` | `horizontal` or `vertical` | `horizontal` |
| `count` | Number of items | `5` |
| `area_layout` | **Default panel boundary** `{x, y, width, height}`. Defines the full container area and serves as the panel dimensions by default. When `width/height` are provided, cells are positioned inside this area subject to `padding`, and the panel itself uses these exact dimensions. Only use `auto_panel.layout` if the panel needs to deviate from this boundary. When `width/height` are omitted, falls back to legacy mode where `x/y` is the direct cell start. | `{"x": 100, "y": 300, "width": 500, "height": 80}` |
| `padding` | Inner padding between panel edge and cells. Can be a single number (all sides) or `{top, right, bottom, left}`. Defaults to `0`. When `0`, `area_layout` is the exact cell area (no panel gap). **Can be negative** when cells visually extend beyond the panel edge (e.g., tabs that overflow the tab bar). Negative values are preserved through detection and handled by the Figma plugin via expanded auto-frame sizing. | `16` or `{"top": 16, "right": -4, "bottom": 16, "left": -4}` |
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

**Phase 4 自动位置修正**：

在 Phase 4（Web Composition Check）中，如果 panel 已成功生成 PNG，`detect_layer_positions.py` 会自动对 panel 进行模板匹配以修正容器位置。验证通过后，所有 cell 会自动对齐到检测到的 panel 边界，`area_layout` 和 `padding` 也会同步更新。

因此，Phase 2 中 `area_layout` 只需粗略估算 — Phase 4 会自动修正。只有当 panel 视觉上明显偏离 cell 区域（如阴影外扩、装饰性边框超出 cell 区）时，才需要手动配置 `auto_panel.layout`。

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

## Step 3: Extract Layout

For **each layer**, the agent must visually estimate its bounding box within the overall design canvas:

| Field | Description | Example |
|-------|-------------|---------|
| `x` | Left edge offset from canvas left (px) | `0` |
| `y` | Top edge offset from canvas top (px) | `80` |
| `width` | Estimated pixel width of the element | `240` |
| `height` | Estimated pixel height of the element | `600` |

**Rules**:
- Coordinates are in **full-size canvas pixels** (same as `dimensions` below)
- The layer's bounding box should be the **tightest rectangle** that contains the element
- Partially off-canvas elements are allowed (x or y can be negative)
- The layer image itself will be generated at `early_size`, but the **layout coordinates stay at full size** — scaling is handled by the preview generator
- If a layer spans the full width/height (e.g., full-bleed background), use the canvas dimensions

---

## Step 4: Extract Style Anchor

Extract a concise string summarizing the visual style for prompt consistency:
```
Flat design, primary blue #3B82F6, Inter font, 8px grid, rounded 12px corners, soft shadows
```

This anchor must be included in **all subsequent generation prompts** (Phase 3~8).

---

## Step 5: Visual Opacity Judgment

For each layer, the agent must visually judge whether it should be **semi-transparent** when stacked over other layers. Add an `opacity` field directly to each layer entry in `layer_plan.json`:

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

**Example `layer_plan.json` with opacity**:
```json
{
  "project": "my-dashboard",
  "dimensions": {"width": 1920, "height": 1080},
  "style_anchor": "Flat design, primary blue #3B82F6...",
  "layers": [
    {
      "name": "background",
      "contents": "Solid dark navy fill with subtle gradient texture",
      "opacity": 1.0,
      "layout": {"x": 0, "y": 0, "width": 1920, "height": 1080}
    },
    {
      "name": "sidebar",
      "contents": "Left navigation bar with icons and labels",
      "opacity": 0.9,
      "layout": {"x": 0, "y": 80, "width": 240, "height": 1000}
    }
  ],
  "stacking_order": ["background", "sidebar"]
}
```

The `opacity` field flows through the entire pipeline: Phase 3 generation prompts → Phase 4 preview → Figma import.

---

## Step 6: Produce `layer_plan.json`

Save via `PathManager.get_layer_plan_path()`:

```json
{
  "project": "my-dashboard",
  "dimensions": {"width": 1920, "height": 1080},
  "style_anchor": "Flat design, primary blue #3B82F6...",
  "layers": [
    {
      "name": "background",
      "contents": "Solid dark navy fill with subtle gradient texture",
      "quality_tier": "low",
      "states": [],
      "layout": {"x": 0, "y": 0, "width": 1920, "height": 1080}
    },
    {
      "name": "sidebar",
      "contents": "Left navigation bar with icons and labels",
      "quality_tier": "medium",
      "states": [],
      "layout": {"x": 0, "y": 80, "width": 240, "height": 1000}
    },
    {
      "name": "header",
      "contents": "Top bar with logo, search input, avatar",
      "quality_tier": "medium",
      "states": [],
      "layout": {"x": 240, "y": 0, "width": 1680, "height": 80}
    },
    {
      "name": "buttons",
      "contents": "Primary action buttons in content area",
      "quality_tier": "high",
      "states": ["hover", "active", "disabled"],
      "layout": {"x": 1520, "y": 960, "width": 280, "height": 60}
    }
  ],
  "stacking_order": ["background", "sidebar", "header", "buttons"]
}
```

---

## Step 5: Detect Repeat Patterns & Ask User

After completing the initial layer breakdown (Step 2), inspect the confirmed preview for **repeating patterns** before presenting the plan.

### Detection Criteria

| Confidence | Visual Evidence | Action |
|-----------|-----------------|--------|
| **High** | Elements are **visually identical** (same shape, size, color, style), arranged in grid or list | Auto-suggest `repeat_mode`, explain savings |
| **Medium** | Elements share **common structure** (same container, same size) but content varies (different text, different icons, different photos) | Prompt user: "检测到可能是 grid/list，但内容有差异，是否启用复用模式？" |
| **Low / None** | No repeating pattern, or elements vary significantly in size/shape | Skip, no prompt |

### User Prompt Templates

**High confidence (auto-suggest):**
```
检测到以下重复元素模式，建议启用复用模式以节省生成时间和成本：

🔄 商品卡片 — Grid 3×2（共 6 个）
   每个卡片外观相同，仅内容不同
   启用后：生成 1 次 → 复用 6 次（节省 83%）

🔄 底部标签栏 — List 横向 ×4（共 4 个）
   每个标签按钮外观相同，仅图标/文字不同
   启用后：生成 1 次 → 复用 4 次（节省 75%）

是否启用复用模式？
• 回复 "启用" → 自动应用 repeat_mode
• 回复 "不启用" → 保持逐一生成
• 回复 "部分启用" → 告诉我哪些启用、哪些不启用
```

**Medium confidence (ask user):**
```
检测到以下区域可能是重复元素，但内容有一定差异：

⚠️ 商品卡片区域 — 看起来是 3×2 的网格
   观察到：卡片容器样式相同，但每张卡片的商品图片不同
   
   选项：
   A. 启用复用模式（只生成一个通用卡片容器，内容差异忽略）
   B. 不启用（每个卡片单独生成，保留各自的内容差异）
   C. 混合方案（启用复用 + 额外生成内容差异层）

请告诉我你的选择。
```

### User Response Handling

| User Says | Action |
|-----------|--------|
| "启用" / "yes" / "全部启用" | Apply `repeat_mode` to all detected patterns |
| "不启用" / "no" / "全部不启用" | Skip repeat_mode, keep all as individual layers |
| "只启用 XX" | Apply to specified layers only |
| "XX 启用，YY 不启用" | Apply selectively per layer |
| 无回应或模糊 | Re-prompt with clearer options |

### Applying repeat_mode

Once user confirms:
1. Add `repeat_mode` and `repeat_config` to the confirmed layers
2. Re-count total "effective layers" (parents count as 1 for generation)
3. Present updated plan including repeat savings summary

**Carrier panel detection during visual analysis (MUST):**

When inspecting the preview for repeat patterns, you **must** also check whether the grid/list has a **carrier panel** — a shared container that visually carries all repeating elements. This is **not** the main page background; it is a secondary container specific to the grid/list region.

A carrier panel may include any or all of the following visual elements:

| Panel Component | Visual Evidence | Action |
|----------------|-----------------|--------|
| **Background shape** | Rounded rectangle, card, bar, pill, or other geometric shape behind all cells | `auto_panel: {enabled: true}` |
| **Texture / pattern fill** | Gradient, noise, fabric, glass, marble, or decorative texture on the container shape | `auto_panel: {enabled: true}` |
| **Decorative border / frame** | Outline, ornamental frame, corner accents, gold trim, etched edges | `auto_panel: {enabled: true}` |
| **Shadow / glow effects** | Drop shadow, inner glow, ambient occlusion, bloom around the container perimeter | `auto_panel: {enabled: true}` |
| **No shared container** | Cells float directly on the main background; each cell has its own isolated background with no shared visual wrapper | Omit `auto_panel` or `enabled: false` |
| **Uncertain** | Partial background, ambiguous edges, or mixed evidence | Ask user: "该重复区域的子项是否共享一个容器面板（包含底板、纹理、边框、阴影等）？" |

**Why carrier panel matters:**
- Without extracting the panel as a separate layer, the repeat parent (single cell) would need to include the panel background in every instance → redundant and compositing issues
- With `auto_panel`, the panel is generated **once** as a full-area layer, and the repeat parent (single cell) is generated **once** as a clean element on transparent background → instances are composited on top of the panel cleanly

**Panel 尺寸自动计算：**
- `expand_repeats.py` 自动根据 `cols/rows/gap` 或 `count/direction/gap` 计算覆盖整个 repeat 区域的 bounding box
- Panel 在 `stacking_order` 中自动置于对应实例**下方**
- Panel 作为独立图层生成，有自己的 `id` 目录和 PNG

**Example savings summary:**
```
图层方案更新：
• 总图层数：14（含 2 个复用父图层 + 2 个 panel 背景 + 10 个自动展开实例）
• 实际需生成：6 次（背景 + 卡片底板 + 卡片父图层 + 标签栏底板 + 标签栏父图层 + 标题栏）
• 预计节省 API 调用：10 次实例 → 复用（节省 83%）
```

---

## Step 5b: Precise Layout Mode (PL Mode) — Optional

After the layer breakdown is finalized, ask the user whether any layers should use **Precise Layout Mode (PL mode)**.

### What is PL Mode?

PL mode is an **experimental** feature for layers where pixel-accurate positioning is critical.

| | Normal Mode | PL Mode |
|---|---|---|
| **Phase 3 canvas size** | `compute_layer_size()` — smallest compliant canvas matching aspect ratio | **`early_size` — full canvas** |
| **Phase 3 prompt** | "leave 3-5% transparent margin" | **"natural size on full transparent canvas, no extra margins"** |
| **Phase 4 layout source** | Planned layout × scale_ratio | **Crop bbox or detected layout (more accurate)** |
| **Phase 4 detect** | On-demand (user request only) | **Automatic for PL layers** |
| **Cost** | Lower | **Higher** (full canvas per PL layer) |

### When to Recommend PL Mode

Recommend PL mode for layers where **exact position matters**, such as:
- Small, precisely-placed controls (buttons, input fields, toggles)
- Icons that must align with grid lines or text baselines
- Floating action buttons (FAB) with specific corner placement
- Any layer the user explicitly says "this needs to be pixel-perfect"

### When NOT to Use PL Mode

- **Background layers** — already use full canvas
- **`grid` / `list` repeat_mode layers** — not yet supported (will be added in future update)
- **Large containers / panels** — cost is high and position is usually forgiving
- **Layers with opacity < 0.85** — template matching is unreliable for semitransparent layers

### User Prompt

```
为了提高某些控件的位置精度，我支持「精确布局模式」（PL 模式）：

📍 PL 模式优势：
   • 使用全画布生成，模型有更多空间上下文
   • 自动运行多尺度模板匹配，位置更精确
   • 适合按钮、输入框、图标等位置敏感的控件

📍 PL 模式代价：
   • 每个 PL 图层都按全画布尺寸生成（成本更高、更慢）
   • 暂不支持 grid/list 复用模式

当前图层：
• submit_btn — 建议启用 PL（位置敏感的小按钮）
• search_input — 建议启用 PL（输入框需要对齐）
• sidebar — 不建议（大容器，位置宽容度高）
• header — 不建议（通栏，位置天然对齐）

是否需要启用 PL 模式？
• 回复 "全部启用" / "all" → 所有推荐图层启用 PL
• 回复 "不启用" / "none" → 全部保持普通模式
• 回复图层名列表 → 只启用指定的图层（如 "submit_btn, search_input"）
```

### Applying PL Mode

Once the user confirms which layers should use PL mode:
1. Add `"precise_layout": true` to each selected layer in `layer_plan.json`
2. Document the choice in the plan presentation below

**Example `layer_plan.json` with PL mode:**
```json
{
  "project": "my-dashboard",
  "layers": [
    {
      "id": "submit_btn",
      "name": "Submit Button",
      "precise_layout": true,
      "layout": {"x": 860, "y": 520, "width": 200, "height": 56}
    },
    {
      "id": "sidebar",
      "name": "Sidebar",
      "layout": {"x": 0, "y": 80, "width": 240, "height": 1000}
    }
  ]
}
```

---

## Step 6: Present Plan to User

Show the final layer breakdown list:
- Total layer count (including repeat instances)
- Effective generation count (parents only)
- Quality tier assignments (if adaptive)
- Style anchor summary
- Repeat mode summary (if any)
- **PL mode summary** (which layers are in PL mode, if any)

**Require explicit "OK"** to proceed to Phase 3.

**User can**:
- Approve and proceed to Phase 3
- Request layer adjustments (merge, split, reorder, add, remove)
- Request return to Phase 1 to redesign the preview
- Toggle repeat_mode on/off for specific layers
- Toggle PL mode on/off for specific layers

---

**Exit Condition**: User replies "OK".

**Output upon exit**:
- `layer_plan.json` (with `repeat_mode` applied if user confirmed)
- `style_anchor` string
- Confirmed preview reference path

**Output upon exit**:
- `layer_plan.json`
- `style_anchor` string
- Confirmed preview reference path
