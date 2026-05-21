"""Mock-test export_style.py: manual / from-project / add-reference subcommands."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_style
from path_manager import PathManager
import style_loader


def patch_styles_root(tmp_path: Path):
    """Redirect PathManager.get_styles_dir() to a tmp location."""
    original = PathManager.get_styles_dir
    PathManager.get_styles_dir = classmethod(lambda cls: tmp_path)  # type: ignore
    return original


def restore_styles_root(original):
    PathManager.get_styles_dir = original


# ---------------------------------------------------------------------------
# Test 1: parse_copy_reference
# ---------------------------------------------------------------------------
spec = "C:/x.png:button reference:button:button.png"
ref = export_style._parse_copy_reference(spec)
assert ref == {
    "source": "C:/x.png",
    "role": "button reference",
    "use_for_first": "button",
    "dest_filename": "button.png",
}, f"unexpected: {ref}"
print("[1] _parse_copy_reference parses 4-field spec: PASS")

# Test 1b: rejects malformed specs
try:
    export_style._parse_copy_reference("only:three:fields")
    assert False, "should have raised"
except ValueError:
    pass
try:
    export_style._parse_copy_reference("a::c:d")  # empty role
    assert False, "should have raised on empty field"
except ValueError:
    pass
print("[1b] _parse_copy_reference rejects bad specs: PASS")


# ---------------------------------------------------------------------------
# Test 2: manual subcommand creates template
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    original = patch_styles_root(tmp_path)
    try:
        export_style.main([
            "manual", "--name", "retro-arcade",
            "--description", "80s neon arcade",
        ])
        out = tmp_path / "retro-arcade" / "style.json"
        assert out.exists(), f"missing: {out}"
        with out.open(encoding="utf-8") as f:
            doc = json.load(f)
        assert doc["schema_version"] == "1.0"
        assert doc["name"] == "retro-arcade"
        assert doc["description"] == "80s neon arcade"
        assert doc["image_refs"] == []
        assert doc["style_anchor_override"] is None
        # Should validate (loads cleanly)
        style_loader.load_style(out.parent)
    finally:
        restore_styles_root(original)
print("[2] manual: writes valid empty template: PASS")


# ---------------------------------------------------------------------------
# Test 3: manual refuses to overwrite without --overwrite
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    original = patch_styles_root(tmp_path)
    try:
        export_style.main(["manual", "--name", "dup"])
        # Second call without --overwrite should sys.exit(1)
        try:
            export_style.main(["manual", "--name", "dup"])
            assert False, "should have exited"
        except SystemExit as e:
            assert e.code == 1
        # With --overwrite it succeeds
        export_style.main(["manual", "--name", "dup", "--overwrite",
                           "--description", "changed"])
        with (tmp_path / "dup" / "style.json").open(encoding="utf-8") as f:
            doc = json.load(f)
        assert doc["description"] == "changed"
    finally:
        restore_styles_root(original)
print("[3] manual: --overwrite gate works: PASS")


# ---------------------------------------------------------------------------
# Test 4: from-project captures style_anchor + copies refs
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    styles_root = tmp_path / "styles"
    project_root = tmp_path / "project-data"
    project_root.mkdir()
    original_styles = patch_styles_root(styles_root)
    # Monkeypatch PathManager to point at tmp project structure
    original_pm = PathManager.__init__
    original_layer_path = PathManager.get_layer_plan_path
    original_phase_dir = PathManager.get_phase_dir

    def fake_init(self, project_name, config_path=None):
        self.project_name = project_name
        self._root = project_root / project_name

    def fake_layer_plan_path(self):
        return self._root / "02-confirmation" / "layer_plan.json"

    def fake_phase_dir(self, phase):
        return self._root / {"requirements": "01-requirements",
                             "confirmation": "02-confirmation"}[phase]

    PathManager.__init__ = fake_init
    PathManager.get_layer_plan_path = fake_layer_plan_path
    PathManager.get_phase_dir = fake_phase_dir

    try:
        # Create fake project
        proj = project_root / "my-app"
        confirmation = proj / "02-confirmation"
        confirmation.mkdir(parents=True)
        previews = proj / "01-requirements" / "previews"
        previews.mkdir(parents=True)
        preview_file = previews / "preview_v1_001.png"
        preview_file.write_bytes(b"X")

        layer_plan = {
            "style_anchor": "flat, primary #3B82F6, Inter font, 8px grid",
            "layers": [],
        }
        (confirmation / "layer_plan.json").write_text(
            json.dumps(layer_plan), encoding="utf-8"
        )

        ref_src = tmp_path / "external_button.png"
        ref_src.write_bytes(b"X")

        export_style.main([
            "from-project", "--config", "config.json",
            "--project", "my-app", "--name", "saas-blue",
            "--description", "SaaS dashboard",
            "--copy-references", f"{ref_src}:button reference:button:button.png",
        ])

        out_dir = styles_root / "saas-blue"
        out_file = out_dir / "style.json"
        assert out_file.exists()
        with out_file.open(encoding="utf-8") as f:
            doc = json.load(f)
        assert doc["name"] == "saas-blue"
        assert doc["description"] == "SaaS dashboard"
        assert doc["style_anchor_override"] == "flat, primary #3B82F6, Inter font, 8px grid"
        assert doc["derived_from"] is not None and "preview_v1_001.png" in doc["derived_from"]
        assert len(doc["image_refs"]) == 1
        ref = doc["image_refs"][0]
        assert ref["path"] == "button.png"
        assert ref["role"] == "button reference"
        assert ref["use_for"] == ["button"]
        # File was actually copied
        assert (out_dir / "button.png").exists()
        # And it loads/validates cleanly via style_loader
        loaded = style_loader.load_style(out_dir)
        assert style_loader.derive_anchor(loaded) == "flat, primary #3B82F6, Inter font, 8px grid"
    finally:
        restore_styles_root(original_styles)
        PathManager.__init__ = original_pm
        PathManager.get_layer_plan_path = original_layer_path
        PathManager.get_phase_dir = original_phase_dir
print("[4] from-project: captures anchor, copies refs, validates: PASS")


# ---------------------------------------------------------------------------
# Test 5: add-reference appends + dedupes use_for
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    styles_root = tmp_path / "styles"
    original_styles = patch_styles_root(styles_root)

    # Patch resolve_style to find the style we just created in tmp
    original_resolve = PathManager.resolve_style

    def fake_resolve_style(cls, name):
        candidate = styles_root / name
        if not (candidate / "style.json").exists():
            raise FileNotFoundError(f"Style '{name}' not found")
        return candidate

    PathManager.resolve_style = classmethod(fake_resolve_style)

    try:
        export_style.main(["manual", "--name", "base-style"])

        new_ref = tmp_path / "new_button.png"
        new_ref.write_bytes(b"X")

        export_style.main([
            "add-reference", "--style", "base-style",
            "--image", str(new_ref),
            "--role", "primary button look",
            "--use-for", "button",
            "--use-for", "button",      # duplicate, should dedupe
            "--use-for", "control",
            "--rename", "button.png",
        ])

        out = styles_root / "base-style" / "style.json"
        with out.open(encoding="utf-8") as f:
            doc = json.load(f)
        assert len(doc["image_refs"]) == 1
        ref = doc["image_refs"][0]
        assert ref["path"] == "button.png"
        assert ref["role"] == "primary button look"
        assert ref["use_for"] == ["button", "control"]  # dedupe preserved order
        assert (styles_root / "base-style" / "button.png").exists()

        # Adding another with the SAME dest filename (no --overwrite) should fail
        try:
            export_style.main([
                "add-reference", "--style", "base-style",
                "--image", str(new_ref),
                "--role", "different role",
                "--use-for", "button",
                "--rename", "button.png",
            ])
            assert False, "should have exited"
        except SystemExit as e:
            assert e.code == 1

        # With --overwrite the existing image_refs entry is replaced (not duplicated)
        export_style.main([
            "add-reference", "--style", "base-style",
            "--image", str(new_ref),
            "--role", "updated role",
            "--use-for", "button",
            "--rename", "button.png",
            "--overwrite",
        ])
        with out.open(encoding="utf-8") as f:
            doc = json.load(f)
        assert len(doc["image_refs"]) == 1, "should not duplicate"
        assert doc["image_refs"][0]["role"] == "updated role"
    finally:
        restore_styles_root(original_styles)
        PathManager.resolve_style = original_resolve
print("[5] add-reference: append, dedupe use_for, --overwrite replaces in place: PASS")


# ---------------------------------------------------------------------------
# Test 6: add-reference on unknown style fails cleanly
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    styles_root = tmp_path / "styles"
    original_styles = patch_styles_root(styles_root)
    original_resolve = PathManager.resolve_style

    def fake_resolve_style(cls, name):
        raise FileNotFoundError(f"Style '{name}' not found under {styles_root}")

    PathManager.resolve_style = classmethod(fake_resolve_style)

    img = tmp_path / "x.png"
    img.write_bytes(b"X")
    try:
        try:
            export_style.main([
                "add-reference", "--style", "nope",
                "--image", str(img), "--role", "r", "--use-for", "x",
            ])
            assert False, "should have exited"
        except SystemExit as e:
            assert e.code == 1
    finally:
        restore_styles_root(original_styles)
        PathManager.resolve_style = original_resolve
print("[6] add-reference rejects unknown style: PASS")


print("\nall export_style tests PASS")
