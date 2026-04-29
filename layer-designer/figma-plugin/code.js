/**
 * Figma Plugin: Layered Design Importer
 * Imports layer images from the Layered Design Generator workflow into Figma,
 * positioning each layer according to layer_plan.json layout coordinates.
 */

figma.showUI(__html__, { width: 420, height: 580 });

// State for batched import
let pendingPlan = null;
let pendingImages = {};

figma.ui.onmessage = async (msg) => {
  try {
    if (msg.type === 'import-start') {
      pendingPlan = msg.plan;
      pendingImages = {};
      console.log('[LayerImporter] import-start received, layers:', (msg.plan.layers || []).length);
    } else if (msg.type === 'import-batch') {
      // Decode base64 strings back to Uint8Array
      const entries = Object.entries(msg.images);
      console.log('[LayerImporter] import-batch received, images:', entries.length);
      for (const [name, base64] of entries) {
        try {
          pendingImages[name] = base64ToUint8Array(base64);
          console.log('[LayerImporter]   decoded:', name, 'size:', pendingImages[name].length, 'bytes');
        } catch (e) {
          console.error('[LayerImporter]   failed to decode:', name, e.message);
          figma.notify('Failed to decode image: ' + name, { error: true });
        }
      }
    } else if (msg.type === 'import-done') {
      console.log('[LayerImporter] import-done received, plan:', !!pendingPlan, 'images:', Object.keys(pendingImages).length);
      if (pendingPlan) {
        await importLayers(pendingPlan, pendingImages);
      } else {
        figma.notify('No plan received. Please try again.', { error: true });
      }
      pendingPlan = null;
      pendingImages = {};
    } else if (msg.type === 'export-start') {
      await exportLayerPlan(msg.refPlan || null);
    }
  } catch (err) {
    console.error('[LayerImporter] onmessage error:', err);
    figma.notify('Plugin error: ' + err.message, { error: true });
    pendingPlan = null;
    pendingImages = {};
  }
};

/**
 * Decode base64 string to Uint8Array.
 * Uses a manual decode that does not rely on atob (safer in Figma plugin env).
 */
function base64ToUint8Array(base64) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const lookup = new Uint8Array(256);
  for (let i = 0; i < chars.length; i++) {
    lookup[chars.charCodeAt(i)] = i;
  }

  const len = base64.length;
  let padding = 0;
  if (base64[len - 1] === '=') padding++;
  if (base64[len - 2] === '=') padding++;

  const outLen = (len * 3 / 4) - padding;
  const bytes = new Uint8Array(outLen);

  let j = 0;
  for (let i = 0; i < len; i += 4) {
    const encoded1 = lookup[base64.charCodeAt(i)];
    const encoded2 = lookup[base64.charCodeAt(i + 1)];
    const encoded3 = lookup[base64.charCodeAt(i + 2)];
    const encoded4 = lookup[base64.charCodeAt(i + 3)];

    bytes[j++] = (encoded1 << 2) | (encoded2 >> 4);
    if (j < outLen) bytes[j++] = ((encoded2 & 15) << 4) | (encoded3 >> 2);
    if (j < outLen) bytes[j++] = ((encoded3 & 3) << 6) | encoded4;
  }

  return bytes;
}

/**
 * Create a Figma rectangle node for a single layer.
 */
async function createLayerNode(layer, images) {
  const rect = figma.createRectangle();
  rect.name = layer.name || layer.id || 'Layer';
  rect.x = layer.layout.x;
  rect.y = layer.layout.y;
  rect.resize(layer.layout.width, layer.layout.height);
  rect.opacity = layer.opacity !== undefined ? layer.opacity : 1;
  if (layer.id) {
    rect.setPluginData('layerId', layer.id);
  }

  const layerId = layer.id || (layer.source ? layer.source.split('/').pop().replace(/\.png$/i, '') : layer.name);
  const imageData = findImageForLayer(layerId, layer.name, images, layer.source);

  if (imageData) {
    try {
      const image = figma.createImage(imageData);
      rect.fills = [{
        type: 'IMAGE',
        imageHash: image.hash,
        scaleMode: 'FIT'
      }];
    } catch (imgErr) {
      const isBg = layer.is_background;
      rect.fills = [{
        type: 'SOLID',
        color: isBg ? { r: 0.1, g: 0.1, b: 0.15 } : { r: 0.9, g: 0.2, b: 0.2 },
        opacity: isBg ? 1.0 : 0.3
      }];
    }
  } else {
    const isBg = layer.is_background;
    rect.fills = [{
      type: 'SOLID',
      color: isBg ? { r: 0.1, g: 0.1, b: 0.15 } : { r: 0.2, g: 0.6, b: 1.0 },
      opacity: isBg ? 1.0 : 0.15
    }];
  }

  rect.strokeWeight = 1;
  rect.strokes = [{ type: 'SOLID', color: { r: 0.3, g: 0.8, b: 1.0 }, opacity: 0.3 }];

  return rect;
}

