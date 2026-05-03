#!/usr/bin/env python3
"""
Test image generation via chat completions + tool calling.

Tries multiple strategies:
1. Standard text chat (baseline)
2. Chat with model=gpt-image-2
3. Chat with modalities=["image"]
4. Chat with tools=[{"type": "image_generation"}]
5. Chat with tool_choice={"type": "image_generation"}
"""

import json
import sys
import requests

BASE_URL = "https://api.b4im.com/v1"
API_KEY = "sk-e3bf3e64eae9a8b8d606fadeed3a6b8cdde2c9f3d9456e6f96e241e4c1a26b1c"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def test(name: str, payload: dict):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    url = f"{BASE_URL}/chat/completions"
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=120)
        print(f"Status: {resp.status_code}")
        try:
            data = resp.json()
            print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)[:2000]}")
        except Exception:
            print(f"Raw: {resp.text[:2000]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    prompt = "A cute watercolor fantasy backpack UI button with soft pink tones"

    # Test 1: Standard text chat (baseline)
    test("Standard text chat", {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
    })

    # Test 2: Chat with gpt-image-2 model
    test("Chat with gpt-image-2", {
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": prompt}],
    })

    # Test 3: Chat with modalities=["image"]
    test("Chat with modalities=['image']", {
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image"],
    })

    # Test 4: Chat with tools image_generation
    test("Chat with tools image_generation", {
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "image_generation"}],
    })

    # Test 5: Chat with tool_choice forcing image_generation
    test("Chat with tool_choice image_generation", {
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "image_generation"}],
        "tool_choice": {"type": "image_generation"},
    })

    # Test 6: Responses API with image tool
    print(f"\n{'='*60}")
    print("TEST: Responses API with image_generation tool")
    print(f"{'='*60}")
    try:
        resp = requests.post(
            f"{BASE_URL}/responses",
            headers=HEADERS,
            json={
                "model": "gpt-image-2",
                "input": prompt,
                "tools": [{"type": "image_generation"}],
            },
            timeout=120,
        )
        print(f"Status: {resp.status_code}")
        try:
            data = resp.json()
            print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)[:2000]}")
        except Exception:
            print(f"Raw: {resp.text[:2000]}")
    except Exception as e:
        print(f"ERROR: {e}")

    print("\n" + "="*60)
    print("Tests completed")
    print("="*60)


if __name__ == "__main__":
    main()
