"""Task 3.5 — assertions unique to spaced-paste's data.

The shared Task 3.x acceptance contract — plant count, zero field loss,
verification evidence counts, registry-sourced routing fields, *behavioural*
ID routing, sandbox isolation, determinism, side-effect proofs — lives in
`tests/test_project_migration_contract.py` and runs against this project via
its `ProjectSpec` in `src/migration_specs.py`. None of it is repeated here.

What makes this project's data different, and why each matters:

* **The first LOWERCASE plant-ID family.** The registry prefix is `sp` and
  the IDs are `sp01`..`sp06`; MG/HBH/PK/PL/PC/Ltz are all uppercase-initial.
  Case is load-bearing in three places no earlier project could exercise: the
  per-plant **filename** (`sp01.md` — an ID normalised to upper case during
  migration produces a differently-named file while every *field* still
  round-trips, so the shared field diff stays green), the **routing pattern**
  (production compiles with `re.IGNORECASE`, so a pattern that re-locked its
  own case still routes the canonical spelling and drops the rest), and the
  **registry prefix** itself.
* **A 2-char prefix that is a common English bigram.** `MG`/`PK`/`PL`/`PC`
  are the same length, but only `sp` occurs inside ordinary words, so
  `\\bsp\\b`-style boundaries are the only thing stopping it from firing
  inside `wasp01` or `crisp 01`. A boundary lost during migration is a live
  mis-route into ordinary Discord prose, not a theoretical one.
* **The source `plants` array is not in ID order.** It is stored `sp06, sp01,
  sp02, sp03, sp05`: the first project where array order and sorted-ID order
  differ. A migration that paired records positionally against a sorted
  roster would write sp06's payload into `sp01.md` and still produce five
  files with five correct-looking IDs.
* **`photos_drive_url` is the empty string on every plant.** The first
  *migrated* project where a *plant* field is `''` rather than a URL or `None`
  (kibungan's `''` was at project level). `lantz` has the same shape but is
  not migrated yet, so this is the first chance to catch a writer or reader
  coercing `''` to `None` — or `None` to `''` — not the only one.
* **`notes_meta` present while `genetics`/`breeder_lineage` are absent.** A
  project-default combination no earlier project has.

Skips cleanly if the real tracker is not present on this machine.
"""

import json
import re

import pytest

from helpers_migration import (  # noqa: F401  (fixture re-export)
    PLANT_TEMPLATE,
    PROJECT_TEMPLATE,
    migrate_project,
    no_side_effects,
    registry_entry,
    tracker_json,
)
from breeding_tracker.migration_specs import SPACED_PASTE as SPEC

requires_real_data = pytest.mark.skipif(
    not SPEC.tracker.exists(),
    reason=f"real tracker for {SPEC.slug} not present",
)

pytestmark = requires_real_data

#: The exact roster, gap included. Written out rather than generated so a
#: renumbered or dropped record fails on identity, not on a count.
EXPECTED_IDS = ["sp01", "sp02", "sp03", "sp05", "sp06"]

#: The order the records physically appear in `tracker.json`, which is NOT
#: `sorted(EXPECTED_IDS)`. Pinned so the discriminating premise of
#: `test_records_are_matched_by_id_and_never_positionally` cannot rot away.
SOURCE_ORDER = ["sp06", "sp01", "sp02", "sp03", "sp05"]

#: Plant fields that are null on every plant here (nine of the ten nullable
#: columns; `selection_notes` is populated on sp06 alone).
ALL_NULL_FIELDS = [
    "flower_flip",
    "germ_date",
    "harvest_date",
    "issues",
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

    return read_plant(
        out / "plants" / f"{plant_id}.md", schema=load_schema(PLANT_TEMPLATE)
    )


def _project(out):
    from breeding_tracker.project_markdown import load_schema, read_project

    return read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))


# ------------------------------------------------- the lowercase-ID case ----


def test_this_project_is_the_first_with_lowercase_plant_ids():
    """Guards the premise of every case-sensitivity check below.

    If the roster were ever normalised to upper case in the source, the checks
    would still pass while testing nothing, so the fixture's own
    discriminating power is asserted rather than assumed.
    """
    ids = [p["id"] for p in tracker_json(SPEC)["plants"]]
    assert all(i == i.lower() and i != i.upper() for i in ids), ids
    assert registry_entry(SPEC)["plant_id_prefixes"][0]["prefix"] == "sp"


