#!/usr/bin/env python3
"""
Setup script for Layered Design Generator.

Run this once after cloning the repository to:
  1. Install required Python packages (from requirements.txt if present,
     otherwise an inline fallback list).
  2. Create config.json from the example template (so we can read the
     desired matting model from it).
  3. (Optional) Download the configured matting ONNX model — requires
     --download flag. Default is to skip downloading.
  4. Run a quick import + presence sanity check.

Quick examples:
    cd layer-designer
    python scripts/setup.py                              # install deps + config only
    python scripts/setup.py --download                   # also download default model
    python scripts/setup.py --download --model birefnet-general
    python scripts/setup.py --use-proxy                  # built-in ghproxy.cn mirror
    python scripts/setup.py --mirror https://my.mirror   # custom mirror
    python scripts/setup.py --skip-deps

    # Link an already-downloaded model file
    python scripts/setup.py link /path/to/u2net.onnx
    python scripts/setup.py link /path/to/model.onnx --model birefnet-general

See `python scripts/setup.py --help` for the full option list.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Built-in proxy for users in regions where GitHub is unreachable.
DEFAULT_PROXY = "https://ghproxy.cn"

# Official model download URLs (used as fallback when rembg's downloader
# fails or when the user specifies a mirror).
_MODEL_OFFICIAL_URLS = {
    "u2net": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
    "birefnet-general": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx",
    "birefnet-general-lite": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-lite-epoch_234.onnx",
    "birefnet-portrait": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-portrait-epoch_150.onnx",
    "birefnet-hrsod": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-HRSOD-epoch_150.onnx",
    "birefnet-dis": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-DIS-epoch_150.onnx",
    "birefnet-cod": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-COD-epoch_150.onnx",
    "birefnet-massive": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-massive-epoch_150.onnx",
}

SUPPORTED_MODELS = list(_MODEL_OFFICIAL_URLS.keys())

# Inline fallback dependency list when requirements.txt is missing.
_FALLBACK_DEPS = [
    "openai>=2.0,<3.0",
    "Pillow>=10.0,<12.0",
    "rembg>=2.0,<3.0",
    "numpy>=1.24,<3.0",
    "requests>=2.28,<3.0",
]


def _log(msg: str, *, quiet: bool = False, important: bool = False) -> None:
    """Emit a log line, respecting --quiet (important messages always print)."""
    if quiet and not important:
        return
    print(msg)


def _download_via_requests(
    url: str,
    output_path: Path,
    *,
    sha256: str = "",
    quiet: bool = False,
) -> bool:
    """Download to a `.partial` sidecar and atomically rename on success.

    Validates content-length when available, and optionally verifies SHA256.
    Mismatched/incomplete downloads are discarded so a half-finished file
    can never be mistaken for a complete one on the next run.
    """
    try:
        import requests
    except ImportError:
        _log("   requests not available (should be installed with rembg)", important=True)
        return False

    partial = output_path.with_suffix(output_path.suffix + ".partial")
    _log(f"   Downloading from: {url}", quiet=quiet)
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            hasher = hashlib.sha256() if sha256 else None
            with open(partial, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    downloaded += len(chunk)
                    if total > 0 and not quiet:
                        percent = downloaded / total * 100
                        print(
                            f"   Progress: {percent:.1f}% "
                            f"({downloaded/1024/1024:.1f} MB / {total/1024/1024:.1f} MB)",
                            end="\r",
                        )
            if not quiet:
                print()  # newline after the carriage-return progress line

        if total > 0 and downloaded != total:
            _log(
                f"   [WARNING] Size mismatch: got {downloaded}, expected {total}. "
                f"Discarding partial.",
                important=True,
            )
            partial.unlink(missing_ok=True)
            return False

        if hasher is not None:
            actual = hasher.hexdigest()
            if actual.lower() != sha256.lower():
                _log(
                    f"   [ERROR] SHA256 mismatch: got {actual}, expected {sha256}. "
                    f"Discarding partial.",
                    important=True,
                )
                partial.unlink(missing_ok=True)
                return False
            _log(f"   [OK] SHA256 verified: {actual}", important=True)

        os.replace(partial, output_path)
        size_mb = output_path.stat().st_size / (1024 * 1024)
        _log(f"[OK] Model downloaded: {output_path} ({size_mb:.1f} MB)", important=True)
        return True
    except Exception as e:
        _log(f"   Download failed: {e}", important=True)
        partial.unlink(missing_ok=True)
        return False


def check_python_version(*, quiet: bool = False) -> None:
    """Ensure Python 3.9+ is available."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(f"ERROR: Python {version.major}.{version.minor} detected. Python 3.9+ is required.")
        sys.exit(1)
    _log(f"[OK] Python {version.major}.{version.minor}.{version.micro}", quiet=quiet)


