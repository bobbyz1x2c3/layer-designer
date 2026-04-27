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

  // Build a lookup map from layer id -> layer data
  // Falls back to source basename if id is missing
  const layerMap = new Map();
  for (const layer of plan.layers) {
    let key = layer.id;
    if (!key && layer.source) {
      key = layer.source.split('/').pop().replace(/\.png$/i, '');
    }
    if (key) {
      layerMap.set(key, layer);
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

  let importedCount = 0;
  let missingCount = 0;
  let errorCount = 0;

  for (let i = 0; i < sortedLayers.length; i++) {
    const layer = sortedLayers[i];
    try {
      const rect = figma.createRectangle();
      rect.name = layer.name || layer.id || 'Layer';
      rect.x = layer.layout.x;
      rect.y = layer.layout.y;
      rect.resize(layer.layout.width, layer.layout.height);
      rect.opacity = layer.opacity !== undefined ? layer.opacity : 1;
      // Store original id so export can recover it even if name is localized
      if (layer.id) {
        rect.setPluginData('layerId', layer.id);
      }

      // Attempt to find a matching image (pass source for path-based lookup)
      const layerId = layer.id || (layer.source ? layer.source.split('/').pop().replace(/\.png$/i, '') : layer.name);
      const imageData = findImageForLayer(layerId, layer.name, images, layer.source);

      if (imageData) {
        try {
          console.log('[LayerImporter]   creating image for', layer.name || layerId, 'bytes:', imageData.length);
          const image = figma.createImage(imageData);
          rect.fills = [{
            type: 'IMAGE',
            imageHash: image.hash,
            scaleMode: 'FIT'
          }];
          importedCount++;
          console.log('[LayerImporter]   ✓ image created for', layer.name || layerId);
        } catch (imgErr) {
          console.error('[LayerImporter]   ✗ createImage failed for', layer.name || layerId, ':', imgErr.message);
          figma.notify('Image error for ' + (layer.name || layerId) + ': ' + imgErr.message, { error: true });
          // Fallback to placeholder
          const isBg = layer.is_background;
          rect.fills = [{
            type: 'SOLID',
            color: isBg ? { r: 0.1, g: 0.1, b: 0.15 } : { r: 0.9, g: 0.2, b: 0.2 },
            opacity: isBg ? 1.0 : 0.3
          }];
          errorCount++;
        }
      } else {
        // Placeholder: semi-transparent tint to indicate missing image
        const isBg = layer.is_background;
        rect.fills = [{
          type: 'SOLID',
          color: isBg ? { r: 0.1, g: 0.1, b: 0.15 } : { r: 0.2, g: 0.6, b: 1.0 },
          opacity: isBg ? 1.0 : 0.15
        }];
        missingCount++;
      }

      // Add a subtle border for visibility
      rect.strokeWeight = 1;
      rect.strokes = [{ type: 'SOLID', color: { r: 0.3, g: 0.8, b: 1.0 }, opacity: 0.3 }];

      frame.appendChild(rect);
    } catch (layerErr) {
      console.error('[LayerImporter]   ✗ layer error for', layer.name || layer.id, ':', layerErr.message);
      figma.notify('Layer error: ' + (layer.name || layer.id) + ' - ' + layerErr.message, { error: true });
      errorCount++;
    }
  }

  // Move frame to center of viewport
  figma.currentPage.appendChild(frame);
  figma.viewport.scrollAndZoomIntoView([frame]);

  const msg = `Imported ${sortedLayers.length} layers (${importedCount} images, ${missingCount} missing, ${errorCount} errors)`;
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
  const children = frame.children || [];

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

  for (const child of children) {
    // Only export visible rectangle/image-like nodes
    if (child.type !== 'RECTANGLE' && child.type !== 'VECTOR' && child.type !== 'GROUP') {
      continue;
    }

    const name = child.name || 'Layer';
    const ref = refMap.get(name);

    // Recover original id from plugin data, or fall back to ref/id generation
    let id = child.getPluginData('layerId');
    if (!id && ref && ref.id) id = ref.id;
    if (!id) id = name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
    if (!id) id = 'layer_' + exportedLayers.length;

    const layout = {
      x: Math.round(child.x),
      y: Math.round(child.y),
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

    exportedLayers.push(layer);
    stackingOrder.push(id);
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
