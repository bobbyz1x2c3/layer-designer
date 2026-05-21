"""Mock-test generate_variants.py: --style / --style-from / --control-type
forwarding to generate_image.py edit subprocess."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_variants


captured: list[list[str]] = []


class FakeResult:
    returncode = 0
    stderr = ""
    stdout = ""


def fake_run(cmd, *args, **kwargs):
    captured.append(list(cmd))
    return FakeResult()


# ---------------------------------------------------------------------------
# Setup: patch subprocess
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    base_img = tmp_path / "button_normal.png"
    base_img.write_bytes(b"X")
    out_dir = tmp_path / "out"
    style_dir = tmp_path / "fake-style"
    style_dir.mkdir()
    (style_dir / "style.json").write_text("{}", encoding="utf-8")

    # ---- Test 1: --style-from + --control-type ----
    captured.clear()
    with mock.patch.object(generate_variants.subprocess, "run", fake_run):
        try:
            generate_variants.main()
        except SystemExit:
            pass

        sys.argv = [
            "generate_variants.py",
            "--image", str(base_img),
            "--control-type", "button",
            "--states", "hover", "active",
            "--output-dir", str(out_dir),
            "--style-from", str(style_dir),
        ]
        generate_variants.main()

    assert len(captured) == 2, f"expected 2 subprocess calls (one per state), got {len(captured)}"
    for cmd in captured:
        assert "--style-from" in cmd, cmd
        assert str(style_dir) in cmd
        assert "--phase" in cmd
        phase_idx = cmd.index("--phase")
        assert cmd[phase_idx + 1] == "variant"
        assert "--control-type" in cmd
        ct_idx = cmd.index("--control-type")
        assert cmd[ct_idx + 1] == "button"
    print("[1] --style-from + control_type=button forwards correctly: PASS")

    # Manifest should record style_ref
    manifest_path = out_dir / "button_normal_variants_manifest.json"
    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["style_ref"] == {"name": None, "dir": str(style_dir)}
    print("[1b] manifest records style_ref: PASS")

    # ---- Test 2: --style (name lookup) ----
    captured.clear()
    sys.argv = [
        "generate_variants.py",
        "--image", str(base_img),
        "--control-type", "card",
        "--states", "hover",
        "--output-dir", str(out_dir / "card"),
        "--style", "my-style",
    ]
    with mock.patch.object(generate_variants.subprocess, "run", fake_run):
        generate_variants.main()
    assert len(captured) == 1
    cmd = captured[0]
    assert "--style" in cmd and "my-style" in cmd
    assert "--style-from" not in cmd
    assert "--phase" in cmd and cmd[cmd.index("--phase") + 1] == "variant"
    assert "--control-type" in cmd and cmd[cmd.index("--control-type") + 1] == "card"
    print("[2] --style my-style + custom control_type='card' forwards correctly: PASS")

    # ---- Test 3: No style flags (back-compat) ----
    captured.clear()
    sys.argv = [
        "generate_variants.py",
        "--image", str(base_img),
        "--control-type", "button",
        "--states", "hover",
        "--output-dir", str(out_dir / "nostyle"),
    ]
    with mock.patch.object(generate_variants.subprocess, "run", fake_run):
        generate_variants.main()
    assert len(captured) == 1
    cmd = captured[0]
    assert "--style" not in cmd
    assert "--style-from" not in cmd
    assert "--phase" not in cmd
    # control_type is currently NOT forwarded when no style — it only matters for prompt selection.
    # The original behavior did not pass --control-type to generate_image.py either.
    print("[3] no style flags -> no --style/--phase forwarded (back-compat): PASS")

    manifest_no_style = (out_dir / "nostyle" / "button_normal_variants_manifest.json")
    with manifest_no_style.open(encoding="utf-8") as f:
        manifest = json.load(f)
    assert "style_ref" not in manifest, "back-compat manifest should not include style_ref"
    print("[3b] back-compat manifest omits style_ref: PASS")

    # ---- Test 4: mutex of --style and --style-from ----
    captured.clear()
    sys.argv = [
        "generate_variants.py",
        "--image", str(base_img),
        "--style", "a", "--style-from", str(style_dir),
        "--states", "hover", "--output-dir", str(out_dir / "mutex"),
    ]
    try:
        with mock.patch.object(generate_variants.subprocess, "run", fake_run):
            generate_variants.main()
        assert False, "argparse should have rejected the mutex pair"
    except SystemExit as e:
        assert e.code == 2  # argparse exit code for usage error
    print("[4] --style and --style-from are mutually exclusive: PASS")

    # ---- Test 5: get_state_prompt fallback for unknown control_type ----
    p = generate_variants.get_state_prompt("card", "hover")
    # Should fall through to "generic" prompts since "card" isn't in DEFAULT_STATE_PROMPTS
    assert "Same element" in p, f"unexpected prompt: {p}"
    print("[5] unknown control_type uses 'generic' prompt template: PASS")


print("\nall generate_variants tests PASS")
