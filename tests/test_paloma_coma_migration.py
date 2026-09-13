"""Task 3.4 — assertions unique to paloma-coma's data.

The shared Task 3.x acceptance contract — plant count, zero field loss,
verification evidence counts, registry-sourced routing fields, *behavioural*
ID routing, sandbox isolation, determinism, side-effect proofs — lives in
`tests/test_project_migration_contract.py` and runs against this project via
its `ProjectSpec` in `src/migration_specs.py`. None of it is repeated here.

What makes this project's data different, and why each matters:

* **Every nullable field is null on every plant.** All ten of `sex`,
  `germ_date`, `veg_start`, `flower_flip`, `harvest_date`, `vigor`,
  `structure`, `terpene_notes`, `issues` and `selection_notes` are empty at
  once — the first project where that is true. Earlier projects always had at
  least one of `terpene_notes`/`selection_notes` populated somewhere, so a
  writer that skipped an entirely-null column, or a reader that only
  materialised keys it had seen carry a value, round-trips them cleanly and
  silently drops ten fields per plant here.
* **The smallest project (5 plants) with a numbering gap at the front.**
  `PC01` then `PC04`–`PC07`: `PC02`/`PC03` never existed. A migration that
  regenerated IDs from an index would produce a plausible `PC01..PC05`.
* **`notes_meta.migration_note` enumerates the five source tabs by plant ID.**
  Unlike honey-badger's stale note, this one is checkable against the roster —
  and it is the record of a Drive misfiling that was nearly missed, so losing
  the prose loses the provenance.
* **The observation logs carry emoji and typographic apostrophes** (`☠️`
  U+2620 U+FE0F, `’` U+2019) inside a markdown body written under a YAML
  frontmatter — non-ASCII that a mis-set encoding mangles.

Skips cleanly if the real tracker is not present on this machine.
"""

import json

import pytest

from helpers_migration import (  # noqa: F401  (fixture re-export)
    PLANT_TEMPLATE,
    PROJECT_TEMPLATE,
    migrate_project,
    no_side_effects,
    tracker_json,
)
from breeding_tracker.migration_specs import PALOMA_COMA as SPEC

requires_real_data = pytest.mark.skipif(
    not SPEC.tracker.exists(),
    reason=f"real tracker for {SPEC.slug} not present",
)

pytestmark = requires_real_data

#: The exact roster, gap included. Written out rather than generated so a
#: renumbered or dropped record fails on identity, not on a count.
EXPECTED_IDS = ["PC01", "PC04", "PC05", "PC06", "PC07"]

#: Every plant field that is null on every plant in this project.
ALL_NULL_FIELDS = [
    "flower_flip",
    "germ_date",
    "harvest_date",
    "issues",
    "selection_notes",
    "sex",
    "structure",
    "terpene_notes",
    "veg_start",
    "vigor",
]


@pytest.fixture
def migrated(tmp_path, no_side_effects):
    return migrate_project(SPEC, tmp_path)


def _plant(out, plant_id):
    from breeding_tracker.plant_markdown import load_schema, read_plant

    return read_plant(out / "plants" / f"{plant_id}.md", schema=load_schema(PLANT_TEMPLATE))


def _project(out):
    from breeding_tracker.project_markdown import load_schema, read_project

    return read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))


# ------------------------------------ the all-nullable-fields-empty case ----


def test_this_project_is_the_first_with_every_nullable_field_empty():
    """Guards the premise the shared null check leans on here.

    That the nulls survive — through the reader AND as explicit `field: null`
    in the migrated bytes — is asserted for every project by the shared
    contract's `test_fields_null_on_every_plant_are_written_as_explicit_yaml_
    nulls`, over the set it derives from each tracker. What is unique to this
    project is *which* fields those are: all ten nullable columns at once, so
    a writer that omitted an entirely-null column loses ten fields per plant
    here. If a value were ever filled in upstream, the derived set would
    shrink and the shared check would silently test something weaker, so the
    fixture's own discriminating power is pinned rather than assumed.
    """
    plants = tracker_json(SPEC)["plants"]
    empty = sorted(k for k in plants[0] if all(p[k] is None for p in plants))
    assert empty == ALL_NULL_FIELDS
    assert len(empty) == 10


