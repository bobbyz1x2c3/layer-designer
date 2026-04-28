# Prompt Templates

## Table of Contents
1. [UI/UX Design Prompts](#uiux-design-prompts)
2. [Common Style Anchors](#common-style-anchors)
3. [Transparency Requirements](#transparency-requirements)

---

## UI/UX Design Prompts

### Phase 1: Preview Generation (Text-to-Image)

**Base Template**:
```
UI design for {app_type}, {screen_type} screen.
Style: {style_description}.
Elements: {component_list}.
Layout: {layout_description}.
Color scheme: {colors}.
Typography: {font_style}.
Overall composition, full interface mockup, clean and modern.
```

**Example**:
```
UI design for a finance dashboard, desktop web application.
Style: flat design with subtle glassmorphism, rounded corners, soft shadows.
Elements: sidebar navigation, top header with search, KPI cards grid, line chart, recent transactions table.
Layout: left sidebar 240px, main content area with 24px padding, card-based grid.
Color scheme: primary blue #3B82F6, surface white #FFFFFF, background gray #F8FAFC, success green #10B981.
Typography: Inter font family, clear hierarchy.
Overall composition, full interface mockup, clean and modern.
```

### Phase 1: Preview Revision (Image-to-Image)

**Base Template**:
```
Based on this UI design, modify: {changes}.
Keep the overall layout and style consistent.
{style_anchor}
```

---

### Phase 1: Reference-Image Preview Generation (UI/UX)

Use this when the user provides a reference image (wireframe, sketch, mockup, screenshot) in `reference-image` mode.

**From Wireframe / Low-Fidelity Prototype**:
```
Transform this wireframe into a polished, high-fidelity UI design.
Retain the layout and structure from the reference.
Apply style: {style_description}.
Elements to render: {component_list}.
Color scheme: {colors}.
Typography: {font_style}.
Refine spacing, visual hierarchy, and proportions. Professional UI mockup quality.
```

**From Existing UI / Screenshot**:
```
Based on this UI reference, recreate and refine the design.
Maintain the core layout and element relationships.
Apply updates: {modifications_if_any}.
Style: {style_description}.
Color scheme: {colors}.
Typography: {font_style}.
Polished, professional UI mockup. Full interface composition.
```

**From Hand-Drawn Sketch**:
```
Interpret this hand-drawn sketch and convert it into a polished digital UI design.
Preserve the intended layout, component positions, and content structure.
Style: {style_description}.
Elements: {component_list}.
Color scheme: {colors}.
Typography: {font_style}.
Clean, modern, professional interface mockup.
```

**Base Reference-Image Revision**:
```
Based on this reference design, modify: {changes}.
Retain the core layout and structure from the original reference.
Keep the overall style consistent.
```

### Phase 3: Layer Isolation (Image-to-Image)

**Background Layer**:
```
From this UI design, extract ONLY the background layer.
Include: {background_elements}.
Full canvas filled, no transparent areas, complete background.
```

**Element Layer** (transparent):
```
From this UI design, extract ONLY the {element_name}.
Include: {specific_contents}.
CRITICAL: Transparent background (PNG with alpha channel).
Isolate this element completely. Do NOT include any other UI elements.
Maintain exact colors, shadows, and style from the original.
CRITICAL: STRICTLY maintain the element's original aspect ratio. Do NOT stretch, distort, or change proportions in any way. The canvas preserves the element's aspect ratio. Scale the element proportionally to fit within the canvas while leaving a small transparent margin of approximately 3-5% on each side. Do NOT let the element touch or overlap the canvas boundary. This margin ensures clean background removal in post-processing.
```

**Example - Button Layer**:
```
From this UI design, extract ONLY the primary "Submit" button.
Include: the button shape, label text "Submit", button shadow.
CRITICAL: Transparent background (PNG with alpha channel).
Isolate this button completely. Do NOT include background, other buttons, or UI chrome.
Maintain exact blue color #3B82F6, rounded corners, and soft shadow from the original.
```

### Phase 5: High-Quality Preview Refinement

```
Refine this UI design to high quality, polished final version.
Enhance: visual hierarchy, spacing consistency, color accuracy, shadow refinement.
Maintain all elements and layout exactly.
Professional UI mockup quality.
```

### Phase 6: High-Quality Layer Refinement (Element — Transparent)

```
From this high-quality UI preview, extract ONLY the {element_name}.
High quality, polished, pixel-perfect.
CRITICAL: Transparent background (PNG with alpha channel).
Preserve exact style, colors, and proportions.
```

### Phase 6: Background Layer Refinement (Non-transparent)

```
From this high-quality UI preview, extract ONLY the background layer.
Include: {background_elements — e.g., gradient, texture, pattern, environment}.
Full canvas filled completely. NO transparent areas.
NO UI elements, NO buttons, NO text, NO icons, NO overlays.
Only the pure background.
```

### Phase 8: Control State Variants

**Base State Template**:
```
This is a {control_type} UI control in normal state.
Generate the same control in {state} state.
Maintain: exact dimensions, colors, typography, border radius, shadow style.
Changes for {state}: {state_specific_changes}.
CRITICAL: Transparent background (PNG with alpha channel).
```

**Examples**:
- Hover: "Slightly brighter, subtle glow effect, elevated shadow"
- Active: "Darker shade, pressed-in appearance, reduced shadow"
- Disabled: "Grayed out, reduced opacity to 40%, no shadow"
- Focused: "Visible focus ring 2px offset, outline color matches primary"
- Error: "Red border #EF4444, subtle red tint background, warning icon"

---

## Common Style Anchors

Use these to reinforce consistency across all generations:

**Flat / Modern UI**:
```
Flat design, minimal, clean lines, no gradients (or subtle gradients only),
consistent 8px grid spacing, rounded corners 8px-16px, soft shadows.
```

**Glassmorphism**:
```
Glassmorphism, translucent surfaces, background blur, subtle white borders,
light refraction effects, layered depth.
```

**Neumorphism**:
```
Neumorphism, soft extruded shapes, monochromatic color scheme,
subtle shadow highlights and lowlights, no hard borders.
```

**Pixel Art**:
```
Pixel art, {resolution} palette, crisp pixel edges, limited color count,
dithering for shading, consistent pixel scale.
```

**Low Poly 3D**:
```
Low poly 3D render, faceted surfaces, flat shading, clean geometry,
minimal polygon count, consistent lighting direction.
```

**Hand-drawn / Stylized**:
```
Hand-drawn style, visible brush strokes, organic lines, watercolor textures,
consistent lighting, warm color palette.
```

---

## Transparency Requirements

Always include this phrase for non-background layers:

```
CRITICAL: The output MUST be a PNG image with a real transparent background (alpha channel).
The background must be fully transparent (alpha = 0), not white or any solid color.
Only the requested element should have visible pixels.
```

For models that struggle with transparency, add:

```
The element should be cleanly cut out and isolated on a transparent background.
No background color, no backdrop, no environment - just the element itself with transparency.
```
