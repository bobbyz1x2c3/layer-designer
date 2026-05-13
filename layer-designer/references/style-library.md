# Style Library — Consumption Guide

**Goal**: Reuse a single visual / interaction spec (palette, typography,
spacing, rules, reference images) across multiple Layer Designer projects.

**When to read**: When you want to apply a saved style to a workflow, OR
when you need to understand how `--style` changes prompt assembly in
Phases 1, 3, 5, 6, and 8.

> **See also**: `style-generation.md` — how to **create / extend** a
> style entry (use that doc when you're producing a style; this doc is
> for consuming an existing one).

---

## 1. What a Style Is

A **style** is a directory under `layer-designer/styles/{name}/` containing:

```
layer-designer/styles/saas-blue/
├── style.json                # required: tokens + rules + image_refs
├── button.png                # optional: reference image
├── sidebar.png               # optional: reference image
└── card.png                  # optional: reference image
```

`style.json` declares:

- **Tokens**: palette, typography, spacing, shape, elevation, motif
- **Rules**: free-text guidelines grouped by category (interaction / layout / typography / …)
- **`image_refs[]`**: 0~N reference images, each tagged with the control
  types it applies to via `use_for`

Styles are **fully optional**. Workflows that omit `--style` behave
exactly as before — no `style_ref` field appears anywhere in outputs and
no per-layer `control_type` is required.

---

## 2. style.json Schema v1.0

```json
{
  "schema_version": "1.0",
  "name": "saas-blue",
  "description": "Internal SaaS dashboard, professional blue theme",
  "derived_from": "output/.../01-requirements/previews/preview_v1_001.png",

  "image_refs": [
    {
      "path": "button.png",
      "role": "Button standard, applied to all button controls",
      "use_for": ["button"]
    },
    {
      "path": "sidebar.png",
      "role": "Sidebar standard",
      "use_for": ["sidebar", "navigation"]
    },
    {
      "path": "card.png",
      "role": "Card container standard",
      "use_for": ["card", "panel"]
    }
  ],

  "palette": {
    "role":     { "primary": "#3B82F6", "surface": "#FFFFFF", "text_primary": "#111827", ... },
    "semantic": { "info": "#0EA5E9", "success": "#10B981", "warning": "#F59E0B", "danger": "#EF4444" }
  },

  "typography": { "font_family": "Inter", "font_size_base": 14, ... },
  "spacing":    { "base": 8, "scale": [4, 8, 12, 16, 24, 32, 48, 64] },
  "shape":      { "corner_radius_md": 8, "button_radius": 4, "border_width": 1 },
  "elevation":  { "preset": "soft", "shadow_md": "0 4px 6px rgba(0,0,0,0.08)" },
  "motif":      { "tags": ["flat", "minimalist", "saas-dashboard"] },

  "rules": {
    "interaction": [
      "Clickable buttons use 4px corner radius (shape.button_radius)",
      "Hover state lifts shadow one tier (sm → md, md → lg)"
    ],
    "layout":      ["All elements align to the 8px grid (spacing.base)"],
    "typography":  ["Headings use Inter Bold, font-size ≥24px"]
  },

  "style_anchor_override": null
}
```

### Field Rules

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Pinned at `"1.0"`. Loaders warn on `1.x` mismatches, hard-fail on `2.x`. |
| `name` | yes | Must match the folder name. |
| `image_refs[].path` | yes (per entry) | Relative to `style.json` directory. |
| `image_refs[].role` | yes (per entry) | Used verbatim in prompt headers. |
| `image_refs[].use_for` | yes, ≥1 entry | Array of control-type strings (e.g. `["button"]` or `["card", "panel"]`). |
| `palette.role` / `palette.semantic` | optional | Either or both, fill what you need. |
| `motif.tags` | optional | Free strings; first few are pulled into the derived anchor. |
| `rules.*` | optional | Category names are open — `interaction`, `layout`, `typography`, and any custom keys. |
| `style_anchor_override` | optional | When non-null, **replaces** the derived anchor entirely. Use only if you need to lock specific wording. |

### Derived Anchor (Deterministic)

When `style_anchor_override` is null, `style_loader.derive_anchor()`
assembles a free-text anchor in this order:

1. `motif.tags` joined by commas
2. `palette.role.primary` (or `palette.semantic.brand` fallback) → `"primary {hex}"`
3. `typography.font_family` → `"{font} font"`
4. `spacing.base` → `"{n}px grid"`
5. `shape.button_radius` (or `shape.corner_radius_md`) → `"rounded {n}px buttons"` / `"rounded {n}px corners"`
6. `elevation.preset` → `"{preset} shadows"`

The format mirrors what Phase 2 produces from a preview, so you can mix
library-driven anchors with project-extracted ones.

---

## 3. Selecting a Style at the CLI

Two mutually exclusive flags, supported by every generation entry point
(`generate_image.py`, `generate_variants.py`, `separate_mode.py`,
`batch_generate_pl_test.py`):

