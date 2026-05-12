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


def _resolve_default_provider(config: dict) -> str:
    """Pick the default provider name. New schema: api.default_provider; legacy: api.provider."""
    api = config.get("api", {})
    return api.get("default_provider") or api.get("provider") or "openai"


def _get_provider_block(config: dict, provider: str) -> dict:
    """Read a provider's config block. New schema: api.providers.<name>; legacy: api.<name>."""
    api = config.get("api", {})
    providers = api.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get(provider), dict):
        return providers[provider]
    block = api.get(provider)
    if isinstance(block, dict):
        return block
    return {}


def get_api_config(config: dict) -> dict:
    """Extract API-related config for the default provider.

    New schema:
        "api": {
            "default_provider": "openai",
            "phase_models": {                              # top-level
                "preview": "openai/gpt-image-2",
                "layer": "apimart/gpt-image-1.5-official"
            },
            "providers": {
                "openai":  { "provider_type": "openai", "base_url": "...", "api_key": "..." },
                "apimart": { "provider_type": "async_task", "base_url": "...", ... }
            }
        }

    Legacy schema (still supported by the loader; migrate via migrate_config.py):
        "api": {
            "provider": "openai",
            "openai":  { "base_url": "...", "api_key": "...", "phase_models": {...} },
            "apimart": { "base_url": "...", "api_key": "...", "async_config": {...} }
        }
    """
    provider = _resolve_default_provider(config)
    cfg = get_provider_api_config(config, provider)
    api = config.get("api", {})
    cfg["phase_models"] = api.get("phase_models", _get_provider_block(config, provider).get("phase_models", {}))
    return cfg


def get_provider_api_config(config: dict, provider: str) -> dict:
    """Extract API config for a SPECIFIC provider, regardless of the default.

    Used when phase_models routes a phase to a non-default provider — we still
    need that provider's credentials, base_url, async_config, and any
    provider-specific model constraints.
    """
    api = config.get("api", {})
    provider_cfg = _get_provider_block(config, provider)

    # Top-level api defaults still apply (legacy flat schema support)
    merged = {**api, **provider_cfg}
    # Strip api-level metadata + provider container keys
    for k in ("provider", "default_provider", "phase_models", "providers", "openai", "apimart"):
        merged.pop(k, None)

    default_model = merged.get("default_model", merged.get("model", "gpt-image-2"))

    return {
        "provider": provider,
        "provider_type": merged.get("provider_type", "openai"),
        "base_url": merged.get("base_url", os.environ.get("OPENAI_BASE_URL", "https://your-api-gateway.com/v1")),
        "api_key": merged.get("api_key", os.environ.get("OPENAI_API_KEY", "your-key")),
        "default_model": default_model,
        "default_size": merged.get("default_size", "1024x1024"),
        "default_quality_low": merged.get("default_quality_low", "low"),
        "default_quality_medium": merged.get("default_quality_medium", "medium"),
        "default_quality_high": merged.get("default_quality_high", "high"),
        "default_n": merged.get("default_n", 1),
        "output_format": merged.get("output_format", "png"),
        "official_fallback": merged.get("official_fallback", False),
        "async_config": merged.get("async_config", {}),
        "model_constraints": merged.get("model_constraints", {}),
    }


def parse_model_spec(spec: str | None, default_provider: str = "openai") -> tuple[str, str]:
    """Parse a phase_models value or --model argument into (provider, model).

    Accepts:
        "openai/gpt-image-2"   -> ("openai", "gpt-image-2")
        "apimart/gpt-image-1.5-official" -> ("apimart", "gpt-image-1.5-official")
        "gpt-image-2"          -> (default_provider, "gpt-image-2")
        None / ""              -> (default_provider, "gpt-image-2")
    """
    if not spec:
        return default_provider, "gpt-image-2"
    spec = spec.strip()
    if "/" in spec:
        prov, _, mdl = spec.partition("/")
        prov = prov.strip()
        mdl = mdl.strip()
        if prov and mdl:
            return prov, mdl
    return default_provider, spec


def get_phase_model(config: dict, role: str | None, fallback: str | None = None) -> str:
    """Resolve the model spec for a workflow phase role.

    Reads `api.phase_models[role]` (new top-level schema). Legacy fallback is
    `api.<default_provider>.phase_models[role]`. Final fallback is the default
    provider's `default_model`. `fallback` overrides everything when provided
    (used when callers pass an explicit `--model` flag).

    Returns a spec string that may be either:
        - "<provider>/<model>" (cross-provider routing)
        - "<model>" (resolved against the default provider)

    Args:
        config: Full configuration dictionary.
        role: One of "preview", "layer", "variant" (or any custom key the user
              defined under `phase_models`). Pass None to skip phase lookup.
        fallback: Optional override that takes precedence over the lookup.

    Returns:
        Model spec string. Never empty — falls back to "gpt-image-2".
    """
    if fallback:
        return fallback
    api = config.get("api", {})
    top_phase_models = api.get("phase_models", {}) or {}
    if role and top_phase_models.get(role):
        return top_phase_models[role]
    provider = _resolve_default_provider(config)
    legacy_phase_models = _get_provider_block(config, provider).get("phase_models", {}) or {}
    if role and legacy_phase_models.get(role):
        return legacy_phase_models[role]
    return get_provider_api_config(config, provider).get("default_model") or "gpt-image-2"


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


def get_model_constraints(config: dict, model_name: str | None = None,
                          provider: str | None = None) -> dict:
    """Extract model constraints for a specific model.

    Per-provider overrides live under api.providers.<provider>.model_constraints
    (new schema) or api.<provider>.model_constraints (legacy). Provider-specific
    fields are merged on top of the global model_constraints block.

    Args:
        config: Full configuration dictionary.
        model_name: Model identifier (e.g., 'gpt-image-2'). If None, uses the
                    provider's default_model.
        provider: Provider name (e.g., 'openai', 'apimart'). If None, uses the
                  configured default provider.

    Returns:
        Model constraint dictionary. Empty dict if model not found anywhere.
    """
    constraints = config.get("model_constraints", {})
    if provider is None:
        provider = _resolve_default_provider(config)
    if model_name is None:
        model_name = get_provider_api_config(config, provider).get("default_model") or "gpt-image-2"

    base = constraints.get(model_name, {})
    provider_override = _get_provider_block(config, provider).get("model_constraints", {}).get(model_name, {})

    if provider_override:
        return {**base, **provider_override}
    return base


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Config loader test")
    parser.add_argument("--config", help="Path to config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    print(json.dumps(cfg, indent=2))
