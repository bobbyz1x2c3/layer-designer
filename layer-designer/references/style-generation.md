# Style Library — Generation Guide

**Goal**: Create a new style entry in `layer-designer/styles/{name}/`,
or extend an existing one with additional reference images.

**When to read**: When you're producing a style for the first time, or
adding to an existing one. For **consuming** a style in workflows, see
`style-library.md`.

---

## 1. Skill Entry — LLM-Driven Authoring from Reference Images

> **You (the agent) are the vision-extractor.** `scripts/export_style.py`
> does NOT call any vision LLM. The visual analysis must happen here in
> this turn, by you, before you invoke the persistence command.

This is the **recommended primary path** for "make me a style that
looks like these images" requests. Use it whenever:

- The user pastes/attaches one or more reference images.
- The user describes a look ("retro arcade, neon on black") and may or
  may not have images yet.
- The user wants to iterate on the spec interactively before it's
  written to disk.

### Workflow (8 steps)

**Step 1 — Understand the brief.**
Ask the user (if not already clear):
- Which control types should each reference image bind to?
  (Examples: button, sidebar, card, navigation, panel, tile,
  character, environment.)
- Are there interaction rules you want explicit? (Hover, disabled,
  pressed, etc.)
- Is this a UI/UX style or a game-asset style? The `motif.tags` and
  `rules.*` categories will differ.
- A short style `name` (folder slug) and one-line `description`.

If the user gave images without explicit control-type assignments,
**propose** an assignment after Step 2 and confirm before persisting.

**Step 2 — Visually extract tokens from the reference images.**
Look at each image and pull out:

| Token | What to look for |
|---|---|
| `palette.role.primary` | Most-used non-neutral hex. Read it off the canvas. |
| `palette.role.surface` / `background` | Card/panel fill, page fill. |
| `palette.role.text_primary` / `text_secondary` | Heading/body text colors. |
| `palette.role.border` | Hairline / divider color. |
| `palette.semantic.*` | Any explicit info/success/warning/danger swatches. |
| `typography.font_family` | If discernible, name the font (else use a category like `"sans-serif"`). |
| `spacing.base` | Grid spacing — usually 4 or 8. Infer from padding rhythm. |
| `shape.button_radius` / `corner_radius_*` | Measure off button / card corners. |
| `elevation.preset` | `"soft"`, `"sharp"`, `"none"`, or `"layered"` — describe the shadow vibe. |
| `motif.tags` | 2–4 short tags (`["flat", "minimalist"]`, `["retro", "neon", "arcade"]`, `["material", "elevated"]`). |

Use approximate hex values when exact ones aren't readable — the
designer can refine later.

**Step 3 — Draft `image_refs` and `rules`.**

For each reference image the user provided:

```json
{
  "path": "button.png",            // dest filename (you'll set --copy-references)
  "role": "Button standard ...",    // one short sentence; appears in prompt header
  "use_for": ["button"]              // control types this ref applies to (≥1)
}
```

For `rules`, generate explicit free-text sentences (NOT structured
fields) the downstream prompts will inject literally:

- `rules.interaction` — hover/active/disabled state transformations.
  **Required if the user expects Phase 8 variants to look polished.**
  Examples: `"Hover state lifts shadow one tier (sm → md, md → lg)"`,
  `"Disabled state uses 50% opacity"`.
- `rules.layout` — grid alignment, padding, touch-target minima.
  Examples: `"All elements align to the 8px grid"`,
  `"Tap targets ≥ 44×44px"`.
- `rules.typography` — heading vs body, weight, min contrast.

Skip a category if you have nothing meaningful to say — empty rule
arrays are fine.

**Step 4 — Mental `derive_anchor()` check.**
The deterministic anchor recipe is:

```
{motif.tags joined with ", "}, primary {palette.role.primary},
{typography.font_family} font, {spacing.base}px grid,
rounded {shape.button_radius}px buttons, {elevation.preset} shadows
```

Read your draft tokens back and confirm the resulting anchor string
matches the intended vibe. If it doesn't, adjust the tokens (or set
`style_anchor_override` to a hand-written string — but that defeats
the purpose).

**Step 5 — Present the draft to the user.**
Show the full `style.json` as a fenced block, plus:

- The derived anchor string.
- Which reference image will copy to which `dest_filename` (full
  `--copy-references` specs).
