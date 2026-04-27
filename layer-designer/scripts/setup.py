#!/usr/bin/env python3
"""
Setup script for Layered Design Generator.

Run this once after cloning the repository to:
1. Install required Python packages
2. Download the U²Net ONNX model (~176 MB) for background removal
3. Create config.json from the example template

Usage:
    cd layer-designer
    python scripts/setup.py
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Official model download URLs (for mirror fallback)
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


def _download_via_requests(url: str, output_path: Path) -> bool:
    """Download a file via requests with progress display."""
    try:
        import requests
    except ImportError:
        print("   requests not available (should be installed with rembg)")
        return False

    print(f"   Downloading from: {url}")
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            percent = downloaded / total * 100
                            print(
                                f"   Progress: {percent:.1f}% ({downloaded/1024/1024:.1f} MB / {total/1024/1024:.1f} MB)",
                                end="\r",
                            )
            print()  # newline after progress
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"[OK] Model downloaded: {output_path} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"   Download failed: {e}")
        return False


def check_python_version():
    """Ensure Python 3.9+ is available."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(f"ERROR: Python {version.major}.{version.minor} detected. Python 3.9+ is required.")
        sys.exit(1)
    print(f"[OK] Python {version.major}.{version.minor}.{version.micro}")


def install_dependencies():
    """Install required packages from pip."""
    deps = ["openai>=2.0", "Pillow", "rembg>=2.0", "numpy"]
    print(f"\n[INSTALL] Installing dependencies: {', '.join(deps)}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", *deps])
        print("[OK] Dependencies installed")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to install dependencies: {e}")
        sys.exit(1)


def download_model(model_name: str = "u2net", mirror: str = ""):
    """Download a rembg ONNX model to the skill-internal models directory.

    Tries rembg's built-in downloader first, then falls back to mirror
    download via requests if a mirror prefix is provided.
    """
    script_dir = Path(__file__).parent.resolve()
    model_dir = script_dir.parent / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(model_dir)

    model_path = model_dir / f"{model_name}.onnx"

    # If user specified a custom model_file, create a hard link so rembg can find it
    # (do this before checking existence, in case the link is missing)
    try:
        from config_loader import load_config, get_matting_config
        cfg_path = script_dir.parent / "config.json"
        if cfg_path.exists():
            cfg = load_config(cfg_path)
            matting = get_matting_config(cfg)
            model_file = matting.get("model_file", "")
            if model_file:
                custom_path = model_dir / model_file
                if custom_path.exists() and not model_path.exists():
                    try:
                        os.link(str(custom_path), str(model_path))
                        print(f"\n[OK] Linked {model_file} -> {model_name}.onnx")
                    except Exception as e:
                        print(f"\n[WARNING] Could not link model file: {e}")
    except Exception:
        pass

    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Model already exists: {model_path} ({size_mb:.1f} MB)")
        return

    print(f"\n[DOWNLOAD] {model_name} model. This may take a few minutes...")

    # 1. Try rembg official downloader
    official_failed = False
    try:
        from rembg.session_factory import new_session
        new_session(model_name)
        if model_path.exists():
            size_mb = model_path.stat().st_size / (1024 * 1024)
            print(f"[OK] Model downloaded: {model_path} ({size_mb:.1f} MB)")
            return
    except Exception as e:
        official_failed = True
        print(f"   Official downloader failed: {e}")

    # 2. Try mirror / direct download via requests
    official_url = _MODEL_OFFICIAL_URLS.get(model_name)
    if official_url:
        urls_to_try = []
        if mirror:
            urls_to_try.append(mirror.rstrip("/") + "/" + official_url)
        urls_to_try.append(official_url)

        for url in urls_to_try:
            print(f"\n   Trying alternative source...")
            if _download_via_requests(url, model_path):
                return

    # 3. Final fallback: print manual instructions
    print(f"\n[ERROR] Automatic download failed for {model_name}.")
    print(f"   Please manually download the model and place it at:")
    print(f"   {model_path}")
    if official_url:
        print(f"\n   Official URL: {official_url}")
        print(f"   Mirror URL (China mainland): https://ghproxy.cn/{official_url}")
        print(f"\n   Example:")
        print(f'   curl -L -o "{model_path}" "https://ghproxy.cn/{official_url}"')
    sys.exit(1)


