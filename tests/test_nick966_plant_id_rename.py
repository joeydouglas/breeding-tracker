"""NICK-966: the migrated plant markdown corpus must be keyed ``plant_id:``.

Joey's decision (recorded on NICK-701, 2026-09-07): ``plant_id`` is the
canonical ID key for the markdown format. NICK-965 fixed the *runtime*
read/write path (``breeding_core`` / ``markdown_backend`` via
``plant_record.plant_id_of``). This module pins the *migration* side of the
same decision, which NICK-965 did not touch:

* ``templates/plant-template.md`` must DECLARE the field as ``plant_id``, so
  ``write_plant``'s schema-driven field ordering emits it first and
  ``read_plant(..., schema=...)`` types it as a string.
* ``tracker_migration`` must RENAME on the way out: ``tracker.json``'s native
  key is ``id`` (it is the pre-Phase-2 JSON format's own spelling, and
  ``json_backend`` still depends on it byte-for-byte for a NICK-949
  rollback), so the migration reads ``id`` and writes ``plant_id``.

The failure mode these tests exist to prevent is subtle and was reachable by
doing only half the rename: with the template declaring ``plant_id`` but
``build_plant_record`` still copying the source dict verbatim, every migrated
file would carry BOTH ``id: MG07`` (copied from the tracker) and
``plant_id: null`` (materialised from the template default). That is exactly
the dual-key shape ``plant_record.plant_id_of`` raises "conflicting ids" on,
i.e. a corrupt record, written by the very tool meant to produce clean ones.
"""

import json
from pathlib import Path

import pytest

from breeding_tracker.plant_markdown import load_schema, read_plant
from breeding_tracker.tracker_migration import (
    CANONICAL_PLANT_ID_KEY,
    SOURCE_PLANT_ID_KEY,
    build_plant_record,
    migrate_tracker,
    verify_migration,
)

REPO = Path(__file__).resolve().parents[1]
PLANT_TEMPLATE = REPO / "breeding_tracker" / "templates" / "plant-template.md"
PROJECT_TEMPLATE = REPO / "breeding_tracker" / "templates" / "project-template.md"

SLUG = "nick966-fixture"


def _write_fixture(tmp_path):
    tracker = {
        "cross_name": "Fixture Cross",
        "created": "2026-01-01",
        "plants": [
            {
                "id": "FX01",
                "cross": "Fixture Cross",
                "status": "keeper",
                "original_notes": "smells great",
                "observation_log": "\n### 2026-01-02T00:00:00\nFX01 doing well\n",
            },
            {"id": "FX02", "cross": "Fixture Cross", "status": "culled"},
        ],
    }
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "projects": [
                    {
                        "slug": SLUG,
                        "auto_create": False,
                        "plant_id_prefixes": [{"prefix": "FX", "pattern": "FX(\\d+)"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return tracker_path, registry_path


# ------------------------------------------------------------- template ----


def test_template_declares_the_canonical_plant_id_field():
    schema = load_schema(PLANT_TEMPLATE)
    assert CANONICAL_PLANT_ID_KEY in schema
    assert schema[CANONICAL_PLANT_ID_KEY]["type"] == "string"


def test_template_no_longer_declares_the_legacy_id_field():
    """Both spellings in the schema would make write_plant emit both keys."""
    assert SOURCE_PLANT_ID_KEY not in load_schema(PLANT_TEMPLATE)


def test_plant_id_is_the_first_declared_field_so_it_leads_the_frontmatter():
    assert next(iter(load_schema(PLANT_TEMPLATE))) == CANONICAL_PLANT_ID_KEY


# --------------------------------------------------------------- rename ----


def test_build_plant_record_renames_the_source_id_to_plant_id():
    schema = load_schema(PLANT_TEMPLATE)
    record, _ = build_plant_record({"id": "FX01", "cross": "c"}, schema)
    assert record[CANONICAL_PLANT_ID_KEY] == "FX01"
    assert SOURCE_PLANT_ID_KEY not in record


def test_build_plant_record_never_emits_both_id_spellings():
    """The dual-key corruption shape `plant_id_of` raises on."""
    schema = load_schema(PLANT_TEMPLATE)
    record, _ = build_plant_record({"id": "FX01", "cross": "c"}, schema)
    present = {k for k in ("id", "plant_id") if k in record}
    assert present == {CANONICAL_PLANT_ID_KEY}


def test_build_plant_record_accepts_a_record_already_keyed_plant_id():
    schema = load_schema(PLANT_TEMPLATE)
    record, defaulted = build_plant_record({"plant_id": "FX01", "cross": "c"}, schema)
    assert record[CANONICAL_PLANT_ID_KEY] == "FX01"
    assert SOURCE_PLANT_ID_KEY not in record
    assert CANONICAL_PLANT_ID_KEY not in defaulted


def test_build_plant_record_rejects_a_record_whose_two_id_keys_disagree():
    schema = load_schema(PLANT_TEMPLATE)
    with pytest.raises(Exception) as exc:
        build_plant_record({"id": "FX01", "plant_id": "FX99"}, schema)
    assert "FX99" in str(exc.value)


def test_plant_id_is_not_reported_as_a_defaulted_field():
    """It came from the source, renamed -- not materialised from a default."""
    schema = load_schema(PLANT_TEMPLATE)
    _, defaulted = build_plant_record({"id": "FX01", "cross": "c"}, schema)
    assert CANONICAL_PLANT_ID_KEY not in defaulted


# ------------------------------------------------------ end-to-end shape ----


def test_migrated_files_are_keyed_plant_id_on_disk(tmp_path):
    tracker_path, registry_path = _write_fixture(tmp_path)
    out = tmp_path / "out"
    migrate_tracker(
        tracker_path, registry_path, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
    )
    for pid in ("FX01", "FX02"):
        text = (out / "plants" / f"{pid}.md").read_text(encoding="utf-8")
        assert f"plant_id: {pid}\n" in text
        assert f"\nid: {pid}\n" not in text
        assert "\nid: " not in text


def test_migrated_files_round_trip_the_id_under_the_canonical_key(tmp_path):
    tracker_path, registry_path = _write_fixture(tmp_path)
    out = tmp_path / "out"
    migrate_tracker(
        tracker_path, registry_path, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
    )
    schema = load_schema(PLANT_TEMPLATE)
    got = read_plant(out / "plants" / "FX01.md", schema=schema)
    assert got[CANONICAL_PLANT_ID_KEY] == "FX01"
    assert got.get(SOURCE_PLANT_ID_KEY) is None


def test_verification_maps_the_source_id_onto_the_canonical_key(tmp_path):
    """Verification must not report the renamed key as a lost field."""
    tracker_path, registry_path = _write_fixture(tmp_path)
    out = tmp_path / "out"
    migrate_tracker(
        tracker_path, registry_path, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
    )
    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert report.ok, json.dumps(report.as_dict(), indent=2, default=str)


def test_verification_still_catches_a_wrong_id_after_the_rename(tmp_path):
    """The rename must not turn the ID check into a no-op (falsification)."""
    tracker_path, registry_path = _write_fixture(tmp_path)
    out = tmp_path / "out"
    migrate_tracker(
        tracker_path, registry_path, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
    )
    target = out / "plants" / "FX01.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "plant_id: FX01", "plant_id: WRONG"
        ),
        encoding="utf-8",
    )
    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert not report.ok
    changed = report.changed_fields.get("FX01", [])
    assert any(c["field"] == CANONICAL_PLANT_ID_KEY for c in changed), changed