def test_corrected_reading_is_the_only_defaulted_plant_field(migrated):
    """Every plant carries all 18 keys, so nothing else may be materialised —
    a real field loss cannot hide behind "it was defaulted"."""
    summary, out = migrated
    for plant in tracker_json(SPEC)["plants"]:
        plant_id = plant["id"]
        assert set(plant) == set(SPEC.plant_keys), plant_id
        assert summary.defaulted_fields[plant_id] == ["corrected_reading"], plant_id
        assert _plant(out, plant_id)["corrected_reading"] is None


# ------------------------------------------------- this project's records --


def test_plant_ids_are_the_roster_with_its_front_gap(migrated):
    """PC02/PC03 never existed; a migration regenerating IDs from an index
    would produce a plausible PC01..PC05 and pass a count-only check."""
    _, out = migrated
    assert sorted(p["id"] for p in tracker_json(SPEC)["plants"]) == EXPECTED_IDS
    assert sorted(p.stem for p in (out / "plants").glob("*.md")) == EXPECTED_IDS
    assert "PC02" not in EXPECTED_IDS and "PC03" not in EXPECTED_IDS


def test_statuses_and_photo_counts_survive_exactly(migrated):
    """Only id/cross/status/photos/notes carry data here, so these are the
    entire non-null payload; `photo_count` must stay consistent with the list
    rather than being recomputed or normalised."""
    _, out = migrated
    seen = set()
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        assert got["status"] == plant["status"], plant["id"]
        assert got["cross"] == plant["cross"] == "Paloma Coma"
        assert got["photos"] == plant["photos"], plant["id"]
        assert got["photo_count"] == plant["photo_count"] == len(plant["photos"])
        assert got["photos_drive_url"] == plant["photos_drive_url"]
        seen.add(got["status"])
    assert seen == {"culled", "keeper"}


def test_notes_meta_tab_roster_survives_and_matches_the_real_plants(migrated):
    """This project's `migration_note` names the five source tabs by plant ID.

    Unlike honey-badger's note (stale in the source and preserved anyway),
    this one is checkable — and it records a Drive misfiling that was nearly
    missed, so the prose is provenance, not decoration.
    """
    summary, out = migrated
    source = tracker_json(SPEC)["notes_meta"]
    got = _project(out)["notes_meta"]

    assert json.dumps(got, sort_keys=True) == json.dumps(source, sort_keys=True)
    assert "notes_meta" not in summary.defaulted_fields.get("project", [])

    note = got["migration_note"]
    for plant_id in EXPECTED_IDS:
        assert plant_id in note
    assert "5 tabs" in note
    assert "wrong Drive location" in note
    assert got["source_doc"].startswith("https://docs.google.com/")
    assert got["brand_assets_in_drive"] == []
    assert got["flagged_ambiguities"] == []
    assert got["resolved_ambiguities"] == []


def test_non_ascii_note_text_survives_byte_for_byte(migrated):
    """Emoji (☠️ = U+2620 U+FE0F) and typographic apostrophes (U+2019) sit in
    the markdown *body* under a YAML frontmatter; a mis-set encoding or an
    ASCII-escaping YAML dump mangles them while everything still parses."""
    _, out = migrated
    emoji_carriers, apostrophe_carriers = [], []
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        assert got["original_notes"] == plant["original_notes"], plant["id"]
        text = (out / "plants" / f"{plant['id']}.md").read_text(
            encoding="utf-8", newline=""
        )
        body = text.split("\n---\n", 1)[1]
        assert body == plant["observation_log"], plant["id"]
        if "\u2620\ufe0f" in plant["observation_log"]:
            emoji_carriers.append(plant["id"])
        if "\u2019" in plant["observation_log"]:
            apostrophe_carriers.append(plant["id"])
    assert emoji_carriers == ["PC01", "PC04", "PC06"]
    assert apostrophe_carriers == ["PC01", "PC05", "PC06"]
    assert "\u2620\ufe0f" in (out / "plants" / "PC01.md").read_text(encoding="utf-8")


def test_original_notes_stay_a_substring_of_the_observation_log(migrated):
    """The two fields overlap by construction here (the log wraps the raw
    Discord/Doc text under a heading). Truncating either one independently is
    the realistic loss, and it breaks the relationship."""
    _, out = migrated
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        text = (out / "plants" / f"{plant['id']}.md").read_text(
            encoding="utf-8", newline=""
        )
        body = text.split("\n---\n", 1)[1]
        assert got["original_notes"] in body, plant["id"]
        assert body.startswith("\n### Original Notes from Google Doc"), plant["id"]
