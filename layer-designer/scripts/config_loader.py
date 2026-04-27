#!/usr/bin/env python3
"""
Shared configuration loader for Layered Design Generator scripts.
Supports JSON config files with environment variable interpolation.

Workflow role:
- Imported by ALL other scripts. Provides centralized config parsing.
- Resolves `${ENV_VAR}` placeholders from environment variables.
- Agents should NOT read config.json directly; import and use `load_config()`.

Usage:
    from config_loader import load_config, get_api_config, get_workflow_config
    config = load_config("../config.json")
    api_cfg = get_api_config(config)
"""

import json
import os
import re
from pathlib import Path


def _resolve_env(value):
    """Resolve ${VAR} or $VAR in string values from environment."""
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\$\{(\w+)\}|\$(\w+)")
    def replacer(match):
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, match.group(0))
    return pattern.sub(replacer, value)


def _deep_resolve(obj):
    """Recursively resolve environment variables in dicts and lists."""
    if isinstance(obj, dict):
        return {k: _deep_resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_resolve(item) for item in obj]
    return _resolve_env(obj)


def load_config(config_path: str | None = None) -> dict:
    """
    Load config from JSON file.

    Args:
        config_path: Path to config.json. If None, searches for config.json
                     in parent directory of this script.

    Returns:
        Resolved configuration dictionary.
    """
    if config_path is None:
        script_dir = Path(__file__).parent
        config_path = script_dir.parent / "config.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return _deep_resolve(raw)


def get_api_config(config: dict) -> dict:
    """Extract API-related config with sensible fallbacks.

    Supports per-provider grouped config under api.<provider> while
    remaining backward-compatible with flat (legacy) config.

    Example (new grouped style):
        "api": {
            "provider": "apimart",
            "openai": { "base_url": "...", "api_key": "..." },
            "apimart": { "base_url": "...", "api_key": "...", "official_fallback": false }
        }

    Example (legacy flat style):
        "api": { "provider": "openai", "base_url": "...", "api_key": "..." }
    """
    api = config.get("api", {})
    provider = api.get("provider", "openai")

    # If a provider-specific block exists, merge it on top of the flat defaults.
    provider_cfg = api.get(provider, {})
    merged = {**api, **provider_cfg}

    return {
        "provider": provider,
        "provider_type": merged.get("provider_type", "openai"),
        "base_url": merged.get("base_url", os.environ.get("OPENAI_BASE_URL", "https://your-api-gateway.com/v1")),
        "api_key": merged.get("api_key", os.environ.get("OPENAI_API_KEY", "your-key")),
        "model": merged.get("model", "gpt-image-2"),
        "default_size": merged.get("default_size", "1024x1024"),
        "default_quality_low": merged.get("default_quality_low", "low"),
        "default_quality_medium": merged.get("default_quality_medium", "medium"),
        "default_quality_high": merged.get("default_quality_high", "high"),
        "default_n": merged.get("default_n", 1),
        "output_format": merged.get("output_format", "png"),
        "official_fallback": merged.get("official_fallback", False),
        "prefer_official": merged.get("prefer_official", True),
        "async_config": merged.get("async_config", {}),
    }


def get_workflow_config(config: dict) -> dict:
    """Extract workflow-related config."""
    wf = config.get("workflow", {})
    return {
        "max_iterations": wf.get("max_iterations", 20),
        "require_user_ok": wf.get("require_user_ok", True),
        "default_scene": wf.get("default_scene", "ui-design"),
        "fast_workflow": wf.get("fast_workflow", False),
        "preview_count_initial": wf.get("preview_count_initial", 3),
        "preview_count_revision": wf.get("preview_count_revision", 2),
        "preview_quality_initial": wf.get("preview_quality_initial", "low"),
        "preview_quality_revision": wf.get("preview_quality_revision", "low"),
        "parallel_generation": wf.get("parallel_generation", True),
        "parallel_max_workers": wf.get("parallel_max_workers", 8),
        "downsize_early_phases": wf.get("downsize_early_phases", True),
        "downsize_ratio": wf.get("downsize_ratio", 0.5),
        "downsize_threshold_width": wf.get("downsize_threshold_width", 300),
        "downsize_threshold_height": wf.get("downsize_threshold_height", 200),
        "downsize_threshold_pixels": wf.get("downsize_threshold_pixels", 60000),
        "incremental_update": wf.get("incremental_update", True),
        "quality_adaptive": wf.get("quality_adaptive", True),
    }


def get_paths_config(config: dict) -> dict:
    """Extract output path config."""
    p = config.get("paths", {})
    return {
        "layers_dir": p.get("layers_dir", "./layers"),
        "final_dir": p.get("final_dir", "./final"),
        "check_dir": p.get("check_dir", "./check"),
        "variants_dir": p.get("variants_dir", "./variants"),
        "states_dir": p.get("states_dir", "./states"),
        "temp_dir": p.get("temp_dir", "./temp"),
    }


def get_transparency_config(config: dict) -> dict:
    """Extract transparency check config."""
    t = config.get("transparency", {})
    return {
        "threshold": t.get("threshold", 10),
        "sample_rate": t.get("sample_rate", 1.0),
        "skip_check_if_no_alpha": t.get("skip_check_if_no_alpha", True),
    }


def get_composition_config(config: dict) -> dict:
    """Extract composition config."""
    c = config.get("composition", {})
    return {
        "enforce_uniform_size": c.get("enforce_uniform_size", True),
        "default_width": c.get("default_width", 1024),
        "default_height": c.get("default_height", 1024),
    }


def get_variants_config(config: dict) -> dict:
    """Extract variant generation config."""
    v = config.get("variants", {})
    return {
        "default_control_type": v.get("default_control_type", "generic"),
        "default_states": v.get("default_states", ["hover", "active", "disabled"]),
    }


def get_matting_config(config: dict) -> dict:
    """Extract background matting/removal config."""
    m = config.get("matting", {})
    return {
        "model": m.get("model", "u2net"),
        "model_file": m.get("model_file", ""),
        "alpha_matting": m.get("alpha_matting", True),
        "alpha_matting_foreground_threshold": m.get("alpha_matting_foreground_threshold", 240),
        "alpha_matting_background_threshold": m.get("alpha_matting_background_threshold", 10),
        "alpha_matting_erode_size": m.get("alpha_matting_erode_size", 10),
    }


def get_model_constraints(config: dict, model_name: str | None = None) -> dict:
    """Extract model constraints for a specific model.
    
    Args:
        config: Full configuration dictionary.
        model_name: Model identifier (e.g., 'gpt-image-2'). If None, uses
                    the model from api config.
    
    Returns:
        Model constraint dictionary. Empty dict if model not found.
    """
    constraints = config.get("model_constraints", {})
    if model_name is None:
        model_name = config.get("api", {}).get("model", "gpt-image-2")
    return constraints.get(model_name, {})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Config loader test")
    parser.add_argument("--config", help="Path to config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    print(json.dumps(cfg, indent=2))
