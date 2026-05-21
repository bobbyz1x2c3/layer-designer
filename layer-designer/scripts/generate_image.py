#!/usr/bin/env python3
"""
Unified image generation script supporting both text-to-image and image-to-image.

Provider architecture:
  - provider_type = "openai"  → Synchronous (client.images.generate/edit)
  - provider_type = "async_task" → Asynchronous (POST task → poll → download URLs)

The async_task mode is generic: any provider that follows the pattern of
  1. POST to submit a generation job and receive a task_id
  2. GET to poll task status until completed/failed
  3. Download result image URLs

can be added purely through config.json without code changes.

Workflow phases where this script is invoked:
- Phase 1 (Requirements): generate preview candidates
- Phase 3 (Rough Design): generate isolated layers from confirmed preview
- Phase 4 (Rework): regenerate problematic layers
- Phase 5 (Refinement Preview): generate high-quality full preview
- Phase 6 (Refinement Layers): generate final high-quality isolated layers
- Phase 7/8 (Variants): generate control state variants or animation frames
"""

import argparse
import base64
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from config_loader import (
    load_config,
    get_api_config,
    get_provider_api_config,
    get_model_constraints,
    get_phase_model,
    parse_model_spec,
)
import style_loader


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def _resolve_default_provider(config_path: str | None = None) -> str:
    """Read the default provider name from config (api.default_provider, legacy api.provider)."""
    try:
        return get_api_config(load_config(config_path)).get("provider", "openai").lower()
    except Exception:
        return "openai"


def _provider_cfg(config_path: str | None, provider: str) -> dict:
    """Get the API config block for a SPECIFIC provider, regardless of default."""
    try:
        return get_provider_api_config(load_config(config_path), provider)
    except Exception:
        return {"provider": provider, "provider_type": "openai", "base_url": "", "api_key": "", "async_config": {}}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def save_b64_image(b64_data: str, output_path: str):
    """Save base64-encoded image to file."""
    image_data = base64.b64decode(b64_data)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(image_data)
    return output_path


def _resolve_background(background: str | None, config_path: str | None,
                        model: str, provider: str) -> str | None:
    """Drop "transparent" if the (provider, model) pair does not support it."""
    if not background:
        return None
    if background != "transparent":
        return background
    try:
        cfg = load_config(config_path)
        model_cfg = get_model_constraints(cfg, model, provider=provider)
        supports = model_cfg.get("supports_transparent_output", False)
    except Exception:
        supports = False
    return "transparent" if supports else None


def _check_size_allowed(size: str, config_path: str | None, model: str, provider: str):
    """Raise ValueError if the (provider, model) has fixed allowed_sizes and size is not in the list."""
    try:
        cfg = load_config(config_path)
        model_cfg = get_model_constraints(cfg, model, provider=provider)
        allowed_sizes = model_cfg.get("allowed_sizes")
    except Exception:
        return
    if not allowed_sizes:
        return
    normalized = size.replace("*", "x").lower().strip()
    if normalized not in [s.replace("*", "x").lower().strip() for s in allowed_sizes]:
        raise ValueError(
            f"Model '{provider}/{model}' only supports fixed sizes: {', '.join(allowed_sizes)}. "
            f"Requested size '{size}' is not allowed. "
            f"PL (precise_layout) mode will fail because the canvas size does not match the model's constraints."
        )


def _extract_nested(data, path: str):
    """Extract value from nested dict/list by dot-separated path.

    Supports array indices: 'data.0.task_id' → data[0]['task_id']
    """
    if not path:
        return data
    parts = path.split(".")
    current = data
    for part in parts:
        if current is None:
            return None
        if isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx] if 0 <= idx < len(current) else None
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


# ---------------------------------------------------------------------------
# OpenAI provider (synchronous)
# ---------------------------------------------------------------------------

