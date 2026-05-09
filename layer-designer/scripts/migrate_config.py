#!/usr/bin/env python3
"""
Config migration script for Layered Design Generator.

When the project schema evolves (new fields, renames, provider-specific overrides),
run this script to upgrade an existing config.json without losing user secrets.

Usage:
    python scripts/migrate_config.py --config config.json
    python scripts/migrate_config.py --config config.json --dry-run

Behavior:
    1. Reads existing config.json (preserves user values like api_key)
    2. Reads config.example.json as the schema template
    3. Deep-merges: user values win, missing keys are filled from template
    4. Applies known renames (e.g. "model" -> "default_model")
    5. Writes back to config.json (or prints diff in dry-run mode)
"""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path


def _deep_merge(base: dict, template: dict, path: str = "") -> dict:
    """Recursively merge template into base. Base values are preserved."""
    result = deepcopy(base)
    for key, tmpl_val in template.items():
        current_path = f"{path}.{key}" if path else key
        if key not in result:
            result[key] = deepcopy(tmpl_val)
        elif isinstance(tmpl_val, dict) and isinstance(result[key], dict):
            result[key] = _deep_merge(result[key], tmpl_val, current_path)
    return result


def _apply_renames(cfg: dict) -> dict:
    """Apply known field renames while preserving old values as fallback."""
    api = cfg.get("api", {})
    for provider in ["openai", "apimart"]:
        block = api.get(provider)
        if not isinstance(block, dict):
            continue
        # model -> default_model
        if "model" in block and "default_model" not in block:
            block["default_model"] = block["model"]
    return cfg


def migrate(config_path: str, dry_run: bool = False) -> dict:
    config_file = Path(config_path)
    example_file = config_file.parent / "config.example.json"

    if not config_file.exists():
        print(f"ERROR: Config not found: {config_file}", file=sys.stderr)
        sys.exit(1)

    if not example_file.exists():
        print(f"ERROR: Template not found: {example_file}", file=sys.stderr)
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        user_cfg = json.load(f)

    with open(example_file, "r", encoding="utf-8") as f:
        template = json.load(f)

    # Remove template-only metadata before merging
    template.pop("_comment", None)

    merged = _deep_merge(user_cfg, template)
    merged = _apply_renames(merged)

    if dry_run:
        print(json.dumps(merged, indent=2, ensure_ascii=False))
    else:
        # Backup old config
        backup = config_file.with_suffix(".json.backup")
        backup.write_text(config_file.read_text("utf-8"), encoding="utf-8")
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Migrated config saved to: {config_file}")
        print(f"Backup saved to: {backup}")

    return merged


def main():
    parser = argparse.ArgumentParser(description="Migrate config.json to latest schema")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Print result without writing")
    args = parser.parse_args()

    migrate(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