def test_plant_filenames_preserve_id_case_exactly(migrated):
    """The filename is the only place an upper-cased ID is visible.

    `read_plant(out / "plants" / f"{id}.md")` is how every shared field check
    locates a record, and on a case-insensitive filesystem `SP01.md` answers
    to `sp01.md` — so a migration that upper-cased IDs while writing would
    pass the entire shared contract there and produce a roster that no longer
    matches the source on a case-sensitive one. Compared against the real
    directory listing, byte for byte.
    """
    _, out = migrated
    written = sorted(p.name for p in (out / "plants").glob("*.md"))
    assert written == [f"{i}.md" for i in EXPECTED_IDS]
    assert not [n for n in written if n != n.lower()]


def test_the_id_field_inside_each_file_keeps_its_lowercase_form(migrated):
    """A filename can be right while the record's own `id` was normalised.

    Read back through the schema *and* asserted in the raw frontmatter, since
    a YAML dump that quoted-and-cased differently is invisible to the reader.
    """
    _, out = migrated
    for plant_id in EXPECTED_IDS:
        got = _plant(out, plant_id)
        # NICK-966: the migrated file's ID key is `plant_id`, not `id`.
        assert got["plant_id"] == plant_id
        assert got["plant_id"] != plant_id.upper()
        frontmatter = (out / "plants" / f"{plant_id}.md").read_text(
            encoding="utf-8"
        ).split("\n---\n", 1)[0]
        assert re.search(
            rf"^plant_id: ['\"]?{plant_id}['\"]?$", frontmatter, re.M
        ), plant_id


def test_the_two_char_prefix_does_not_fire_inside_ordinary_prose(migrated):
    """`sp` is a common English bigram — the boundary is doing real work.

    Other 2-char prefixes exist (`MG`, `PK`, `PL`, `PC`); what is unique here
    is that `sp` occurs inside ordinary words. The shared routing check proves
    the pattern rejects one synthetic leading
    character (`Xsp01`). This project is the only one where the negative case
    is *real English*: `wasp01`, `crisp 01`, `esp 5` are the kind of thing
    people actually type, and a `\\b` eaten during migration turns each into a
    silent mis-route onto a real plant. Compiled with `ROUTING_FLAGS` —
    production's flags, imported from `migration_harness` rather than spelled
    `re.IGNORECASE` here — out of the MIGRATED markdown, not the registry.

    Hardcoding the flag in this module would mean that if production ever
    changed how it compiles routing patterns, `migration_harness.ROUTING_FLAGS`
    and its parity assertion against `breeding_core` would move while this
    module silently kept testing the old matcher.
    """
    from breeding_tracker.migration_harness import ROUTING_FLAGS

    _, out = migrated
    entry = _project(out)["plant_id_prefixes"][0]
    compiled = re.compile(entry["pattern"], ROUTING_FLAGS)

    for text in ("wasp01 looks great", "crisp 01 leaves", "esp 5 was fine", "gasp-01"):
        assert not compiled.search(text), f"{text!r} mis-routed"

    # Discriminating: the same probes DO fire once the boundary is removed,
    # so this is proving the boundary rather than a quirk of the probe text.
    unbounded = re.compile(entry["pattern"].replace(r"\b", ""), ROUTING_FLAGS)
    assert unbounded.search("wasp01 looks great")


def test_routing_is_case_insensitive_in_both_directions(migrated):
    """Production compiles with `re.IGNORECASE`; the IDs are lowercase.

    So the uppercase spelling people type (`SP01`, `Sp 3`) must route to the
    same plant, and the captured group — which the monitor uses to pick the
    record — must be the same number in either case. Compiled with
    `ROUTING_FLAGS` so this module and the shared contract cannot drift onto
    different matchers.
    """
    from breeding_tracker.migration_harness import ROUTING_FLAGS

    _, out = migrated
    compiled = re.compile(
        _project(out)["plant_id_prefixes"][0]["pattern"], ROUTING_FLAGS
    )
    for plant_id in EXPECTED_IDS:
        digits = plant_id[2:]
        for spelling in (plant_id, plant_id.upper(), plant_id.capitalize()):
            match = compiled.search(f"checked {spelling} today")
            assert match, spelling
            assert int(match.group(1)) == int(digits), spelling


# ------------------------------------------- the unsorted source array ------


def test_the_source_array_is_not_in_id_order():
    """Guards the premise of the positional-matching check below."""
    order = [p["id"] for p in tracker_json(SPEC)["plants"]]
    assert order == SOURCE_ORDER
    assert order != sorted(order), "source is sorted -- the check below is vacuous"


