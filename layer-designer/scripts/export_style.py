#!/usr/bin/env python3
"""
export_style.py — Create or extend Style Library entries.

Subcommands:

    from-llm-draft  Persist a complete style.json drafted by an LLM (with
                    optional source-image copy), validated before write.
                    This is the recommended path when the LLM has just
                    extracted tokens from user-provided reference images.
    from-project    Materialize a style from a completed project's
                    layer_plan.json (captures style_anchor and copies
                    user-specified reference images).
    manual          Write an empty style.json template for hand-editing.
    add-reference   Append a reference image (and image_refs entry) to an
                    existing style.

Output layout (under workspace/styles/{name}/):

    style.json
    button.png   sidebar.png   card.png   ...    (any user-copied refs)

This module never makes vision-LLM calls. The vision-extraction step
lives in the calling agent (see `references/style-generation.md`); this
script only handles file persistence and post-write validation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_script_dir = Path(__file__).parent.resolve()
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from path_manager import PathManager
import style_loader


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

_EMPTY_TEMPLATE: dict = {
    "schema_version": "1.0",
    "name": "",
    "description": "",
    "image_refs": [],
    "palette": {"role": {}, "semantic": {}},
    "typography": {},
    "spacing": {},
    "shape": {},
    "elevation": {},
    "motif": {"tags": []},
    "rules": {},
    "style_anchor_override": None,
}

_SPEC_PROMPT_TEMPLATE: str = (
    "Generate a comprehensive UI design specification reference sheet based on the style described below.\n\n"
    "The sheet must clearly display:\n"
    "1. COLOR PALETTE: Show all primary colors as labeled rectangular swatches. "
    "Include primary, secondary, surface, background, and text colors with their hex values visible.\n"
    "2. TYPOGRAPHY: Display the font family name with placeholder sample text (e.g. \"Sample Text\", \"Heading Example\") "
    "showing heading and body sizes. Do NOT use any real words, brand names, or meaningful sentences.\n"
    "3. BASE CONTROL SHAPES: Draw a standard button, a card/container, and an input field "
    "with the exact corner radius, border width, and shadow style specified. "
    "Use neutral placeholder text (e.g. \"Label\", \"Button\") inside controls — never real content.\n"
    "4. MOTIF/VIBE: The overall visual feel should match the described style tags.\n\n"
    "Style: {anchor}\n\n"
    "Design Rules:\n{rules}\n\n"
    "Generate this as a clean, professional design reference card on a neutral light gray background. "
    "All elements must be clearly separated, labeled, and easy to read. "
    "This will be used as a visual specification for generating consistent UI components."
)


def _parse_copy_reference(spec: str) -> dict:
    """
    Parse a `--copy-references` spec for `from-project`.

    Format: ``source_path:role:use_for_first:dest_filename``

    Parsed right-to-left so the source path may contain ':' (e.g. Windows
    drive letters like ``C:\\foo.png``). The other three fields must NOT
    contain ':'. Quote the spec in your shell if `role` contains spaces.
    """
    parts = spec.rsplit(":", 3)
    if len(parts) != 4:
        raise ValueError(
            f"--copy-references must be exactly 4 colon-separated fields "
            f"'source:role:use_for_first:dest_filename', got '{spec}'"
        )
    source, role, use_for_first, dest_filename = (p.strip() for p in parts)
    if not source or not role or not use_for_first or not dest_filename:
        raise ValueError(
            f"--copy-references fields must all be non-empty: '{spec}'"
        )
    return {
        "source": source,
        "role": role,
        "use_for_first": use_for_first,
        "dest_filename": dest_filename,
    }


def _parse_simple_copy_reference(spec: str) -> dict:
    """
    Parse a `--copy-references` spec for `from-llm-draft`.

    Format: ``source_path:dest_filename``

    Parsed right-to-left so the source path may contain ':' (Windows
    drive letters). The destination filename must NOT contain ':'.
    Role / use_for live inside the LLM-drafted ``image_refs`` block, so
    this 2-field form only describes the file copy.
    """
    parts = spec.rsplit(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"--copy-references must be exactly 2 colon-separated fields "
            f"'source:dest_filename', got '{spec}'"
        )
    source, dest_filename = (p.strip() for p in parts)
    if not source or not dest_filename:
        raise ValueError(
            f"--copy-references fields must all be non-empty: '{spec}'"
        )
    return {"source": source, "dest_filename": dest_filename}


def _build_spec_prompt(style: dict) -> str:
    """Fill the spec template with derived anchor and rules text."""
    anchor = style_loader.derive_anchor(style)
    rules_text = style_loader.rules_to_prompt_text(style)
    return _SPEC_PROMPT_TEMPLATE.format(anchor=anchor, rules=rules_text or "No additional design rules.")


def _generate_spec_image(
    style: dict,
    style_dir: Path,
    config_path: str | None,
    spec_size: str,
    spec_quality: str,
    copied_refs: list[str],
) -> Path:
    """
    Generate the style specification sheet image.

    Uses `generate_image.py edit` when reference images exist (copied_refs),
    otherwise `generate` (text-to-image). Returns the path to the generated
    spec.png on success, raises RuntimeError on failure.
    """
    spec_path = style_dir / "spec.png"
    prompt = _build_spec_prompt(style)

    script = Path(__file__).parent / "generate_image.py"
    if copied_refs:
        cmd = [
            sys.executable, str(script),
            "edit",
            "--config", config_path or "",
            "--image",
            *[str(style_dir / r) for r in copied_refs],
            "--prompt", prompt,
            "--output", str(spec_path),
            "--size", spec_size,
            "--quality", spec_quality,
            "--phase", "preview",
        ]
    else:
        cmd = [
            sys.executable, str(script),
            "generate",
            "--config", config_path or "",
            "--prompt", prompt,
            "--output", str(spec_path),
            "--size", spec_size,
            "--quality", spec_quality,
            "--phase", "preview",
        ]

    # Remove empty --config so generate_image.py doesn't see it
    cmd = [c for c in cmd if c != ""]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Spec generation failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    if not spec_path.exists():
        raise RuntimeError(
            f"Spec generation reported success but {spec_path} was not created."
        )
    return spec_path


def _write_style_json(style_dir: Path, style: dict) -> Path:
    """Write style.json with stable formatting and return its path."""
    out = style_dir / "style.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(style, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out


def _ensure_style_dir(name: str, overwrite: bool) -> Path:
    """Create the styles/{name}/ folder, refusing to clobber unless asked."""
    style_dir = PathManager.get_styles_dir() / name
    if style_dir.exists():
        if not overwrite:
            print(
                f"[ERROR] Style '{name}' already exists at {style_dir}\n"
                f"        Use --overwrite to replace, or `add-reference` to extend."
            )
            sys.exit(1)
        # We only delete style.json + previously-referenced files; refuse if
        # there are other unrelated files in there to avoid surprises.
        # For simplicity in v1, we overwrite style.json in place; the user
        # is expected to manage stale reference files manually.
    style_dir.mkdir(parents=True, exist_ok=True)
    return style_dir


# ---------------------------------------------------------------------
# Subcommand: from-llm-draft
# ---------------------------------------------------------------------

def cmd_from_llm_draft(args: argparse.Namespace) -> None:
    # 1. Read the LLM-drafted JSON (stdin or file)
    if args.json_stdin:
        raw = sys.stdin.read()
        source_label = "<stdin>"
    else:
        json_path = Path(args.json_file).resolve()
        if not json_path.exists():
            print(f"[ERROR] --json-file not found: {json_path}")
            sys.exit(1)
        with json_path.open(encoding="utf-8") as f:
            raw = f.read()
        source_label = str(json_path)

    if not raw.strip():
        print(f"[ERROR] Empty draft JSON from {source_label}")
        sys.exit(1)

    try:
        style = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in {source_label}: {e}")
        sys.exit(1)

    if not isinstance(style, dict):
        print(
            f"[ERROR] Top-level JSON must be an object, "
            f"got {type(style).__name__} from {source_label}"
        )
        sys.exit(1)

    # `--name` is authoritative for the folder; override whatever the LLM put.
    style["name"] = args.name
    style.setdefault("schema_version", "1.0")

    # 2. Create the style folder
    style_dir = _ensure_style_dir(args.name, args.overwrite)

    # 3. Copy referenced images (if any)
    copied: list[str] = []
    for spec in (args.copy_references or []):
        ref = _parse_simple_copy_reference(spec)
        source = Path(ref["source"]).resolve()
        if not source.exists():
            print(f"[ERROR] Source not found: {source}")
            sys.exit(1)
        dest = style_dir / ref["dest_filename"]
        shutil.copy2(source, dest)
        copied.append(ref["dest_filename"])
        print(f"[OK] Copied reference: {source.name} -> {dest.name}")

    # 4. Optional: generate spec sheet image
    if getattr(args, "generate_spec", False):
        spec_size = getattr(args, "spec_size", "2048x2048") or "2048x2048"
        spec_quality = getattr(args, "spec_quality", "medium") or "medium"
        try:
            spec_path = _generate_spec_image(
                style=style,
                style_dir=style_dir,
                config_path=getattr(args, "config", None),
                spec_size=spec_size,
                spec_quality=spec_quality,
                copied_refs=copied,
            )
            print(f"[OK] Generated spec sheet: {spec_path}")
        except RuntimeError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

        # Replace image_refs with spec-only entry
        style["image_refs"] = [
            {
                "path": "spec.png",
                "role": "UI design specification reference sheet",
                "use_for": ["*"],
            }
        ]

        # Remove original reference images unless user asked to keep them
        if not getattr(args, "keep_original_refs", False):
            for orig in copied:
                orig_path = style_dir / orig
                if orig_path.exists():
                    orig_path.unlink()
                    print(f"[OK] Removed original ref: {orig}")
            copied = []

    # 5. Pre-check: every image_refs[*].path must exist under style_dir
    image_refs = style.get("image_refs") or []
    missing: list[str] = []
    for ref in image_refs:
        ref_path = (ref.get("path") or "").strip()
        if not ref_path:
            continue
        if not (style_dir / ref_path).exists():
            missing.append(ref_path)
    if missing:
        print(
            f"[ERROR] style.image_refs references images not present in {style_dir}:\n"
            f"        missing: {missing}\n"
            f"        Either pass --copy-references 'src:dest' for each missing file,\n"
            f"        or remove the entry from the draft image_refs."
        )
        sys.exit(1)

    # 6. Write style.json
    out = _write_style_json(style_dir, style)

    # 7. Post-write validation via style_loader (authoritative).
    try:
        loaded = style_loader.load_style(style_dir)
    except Exception as e:
        print(
            f"[ERROR] style_loader.load_style rejected the written file:\n"
            f"        {type(e).__name__}: {e}\n"
            f"        File left on disk at {out} for inspection."
        )
        sys.exit(1)

    errs = style_loader.validate(loaded, style_dir)
    if errs:
        print(f"[ERROR] Written style.json failed validation:")
        for err in errs:
            print(f"  - {err}")
        print(f"        File left on disk at {out} for inspection.")
        sys.exit(1)

    # 7. Report success
    print(f"\n[OK] Wrote LLM-drafted style: {out}")
    if getattr(args, "generate_spec", False):
        print(f"  - spec sheet generated (spec.png, use_for='*')")
    if copied:
        print(f"  - {len(copied)} reference image(s) copied: {copied}")
    print(f"  - image_refs entries: {len(image_refs)}")
    try:
        cts = style_loader.list_control_types(loaded)
    except Exception:
        cts = []
    if cts:
        print(f"  - control_types covered: {cts}")
    print(f"  - schema_version: {style.get('schema_version', '?')}")
    print(f"  - derived anchor: {style_loader.derive_anchor(loaded)}")


# ---------------------------------------------------------------------
# Subcommand: manual
# ---------------------------------------------------------------------

def cmd_manual(args: argparse.Namespace) -> None:
    style_dir = _ensure_style_dir(args.name, args.overwrite)

    style = json.loads(json.dumps(_EMPTY_TEMPLATE))  # deep copy
    style["name"] = args.name
    style["description"] = args.description

    out = _write_style_json(style_dir, style)
    print(f"[OK] Created empty style: {out}")
    print("\nNext steps:")
    print(f"  - Edit {out} to fill palette / typography / shape / motif / rules")
    print(f"  - Add reference images with:")
    print(
        f"      python scripts/export_style.py add-reference \\\n"
        f"        --style {args.name} --image <path> \\\n"
        f"        --role '<description>' --use-for <type>"
    )


# ---------------------------------------------------------------------
# Subcommand: from-project
# ---------------------------------------------------------------------

def cmd_from_project(args: argparse.Namespace) -> None:
    pm = PathManager(args.project, config_path=args.config)

    layer_plan_path = pm.get_layer_plan_path()
    if not layer_plan_path.exists():
        print(f"[ERROR] layer_plan.json not found: {layer_plan_path}")
        print("        Run Phase 2 (Confirmation) on the project first.")
        sys.exit(1)
    with layer_plan_path.open(encoding="utf-8") as f:
        layer_plan = json.load(f)

    style_anchor = (layer_plan.get("style_anchor") or "").strip()

    # Locate a derived_from preview to record provenance (best-effort).
    derived_from: str | None = None
    preview_dir = pm.get_phase_dir("requirements") / "previews"
    if preview_dir.exists():
        previews = sorted(preview_dir.glob("preview_*.png"))
        if previews:
            derived_from = str(previews[-1])

    style_dir = _ensure_style_dir(args.name, args.overwrite)

    # Process --copy-references first so image_refs is populated when we
    # validate the result.
    image_refs: list[dict] = []
    if args.copy_references:
        for spec in args.copy_references:
            ref = _parse_copy_reference(spec)
            source = Path(ref["source"]).resolve()
            if not source.exists():
                print(f"[ERROR] Source not found: {source}")
                sys.exit(1)
            dest = style_dir / ref["dest_filename"]
            shutil.copy2(source, dest)
            image_refs.append({
                "path": ref["dest_filename"],
                "role": ref["role"],
                "use_for": [ref["use_for_first"]],
            })
            print(f"[OK] Copied reference: {source.name} -> {dest.name}")

    style = json.loads(json.dumps(_EMPTY_TEMPLATE))
    style["name"] = args.name
    style["description"] = args.description
    if derived_from:
        style["derived_from"] = derived_from
    if image_refs:
        style["image_refs"] = image_refs
    if style_anchor:
        style["style_anchor_override"] = style_anchor

    out = _write_style_json(style_dir, style)
    print(f"\n[OK] Wrote style: {out}")
    if style_anchor:
        print(f"  - Captured Phase 2 style_anchor as `style_anchor_override`")
        print(f"  - Anchor: {style_anchor}")
    print("\nNext steps:")
    print(f"  - Edit {out} to fill structured palette / typography / rules")
    if image_refs:
        print(f"  - {len(image_refs)} reference image(s) added; expand `use_for` "
              f"arrays in style.json to cover more control types if needed")
    else:
        print(f"  - Add reference images with `export_style.py add-reference`")


# ---------------------------------------------------------------------
# Subcommand: add-reference
# ---------------------------------------------------------------------

def cmd_add_reference(args: argparse.Namespace) -> None:
    try:
        style_dir = PathManager.resolve_style(args.style)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    source = Path(args.image).resolve()
    if not source.exists():
        print(f"[ERROR] Image not found: {source}")
        sys.exit(1)

    dest_name = args.rename or source.name
    dest = style_dir / dest_name
    if dest.exists() and not args.overwrite:
        print(
            f"[ERROR] Reference already exists: {dest}\n"
            f"        Use --overwrite to replace, or pass --rename <newname>."
        )
        sys.exit(1)

    style_json = style_dir / "style.json"
    if not style_json.exists():
        print(f"[ERROR] style.json missing in {style_dir}; cannot append reference.")
        sys.exit(1)
    with style_json.open(encoding="utf-8") as f:
        style = json.load(f)

    # Validate use_for (strip empties, dedupe in declaration order)
    use_for_clean: list[str] = []
    seen: dict[str, None] = {}
    for t in args.use_for:
        t2 = t.strip()
        if t2 and t2 not in seen:
            seen[t2] = None
            use_for_clean.append(t2)
    if not use_for_clean:
        print("[ERROR] --use-for must provide at least one non-empty control type.")
        sys.exit(1)

    shutil.copy2(source, dest)

    style.setdefault("image_refs", [])
    # If we're overwriting and the same dest already had an entry, replace it.
    existing_idx = None
    for i, ref in enumerate(style["image_refs"]):
        if ref.get("path") == dest_name:
            existing_idx = i
            break
    new_entry = {
        "path": dest_name,
        "role": args.role,
        "use_for": use_for_clean,
    }
    if existing_idx is not None:
        style["image_refs"][existing_idx] = new_entry
        action = "Updated"
    else:
        style["image_refs"].append(new_entry)
        action = "Added"

    _write_style_json(style_dir, style)
    print(f"[OK] {action} reference: {dest_name}")
    print(f"  - role: {args.role}")
    print(f"  - use_for: {use_for_clean}")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export Style — create or extend an entry in the workspace "
            "Style Library (workspace/styles/{name}/)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # from-llm-draft
    p_ld = sub.add_parser(
        "from-llm-draft",
        help="Persist an LLM-drafted style.json + copy referenced images in one shot.",
    )
    p_ld.add_argument(
        "--name", required=True,
        help="Style name (folder under styles/). Overrides any `name` in the draft.",
    )
    src_group = p_ld.add_mutually_exclusive_group(required=True)
    src_group.add_argument(
        "--json-stdin", action="store_true",
        help="Read the draft style.json from stdin.",
    )
    src_group.add_argument(
        "--json-file",
        help="Path to a file containing the draft style.json.",
    )
    p_ld.add_argument(
        "--copy-references", action="append", default=[],
        help=(
            "Copy a reference image into the style. Format: "
            "'source_path:dest_filename'. Repeat for each ref. Every "
            "`image_refs[*].path` in the draft must either already live "
            "inside the style folder or be supplied here."
        ),
    )
    p_ld.add_argument(
        "--overwrite", action="store_true",
        help="Replace style.json if the style already exists.",
    )
    p_ld.add_argument(
        "--config",
        help="Path to config.json (required for --generate-spec).",
    )
    p_ld.add_argument(
        "--generate-spec", action="store_true",
        help=(
            "Generate a unified UI specification sheet image from the style "
            "and use it as the sole reference (use_for='*'). When original "
            "reference images are present they are used as edit inputs; "
            "otherwise text-to-image is used. Original refs are removed "
            "unless --keep-original-refs is set."
        ),
    )
    p_ld.add_argument(
        "--keep-original-refs", action="store_true",
        help="When --generate-spec is used, retain the original reference images.",
    )
    p_ld.add_argument(
        "--spec-size", default="2048x2048",
        help="Size for the spec sheet image (default: 2048x2048).",
    )
    p_ld.add_argument(
        "--spec-quality", default="medium",
        choices=["low", "medium", "high"],
        help="Quality for the spec sheet image (default: medium).",
    )
    p_ld.set_defaults(func=cmd_from_llm_draft)

    # from-project
    p_fp = sub.add_parser(
        "from-project",
        help="Materialize a style from a completed project's layer_plan.json.",
    )
    p_fp.add_argument("--config", required=True, help="Path to config.json")
    p_fp.add_argument("--project", "-p", required=True, help="Project name")
    p_fp.add_argument("--name", required=True, help="Style name (folder under styles/)")
    p_fp.add_argument("--description", default="", help="Free-text description")
    p_fp.add_argument(
        "--copy-references", action="append", default=[],
        help=(
            "Copy a reference image into the style. Format: "
            "'source_path:role:use_for_first:dest_filename'. "
            "Repeat for multiple references."
        ),
    )
    p_fp.add_argument("--overwrite", action="store_true",
                      help="Replace style.json if the style already exists.")
    p_fp.set_defaults(func=cmd_from_project)

    # manual
    p_m = sub.add_parser(
        "manual",
        help="Write an empty style.json template for hand-editing.",
    )
    p_m.add_argument("--name", required=True, help="Style name (folder under styles/)")
    p_m.add_argument("--description", default="", help="Free-text description")
    p_m.add_argument("--overwrite", action="store_true",
                     help="Replace style.json if the style already exists.")
    p_m.set_defaults(func=cmd_manual)

    # add-reference
    p_ar = sub.add_parser(
        "add-reference",
        help="Append a reference image to an existing style.",
    )
    p_ar.add_argument("--style", required=True,
                      help="Existing style name (or explicit path).")
    p_ar.add_argument("--image", required=True, help="Source image path.")
    p_ar.add_argument("--role", required=True,
                      help="Description string used in the prompt header.")
    p_ar.add_argument(
        "--use-for", action="append", required=True, default=[],
        help="Control type this reference applies to (repeat for multiple).",
    )
    p_ar.add_argument("--rename",
                      help="Rename to this filename inside the style folder.")
    p_ar.add_argument("--overwrite", action="store_true",
                      help="Replace if a reference with the same filename exists.")
    p_ar.set_defaults(func=cmd_add_reference)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
