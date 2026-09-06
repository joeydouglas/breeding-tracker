"""Task 3.2 — assertions unique to honey-badger-haze-pheno-hunt's data.

The shared Task 3.x acceptance contract — plant count, zero field loss,
verification evidence counts, sandbox isolation, determinism, side-effect
proofs — lives in `tests/test_project_migration_contract.py` and runs against
this project via its `ProjectSpec` in `src/migration_specs.py`. Duplicating
those checks per project is what let Task 3.1's and Task 3.2's copies drift
apart, so only genuinely project-specific facts remain here.

What makes this project's data different, and why each matters:

* `auto_create` is **true** while the project template's default is `false`.
  On mule-fuel the registry value and the template default were both `false`,
  so that project's "sourced from the registry" assertion could not tell a
  registry read apart from a silent template default. Here they differ, so
  this is the first project whose data can *prove* Task 3.0 §8's
  highest-risk finding was handled.
* `notes_meta` is **present** (absent on mule-fuel, materialised there).
* Every plant carries all 18 inventoried keys — there is no MG07-style record
  missing `photo_count`/`photos_drive_url`.
* Plant IDs are the contiguous HBH01..HBH23 run; mule-fuel skips MG09.

Skips cleanly if the real tracker is not present on this machine.
"""

import json

import pytest

from migration_specs import HONEY_BADGER_HAZE as SPEC
from helpers_migration import (  # noqa: F401  (fixture re-export)
    PLANT_TEMPLATE,
    PROJECT_TEMPLATE,
    migrate_project,
    no_side_effects,
    registry_entry,
    tracker_json,
)

requires_real_data = pytest.mark.skipif(
    not SPEC.tracker.exists(),
    reason=f"real tracker for {SPEC.slug} not present",
)

pytestmark = requires_real_data


@pytest.fixture
def migrated(tmp_path, no_side_effects):
    return migrate_project(SPEC, tmp_path)


def test_plant_ids_are_the_contiguous_hbh01_to_hbh23_run(migrated):
    """No numbering gap here (mule-fuel skips MG09); a migration that
    renumbered or dropped a record would show up as a changed run."""
    _, out = migrated
    expected = [f"HBH{n:02d}" for n in range(1, SPEC.plant_count + 1)]
    assert sorted(p["id"] for p in tracker_json(SPEC)["plants"]) == expected
    assert sorted(p.stem for p in (out / "plants").glob("*.md")) == expected


def test_every_plant_carries_all_eighteen_keys():
    """Task 3.0 §2b: unlike mule-fuel's MG07, no record here is missing a key."""
    for plant in tracker_json(SPEC)["plants"]:
        assert set(plant) == set(SPEC.plant_keys), plant["id"]


def test_drive_folders_survive_whole_without_the_mule_fuel_reports_subkeys(migrated):
    """Task 3.0 §4: `reports`/`reports_url` are unique to mule-fuel. This
    project's 8-subkey shape must round-trip exactly, and the migration must
    not invent the sibling project's extra keys."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    source = tracker_json(SPEC)["drive_folders"]
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["drive_folders"] == source
    assert set(got["drive_folders"]) == {
        "dashboard",
        "dashboard_url",
        "notes",
        "notes_url",
        "photos",
        "photos_url",
        "root",
        "root_url",
    }
    assert "reports" not in got["drive_folders"]


def test_notes_meta_is_present_and_survives_verbatim(migrated):
    """Task 3.0 §6: absent on mule-fuel (defaulted there), present here — so it
    must be preserved, not overwritten with the template's `{}` default.

    Includes its `migration_note`, whose text is factually stale (it claims
    `plants[]` is empty while 23 plants exist). Migration preserves data
    verbatim; it is not the migration's job to correct or drop stale prose.
    """
    from project_markdown import load_schema, read_project

    summary, out = migrated
    source = tracker_json(SPEC)["notes_meta"]
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["notes_meta"] == source
    assert got["notes_meta"] != {}
    assert got["notes_meta"]["source_doc"] is None
    assert "migration_note" in got["notes_meta"]
    assert "notes_meta" not in summary.defaulted_fields.get("project", [])


def test_corrected_reading_is_the_only_defaulted_plant_field(migrated):
    """Task 3.0 §9.4 — declared in the template, absent from this project's
    data, so it materialises as null on every plant and must never be
    fabricated. And because every plant here has all 18 other keys, it must be
    the ONLY defaulted field on every record."""
    from plant_markdown import load_schema, read_plant

    summary, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    for plant in tracker_json(SPEC)["plants"]:
        plant_id = plant["id"]
        assert summary.defaulted_fields[plant_id] == ["corrected_reading"], plant_id
        got = read_plant(out / "plants" / f"{plant_id}.md", schema=schema)
        assert got["corrected_reading"] is None


def test_photos_and_photo_counts_survive_including_the_one_photoless_plant(migrated):
    """22 of 23 plants carry photos; `photos[]` passes through opaquely and the
    empty-list plant must stay an empty list, not become null."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    photoless = []
    for plant in tracker_json(SPEC)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert got["photos"] == plant["photos"], plant["id"]
        assert got["photo_count"] == plant["photo_count"], plant["id"]
        if not plant["photos"]:
            photoless.append(plant["id"])
            assert got["photos"] == []
    assert len(photoless) == 1