def install_dependencies(
    script_dir: Path,
    *,
    skip_pip_upgrade: bool = False,
    quiet: bool = False,
) -> None:
    """Install required packages, preferring requirements.txt over the inline fallback."""
    requirements = script_dir.parent / "requirements.txt"
    if requirements.exists():
        _log(f"\n[INSTALL] Installing dependencies from {requirements.name}", important=True)
        pip_args = ["-r", str(requirements)]
    else:
        _log("\n[INSTALL] requirements.txt not found, falling back to inline list:", important=True)
        _log(f"          {', '.join(_FALLBACK_DEPS)}", important=True)
        pip_args = list(_FALLBACK_DEPS)

    pip_quiet = ["--quiet"] if quiet else []
    try:
        if skip_pip_upgrade:
            _log("   Skipping `pip install --upgrade pip` (--skip-pip-upgrade)", quiet=quiet)
        else:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--upgrade", "pip", *pip_quiet]
            )
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *pip_quiet, *pip_args]
        )
        _log("[OK] Dependencies installed", important=True)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to install dependencies: {e}")
        sys.exit(1)


def _try_link_custom_model(
    model_dir: Path,
    model_name: str,
    model_file: str,
    *,
    quiet: bool = False,
) -> None:
    """Hard-link (or copy as fallback) a user-supplied .onnx file to <model>.onnx.

    `os.link` fails across filesystems and on some Windows configurations
    without developer mode, so we fall back to `shutil.copy2`.
    """
    custom_path = model_dir / model_file
    target = model_dir / f"{model_name}.onnx"
    if not custom_path.exists() or target.exists():
        return
    try:
        os.link(str(custom_path), str(target))
        _log(f"\n[OK] Linked {model_file} -> {model_name}.onnx", quiet=quiet)
        return
    except OSError as link_err:
        try:
            shutil.copy2(str(custom_path), str(target))
            _log(
                f"\n[OK] Copied {model_file} -> {model_name}.onnx "
                f"(hardlink unavailable: {link_err})",
                important=True,
            )
        except Exception as copy_err:
            _log(
                f"\n[WARNING] Could not link or copy custom model: "
                f"link={link_err}; copy={copy_err}",
                important=True,
            )