- A short summary: "{N} reference image(s), tokens for {palette tier},
  {rules count} rules."

Then ask:
- "Anything to change in palette/typography/shape/rules?"
- "Do the control_type assignments look right?"
- "Approve and write?"

**Step 6 — Revision loop.**
Apply the user's edits to the draft in-memory. Re-show the diff or
the updated section. Keep iterating until the user says "looks good"
or equivalent.

**Step 7 — Generate the specification sheet (mandatory).**
Before persisting, the style MUST produce a unified UI specification
sheet image. This single image becomes the canonical reference for
ALL control types, replacing the original raw reference images.

When invoking `from-llm-draft`, pass `--generate-spec` (and
`--config config.json` so the generation can reach the image API).
The script will:

1. Build a dedicated prompt from `derive_anchor()` + `rules` that asks
   the model to produce a clean design reference card (palette swatches,
   typography sample, base control shapes, spacing grid, motif).
2. Call `generate_image.py`:
   - **With original refs** → uses `edit` mode, passing the copied
     reference images as multi-image inputs.
   - **Without original refs** → uses `generate` mode (text-to-image).
3. Save the result as `spec.png` inside the style folder.
4. Replace `image_refs` with a single entry:
   `{"path": "spec.png", "role": "UI design specification reference sheet", "use_for": ["*"]}`.
5. Remove the original reference images to keep the style folder clean
   (unless `--keep-original-refs` is passed).

The spec sheet is a **hard requirement** for reusable styles because
it gives downstream phases one unified visual standard instead of
fragmented raw refs.

**Step 8 — Persist via `from-llm-draft`.**
Once approved, write to disk in a single command:

```bash
python scripts/export_style.py from-llm-draft \
  --name {style_name} \
  --json-stdin \
  --generate-spec \
  --config config.json \
  --copy-references "{user_image_1_abs_path}:button.png" \
  --copy-references "{user_image_2_abs_path}:sidebar.png"
```

Pipe the final JSON into stdin. The script will:

1. Create `<workspace>/styles/{name}/`.
2. Copy each `--copy-references` source into the style folder under
   the given destination filename.
3. Generate the spec sheet (Step 7) and replace `image_refs`.
4. Verify every `image_refs[*].path` in the draft refers to a file
   now present in the folder (fails fast otherwise).
5. Write `style.json`.
6. Re-load via `style_loader.load_style()` and run
   `style_loader.validate()`. Any failure leaves the file on disk for
   inspection and exits non-zero.

If you don't have shell pipes available, use `--json-file <path>`
instead and write the draft to a temp file first.

### Minimum viable style

Even a "text-only" style with no reference images is valid — just omit
`--copy-references` and leave `image_refs: []` in the draft. The
composer will inject rules + derived anchor without any reference
images.

If you pass `--generate-spec` on a text-only style, the spec is
produced via `generate` mode (text-to-image) since there are no
original refs to use as edit inputs. The resulting `spec.png` still
becomes the single `image_refs` entry with `use_for: ["*"]`.

### Re-running on an existing style

`from-llm-draft` refuses to clobber an existing style by default. If
the user is iterating on a style that's already been written, either:

- Add `--overwrite` to replace `style.json` (existing reference images
  are left in place; new `--copy-references` will overwrite by
  filename).
- Switch to `add-reference` if you only need to attach one more image.

---

## 2. Four Ways to Author a Style

| Command | Use When |
|---|---|
| `export_style.py from-llm-draft` | **(Recommended)** You (the agent) have visually extracted tokens from user-provided references and want to persist the full draft + copy images in one shot. |
| `export_style.py from-project` | You've just finished a project whose look you want to reuse. Captures the Phase 2 `style_anchor` and copies user-picked reference images. Structured tokens stay empty — fill them by hand or re-process with `from-llm-draft`. |
| `export_style.py manual` | You're starting from a hand-written spec and don't want any LLM extraction. Produces an empty scaffold for direct editing. |
| `export_style.py add-reference` | A style already exists and you want to append another reference image. |

All commands write into the workspace style library at
`<workspace>/layer-designer/styles/{name}/` (located via
`PathManager.get_styles_dir()`).

---

## 3. `from-llm-draft` — Persist an LLM-Drafted Style

Reference for the command invoked at the end of Section 1.

### Synopsis