/**
 * Resolve padding from repeat config (number or object).
 */
function resolvePadding(config) {
  const p = config.padding;
  if (p !== undefined && p !== null) {
    if (typeof p === 'object') {
      return {
        top: p.top || 0,
        right: p.right || 0,
        bottom: p.bottom || 0,
        left: p.left || 0
      };
    }
    const v = parseInt(p) || 0;
    return { top: v, right: v, bottom: v, left: v };
  }
  return { top: 0, right: 0, bottom: 0, left: 0 };
}

/**
 * Compute an instance's position relative to its repeat container based on config.
 * Needed because auto-layout manages positions in Figma, but round-trip needs relative coords.
 */
function getInstanceRelativePosition(instanceNode) {
  let container = instanceNode.parent;
  while (container) {
    if (container.getPluginData && container.getPluginData('repeatGroup') === 'true') break;
    container = container.parent;
  }
  if (!container) return { x: 0, y: 0 };

  const configStr = container.getPluginData('repeatConfig');
  const cellLayoutStr = container.getPluginData('parentLayerLayout');
  if (!configStr || !cellLayoutStr) return { x: 0, y: 0 };

  let config, cellLayout;
  try { config = JSON.parse(configStr); } catch (e) { return { x: 0, y: 0 }; }
  try { cellLayout = JSON.parse(cellLayoutStr); } catch (e) { return { x: 0, y: 0 }; }

  const mode = instanceNode.getPluginData('repeatMode') || config.repeat_mode || 'grid';
  const padding = resolvePadding(config);
  const cellW = cellLayout.width || 100;
  const cellH = cellLayout.height || 100;
  const col = parseInt(instanceNode.getPluginData('cellCol') || '0');
  const row = parseInt(instanceNode.getPluginData('cellRow') || '0');
  const idx = parseInt(instanceNode.getPluginData('cellIndex') || '0');

  if (mode === 'grid') {
    const gapX = config.gap_x || 0;
    const gapY = config.gap_y || 0;
    return {
      x: padding.left + col * (cellW + gapX),
      y: padding.top + row * (cellH + gapY),
    };
  } else if (mode === 'list') {
    const gap = config.gap || 0;
    const direction = config.direction || 'horizontal';
    if (direction === 'horizontal') {
      return { x: padding.left + idx * (cellW + gap), y: padding.top };
    } else {
      return { x: padding.left, y: padding.top + idx * (cellH + gap) };
    }
  }
  return { x: 0, y: 0 };
}

/**
 * Create an Auto Layout container for a repeat group (grid or list).
 */
