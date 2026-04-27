# Script Usage Reference

## Script Summary

| Script | Phase | Usage |
|--------|-------|-------|
| `validate_size.py` | Phase 1 | `--config`, `--project`, `--width`, `--height` |
| `generate_image.py` | Phase 1,3,5,6,8 | `generate` or `edit` subcommand |
| `check_transparency.py` | Phase 4 | `--config`, `--image` |
| `generate_preview.py` | Phase 4, 7 | `--config`, `--project`, `--phase` |
| `generate_variants.py` | Phase 8 | `--config`, `--image`, `--control-type`, `--states`, `--output-dir` |

**Always pass `--config` and `--project`** to scripts.

---

## Quick Invocation Examples

These are the exact commands verified against the configured API endpoint (`config.json`):

### Text-to-image (generate preview)

```bash
python scripts/generate_image.py generate \
  --config config.json \
  --prompt "A beautiful anime style UI dashboard, flat design, purple theme" \
  --output output/my-app/01-requirements/previews/preview_v1_001.png \
  --size 1024x1024 --quality medium --model gpt-image-2
```

### Image-to-image (edit / layer isolation)

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image output/my-app/01-requirements/previews/preview_v1_001.png \
  --prompt "Extract ONLY the sidebar. Transparent background. Keep exact position." \
  --output output/my-app/03-rough-design/sidebar/sidebar_001.png \
  --size 1024x1024 --quality low --model gpt-image-2
```

### Multi-reference image-to-image

Pass multiple images directly to the API (combined horizontally):

```bash
python scripts/generate_image.py edit \
  --config config.json \
  --image ref_a.png ref_b.png \
  --prompt "Use the element from the first image. Match its size and proportions to the second image. Transparent background." \
  --output output.png --size 1024x1024 --quality high
```

> **Limit**: Maximum 5 reference images per call. For accuracy, explicitly reference images by order in the prompt (e.g., "first image", "second image", "Image 1", "Image 2").

### Size validation (run BEFORE any generation)

```bash
python scripts/validate_size.py \
  --config config.json --project my-app \
  --width 1920 --height 1080
```

### Transparency check

```bash
python scripts/check_transparency.py \
  --config config.json \
  --image output/my-app/03-rough-design/sidebar/sidebar_001.png
```

### Generate interactive web preview (Phase 4 / Phase 7)

```bash
python scripts/generate_preview.py \
  --config config.json \
  --project my-app \
  --phase check
```