```bash
python scripts/export_style.py from-llm-draft \
  --name <style-name> \
  (--json-stdin | --json-file <path>) \
  [--copy-references "<source>:<dest-filename>" ...] \
  [--generate-spec] \
  [--config <config.json>] \
  [--keep-original-refs] \
  [--spec-size <WxH>] \
  [--spec-quality {low,medium,high}] \
  [--overwrite]
```

`--json-stdin` and `--json-file` are mutually exclusive — exactly one
must be supplied.

### What It Does

1. Reads the draft `style.json` from stdin or a file.
2. Overrides `style["name"]` with `--name` (authoritative source for
   the folder slug).
3. Defaults `schema_version` to `"1.0"` if the draft omits it.
4. Creates `<workspace>/styles/{name}/` (refusing to clobber unless
   `--overwrite` is passed).
5. For each `--copy-references` spec, copies the source file into the
   style folder under the given destination filename.
6. **If `--generate-spec` is passed:** builds a spec-sheet prompt from
   the style's anchor + rules, calls `generate_image.py` (edit when refs
   exist, generate otherwise), writes `spec.png`, and replaces
   `image_refs` with a single `{"path": "spec.png", "use_for": ["*"]}`
   entry. Original refs are deleted unless `--keep-original-refs`.
7. Pre-checks: every `image_refs[*].path` must exist inside the style
   folder (either pre-existing, just copied, or the generated spec).
   Fails with `[ERROR]` listing the missing entries.
8. Writes `style.json`.
9. Re-loads via `style_loader.load_style()` and runs
   `style_loader.validate()`. On failure, leaves the file on disk for
   inspection and exits non-zero.
10. On success, prints the derived anchor, the control-type coverage,
    and a summary.

### `--copy-references` Spec Format

```
source_path:dest_filename
```

Parsed right-to-left with `rsplit(":", 1)` so the source path may
contain `:` (Windows drive letters work). `dest_filename` must not
contain `:`.

- `source_path` — absolute or relative path to the source image.
- `dest_filename` — file name (no path) inside the style folder.
  Should match the `image_refs[*].path` value in the draft.

Role and `use_for` are not part of this spec because the LLM has
already written them inside the draft's `image_refs[]` block.

### Example: piping a draft

```bash
cat <<'EOF' | python scripts/export_style.py from-llm-draft \
  --name saas-blue \
  --json-stdin \
  --copy-references "/path/to/button_ref.png:button.png" \
  --copy-references "/path/to/sidebar_ref.png:sidebar.png" \
  --copy-references "/path/to/card_ref.png:card.png"
{
  "schema_version": "1.0",
  "name": "PLACEHOLDER",
  "description": "Internal SaaS dashboard, professional blue theme",
  "image_refs": [
    {"path": "button.png",  "role": "Button standard",   "use_for": ["button"]},
    {"path": "sidebar.png", "role": "Sidebar standard",  "use_for": ["sidebar", "navigation"]},
    {"path": "card.png",    "role": "Card container",    "use_for": ["card", "panel"]}
  ],
  "palette": {
    "role": {"primary": "#3B82F6", "surface": "#FFFFFF"},
    "semantic": {"info": "#0EA5E9"}
  },
  "typography": {"font_family": "Inter"},
  "spacing": {"base": 8},
  "shape": {"button_radius": 4, "corner_radius_md": 8},
  "elevation": {"preset": "soft"},
  "motif": {"tags": ["flat", "minimalist", "saas-dashboard"]},
  "rules": {
    "interaction": ["Hover lifts shadow one tier", "Disabled = 50% opacity"],
    "layout": ["Align to 8px grid"]
  },
  "style_anchor_override": null
}
EOF
```

### Example: file-based draft

```bash
# write draft to a temp file first
python scripts/export_style.py from-llm-draft \
  --name retro-arcade \
  --json-file /tmp/retro_draft.json \
  --copy-references "/path/to/neon_frame.png:neon-frame.png"
```

### Failure Modes

| Condition | Exit | Message |
|---|---|---|
| Empty stdin or missing `--json-file` | non-zero | `[ERROR] Empty draft JSON ...` |
| Invalid JSON | non-zero | `[ERROR] Invalid JSON in ...` |
| Top-level JSON is not an object | non-zero | `[ERROR] Top-level JSON must be an object ...` |
| Style already exists, no `--overwrite` | non-zero | `[ERROR] Style '<name>' already exists ...` |
| `--copy-references` source path missing | non-zero | `[ERROR] Source not found: ...` |
| `image_refs[*].path` references file not in style folder | non-zero | `[ERROR] style.image_refs references images not present ...` |
| Post-write `style_loader.validate()` fails | non-zero | `[ERROR] Written style.json failed validation:` + per-error list |