def _verify_existing_sha256(model_path: Path, sha256: str) -> bool:
    """Compute SHA256 of an on-disk file and compare to expected hex digest."""
    h = hashlib.sha256()
    with open(model_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().lower() == sha256.lower()


def download_model(
    model_name: str,
    *,
    mirror: str = "",
    sha256: str = "",
    force: bool = False,
    custom_model_file: str = "",
    quiet: bool = False,
) -> None:
    """Download an ONNX matting model into <repo>/models/.

    Resolution order:
        1. If model is already present (and not --force-redownload), keep it.
        2. Try rembg's official downloader.
        3. Try mirror prefix + official URL via requests.
        4. Try the official URL directly via requests.
        5. Print manual instructions and exit non-zero.
    """
    script_dir = Path(__file__).parent.resolve()
    model_dir = script_dir.parent / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(model_dir)

    model_path = model_dir / f"{model_name}.onnx"

    if custom_model_file:
        _try_link_custom_model(model_dir, model_name, custom_model_file, quiet=quiet)

    if model_path.exists() and not force:
        size_mb = model_path.stat().st_size / (1024 * 1024)
        if sha256 and not _verify_existing_sha256(model_path, sha256):
            _log(
                f"\n[WARNING] Existing {model_path.name} fails SHA256 check; re-downloading.",
                important=True,
            )
            model_path.unlink()
        else:
            _log(f"\n[OK] Model already exists: {model_path} ({size_mb:.1f} MB)", important=True)
            _log("     Pass --force-redownload to re-fetch.", quiet=quiet)
            return
    elif model_path.exists() and force:
        _log(f"\n[INFO] --force-redownload: removing existing {model_path.name}", important=True)
        model_path.unlink()

    _log(f"\n[DOWNLOAD] {model_name} model. This may take a few minutes...", important=True)

    # 1. Try rembg's built-in downloader (uses U2NET_HOME).
    try:
        from rembg.session_factory import new_session
        new_session(model_name)
        if model_path.exists():
            if sha256 and not _verify_existing_sha256(model_path, sha256):
                _log(
                    "   [ERROR] rembg-downloaded file failed SHA256 check; falling back.",
                    important=True,
                )
                model_path.unlink()
            else:
                size_mb = model_path.stat().st_size / (1024 * 1024)
                _log(f"[OK] Model downloaded: {model_path} ({size_mb:.1f} MB)", important=True)
                return
    except Exception as e:
        _log(f"   Official downloader failed: {e}", important=True)

    # 2. Try mirror, then 3. official URL via requests.
    official_url = _MODEL_OFFICIAL_URLS.get(model_name)
    if official_url:
        urls_to_try = []
        if mirror:
            urls_to_try.append(mirror.rstrip("/") + "/" + official_url)
        urls_to_try.append(official_url)

        for url in urls_to_try:
            _log("\n   Trying alternative source...", quiet=quiet)
            if _download_via_requests(url, model_path, sha256=sha256, quiet=quiet):
                return

    # 4. Manual instructions.
    print(f"\n[ERROR] Automatic download failed for {model_name}.")
    print("   Please manually download the model and place it at:")
    print(f"   {model_path}")
    if official_url:
        print(f"\n   Official URL: {official_url}")
        print(f"   Mirror URL (China mainland): {DEFAULT_PROXY}/{official_url}")
        print("\n   Example:")
        print(f'   curl -L -o "{model_path}" "{DEFAULT_PROXY}/{official_url}"')
        print("\n   Or use the link command:")
        print(f'   python scripts/setup.py link /path/to/{model_name}.onnx --model {model_name}')
    sys.exit(1)


def create_config(*, quiet: bool = False) -> bool:
    """Copy config.example.json -> config.json if missing.

    Returns True if config.json now exists, False if the example template
    was missing too.
    """
    script_dir = Path(__file__).parent.resolve()
    example = script_dir.parent / "config.example.json"
    target = script_dir.parent / "config.json"

    if target.exists():
        _log("\n[OK] config.json already exists", quiet=quiet)
        return True

    if not example.exists():
        _log(f"\n[WARNING] config.example.json not found at {example}", important=True)
        return False

    shutil.copy2(example, target)
    _log(f"\n[OK] Created {target}", important=True)
    _log(
        "   [IMPORTANT] Edit config.json and fill in your API endpoint and key before use.",
        important=True,
    )
    return True


def verify_installation(model_name: str, *, quiet: bool = False, suggest_download: bool = True) -> None:
    """Run a quick sanity check on imports + model + config presence."""
    _log("\n[VERIFY] Verifying installation...", important=True)
    try:
        import openai  # noqa: F401
        import PIL  # noqa: F401
        import rembg  # noqa: F401
        import numpy  # noqa: F401
        _log("[OK] All packages importable", important=True)
    except ImportError as e:
        print(f"ERROR: Import failed: {e}")
        sys.exit(1)

    script_dir = Path(__file__).parent.resolve()
    model_dir = script_dir.parent / "models"

    if (model_dir / f"{model_name}.onnx").exists():
        _log(f"[OK] Matting model ({model_name}) present", important=True)
    else:
        msg = (
            f"[WARNING] Matting model ({model_name}) missing"
        )
        if suggest_download:
            msg += (
                " - run with --download to fetch, or use 'link' to use an existing file"
            )
        _log(msg, important=True)

    config = script_dir.parent / "config.json"
    if config.exists():
        _log("[OK] config.json present", important=True)
    else:
        _log("[WARNING] config.json missing - remember to create it", important=True)

    _log(
        "\n[DONE] Setup complete! You're ready to use the Layered Design Generator.",
        important=True,
    )
    if not config.exists():
        # Cross-platform copy hint that works on Windows + Unix.
        print(
            f"   -> Run: {sys.executable} -c "
            "\"import shutil; shutil.copy('layer-designer/config.example.json', "
            "'layer-designer/config.json')\""
        )
        print("   -> Then edit config.json with your API credentials.")


def _resolve_settings(args, script_dir: Path):
    """Read config.json once and resolve (model, mirror, custom_model_file).

    Priority:
        - model:  --model > config.matting.model > "u2net"
        - mirror: --no-proxy > --use-proxy > --mirror > config.download_mirror > ""
        - custom_model_file: config.matting.model_file (no CLI override)
    """
    cfg = None
    config_path = script_dir.parent / "config.json"
    if config_path.exists():
        try:
            from config_loader import load_config  # type: ignore
            cfg = load_config(config_path)
        except Exception as e:
            _log(f"[WARNING] Could not load config.json: {e}", important=True)

    # Model.
    if getattr(args, "model", None):
        model = args.model
    elif cfg is not None:
        try:
            from config_loader import get_matting_config  # type: ignore
            model = get_matting_config(cfg).get("model", "u2net")
        except Exception as e:
            _log(f"[WARNING] Could not read matting.model from config: {e}", important=True)
            model = "u2net"
    else:
        model = "u2net"

    # Mirror.
    if getattr(args, "no_proxy", False):
        mirror = ""
    elif getattr(args, "use_proxy", False):
        mirror = DEFAULT_PROXY
    elif getattr(args, "mirror", None):
        mirror = args.mirror
    elif cfg is not None:
        mirror = cfg.get("download_mirror", "") or ""
    else:
        mirror = ""

    # Custom model file (config-only).
    custom_file = ""
    if cfg is not None:
        try:
            from config_loader import get_matting_config  # type: ignore
            custom_file = get_matting_config(cfg).get("model_file", "") or ""
        except Exception:
            custom_file = ""

    return model, mirror, custom_file


def _update_config_matting(script_dir: Path, model: str, model_file: str = "") -> bool:
    """Update matting.model and optionally matting.model_file in config.json."""
    config_path = script_dir.parent / "config.json"
    if not config_path.exists():
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        if "matting" not in cfg:
            cfg["matting"] = {}
        cfg["matting"]["model"] = model
        if model_file:
            cfg["matting"]["model_file"] = model_file
        else:
            cfg["matting"].pop("model_file", None)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        _log(f"[WARNING] Could not update config.json: {e}", important=True)
        return False


def _infer_model_from_filename(filename: str) -> str | None:
    """Try to infer a supported model name from a filename."""
    lower = filename.lower()
    for m in SUPPORTED_MODELS:
        # Check for model name or common variants in filename
        patterns = [
            m.lower(),
            m.lower().replace("-", "_"),
            m.lower().replace("-", ""),
        ]
        for pat in patterns:
            if pat in lower:
                return m
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Layered Design Generator setup script.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            "  setup                     Run setup (default)\n"
            "  link <source>             Link an existing model file to models/{model}.onnx\n"
            "\n"
            "Setup examples:\n"
            "  python scripts/setup.py                              # install deps + config only\n"
            "  python scripts/setup.py --download                   # also download default model\n"
            "  python scripts/setup.py --download --model birefnet-general\n"
            "  python scripts/setup.py --use-proxy\n"
            "  python scripts/setup.py --skip-deps\n"
            "\n"
            "Link examples:\n"
            "  python scripts/setup.py link /path/to/u2net.onnx\n"
            "  python scripts/setup.py link /path/to/model.onnx --model birefnet-general\n"
            "  python scripts/setup.py link /path/to/model.onnx --force\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── setup subcommand ──────────────────────────────────────────────
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install dependencies, create config, optionally download model",
    )
    setup_parser.add_argument(
        "--download",
        action="store_true",
        help="Download the matting model. Without this flag, setup skips downloading.",
    )
    setup_parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        help=(
            "Matting model to download (overrides config.matting.model). "
            f"Choices: {', '.join(SUPPORTED_MODELS)}"
        ),
    )

    proxy_group = setup_parser.add_mutually_exclusive_group()
    proxy_group.add_argument(
        "--use-proxy",
        action="store_true",
        help=(
            f"Use the built-in proxy ({DEFAULT_PROXY}) for downloading the model. "
            "Recommended for users in China mainland."
        ),
    )
    proxy_group.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable any mirror/proxy even if set in config.json.",
    )
    proxy_group.add_argument(
        "--mirror",
        default="",
        help="Custom download mirror prefix (e.g. https://ghproxy.cn). Overrides config.download_mirror.",
    )

    setup_parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip pip install (assume dependencies are already present, e.g. inside a prepared venv).",
    )
    setup_parser.add_argument(
        "--skip-pip-upgrade",
        action="store_true",
        help="Don't run `pip install --upgrade pip` (avoid breaking managed environments).",
    )
    setup_parser.add_argument(
        "--no-config-create",
        action="store_true",
        help="Don't auto-copy config.example.json -> config.json if it's missing.",
    )
    setup_parser.add_argument(
        "--force-redownload",
        action="store_true",
        help="Re-download the model even if it already exists on disk.",
    )
    setup_parser.add_argument(
        "--sha256",
        default="",
        metavar="HEX",
        help="Optional SHA256 hex digest. If provided, downloads (and existing files) are verified against it.",
    )
    setup_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce log verbosity. Important warnings/errors still print.",
    )

    # ── link subcommand ───────────────────────────────────────────────
    link_parser = subparsers.add_parser(
        "link",
        help="Link an existing model .onnx file into models/{model}.onnx",
    )
    link_parser.add_argument(
        "source",
        help="Path to an existing .onnx model file",
    )
    link_parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        help=(
            "Target model name (e.g. u2net, birefnet-general). "
            "If omitted, reads from config.json or infers from filename."
        ),
    )
    link_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target file if it already exists.",
    )
    link_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce log verbosity. Important warnings/errors still print.",
    )

    return parser


