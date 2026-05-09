#!/usr/bin/env python3
"""
layer-designer CLI entry point.

Wraps core scripts and provides an `update` subcommand for pulling
latest releases and auto-migrating config.

Usage:
    layer-designer.py update
    layer-designer.py generate --prompt "..." --output out.png --size 1024x1024
    layer-designer.py edit --image ref.png --prompt "..." --output out.png
    layer-designer.py validate-size --width 1920 --height 1080
    layer-designer.py migrate-config
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

__version__ = "0.3.1-dev"

# Project root is the directory containing this script
ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
CONFIG_PATH = ROOT / "config.json"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = False):
    """Run a shell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _get_current_version() -> str:
    """Return current version from git tag, or short commit hash."""
    rc, out, _ = _run(["git", "describe", "--tags", "--always"])
    if rc == 0 and out:
        return out
    rc, out, _ = _run(["git", "rev-parse", "--short", "HEAD"])
    return out if rc == 0 else "unknown"


def _get_latest_tag() -> str | None:
    """Return the latest semver tag from origin, or None."""
    _run(["git", "fetch", "--tags"])
    rc, out, _ = _run(["git", "tag", "-l"])
    if rc != 0 or not out:
        return None
    tags = [t.strip() for t in out.splitlines() if t.strip()]
    if not tags:
        return None
    # Sort by semver-ish: strip leading 'v', split by dot, pad to 3 parts
    def _sort_key(t: str):
        s = re.sub(r"^[vV]", "", t)
        parts = s.replace("-", ".").split(".")
        numeric = []
        for p in parts:
            m = re.match(r"(\d+)", p)
            numeric.append(int(m.group(1)) if m else 0)
        while len(numeric) < 3:
            numeric.append(0)
        return tuple(numeric)
    tags.sort(key=_sort_key, reverse=True)
    return tags[0]


def _version_lt(a: str, b: str) -> bool:
    """Rough semver compare: a < b?"""
    def _parse(v: str):
        s = re.sub(r"^[vV]", "", v)
        parts = s.replace("-", ".").split(".")
        numeric = []
        for p in parts:
            m = re.match(r"(\d+)", p)
            numeric.append(int(m.group(1)) if m else 0)
        while len(numeric) < 3:
            numeric.append(0)
        return tuple(numeric)
    return _parse(a) < _parse(b)


def cmd_update(_args):
    """Check latest tag, pull if newer, then auto-migrate config."""
    print(f"[update] Current version: {_get_current_version()}")
    latest = _get_latest_tag()
    if not latest:
        print("[update] No tags found. Nothing to update.")
        return

    current = _get_current_version()
    print(f"[update] Latest available tag: {latest}")

    if not _version_lt(current, latest):
        print(f"[update] Already up to date ({current}).")
        return

    print(f"[update] Newer release available: {latest}")
    ans = input(f"Pull and checkout {latest}? [y/N] ").strip().lower()
    if ans not in ("y", "yes"):
        print("[update] Aborted.")
        return

    rc, out, err = _run(["git", "checkout", latest], check=False)
    if rc != 0:
        # Try pull then checkout again in case local is behind
        _run(["git", "pull"], check=False)
        rc, out, err = _run(["git", "checkout", latest], check=False)
    if rc != 0:
        print(f"[update] ERROR: failed to checkout {latest}\n{err}", file=sys.stderr)
        sys.exit(1)

    print(f"[update] Checked out {latest}.")

    # Auto-migrate config
    migrate_script = SCRIPTS / "migrate_config.py"
    if migrate_script.exists() and CONFIG_PATH.exists():
        print("[update] Running config migration...")
        rc, out, err = _run(
            [sys.executable, str(migrate_script), "--config", str(CONFIG_PATH)],
            check=False,
        )
        if rc == 0:
            print("[update] Config migrated successfully.")
        else:
            print(f"[update] Config migration warning:\n{err}", file=sys.stderr)
    else:
        print("[update] migrate_config.py not found; skipping config migration.")

    print("[update] Done.")


