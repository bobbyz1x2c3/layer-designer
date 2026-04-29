# Phase 2: Confirmation (Standard Mode Only)

**Goal**: Analyze the confirmed preview visually and produce a formal layer breakdown plan.

**When to read this file**: Agent MUST read this file when entering Phase 2 of the workflow (Standard mode only). If Fast Track mode was selected, Phase 2 was already completed inside Phase 1 Step 9 — skip directly to Phase 3.

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

**`repeat_config` fields:**

For `grid`:
| Field | Description | Example |
|-------|-------------|---------|
| `cols` | Number of columns | `3` |
| `rows` | Number of rows | `2` |
| `area_layout` | Position of the first cell `{x, y}` (optional) | `{"x": 200, "y": 150}` |
| `gap_x` | Horizontal gap between cells (px) | `20` |
| `gap_y` | Vertical gap between cells (px) | `20` |
| `auto_panel` | Optional panel background config | See below |

For `list`:
| Field | Description | Example |
|-------|-------------|---------|
| `direction` | `horizontal` or `vertical` | `horizontal` |
| `count` | Number of items | `5` |
| `area_layout` | Position of the first item `{x, y}` (optional) | `{"x": 100, "y": 300}` |
| `gap` | Gap between items (px) | `16` |
| `auto_panel` | Optional panel background config | See below |

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

Panel 层会自动计算覆盖整个 repeat 区域的 bounding box，并在 stacking_order 中**置于实例下方**。

**Example `layer_plan.json` with repeat_mode + auto_panel:**
```json
{
  "name": "商品卡片",
  "id": "product_card",
  "description": "Product card with image, title, price",
  "layout": {"x": 0, "y": 0, "width": 280, "height": 360},
  "quality_tier": "medium",
  "opacity": 1.0,
  "repeat_mode": "grid",
  "repeat_config": {
    "cols": 3,
    "rows": 2,
    "area_layout": {"x": 200, "y": 150},
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

**Panel background detection during visual analysis:**

When inspecting the preview for repeat patterns, also check whether the grid/list has a **container background / panel**:

| Panel Type | Visual Evidence | `auto_panel` Action |
|-----------|-----------------|---------------------|
| **Has panel** | Visible background shape behind all cells (rounded rectangle, card, bar) | Include `auto_panel: {enabled: true, ...}` in `repeat_config` |
| **No panel** | Cells float directly on the main background, no visible container | Omit `auto_panel` or set `enabled: false` |
| **Uncertain** | Partial background or ambiguous edges | Ask user: "该区域是否有容器背景？" |

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

## Step 6: Present Plan to User

Show the final layer breakdown list:
- Total layer count (including repeat instances)
- Effective generation count (parents only)
- Quality tier assignments (if adaptive)
- Style anchor summary
- Repeat mode summary (if any)

**Require explicit "OK"** to proceed to Phase 3.

**User can**:
- Approve and proceed to Phase 3
- Request layer adjustments (merge, split, reorder, add, remove)
- Request return to Phase 1 to redesign the preview
- Toggle repeat_mode on/off for specific layers

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