In every failure path after `_ensure_style_dir` runs, the (possibly
empty) style folder is left on disk. Either clean it up manually or
re-run with `--overwrite`.

---

## 4. `from-project` — Inherit from a Completed Project

Use after Phase 2 (or later) has produced a `layer_plan.json` whose
`style_anchor` you want to bottle up. Unlike `from-llm-draft`, this
command does **no** visual extraction — it captures the Phase 2
anchor string verbatim and leaves the structured token fields empty.

### Synopsis

```bash
python scripts/export_style.py from-project \
  --config config.json --project <existing-project> \
  --name <style-name> \
  --description "<short purpose>" \
  [--copy-references "<source>:<role>:<use_for>:<dest-filename>" ...] \
  [--overwrite]
```

### What It Does

1. Reads `output/{project}/02-confirmation/layer_plan.json`.
2. Captures `style_anchor` into `style.style_anchor_override` so the
   library reuses the exact wording Phase 2 produced.
3. Locates a representative preview (the most recent
   `01-requirements/previews/preview_*.png`) and records it as
   `style.derived_from` for provenance.
4. For each `--copy-references` spec, copies the source image into the
   style directory and appends an entry to `style.image_refs`.
5. Writes `style.json` with empty `palette` / `typography` / `rules`
   sections — fill those in by hand afterward, or re-process via
   `from-llm-draft` if you want full token extraction.

### `--copy-references` Spec Format (4 fields)

```
source_path:role:use_for_first:dest_filename
```

Parsed right-to-left with `rsplit(":", 3)` so the source path may
contain `:`. The other three fields must not. If `role` contains
spaces, quote the whole spec.

- `source_path` — absolute or relative path to the source image.
- `role` — natural-language description; appears verbatim in the
  prompt header (`Image{N} [type]: <role>`).
- `use_for_first` — **single** control type assigned to this ref
  initially. Edit `image_refs[*].use_for` in `style.json` afterward to
  add more.
- `dest_filename` — file name (no path) inside the style folder.

> **Note**: `from-project` uses a 4-field spec because role/use_for
> come from the command line; `from-llm-draft` uses a 2-field spec
> because the LLM already wrote them inside the draft.

### Example

```bash
python scripts/export_style.py from-project \
  --config config.json --project saas-dashboard \
  --name saas-blue \
  --description "Internal SaaS dashboard, professional blue theme" \
  --copy-references "output/saas-dashboard/06-refinement-layers/submit_button/submit_button_xxx.png:Button standard:button:button.png" \
  --copy-references "output/saas-dashboard/06-refinement-layers/left_sidebar/left_sidebar_xxx.png:Sidebar standard:sidebar:sidebar.png" \
  --copy-references "output/saas-dashboard/06-refinement-layers/metric_card_1/metric_card_xxx.png:Card container:card:card.png"
```

### Next Steps After `from-project`

1. **Expand `use_for` arrays**: a card ref probably applies to both
   `card` and `panel`; a sidebar ref to `sidebar` and `navigation`.
   Hand-edit `image_refs[*].use_for` to add the extras.
2. **Fill structured tokens**: open the preview image, pick the
   primary/secondary/background hex values, and populate
   `palette.role`. Same for `typography.font_family`, `spacing.base`,
   `shape.button_radius`, etc.
3. **Write the rules**: convert the implicit conventions of the
   reference design into explicit free-text rules under `rules.*`.
4. **Decide on `style_anchor_override`**: keep it if the captured
   Phase 2 string is exactly what you want; set it to `null` to let
   `derive_anchor()` rebuild from the structured tokens (once you've
   filled `motif.tags`, `palette.role.primary`, etc.).

### `--overwrite` Semantics

Refuses to clobber an existing style by default. With `--overwrite`,
`style.json` is replaced in place, but **unrelated files in the
folder are left alone** — including previously copied reference
images. Clean them up manually if needed.

---

## 5. `manual` — Empty Template

Use when there is no source project and you'll write everything by
hand without any LLM assistance.

### Synopsis

```bash
python scripts/export_style.py manual \
  --name <style-name> \
  --description "<short purpose>" \
  [--overwrite]
```

