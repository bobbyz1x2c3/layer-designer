# Incremental Update Mode

**Goal**: Partial modifications after workflow completion without regenerating everything.

**When to read this file**: Agent MUST read this file when the user requests a change after the workflow has completed or during the output phase.

**Trigger examples**:
- "Change the button color to red"
- "Add a search icon to the header"
- "Remove the sidebar"
- "Add a disabled state for the submit button"

**Prerequisite**: Project must have an existing `07-output/manifest.json`. If first run, fall back to full workflow.

---

## Step 1: Parse Scope

Identify the affected scope from the user's request:

| Change Type | Affected Phases | Skip |
|-------------|----------------|------|
| Single layer modification | Phase 3 + Phase 6 for that layer only | Phases 1-2, 4-5, other layers |
| Single control state addition (UI) | Phase 8 for that control only | All other phases |
| Style-only change (colors, fonts, no layout) | Phase 5 preview + Phase 6 all layers | Phase 3 isolation (reuse existing layer masks) |
| Layout change | Affected layers' Phase 3 + Phase 4 + Phase 6 | Unaffected layers |

---

## Step 2: Load Current State

Read `07-output/manifest.json` to determine:
- Current layer list and stacking order
- Current dimensions and style anchor
- Which layers exist and where they are stored

---

## Step 3: Determine Minimal Regeneration Set

Diff the requested change against current state:
1. Identify layers that need regeneration
2. Identify layers that can be reused as-is
3. Identify controls that need new state variants

---

## Step 4: Execute Partial Workflow

Run only necessary phases for affected items:
1. For each affected layer: run Phase 3 (rough) + Phase 6 (refinement)
   - **MUST use `generate_image.py edit`** for both phases, passing the existing layer or preview as `--image`
   - Do NOT use `generate` (text-to-image) for modifications — this would break visual consistency
2. If layout changed: run Phase 4 (check) on affected layers only
3. If style changed: run Phase 5 (preview) then Phase 6 (all layers)
   - Phase 5: use `edit` with the previous preview as `--image`
   - Phase 6: use `edit` with the new preview as `--image`
4. For new states: run Phase 8 for affected controls only
   - Use `edit` with the base control layer as `--image`

---

## Step 5: Generate Web Preview

Generate the interactive web preview with reused + new layers:

```bash
python scripts/generate_preview.py \
  --config config.json \
  --project {project_name} \
  --phase check
```

This produces `04-check/preview.html` with all layers composited via CSS. Open in a browser to verify the final layout.

---

## Step 6: Present Delta

Show the user:
- What changed (new/modified layers or controls)
- What was preserved (reused layers)
- Updated `manifest.json`

---

**Benefit**: Small changes drop from ~28 images to 3–5 images.