def cmd_generate(args):
    """Forward to generate_image.py generate."""
    cmd = [
        sys.executable,
        str(SCRIPTS / "generate_image.py"),
        "generate",
        "--config", str(CONFIG_PATH),
        "--prompt", args.prompt,
        "--output", args.output,
    ]
    if args.size:
        cmd += ["--size", args.size]
    if args.quality:
        cmd += ["--quality", args.quality]
    if args.model:
        cmd += ["--model", args.model]
    if args.background:
        cmd += ["--background", args.background]
    if args.n:
        cmd += ["--n", str(args.n)]
    os.execvp(sys.executable, cmd)


def cmd_edit(args):
    """Forward to generate_image.py edit."""
    cmd = [
        sys.executable,
        str(SCRIPTS / "generate_image.py"),
        "edit",
        "--config", str(CONFIG_PATH),
        "--image", *args.image,
        "--prompt", args.prompt,
        "--output", args.output,
    ]
    if args.size:
        cmd += ["--size", args.size]
    if args.quality:
        cmd += ["--quality", args.quality]
    if args.model:
        cmd += ["--model", args.model]
    if args.background:
        cmd += ["--background", args.background]
    os.execvp(sys.executable, cmd)


def cmd_validate_size(args):
    """Forward to validate_size.py."""
    cmd = [
        sys.executable,
        str(SCRIPTS / "validate_size.py"),
        "--config", str(CONFIG_PATH),
        "--width", str(args.width),
        "--height", str(args.height),
    ]
    if args.downsize_ratio is not None:
        cmd += ["--downsize-ratio", str(args.downsize_ratio)]
    if args.model:
        cmd += ["--model", args.model]
    if args.project:
        cmd += ["--project", args.project]
    os.execvp(sys.executable, cmd)


def cmd_migrate_config(args):
    """Forward to migrate_config.py."""
    cmd = [
        sys.executable,
        str(SCRIPTS / "migrate_config.py"),
        "--config", str(CONFIG_PATH),
    ]
    if args.dry_run:
        cmd += ["--dry-run"]
    os.execvp(sys.executable, cmd)


def main():
    parser = argparse.ArgumentParser(
        prog="layer-designer",
        description="Layer Designer CLI — wrapper for core scripts",
    )
    parser.add_argument("--version", "-v", action="version", version=f"layer-designer {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # update
    subparsers.add_parser("update", help="Check latest tag, pull updates, auto-migrate config")

    # generate
    gen_parser = subparsers.add_parser("generate", help="Text-to-image generation")
    gen_parser.add_argument("--prompt", "-p", required=True)
    gen_parser.add_argument("--output", "-o", required=True)
    gen_parser.add_argument("--size", default="1024x1024")
    gen_parser.add_argument("--quality", default="low", choices=["low", "medium", "high", "auto"])
    gen_parser.add_argument("--model", default=None)
    gen_parser.add_argument("--background", default="auto", choices=["transparent", "opaque", "auto"])
    gen_parser.add_argument("--n", type=int, default=1)

    # edit
    edit_parser = subparsers.add_parser("edit", help="Image-to-image editing")
    edit_parser.add_argument("--image", "-i", nargs="+", required=True)
    edit_parser.add_argument("--prompt", "-p", required=True)
    edit_parser.add_argument("--output", "-o", required=True)
    edit_parser.add_argument("--size", default="1024x1024")
    edit_parser.add_argument("--quality", default="low", choices=["low", "medium", "high", "auto"])
    edit_parser.add_argument("--model", default=None)
    edit_parser.add_argument("--background", default="auto", choices=["transparent", "opaque", "auto"])

    # validate-size
    vs_parser = subparsers.add_parser("validate-size", help="Validate image generation size")
    vs_parser.add_argument("--width", "-W", type=int, required=True)
    vs_parser.add_argument("--height", "-H", type=int, required=True)
    vs_parser.add_argument("--downsize-ratio", "-d", type=float, default=0.5)
    vs_parser.add_argument("--model", "-m", default=None)
    vs_parser.add_argument("--project", "-p", default=None)

    # migrate-config
    mc_parser = subparsers.add_parser("migrate-config", help="Migrate config.json to latest schema")
    mc_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    handlers = {
        "update": cmd_update,
        "generate": cmd_generate,
        "edit": cmd_edit,
        "validate-size": cmd_validate_size,
        "migrate-config": cmd_migrate_config,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