def test_nullable_and_always_null_plant_fields_stay_null(migrated):
    """Task 3.0 §3/§9.5: types come from the template, never inferred from
    observed data. `selection_notes` is non-null on exactly one plant here, so
    a reader that coerced nulls to "" would be caught."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    always_null = (
        "germ_date",
        "veg_start",
        "flower_flip",
        "harvest_date",
        "vigor",
        "structure",
        "issues",
        "sex",
    )
    with_selection_notes = []
    for plant in tracker_json(SPEC)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        for field in always_null:
            assert plant[field] is None, f"source drifted: {plant['id']}.{field}"
            assert got[field] is None, f"{plant['id']}.{field}"
        assert got["terpene_notes"] is None
        assert got["selection_notes"] == plant["selection_notes"]
        if plant["selection_notes"] is not None:
            with_selection_notes.append(plant["id"])
    assert with_selection_notes == ["HBH15"]


def test_statuses_survive_across_all_three_values(migrated):
    """active/culled/keeper all appear here; a status lost or normalised would
    change downstream dashboards."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    seen = set()
    for plant in tracker_json(SPEC)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert got["status"] == plant["status"], plant["id"]
        seen.add(got["status"])
    assert seen == {"active", "culled", "keeper"}


def test_original_notes_survive_verbatim(migrated):
    """`original_notes` is the raw Discord text and is frontmatter, not body;
    every plant here has a non-empty one."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    for plant in tracker_json(SPEC)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert plant["original_notes"] != ""
        assert got["original_notes"] == plant["original_notes"], plant["id"]


def test_auto_create_is_registry_true_and_not_the_template_default(migrated):
    """The discriminating case mule-fuel could not provide.

    mule-fuel's registry `auto_create` is `false`, which is also the project
    template's default — so on that project a migration that ignored
    registry.json entirely would have produced an identical file and passed.
    This project's value is `true`, so equality with the registry here is real
    evidence the registry was read.
    """
    from project_markdown import load_schema, read_project

    _, out = migrated
    project_schema = load_schema(PROJECT_TEMPLATE)
    template_default = project_schema["auto_create"]["default"]
    entry = registry_entry(SPEC)

    assert template_default is False
    assert entry["auto_create"] is True
    assert entry["auto_create"] != template_default

    got = read_project(out / "project.md", schema=project_schema)
    assert got["auto_create"] is True
    assert "auto_create" not in tracker_json(SPEC)


def test_the_hbh_id_routing_regex_is_exact(migrated):
    """A mangled backslash silently breaks ID routing for every future Discord
    note in this project."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["plant_id_prefixes"][0]["prefix"] == "HBH"
    assert got["plant_id_prefixes"][0]["pattern"] == r"\bHBH[\s\-]?(\d{1,2})\b"


def test_the_stale_migration_note_is_preserved_not_corrected(migrated):
    """The source note asserts `plants[]` is intentionally empty while 23
    plants exist. It is stale in the SOURCE. Correcting or dropping prose
    during a migration is data loss and would hide the drift from the human
    who needs to see it."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    note = got["notes_meta"]["migration_note"]
    assert note == tracker_json(SPEC)["notes_meta"]["migration_note"]
    assert len(tracker_json(SPEC)["plants"]) == SPEC.plant_count
    assert json.dumps(got["notes_meta"], sort_keys=True) == json.dumps(
        tracker_json(SPEC)["notes_meta"], sort_keys=True
    )