async function createRepeatAutoLayout(parentFrame, group, images) {
  const { instances, panel, parentLayer } = group;
  if (!instances.length || !parentLayer) return;

  const config = parentLayer.repeat_config || {};
  const mode = parentLayer.repeat_mode || 'list';
  const padding = resolvePadding(config);

  // Create container frame
  const container = figma.createFrame();
  container.name = parentLayer.name || parentLayer.id || 'Repeat Group';

  // Store repeat metadata for export
  const pid = parentLayer.id || parentLayer.name;
  container.setPluginData('repeatGroup', 'true');
  container.setPluginData('repeatMode', mode);
  container.setPluginData('repeatConfig', JSON.stringify(config));
  container.setPluginData('parentLayerId', pid);
  container.setPluginData('parentLayerName', parentLayer.name || '');

  // Save cell size (not area_layout) so export/import round-trip uses correct cell dimensions
  const cellW = instances[0].layout.width;
  const cellH = instances[0].layout.height;
  container.setPluginData('parentLayerLayout', JSON.stringify({ x: 0, y: 0, width: cellW, height: cellH }));
  container.setPluginData('parentLayerOpacity', String(parentLayer.opacity !== undefined ? parentLayer.opacity : 1));

  // On round-trip, parentLayer.layout becomes container bounds (with cell_layout holding cell size).
  // On first import, parentLayout.layout is cell size, so fall back to panel/instance coords.
  const baseX = parentLayer.cell_layout ? parentLayer.layout.x : (panel ? panel.layout.x : instances[0].layout.x);
  const baseY = parentLayer.cell_layout ? parentLayer.layout.y : (panel ? panel.layout.y : instances[0].layout.y);
  container.x = baseX;
  container.y = baseY;

  let containerW, containerH;
  if (parentLayer.cell_layout) {
    // Round-trip: use saved container bounds directly, don't recompute
    containerW = parentLayer.layout.width;
    containerH = parentLayer.layout.height;
  } else if (panel) {
    containerW = panel.layout.width;
    containerH = panel.layout.height;
  } else {
    // First import: compute from instance absolute coordinates
    let maxRight = 0, maxBottom = 0;
    for (const inst of instances) {
      maxRight = Math.max(maxRight, inst.layout.x + inst.layout.width - baseX);
      maxBottom = Math.max(maxBottom, inst.layout.y + inst.layout.height - baseY);
    }
    containerW = (maxRight || instances[0].layout.width) + padding.left + padding.right;
    containerH = (maxBottom || instances[0].layout.height) + padding.top + padding.bottom;
  }
  container.resize(containerW, containerH);
  container.fills = [];
  container.clipsContent = false;

  // Add panel background if exists
  if (panel) {
    const panelNode = await createLayerNode(panel, images);
    panelNode.setPluginData('isRepeatPanel', 'true');
    panelNode.setPluginData('repeatParentId', pid);
    container.appendChild(panelNode);
    panelNode.x = 0;
    panelNode.y = 0;
    panelNode.resize(panel.layout.width, panel.layout.height);
  }

  // Create auto layout frame for instances
  const autoFrame = figma.createFrame();
  autoFrame.name = 'Instances';
  autoFrame.fills = [];
  autoFrame.clipsContent = false;
  autoFrame.setPluginData('repeatInternal', 'true');

  // cellW / cellH already declared above (line ~225) for parentLayerLayout

  // Helper to add a node with fixed sizing into auto layout
  async function addFixedNode(targetFrame, layer, extraPluginData = {}) {
    const node = await createLayerNode(layer, images);
    node.layoutSizingHorizontal = 'FIXED';
    node.layoutSizingVertical = 'FIXED';
    for (const [key, value] of Object.entries(extraPluginData)) {
      node.setPluginData(key, value);
    }
    targetFrame.appendChild(node);
  }

  if (mode === 'list') {
    const direction = config.direction || 'horizontal';
    const gap = config.gap || 0;
    autoFrame.layoutMode = direction === 'horizontal' ? 'HORIZONTAL' : 'VERTICAL';
    autoFrame.primaryAxisAlignItems = 'MIN';
    autoFrame.counterAxisAlignItems = 'MIN';
    autoFrame.itemSpacing = gap;
    autoFrame.paddingLeft = padding.left;
    autoFrame.paddingRight = padding.right;
    autoFrame.paddingTop = padding.top;
    autoFrame.paddingBottom = padding.bottom;

    for (const inst of instances) {
      await addFixedNode(autoFrame, inst, {
        isRepeatInstance: 'true',
        parentId: pid,
        cellIndex: String(inst.cell_index || 0),
        cellRow: String(inst.cell_row || 0),
        cellCol: String(inst.cell_col || 0),
        repeatMode: mode,
      });
    }

    autoFrame.primaryAxisSizingMode = 'FIXED';
    autoFrame.counterAxisSizingMode = 'FIXED';
    autoFrame.resize(
      direction === 'horizontal'
        ? instances.length * cellW + Math.max(0, instances.length - 1) * gap + padding.left + padding.right
        : cellW + padding.left + padding.right,
      direction === 'horizontal'
        ? cellH + padding.top + padding.bottom
        : instances.length * cellH + Math.max(0, instances.length - 1) * gap + padding.top + padding.bottom
    );
  } else if (mode === 'grid') {
    const cols = config.cols || 1;
    const rows = config.rows || 1;
    const gapX = config.gap_x || 0;
    const gapY = config.gap_y || 0;

    if (cols === 1 && rows === 1) {
      autoFrame.layoutMode = 'HORIZONTAL';
      autoFrame.itemSpacing = 0;
      autoFrame.paddingLeft = padding.left;
      autoFrame.paddingRight = padding.right;
      autoFrame.paddingTop = padding.top;
      autoFrame.paddingBottom = padding.bottom;
      await addFixedNode(autoFrame, instances[0], {
        isRepeatInstance: 'true',
        parentId: pid,
        cellIndex: String(instances[0].cell_index || 0),
        cellRow: String(instances[0].cell_row || 0),
        cellCol: String(instances[0].cell_col || 0),
        repeatMode: mode,
      });
      autoFrame.resize(cellW + padding.left + padding.right, cellH + padding.top + padding.bottom);
    } else if (cols === 1) {
      autoFrame.layoutMode = 'VERTICAL';
      autoFrame.primaryAxisAlignItems = 'MIN';
      autoFrame.counterAxisAlignItems = 'MIN';
      autoFrame.itemSpacing = gapY;
      autoFrame.paddingLeft = padding.left;
      autoFrame.paddingRight = padding.right;
      autoFrame.paddingTop = padding.top;
      autoFrame.paddingBottom = padding.bottom;
      for (const inst of instances) {
        await addFixedNode(autoFrame, inst, {
          isRepeatInstance: 'true',
          parentId: pid,
          cellIndex: String(inst.cell_index || 0),
          cellRow: String(inst.cell_row || 0),
          cellCol: String(inst.cell_col || 0),
          repeatMode: mode,
        });
      }
      autoFrame.resize(cellW + padding.left + padding.right, rows * cellH + Math.max(0, rows - 1) * gapY + padding.top + padding.bottom);
    } else if (rows === 1) {
      autoFrame.layoutMode = 'HORIZONTAL';
      autoFrame.primaryAxisAlignItems = 'MIN';
      autoFrame.counterAxisAlignItems = 'MIN';
      autoFrame.itemSpacing = gapX;
      autoFrame.paddingLeft = padding.left;
      autoFrame.paddingRight = padding.right;
      autoFrame.paddingTop = padding.top;
      autoFrame.paddingBottom = padding.bottom;
      for (const inst of instances) {
        await addFixedNode(autoFrame, inst, {
          isRepeatInstance: 'true',
          parentId: pid,
          cellIndex: String(inst.cell_index || 0),
          cellRow: String(inst.cell_row || 0),
          cellCol: String(inst.cell_col || 0),
          repeatMode: mode,
        });
      }
      autoFrame.resize(cols * cellW + Math.max(0, cols - 1) * gapX + padding.left + padding.right, cellH + padding.top + padding.bottom);
    } else {
      // Nested grid: outer VERTICAL, inner HORIZONTAL per row
      autoFrame.layoutMode = 'VERTICAL';
      autoFrame.primaryAxisAlignItems = 'MIN';
      autoFrame.counterAxisAlignItems = 'MIN';
      autoFrame.itemSpacing = gapY;
      autoFrame.paddingLeft = padding.left;
      autoFrame.paddingRight = padding.right;
      autoFrame.paddingTop = padding.top;
      autoFrame.paddingBottom = padding.bottom;

      for (let r = 0; r < rows; r++) {
        const rowFrame = figma.createFrame();
        rowFrame.name = `Row ${r + 1}`;
        rowFrame.layoutMode = 'HORIZONTAL';
        rowFrame.primaryAxisAlignItems = 'MIN';
        rowFrame.counterAxisAlignItems = 'MIN';
        rowFrame.itemSpacing = gapX;
        rowFrame.paddingLeft = rowFrame.paddingRight = rowFrame.paddingTop = rowFrame.paddingBottom = 0;
        rowFrame.fills = [];
        rowFrame.clipsContent = false;
        rowFrame.setPluginData('repeatInternal', 'true');

        const rowInstances = instances.filter(inst => (inst.cell_row || 0) === r);
        for (const inst of rowInstances) {
          await addFixedNode(rowFrame, inst, {
            isRepeatInstance: 'true',
            parentId: pid,
            cellIndex: String(inst.cell_index || 0),
            cellRow: String(inst.cell_row || 0),
            cellCol: String(inst.cell_col || 0),
            repeatMode: mode,
          });
        }

        // Fix row frame size explicitly so it doesn't collapse to default 100
        rowFrame.primaryAxisSizingMode = 'FIXED';
        rowFrame.counterAxisSizingMode = 'FIXED';
        rowFrame.resize(
          cols * cellW + Math.max(0, cols - 1) * gapX,
          cellH
        );

        autoFrame.appendChild(rowFrame);
      }

      autoFrame.primaryAxisSizingMode = 'FIXED';
      autoFrame.counterAxisSizingMode = 'FIXED';
      autoFrame.resize(
        cols * cellW + Math.max(0, cols - 1) * gapX + padding.left + padding.right,
        rows * cellH + Math.max(0, rows - 1) * gapY + padding.top + padding.bottom
      );
    }

    autoFrame.primaryAxisSizingMode = 'FIXED';
    autoFrame.counterAxisSizingMode = 'FIXED';
  }

  container.appendChild(autoFrame);
  autoFrame.x = 0;
  autoFrame.y = 0;
  parentFrame.appendChild(container);
}