def create_config():
    """Copy config.example.json to config.json if it doesn't exist."""
    script_dir = Path(__file__).parent.resolve()
    example = script_dir.parent / "config.example.json"
    target = script_dir.parent / "config.json"

    if target.exists():
        print(f"\n[OK] config.json already exists")
        return

    if not example.exists():
        print(f"\n[WARNING] config.example.json not found at {example}")
        return

    shutil.copy2(example, target)
    print(f"\n[OK] Created {target}")
    print("   [IMPORTANT] Edit config.json and fill in your API endpoint and key before use.")


def verify_installation():
    """Run a quick sanity check."""
    print("\n[VERIFY] Verifying installation...")
    try:
        import openai
        import PIL
        import rembg
        import numpy
        print("[OK] All packages importable")
    except ImportError as e:
        print(f"ERROR: Import failed: {e}")
        sys.exit(1)

    script_dir = Path(__file__).parent.resolve()
    model_dir = script_dir.parent / "models"
    if (model_dir / "u2net.onnx").exists():
        print("[OK] U²Net model present")
    else:
        print("[WARNING] U²Net model missing")

    # Check configured matting model
    try:
        from config_loader import load_config, get_matting_config
        config_path = script_dir.parent / "config.json"
        if config_path.exists():
            cfg = load_config(config_path)
            matting = get_matting_config(cfg)
            model_name = matting["model"]
            if model_name != "u2net":
                if (model_dir / f"{model_name}.onnx").exists():
                    print(f"[OK] Matting model ({model_name}) present")
                else:
                    print(f"[WARNING] Matting model ({model_name}) missing — run setup again after setting matting.model in config.json")
    except Exception as e:
        print(f"[WARNING] Could not verify matting model: {e}")

    config = script_dir.parent / "config.json"
    if config.exists():
        print("[OK] config.json present")
    else:
        print("[WARNING] config.json missing — remember to create it")

    print("\n[DONE] Setup complete! You're ready to use the Layered Design Generator.")
    if not config.exists():
        print("   → Run: cp layer-designer/config.example.json layer-designer/config.json")
        print("   → Then edit config.json with your API credentials.")


def main():
    parser = argparse.ArgumentParser(description="Layered Design Generator Setup")
    parser.add_argument(
        "--mirror",
        default="",
        help="Download mirror prefix, e.g. https://ghproxy.cn (for China mainland users)",
    )
    args = parser.parse_args()

    # Resolve mirror: CLI arg > config.json > empty
    mirror = args.mirror
    if not mirror:
        try:
            from config_loader import load_config
            script_dir = Path(__file__).parent.resolve()
            config_path = script_dir.parent / "config.json"
            if config_path.exists():
                cfg = load_config(config_path)
                mirror = cfg.get("download_mirror", "")
        except Exception:
            pass

    print("=" * 60)
    print("  Layered Design Generator - Setup")
    print("=" * 60)

    check_python_version()
    install_dependencies()
    download_model("u2net", mirror=mirror)

    # If config already exists, also download the configured matting model
    try:
        from config_loader import load_config, get_matting_config
        script_dir = Path(__file__).parent.resolve()
        config_path = script_dir.parent / "config.json"
        if config_path.exists():
            cfg = load_config(config_path)
            matting = get_matting_config(cfg)
            if matting["model"] != "u2net":
                download_model(matting["model"], mirror=mirror)
    except Exception as e:
        print(f"\n[WARNING] Could not check matting model config: {e}")

    create_config()
    verify_installation()


if __name__ == "__main__":
    main()