def test_records_are_matched_by_id_and_never_positionally(migrated):
    """The failure only this project's data can catch.

    Every earlier tracker stores its plants in sorted-ID order, so a migration
    that zipped the source array against a sorted roster produced identical
    output and passed. Here the first source record is `sp06`, so positional
    pairing writes sp06's payload into `sp01.md`.

    Asserted on the payload that is *unique per record*: sp06 is the only
    plant carrying `selection_notes`, and each plant's `observation_log` names
    its own source tab.
    """
    _, out = migrated
    source = {p["id"]: p for p in tracker_json(SPEC)["plants"]}

    # sp06 alone has selection_notes; positional pairing moves it to sp01.
    carriers = [i for i in EXPECTED_IDS if source[i]["selection_notes"] is not None]
    assert carriers == ["sp06"], "fixture no longer discriminates"
    assert _plant(out, "sp06")["selection_notes"] == source["sp06"]["selection_notes"]
    assert _plant(out, "sp01")["selection_notes"] is None

    # Each log names its own tab, so a shuffled roster is visible per record.
    for plant_id in EXPECTED_IDS:
        got = _plant(out, plant_id)
        assert got["plant_id"] == plant_id
        body = (out / "plants" / f"{plant_id}.md").read_text(
            encoding="utf-8", newline=""
        ).split("\n---\n", 1)[1]
        assert body == source[plant_id]["observation_log"], plant_id
        assert f"tab: {plant_id[:2]}{int(plant_id[2:])}" in body, plant_id


def test_plant_ids_are_the_roster_with_its_sp04_gap(migrated):
    """sp04 never existed; a migration regenerating IDs from an index would
    produce a plausible sp01..sp05 and pass a count-only check."""
    _, out = migrated
    assert sorted(p["id"] for p in tracker_json(SPEC)["plants"]) == EXPECTED_IDS
    assert sorted(p.stem for p in (out / "plants").glob("*.md")) == EXPECTED_IDS
    assert "sp04" not in EXPECTED_IDS


# ------------------------------------------ the empty-string plant field ----


def test_photos_drive_url_is_the_empty_string_on_every_plant():
    """Guards the premise: the first PLANT-level `''` in a migrated project."""
    plants = tracker_json(SPEC)["plants"]
    assert [p["photos_drive_url"] for p in plants] == [""] * len(plants)


def test_the_empty_string_survives_as_an_empty_string_not_as_null(migrated):
    """`''` and `None` are both falsy; only one of them is what was there.

    A reader coercing `''` to `None` (or a writer emitting `null` for an empty
    string) round-trips every earlier project cleanly and corrupts all five
    records here. Asserted through the schema reader *and* in the raw
    frontmatter, because reading a missing key would yield the template
    default and hide the difference.
    """
    _, out = migrated
    for plant_id in EXPECTED_IDS:
        got = _plant(out, plant_id)
        assert got["photos_drive_url"] == "", plant_id
        assert got["photos_drive_url"] is not None, plant_id
        frontmatter = (out / "plants" / f"{plant_id}.md").read_text(
            encoding="utf-8"
        ).split("\n---\n", 1)[0]
        assert re.search(r"^photos_drive_url: (''|\"\")$", frontmatter, re.M), plant_id
        assert "photos_drive_url: null" not in frontmatter, plant_id


def test_photo_lists_and_counts_are_migrated_consistently(migrated):
    """`photos` and `photo_count` migrate byte-for-byte from the tracker,
    whatever their content -- neither recomputed, normalised, nor dropped.

    Until NICK-987, every spaced-paste plant's `photos` was `[]` (the old
    HTML dashboard generator sourced images from a separate, non-canonical
    `cache/all_doc_images.json` that was never round-tripped into
    tracker.json). NICK-987 merged those Google Doc images into
    tracker.json's `photos` field for real, so the fixed "always `[]`"
    assertion this test previously made is now false for the live data --
    correctly so. The invariant this test protects (photos/photo_count
    survive migration unchanged, in whatever shape the tracker holds them)
    still holds and is what is asserted now.
    """
    _, out = migrated
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        assert got["photos"] == plant["photos"]
        assert got["photo_count"] == plant["photo_count"] == len(plant["photos"] or [])


# ------------------------------------------------- this project's records ---


def test_exactly_nine_of_the_ten_nullable_columns_are_null_on_every_plant():
    """Guards the premise: `selection_notes` is populated on sp06 alone.

    That those nine survive — through the reader AND as explicit `field: null`
    in the migrated bytes — is asserted for every project by the shared
    contract's `test_fields_null_on_every_plant_are_written_as_explicit_yaml_
    nulls`, over the set it derives from each tracker. What is unique here is
    *which* fields those are: this is the one project where `''` is a real,
    different value on a neighbouring plant field, so a coercion that
    conflated `''` with `None` would move `photos_drive_url` into this set
    and the mismatch is caught here rather than passing a weaker set.
    """
    plants = tracker_json(SPEC)["plants"]
    empty = sorted(k for k in plants[0] if all(p[k] is None for p in plants))
    assert empty == ALL_NULL_FIELDS
    assert "selection_notes" not in empty
    assert "photos_drive_url" not in empty