```bash
# Lookup by name under layer-designer/styles/
--style saas-blue

# Explicit path (use for ad-hoc styles outside the workspace)
--style-from /path/to/external/style-dir
```

**Resolution order** (each tool follows the same rule):

1. CLI flag wins (`--style` or `--style-from`)
2. Otherwise `layer_plan.style_ref` is consulted (set by Phase 2 when
   `--style` was active there)
3. If neither is set, no style is applied — workflow behaves as before

If a referenced style is missing, the tool warns and continues without
style (preserving back-compat). If the CLI flag points at a missing
style, the tool **errors out** — that path was explicit user intent.

---

## 4. Three-Phase Prompt Assembly

`style_loader.build_prompt(style, user_prompt, phase, control_type,
base_image)` is the single composer used by every entry point. It
returns `(final_prompt_str, image_paths_list)`. The behavior changes by
`phase`:

### 4a. `phase="preview"` — Phases 1 / 5

Used when generating a full composition.

- **If `image_refs` non-empty**: route auto-switches to
  `generate_image.py edit` and **all** reference images are passed.
  Each is labeled with its first `use_for` value in the prompt header:

  ```
  Image1 [button]: Button standard, applied to all button controls
  Image2 [sidebar]: Sidebar standard
  Image3 [card]: Card container standard

  instruction: Generate a UI design composition. Each labeled reference
  image above defines the visual standard for its tagged control type.
  Apply Image1 to every [button] in the output, Image2 to the [sidebar],
  Image3 to every [card]. Components outside these tagged types should
  follow the textual style and rules below.

  Design rules:
  - Clickable buttons use 4px corner radius
  - Hover state lifts shadow one tier
  - All elements align to the 8px grid

  Style: flat, minimalist, saas-dashboard, primary #3B82F6, Inter font,
  8px grid, rounded 4px buttons, soft shadows.

  User request: <original prompt>
  ```

- **If `image_refs` empty**: stays on `generate_image.py generate`. No
  `[type]` labels — just the rules + anchor prefix:

  ```
  Design rules:
  - ...

  Style: ...

  User request: <original prompt>
  ```

### 4b. `phase="layer"` — Phases 3 / 6

Used when extracting a single layer from a preview.

- Reads the layer's `control_type` from `layer_plan.json`.
- Selects `image_refs` entries whose `use_for` contains that
  `control_type` (zero, one, or many).
- Final image list: `[base_image, *matching_refs]`. Base image (the
  preview) is `Image1` and **does not** carry a `[type]` tag; refs are
  labeled `[control_type]`:

  ```
  Image1: Current preview (extract the target control from this)
  Image2 [button]: Button standard

  instruction: Extract ONLY the submit_button from Image1. This is a
  [button] — its style must strictly match Image2. Transparent
  background. Keep exact position relative to Image1.

  Design rules: ...
  Style: ...
  User request: <original prompt>
  ```

- **If `control_type` is null or no refs match**: only `base_image` is
  passed; the prompt has no `[type]` labels but still includes rules +
  anchor.

### 4c. `phase="variant"` — Phase 8

Used when generating hover/active/disabled state variants from a
finished layer PNG.

- Base image is the **layer itself** (not a preview). It DOES carry a
  `[control_type]` tag because it is an instance of that type.
- Refs matching `control_type` are appended.
- Rules are filtered to the `interaction` category only (state changes
  are interaction-driven; layout / typography rules are noise here):

  ```
  Image1 [button]: Current submit_button (normal state)
  Image2 [button]: Style reference (control_type = button)

  instruction: Generate the hover state of this [button] (Image1). Match
  overall style to Image2. Maintain exact dimensions, palette,
  typography, base shape. Apply hover transformations only.

  Design rules (interaction):
  - Hover state lifts shadow one tier
  - Active/pressed state drops brightness one tier
  - Disabled state uses 50% opacity

  Style: ...
  User request: Generate hover variant.
  ```

### 4d. Image-Count Hard Cap

`generate_image.py edit` accepts at most 5 images. When base + matching
refs exceed that, refs are truncated in `image_refs` declaration order
(base image is always kept). For preview phase with many refs, this
means refs are taken in order until the cap is hit.

---

## 5. `control_type` Tagging in Phase 2

When Phase 2 runs **with** `--style`, the LLM is required to label every
layer with one of:

- A control-type string drawn from the union of all
  `style.image_refs[*].use_for` values
- `null` — for layers that don't correspond to any control category

