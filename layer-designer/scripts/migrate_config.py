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
    2. Migrates schema shape:
       - api.provider -> api.default_provider
       - api.{openai, apimart} -> api.providers.{openai, apimart}
       - active provider's phase_models -> top-level api.phase_models with
         "provider/model" qualified values
    3. Deep-merges with config.example.json template (user values win)
    4. Applies known field renames (e.g. "model" -> "default_model")
    5. Writes back to config.json (or prints diff in dry-run mode)
"""

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path


def _get_project_version(config_file: Path) -> str | None:
    """Read __version__ from layer-designer.py next to config.json."""
    cli_file = config_file.parent / "layer-designer.py"
    if not cli_file.exists():
        return None
    content = cli_file.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.M)
    return m.group(1) if m else None


def _migrate_api_schema(cfg: dict) -> dict:
    """Lift legacy api.<provider> blocks under api.providers.<name>, rename
    provider→default_provider, and hoist the active provider's phase_models to
    a top-level api.phase_models with `provider/model` qualified values.

    Idempotent: if the new shape is already in place, this is a no-op.
    """
    api = cfg.get("api")
    if not isinstance(api, dict):
        return cfg

    # 1. provider -> default_provider
    if "provider" in api and "default_provider" not in api:
        api["default_provider"] = api.pop("provider")
        print("[MIGRATE] api.provider -> api.default_provider")

    # 2. Move api.<known-provider> -> api.providers.<name>
    providers = api.get("providers")
    if not isinstance(providers, dict):
        providers = {}

    moved = []
    for legacy_key in ("openai", "apimart"):
        block = api.get(legacy_key)
        if isinstance(block, dict):
            # Don't clobber if already under providers
            providers.setdefault(legacy_key, block)
            api.pop(legacy_key, None)
            moved.append(legacy_key)
    if moved:
        print(f"[MIGRATE] api.{{ {', '.join(moved)} }} -> api.providers.*")

    if providers:
        api["providers"] = providers

    # 3. Hoist phase_models from the active provider's block to top-level
    if not isinstance(api.get("phase_models"), dict) or not api.get("phase_models"):
        active = api.get("default_provider") or "openai"
        active_block = providers.get(active) if isinstance(providers, dict) else None
        if isinstance(active_block, dict):
            legacy_pm = active_block.get("phase_models")
            if isinstance(legacy_pm, dict) and legacy_pm:
                api["phase_models"] = {
                    role: f"{active}/{model}" for role, model in legacy_pm.items()
                }
                print(f"[MIGRATE] api.providers.{active}.phase_models -> api.phase_models (qualified)")

    # 4. Drop phase_models from each provider block (now lives top-level)
    if isinstance(api.get("providers"), dict):
        for prov_block in api["providers"].values():
            if isinstance(prov_block, dict):
                prov_block.pop("phase_models", None)

    cfg["api"] = api
    return cfg


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
    """Apply known field renames inside provider blocks."""
    api = cfg.get("api", {})
    providers = api.get("providers", {}) if isinstance(api, dict) else {}
    if not isinstance(providers, dict):
        return cfg
    for block in providers.values():
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

    # Schema migration must precede deep_merge — otherwise legacy api.<provider>
    # blocks would coexist with the template's api.providers.<provider> blocks.
    user_cfg = _migrate_api_schema(user_cfg)

    merged = _deep_merge(user_cfg, template)
    merged = _apply_renames(merged)

    # Sync config_version to project version so user config tracks schema evolution
    project_version = _get_project_version(config_file)
    if project_version:
        old_version = merged.get("config_version", "<none>")
        merged["config_version"] = project_version
        if old_version != project_version:
            print(f"[MIGRATE] config_version: {old_version} -> {project_version}")

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
