"""Mock-test generate_image.py CLI with style scenarios."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_image

captured = {"mode": None, "prompt": None, "images": None}


def fake_text(prompt, output, size, quality, model, n, config_path, background):
    captured.update({"mode": "text", "prompt": prompt, "images": None})
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(b"fake")
    return [output]


def fake_edit(image_paths, prompt, output, size, quality, model, n, config_path, background):
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    captured.update({"mode": "edit", "prompt": prompt, "images": list(image_paths)})
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(b"fake")
    return [output]


generate_image.text_to_image = fake_text
generate_image.image_to_image = fake_edit


def run(*argv):
    sys.argv = ["generate_image.py", *argv]
    captured.update({"mode": None, "prompt": None, "images": None})
    try:
        generate_image.main()
        return True
    except SystemExit as e:
        return False


with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    style_dir = tmp_path / "fixture"
    style_dir.mkdir()
    (style_dir / "button.png").write_bytes(b"X")
    (style_dir / "card.png").write_bytes(b"X")
    (style_dir / "style.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "name": "fixture",
                "image_refs": [
                    {"path": "button.png", "role": "btn ref", "use_for": ["button"]},
                    {"path": "card.png", "role": "card ref", "use_for": ["card"]},
                ],
                "palette": {"role": {"primary": "#3B82F6"}},
                "typography": {"font_family": "Inter"},
                "spacing": {"base": 8},
                "shape": {"button_radius": 4},
                "motif": {"tags": ["flat"]},
                "rules": {"interaction": ["rule1"], "layout": ["rule2"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    noref_dir = tmp_path / "noref"
    noref_dir.mkdir()
    (noref_dir / "style.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "name": "noref",
                "palette": {"role": {"primary": "#FF0000"}},
                "rules": {"layout": ["only layout"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    base = tmp_path / "preview.png"
    base.write_bytes(b"X")
    out_path = tmp_path / "out" / "result.png"

    print("=== Test 1: generate with refs (auto-route to edit) ===")
    run(
        "generate",
        "--style-from", str(style_dir),
        "--prompt", "dashboard",
        "--output", str(out_path),
    )
    print("mode:", captured["mode"])
    print("image_count:", len(captured["images"] or []))
    print("has [button] header:", "Image1 [button]" in captured["prompt"])
    print("has Design rules:", "Design rules" in captured["prompt"])
    print()

    print("=== Test 2: generate without refs (stays text) ===")
    run(
        "generate",
        "--style-from", str(noref_dir),
        "--prompt", "dashboard",
        "--output", str(out_path),
    )
    print("mode:", captured["mode"])
    print("has Design rules:", "Design rules" in captured["prompt"])
    print("has User request:", "User request" in captured["prompt"])
    print("starts with Image:", captured["prompt"].startswith("Image"))
    print()

    print("=== Test 3: edit phase=layer control_type=button ===")
    run(
        "edit",
        "--style-from", str(style_dir),
        "--control-type", "button",
        "--phase", "layer",
        "--image", str(base),
        "--prompt", "Extract submit_button",
        "--output", str(out_path),
    )
    print("image_count:", len(captured["images"]))
    print("image_names:", [Path(p).name for p in captured["images"]])
    print("has Image2 [button]:", "Image2 [button]" in captured["prompt"])
    print()

    print("=== Test 4: edit phase=layer control_type=None ===")
    run(
        "edit",
        "--style-from", str(style_dir),
        "--phase", "layer",
        "--image", str(base),
        "--prompt", "Extract main_chart",
        "--output", str(out_path),
    )
    print("image_count:", len(captured["images"]))
    print("image_names:", [Path(p).name for p in captured["images"]])
    print("no Image2 header:", "Image2" not in captured["prompt"])
    print()

    print("=== Test 5: edit phase=variant control_type=button ===")
    run(
        "edit",
        "--style-from", str(style_dir),
        "--control-type", "button",
        "--phase", "variant",
        "--image", str(base),
        "--prompt", "hover variant",
        "--output", str(out_path),
    )
    print("image_count:", len(captured["images"]))
    print("has Image1 [button]:", "Image1 [button]" in captured["prompt"])
    print("filtered to interaction:", "filtered to interaction" in captured["prompt"])
    print()

    print("=== Test 6: edit + style + multiple --image (should error) ===")
    ok = run(
        "edit",
        "--style-from", str(style_dir),
        "--control-type", "button",
        "--image", str(base), str(base),
        "--prompt", "x",
        "--output", str(out_path),
    )
    print("rejected:", not ok)
    print()

    print("=== Test 7: --style and --style-from mutex ===")
    ok = run(
        "edit",
        "--style", "foo", "--style-from", str(style_dir),
        "--image", str(base),
        "--prompt", "x",
        "--output", str(out_path),
    )
    print("rejected:", not ok)
    print()

    print("=== Test 8: backward-compat (no --style) ===")
    run(
        "edit",
        "--image", str(base),
        "--prompt", "plain edit",
        "--output", str(out_path),
    )
    print("mode:", captured["mode"])
    print("prompt unchanged:", captured["prompt"] == "plain edit")
    print("image_count:", len(captured["images"]))
    print()

    print("all CLI tests done")
