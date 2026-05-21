"""
Focused unit tests for style_loader.

Covers Task #34 verification items 1-7 from the plan:
  - load_style, validate, derive_anchor, rules_to_prompt_text
  - list_control_types, select_image_refs (button / "*" / None)
  - build_prompt for preview / layer / variant phases
  - resolve precedence (explicit path / workspace / missing)
  - image-count hard cap (preview + many refs)

Run: python scripts/_test_style_loader.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import style_loader  # noqa: E402


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------

FULL_STYLE = {
    "schema_version": "1.0",
    "name": "saas-blue",
    "description": "Internal SaaS dashboard",
    "image_refs": [
        {"path": "button.png",  "role": "Button standard",   "use_for": ["button"]},
        {"path": "sidebar.png", "role": "Sidebar standard",  "use_for": ["sidebar", "navigation"]},
        {"path": "card.png",    "role": "Card container",    "use_for": ["card", "panel"]},
    ],
    "palette": {
        "role":     {"primary": "#3B82F6", "surface": "#FFFFFF"},
        "semantic": {"info": "#0EA5E9"},
    },
    "typography": {"font_family": "Inter"},
    "spacing":    {"base": 8},
    "shape":      {"button_radius": 4, "corner_radius_md": 8},
    "elevation":  {"preset": "soft"},
    "motif":      {"tags": ["flat", "minimalist", "saas-dashboard"]},
    "rules": {
        "interaction": [
            "Hover state lifts shadow one tier (sm → md, md → lg)",
            "Disabled state uses 50% opacity",
        ],
        "layout": ["All elements align to the 8px grid"],
    },
    "style_anchor_override": None,
}


def write_fixture(tmp: Path, body: dict) -> Path:
    """Write a style.json + dummy PNGs so validate passes."""
    style_dir = tmp / body["name"]
    style_dir.mkdir(parents=True, exist_ok=True)
    for ref in body.get("image_refs", []):
        (style_dir / ref["path"]).write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic
    (style_dir / "style.json").write_text(json.dumps(body), encoding="utf-8")
    return style_dir


# ----------------------------------------------------------------------
# tests
# ----------------------------------------------------------------------

results: list[tuple[str, bool, str]] = []


def check(label: str, predicate, hint: str = "") -> None:
    try:
        ok = bool(predicate())
    except Exception as e:
        results.append((label, False, f"{type(e).__name__}: {e}"))
        return
    results.append((label, ok, hint if not ok else ""))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        # ---- load_style + validate happy path ----------------------------
        style_dir = write_fixture(tmp, FULL_STYLE)
        loaded = style_loader.load_style(style_dir)
        check("[1] load_style returns dict with abs_path on each ref",
              lambda: all("abs_path" in r for r in loaded["image_refs"]))
        check("[1b] load_style preserves schema_version",
              lambda: loaded["schema_version"] == "1.0")

        errs = style_loader.validate(loaded, style_dir)
        check("[2] validate(full fixture) returns no errors",
              lambda: errs == [], f"got errors: {errs}")

        # ---- derive_anchor ----------------------------------------------
        anchor = style_loader.derive_anchor(loaded)
        check("[3a] anchor includes motif tags",
              lambda: "flat" in anchor and "minimalist" in anchor)
        check("[3b] anchor includes primary hex",
              lambda: "#3B82F6" in anchor)
        check("[3c] anchor mentions Inter font",
              lambda: "Inter" in anchor and "font" in anchor)
        check("[3d] anchor mentions 8px grid",
              lambda: "8px grid" in anchor)
        check("[3e] anchor mentions 4px buttons",
              lambda: "4px" in anchor and "button" in anchor.lower())
        check("[3f] anchor mentions soft shadows",
              lambda: "soft" in anchor and "shadow" in anchor.lower())

        # override
        override_style = dict(loaded)
        override_style["style_anchor_override"] = "OVERRIDE STRING ONLY"
        check("[3g] style_anchor_override replaces derived anchor entirely",
              lambda: style_loader.derive_anchor(override_style)
                      == "OVERRIDE STRING ONLY")

        # ---- list_control_types -----------------------------------------
        cts = style_loader.list_control_types(loaded)
        check("[4] list_control_types returns deduped union in declaration order",
              lambda: cts == ["button", "sidebar", "navigation", "card", "panel"],
              f"got {cts}")

        # ---- select_image_refs ------------------------------------------
        only_btn = style_loader.select_image_refs(loaded, "button")
        check("[5a] select_image_refs('button') -> only button ref",
              lambda: len(only_btn) == 1 and only_btn[0]["path"] == "button.png")

        panel_refs = style_loader.select_image_refs(loaded, "panel")
        check("[5b] select_image_refs('panel') -> card ref (multi-use_for)",
              lambda: len(panel_refs) == 1 and panel_refs[0]["path"] == "card.png")

        all_refs = style_loader.select_image_refs(loaded, "*")
        check("[5c] select_image_refs('*') -> all refs",
              lambda: len(all_refs) == 3)

        none_refs = style_loader.select_image_refs(loaded, None)
        check("[5d] select_image_refs(None) -> []",
              lambda: none_refs == [])

        unknown_refs = style_loader.select_image_refs(loaded, "spaceship")
        check("[5e] select_image_refs(unknown) -> []",
              lambda: unknown_refs == [])

        # wildcard "*" in use_for matches any control_type
        wild_body = dict(FULL_STYLE)
        wild_body["name"] = "wildcard-spec"
        wild_body["image_refs"] = [
            {"path": "spec.png", "role": "Spec summary", "use_for": ["*"]},
            {"path": "button.png", "role": "Button standard", "use_for": ["button"]},
        ]
        wild_dir = write_fixture(tmp, wild_body)
        wild_loaded = style_loader.load_style(wild_dir)
        wild_all = style_loader.select_image_refs(wild_loaded, "*")
        check("[5f] select_image_refs('*') still returns all refs",
              lambda: len(wild_all) == 2)
        wild_btn = style_loader.select_image_refs(wild_loaded, "button")
        check("[5g] wildcard ref returned for button",
              lambda: len(wild_btn) == 2
                      and any(r["path"] == "spec.png" for r in wild_btn))
        wild_card = style_loader.select_image_refs(wild_loaded, "card")
        check("[5h] wildcard ref returned for unmatched control_type",
              lambda: len(wild_card) == 1
                      and wild_card[0]["path"] == "spec.png")

        # ---- build_prompt: preview with refs ----------------------------
        preview_prompt, preview_imgs = style_loader.build_prompt(
            loaded,
            user_prompt="Dashboard with sidebar, top nav, 4-card metric grid",
            phase="preview",
        )
        check("[6a] preview phase passes all 3 refs",
              lambda: len(preview_imgs) == 3)
        check("[6b] preview prompt labels Image1 with [button]",
              lambda: "Image1 [button]" in preview_prompt)
        check("[6c] preview prompt labels Image2 with [sidebar]",
              lambda: "Image2 [sidebar]" in preview_prompt)
        check("[6d] preview prompt labels Image3 with [card]",
              lambda: "Image3 [card]" in preview_prompt)
        check("[6e] preview prompt includes design rules",
              lambda: "Design rules" in preview_prompt)
        check("[6f] preview prompt includes style anchor",
              lambda: "Style:" in preview_prompt and "Inter" in preview_prompt)
        check("[6g] preview prompt echoes user request",
              lambda: "Dashboard with sidebar" in preview_prompt)

        # ---- build_prompt: preview with empty refs ----------------------
        empty_body = dict(FULL_STYLE)
        empty_body["name"] = "text-only"
        empty_body["image_refs"] = []
        empty_dir = write_fixture(tmp, empty_body)
        empty_loaded = style_loader.load_style(empty_dir)

        text_prompt, text_imgs = style_loader.build_prompt(
            empty_loaded,
            user_prompt="Something else",
            phase="preview",
        )
        check("[7a] preview with empty image_refs -> 0 images",
              lambda: text_imgs == [])
        check("[7b] preview with empty refs -> no [type] header",
              lambda: "Image1" not in text_prompt)
        check("[7c] preview with empty refs still includes rules + anchor",
              lambda: "Design rules" in text_prompt and "Style:" in text_prompt)

        # ---- build_prompt: layer phase ----------------------------------
        fake_preview = tmp / "preview.png"
        fake_preview.write_bytes(b"\x89PNG\r\n\x1a\n")

        layer_prompt, layer_imgs = style_loader.build_prompt(
            loaded,
            user_prompt="Extract ONLY the submit_button. Transparent background.",
            phase="layer",
            control_type="button",
            base_image=fake_preview,
        )
        check("[8a] layer phase passes base_image + 1 matching ref",
              lambda: len(layer_imgs) == 2
                      and layer_imgs[0] == fake_preview
                      and layer_imgs[1].name == "button.png")
        check("[8b] layer prompt: Image1 has no [type] tag (base = preview)",
              lambda: "Image1:" in layer_prompt and "Image1 [" not in layer_prompt)
        check("[8c] layer prompt: Image2 labeled [button]",
              lambda: "Image2 [button]" in layer_prompt)

        # control_type=None: no refs attached
        layer_none_prompt, layer_none_imgs = style_loader.build_prompt(
            loaded,
            user_prompt="Extract ONLY the main_chart.",
            phase="layer",
            control_type=None,
            base_image=fake_preview,
        )
        check("[8d] layer phase + control_type=None -> only base image",
              lambda: len(layer_none_imgs) == 1
                      and layer_none_imgs[0] == fake_preview)
        check("[8e] layer phase + control_type=None -> no [type] headers",
              lambda: "[button]" not in layer_none_prompt
                      and "[card]" not in layer_none_prompt
                      and "[sidebar]" not in layer_none_prompt)

        # ---- build_prompt: variant phase --------------------------------
        fake_layer = tmp / "submit_button.png"
        fake_layer.write_bytes(b"\x89PNG\r\n\x1a\n")

        variant_prompt, variant_imgs = style_loader.build_prompt(
            loaded,
            user_prompt="Generate hover variant.",
            phase="variant",
            control_type="button",
            base_image=fake_layer,
            rule_kinds=("interaction",),
        )
        check("[9a] variant phase: base + matching ref",
              lambda: len(variant_imgs) == 2 and variant_imgs[1].name == "button.png")
        check("[9b] variant prompt: Image1 DOES carry [button] tag",
              lambda: "Image1 [button]" in variant_prompt)
        check("[9c] variant prompt filters rules to interaction only",
              lambda: "Hover state lifts shadow" in variant_prompt
                      and "8px grid" not in variant_prompt.split("Design rules")[1].split("Style:")[0])

        # ---- validate: bad style detection ------------------------------
        bad_body = dict(FULL_STYLE)
        bad_body["name"] = "bad-missing-version"
        bad_body.pop("schema_version", None)
        bad_dir = write_fixture(tmp, bad_body)
        try:
            style_loader.load_style(bad_dir)
            errs_missing_ver: list[str] = []
        except Exception as e:
            errs_missing_ver = [str(e)]
        check("[10a] missing schema_version raises StyleError on load",
              lambda: len(errs_missing_ver) > 0)

        bad_ref_body = dict(FULL_STYLE)
        bad_ref_body["name"] = "bad-missing-image"
        bad_ref_body["image_refs"] = [
            {"path": "nope.png", "role": "missing", "use_for": ["button"]},
        ]
        bad_ref_dir = tmp / bad_ref_body["name"]
        bad_ref_dir.mkdir(parents=True, exist_ok=True)
        (bad_ref_dir / "style.json").write_text(json.dumps(bad_ref_body), encoding="utf-8")
        # Manually invoke validate after loading skeleton dict
        try:
            style_loader.load_style(bad_ref_dir)
            check("[10b] missing image_refs path causes load_style to fail",
                  lambda: False, "load_style accepted missing image file")
        except Exception:
            check("[10b] missing image_refs path causes load_style to fail",
                  lambda: True)

        bad_useforbody = dict(FULL_STYLE)
        bad_useforbody["name"] = "bad-empty-usefor"
        bad_useforbody["image_refs"] = [
            {"path": "button.png", "role": "x", "use_for": []},
        ]
        bad_uf_dir = write_fixture(tmp, bad_useforbody)
        try:
            style_loader.load_style(bad_uf_dir)
            check("[10c] empty use_for fails validation",
                  lambda: False, "empty use_for was accepted")
        except Exception:
            check("[10c] empty use_for fails validation",
                  lambda: True)

        # ---- resolve precedence -----------------------------------------
        # explicit absolute path wins
        explicit = style_loader.resolve(str(style_dir), workspace_root=tmp)
        check("[11a] resolve(absolute_path) returns that path",
              lambda: explicit == style_dir)

        # workspace lookup: workspace_root/styles/{name}/
        ws_root = tmp / "ws"
        ws_styles = ws_root / "styles" / "myname"
        ws_styles.mkdir(parents=True)
        (ws_styles / "style.json").write_text(json.dumps({
            "schema_version": "1.0", "name": "myname", "image_refs": [],
        }), encoding="utf-8")
        found = style_loader.resolve("myname", workspace_root=ws_root)
        check("[11b] resolve('name') finds under workspace styles dir",
              lambda: found == ws_styles)

        # missing -> error
        try:
            style_loader.resolve("definitely-not-real-style-name", workspace_root=ws_root)
            check("[11c] resolve(unknown) raises FileNotFoundError",
                  lambda: False, "did not raise")
        except FileNotFoundError:
            check("[11c] resolve(unknown) raises FileNotFoundError",
                  lambda: True)
        except Exception as e:
            check("[11c] resolve(unknown) raises FileNotFoundError",
                  lambda: False, f"raised {type(e).__name__}")

        # ---- image-count hard cap on preview ----------------------------
        many = dict(FULL_STYLE)
        many["name"] = "many-refs"
        many["image_refs"] = [
            {"path": f"r{i}.png", "role": f"ref {i}", "use_for": ["card"]}
            for i in range(7)
        ]
        many_dir = write_fixture(tmp, many)
        many_loaded = style_loader.load_style(many_dir)
        _, p_imgs = style_loader.build_prompt(
            many_loaded, user_prompt="test", phase="preview",
        )
        check("[12a] preview phase truncates to IMAGE_HARD_CAP (5)",
              lambda: len(p_imgs) == style_loader.IMAGE_HARD_CAP)

        # layer phase: base reserves 1 slot
        _, l_imgs = style_loader.build_prompt(
            many_loaded, user_prompt="test", phase="layer",
            control_type="card", base_image=fake_preview,
        )
        check("[12b] layer phase: base + up to 4 refs (cap=5)",
              lambda: len(l_imgs) <= style_loader.IMAGE_HARD_CAP
                      and len(l_imgs) == 5)

        # ---- preview + base_image (wireframe mode) ----------------------
        wireframe = tmp / "wireframe.png"
        wireframe.write_bytes(b"\x89PNG\r\n\x1a\n")
        pw_prompt, pw_imgs = style_loader.build_prompt(
            loaded, user_prompt="test", phase="preview",
            base_image=wireframe,
        )
        check("[13a] preview + base_image: base is Image1",
              lambda: len(pw_imgs) == 4
                      and pw_imgs[0] == wireframe
                      and pw_imgs[1].name == "button.png")
        check("[13b] preview + base_image: Image1 has no [type] tag",
              lambda: "Image1: Reference draft" in pw_prompt
                      and "Image1 [" not in pw_prompt)
        check("[13c] preview + base_image: Image2 labeled [button]",
              lambda: "Image2 [button]" in pw_prompt)

        # preview + base_image with many refs: base reserves 1 slot
        _, pw_many = style_loader.build_prompt(
            many_loaded, user_prompt="test", phase="preview",
            base_image=wireframe,
        )
        check("[13d] preview + base_image truncates refs to cap-1",
              lambda: len(pw_many) == style_loader.IMAGE_HARD_CAP)

        # ---- summary -----------------------------------------------------
        failed = [(n, h) for (n, ok, h) in results if not ok]
        for name, ok, hint in results:
            print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  -- {hint}" if hint else ""))
        print()
        if failed:
            print(f"{len(failed)} test(s) failed:")
            for name, hint in failed:
                print(f"  - {name}: {hint}")
            return 1
        print(f"all {len(results)} style_loader tests PASS")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
