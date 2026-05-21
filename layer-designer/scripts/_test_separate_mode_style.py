"""Mock-test separate_mode.py: generate_layer signature, prompt builder
style_active flag, and subprocess command shape with --style-from."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import separate_mode


# ---------------------------------------------------------------------------
# 1. _build_pl_prompt: style_active suppresses inline anchor
# ---------------------------------------------------------------------------
p_no_style = separate_mode._build_pl_prompt(
    "submit_button", "primary CTA button", "flat blue anchor",
    opacity=1.0, style_active=False,
)
p_styled = separate_mode._build_pl_prompt(
    "submit_button", "primary CTA button", "flat blue anchor",
    opacity=1.0, style_active=True,
)
assert "flat blue anchor" in p_no_style, "anchor should appear when style_active=False"
assert "flat blue anchor" not in p_styled, "anchor should be omitted when style_active=True"
print("[1] _build_pl_prompt suppresses inline anchor when style_active=True: PASS")


# ---------------------------------------------------------------------------
# 2. _build_bg_prompt: same suppression
# ---------------------------------------------------------------------------
b_no_style = separate_mode._build_bg_prompt(
    "background", "solid surface", "flat blue anchor", style_active=False,
)
b_styled = separate_mode._build_bg_prompt(
    "background", "solid surface", "flat blue anchor", style_active=True,
)
assert "flat blue anchor" in b_no_style
assert "flat blue anchor" not in b_styled
print("[2] _build_bg_prompt suppresses inline anchor when style_active=True: PASS")


# ---------------------------------------------------------------------------
# 3. generate_layer subprocess command: appends --style-from + --control-type
# ---------------------------------------------------------------------------
captured = {"cmd": None}


def fake_run_cmd(cmd, *, timeout=300, quiet=False):
    captured["cmd"] = list(cmd)
    # Pretend success and that the output file exists
    out_idx = cmd.index("--output") + 1
    Path(cmd[out_idx]).parent.mkdir(parents=True, exist_ok=True)
    Path(cmd[out_idx]).write_bytes(b"fake")
    return True, "ok"


separate_mode._run_cmd = fake_run_cmd


class FakePM:
    project_name = "demo"

    def __init__(self, root: Path):
        self.root = root

    def get_layer_dir(self, layer_id):
        return self.root / layer_id

    def get_layer_path(self, layer_id):
        return self.root / layer_id / f"{layer_id}.png"


with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    pm = FakePM(tmp_path)
    style_dir = tmp_path / "fake-style"
    style_dir.mkdir()
    (style_dir / "style.json").write_text("{}", encoding="utf-8")
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"X")

    # 3a) style_active + control_type
    layer = {"id": "submit_button", "control_type": "button",
             "contents": "primary CTA", "style_anchor": "flat blue",
             "opacity": 1.0}
    lid, ok, _ = separate_mode.generate_layer(
        layer, str(ref), "config.json", pm, 1024, 256, "low",
        style_dir=str(style_dir),
    )
    assert ok and lid == "submit_button"
    cmd = captured["cmd"]
    assert "--style-from" in cmd and str(style_dir) in cmd
    assert "--control-type" in cmd and "button" in cmd
    assert "--phase" in cmd and "layer" in cmd
    print("[3a] generate_layer(style_active=True, control_type='button'): PASS")

    # 3b) style_active + control_type=None (should NOT pass --control-type)
    captured["cmd"] = None
    layer2 = {"id": "main_chart", "control_type": None,
              "contents": "complex chart", "style_anchor": "flat blue",
              "opacity": 1.0}
    _, ok2, _ = separate_mode.generate_layer(
        layer2, str(ref), "config.json", pm, 1024, 256, "low",
        style_dir=str(style_dir),
    )
    assert ok2
    cmd = captured["cmd"]
    assert "--style-from" in cmd
    assert "--control-type" not in cmd
    print("[3b] generate_layer(style_active=True, control_type=None) -> no --control-type: PASS")

    # 3c) style_dir=None  (back-compat path)
    captured["cmd"] = None
    layer3 = {"id": "footer", "contents": "footer", "style_anchor": "flat blue",
              "opacity": 1.0}
    _, ok3, _ = separate_mode.generate_layer(
        layer3, str(ref), "config.json", pm, 1024, 256, "low",
        style_dir=None,
    )
    assert ok3
    cmd = captured["cmd"]
    assert "--style-from" not in cmd
    assert "--control-type" not in cmd
    assert "--phase" not in cmd
    # And prompt should contain the inline anchor (style_active=False)
    prompt_idx = cmd.index("--prompt") + 1
    assert "flat blue" in cmd[prompt_idx]
    print("[3c] generate_layer(style_dir=None) back-compat (no style flags, inline anchor): PASS")


# ---------------------------------------------------------------------------
# 4. gen_commands tuple shape: 8 elements unpack into generate_layer
# ---------------------------------------------------------------------------
import inspect
sig = inspect.signature(separate_mode.generate_layer)
params = list(sig.parameters)
assert params == [
    "layer_info", "reference_path", "config_path", "pm",
    "canvas_w", "canvas_h", "quality", "style_dir",
], f"unexpected signature: {params}"
print("[4] generate_layer has 8-parameter signature: PASS")


print("\nall separate_mode tests PASS")