Produces only `style.json` with the empty schema scaffold:

```json
{
  "schema_version": "1.0",
  "name": "<style-name>",
  "description": "<short purpose>",
  "image_refs": [],
  "palette": { "role": {}, "semantic": {} },
  "typography": {},
  "spacing": {},
  "shape": {},
  "elevation": {},
  "motif": { "tags": [] },
  "rules": {},
  "style_anchor_override": null
}
```

Then either hand-edit the file directly or call `add-reference` once
per image you want to attach.

> For most LLM-assisted workflows, prefer `from-llm-draft` — it
> produces a populated `style.json` in a single shot instead of an
> empty shell.

---

## 6. `add-reference` — Append to an Existing Style

Use to attach a new reference image to a style that already exists.

### Synopsis

```bash
python scripts/export_style.py add-reference \
  --style <name-or-path> \
  --image <source-path> \
  --role "<description string>" \
  --use-for <control-type> [--use-for <control-type> ...] \
  [--rename <new-filename>] \
  [--overwrite]
```

### Behavior

1. Resolves `--style` via `PathManager.resolve_style()` (workspace
   lookup) — pass an absolute path for ad-hoc styles outside the
   workspace.
2. Copies the source image into the style directory, optionally
   renaming via `--rename`.
3. Adds (or replaces, with `--overwrite`) the matching entry in
   `style.image_refs`. `use_for` values are deduplicated while
   preserving declaration order.

### Example

```bash
# Add a hover-state button reference to an existing style
python scripts/export_style.py add-reference \
  --style saas-blue \
  --image ~/desktop/button_hover_ref.png \
  --role "Button hover-state standard" \
  --use-for button \
  --rename button_hover.png
```

Resulting `image_refs` after the call:

```json
[
  { "path": "button.png",       "role": "Button standard",        "use_for": ["button"] },
  { "path": "button_hover.png", "role": "Button hover-state standard", "use_for": ["button"] }
]
```

Both refs apply to `control_type: "button"`; the layer/variant prompt
composer will pass them in declaration order.

### Multiple Control Types per Image

Repeat `--use-for` to tag one image with several types:

```bash
python scripts/export_style.py add-reference \
  --style saas-blue \
  --image ~/desktop/container.png \
  --role "Generic container reference" \
  --use-for card --use-for panel --use-for tile
```

---

## 7. Reference Image Selection Guidance

The reference images make or break the style. Pick them deliberately:

- **One canonical look per control category.** A button reference
  should show the *normal* / default state, not a hover or disabled
  variant. State variants are derived from this canonical look in
  Phase 8.
- **Transparent or matched background.** When the LLM sees a button
  reference on a noisy background, it sometimes copies the noise into
  the generated layer. Use cropped PNGs with transparent or
  solid-color backgrounds.
- **Consistent palette across refs.** If button.png uses `#3B82F6`
  but sidebar.png uses `#EFF6FF`, the model will struggle to apply
  both consistently — keep all refs inside the same design language.
- **3 refs is the practical sweet spot.** The pipeline supports up to
  5 total images per `edit` call. In layer phase, that budget
  becomes: preview (1) + matching refs (≤4). Going above 3 refs per
  control category risks hitting the cap and silently truncating.
- **Name files after their `use_for[0]`.** `button.png`,
  `sidebar.png`, `card.png` — easier to debug when reading prompts.
- **Crop to the control, not the full screen.** Generative models pay
  most attention to image content; surrounding chrome dilutes the
  signal.

---

## 8. Filling `style.json` By Hand

After running `manual` (or `from-project` without subsequent
re-processing), the structured fields are mostly empty. Recommended
fill order:

1. **`motif.tags`** — first, because the derived anchor consumes them
   in declaration order. Use 2-4 short tags (`["flat", "minimalist",
   "saas-dashboard"]`).
2. **`palette.role.primary`** — the single most important token. The
   derived anchor uses it for `"primary {hex}"`.
3. **`typography.font_family`** — exact font name (`"Inter"`,
   `"JetBrains Mono"`, etc.).
4. **`spacing.base`** — usually 4 or 8.
5. **`shape.button_radius`** OR **`shape.corner_radius_md`** — pick
   the tier that matches your buttons.
6. **`elevation.preset`** — short shorthand for the shadow vibe
   (`"soft"`, `"sharp"`, `"none"`).
