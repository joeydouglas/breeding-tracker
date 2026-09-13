"""Task 3.1 — assertions unique to mule-fuel-x-nana-glue's data.

The shared Task 3.x acceptance contract — plant count, zero field loss,
verification evidence counts, sandbox isolation, determinism, side-effect
proofs — lives in `tests/test_project_migration_contract.py` and runs against
this project via its `ProjectSpec` in `src/migration_specs.py`. Only facts
specific to this project's data remain here.

What makes this project's data different:

* `drive_folders` carries `reports`/`reports_url` subkeys that exist on no
  other project (Task 3.0 §4).
* MG07 alone lacks `photo_count`/`photos_drive_url` and carries extra
  `uploaded`/`context` photo subkeys (Task 3.0 §7a/§9.3).
* Plant IDs skip MG09 — there IS a numbering gap here, unlike honey-badger.
* `genetics`, `breeder_lineage` and `notes_meta` are absent and must be
  materialised from the template.
* Registry `auto_create` is `false`, which EQUALS the template default, so
  this project's data cannot distinguish a registry read from a silent
  template default. That gap is recorded in the spec's `notes` and covered by
  honey-badger-haze, whose value is `true`.

Skips cleanly if the real tracker is not present on this machine.
"""

import pytest

from helpers_migration import (  # noqa: F401  (fixture re-export)
    PLANT_TEMPLATE,
    PROJECT_TEMPLATE,
    migrate_project,
    no_side_effects,
    registry_entry,
    tracker_json,
)
from migration_specs import MULE_FUEL as SPEC

requires_real_data = pytest.mark.skipif(
    not SPEC.tracker.exists(),
    reason=f"real tracker for {SPEC.slug} not present",
)

pytestmark = requires_real_data


@pytest.fixture
def migrated(tmp_path, no_side_effects):
    return migrate_project(SPEC, tmp_path)


def test_drive_folders_reports_subkeys_unique_to_this_project_survive(migrated):
    """Task 3.0 §4: `reports`/`reports_url` exist only on mule-fuel."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["drive_folders"] == tracker_json(SPEC)["drive_folders"]
    assert "reports" in got["drive_folders"]
    assert "reports_url" in got["drive_folders"]


def test_mg07_photo_extra_subkeys_and_missing_fields_are_handled(migrated):
    """Task 3.0 §7a/§9.3: MG07 carries `uploaded`/`context` and lacks
    `photo_count`/`photos_drive_url`."""
    from plant_markdown import load_schema, read_plant

    summary, out = migrated
    source = next(p for p in tracker_json(SPEC)["plants"] if p["id"] == "MG07")
    got = read_plant(out / "plants" / "MG07.md", schema=load_schema(PLANT_TEMPLATE))

    assert got["photos"] == source["photos"]
    assert set(got["photos"][0]) >= {"uploaded", "context"}
    # `corrected_reading` is absent from all 45 plants here (Task 3.0 §2b: it
    # exists on exactly one lantz plant), so it is defaulted on every record;
    # `photo_count`/`photos_drive_url` are defaulted on MG07 ALONE.
    assert set(summary.defaulted_fields["MG07"]) == {
        "corrected_reading",
        "photo_count",
        "photos_drive_url",
    }
    assert got["photo_count"] == 0
    assert got["photos_drive_url"] == ""
    assert got["corrected_reading"] is None


def test_mg07_is_the_only_record_missing_photo_fields():
    """Pins the hazard to one record, from the source rather than the output."""
    incomplete = {
        p["id"]
        for p in tracker_json(SPEC)["plants"]
        if "photo_count" not in p or "photos_drive_url" not in p
    }
    assert incomplete == set(SPEC.incomplete_plants) == {"MG07"}


def test_the_plant_id_run_has_a_gap_at_mg09():
    """Unlike honey-badger's contiguous run, this project skips MG09. A
    migration that "helpfully" renumbered records would close the gap."""
    ids = sorted(p["id"] for p in tracker_json(SPEC)["plants"])
    assert "MG09" not in ids
    assert len(ids) == SPEC.plant_count


def test_project_level_fields_absent_here_are_materialised_from_the_template(
    migrated,
):
    """Task 3.0 §6: `genetics`/`breeder_lineage`/`notes_meta` exist on
    honey-badger but not here, so they must be filled from the template AND
    recorded as defaulted — never silently conflated with a preserved value."""
    summary, _ = migrated
    source = tracker_json(SPEC)
    defaulted = set(summary.defaulted_fields.get("project", ()))
    assert defaulted == {"genetics", "breeder_lineage", "notes_meta"}
    for field in defaulted:
        assert field not in source


def test_auto_create_matches_the_template_default_so_this_project_cannot_prove_it(
    migrated,
):
    """Documents, as an executable assertion, why this project's routing-field
    check is true but NOT discriminating.

    Task 3.0 §8's risk is that `auto_create` is read from the template instead
    of registry.json. Here both are `false`, so a migration that never opened
    the registry would produce a byte-identical project.md and pass. If this
    assertion ever fails, the registry changed and this project became a
    discriminating case — at which point the honey-badger-specific proof is no
    longer the only one.
    """
    from project_markdown import load_schema

    entry = registry_entry(SPEC)
    schema = load_schema(PROJECT_TEMPLATE)
    assert entry["auto_create"] == schema["auto_create"]["default"] is False
    assert "cannot distinguish" in SPEC.notes or "discriminating" in SPEC.notes
