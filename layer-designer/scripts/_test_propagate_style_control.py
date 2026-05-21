"""Mock-test: style_ref + control_type passthrough in
expand_repeats.expand_layer_plan and generate_preview.generate_enhanced_plan."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import expand_repeats


# ---------------------------------------------------------------------------
# expand_repeats: grid + list + non-repeat layers, with style_ref and
# control_type tagging.
# ---------------------------------------------------------------------------

plan = {
    "project": "demo",
    "dimensions": {"width": 1920, "height": 1080},
    "style_anchor": "flat, primary #3B82F6, Inter, 8px grid",
    "style_ref": {
        "name": "saas-blue",
        "dir": "styles/saas-blue",
        "schema_version": "1.0",
    },
    "layers": [
        {
            "id": "title",
            "name": "Title",
            "control_type": None,
            "layout": {"x": 0, "y": 0, "width": 400, "height": 80},
        },
        {
            "id": "metric_grid",
            "name": "Metric Grid",
            "control_type": "card",
            "layout": {"x": 100, "y": 200, "width": 200, "height": 120},
            "repeat_mode": "grid",
            "repeat_config": {"cols": 2, "rows": 2, "gap_x": 16, "gap_y": 16},
        },
        {
            "id": "nav_list",
            "name": "Nav List",
            "control_type": "button",
            "layout": {"x": 0, "y": 600, "width": 180, "height": 40},
            "repeat_mode": "list",
            "repeat_config": {"count": 3, "gap": 8, "direction": "vertical"},
        },
    ],
    "stacking_order": ["Title", "Metric Grid", "Nav List"],
}

expanded = expand_repeats.expand_layer_plan(plan)

# 1) Top-level style_ref must be preserved.
assert "style_ref" in expanded, "expand_layer_plan dropped style_ref"
assert expanded["style_ref"]["name"] == "saas-blue", expanded["style_ref"]
print("[1] style_ref propagates through expand_layer_plan: PASS")

# 2) Grid instances must carry control_type from parent.
grid_instances = [l for l in expanded["layers"] if l.get("is_repeat_instance")
                  and l.get("parent_id") == "metric_grid"]
assert len(grid_instances) == 4, f"expected 4 grid cells, got {len(grid_instances)}"
for inst in grid_instances:
    assert inst.get("control_type") == "card", \
        f"grid cell missing control_type='card': {inst}"
print("[2] grid instances inherit control_type='card' from parent: PASS")

# 3) List instances must carry control_type from parent.
list_instances = [l for l in expanded["layers"] if l.get("is_repeat_instance")
                  and l.get("parent_id") == "nav_list"]
assert len(list_instances) == 3, f"expected 3 list items, got {len(list_instances)}"
for inst in list_instances:
    assert inst.get("control_type") == "button", \
        f"list item missing control_type='button': {inst}"
print("[3] list instances inherit control_type='button' from parent: PASS")

# 4) Non-repeat layer keeps its own control_type=None.
title = next(l for l in expanded["layers"] if l.get("id") == "title")
assert title.get("control_type") is None, title
print("[4] non-repeat layer preserves control_type=None: PASS")

# 5) Parent layers also retain control_type (they're generated separately).
grid_parent = next(l for l in expanded["layers"]
                   if l.get("id") == "metric_grid" and l.get("is_repeat_parent"))
assert grid_parent.get("control_type") == "card", grid_parent
list_parent = next(l for l in expanded["layers"]
                   if l.get("id") == "nav_list" and l.get("is_repeat_parent"))
assert list_parent.get("control_type") == "button", list_parent
print("[5] is_repeat_parent layers retain their own control_type: PASS")

# 6) A plan with NO style_ref / NO control_type fields must round-trip cleanly
# (back-compat: do not inject these fields when absent).
bare_plan = {
    "project": "bare",
    "dimensions": {"width": 800, "height": 600},
    "style_anchor": "minimal",
    "layers": [
        {"id": "logo", "name": "Logo",
         "layout": {"x": 0, "y": 0, "width": 100, "height": 100}},
        {"id": "grid", "name": "Grid",
         "layout": {"x": 0, "y": 100, "width": 50, "height": 50},
         "repeat_mode": "grid",
         "repeat_config": {"cols": 2, "rows": 1}},
    ],
    "stacking_order": ["Logo", "Grid"],
}
expanded_bare = expand_repeats.expand_layer_plan(bare_plan)
assert "style_ref" not in expanded_bare, \
    "expand_layer_plan added style_ref unexpectedly"
for l in expanded_bare["layers"]:
    assert "control_type" not in l, \
        f"layer gained spurious control_type: {l}"
print("[6] bare plan round-trips without style_ref/control_type: PASS")


# ---------------------------------------------------------------------------
# generate_preview: style_ref top-level + control_type per layer pass-through.
# ---------------------------------------------------------------------------

import generate_preview


with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)

    class FakePM:
        def __init__(self, project, config_path=None):
            self.project = project

        @staticmethod
        def get_phase_dir(phase):
            d = tmp_path / phase
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_expanded_layer_plan_path(self, phase="check"):
            return tmp_path / "expanded_layer_plan.json"

        def get_layer_plan_path(self):
            return tmp_path / "layer_plan.json"

        def get_output_dir(self):
            d = tmp_path / "07-output"
            d.mkdir(exist_ok=True)
            return d

        def get_check_dir(self):
            d = tmp_path / "04-check"
            d.mkdir(exist_ok=True)
            return d

    sample_plan = {
        "project": "demo",
        "dimensions": {"width": 1920, "height": 1080},
        "style_anchor": "flat",
        "style_ref": {"name": "saas-blue", "dir": "styles/saas-blue"},
        "layers": [
            {"id": "submit_button", "name": "Submit",
             "control_type": "button",
             "layout": {"x": 0, "y": 0, "width": 100, "height": 40},
             "status": "active"},
            {"id": "main_chart", "name": "Chart",
             "control_type": None,
             "layout": {"x": 0, "y": 100, "width": 400, "height": 300},
             "status": "active"},
            {"id": "logo", "name": "Logo",
             "layout": {"x": 0, "y": 500, "width": 80, "height": 80},
             "status": "active"},
        ],
        "stacking_order": ["Submit", "Chart", "Logo"],
    }
    (tmp_path / "expanded_layer_plan.json").write_text(
        json.dumps(sample_plan), encoding="utf-8"
    )

    with mock.patch.object(generate_preview, "PathManager", FakePM):
        plan_path = generate_preview.generate_enhanced_plan(
            "demo", phase="output", config_path=None,
            apply_detected_layouts=False,
        )

    with open(plan_path, encoding="utf-8-sig") as f:
        enhanced = json.load(f)

    assert enhanced.get("style_ref") == {"name": "saas-blue", "dir": "styles/saas-blue"}, \
        enhanced.get("style_ref")
    print("[7] generate_enhanced_plan propagates top-level style_ref: PASS")

    by_id = {l["id"]: l for l in enhanced["layers"]}
    assert by_id["submit_button"].get("control_type") == "button"
    assert by_id["main_chart"].get("control_type") is None
    assert "control_type" not in by_id["logo"], \
        "layer without control_type should not gain one"
    print("[8] generate_enhanced_plan propagates per-layer control_type: PASS")

    # Back-compat: bare plan without style_ref / control_type
    bare = {
        "project": "bare",
        "dimensions": {"width": 800, "height": 600},
        "style_anchor": "x",
        "layers": [
            {"id": "a", "name": "A",
             "layout": {"x": 0, "y": 0, "width": 100, "height": 100},
             "status": "active"},
        ],
        "stacking_order": ["A"],
    }
    (tmp_path / "expanded_layer_plan.json").write_text(
        json.dumps(bare), encoding="utf-8"
    )
    with mock.patch.object(generate_preview, "PathManager", FakePM):
        plan_path = generate_preview.generate_enhanced_plan(
            "bare", phase="output", config_path=None,
            apply_detected_layouts=False,
        )
    with open(plan_path, encoding="utf-8-sig") as f:
        enhanced_bare = json.load(f)
    assert "style_ref" not in enhanced_bare
    assert "control_type" not in enhanced_bare["layers"][0]
    print("[9] bare plan round-trips through generate_enhanced_plan cleanly: PASS")


print("\nall propagation tests PASS")