def test_corrected_reading_is_the_only_defaulted_plant_field(migrated):
    """Every plant carries all 18 keys, so nothing else may be materialised —
    a real field loss cannot hide behind "it was defaulted"."""
    summary, out = migrated
    for plant in tracker_json(SPEC)["plants"]:
        plant_id = plant["id"]
        assert set(plant) == set(SPEC.plant_keys), plant_id
        assert summary.defaulted_fields[plant_id] == ["corrected_reading"], plant_id
        assert _plant(out, plant_id)["corrected_reading"] is None


def test_notes_meta_present_while_genetics_and_lineage_are_defaulted(migrated):
    """A project-default combination no earlier project has.

    mule-fuel defaults all three; the other three projects default none. Here
    `notes_meta` is real data and must NOT appear as defaulted, while
    `genetics`/`breeder_lineage` are genuinely absent from the source.
    """
    summary, out = migrated
    source = tracker_json(SPEC)
    defaulted = set(summary.defaulted_fields.get("project", []))

    assert defaulted == {"genetics", "breeder_lineage"}
    assert "genetics" not in source and "breeder_lineage" not in source
    assert json.dumps(_project(out)["notes_meta"], sort_keys=True) == json.dumps(
        source["notes_meta"], sort_keys=True
    )


def test_notes_meta_provenance_prose_survives(migrated):
    """This project's `migration_note` records that the original build read
    only the default Doc tab and missed four plants; the ambiguity lists
    record two facts Joey confirmed by hand. Losing the prose loses the
    provenance — and the note carries the same status emoji as the tabs."""
    _, out = migrated
    got = _project(out)["notes_meta"]
    note = got["migration_note"]

    assert "5 separate tabs" in note
    assert "only captured the default tab (sp6)" in note
    assert "\u2620\ufe0f" in note and "\U0001f49a" in note  # ☠️ culled, 💚 keeper
    assert len(got["brand_assets_in_drive"]) == 6
    assert got["flagged_ambiguities"] == [
        "No explicit keeper/culled status found for sp6 -- left as 'active'."
    ]
    assert len(got["resolved_ambiguities"]) == 2
    assert got["source_doc"].startswith("https://docs.google.com/")


def test_statuses_survive_including_the_unresolved_active_one(migrated):
    """sp06's status is `active` because the source tab carried no emoji — the
    one record whose status was NOT inferred. A migration normalising statuses
    to the keeper/culled pair would erase a flagged, unresolved ambiguity."""
    _, out = migrated
    got = {i: _plant(out, i)["status"] for i in EXPECTED_IDS}
    source = {p["id"]: p["status"] for p in tracker_json(SPEC)["plants"]}
    assert got == source
    assert got["sp06"] == "active"
    assert set(got.values()) == {"active", "keeper", "culled"}


def test_non_ascii_status_emoji_in_the_tab_headings_survive(migrated):
    """The tab names in each `observation_log` heading carry ☠️ (U+2620
    U+FE0F) and 💚 (U+1F49A, a non-BMP astral character) inside a markdown
    body under a YAML frontmatter — a mis-set encoding or an ASCII-escaping
    YAML dump mangles them while everything still parses."""
    _, out = migrated
    skull, heart = [], []
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        assert got["original_notes"] == plant["original_notes"], plant["id"]
        body = (out / "plants" / f"{plant['id']}.md").read_text(
            encoding="utf-8", newline=""
        ).split("\n---\n", 1)[1]
        assert body == plant["observation_log"], plant["id"]
        if "\u2620\ufe0f" in body:
            skull.append(plant["id"])
        if "\U0001f49a" in body:
            heart.append(plant["id"])
    assert sorted(skull) == ["sp02", "sp03"]
    assert sorted(heart) == ["sp01", "sp05"]


def test_original_notes_stay_a_substring_of_the_observation_log(migrated):
    """The two fields overlap by construction here (the log wraps the raw Doc
    text under a tab heading). Truncating either one independently is the
    realistic loss, and it breaks the relationship."""
    _, out = migrated
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        body = (out / "plants" / f"{plant['id']}.md").read_text(
            encoding="utf-8", newline=""
        ).split("\n---\n", 1)[1]
        assert got["original_notes"] in body, plant["id"]
        assert body.startswith("\n### Original Notes from Google Doc"), plant["id"]
