"""Tests for the NICK-948 live ``project.md`` generator glue.

The writer itself is already covered by Task 1.2's suite; these tests cover
only what this glue adds: sourcing the right real fields, recording
``plant_order``, never touching ``tracker.json`` or ``plants/``, and refusing
to clobber an existing live file.

Every test runs against a COPY of a real live tracker in tmp_path -- nothing
here reads or writes ``~/.hermes/breeding/<project>``.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import generate_live_project_md as gen  # noqa: E402
from breeding_tracker import project_markdown  # noqa: E402
from breeding_tracker import tracker_migration  # noqa: E402

LIVE_ROOT = Path.home() / ".hermes" / "breeding"
REGISTRY = LIVE_ROOT / "_shared" / "breeding-meta" / "registry.json"
TEMPLATE = _REPO_ROOT / "breeding_tracker" / "templates" / "project-template.md"

ALL_SLUGS = [
    "lantz",
    "mule-fuel-x-nana-glue",
    "honey-badger-haze-pheno-hunt",
    "kibungan-pheno-hunt",
    "spaced-paste",
    "paloma-coma",
]


@pytest.fixture
def sandbox(tmp_path):
    """A tmp copy of one live project's tracker.json (+ a stub plants dir)."""

    def _make(slug):
        project_dir = tmp_path / slug
        project_dir.mkdir()
        shutil.copy2(LIVE_ROOT / slug / "tracker.json", project_dir / "tracker.json")
        (project_dir / "plants").mkdir()
        return project_dir

    return _make


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_record_carries_every_project_field_from_the_real_tracker(slug, sandbox):
    """No project-level tracker key is silently dropped (``plants`` excepted)."""
    project_dir = sandbox(slug)
    tracker = json.loads((project_dir / "tracker.json").read_text())
    record = gen.build_record(project_dir / "tracker.json", REGISTRY, slug, TEMPLATE)

    for key, value in tracker.items():
        if key == "plants":
            continue
        assert record[key] == value, f"{slug}: {key} not preserved verbatim"


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_routing_fields_come_from_the_registry_not_the_template_default(slug, sandbox):
    """``auto_create``/``plant_id_prefixes`` exist only in registry.json."""
    project_dir = sandbox(slug)
    entry = tracker_migration.load_registry_entry(REGISTRY, slug)
    record = gen.build_record(project_dir / "tracker.json", REGISTRY, slug, TEMPLATE)

    assert record["auto_create"] == entry["auto_create"]
    assert record["plant_id_prefixes"] == entry["plant_id_prefixes"]


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_plant_order_matches_the_tracker_array_order(slug, sandbox):
    """Order is caller-visible state; spaced-paste is NOT in ID order."""
    project_dir = sandbox(slug)
    tracker = json.loads((project_dir / "tracker.json").read_text())
    record = gen.build_record(project_dir / "tracker.json", REGISTRY, slug, TEMPLATE)

    assert record["plant_order"] == [p["id"] for p in tracker["plants"]]


def test_spaced_paste_order_is_not_merely_sorted(sandbox):
    """Guards against a generator that sorts instead of preserving order."""
    project_dir = sandbox("spaced-paste")
    record = gen.build_record(
        project_dir / "tracker.json", REGISTRY, "spaced-paste", TEMPLATE
    )
    assert record["plant_order"] != sorted(record["plant_order"])


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_written_file_round_trips_through_the_canonical_schema(slug, sandbox):
    """``read_project(write_project(x)) == x`` for every real project."""
    project_dir = sandbox(slug)
    record = gen.generate(project_dir, REGISTRY, slug, TEMPLATE)

    schema = project_markdown.load_schema(TEMPLATE)
    reread = project_markdown.read_project(project_dir / "project.md", schema=schema)
    for key, value in record.items():
        assert reread[key] == value, f"{slug}: {key} did not round-trip"


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_generation_never_touches_tracker_json_or_plants(slug, sandbox):
    project_dir = sandbox(slug)
    before = tracker_migration.file_md5(project_dir / "tracker.json")
    plants_before = sorted(p.name for p in (project_dir / "plants").iterdir())

    gen.generate(project_dir, REGISTRY, slug, TEMPLATE)

    assert tracker_migration.file_md5(project_dir / "tracker.json") == before
    assert sorted(p.name for p in (project_dir / "plants").iterdir()) == plants_before


def test_refuses_to_clobber_an_existing_project_md(sandbox):
    project_dir = sandbox("lantz")
    gen.generate(project_dir, REGISTRY, "lantz", TEMPLATE)
    original = (project_dir / "project.md").read_bytes()

    with pytest.raises(FileExistsError):
        gen.generate(project_dir, REGISTRY, "lantz", TEMPLATE)

    assert (project_dir / "project.md").read_bytes() == original


def test_force_allows_a_deliberate_rewrite(sandbox):
    project_dir = sandbox("lantz")
    gen.generate(project_dir, REGISTRY, "lantz", TEMPLATE)
    gen.generate(project_dir, REGISTRY, "lantz", TEMPLATE, force=True)
    assert (project_dir / "project.md").exists()


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_generated_file_satisfies_the_live_load_tracker_path(slug, sandbox):
    """The actual bug: ``markdown_backend.load_tracker`` must stop raising."""
    from breeding_tracker import markdown_backend  # noqa: PLC0415

    project_dir = sandbox(slug)
    gen.generate(project_dir, REGISTRY, slug, TEMPLATE)

    tracker = markdown_backend.load_tracker(project_dir / "tracker.json")
    entry = tracker_migration.load_registry_entry(REGISTRY, slug)
    source = json.loads((project_dir / "tracker.json").read_text())
    # cross_name comes from the TRACKER, not the registry: for spaced-paste the
    # two genuinely disagree ("Spaced Paste (Dulce de Uva x Nana Glue)" vs
    # "Spaced Paste"), and the tracker is the source of truth for every field
    # except the two registry-owned routing ones.
    assert tracker["cross_name"] == source["cross_name"]
    assert tracker["auto_create"] == entry["auto_create"]
    assert tracker["plants"] == []  # stub plants dir; plant cutover is Task 7.2
    assert "plant_order" not in tracker  # popped by the backend on load
