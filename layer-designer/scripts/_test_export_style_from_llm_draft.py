"""
Smoke test for `export_style.py from-llm-draft`.

Covers Task #38 + #40:
  - happy path (json-file + 2 refs copied), style_loader.validate passes
  - happy path via --json-stdin
  - failure when image_refs references a file that wasn't copied
  - failure on invalid JSON
  - overwrite protection (exits non-zero without --overwrite)
  - overwrite succeeds with --overwrite
  - empty stdin / non-object JSON edge cases
  - --generate-spec with mocked subprocess (edit vs generate mode)
  - --generate-spec replaces refs, --keep-original-refs retains them

NOTE: PathManager.get_workspace_root() is hard-coded to scripts/../ —
no env override exists — so this test writes into the real
`{workspace}/styles/` directory using a `_smoketest_` prefix and
cleans up afterwards (try/finally).

Run: python scripts/_test_export_style_from_llm_draft.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "export_style.py"
WORKSPACE = HERE.parent  # layer-designer/
STYLES_DIR = WORKSPACE / "styles"
PY = sys.executable

PREFIX = "_smoketest_"

results: list[tuple[str, bool, str]] = []
_created: list[Path] = []  # style dirs we made — must clean up


def check(label: str, predicate, hint: str = "") -> None:
    try:
        ok = bool(predicate())
    except Exception as e:
        results.append((label, False, f"{type(e).__name__}: {e}"))
        return
    results.append((label, ok, hint if not ok else ""))


def style_dir(name: str) -> Path:
    p = STYLES_DIR / (PREFIX + name)
    if p not in _created:
        _created.append(p)
    return p


SAMPLE_STYLE = {
    "schema_version": "1.0",
    "name": "PLACEHOLDER",  # overridden by --name
    "description": "Smoke test style",
    "image_refs": [
        {
            "path": "button.png",
            "role": "Button reference",
            "use_for": ["button"],
        },
        {
            "path": "card.png",
            "role": "Card reference",
            "use_for": ["card", "panel"],
        },
    ],
    "palette": {
        "role": {"primary": "#3B82F6", "surface": "#FFFFFF"},
        "semantic": {"info": "#0EA5E9"},
    },
    "typography": {"font_family": "Inter"},
    "spacing": {"base": 8},
    "shape": {"button_radius": 4, "corner_radius_md": 8},
    "elevation": {"preset": "soft"},
    "motif": {"tags": ["flat", "minimalist"]},
    "rules": {
        "interaction": ["Hover lifts shadow one tier"],
        "layout": ["Align to 8px grid"],
    },
    "style_anchor_override": None,
}


def write_png(path: Path) -> None:
    """Write a minimal valid 1x1 PNG."""
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452"
        "00000001000000010806000000"
        "1f15c4890000000d49444154789c63"
        "f8cf00000003000100"
        "01c0a0c5a90000000049454e44ae426082"
    )
    path.write_bytes(png_bytes)


def run(args: list[str], stdin_str: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(SCRIPT), *args],
        input=stdin_str,
        text=True,
        capture_output=True,
    )


def run_tests() -> None:
    tmp_str = tempfile.mkdtemp(prefix="_smoketest_export_style_")
    tmp = Path(tmp_str)
    try:
        # Fixture: two source images
        src_btn = tmp / "src_button.png"
        src_card = tmp / "src_card.png"
        write_png(src_btn)
        write_png(src_card)

        # Fixture: draft style.json on disk for --json-file path
        draft_path = tmp / "draft.json"
        draft_path.write_text(json.dumps(SAMPLE_STYLE), encoding="utf-8")

        # ---- [1] happy path: --json-file + 2 copy-references -----------
        target1 = style_dir("smoke-style")
        proc = run([
            "from-llm-draft",
            "--name", target1.name,
            "--json-file", str(draft_path),
            "--copy-references", f"{src_btn}:button.png",
            "--copy-references", f"{src_card}:card.png",
        ])
        check("[1a] from-llm-draft --json-file exits 0",
              lambda: proc.returncode == 0,
              f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        check("[1b] style.json written",
              lambda: (target1 / "style.json").exists())
        check("[1c] button.png copied",
              lambda: (target1 / "button.png").exists())
        check("[1d] card.png copied",
              lambda: (target1 / "card.png").exists())

        if (target1 / "style.json").exists():
            written = json.loads((target1 / "style.json").read_text(encoding="utf-8"))
            check("[1e] written name overridden",
                  lambda: written["name"] == target1.name)
            check("[1f] schema_version preserved",
                  lambda: written["schema_version"] == "1.0")
            check("[1g] image_refs count == 2",
                  lambda: len(written["image_refs"]) == 2)

        # Validate via style_loader
        sys.path.insert(0, str(HERE))
        import style_loader  # noqa: E402
        try:
            loaded = style_loader.load_style(target1)
            errs = style_loader.validate(loaded, target1)
            check("[1h] style_loader.validate returns no errors",
                  lambda: errs == [], f"errors: {errs}")
        except Exception as e:
            check("[1h] style_loader.validate returns no errors",
                  lambda: False, f"raised {type(e).__name__}: {e}")

        # ---- [2] --json-stdin happy path -------------------------------
        target2 = style_dir("stdin-style")
        stdin_style = dict(SAMPLE_STYLE)
        stdin_style["description"] = "From stdin"
        stdin_style["image_refs"] = [
            {"path": "ref.png", "role": "Single", "use_for": ["button"]},
        ]
        proc = run([
            "from-llm-draft",
            "--name", target2.name,
            "--json-stdin",
            "--copy-references", f"{src_btn}:ref.png",
        ], stdin_str=json.dumps(stdin_style))
        check("[2a] --json-stdin exits 0",
              lambda: proc.returncode == 0,
              f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        check("[2b] stdin style folder created",
              lambda: (target2 / "style.json").exists())
        check("[2c] stdin ref copied",
              lambda: (target2 / "ref.png").exists())

        # ---- [3] missing image_refs path fails cleanly -----------------
        target3 = style_dir("missing-ref-style")
        bad_style = dict(SAMPLE_STYLE)
        bad_style["image_refs"] = [
            {"path": "never_copied.png", "role": "x", "use_for": ["button"]},
        ]
        bad_path = tmp / "bad.json"
        bad_path.write_text(json.dumps(bad_style), encoding="utf-8")
        proc = run([
            "from-llm-draft",
            "--name", target3.name,
            "--json-file", str(bad_path),
        ])
        check("[3a] missing image_refs path exits non-zero",
              lambda: proc.returncode != 0,
              f"rc={proc.returncode}\nstdout={proc.stdout}")
        check("[3b] error mentions the missing path",
              lambda: "never_copied.png" in (proc.stdout + proc.stderr),
              f"stdout={proc.stdout}\nstderr={proc.stderr}")
        # Style folder was created by _ensure_style_dir before validation kicked in.
        # Acceptable as long as no style.json was persisted.
        check("[3c] no style.json written for failed run",
              lambda: not (target3 / "style.json").exists())

        # ---- [4] invalid JSON fails cleanly ----------------------------
        target4 = style_dir("bad-json-style")
        bad_json_path = tmp / "bad_syntax.json"
        bad_json_path.write_text("{ this is not valid json", encoding="utf-8")
        proc = run([
            "from-llm-draft",
            "--name", target4.name,
            "--json-file", str(bad_json_path),
        ])
        check("[4a] invalid JSON exits non-zero",
              lambda: proc.returncode != 0)
        check("[4b] error mentions invalid JSON",
              lambda: "Invalid JSON" in (proc.stdout + proc.stderr),
              f"stdout={proc.stdout}\nstderr={proc.stderr}")

        # ---- [5] overwrite protection (re-run target1) ------------------
        proc = run([
            "from-llm-draft",
            "--name", target1.name,
            "--json-file", str(draft_path),
            "--copy-references", f"{src_btn}:button.png",
            "--copy-references", f"{src_card}:card.png",
        ])
        check("[5a] re-write without --overwrite exits non-zero",
              lambda: proc.returncode != 0)
        check("[5b] error mentions already exists",
              lambda: "already exists" in (proc.stdout + proc.stderr),
              f"stdout={proc.stdout}\nstderr={proc.stderr}")

        # ---- [6] --overwrite succeeds -----------------------------------
        modified = dict(SAMPLE_STYLE)
        modified["description"] = "Modified via overwrite"
        modified["image_refs"] = [
            {"path": "button.png", "role": "New role", "use_for": ["button"]},
        ]
        modified_path = tmp / "modified.json"
        modified_path.write_text(json.dumps(modified), encoding="utf-8")
        proc = run([
            "from-llm-draft",
            "--name", target1.name,
            "--json-file", str(modified_path),
            "--overwrite",
        ])
        check("[6a] --overwrite succeeds",
              lambda: proc.returncode == 0,
              f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        if (target1 / "style.json").exists():
            after = json.loads((target1 / "style.json").read_text(encoding="utf-8"))
            check("[6b] description updated",
                  lambda: after["description"] == "Modified via overwrite")
            check("[6c] image_refs replaced",
                  lambda: len(after["image_refs"]) == 1
                          and after["image_refs"][0]["role"] == "New role")

        # ---- [7] empty stdin fails -------------------------------------
        target7 = style_dir("empty-stdin")
        proc = run([
            "from-llm-draft",
            "--name", target7.name,
            "--json-stdin",
        ], stdin_str="")
        check("[7a] empty stdin exits non-zero",
              lambda: proc.returncode != 0)
        check("[7b] error mentions empty",
              lambda: "Empty" in (proc.stdout + proc.stderr),
              f"stdout={proc.stdout}\nstderr={proc.stderr}")

        # ---- [8] non-object JSON (array) fails -------------------------
        target8 = style_dir("arr-style")
        arr_path = tmp / "arr.json"
        arr_path.write_text("[1,2,3]", encoding="utf-8")
        proc = run([
            "from-llm-draft",
            "--name", target8.name,
            "--json-file", str(arr_path),
        ])
        check("[8a] array JSON exits non-zero",
              lambda: proc.returncode != 0)
        check("[8b] error mentions object expected",
              lambda: "object" in (proc.stdout + proc.stderr),
              f"stdout={proc.stdout}")

        # ---- [9] --generate-spec fails gracefully without valid config ----
        target9 = style_dir("spec-fail")
        proc = run([
            "from-llm-draft",
            "--name", target9.name,
            "--json-file", str(draft_path),
            "--copy-references", f"{src_btn}:button.png",
            "--copy-references", f"{src_card}:card.png",
            "--generate-spec",
        ])
        check("[9a] --generate-spec without config fails non-zero",
              lambda: proc.returncode != 0,
              f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        check("[9b] error mentions spec generation failed",
              lambda: "pec generation failed" in (proc.stdout + proc.stderr),
              f"stdout={proc.stdout}\nstderr={proc.stderr}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cleanup_created() -> None:
    """Remove every _smoketest_* dir we may have created in real styles/."""
    if not STYLES_DIR.exists():
        return
    for d in STYLES_DIR.iterdir():
        if d.is_dir() and d.name.startswith(PREFIX):
            shutil.rmtree(d, ignore_errors=True)


def run_direct_tests() -> None:
    """Direct-import tests for _generate_spec_image and cmd_from_llm_draft."""
    sys.path.insert(0, str(HERE))
    import export_style as es  # noqa: E402
    import style_loader  # noqa: E402

    tmp_str = tempfile.mkdtemp(prefix="_smoketest_export_direct_")
    tmp = Path(tmp_str)
    try:
        test_style_dir = tmp / "test-style"
        test_style_dir.mkdir(parents=True, exist_ok=True)

        # Write dummy refs
        (test_style_dir / "btn.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (test_style_dir / "card.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        style = {
            "schema_version": "1.0",
            "name": "test",
            "motif": {"tags": ["flat"]},
            "palette": {"role": {"primary": "#3B82F6"}},
            "typography": {"font_family": "Inter"},
            "spacing": {"base": 8},
            "shape": {"button_radius": 4},
            "elevation": {"preset": "soft"},
            "rules": {},
            "style_anchor_override": None,
        }

        # ---- [10] _generate_spec_image with refs -> edit mode ------------
        def _mock_run_edit(cmd, **kwargs):
            # cmd is a list; find --output value and write a dummy PNG there
            try:
                out_idx = cmd.index("--output") + 1
                out_path = Path(cmd[out_idx])
            except (ValueError, IndexError):
                out_path = test_style_dir / "spec.png"
            out_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_mock_run_edit):
            spec_path = es._generate_spec_image(
                style=style,
                style_dir=test_style_dir,
                config_path=None,
                spec_size="1024x1024",
                spec_quality="low",
                copied_refs=["btn.png", "card.png"],
            )
        check("[10a] _generate_spec_image returns spec.png",
              lambda: spec_path.name == "spec.png")
        check("[10b] spec.png was created",
              lambda: spec_path.exists())

        # ---- [11] _generate_spec_image without refs -> generate mode -----
        (test_style_dir / "spec.png").unlink(missing_ok=True)

        def _mock_run_generate(cmd, **kwargs):
            # Verify it's generate mode
            assert "generate" in cmd, f"expected generate in cmd, got {cmd}"
            out_idx = cmd.index("--output") + 1
            out_path = Path(cmd[out_idx])
            out_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_mock_run_generate):
            spec_path2 = es._generate_spec_image(
                style=style,
                style_dir=test_style_dir,
                config_path=None,
                spec_size="1024x1024",
                spec_quality="low",
                copied_refs=[],
            )
        check("[11a] generate mode produces spec.png",
              lambda: spec_path2.exists())

        # ---- [12] cmd_from_llm_draft + --generate-spec replaces refs -----
        target12 = style_dir("direct-spec")
        draft = dict(SAMPLE_STYLE)
        draft["image_refs"] = [
            {"path": "btn.png", "role": "btn", "use_for": ["button"]},
        ]
        draft_path = tmp / "draft12.json"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")

        # Copy a source image into the temp area
        src_btn = tmp / "src_btn.png"
        write_png(src_btn)

        def _mock_run_for_cmd(cmd, **kwargs):
            out_idx = cmd.index("--output") + 1
            out_path = Path(cmd[out_idx])
            out_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_mock_run_for_cmd):
            args = es.build_parser().parse_args([
                "from-llm-draft",
                "--name", target12.name,
                "--json-file", str(draft_path),
                "--copy-references", f"{src_btn}:btn.png",
                "--generate-spec",
            ])
            es.cmd_from_llm_draft(args)

        written = json.loads((target12 / "style.json").read_text(encoding="utf-8"))
        check("[12a] spec replaces image_refs",
              lambda: len(written["image_refs"]) == 1
                      and written["image_refs"][0]["path"] == "spec.png")
        check("[12b] spec use_for is ['*']",
              lambda: written["image_refs"][0]["use_for"] == ["*"])
        check("[12c] original ref removed",
              lambda: not (target12 / "btn.png").exists())

        # ---- [13] --keep-original-refs retains originals -----------------
        target13 = style_dir("keep-refs")
        with patch("subprocess.run", side_effect=_mock_run_for_cmd):
            args = es.build_parser().parse_args([
                "from-llm-draft",
                "--name", target13.name,
                "--json-file", str(draft_path),
                "--copy-references", f"{src_btn}:btn.png",
                "--generate-spec",
                "--keep-original-refs",
            ])
            es.cmd_from_llm_draft(args)

        check("[13a] original ref kept",
              lambda: (target13 / "btn.png").exists())
        written13 = json.loads((target13 / "style.json").read_text(encoding="utf-8"))
        check("[13b] image_refs still spec-only",
              lambda: len(written13["image_refs"]) == 1
                      and written13["image_refs"][0]["path"] == "spec.png")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    try:
        run_tests()
        run_direct_tests()
    finally:
        cleanup_created()

    failed = [(n, h) for (n, ok, h) in results if not ok]
    for name, ok, hint in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"  -- {hint}" if hint else ""))
    print()
    if failed:
        print(f"{len(failed)} test(s) failed:")
        for name, hint in failed:
            print(f"  - {name}: {hint}")
        return 1
    print(f"all {len(results)} from-llm-draft smoke tests PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        cleanup_created()
        sys.exit(2)