def _cmd_setup(args) -> None:
    """Execute the setup subcommand."""
    script_dir = Path(__file__).parent.resolve()

    print("=" * 60)
    print("  Layered Design Generator - Setup")
    print("=" * 60)

    check_python_version(quiet=args.quiet)

    if args.skip_deps:
        _log("\n[SKIP] Skipping pip install (--skip-deps).", important=True)
    else:
        install_dependencies(
            script_dir,
            skip_pip_upgrade=args.skip_pip_upgrade,
            quiet=args.quiet,
        )

    # Create config first so model resolution can read it.
    if args.no_config_create:
        _log("\n[SKIP] Skipping config.json creation (--no-config-create).", important=True)
    else:
        create_config(quiet=args.quiet)

    model, mirror, custom_file = _resolve_settings(args, script_dir)
    _log(f"\n[INFO] Using matting model: {model}", important=True)
    if mirror:
        _log(f"[INFO] Using download mirror: {mirror}", important=True)

    if args.download:
        download_model(
            model,
            mirror=mirror,
            sha256=args.sha256,
            force=args.force_redownload,
            custom_model_file=custom_file,
            quiet=args.quiet,
        )
    else:
        _log("\n[SKIP] Skipping model download (--download not set).", important=True)
        # Still try to link a custom model if configured
        if custom_file:
            model_dir = script_dir.parent / "models"
            model_dir.mkdir(parents=True, exist_ok=True)
            _try_link_custom_model(model_dir, model, custom_file, quiet=args.quiet)

    verify_installation(model, quiet=args.quiet, suggest_download=not args.download)


