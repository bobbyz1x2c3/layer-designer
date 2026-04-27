#!/usr/bin/env python3
"""
Cache and output cleanup utility for Layered Design Generator.

Workflow role:
- On-demand utility. Not part of the standard 8-phase flow.
- Use between workflow runs or to free disk space.

Usage:
    # Clean only cache/temp files for a project
    python clean_cache.py --project my-dashboard --cache-only

    # Clean entire project output
    python clean_cache.py --project my-dashboard --all

    # Clean specific phase only
    python clean_cache.py --project my-dashboard --phase 03-rough-design

    # Clean all intermediate files but keep final output (07-output)
    python clean_cache.py --project my-dashboard --keep-final

    # Dry run (show what would be deleted without deleting)
    python clean_cache.py --project my-dashboard --all --dry-run
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from config_loader import load_config, get_paths_config
from path_manager import PathManager


def get_project_dir(project_name: str, config_path: str | None = None) -> Path:
    """Resolve project directory from config or default."""
    try:
        cfg = get_paths_config(load_config(config_path))
        base = Path(cfg.get("output_root", "./output"))
    except Exception:
        base = Path("./output")
    return base / project_name


def delete_path(path: Path, dry_run: bool = False) -> bool:
    """Delete a file or directory. Returns True if deleted."""
    if not path.exists():
        return False
    if dry_run:
        return True
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except Exception as e:
        print(f"  Failed to delete {path}: {e}", file=sys.stderr)
        return False


def clean_cache(project_name: str, config_path: str | None = None,
                cache_only: bool = False, all_output: bool = False,
                phase: str | None = None, keep_final: bool = False,
                dry_run: bool = False) -> dict:
    """
    Clean project output according to specified mode.

    Returns:
        dict with deleted_items, skipped_items, bytes_freed (estimated)
    """
    pm = PathManager(project_name, config_path=config_path)
    project_dir = pm.project_dir

    if not project_dir.exists():
        print(f"Project not found: {project_dir}")
        return {"deleted": [], "skipped": [], "bytes_freed": 0}

    deleted = []
    skipped = []
    bytes_freed = 0

    def collect_size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    def mark_for_deletion(path: Path):
        nonlocal bytes_freed
        if path.exists():
            size = collect_size(path)
            action = "[DRY-RUN] Would delete" if dry_run else "Deleting"
            print(f"  {action}: {path.relative_to(project_dir)}")
            if delete_path(path, dry_run):
                deleted.append(str(path.relative_to(project_dir)))
                bytes_freed += size
            else:
                skipped.append(str(path.relative_to(project_dir)))

    print(f"\nCleaning project: {project_name}")
    print(f"Project path: {project_dir}")
    print(f"Mode: ", end="")

    if all_output:
        print("DELETE ALL OUTPUT")
        mark_for_deletion(project_dir)
    elif cache_only:
        print("CACHE ONLY")
        cache_dir = pm.get_cache_dir()
        mark_for_deletion(cache_dir)
    elif phase:
        print(f"PHASE: {phase}")
        target = project_dir / phase
        mark_for_deletion(target)
    elif keep_final:
        print("KEEP FINAL, DELETE INTERMEDIATE")
        # Delete everything except 07-output
        for item in sorted(project_dir.iterdir()):
            if item.name == "07-output":
                print(f"  Preserving: {item.name}")
                continue
            if item.is_dir() or item.is_file():
                mark_for_deletion(item)
    else:
        # Default: clean cache + temp only
        print("CACHE + TEMP (default)")
        cache_dir = pm.get_cache_dir()
        mark_for_deletion(cache_dir)

    print(f"\nSummary:")
    print(f"  Items {'would be ' if dry_run else ''}deleted: {len(deleted)}")
    print(f"  Items skipped: {len(skipped)}")
    print(f"  Estimated space freed: {bytes_freed / 1024 / 1024:.2f} MB")

    return {
        "deleted": deleted,
        "skipped": skipped,
        "bytes_freed": bytes_freed,
        "dry_run": dry_run,
    }


def list_projects(config_path: str | None = None) -> list[str]:
    """List all projects in the output root."""
    try:
        cfg = get_paths_config(load_config(config_path))
        base = Path(cfg.get("output_root", "./output"))
    except Exception:
        base = Path("./output")

    if not base.exists():
        return []
    return [d.name for d in base.iterdir() if d.is_dir()]


def main():
    parser = argparse.ArgumentParser(description="Clean Layered Design Generator output")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--project", "-p", required=True, help="Project name to clean")
    parser.add_argument("--all", action="store_true", help="Delete entire project output")
    parser.add_argument("--cache-only", action="store_true", help="Delete only cache/temp files")
    parser.add_argument("--phase", help="Delete specific phase folder (e.g., 03-rough-design)")
    parser.add_argument("--keep-final", action="store_true",
                        help="Delete intermediate phases, preserve 07-output")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be deleted without deleting")
    parser.add_argument("--list-projects", action="store_true", help="List all projects and exit")
    args = parser.parse_args()

    if args.list_projects:
        projects = list_projects(args.config)
        print("Projects:")
        for name in projects:
            print(f"  - {name}")
        return

    # Validate mutually exclusive options
    modes = [args.all, args.cache_only, bool(args.phase), args.keep_final]
    if sum(modes) > 1:
        print("ERROR: Only one of --all, --cache-only, --phase, --keep-final can be used", file=sys.stderr)
        sys.exit(1)

    result = clean_cache(
        project_name=args.project,
        config_path=args.config,
        cache_only=args.cache_only,
        all_output=args.all,
        phase=args.phase,
        keep_final=args.keep_final,
        dry_run=args.dry_run,
    )

    if not args.dry_run and result["deleted"]:
        # Write cleanup log
        pm = PathManager(args.project, config_path=args.config)
        log_path = pm.project_dir / ".cleanup_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"  Cleanup log: {log_path}")


if __name__ == "__main__":
    main()