/**
 * Main import function.
 * @param {object} plan - Parsed layer_plan.json content
 * @param {Record<string, Uint8Array>} images - Map of image name -> PNG bytes
 */
async function importLayers(plan, images) {
  console.log('[LayerImporter] importLayers start, dimensions:', plan.dimensions);

  // Create the main frame, centered on current viewport
  const frame = figma.createFrame();
  frame.name = plan.project || "Imported Design";
  frame.resize(plan.dimensions.width, plan.dimensions.height);
  frame.fills = [{ type: 'SOLID', color: { r: 0.05, g: 0.05, b: 0.05 } }];
  frame.clipsContent = false;

  const center = figma.viewport.center;
  frame.x = center.x - plan.dimensions.width / 2;
  frame.y = center.y - plan.dimensions.height / 2;

  // Build a lookup map from layer id/name -> layer data
  // Falls back to source basename if id is missing
  // Also indexes by name because stacking_order may use names (repeat instances/panels)
  const layerMap = new Map();
  for (const layer of plan.layers) {
    let key = layer.id;
    if (!key && layer.source) {
      key = layer.source.split('/').pop().replace(/\.png$/i, '');
    }
    if (key) {
      layerMap.set(key, layer);
    }
    if (layer.name && layer.name !== key) {
      layerMap.set(layer.name, layer);
    }
  }
  console.log('[LayerImporter] layerMap keys:', Array.from(layerMap.keys()));
  console.log('[LayerImporter] images keys:', Object.keys(images));

  // Sort layers by stacking_order
  const sortedIds = plan.stacking_order || plan.layers.map(l => l.id).filter(Boolean);
  const sortedLayers = sortedIds
    .map(id => layerMap.get(id))
    .filter(l => l !== undefined);

  console.log('[LayerImporter] sortedLayers:', sortedLayers.length, 'of', plan.layers.length);

  // Pre-process repeat groups from all layers (including parents not in stacking_order)
  const repeatGroups = {};
  for (const layer of plan.layers || []) {
    if (layer.is_repeat_instance && layer.parent_id) {
      if (!repeatGroups[layer.parent_id]) {
        repeatGroups[layer.parent_id] = { instances: [], panel: null, parentLayer: null };
      }
      repeatGroups[layer.parent_id].instances.push(layer);
    } else if (layer.is_repeat_panel && layer.repeat_parent_id) {
      if (!repeatGroups[layer.repeat_parent_id]) {
        repeatGroups[layer.repeat_parent_id] = { instances: [], panel: null, parentLayer: null };
      }
      repeatGroups[layer.repeat_parent_id].panel = layer;
    } else if (layer.is_repeat_parent) {
      const pid = layer.id || layer.name;
      if (!repeatGroups[pid]) {
        repeatGroups[pid] = { instances: [], panel: null, parentLayer: layer };
      } else {
        repeatGroups[pid].parentLayer = layer;
      }
    }
  }
  // Sort instances by cell_index within each group
  for (const group of Object.values(repeatGroups)) {
    group.instances.sort((a, b) => (a.cell_index || 0) - (b.cell_index || 0));
  }

  let importedCount = 0;
  let missingCount = 0;
  let errorCount = 0;
  let autoLayoutCount = 0;
  const processedNames = new Set();

  for (let i = 0; i < sortedLayers.length; i++) {
    const layer = sortedLayers[i];

    // Skip if already processed as part of a repeat group
    if (processedNames.has(layer.name)) continue;

    // Determine group key for any repeat-related layer (parent, instance, or panel)
    let groupKey = null;
    if (layer.is_repeat_parent) {
      groupKey = layer.id || layer.name;
    } else if (layer.is_repeat_instance && layer.parent_id) {
      groupKey = layer.parent_id;
    } else if (layer.is_repeat_panel && layer.repeat_parent_id) {
      groupKey = layer.repeat_parent_id;
    }

    if (groupKey && repeatGroups[groupKey] && !processedNames.has('__group__' + groupKey)) {
      processedNames.add('__group__' + groupKey);
      const group = repeatGroups[groupKey];

      // Create auto layout only if parent metadata is available
      if (group.parentLayer && group.instances.length > 0) {
        try {
          await createRepeatAutoLayout(frame, group, images);
          autoLayoutCount++;
          // Mark all group members as processed
          for (const inst of group.instances) processedNames.add(inst.name);
          if (group.panel) processedNames.add(group.panel.name);
          // Count image imports for stats
          for (const inst of group.instances) {
            const layerId = inst.id || (inst.source ? inst.source.split('/').pop().replace(/\.png$/i, '') : inst.name);
            if (findImageForLayer(layerId, inst.name, images, inst.source)) {
              importedCount++;
            } else {
              missingCount++;
            }
          }
          if (group.panel) {
            const panelId = group.panel.id || (group.panel.source ? group.panel.source.split('/').pop().replace(/\.png$/i, '') : group.panel.name);
            if (findImageForLayer(panelId, group.panel.name, images, group.panel.source)) {
              importedCount++;
            } else {
              missingCount++;
            }
          }
          continue;
        } catch (groupErr) {
          console.error('[LayerImporter]   ✗ repeat group error for', groupKey, ':', groupErr.message);
          figma.notify('Repeat group error: ' + groupKey + ' - ' + groupErr.message, { error: true });
          errorCount++;
          // Fall through to individual processing below
        }
      }
      // No parentLayer or group creation failed: process members individually below
    }

    // Normal layer processing (also handles repeat members when not in auto layout)
    try {
      const rect = await createLayerNode(layer, images);
      frame.appendChild(rect);
      processedNames.add(layer.name);

      // Count for stats
      const layerId = layer.id || (layer.source ? layer.source.split('/').pop().replace(/\.png$/i, '') : layer.name);
      if (findImageForLayer(layerId, layer.name, images, layer.source)) {
        importedCount++;
      } else {
        missingCount++;
      }
    } catch (layerErr) {
      console.error('[LayerImporter]   ✗ layer error for', layer.name || layer.id, ':', layerErr.message);
      figma.notify('Layer error: ' + (layer.name || layer.id) + ' - ' + layerErr.message, { error: true });
      errorCount++;
    }
  }

  // Move frame to center of viewport
  figma.currentPage.appendChild(frame);
  figma.viewport.scrollAndZoomIntoView([frame]);

  const msg = `Imported ${sortedLayers.length} layers (${importedCount} images, ${missingCount} missing, ${errorCount} errors${autoLayoutCount > 0 ? ', ' + autoLayoutCount + ' auto-layout groups' : ''})`;
  console.log('[LayerImporter]', msg);
  figma.notify(msg);

  // Notify UI that import is complete
  figma.ui.postMessage({
    type: 'import-complete',
    importedCount,
    missingCount,
    errorCount,
    totalLayers: sortedLayers.length,
  });
}