def _cmd_link(args) -> None:
    """Execute the link subcommand."""
    script_dir = Path(__file__).parent.resolve()
    model_dir = script_dir.parent / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(model_dir)

    source = Path(args.source).resolve()
    if not source.exists():
        print(f"[ERROR] Source file not found: {source}")
        sys.exit(1)

    if source.suffix.lower() != ".onnx":
        _log(
            f"[WARNING] Source file does not have .onnx extension: {source}",
            important=True,
        )

    # Resolve model name
    model = args.model
    if not model:
        # Try config
        config_path = script_dir.parent / "config.json"
        if config_path.exists():
            try:
                from config_loader import load_config  # type: ignore
                cfg = load_config(config_path)
                from config_loader import get_matting_config  # type: ignore
                model = get_matting_config(cfg).get("model", "")
            except Exception:
                pass
        # Try to infer from filename
        if not model:
            inferred = _infer_model_from_filename(source.name)
            if inferred:
                model = inferred
                _log(f"[INFO] Inferred model name '{model}' from filename", quiet=args.quiet)
        # Fallback
        if not model:
            model = "u2net"
            _log(f"[INFO] Could not infer model name, defaulting to '{model}'", important=True)

    target = model_dir / f"{model}.onnx"

    if target.exists() and not args.force:
        print(f"[ERROR] Target already exists: {target}. Use --force to overwrite.")
        sys.exit(1)

    if target.exists() and args.force:
        target.unlink()

    # Link or copy
    try:
        os.link(str(source), str(target))
        _log(f"[OK] Linked {source.name} -> {target.name}", important=True)
    except OSError as link_err:
        try:
            shutil.copy2(str(source), str(target))
            _log(
                f"[OK] Copied {source.name} -> {target.name} "
                f"(hardlink unavailable: {link_err})",
                important=True,
            )
        except Exception as copy_err:
            print(f"[ERROR] Could not link or copy: link={link_err}; copy={copy_err}")
            sys.exit(1)

    # Update config
    if _update_config_matting(script_dir, model, source.name):
        _log(
            f"[OK] Updated config.json: matting.model = '{model}', "
            f"matting.model_file = '{source.name}'",
            important=True,
        )
    else:
        _log("[INFO] config.json not found or not writable. Manual update:", important=True)
        _log(
            f'  "matting": {{"model": "{model}", "model_file": "{source.name}"}}',
            important=True,
        )

    _log("\n[DONE] Model linked successfully.", important=True)


def main() -> None:
    raw = sys.argv[1:]

    # Default subcommand: if no subcommand is given, treat as "setup".
    if not raw or (raw[0] not in ("setup", "link", "-h", "--help")):
        raw = ["setup"] + raw

    parser = _build_parser()
    args = parser.parse_args(raw)

    if args.command == "setup":
        _cmd_setup(args)
    elif args.command == "link":
        _cmd_link(args)


if __name__ == "__main__":
    main()