The valid enum is computed by `style_loader.list_control_types(style)`.
For `saas-blue` above that's `["button", "sidebar", "navigation",
"card", "panel"]`.

Phase 2 output (`02-confirmation/layer_plan.json`) gains two new fields:

```json
{
  "style_anchor": "flat, minimalist, primary #3B82F6, Inter font, 8px grid, rounded 4px buttons",
  "style_ref": {
    "name": "saas-blue",
    "dir": "styles/saas-blue",
    "schema_version": "1.0"
  },
  "layers": [
    {
      "name": "submit_button",
      "control_type": "button",
      "layout": { ... }
    },
    {
      "name": "main_chart",
      "control_type": null,
      "layout": { ... }
    }
  ]
}
```

Without `--style`, neither `style_ref` nor `control_type` appears.
Downstream scripts treat their absence as "no style in play."

---

## 6. Propagation Through the Pipeline

`style_ref` (top-level) and `control_type` (per layer) flow forward
unchanged through every plan-transforming step:

| Script | Phase | Behavior |
|---|---|---|
| `expand_repeats.py` | 4 | Top-level `style_ref` preserved. Repeat-instance children inherit the parent's `control_type`. |
| `detect_layer_positions.py` | 4 | Same — passes both through into `enhanced_layer_plan.json`. |
| `generate_preview.py` | 4 / 7 | Top-level `style_ref` and per-layer `control_type` written into the Figma-import plan. |
| Figma plugin | — | Reads the fields but treats them as metadata (no visual effect in v1). |

The fields are **additive**: code that doesn't know about them keeps
working.

---

## 7. Compatibility Matrix

| Scenario | Behavior |
|---|---|
| No `--style` flag, no `style_ref` in plan | 100% identical to pre-style behavior. |
| `--style saas-blue`, image_refs non-empty | Preview routes to `edit`; layer/variant filter refs by `control_type`. |
| `--style saas-blue`, image_refs empty | Rules + anchor injected, no image refs, no `[type]` tags. |
| `--style missing-name` | Hard error, lists available styles. |
| `--style-from /bad/path` | Hard error if `style.json` missing. |
| No CLI flag, `style_ref.name` in plan is unresolvable | Warn, continue without style. |
| Layer has `control_type` not covered by any `use_for` | Layer/variant phase passes only the base image (no refs); prompt still includes rules + anchor. |
| Layer has `control_type: null` | Same as the above. |
| Phase 2 didn't tag `control_type` despite `--style` active | All layers treated as `null` — refs never selected for those layers. |
| Total image count > 5 (edit hard cap) | Refs truncated in `image_refs` order; base image always kept. |
| `style.json` `schema_version: "1.5"` | Loader warns and continues. |
| `style.json` `schema_version: "2.0"` | Loader hard-fails. |
| Image ref path missing on disk | `style_loader.validate()` fails before any generation runs. |

---

## 8. Common Recipes

### Apply a style to a fresh project

```bash
# Phase 1: generate preview WITH style
python scripts/generate_image.py generate \
  --config config.json --style saas-blue \
  --prompt "Dashboard with sidebar, top nav, 4-card metric grid" \
  --output output/my-app/01-requirements/previews/preview_v1_001.png \
  --size 1920x1088 --quality low --phase preview
# (auto-routes to `edit` because saas-blue has image_refs)

# Phase 2: LLM tags control_type per layer; saves layer_plan.json with
# style_ref + control_type fields.

# Phase 3: each layer is extracted with style context
python scripts/generate_image.py edit \
  --config config.json --style saas-blue --phase layer \
  --image preview_v1_001.png \
  --prompt "Extract ONLY submit_button. Transparent background." \
  --control-type button \
  --output ... --size 256x64 --quality low
```

### Reuse an old preview as a style without re-running Phase 2

```bash
# Use --style-from to point directly at an unsaved style dir
python scripts/generate_image.py generate \
  --config config.json \
  --style-from /tmp/my-adhoc-style \
  --prompt "..." --output ... --phase preview
```

### Run a workflow without a style on a project that has one

```bash
# Explicit no-style via missing flag — the plan's style_ref is honored
# by default, but you can override per-call. To suppress entirely,
# remove or rename style_ref in layer_plan.json before running.
python scripts/generate_image.py edit --config config.json \
  --image ... --prompt "..." --output ...
# (no --style → no style; falls back to style_ref if present)
```

> ⚠️ Currently there is no `--no-style` flag. If you want to bypass the
> plan's `style_ref` for one run without editing the plan, prefer
> `--style-from` pointing at an empty style directory (just a stub
> `style.json` with no image_refs and no rules).

---

## 9. Tooling Reference

- **Loader / composer**: `scripts/style_loader.py`
  - `load_style(dir)`, `validate(style, dir)`, `derive_anchor(style)`,
    `rules_to_prompt_text(style, kinds=None)`,
    `list_control_types(style)`, `select_image_refs(style, control_type)`,
    `build_prompt(...)`, `resolve(name_or_path)`
- **Path helpers**: `PathManager.get_styles_dir()`,
  `PathManager.get_style_dir(name)`,
  `PathManager.resolve_style(name_or_path)`
- **Style creation**: `scripts/export_style.py` (see
  `style-generation.md`)

---

## 10. Out of Scope (for v1)

- W3C DTCG export (planned for v1.x)
- Style merging (`--style a,b`) or extension (`extends`)
- Programmatic validation of `rules` (rules stay free-text)
- Auto-inferring `control_type` from a free-form user prompt
- Figma plugin actively consuming `style_ref` / `image_refs` /
  `control_type` (fields are stored but not yet rendered)