/**
 * Export current Figma selection as an enhanced_layer_plan JSON.
 * User must select a single Frame that was previously imported.
 * If refPlan is provided, metadata (content, source, status, id) is merged by name match.
 *
 * Recursively traverses the frame tree to recover repeat group structures
 * (container → panel → instances) via pluginData set during import.
 */
async function exportLayerPlan(refPlan) {
  const selection = figma.currentPage.selection;

  if (selection.length === 0) {
    figma.notify('Please select a Frame to export.', { error: true });
    figma.ui.postMessage({ type: 'export-error', message: 'No selection. Please select a Frame.' });
    return;
  }
  if (selection.length > 1) {
    figma.notify('Please select only one Frame.', { error: true });
    figma.ui.postMessage({ type: 'export-error', message: 'Multiple selections. Please select only one Frame.' });
    return;
  }

  const node = selection[0];
  if (node.type !== 'FRAME' && node.type !== 'GROUP') {
    figma.notify('Selected node must be a Frame or Group.', { error: true });
    figma.ui.postMessage({ type: 'export-error', message: 'Selected node is not a Frame or Group.' });
    return;
  }

  const frame = node;

  // Build reference map by name (for merging metadata)
  const refMap = new Map();
  if (refPlan && refPlan.layers) {
    for (const layer of refPlan.layers) {
      const key = layer.name || layer.id || '';
      if (key) refMap.set(key, layer);
    }
  }

  const exportedLayers = [];
  const stackingOrder = [];

  /**
   * Sync actual Figma auto-layout values back to repeat_config so that
   * user edits (padding, gap) inside Figma are preserved on export.
   */
  function syncAutoLayoutToConfig(container, config) {
    const autoFrame = (container.children || []).find(c => c.getPluginData && c.getPluginData('repeatInternal') === 'true');
    if (!autoFrame) return;

    // repeat_mode is NOT stored inside repeatConfig pluginData; read it from the container directly.
    const mode = container.getPluginData('repeatMode') || 'grid';

    // Sync padding from autoFrame
    config.padding = {
      top: autoFrame.paddingTop || 0,
      right: autoFrame.paddingRight || 0,
      bottom: autoFrame.paddingBottom || 0,
      left: autoFrame.paddingLeft || 0
    };

    // Sync gaps
    if (mode === 'grid') {
      // Nested grid: gapY from autoFrame, gapX from first rowFrame
      const rowFrame = (autoFrame.children || []).find(c => c.getPluginData && c.getPluginData('repeatInternal') === 'true');
      if (rowFrame) {
        config.gap_y = autoFrame.itemSpacing || 0;
        config.gap_x = rowFrame.itemSpacing || 0;
      } else {
        // Single row or single col
        if (autoFrame.layoutMode === 'HORIZONTAL') {
          config.gap_x = autoFrame.itemSpacing || 0;
        } else {
          config.gap_y = autoFrame.itemSpacing || 0;
        }
      }
    } else if (mode === 'list') {
      config.gap = autoFrame.itemSpacing || 0;
      // Clean up mistaken grid fields from previous exports
      delete config.gap_x;
      delete config.gap_y;
    }

    // Write updated config back to container pluginData so that
    // getInstanceRelativePosition (which reads pluginData) uses the new values.
    container.setPluginData('repeatConfig', JSON.stringify(config));
  }

  /**
   * Build a layer entry from a Figma node, restoring repeat metadata from pluginData.
   */
  function buildLayerFromNode(child) {
    const name = child.name || 'Layer';
    const ref = refMap.get(name);

    // Recover original id from plugin data
    let id = child.getPluginData('layerId');
    if (!id && child.type === 'FRAME' && child.getPluginData('repeatGroup') === 'true') {
      id = child.getPluginData('parentLayerId');
    }
    if (!id && ref && ref.id) id = ref.id;
    if (!id) id = name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
    if (!id) id = 'layer_' + exportedLayers.length;

    // Coordinates:
    // - repeat instance: compute relative position from config for round-trip accuracy
    // - repeat panel: at (0,0) inside container
    // - repeat container / normal layers: actual frame-relative position
    let x, y;
    if (child.getPluginData('isRepeatInstance') === 'true') {
      const pos = getInstanceRelativePosition(child);
      x = pos.x; y = pos.y;
    } else if (child.getPluginData('isRepeatPanel') === 'true') {
      x = 0; y = 0;
    } else {
      x = child.x !== null && child.x !== undefined ? child.x : 0;
      y = child.y !== null && child.y !== undefined ? child.y : 0;
    }

    const layout = {
      x: Math.round(x),
      y: Math.round(y),
      width: Math.round(child.width),
      height: Math.round(child.height),
    };

    const layer = {
      id: id,
      name: name,
      content: (ref && ref.content) || (ref && ref.description) || '',
      status: (ref && ref.status) || 'active',
      layout: layout,
      opacity: child.opacity !== undefined ? child.opacity : 1,
    };

    if (ref) {
      if (ref.source) layer.source = ref.source;
    }

    // Restore repeat group metadata (container frame)
    if (child.type === 'FRAME' && child.getPluginData('repeatGroup') === 'true') {
      layer.is_repeat_parent = true;
      layer.repeat_mode = child.getPluginData('repeatMode') || 'grid';
      const configStr = child.getPluginData('repeatConfig');
      if (configStr) {
        try { layer.repeat_config = JSON.parse(configStr); } catch (e) { layer.repeat_config = {}; }
      } else {
        layer.repeat_config = {};
      }
      // Sync user-edited auto-layout values back to config
      syncAutoLayoutToConfig(child, layer.repeat_config);
      // Export cell size separately for preview.html
      const parentLayoutStr = child.getPluginData('parentLayerLayout');
      if (parentLayoutStr) {
        try { layer.cell_layout = JSON.parse(parentLayoutStr); } catch (e) {}
      }
      const parentOpacityStr = child.getPluginData('parentLayerOpacity');
      if (parentOpacityStr) {
        layer.opacity = parseFloat(parentOpacityStr);
      }
    }

    // Restore panel metadata
    if (child.getPluginData('isRepeatPanel') === 'true') {
      layer.is_repeat_panel = true;
      layer.repeat_parent_id = child.getPluginData('repeatParentId') || '';
    }

    // Restore instance metadata
    if (child.getPluginData('isRepeatInstance') === 'true') {
      layer.is_repeat_instance = true;
      layer.parent_id = child.getPluginData('parentId') || '';
      layer.cell_index = parseInt(child.getPluginData('cellIndex') || '0');
      layer.cell_row = parseInt(child.getPluginData('cellRow') || '0');
      layer.cell_col = parseInt(child.getPluginData('cellCol') || '0');
      layer.repeat_mode = child.getPluginData('repeatMode') || '';
    }

    return layer;
  }

  /**
   * Recursively traverse the node tree, exporting layers while skipping
   * internal auto-layout structures.
   */
  function traverseAndExport(node) {
    // Skip internal auto-layout frames (instances live inside them)
    if (node.getPluginData && node.getPluginData('repeatInternal') === 'true') {
      for (const child of node.children || []) {
        traverseAndExport(child);
      }
      return;
    }

    if (node.type === 'RECTANGLE' || node.type === 'VECTOR' || node.type === 'GROUP') {
      const layer = buildLayerFromNode(node);
      exportedLayers.push(layer);
      stackingOrder.push(layer.id);
    } else if (node.type === 'FRAME' && node.getPluginData && node.getPluginData('repeatGroup') === 'true') {
      // Repeat group container: export as parent, then recurse for panel + instances
      const layer = buildLayerFromNode(node);
      exportedLayers.push(layer);
      stackingOrder.push(layer.id);
      for (const child of node.children || []) {
        traverseAndExport(child);
      }
    } else if (node.type === 'FRAME' || node.type === 'GROUP') {
      // Regular frame/group: recurse into children
      for (const child of node.children || []) {
        traverseAndExport(child);
      }
    }
  }

  for (const child of frame.children || []) {
    traverseAndExport(child);
  }

  const result = {
    project: refPlan ? refPlan.project : (frame.name || 'exported'),
    phase: 'check',
    dimensions: {
      width: Math.round(frame.width),
      height: Math.round(frame.height),
    },
    style_anchor: refPlan ? refPlan.style_anchor : '',
    layers: exportedLayers,
    stacking_order: stackingOrder,
  };

  figma.ui.postMessage({
    type: 'export-complete',
    plan: result,
    layerCount: exportedLayers.length,
  });

  figma.notify(`Exported ${exportedLayers.length} layers from "${frame.name}"`);
}

