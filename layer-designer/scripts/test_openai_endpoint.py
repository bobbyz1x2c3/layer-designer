#!/usr/bin/env python3
"""
Direct HTTP POST test for OpenAI-compatible image endpoints.
Bypasses the openai Python SDK to test raw HTTP connectivity.

Usage:
    python test_openai_endpoint.py text          # Test text-to-image
    python test_openai_endpoint.py image <path>  # Test image-to-image
    python test_openai_endpoint.py --config ../config.json text
"""

import argparse
import base64
import json
import sys
from pathlib import Path

from config_loader import load_config, get_api_config


def test_text_to_image(base_url: str, api_key: str, model: str = "gpt-image-2"):
    """Test /images/generations with direct POST."""
    import requests

    url = f"{base_url.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "prompt": "A simple red circle on white background",
        "size": "512x512",
        "n": 1,
        "response_format": "b64_json",
    }

    print(f"\n{'='*60}")
    print("TEST: Text-to-Image (/images/generations)")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Headers: {json.dumps({k: v[:20]+'...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"\nStatus: {resp.status_code}")
        print(f"Response headers: {dict(resp.headers)}")

        try:
            data = resp.json()
            print(f"Response body: {json.dumps(data, indent=2, ensure_ascii=False)[:2000]}")
        except Exception:
            print(f"Response text (raw): {resp.text[:2000]}")

        if resp.status_code == 200:
            print("\n[SUCCESS] Text-to-image endpoint is reachable")
            # Save image if present
            if "data" in data and len(data["data"]) > 0:
                b64 = data["data"][0].get("b64_json")
                if b64:
                    out = Path("test_output_t2i.png")
                    out.write_bytes(base64.b64decode(b64))
                    print(f"[SUCCESS] Image saved to {out.absolute()}")
            return True
        else:
            print(f"\n[FAILED] HTTP {resp.status_code}")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"\n[CONNECTION ERROR] {e}")
        return False
    except requests.exceptions.Timeout as e:
        print(f"\n[TIMEOUT] {e}")
        return False
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return False


def test_image_to_image(base_url: str, api_key: str, image_path: str, model: str = "gpt-image-2"):
    """Test /images/edits with direct POST."""
    import requests

    url = f"{base_url.rstrip('/')}/images/edits"
    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    image_path = Path(image_path)
    if not image_path.exists():
        print(f"❌ Image not found: {image_path}")
        return False

    # OpenAI images.edit expects multipart/form-data
    # Fields: image (file), prompt (string), model (string), size (string), n (int)
    files = {
        "image": (image_path.name, image_path.read_bytes(), "image/png"),
    }
    data = {
        "model": model,
        "prompt": "Change the style to watercolor painting",
        "size": "512x512",
        "n": "1",
        "response_format": "b64_json",
    }

    print(f"\n{'='*60}")
    print("TEST: Image-to-Image (/images/edits)")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Image: {image_path.absolute()} ({image_path.stat().st_size} bytes)")
    print(f"Form data: {json.dumps(data, indent=2)}")

    try:
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=60)
        print(f"\nStatus: {resp.status_code}")
        print(f"Response headers: {dict(resp.headers)}")

        try:
            resp_data = resp.json()
            print(f"Response body: {json.dumps(resp_data, indent=2, ensure_ascii=False)[:2000]}")
        except Exception:
            print(f"Response text (raw): {resp.text[:2000]}")

        if resp.status_code == 200:
            print("\n[SUCCESS] Image-to-image endpoint is reachable")
            if "data" in resp_data and len(resp_data["data"]) > 0:
                b64 = resp_data["data"][0].get("b64_json")
                if b64:
                    out = Path("test_output_i2i.png")
                    out.write_bytes(base64.b64decode(b64))
                    print(f"[SUCCESS] Image saved to {out.absolute()}")
            return True
        else:
            print(f"\n[FAILED] HTTP {resp.status_code}")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"\n[CONNECTION ERROR] {e}")
        return False
    except requests.exceptions.Timeout as e:
        print(f"\n[TIMEOUT] {e}")
        return False
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return False


def test_models(base_url: str, api_key: str):
    """Test /models endpoint."""
    import requests

    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    print(f"\n{'='*60}")
    print("TEST: List Models (/models)")
    print(f"{'='*60}")

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {resp.status_code}")
        try:
            data = resp.json()
            models = data.get("data", [])
            print(f"Available models ({len(models)}):")
            for m in models[:20]:
                print(f"  - {m.get('id')}")
            if len(models) > 20:
                print(f"  ... and {len(models) - 20} more")
        except Exception:
            print(f"Response: {resp.text[:500]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test OpenAI-compatible endpoint via direct HTTP")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("mode", choices=["text", "image", "models"], help="Test mode")
    parser.add_argument("image_path", nargs="?", help="Image path for image-to-image test")
    args = parser.parse_args()

    try:
        cfg = get_api_config(load_config(args.config))
    except Exception as e:
        print(f"Failed to load config: {e}")
        sys.exit(1)

    provider = cfg.get("provider", "openai")
    if provider != "openai":
        print(f"Warning: provider is '{provider}', using openai config block for testing")
        # Re-read specifically the openai block
        raw = load_config(args.config)
        api = raw.get("api", {})
        openai_cfg = api.get("openai", {})
        base_url = openai_cfg.get("base_url", cfg.get("base_url"))
        api_key = openai_cfg.get("api_key", cfg.get("api_key"))
        model = openai_cfg.get("model", cfg.get("model", "gpt-image-2"))
    else:
        base_url = cfg.get("base_url", "https://your-api-gateway.com/v1")
        api_key = cfg.get("api_key", "your-key")
        model = cfg.get("model", "gpt-image-2")

    print(f"Endpoint: {base_url}")
    print(f"Model: {model}")

    if args.mode == "models":
        ok = test_models(base_url, api_key)
    elif args.mode == "text":
        ok = test_text_to_image(base_url, api_key, model)
    elif args.mode == "image":
        if not args.image_path:
            print("❌ Please provide an image path for image-to-image test")
            sys.exit(1)
        ok = test_image_to_image(base_url, api_key, args.image_path, model)
    else:
        parser.print_help()
        sys.exit(1)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