7. **`rules.interaction`** — at least state-change rules (hover,
   active, disabled). Phase 8 filters to this category.
8. **`rules.layout` / `rules.typography`** — anything else that
   downstream prompts should respect.

### Validating Your Edits

Before relying on a style in a real workflow, validate it:

```python
import style_loader
from pathlib import Path

style_dir = Path("layer-designer/styles/saas-blue")
style = style_loader.load_style(style_dir)
errors = style_loader.validate(style, style_dir)
assert not errors, errors

# Inspect the derived anchor
print(style_loader.derive_anchor(style))

# Verify the control-type enum the Phase 2 LLM will be given
print(style_loader.list_control_types(style))
```

`validate()` checks:

- `schema_version` present and parseable
- Every `image_refs[*].path` resolves to an existing file
- Every `image_refs[*].use_for` is a non-empty list of strings
- Any `palette.role.*` / `palette.semantic.*` hex codes are
  well-formed
- `name` matches the folder name (warning, not fatal)

`from-llm-draft` runs this validation automatically before returning
success, so a draft that passes the command also passes the bar above.

---

## 9. Versioning the Library

The `layer-designer/styles/` directory is intended to be **checked
in**. Treat each style as a small reusable asset:

- Commit `style.json` and every referenced image.
- Don't commit `derived_from` previews if they're large — the path is
  stored as a string for provenance, but the file itself doesn't need
  to be in the repo.
- When bumping a style (e.g., updating `palette.role.primary`), bump
  the `description` to note the change. The schema does not currently
  track in-style versions (`schema_version` is the wire-format
  version), so use git history or a `CHANGELOG.md` inside the style
  folder if you need a paper trail.
- To deprecate a style, leave it on disk but rename to
  `styles/_archive/<name>/`. Resolver lookups only scan top-level
  entries.

---

## 10. End-to-End Example: LLM-Drafted Style from Reference Images

User pastes three images: a button cropped on transparent
background, a sidebar mockup, and a metric card. They say "make a
saas-blue style from these."

**Step 1**: Look at the images. Identify the dominant blue
(`#3B82F6`), surface white (`#FFFFFF`), neutral text (`#111827`),
soft shadow vibe, 4px button radius, 8px grid.

**Step 2**: Propose `control_type` mapping. "I'll bind
button.png→`button`, sidebar.png→`sidebar`+`navigation`,
card.png→`card`+`panel`. OK?"

**Step 3**: Draft `style.json` (full schema, populated tokens, 4-5
rules). Compute the derived anchor mentally:
`"flat, minimalist, saas-dashboard, primary #3B82F6, Inter font, 8px
grid, rounded 4px buttons, soft shadows"`.

**Step 4**: Present the draft + anchor + copy-references plan.

**Step 5**: User says "swap accent to amber, drop the
`saas-dashboard` tag." Apply edits.

**Step 6**: User says "ship it."

**Step 7**: Confirm spec generation parameters (size defaults to
`2048x2048`, quality to `medium` from `config.json`). These can be
overridden with `--spec-size` and `--spec-quality`.

**Step 8**: Persist with mandatory `--generate-spec`:

```bash
python scripts/export_style.py from-llm-draft \
  --name saas-blue \
  --json-stdin \
  --generate-spec \
  --config config.json \
  --copy-references "/tmp/user_button.png:button.png" \
  --copy-references "/tmp/user_sidebar.png:sidebar.png" \
  --copy-references "/tmp/user_card.png:card.png" <<'JSON'
{
  "schema_version": "1.0",
  "name": "PLACEHOLDER",
  "description": "Internal SaaS dashboard, blue + amber accent",
  "image_refs": [
    {"path": "button.png",  "role": "Button standard",   "use_for": ["button"]},
    {"path": "sidebar.png", "role": "Sidebar standard",  "use_for": ["sidebar", "navigation"]},
    {"path": "card.png",    "role": "Card container",    "use_for": ["card", "panel"]}
  ],
  "palette": {
    "role":     {"primary": "#3B82F6", "accent": "#F59E0B", "surface": "#FFFFFF", "text_primary": "#111827"},
    "semantic": {"info": "#0EA5E9"}
  },
  "typography": {"font_family": "Inter"},
  "spacing":    {"base": 8},
  "shape":      {"button_radius": 4, "corner_radius_md": 8},
  "elevation":  {"preset": "soft"},
  "motif":      {"tags": ["flat", "minimalist"]},
  "rules": {
    "interaction": [
      "Hover lifts shadow one tier (sm → md, md → lg)",
      "Disabled state uses 50% opacity"
    ],
    "layout":     ["Align to 8px grid"],
    "typography": ["Headings: Inter Bold, ≥ 24px"]
  },
  "style_anchor_override": null
}
JSON
```

