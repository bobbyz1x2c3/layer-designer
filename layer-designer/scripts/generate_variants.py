#!/usr/bin/env python3
"""
Generate state variants for UI controls based on a base layer image.
Uses image-to-image editing with state-specific prompts.

Workflow phase where this script is invoked:
- Phase 8 (Control State Variants): batch-generate hover/active/disabled/etc.
  state variants for UI controls from a base layer image.

Usage:
    python generate_variants.py --config ../config.json \
        --image button_normal.png --control-type button \
        --states hover active disabled --output-dir ./variants \
        --size 1024x1024 --quality high
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from config_loader import load_config, get_api_config, get_variants_config


# Default state prompt templates per control type
DEFAULT_STATE_PROMPTS = {
    "button": {
        "hover": "Same button style, but with a subtle highlight/glow effect on hover state, slightly brighter, mouse cursor hovering over it",
        "active": "Same button style, but pressed/clicked state, slightly darker and pushed-in effect, active state",
        "disabled": "Same button style, but grayed out and muted, disabled state, lower opacity look, non-interactive appearance",
        "focused": "Same button style, but with a visible focus ring/outline indicating keyboard focus, focused state",
    },
    "input": {
        "hover": "Same input field, but with hover state styling, subtle border highlight",
        "active": "Same input field, but focused/active state with cursor blinking, active text input appearance",
        "disabled": "Same input field, but disabled state, grayed out, non-editable appearance",
        "error": "Same input field, but with error state styling, red border or warning indicator",
    },
    "checkbox": {
        "checked": "Same checkbox, but in checked/selected state with a visible checkmark or tick inside",
        "unchecked": "Same checkbox, but in empty/unchecked state",
        "indeterminate": "Same checkbox, but in indeterminate/partial state with a dash or minus inside",
        "disabled": "Same checkbox, but disabled and grayed out state",
    },
    "toggle": {
        "on": "Same toggle switch, but in ON/active state, switched to the right, active color",
        "off": "Same toggle switch, but in OFF/inactive state, switched to the left, inactive gray color",
        "disabled": "Same toggle switch, but disabled state, muted colors",
    },
    "generic": {
        "hover": "Same element, but with hover/interaction state, slightly elevated or highlighted",
        "active": "Same element, but active/pressed state",
        "disabled": "Same element, but disabled/inactive state, muted and grayed out",
        "selected": "Same element, but selected/chosen state with visible selection indicator",
    },
}


def get_state_prompt(control_type: str, state: str, custom_prompts: dict | None = None) -> str:
    """Get the prompt for a specific control state."""
    if custom_prompts and state in custom_prompts:
        return custom_prompts[state]
    prompts = DEFAULT_STATE_PROMPTS.get(control_type, DEFAULT_STATE_PROMPTS["generic"])
    return prompts.get(state, f"Same element, but in {state} state")


def generate_variant(image_path: str, prompt: str, output_path: str,
                     size: str = "1024x1024", quality: str = "high", model: str = "gpt-image-2",
                     config_path: str | None = None,
                     style: str | None = None,
                     style_from: str | None = None,
                     control_type: str | None = None):
    """Generate a single variant using the generate_image.py edit command."""
    script_dir = Path(__file__).parent
    gen_script = script_dir / "generate_image.py"

    cmd = [
        sys.executable, str(gen_script),
        "edit",
        "--image", image_path,
        "--prompt", prompt,
        "--output", output_path,
        "--size", size,
        "--quality", quality,
        "--model", model,
    ]
    if config_path:
        cmd.extend(["--config", config_path])
    if style_from:
        cmd.extend(["--style-from", style_from, "--phase", "variant"])
        if control_type:
            cmd.extend(["--control-type", control_type])
    elif style:
        cmd.extend(["--style", style, "--phase", "variant"])
        if control_type:
            cmd.extend(["--control-type", control_type])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Variant generation failed: {result.stderr}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate UI control state variants")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--image", "-i", required=True, help="Base control layer image path")
    parser.add_argument("--control-type", "-t", default=None,
                        help=(
                            "Type of UI control. Built-in prompt templates: "
                            f"{sorted(DEFAULT_STATE_PROMPTS)}. "
                            "Other values are accepted (e.g. style-defined "
                            "types like 'card'/'sidebar') and fall back to "
                            "the 'generic' prompt template; the value is "
                            "still forwarded to generate_image.py so the "
                            "style library can select matching refs."
                        ))
    parser.add_argument("--states", "-s", nargs="+", default=None,
                        help="States to generate (e.g., hover active disabled)")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory")
    parser.add_argument("--size", default="1024x1024", help="Image size")
    parser.add_argument("--quality", default="high", choices=["low", "medium", "high"],
                        help="Generation quality")
    parser.add_argument("--model", default="gpt-image-2", help="Model name")
    parser.add_argument("--custom-prompts", help="JSON file with custom state prompts")
    style_group = parser.add_mutually_exclusive_group()
    style_group.add_argument("--style", default=None,
                             help="Style library name (resolved under workspace/styles/{name}/).")
    style_group.add_argument("--style-from", default=None,
                             help="Explicit path to a style directory (containing style.json).")
    args = parser.parse_args()

    # Apply config defaults where CLI args not provided
    if args.config:
        try:
            cfg = load_config(args.config)
            vcfg = get_variants_config(cfg)
            acfg = get_api_config(cfg)
            if args.control_type is None:
                args.control_type = vcfg.get("default_control_type", "generic")
            if args.states is None:
                args.states = vcfg.get("default_states", ["hover", "active", "disabled"])
            if args.model == "gpt-image-2":
                args.model = acfg.get("default_model", "gpt-image-2")
                phase_models = acfg.get("phase_models") or {}
                phase_pick = phase_models.get("variant")
                if phase_pick:
                    args.model = phase_pick
        except Exception:
            if args.control_type is None:
                args.control_type = "generic"
            if args.states is None:
                args.states = ["hover", "active", "disabled"]
    else:
        if args.control_type is None:
            args.control_type = "generic"
        if args.states is None:
            args.states = ["hover", "active", "disabled"]

    # Load custom prompts if provided
    custom_prompts = None
    if args.custom_prompts:
        with open(args.custom_prompts, "r", encoding="utf-8") as f:
            custom_prompts = json.load(f)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(args.image).stem
    results = {}

    for state in args.states:
        prompt = get_state_prompt(args.control_type, state, custom_prompts)
        output_path = str(output_dir / f"{base_name}_{state}.png")
        try:
            generate_variant(
                image_path=args.image,
                prompt=prompt,
                output_path=output_path,
                size=args.size,
                quality=args.quality,
                model=args.model,
                config_path=args.config,
                style=args.style,
                style_from=args.style_from,
                control_type=args.control_type,
            )
            results[state] = output_path
            print(f"VARIANT [{state}]: {output_path}")
        except Exception as e:
            print(f"ERROR generating {state}: {e}", file=sys.stderr)
            results[state] = f"ERROR: {e}"

    # Resolve style metadata for manifest (consistent with style-library.md spec)
    style_info: dict | None = None
    if args.style or args.style_from:
        try:
            import style_loader
            style_dir = style_loader.resolve(args.style or args.style_from)
            style = style_loader.load_style(style_dir)
            style_info = {
                "name": style.get("name"),
                "schema_version": style.get("schema_version", "1.0"),
            }
            try:
                style_info["dir"] = str(style_dir.relative_to(Path.cwd()))
            except ValueError:
                style_info["dir"] = str(style_dir)
        except Exception:
            # Fallback: record what the CLI provided
            style_info = {
                "name": args.style,
                "dir": args.style_from,
            }

    # Write manifest
    manifest_path = output_dir / f"{base_name}_variants_manifest.json"
    manifest: dict = {
        "base_image": args.image,
        "control_type": args.control_type,
        "states": args.states,
        "results": results,
    }
    if style_info:
        manifest["style_ref"] = style_info
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"MANIFEST: {manifest_path}")


if __name__ == "__main__":
    main()
