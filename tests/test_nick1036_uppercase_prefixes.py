"""TDD for NICK-1036: uppercase the 'sp' and 'Ltz' plant-ID prefixes.

Full rename (per Joey's explicit choice, not display-only): every place a
plant ID is CONSTRUCTED from PLANT_ID_PREFIX must now produce 'SP01'/'LTZ01'
instead of 'sp01'/'Ltz01'. The regex `pattern` strings stay case-insensitive
((?i) is always applied, see breeding_core.extract_plant_ids_single) so
messages typed in any case still match -- only the *prefix used to build the
output ID string* changes.

RED before the fix: PLANT_ID_PREFIX for spaced-paste is 'sp' (lowercase) and
for lantz is 'Ltz' (mixed case). GREEN after: both are 'SP' / 'LTZ'.
"""
import importlib
import re
import sys
from pathlib import Path

MONITOR_CORE = Path.home() / ".hermes" / "breeding" / "_shared" / "monitor-core"
if str(MONITOR_CORE) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE))
import breeding_core as core  # noqa: E402


def _load_wrapper_config(slug):
    wrapper_dir = Path.home() / ".hermes" / "breeding" / slug
    sys.path.insert(0, str(wrapper_dir))
    try:
        mod = importlib.import_module("monitor_breeding_notes")
        importlib.reload(mod)
        return mod.CONFIG
    finally:
        sys.path.remove(str(wrapper_dir))
        sys.modules.pop("monitor_breeding_notes", None)


def test_spaced_paste_prefix_is_uppercase():
    cfg = _load_wrapper_config("spaced-paste")
    assert cfg["PLANT_ID_PREFIX"] == "SP", (
        f"expected uppercase 'SP', got {cfg['PLANT_ID_PREFIX']!r}"
    )


def test_lantz_prefix_is_uppercase():
    cfg = _load_wrapper_config("lantz")
    assert cfg["PLANT_ID_PREFIX"] == "LTZ", (
        f"expected uppercase 'LTZ', got {cfg['PLANT_ID_PREFIX']!r}"
    )


def test_spaced_paste_extraction_produces_uppercase_id():
    cfg = _load_wrapper_config("spaced-paste")
    ids = core.extract_plant_ids_single(
        "sp05 vigor 8, looking great", cfg["PLANT_ID_PATTERN"], cfg["PLANT_ID_PREFIX"]
    )
    assert ids == ["SP05"], ids


def test_lantz_extraction_produces_uppercase_id():
    cfg = _load_wrapper_config("lantz")
    ids = core.extract_plant_ids_single(
        "ltz03 recovering nicely", cfg["PLANT_ID_PATTERN"], cfg["PLANT_ID_PREFIX"]
    )
    assert ids == ["LTZ03"], ids


def test_gateway_registry_uses_uppercase_prefixes():
    ingest_path = (
        Path.home()
        / ".hermes"
        / "breeding"
        / "_shared"
        / "breeding-ingest"
        / "breeding_tracker"
        / "discord_ingest.py"
    )
    sys.path.insert(0, str(ingest_path.parent.parent))
    try:
        mod = importlib.import_module("breeding_tracker.discord_ingest")
        importlib.reload(mod)
        prefixes = [p for p, _ in mod.PLANT_ID_REGISTRY]
        assert "SP" in prefixes, prefixes
        assert "LTZ" in prefixes, prefixes
        assert "sp" not in prefixes, prefixes
        assert "Ltz" not in prefixes, prefixes
        ids = mod.extract_plant_ids("sp05 vigor 8 and ltz03 recovering")
        assert set(ids) == {"SP05", "LTZ03"}, ids
    finally:
        sys.path.remove(str(ingest_path.parent.parent))
        sys.modules.pop("breeding_tracker.discord_ingest", None)
        sys.modules.pop("breeding_tracker", None)


def test_registry_json_prefixes_are_uppercase():
    import json

    registry_path = (
        Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
    )
    d = json.loads(registry_path.read_text())
    for p in d["projects"]:
        for entry in p.get("plant_id_prefixes", []):
            assert entry["prefix"] == entry["prefix"].upper(), (
                p["slug"], entry["prefix"]
            )


def test_live_markdown_plant_ids_are_uppercase():
    """The actual plants/*.md files and their filenames, post-rename."""
    for slug, prefix in [("spaced-paste", "SP"), ("lantz", "LTZ")]:
        plants_dir = Path.home() / ".hermes" / "breeding" / slug / "plants"
        files = sorted(plants_dir.glob("*.md"))
        assert files, f"no plant files found for {slug}"
        for f in files:
            assert f.stem == f.stem.upper(), f"{slug}: filename {f.name} not uppercase"
            assert f.stem.startswith(prefix), f"{slug}: filename {f.name} wrong prefix"
            text = f.read_text()
            m = re.search(r"^plant_id:\s*(\S+)", text, re.MULTILINE)
            assert m, f"{slug}/{f.name}: no plant_id field"
            assert m.group(1) == f.stem, (
                f"{slug}/{f.name}: plant_id field {m.group(1)!r} != filename stem {f.stem!r}"
            )
            assert m.group(1) == m.group(1).upper(), (
                f"{slug}/{f.name}: plant_id {m.group(1)!r} not uppercase"
            )


def test_live_tracker_json_ids_are_uppercase():
    import json

    for slug in ["spaced-paste", "lantz"]:
        tracker_path = Path.home() / ".hermes" / "breeding" / slug / "tracker.json"
        t = json.loads(tracker_path.read_text())
        for p in t["plants"]:
            pid = p.get("id") or p.get("plant_id")
            assert pid == pid.upper(), (slug, pid)


def test_live_project_md_plant_order_is_uppercase():
    for slug in ["spaced-paste", "lantz"]:
        project_md = Path.home() / ".hermes" / "breeding" / slug / "project.md"
        text = project_md.read_text()
        m = re.search(r"^plant_order:\n((?:- .+\n)+)", text, re.MULTILINE)
        assert m, f"{slug}: no plant_order block found"
        for line in m.group(1).splitlines():
            pid = line.lstrip("- ").strip()
            assert pid == pid.upper(), (slug, pid)


def test_template_docstring_mentions_uppercase_examples_only():
    """The plant-template.md docstring example IDs (Ltz01, PK03) should not
    show a lowercase-prefix example after this fix -- template text is
    documentation Joey specifically asked to update."""
    template_path = (
        Path.home()
        / ".hermes"
        / "breeding"
        / "_shared"
        / "breeding-markdown"
        / "templates"
        / "plant-template.md"
    )
    text = template_path.read_text()
    assert "Ltz01" not in text, "template still shows lowercase-prefix example Ltz01"