The resulting style folder contains only **`spec.png`** (the generated
specification sheet) plus `style.json`. The original reference images
(`button.png`, `sidebar.png`, `card.png`) were consumed as edit inputs
during spec generation and removed automatically. If you need to keep
them, pass `--keep-original-refs`.

Verify it loads:

```python
import style_loader
from pathlib import Path
d = Path("layer-designer/styles/saas-blue")
s = style_loader.load_style(d)
print("errors:", style_loader.validate(s, d))
print("anchor:", style_loader.derive_anchor(s))
print("control_types:", style_loader.list_control_types(s))
```

Then run a real workflow with `--style saas-blue` and confirm Phase
2 emits `control_type` tags drawn from the union the validator
reports.

---

## 11. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `[ERROR] Style '<name>' already exists` | Running `from-llm-draft` / `from-project` / `manual` on an existing folder. | Pass `--overwrite`, or use `add-reference` instead. |
| `[ERROR] --copy-references must be exactly 2 colon-separated fields` (from `from-llm-draft`) | Spec includes role/use_for fields — those belong inside the draft JSON, not on the command line. | Use the 2-field `source:dest_filename` format. |
| `[ERROR] --copy-references must be exactly 4 colon-separated fields` (from `from-project`) | Source path contains 4+ colons, OR you forgot a field. | Check the spec; absolute Windows paths (with one `:` after the drive letter) are fine because parsing is right-to-left. |
| `[ERROR] style.image_refs references images not present` | Draft references a file that wasn't copied. | Add a matching `--copy-references` spec, or remove the entry from `image_refs`. |
| `[ERROR] Invalid JSON in <stdin>` | Stdin pipe truncated, or you accidentally piped shell output. | Verify the JSON validates locally first; for long drafts prefer `--json-file`. |
| `[ERROR] Written style.json failed validation` | The LLM produced structurally valid JSON that still doesn't satisfy `style_loader.validate()` (e.g., bad hex code, empty `use_for`). | Read the per-error list under the message; the file is left on disk, so iterate by editing + re-validating. |
| `[ERROR] style.json missing in <dir>` (from `add-reference`) | The target style folder exists but has no `style.json`. | Run `from-llm-draft` or `manual` first to seed it. |
| Generated images still ignore the style | `image_refs` is empty AND `rules` is empty AND `style_anchor_override` is null. | The composer has nothing to say; fill at least one of these. |
| Refs are passed but the LLM ignores them | Refs and the user prompt describe different control categories. | Verify `image_refs[*].use_for` matches the `control_type` Phase 2 emitted in `layer_plan.json`. |
| Variant phase output looks unchanged from the base | Style has no `rules.interaction` entries. | Add interaction rules — the variant composer filters to this category and won't have anything to inject otherwise. |
| `[ERROR] Spec generation failed` | `--generate-spec` was passed but `generate_image.py` failed (missing `--config`, bad API endpoint, size violation). | Ensure `--config config.json` points to a valid config with working API credentials. Check that `--spec-size` complies with model constraints. |
| Spec sheet is low quality or ignores some rules | The prompt is built from `derive_anchor()` + `rules_to_prompt_text()`. If tokens/rules are sparse, the prompt is vague. | Fill `palette.role.primary`, `typography.font_family`, `spacing.base`, `shape.button_radius`, and `rules.interaction` before generating the spec. |
| Original refs disappeared after `--generate-spec` | By design — original refs are consumed as edit inputs and removed to keep the style folder clean. | Pass `--keep-original-refs` if you need them for other purposes. |

---

## 12. Cross-References

- **Schema and consumption rules**: `style-library.md`
- **Phase 2 control-type tagging**: `phase-2-confirmation.md`
- **Layer-extraction prompt composition**: `phase-3-rough-design.md`,
  `phase-6-refinement-layers.md`
- **Variant prompt composition**: `phase-8-variants.md`
- **Loader internals**: `scripts/style_loader.py`
- **CLI tool**: `scripts/export_style.py`