def get_client(config_path: str | None = None, provider: str | None = None):
    """Initialize OpenAI-compatible client for a specific provider.

    Args:
        config_path: Path to config.json (defaults to project config).
        provider: Provider name (e.g. 'openai', 'apimart'). When None, uses the
                  configured default provider.
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    if provider is None:
        provider = _resolve_default_provider(config_path)
    cfg = _provider_cfg(config_path, provider)

    api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "your-key")
    base_url = cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://your-api-gateway.com/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def _text_to_image_openai(prompt: str, output: str, size: str, quality: str,
                          model: str, n: int, config_path: str | None,
                          background: str | None, provider: str):
    client = get_client(config_path, provider=provider)
    resolved_bg = _resolve_background(background, config_path, model, provider)
    kwargs = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "output_format": "png",
        "response_format": "b64_json",
        "n": n,
    }
    if resolved_bg:
        kwargs["background"] = resolved_bg
    result = client.images.generate(**kwargs)
    paths = []
    for i, data in enumerate(result.data):
        suffix = f"_{i+1}" if n > 1 else ""
        out_path = str(Path(output).with_suffix("")) + suffix + Path(output).suffix
        save_b64_image(data.b64_json, out_path)
        paths.append(out_path)
    return paths


def _image_to_image_openai(image_paths: str | list[str], prompt: str, output: str,
                           size: str, quality: str, model: str, n: int,
                           config_path: str | None, background: str | None,
                           provider: str):
    client = get_client(config_path, provider=provider)

    if isinstance(image_paths, str):
        image_paths = [image_paths]

    if len(image_paths) > 5:
        print(f"ERROR: Too many reference images ({len(image_paths)}). Maximum is 5.", file=sys.stderr)
        sys.exit(1)

    for p in image_paths:
        if not Path(p).exists():
            print(f"ERROR: Image not found: {p}", file=sys.stderr)
            sys.exit(1)

    with ExitStack() as stack:
        if len(image_paths) == 1:
            image_input = stack.enter_context(open(image_paths[0], "rb"))
        else:
            image_input = [
                stack.enter_context(open(p, "rb"))
                for p in image_paths
            ]

        resolved_bg = _resolve_background(background, config_path, model, provider)
        kwargs = {
            "model": model,
            "image": image_input,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
            "response_format": "b64_json",
        }
        if resolved_bg:
            kwargs["background"] = resolved_bg
        result = client.images.edit(**kwargs)
        paths = []
        for i, data in enumerate(result.data):
            suffix = f"_{i+1}" if n > 1 else ""
            out_path = str(Path(output).with_suffix("")) + suffix + Path(output).suffix
            save_b64_image(data.b64_json, out_path)
            paths.append(out_path)
        return paths


# ---------------------------------------------------------------------------
# Generic async_task provider
# ---------------------------------------------------------------------------

def _async_http_request(base_url: str, api_key: str, method: str, path: str,
                        json_data: dict | None = None):
    """Low-level HTTP helper."""
    import requests
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if method.upper() == "GET":
        resp = requests.get(url, headers=headers, timeout=180)
    else:
        resp = requests.post(url, json=json_data, headers=headers, timeout=180)
    resp.raise_for_status()
    return resp.json()


def _download_image(url: str, output_path: str):
    """Download image from URL to local file."""
    import requests
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path


def _poll_async_task(base_url: str, api_key: str, task_id: str,
                     async_config: dict, provider: str) -> dict:
    """Generic async task polling.

    Reads polling behaviour from async_config:
      - poll_path_template (default: "/tasks/{task_id}")
      - status_extractor   (default: "data.status")
      - progress_extractor (default: "data.progress")
      - completed_status   (default: "completed")
      - failed_statuses    (default: ["failed", "error"])
      - initial_delay      (default: 10)
      - poll_interval      (default: 5)
      - timeout            (default: 180)
    """
    poll_template = async_config.get("poll_path_template", "/tasks/{task_id}")
    status_path = async_config.get("status_extractor", "data.status")
    progress_path = async_config.get("progress_extractor", "data.progress")
    completed = async_config.get("completed_status", "completed")
    failed = async_config.get("failed_statuses", ["failed", "error"])
    initial_delay = async_config.get("initial_delay", 10)
    interval = async_config.get("poll_interval", 5)
    timeout = async_config.get("timeout", 180)

    print(f"[{provider}] Task {task_id} submitted. Waiting {initial_delay}s before polling...",
          file=sys.stderr)
    time.sleep(initial_delay)

    start = time.time()
    while time.time() - start < timeout:
        poll_path = poll_template.format(task_id=task_id)
        data = _async_http_request(base_url, api_key, "GET", poll_path)

        status = _extract_nested(data, status_path)
        progress = _extract_nested(data, progress_path) or 0

        print(f"[{provider}] Task {task_id} status={status} progress={progress}%",
              file=sys.stderr)

        if status == completed:
            return data
        if status in failed:
            raise RuntimeError(f"{provider} task failed: status={status}")

        time.sleep(interval)

    raise TimeoutError(f"{provider} task {task_id} polling timeout after {timeout}s")


def _async_task_generate(payload: dict, output: str, n: int,
                         config_path: str | None, provider: str) -> list[str]:
    """Generic async task generation flow.

    1. POST payload to submit_path
    2. Extract task_id via task_id_extractor
    3. Poll until completed
    4. Extract image URLs via image_urls_extractor
    5. Download each URL to local file
    """
    cfg = _provider_cfg(config_path, provider)
    api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "your-key")
    base_url = cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.apimart.ai/v1")
    base_url = base_url.rstrip("/")
    async_cfg = cfg.get("async_config", {})

    submit_path = async_cfg.get("submit_path", "/images/generations")
    task_id_path = async_cfg.get("task_id_extractor", "data.0.task_id")
    images_path = async_cfg.get("image_urls_extractor", "data.result.images")
    url_field = async_cfg.get("url_field", "url")

    # 1. Submit
    data = _async_http_request(base_url, api_key, "POST", submit_path, payload)

    # 2. Extract task_id
    task_id = _extract_nested(data, task_id_path)
    if not task_id:
        raise RuntimeError(f"Async task submit did not return task_id. Response: {data}")

    # 3. Poll
    result = _poll_async_task(base_url, api_key, task_id, async_cfg, provider)

    # 4. Extract images
    images = _extract_nested(result, images_path)
    if not isinstance(images, list):
        raise RuntimeError(f"Async task result has no image list at path '{images_path}'")

    paths = []
    for i, img in enumerate(images):
        urls = img.get(url_field, []) if isinstance(img, dict) else []
        if not urls:
            continue
        image_url = urls[0] if isinstance(urls, list) else urls
        suffix = f"_{i+1}" if n > 1 else ""
        out_path = str(Path(output).with_suffix("")) + suffix + Path(output).suffix
        _download_image(image_url, out_path)
        paths.append(out_path)

    if not paths:
        raise RuntimeError("Async task completed but no image URLs returned")
    return paths


# ---------------------------------------------------------------------------
# Provider-specific wrappers (async_task)
# ---------------------------------------------------------------------------

def _get_async_extras(config_path: str | None, provider: str) -> dict:
    """Return async_task provider-specific config extras."""
    cfg = _provider_cfg(config_path, provider)
    return {
        "official_fallback": cfg.get("official_fallback", False),
    }


def _text_to_image_async_task(prompt: str, output: str, size: str, quality: str,
                              model: str, n: int, config_path: str | None,
                              background: str | None, provider: str):
    """Text-to-image via generic async_task provider (apimart-compatible)."""
    extras = _get_async_extras(config_path, provider)

    # async_task providers expect 'WxH' (no asterisk)
    size = size.replace("*", "x")

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": n,
    }
    resolved_bg = _resolve_background(background, config_path, model, provider)
    if resolved_bg:
        payload["background"] = resolved_bg
    if extras.get("official_fallback"):
        payload["official_fallback"] = True

    return _async_task_generate(payload, output, n, config_path, provider)


def _file_to_data_uri(path: str) -> str:
    """Read a local image file and return a base64 data URI."""
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        mime = "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _image_to_image_async_task(image_paths: str | list[str], prompt: str, output: str,
                               size: str, quality: str, model: str, n: int,
                               config_path: str | None, background: str | None,
                               provider: str):
    """Image-to-image via generic async_task provider (apimart-compatible)."""
    if isinstance(image_paths, str):
        image_paths = [image_paths]

    for p in image_paths:
        if not Path(p).exists():
            print(f"ERROR: Image not found: {p}", file=sys.stderr)
            sys.exit(1)

    # Convert local files to base64 data URIs
    image_urls = [_file_to_data_uri(p) for p in image_paths]

    extras = _get_async_extras(config_path, provider)

    # async_task providers expect 'WxH' (no asterisk)
    size = size.replace("*", "x")

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": n,
        "image_urls": image_urls,
    }
    resolved_bg = _resolve_background(background, config_path, model, provider)
    if resolved_bg:
        payload["background"] = resolved_bg
    if extras.get("official_fallback"):
        payload["official_fallback"] = True

    return _async_task_generate(payload, output, n, config_path, provider)


# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------

def text_to_image(prompt: str, output: str, size: str = "1024x1024", quality: str = "low",
                  model: str = "gpt-image-2", n: int = 1, config_path: str | None = None,
                  background: str | None = None):
    """Generate image from text prompt.

    `model` may be a plain model name (resolved against the default provider)
    or a `provider/model` spec for cross-provider routing.
    """
    default_provider = _resolve_default_provider(config_path)
    provider, actual_model = parse_model_spec(model, default_provider)
    _check_size_allowed(size, config_path, actual_model, provider)
    ptype = _provider_cfg(config_path, provider).get("provider_type", "openai")
    if ptype == "async_task":
        return _text_to_image_async_task(prompt, output, size, quality, actual_model, n,
                                         config_path, background, provider)
    return _text_to_image_openai(prompt, output, size, quality, actual_model, n,
                                 config_path, background, provider)


def image_to_image(image_paths: str | list[str], prompt: str, output: str,
                   size: str = "1024x1024", quality: str = "low",
                   model: str = "gpt-image-2", n: int = 1,
                   config_path: str | None = None,
                   background: str | None = None):
    """Generate image from existing image(s) + prompt (image-to-image).

    `model` may be a plain model name (resolved against the default provider)
    or a `provider/model` spec for cross-provider routing.
    """
    default_provider = _resolve_default_provider(config_path)
    provider, actual_model = parse_model_spec(model, default_provider)
    _check_size_allowed(size, config_path, actual_model, provider)
    ptype = _provider_cfg(config_path, provider).get("provider_type", "openai")
    if ptype == "async_task":
        return _image_to_image_async_task(image_paths, prompt, output, size, quality,
                                          actual_model, n, config_path, background, provider)
    return _image_to_image_openai(image_paths, prompt, output, size, quality,
                                  actual_model, n, config_path, background, provider)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Layer Designer Image Generation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="Path to config.json")
    common.add_argument("--output", "-o", required=True, help="Output image path")
    common.add_argument("--size", default="1024x1024", help="Image size (e.g., 1024x1024 or 16:9)")
    common.add_argument("--quality", default="low", choices=["low", "medium", "high", "auto"],
                        help="Generation quality")
    common.add_argument("--model", default=None,
                        help="Model spec, plain ('gpt-image-2') or qualified ('apimart/gpt-image-1.5'). "
                             "If omitted, resolves via --phase against api.phase_models, "
                             "or the default provider's default_model when --phase is also omitted.")
    common.add_argument("--phase", choices=["preview", "layer", "variant"], default=None,
                        help="Workflow phase role. Looks up the matching model in api.phase_models. "
                             "Ignored when --model is provided.")
    common.add_argument("--n", type=int, default=1, help="Number of images to generate")
    common.add_argument("--background", choices=["transparent", "opaque", "auto"],
                        default="auto",
                        help="Background type (default: auto, lets the model decide)")
    common.add_argument("--style", default=None,
                        help="Style library name (resolved against {workspace}/styles/{name}/). "
                             "When set, design rules + anchor + (phase-appropriate) reference "
                             "images from the style are folded into the prompt.")
    common.add_argument("--style-from", default=None,
                        help="Explicit path to a style directory containing style.json. "
                             "Mutually exclusive with --style.")
    common.add_argument("--control-type", default=None,
                        help="Layer control type (e.g. 'button', 'card'). Filters which "
                             "style.image_refs are injected in layer/variant phases. "
                             "Ignored in preview phase. Pass an empty value or omit to "
                             "skip style ref injection for this call.")

    # Generate (text-to-image)
    gen_parser = subparsers.add_parser("generate", parents=[common], help="Text-to-image generation")
    gen_parser.add_argument("--prompt", "-p", required=True, help="Text prompt")

    # Edit (image-to-image)
    edit_parser = subparsers.add_parser("edit", parents=[common], help="Image-to-image editing")
    edit_parser.add_argument("--image", "-i", required=True, nargs='+',
                             help="Input image path(s). Multiple images are passed directly to the API.")
    edit_parser.add_argument("--prompt", "-p", required=True, help="Edit prompt")

    args = parser.parse_args()

    # Resolve model: explicit --model wins; else lookup via --phase + phase_models;
    # else fall back to api.<provider>.default_model.
    effective_model = args.model
    if effective_model is None:
        try:
            cfg_for_lookup = load_config(args.config)
            effective_model = get_phase_model(cfg_for_lookup, args.phase)
        except Exception:
            effective_model = "gpt-image-2"

    # ------------------------------------------------------------------
    # Style library: load + prompt rewrite + image-list assembly
    # ------------------------------------------------------------------
    if args.style and args.style_from:
        print("ERROR: --style and --style-from are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    style: dict | None = None
    if args.style or args.style_from:
        try:
            style_dir = style_loader.resolve(args.style or args.style_from)
            style = style_loader.load_style(style_dir)
        except (FileNotFoundError, style_loader.StyleError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    effective_prompt = args.prompt
    effective_images: list[str] | None = getattr(args, "image", None)
    auto_routed = False

    if style is not None:
        # Determine the phase semantics used by build_prompt. For the CLI we
        # mirror the workflow's --phase flag; without it, infer from the
        # subcommand (generate→preview, edit→layer).
        phase_for_prompt = args.phase
        if phase_for_prompt is None:
            phase_for_prompt = "preview" if args.command == "generate" else "layer"

        rule_kinds = ("interaction",) if phase_for_prompt == "variant" else None

        if args.command == "generate":
            built_prompt, ref_imgs = style_loader.build_prompt(
                style,
                user_prompt=args.prompt,
                phase="preview",
                rule_kinds=rule_kinds,
            )
            effective_prompt = built_prompt
            if ref_imgs:
                effective_images = [str(p) for p in ref_imgs]
                auto_routed = True
                print(
                    f"[style] auto-routed to edit (style '{style.get('name', '?')}' "
                    f"has {len(ref_imgs)} image_refs; phase=preview).",
                    file=sys.stderr,
                )
            else:
                effective_images = None  # stay in text-to-image
        else:
            # edit subcommand: --image is required and at least one path exists
            user_images = list(args.image or [])
            if not user_images:
                print("ERROR: --image is required for edit.", file=sys.stderr)
                sys.exit(1)
            if len(user_images) > 1:
                print(
                    "ERROR: --style with edit expects a single base image "
                    "(the preview or layer to extract from). "
                    "Pass additional reference images via the style's image_refs instead.",
                    file=sys.stderr,
                )
                sys.exit(1)
            base_image = user_images[0]
            built_prompt, all_imgs = style_loader.build_prompt(
                style,
                user_prompt=args.prompt,
                phase=phase_for_prompt,
                control_type=args.control_type,
                base_image=base_image,
                rule_kinds=rule_kinds,
            )
            effective_prompt = built_prompt
            effective_images = [str(p) for p in all_imgs]

    try:
        if args.command == "generate" and not auto_routed:
            paths = text_to_image(
                prompt=effective_prompt,
                output=args.output,
                size=args.size,
                quality=args.quality,
                model=effective_model,
                n=args.n,
                config_path=args.config,
                background=args.background,
            )
        else:
            paths = image_to_image(
                image_paths=effective_images,
                prompt=effective_prompt,
                output=args.output,
                size=args.size,
                quality=args.quality,
                model=effective_model,
                n=args.n,
                config_path=args.config,
                background=args.background,
            )
        for p in paths:
            print(f"SAVED: {p}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
