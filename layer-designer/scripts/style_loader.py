#!/usr/bin/env python3
"""
Style Library loader and prompt composer for the Layer Designer workflow.

A "style" is a workspace-level reusable design specification stored under
{workspace}/styles/{name}/style.json (schema v1.0). The style folder may
also contain reference images, each pinned to a list of control types via
`image_refs[*].use_for`.

This module is the single entry point for everything that consumes a style:

    - load_style(style_dir)              : read + validate + resolve abs paths
    - validate(style, style_dir)         : explicit validator (returns errors)
    - derive_anchor(style)               : flatten to free-text style_anchor
    - rules_to_prompt_text(style, kinds) : pretty-print rules sections
    - list_control_types(style)          : enumerate Phase 2 control_type values
    - select_image_refs(style, ct)       : filter refs by control_type
    - build_prompt(style, ...)           : compose the final prompt + image list
    - resolve(name_or_path)              : workspace-aware style lookup

The build_prompt() function is the canonical way to add style context to a
generation call. It returns (final_prompt_str, image_paths_list); the caller
forwards the image list to `generate_image.py edit --image ...`.

The image hard cap is 5 (enforced by `generate_image.py edit`). When the
style + base image would exceed that, image_refs are truncated in declaration
order; a notice is appended to the prompt so the model is aware.

This module performs ONLY data-side composition. It does not call the image
generation API itself.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION_CURRENT = "1.0"
SCHEMA_VERSION_MAJOR = 1
IMAGE_HARD_CAP = 5  # generate_image.py edit caps image inputs at 5

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------

class StyleError(Exception):
    """Raised when a style cannot be loaded or fails validation."""


# ----------------------------------------------------------------------
# Loading + validation
# ----------------------------------------------------------------------

def load_style(style_dir: str | Path) -> dict[str, Any]:
    """
    Load and validate a style from a directory.

    Args:
        style_dir: Path to the directory containing `style.json`. Reference
            image paths inside `image_refs` are resolved relative to this
            directory.

    Returns:
        A dict augmented with:
        - `__dir__`: absolute Path of the style folder
        - each `image_refs[i]['abs_path']`: absolute Path of the reference

    Raises:
        StyleError: when the file is missing, malformed, or fails validation.
    """
    style_dir = Path(style_dir).resolve()
    style_json = style_dir / "style.json"
    if not style_json.exists():
        raise StyleError(f"style.json not found in {style_dir}")

    try:
        with style_json.open("r", encoding="utf-8") as f:
            style = json.load(f)
    except json.JSONDecodeError as e:
        raise StyleError(f"Invalid JSON in {style_json}: {e}") from e

    if not isinstance(style, dict):
        raise StyleError(f"{style_json} must contain a JSON object at top level")

    schema_version = style.get("schema_version")
    if not schema_version:
        raise StyleError(f"{style_json}: missing required field `schema_version`")
    _check_schema_version(schema_version, str(style_json))

    style["__dir__"] = style_dir

    for ref in style.get("image_refs", []) or []:
        rel = ref.get("path")
        if rel:
            ref["abs_path"] = (style_dir / rel).resolve()

    errors = validate(style, style_dir)
    if errors:
        raise StyleError(
            f"Style validation failed for {style_json}:\n  - "
            + "\n  - ".join(errors)
        )

    return style


def _check_schema_version(version: str, source: str) -> None:
    """Enforce major version compatibility; warn on minor mismatch."""
    parts = str(version).split(".")
    try:
        major = int(parts[0])
    except (ValueError, IndexError) as e:
        raise StyleError(f"{source}: invalid schema_version '{version}'") from e

    if major != SCHEMA_VERSION_MAJOR:
        raise StyleError(
            f"{source}: unsupported schema_version '{version}' "
            f"(expected major version {SCHEMA_VERSION_MAJOR}.x)"
        )

    if version != SCHEMA_VERSION_CURRENT:
        # Same major, different minor — accept silently. The loader is
        # forward-compatible within a major version.
        pass


def validate(style: dict[str, Any], style_dir: str | Path) -> list[str]:
    """
    Validate a parsed style dict. Returns a list of error messages; an empty
    list means the style is valid.

    Args:
        style: Parsed style dict (after `load_style` has populated abs paths,
            or a fresh dict for pre-write checks).
        style_dir: Directory the style lives in (for resolving relative paths).
    """
    errors: list[str] = []
    style_dir = Path(style_dir)

    if not isinstance(style.get("schema_version"), str):
        errors.append("schema_version must be a string")

    name = style.get("name")
    if name is not None and not isinstance(name, str):
        errors.append("name must be a string")
    elif isinstance(name, str) and name.strip() and style_dir.name != name.strip():
        errors.append(
            f"name '{name}' does not match folder name '{style_dir.name}'"
        )

    image_refs = style.get("image_refs")
    if image_refs is not None:
        if not isinstance(image_refs, list):
            errors.append("image_refs must be an array")
        else:
            for i, ref in enumerate(image_refs):
                if not isinstance(ref, dict):
                    errors.append(f"image_refs[{i}] must be an object")
                    continue
                rel = ref.get("path")
                if not isinstance(rel, str) or not rel.strip():
                    errors.append(f"image_refs[{i}].path must be a non-empty string")
                else:
                    abs_path = (style_dir / rel).resolve()
                    if not abs_path.exists():
                        errors.append(
                            f"image_refs[{i}].path '{rel}' not found "
                            f"(resolved to {abs_path})"
                        )
                role = ref.get("role")
                if not isinstance(role, str) or not role.strip():
                    errors.append(f"image_refs[{i}].role must be a non-empty string")
                use_for = ref.get("use_for")
                if not isinstance(use_for, list) or not use_for:
                    errors.append(
                        f"image_refs[{i}].use_for must be a non-empty array of strings"
                    )
                elif not all(isinstance(t, str) and t.strip() for t in use_for):
                    errors.append(
                        f"image_refs[{i}].use_for must contain only non-empty strings"
                    )

    palette = style.get("palette")
    if palette is not None:
        if not isinstance(palette, dict):
            errors.append("palette must be an object")
        else:
            for group in ("role", "semantic"):
                group_val = palette.get(group)
                if group_val is None:
                    continue
                if not isinstance(group_val, dict):
                    errors.append(f"palette.{group} must be an object")
                    continue
                for token, color in group_val.items():
                    if not isinstance(color, str) or not _HEX_RE.match(color):
                        errors.append(
                            f"palette.{group}.{token} must be a hex color "
                            f"(#RRGGBB or #RRGGBBAA), got '{color}'"
                        )

    motif = style.get("motif")
    if motif is not None:
        if not isinstance(motif, dict):
            errors.append("motif must be an object")
        else:
            tags = motif.get("tags")
            if tags is not None and (
                not isinstance(tags, list)
                or not all(isinstance(t, str) for t in tags)
            ):
                errors.append("motif.tags must be an array of strings")

    rules = style.get("rules")
    if rules is not None:
        if not isinstance(rules, dict):
            errors.append("rules must be an object keyed by category")
        else:
            for kind, items in rules.items():
                if not isinstance(items, list) or not all(
                    isinstance(line, str) for line in items
                ):
                    errors.append(f"rules.{kind} must be an array of strings")

    return errors


# ----------------------------------------------------------------------
# Anchor derivation
# ----------------------------------------------------------------------

def derive_anchor(style: dict[str, Any]) -> str:
    """
    Derive a free-text `style_anchor` string from a structured style.

    Output format mirrors the Phase 2 anchor string used elsewhere in the
    workflow. Deterministic — same input always produces the same output.

    If `style.style_anchor_override` is a non-empty string, it replaces the
    derived output entirely.
    """
    override = style.get("style_anchor_override")
    if isinstance(override, str) and override.strip():
        return override.strip()

    parts: list[str] = []

    motif = style.get("motif") or {}
    tags = motif.get("tags") or []
    if isinstance(tags, list):
        tag_strs = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
        if tag_strs:
            parts.append(", ".join(tag_strs))

    palette = style.get("palette") or {}
    role_palette = palette.get("role") or {}
    semantic_palette = palette.get("semantic") or {}
    primary = role_palette.get("primary") or semantic_palette.get("brand")
    if isinstance(primary, str) and primary.strip():
        parts.append(f"primary {primary.strip()}")

    typography = style.get("typography") or {}
    font_family = typography.get("font_family")
    if isinstance(font_family, str) and font_family.strip():
        parts.append(f"{font_family.strip()} font")

    spacing = style.get("spacing") or {}
    base = spacing.get("base")
    if isinstance(base, (int, float)) and base > 0:
        parts.append(f"{int(base)}px grid")

    shape = style.get("shape") or {}
    button_radius = shape.get("button_radius")
    corner_md = shape.get("corner_radius_md")
    if isinstance(button_radius, (int, float)) and button_radius >= 0:
        parts.append(f"rounded {int(button_radius)}px buttons")
    elif isinstance(corner_md, (int, float)) and corner_md >= 0:
        parts.append(f"rounded {int(corner_md)}px corners")

    elevation = style.get("elevation") or {}
    preset = elevation.get("preset")
    if isinstance(preset, str) and preset.strip():
        parts.append(f"{preset.strip()} shadows")

    return ", ".join(parts)


# ----------------------------------------------------------------------
# Rules / control types
# ----------------------------------------------------------------------

def rules_to_prompt_text(
    style: dict[str, Any],
    kinds: Iterable[str] | None = None,
) -> str:
    """
    Render the rules dict as a multi-line block suitable for inclusion in a
    prompt. Returns an empty string when there are no applicable rules.

    Args:
        style: Loaded style.
        kinds: If provided, only include the listed categories (e.g.
            ['interaction']). Order is preserved. If None, includes all
            categories in their declared order.
    """
    rules = style.get("rules")
    if not isinstance(rules, dict) or not rules:
        return ""

    if kinds is None:
        selected = list(rules.keys())
    else:
        selected = [k for k in kinds if k in rules]

    lines: list[str] = []
    for kind in selected:
        items = rules.get(kind) or []
        for item in items:
            if isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")

    return "\n".join(lines)


def list_control_types(style: dict[str, Any]) -> list[str]:
    """
    Return the deduplicated union of `image_refs[*].use_for`, preserving the
    declaration order of the first occurrence of each value.

    This is the canonical enumeration of allowed `control_type` values for
    Phase 2 layer tagging when the style is in use.
    """
    seen: dict[str, None] = {}
    for ref in style.get("image_refs", []) or []:
        for t in ref.get("use_for", []) or []:
            if isinstance(t, str) and t.strip():
                seen.setdefault(t.strip(), None)
    return list(seen.keys())


def select_image_refs(
    style: dict[str, Any],
    control_type: str | None,
) -> list[dict[str, Any]]:
    """
    Return image_refs whose `use_for` includes the given control_type.

    Special values:
        - `"*"` returns all image_refs (preview phase).
        - `None` or empty string returns [] (layer/variant with no matching
          spec).

    Order follows the original `image_refs` declaration order.
    """
    refs = style.get("image_refs", []) or []
    if not control_type:
        return []
    if control_type == "*":
        return list(refs)
    out: list[dict[str, Any]] = []
    for ref in refs:
        use_for = ref.get("use_for") or []
        if control_type in use_for or "*" in use_for:
            out.append(ref)
    return out


# ----------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------

def _primary_tag(ref: dict[str, Any]) -> str:
    """Return the first use_for value, used as the inline tag in headers."""
    use_for = ref.get("use_for") or []
    for t in use_for:
        if isinstance(t, str) and t.strip():
            return t.strip()
    return ""


def _format_image_header(index: int, tag: str | None, role: str) -> str:
    """Format a single 'ImageN [tag]: role' header line."""
    if tag:
        return f"Image{index} [{tag}]: {role}"
    return f"Image{index}: {role}"


def build_prompt(
    style: dict[str, Any],
    user_prompt: str,
    phase: str,
    control_type: str | None = None,
    base_image: str | Path | None = None,
    base_image_role: str | None = None,
    rule_kinds: Iterable[str] | None = None,
) -> tuple[str, list[Path]]:
    """
    Compose the final prompt string and the list of image paths to pass to
    `generate_image.py edit --image ...`.

    Args:
        style: Loaded style dict (with __dir__ and abs_path on each ref).
        user_prompt: The caller's natural-language request.
        phase: One of 'preview', 'layer', 'variant'.
        control_type: The layer's control_type from layer_plan.json. Ignored
            in preview phase (always uses all refs). Required for layer and
            variant to filter refs; pass None to skip ref injection.
        base_image: The driving image (preview for layer phase, current
            control PNG for variant phase). Not used by preview phase.
        base_image_role: Optional override for the base image's role text in
            the header. Defaults to a phase-appropriate description.
        rule_kinds: Optional filter on which rule categories to include.

    Returns:
        (final_prompt, image_paths)

    Raises:
        ValueError: when phase is not one of the allowed values.
    """
    if phase not in {"preview", "layer", "variant"}:
        raise ValueError(
            f"phase must be one of 'preview' | 'layer' | 'variant', got '{phase}'"
        )

    headers: list[str] = []
    image_paths: list[Path] = []

    base_path: Path | None = Path(base_image) if base_image else None
    base_idx_tag: str | None = None  # tag attached to base image (variant only)

    if phase == "preview":
        refs = select_image_refs(style, "*")
        start_idx = 1
        if base_path is not None:
            # Wireframe / reference-draft mode: base image goes first.
            base_role = base_image_role or "Reference draft / wireframe"
            headers.append(_format_image_header(1, None, base_role))
            image_paths.append(base_path)
            start_idx = 2
            remaining = IMAGE_HARD_CAP - 1
            if len(refs) > remaining:
                refs = refs[:remaining]
        else:
            if len(refs) > IMAGE_HARD_CAP:
                refs = refs[:IMAGE_HARD_CAP]
        img_idx = start_idx
        for ref in refs:
            abs_path = ref.get("abs_path")
            if abs_path is None:
                continue
            tag = _primary_tag(ref) or None
            role = ref.get("role") or ""
            headers.append(_format_image_header(img_idx, tag, role))
            image_paths.append(Path(abs_path))
            img_idx += 1

    else:
        # layer / variant: base image goes first.
        if base_path is None:
            raise ValueError(
                f"phase='{phase}' requires base_image to be provided"
            )

        if phase == "variant" and control_type:
            base_idx_tag = control_type
            default_role = base_image_role or f"当前控件 (control_type={control_type})"
        else:
            default_role = base_image_role or (
                "当前 preview(从中提取目标控件)" if phase == "layer"
                else "当前控件画面"
            )
        headers.append(_format_image_header(1, base_idx_tag, default_role))
        image_paths.append(base_path)

        refs = select_image_refs(style, control_type)
        # Reserve 1 slot for base_image; truncate refs if needed.
        remaining = IMAGE_HARD_CAP - 1
        if len(refs) > remaining:
            refs = refs[:remaining]
        img_idx = 2
        for ref in refs:
            abs_path = ref.get("abs_path")
            if abs_path is None:
                continue
            tag = _primary_tag(ref) or None
            role = ref.get("role") or ""
            headers.append(_format_image_header(img_idx, tag, role))
            image_paths.append(Path(abs_path))
            img_idx += 1

    # --- instruction block (phase-specific) ---------------------------
    instruction = _build_instruction(phase, control_type, headers, base_path)

    # --- design rules + anchor ----------------------------------------
    rules_text = rules_to_prompt_text(style, kinds=rule_kinds)
    anchor = derive_anchor(style)

    # --- assemble ------------------------------------------------------
    sections: list[str] = []
    if headers:
        sections.append("\n".join(headers))
    if instruction:
        sections.append(instruction)
    if rules_text:
        if rule_kinds:
            rules = style.get("rules") or {}
            active_kinds = [k for k in rule_kinds if k in rules]
            kinds_label = " / ".join(active_kinds)
            sections.append(f"Design rules (filtered to {kinds_label}):\n{rules_text}")
        else:
            sections.append(f"Design rules:\n{rules_text}")
    if anchor:
        sections.append(f"Style: {anchor}.")
    if user_prompt and user_prompt.strip():
        sections.append(f"User request: {user_prompt.strip()}")

    final_prompt = "\n\n".join(sections)
    return final_prompt, image_paths


def _build_instruction(
    phase: str,
    control_type: str | None,
    headers: list[str],
    base_path: Path | None = None,
) -> str:
    """Phase-specific instruction line that ties images to the task."""
    has_refs = len(headers) > 1 if phase != "preview" else len(headers) >= 1

    if phase == "preview":
        if not has_refs and base_path is None:
            return ""
        if base_path is not None:
            return (
                "instruction: Generate a UI design composition based on the "
                "reference draft in Image1. Each subsequent labeled reference "
                "image defines the visual standard for its tagged control type. "
                "Apply each Image's style to every instance of its matching "
                "[control_type] in the output. Components outside the tagged "
                "types should follow the textual style and rules below."
            )
        return (
            "instruction: Generate a UI design composition. Each labeled "
            "reference image above defines the visual standard for its "
            "tagged control type. Apply each Image's style to every "
            "instance of its matching [control_type] in the output. "
            "Components outside the tagged types should follow the textual "
            "style and rules below."
        )

    if phase == "layer":
        if not has_refs:
            return (
                "instruction: Extract the requested layer from Image1. "
                "Transparent background. Keep exact position relative to "
                "Image1."
            )
        if control_type:
            return (
                f"instruction: Extract the requested layer from Image1. "
                f"This is a [{control_type}] — its style must strictly "
                f"match the reference image(s) above. Transparent "
                f"background. Keep exact position relative to Image1."
            )
        return (
            "instruction: Extract the requested layer from Image1, "
            "matching the reference image(s) above. Transparent "
            "background. Keep exact position relative to Image1."
        )

    # variant
    if not has_refs:
        if control_type:
            return (
                f"instruction: Generate the requested variant of the "
                f"[{control_type}] shown in Image1. Maintain exact "
                f"dimensions, palette, typography, and base shape. Apply "
                f"only the state-specific transformation."
            )
        return (
            "instruction: Generate the requested variant of the control "
            "shown in Image1. Maintain exact dimensions, palette, "
            "typography, and base shape. Apply only the state-specific "
            "transformation."
        )
    return (
        f"instruction: Generate the requested variant of the "
        f"[{control_type}] shown in Image1. Match overall style to the "
        f"reference image(s) above. Maintain exact dimensions, palette, "
        f"typography, and base shape. Apply only the state-specific "
        f"transformation."
    )


# ----------------------------------------------------------------------
# Workspace resolution
# ----------------------------------------------------------------------

def resolve(name_or_path: str, workspace_root: str | Path | None = None) -> Path:
    """
    Resolve a style name or path to an absolute directory.

    Delegates to `PathManager.resolve_style` when workspace_root is None so
    the workspace lookup logic stays in a single place.

    Args:
        name_or_path: Either a style name (e.g. 'saas-blue') or an explicit
            path (relative or absolute).
        workspace_root: Optional override for the workspace root. When None,
            uses `PathManager.get_workspace_root()`.

    Raises:
        FileNotFoundError: when the style cannot be located.
    """
    if workspace_root is None:
        from path_manager import PathManager
        return PathManager.resolve_style(name_or_path)

    workspace = Path(workspace_root).resolve()
    candidate = Path(name_or_path)
    if candidate.is_absolute() or candidate.exists():
        if candidate.is_dir() and (candidate / "style.json").exists():
            return candidate.resolve()

    candidate2 = workspace / "styles" / name_or_path
    if candidate2.is_dir() and (candidate2 / "style.json").exists():
        return candidate2.resolve()

    candidate3 = workspace / name_or_path
    if candidate3.is_dir() and (candidate3 / "style.json").exists():
        return candidate3.resolve()

    raise FileNotFoundError(
        f"Style '{name_or_path}' not found under workspace {workspace}."
    )
