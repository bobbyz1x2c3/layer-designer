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

## Step 5: Present Plan to User

Show the layer breakdown list, total layer count, quality tier assignments (if adaptive), style anchor summary, and ask for confirmation.

**Require explicit "OK"** to proceed to Phase 3.

**User can**:
- Approve and proceed to Phase 3
- Request layer adjustments (merge, split, reorder, add, remove)
- Request return to Phase 1 to redesign the preview

---

**Exit Condition**: User replies "OK".

**Output upon exit**:
- `layer_plan.json`
- `style_anchor` string
- Confirmed preview reference path