/**
 * Try to match a layer to an uploaded image by id, name, or source path.
 * Source path takes highest priority so we pick the final/cropped or matte
 * versions explicitly referenced by the plan.
 */
function findImageForLayer(id, name, images, source) {
  if (!images) return null;

  const keys = Object.keys(images);
  if (keys.length === 0) return null;

  // Helper: case-insensitive key lookup
  const findKey = (target) => {
    const t = target.toLowerCase();
    for (const k of keys) {
      if (k.toLowerCase() === t) return k;
    }
    return null;
  };

  // Strip timestamp and numeric version suffixes only (keep _matte and _cropped)
  const stripTimestamp = (s) => s.toLowerCase()
    .replace(/_\d{8}_\d{6}$/, '')
    .replace(/_\d+$/, '')
    .replace(/_v\d+$/, '');

  // 0. Source-based match (highest priority)
  if (source) {
    const sourceBase = source.split('/').pop().replace(/\.png$/i, '');

    // 0a. Exact source basename match
    let k = findKey(sourceBase);
    if (k) return images[k];

    // 0b. Source basename + "_matte" (transparent background version)
    k = findKey(sourceBase + '_matte');
    if (k) return images[k];

    // 0c. Source basename + "_cropped" (final cropped version)
    k = findKey(sourceBase + '_cropped');
    if (k) return images[k];

    // 0d. Stripped basename + "_cropped" (e.g. background_20260426_1845 -> background_cropped)
    const stripped = stripTimestamp(sourceBase);
    if (stripped !== sourceBase.toLowerCase()) {
      k = findKey(stripped + '_cropped');
      if (k) return images[k];

      k = findKey(stripped + '_matte');
      if (k) return images[k];

      k = findKey(stripped);
      if (k) return images[k];
    }
  }

  // 1. Exact match by id
  if (images[id]) return images[id];

  // 2. Exact match by name
  if (images[name]) return images[name];

  // 3. Normalize: strip _matte, timestamps, _001, _v1
  const normalize = (s) => s.toLowerCase()
    .replace(/_matte(_v\d+)?$/, '')
    .replace(/_\d{8}_\d{6}$/, '')
    .replace(/_\d+$/, '')
    .replace(/_v\d+$/, '');

  const normId = id ? normalize(id) : '';
  const normName = name ? normalize(name) : '';

  // 4. Fuzzy match normalized names
  for (const key of keys) {
    const normKey = normalize(key);
    if (normKey === normId || normKey === normName) {
      return images[key];
    }
  }

  // 5. Substring match
  for (const key of keys) {
    const normKey = normalize(key);
    if ((normId && normKey.includes(normId)) || (normName && normKey.includes(normName))) {
      return images[key];
    }
  }

  return null;
}
