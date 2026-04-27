# Figma Plugin: Layered Design Importer

Import layered UI designs from the `layered-design-generator` workflow directly into Figma with correct layout positions and stacking order.

## Features

- **One-click folder import**: Select a project folder and the plugin auto-discovers `layer_plan.json` and all layer PNGs
- **Multi-plan detection**: If your project folder contains multiple phase outputs (e.g. `03-rough-design/` and `06-refinement-layers/`), the plugin lists them all and lets you pick which one to import
- **Smart image matching**: Matches layers to PNGs by `id`, `name`, or normalized filename (handles `_matte`, `_001`, timestamp suffixes)
- **Correct layout**: Each layer is placed at its `x, y, width, height` coordinates from the plan
- **Proper stacking order**: Layers are inserted in the order specified by `stacking_order`
- **Batched transfer**: Large projects (20+ images) are sent in small batches to avoid Figma plugin message size limits

## Installation

1. Open Figma Desktop or Web
2. Go to **Plugins → Development → Import plugin from manifest**
3. Select `layer-designer/figma-plugin/manifest.json`

## Usage

### Folder Import (Recommended)

1. Click **Select Folder**
2. Choose the folder containing your generated layers:
   - A specific phase folder like `03-rough-design/` or `06-refinement-layers/`
   - Or the entire project root folder (the plugin will detect all plans and let you choose)
3. If multiple `layer_plan.json` / `enhanced_layer_plan.json` files are found, pick one from the dropdown
4. Review the summary (e.g. "✅ enhanced_layer_plan.json + ✅ 18 PNG(s)")
5. Click **Import to Figma**

### Manual Import (Fallback)

1. Switch to the **Manual** tab
2. Select `layer_plan.json`
3. Multi-select all layer PNG images
4. Click **Import to Figma**

## File Structure

The plugin expects files produced by the `layered-design-generator` workflow:

```
03-rough-design/
  layer_plan.json
  dialog_window.png
  action_bar.png
  character_portrait.png
  character_portrait_matte.png
  ...
```

Or with enhanced plans:

```
06-refinement-layers/
  enhanced_layer_plan.json
  dialog_window.png
  action_bar.png
  ...
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No layer_plan.json found" | Make sure the folder contains a JSON file with `layer_plan` in its name. Check spelling. |
| "No PNG files found" | Ensure PNG images are in the **same directory** as the selected plan file. The plugin does not recursively collect PNGs from sibling folders. |
| Images show as blue placeholders | The plugin couldn't match a layer to any PNG. Check that filenames match layer `id` or `name` (or use `_matte` variants). |
| Plugin freezes on import | The plugin now sends images in batches. If it still freezes, try importing a smaller folder or fewer layers at a time. |
| Multiple phases mixed up | Select only one phase folder at a time, or use the plan dropdown to pick the correct phase when importing from the project root. |
