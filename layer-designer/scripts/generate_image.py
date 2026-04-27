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

from config_loader import load_config, get_api_config, get_model_constraints


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _get_provider(config_path: str | None = None) -> str:
    """Detect provider name from config. Defaults to 'openai'."""
    try:
        cfg = get_api_config(load_config(config_path))
        return cfg.get("provider", "openai").lower()
    except Exception:
        return "openai"


def _get_provider_type(config_path: str | None = None) -> str:
    """Detect provider_type from config. Defaults to 'openai'."""
    try:
        cfg = get_api_config(load_config(config_path))
        return cfg.get("provider_type", "openai").lower()
    except Exception:
        return "openai"


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


def _resolve_background(background: str | None, config_path: str | None, model: str) -> str | None:
    """Resolve background parameter.

    If the model's config explicitly sets supports_transparent_output to false,
    the background parameter is always ignored to avoid upstream errors.
    """
    try:
        cfg = load_config(config_path)
        model_cfg = get_model_constraints(cfg, model)
        supports = model_cfg.get("supports_transparent_output", False)
    except Exception:
        supports = False

    if not supports:
        return None
    return background


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

def get_client(config_path: str | None = None):
    """Initialize OpenAI client from config or environment."""
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = get_api_config(load_config(config_path))
    except Exception:
        cfg = {}

    api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "your-key")
    base_url = cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://your-api-gateway.com/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def _text_to_image_openai(prompt: str, output: str, size: str, quality: str,
                          model: str, n: int, config_path: str | None,
                          background: str | None):
    client = get_client(config_path)
    resolved_bg = _resolve_background(background, config_path, model)
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
                           config_path: str | None, background: str | None):
    client = get_client(config_path)

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

        resolved_bg = _resolve_background(background, config_path, model)
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
                     async_config: dict) -> dict:
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

    provider_name = _get_provider()
    print(f"[{provider_name}] Task {task_id} submitted. Waiting {initial_delay}s before polling...",
          file=sys.stderr)
    time.sleep(initial_delay)

    start = time.time()
    while time.time() - start < timeout:
        poll_path = poll_template.format(task_id=task_id)
        data = _async_http_request(base_url, api_key, "GET", poll_path)

        status = _extract_nested(data, status_path)
        progress = _extract_nested(data, progress_path) or 0

        print(f"[{provider_name}] Task {task_id} status={status} progress={progress}%",
              file=sys.stderr)

        if status == completed:
            return data
        if status in failed:
            raise RuntimeError(f"{provider_name} task failed: status={status}")

        time.sleep(interval)

    raise TimeoutError(f"{provider_name} task {task_id} polling timeout after {timeout}s")


def _async_task_generate(payload: dict, output: str, n: int,
                         config_path: str | None) -> list[str]:
    """Generic async task generation flow.

    1. POST payload to submit_path
    2. Extract task_id via task_id_extractor
    3. Poll until completed
    4. Extract image URLs via image_urls_extractor
    5. Download each URL to local file
    """
    cfg = get_api_config(load_config(config_path))
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
    result = _poll_async_task(base_url, api_key, task_id, async_cfg)

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
# Provider-specific wrappers (apimart)
# ---------------------------------------------------------------------------

def _get_apimart_extras(config_path: str | None = None) -> dict:
    """Return apimart-specific config extras."""
    cfg = get_api_config(load_config(config_path))
    return {
        "official_fallback": cfg.get("official_fallback", False),
        "prefer_official": cfg.get("prefer_official", True),
    }


def _text_to_image_async_task(prompt: str, output: str, size: str, quality: str,
                              model: str, n: int, config_path: str | None,
                              background: str | None):
    """Text-to-image via generic async_task provider (apimart-compatible)."""
    extras = _get_apimart_extras(config_path)

    # apimart-specific: normalise asterisk to 'x'
    size = size.replace("*", "x")

    # apimart-specific: prefer official model
    if extras.get("prefer_official") and model == "gpt-image-2":
        model = "gpt-image-2-official"

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": n,
    }
    if background:
        payload["background"] = background
    if extras.get("official_fallback"):
        payload["official_fallback"] = True

    return _async_task_generate(payload, output, n, config_path)


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
                               config_path: str | None, background: str | None):
    """Image-to-image via generic async_task provider (apimart-compatible)."""
    if isinstance(image_paths, str):
        image_paths = [image_paths]

    for p in image_paths:
        if not Path(p).exists():
            print(f"ERROR: Image not found: {p}", file=sys.stderr)
            sys.exit(1)

    # Convert local files to base64 data URIs
    image_urls = [_file_to_data_uri(p) for p in image_paths]

    extras = _get_apimart_extras(config_path)

    # apimart-specific: normalise asterisk to 'x'
    size = size.replace("*", "x")

    # apimart-specific: prefer official model
    if extras.get("prefer_official") and model == "gpt-image-2":
        model = "gpt-image-2-official"

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": n,
        "image_urls": image_urls,
    }
    if background:
        payload["background"] = background
    if extras.get("official_fallback"):
        payload["official_fallback"] = True

    return _async_task_generate(payload, output, n, config_path)


# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------

def text_to_image(prompt: str, output: str, size: str = "1024x1024", quality: str = "low",
                  model: str = "gpt-image-2", n: int = 1, config_path: str | None = None,
                  background: str | None = None):
    """Generate image from text prompt."""
    ptype = _get_provider_type(config_path)
    if ptype == "async_task":
        return _text_to_image_async_task(prompt, output, size, quality, model, n, config_path, background)
    return _text_to_image_openai(prompt, output, size, quality, model, n, config_path, background)


def image_to_image(image_paths: str | list[str], prompt: str, output: str,
                   size: str = "1024x1024", quality: str = "low",
                   model: str = "gpt-image-2", n: int = 1,
                   config_path: str | None = None,
                   background: str | None = None):
    """Generate image from existing image(s) + prompt (image-to-image)."""
    ptype = _get_provider_type(config_path)
    if ptype == "async_task":
        return _image_to_image_async_task(image_paths, prompt, output, size, quality, model, n, config_path, background)
    return _image_to_image_openai(image_paths, prompt, output, size, quality, model, n, config_path, background)


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
    common.add_argument("--model", default="gpt-image-2", help="Model name")
    common.add_argument("--n", type=int, default=1, help="Number of images to generate")
    common.add_argument("--background", choices=["transparent", "opaque", "auto"],
                        help="Background type (transparent for alpha channel PNG)")

    # Generate (text-to-image)
    gen_parser = subparsers.add_parser("generate", parents=[common], help="Text-to-image generation")
    gen_parser.add_argument("--prompt", "-p", required=True, help="Text prompt")

    # Edit (image-to-image)
    edit_parser = subparsers.add_parser("edit", parents=[common], help="Image-to-image editing")
    edit_parser.add_argument("--image", "-i", required=True, nargs='+',
                             help="Input image path(s). Multiple images are passed directly to the API.")
    edit_parser.add_argument("--prompt", "-p", required=True, help="Edit prompt")

    args = parser.parse_args()

    try:
        if args.command == "generate":
            paths = text_to_image(
                prompt=args.prompt,
                output=args.output,
                size=args.size,
                quality=args.quality,
                model=args.model,
                n=args.n,
                config_path=args.config,
                background=args.background,
            )
        else:
            paths = image_to_image(
                image_paths=args.image,
                prompt=args.prompt,
                output=args.output,
                size=args.size,
                quality=args.quality,
                model=args.model,
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
