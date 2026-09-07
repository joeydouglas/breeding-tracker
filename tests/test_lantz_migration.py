"""Task 3.6 — assertions unique to lantz's data.

The shared Task 3.x acceptance contract — plant count, zero field loss,
verification evidence counts, registry-sourced routing fields, *behavioural*
ID routing, sandbox isolation, determinism, side-effect proofs — lives in
`tests/test_project_migration_contract.py` and runs against this project via
its `ProjectSpec` in `src/migration_specs.py`. None of it is repeated here.

What makes this project's data different, and why each matters:

* **The corpus's only real `corrected_reading`.** Ltz01 carries the single
  human-confirmed transcription correction in all six trackers ("'Thanos' ->
  'phenos'"); no other record in any project has the key at all. Every earlier
  spec therefore declares the field a materialised template default, and the
  correct value there is `null` — which is also exactly what a writer that
  *ignored the source and always materialised the default* would produce. That
  bug is invisible on five projects and destroys real provenance here.
* **Ltz01 is the only record anywhere with ZERO defaulted fields.** It carries
  all 19 keys, so it is the sole case where `defaulted_fields` has no entry for
  a plant. mule-fuel's MG07 is the opposite skew (3 defaults where its siblings
  have 1); the "every plant defaults exactly `corrected_reading`" shape that
  every other project asserts is *false* here, for one record.
* **The only MIXED-CASE plant-ID family.** `Ltz` is upper-initial with a lower
  tail. MG/HBH/PK/PL/PC are all-upper and spaced-paste's `sp` is all-lower, so
  each of those rosters survives one normalisation untouched (`.upper()` and
  `.lower()` respectively). `Ltz` survives neither, and is the only shape that
  catches both.
* **A single status across the whole roster.** All four plants are `culled` —
  the only project without status variety, so a migration that dropped or
  normalised `status` still yields a self-consistent-looking roster.
* **`resolved_ambiguities` non-empty while `flagged_ambiguities` is empty.**
  The only project with that combination, and the resolved entry is the
  provenance for Ltz01's `corrected_reading`, so the two must survive together.

Deliberately NOT claimed here, because neither is unique: `photos_drive_url`
is `''` on every plant (spaced-paste is identical and caught a `''`->`None`
coercion first), and Ltz07's tab emoji contradicts its status (paloma-coma's
PC04 has the same contradiction). Both are covered by the shared contract's
field-level diff.

Skips cleanly if the real tracker is not present on this machine.
"""

import json
import re

import pytest

from helpers_migration import (  # noqa: F401  (fixture re-export)
    PLANT_TEMPLATE,
    PROJECT_TEMPLATE,
    expected_plant_record,
    migrate_project,
    no_side_effects,
    registry_entry,
    tracker_json,
)
from migration_specs import LANTZ as SPEC
from migration_specs import PROJECT_SPECS
from plant_markdown import BODY_FIELD as PLANT_BODY_FIELD

requires_real_data = pytest.mark.skipif(
    not SPEC.tracker.exists(),
    reason=f"real tracker for {SPEC.slug} not present",
)

pytestmark = requires_real_data

#: The exact roster, gaps included. Written out rather than generated so a
#: renumbered or dropped record fails on identity, not on a count.
EXPECTED_IDS = ["Ltz01", "Ltz03", "Ltz06", "Ltz07"]

#: The one record carrying a real `corrected_reading`, and its exact value.
CORRECTION_CARRIER = "Ltz01"
CORRECTION_TEXT = "'Thanos' -> 'phenos' (phenotypes). Confirmed by Joey 2026-08-25."

#: Plant fields null on every plant here (nine of the ten nullable columns;
#: `selection_notes` is populated on Ltz01 alone).
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
    from plant_markdown import read_plant

    return read_plant(out / "plants" / f"{plant_id}.md", schema=_plant_schema())


def _plant_schema():
    from plant_markdown import load_schema

    return load_schema(PLANT_TEMPLATE)


def _project(out):
    from project_markdown import load_schema, read_project

    return read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))


def _frontmatter(out, plant_id):
    return (
        (out / "plants" / f"{plant_id}.md")
        .read_text(encoding="utf-8")
        .split("\n---\n", 1)[0]
    )


def _body(out, plant_id):
    return (
        (out / "plants" / f"{plant_id}.md")
        .read_text(encoding="utf-8", newline="")
        .split("\n---\n", 1)[1]
    )


# ----------------------------------- the corpus's only corrected_reading ----


def test_lantz_is_the_only_project_carrying_corrected_reading_at_all():
    """Guards the premise of every check below, across the WHOLE corpus.

    Asserted against every other `ProjectSpec`'s real tracker rather than
    against a docstring, so if another project ever gains the field this
    module's uniqueness claim fails loudly instead of quietly rotting into a
    false statement in a comment.
    """
    for spec in PROJECT_SPECS:
        if spec.slug == SPEC.slug or not spec.tracker.exists():
            continue
        carriers = [
            p["id"] for p in tracker_json(spec)["plants"] if "corrected_reading" in p
        ]
        assert carriers == [], f"{spec.slug} also carries corrected_reading: {carriers}"

    carriers = [
        p["id"] for p in tracker_json(SPEC)["plants"] if "corrected_reading" in p
    ]
    assert carriers == [CORRECTION_CARRIER]


def test_the_real_corrected_reading_survives_as_data_not_as_a_default(migrated):
    """The failure only this record can catch.

    On all five earlier projects `corrected_reading` is absent from the source
    and `null` is the correct migrated value — so a writer that ignored the
    source field entirely and unconditionally materialised the template
    default produces byte-identical output there and passes the whole shared
    contract. Here that same bug erases the corpus's only human-confirmed
    transcription correction.

    Asserted through the schema reader AND in the raw frontmatter, because a
    reader that fell back to the template default for a key the writer dropped
    would otherwise report a plausible `None` and hide the loss.
    """
    summary, out = migrated
    source = {p["id"]: p for p in tracker_json(SPEC)["plants"]}

    assert source[CORRECTION_CARRIER]["corrected_reading"] == CORRECTION_TEXT

    got = _plant(out, CORRECTION_CARRIER)
    assert got["corrected_reading"] == CORRECTION_TEXT
    assert got["corrected_reading"] is not None

    frontmatter = _frontmatter(out, CORRECTION_CARRIER)
    assert "corrected_reading: null" not in frontmatter
    assert "Thanos" in frontmatter and "phenos" in frontmatter

    # And it must NOT be reported as defaulted — it is real source data.
    assert "corrected_reading" not in summary.defaulted_fields.get(
        CORRECTION_CARRIER, ()
    )


def test_corrected_reading_is_still_defaulted_on_the_other_three_plants(migrated):
    """Both halves must hold at once, on the same run.

    The mirror of the check above: a writer that preserved Ltz01's value by
    *inventing* one everywhere (copying it across records, or emitting the
    template's descriptor text) would pass that check and corrupt three
    records. So the same migration is asserted to default exactly the three
    plants whose source lacks the key, as explicit nulls in the bytes.
    """
    summary, out = migrated
    others = [i for i in EXPECTED_IDS if i != CORRECTION_CARRIER]
    assert others == ["Ltz03", "Ltz06", "Ltz07"]

    source = {p["id"]: p for p in tracker_json(SPEC)["plants"]}
    for plant_id in others:
        assert "corrected_reading" not in source[plant_id], plant_id
        assert summary.defaulted_fields[plant_id] == ["corrected_reading"], plant_id
        assert _plant(out, plant_id)["corrected_reading"] is None, plant_id
        assert "corrected_reading: null" in _frontmatter(out, plant_id), plant_id
        assert CORRECTION_TEXT not in _frontmatter(out, plant_id), plant_id


def test_the_correction_and_its_notes_meta_provenance_survive_together(migrated):
    """The correction is only trustworthy with the record of who confirmed it.

    `notes_meta.resolved_ambiguities` holds the project-level provenance and
    Ltz01's `selection_notes` holds the per-plant restatement; the
    `corrected_reading` field is the machine-readable form of the same fact.
    Losing any one of the three leaves a correction with no audit trail, so
    all three are asserted on one migrated tree.
    """
    _, out = migrated
    source = tracker_json(SPEC)

    resolved = _project(out)["notes_meta"]["resolved_ambiguities"]
    assert resolved == source["notes_meta"]["resolved_ambiguities"]
    assert len(resolved) == 1
    assert "Thanos" in resolved[0] and "phenos" in resolved[0]
    assert "corrected_reading" in resolved[0]

    got = _plant(out, CORRECTION_CARRIER)
    assert got["selection_notes"] == source["plants"][0]["selection_notes"]
    assert "Thanos" in got["selection_notes"]
    assert "corrected_reading" in got["selection_notes"]

    # The uncorrected original is deliberately NOT rewritten: the artifact
    # must still be there verbatim, or the correction has no subject.
    assert "Thanos" in got["original_notes"]
    assert "Thanos" in _body(out, CORRECTION_CARRIER)


def test_this_projects_notes_meta_is_resolved_only(migrated):
    """The only project with resolved ambiguities and no flagged ones.

    kibungan is flagged-only; spaced-paste has both; the rest have neither.
    An empty list and a missing key are both falsy, so the empty
    `flagged_ambiguities` is asserted to survive as an actual empty list.

    The combination claim is checked against every other spec's real tracker
    for the same reason as the claims above: a prose-only "only project"
    rots silently, an asserted one fails.
    """
    _, out = migrated
    got = _project(out)["notes_meta"]
    source = tracker_json(SPEC)["notes_meta"]

    for spec in PROJECT_SPECS:
        if spec.slug == SPEC.slug or not spec.tracker.exists():
            continue
        meta = tracker_json(spec).get("notes_meta") or {}
        resolved_only = bool(meta.get("resolved_ambiguities")) and not meta.get(
            "flagged_ambiguities"
        )
        assert not resolved_only, f"{spec.slug} is also resolved-only"

    assert got["flagged_ambiguities"] == [] == source["flagged_ambiguities"]
    assert len(got["resolved_ambiguities"]) == 1
    assert json.dumps(got, sort_keys=True) == json.dumps(source, sort_keys=True)
    assert len(got["brand_assets_in_drive"]) == 6
    assert got["source_doc"].startswith("https://docs.google.com/")


# ------------------------------------ the only zero-default plant record ----


def test_ltz01_is_the_only_record_in_the_corpus_with_no_defaulted_fields(migrated):
    """Every other project asserts "exactly one defaulted field per plant".

    That shape is false here for one record, and Ltz01 is the only plant in
    any of the six trackers that needs no template default at all. A
    `defaulted_fields` map that always emitted an entry per record — or a
    `_apply_defaults` that reported a field it did not actually materialise —
    is caught only by this record.

    The "only in the corpus" half is asserted against every other spec's real
    tracker, not left as a docstring claim: a record needs no default exactly
    when its source keys already cover every non-body field of the plant
    schema, so the same predicate is evaluated over all six rosters.
    """
    summary, _ = migrated
    assert CORRECTION_CARRIER not in summary.defaulted_fields

    schema = _plant_schema()
    required = {f for f in schema if f != PLANT_BODY_FIELD}
    # NICK-966: the predicate compares source keys against the SCHEMA's key
    # set, and the schema now spells the ID `plant_id` while the trackers
    # still spell it `id`. Apply the migration's own rename to each source
    # record first, or `required <= set(p)` is false for every plant in every
    # project and the assertion passes vacuously.
    for spec in PROJECT_SPECS:
        if spec.slug == SPEC.slug or not spec.tracker.exists():
            continue
        zero_default = [
            p["id"]
            for p in tracker_json(spec)["plants"]
            if required <= set(expected_plant_record(p))
        ]
        assert zero_default == [], (
            f"{spec.slug} also has zero-default records: {zero_default}"
        )
    assert [
        p["id"]
        for p in tracker_json(SPEC)["plants"]
        if required <= set(expected_plant_record(p))
    ] == [CORRECTION_CARRIER]

    source = {p["id"]: p for p in tracker_json(SPEC)["plants"]}
    assert set(source[CORRECTION_CARRIER]) == set(SPEC.plant_keys) | {
        "corrected_reading"
    }
    assert len(source[CORRECTION_CARRIER]) == 19

    # The other three are the ordinary 18-key shape.
    for plant_id in EXPECTED_IDS:
        if plant_id == CORRECTION_CARRIER:
            continue
        assert set(source[plant_id]) == set(SPEC.plant_keys), plant_id
        assert len(source[plant_id]) == 18, plant_id


# ------------------------------------------------ the mixed-case ID family --


def test_this_project_is_the_only_mixed_case_plant_id_family():
    """Guards the premise of the normalisation checks below, corpus-wide."""
    prefix = registry_entry(SPEC)["plant_id_prefixes"][0]["prefix"]
    assert prefix == "Ltz"
    assert prefix != prefix.upper() and prefix != prefix.lower()

    for spec in PROJECT_SPECS:
        if spec.slug == SPEC.slug or not spec.tracker.exists():
            continue
        for entry in registry_entry(spec)["plant_id_prefixes"]:
            other = entry["prefix"]
            assert other == other.upper() or other == other.lower(), (
                f"{spec.slug}'s {other!r} is also mixed case"
            )


def test_plant_filenames_and_ids_survive_both_case_normalisations(migrated):
    """`Ltz` is the only roster that neither `.upper()` nor `.lower()` fixes.

    spaced-paste's lowercase IDs are unchanged by `.lower()` and the four
    uppercase rosters are unchanged by `.upper()`, so each of those catches at
    most one of the two normalisations. Compared against the real directory
    listing and the in-file `id`, byte for byte, since on a case-insensitive
    filesystem `LTZ01.md` answers to `Ltz01.md`.
    """
    _, out = migrated
    written = sorted(p.name for p in (out / "plants").glob("*.md"))
    assert written == [f"{i}.md" for i in EXPECTED_IDS]

    for plant_id in EXPECTED_IDS:
        assert plant_id != plant_id.upper() and plant_id != plant_id.lower()
        got = _plant(out, plant_id)
        # NICK-966: the migrated file's ID key is `plant_id`, not `id`.
        assert got["plant_id"] == plant_id
        assert got["plant_id"] != plant_id.upper()
        assert got["plant_id"] != plant_id.lower()
        assert re.search(
            rf"^plant_id: ['\"]?{plant_id}['\"]?$",
            _frontmatter(out, plant_id),
            re.M,
        ), plant_id


def test_routing_is_case_insensitive_across_the_mixed_case_prefix(migrated):
    """Production compiles with `re.IGNORECASE`; the prefix is mixed case.

    So every spelling people actually type — `Ltz01`, `LTZ7`, `ltz 3` — must
    route to the same plant with the same captured number. Compiled with
    `ROUTING_FLAGS` out of the MIGRATED markdown rather than the registry, so
    this module and the shared contract cannot drift onto different matchers.
    """
    from migration_harness import ROUTING_FLAGS

    _, out = migrated
    compiled = re.compile(
        _project(out)["plant_id_prefixes"][0]["pattern"], ROUTING_FLAGS
    )
    for plant_id in EXPECTED_IDS:
        digits = plant_id[3:]
        for spelling in (
            plant_id,
            plant_id.upper(),
            plant_id.lower(),
            f"{plant_id[:3].upper()} {int(digits)}",
        ):
            match = compiled.search(f"checked {spelling} today")
            assert match, spelling
            assert int(match.group(1)) == int(digits), spelling


def test_the_prefix_does_not_fire_inside_ordinary_words(migrated):
    """The `\\b` boundary is what stops a mis-route onto a real plant."""
    from migration_harness import ROUTING_FLAGS

    _, out = migrated
    pattern = _project(out)["plant_id_prefixes"][0]["pattern"]
    compiled = re.compile(pattern, ROUTING_FLAGS)

    for text in ("xLtz01 looks great", "waltz01 tonight", "ALTZ 3 sample"):
        assert not compiled.search(text), f"{text!r} mis-routed"

    # Discriminating: the same probes DO fire once the boundary is removed.
    unbounded = re.compile(pattern.replace(r"\b", ""), ROUTING_FLAGS)
    assert unbounded.search("waltz01 tonight")


def test_plant_ids_are_the_roster_with_its_three_gaps(migrated):
    """Ltz02/04/05 never existed; a migration regenerating IDs from a loop
    index would produce a plausible Ltz01..Ltz04 and pass a count-only check."""
    _, out = migrated
    assert sorted(p["id"] for p in tracker_json(SPEC)["plants"]) == EXPECTED_IDS
    assert sorted(p.stem for p in (out / "plants").glob("*.md")) == EXPECTED_IDS
    for missing in ("Ltz02", "Ltz04", "Ltz05"):
        assert missing not in EXPECTED_IDS
        assert not (out / "plants" / f"{missing}.md").exists()


# --------------------------------------------- the single-status roster -----


def test_every_plant_shares_one_status_and_it_survives(migrated):
    """The only project with no status variety.

    All four plants are `culled`, so a migration that dropped `status`
    entirely, or normalised it to a constant, still produces a
    self-consistent-looking roster here — every other project's data would
    show the collapse as a lost distinction.

    The "only project" half is asserted against every other spec's real
    tracker rather than stated in prose, so a future project losing its
    status variety fails this claim loudly instead of rotting it.
    """
    _, out = migrated
    source = {p["id"]: p["status"] for p in tracker_json(SPEC)["plants"]}
    assert set(source.values()) == {"culled"}

    for spec in PROJECT_SPECS:
        if spec.slug == SPEC.slug or not spec.tracker.exists():
            continue
        statuses = {p["status"] for p in tracker_json(spec)["plants"]}
        assert len(statuses) > 1, (
            f"{spec.slug} also has a single-status roster: {sorted(statuses)}"
        )

    got = {i: _plant(out, i)["status"] for i in EXPECTED_IDS}
    assert got == source
    for plant_id in EXPECTED_IDS:
        assert re.search(
            r"^status: ['\"]?culled['\"]?$", _frontmatter(out, plant_id), re.M
        ), plant_id


def test_ltz07_keeps_its_culled_status_despite_a_keeper_tab_emoji(migrated):
    """The stored status must win over anything re-derivable from the body.

    Ltz07's source tab is `LTZ7💚` (💚 = keeper by this corpus's convention)
    while its status is `culled` — the later observation records the cull
    decision. A migration that re-inferred status from the tab emoji would
    flip this record and look reasonable doing it. paloma-coma's PC04 carries
    the mirror-image contradiction, so this is *not* claimed as unique; it is
    asserted here because the conflicting evidence lives in this project's own
    body text and the shared field diff would report only the symptom.
    """
    _, out = migrated
    body = _body(out, "Ltz07")
    assert "\U0001f49a" in body  # 💚 in the tab heading
    assert _plant(out, "Ltz07")["status"] == "culled"
    assert "gonna cull LTZ7" in body


def test_non_ascii_emoji_and_smart_punctuation_survive_the_round_trip(migrated):
    """☠️ (U+2620 U+FE0F) and 💚 (U+1F49A, astral) sit in markdown bodies under
    a YAML frontmatter, alongside curly quotes in the prose. A mis-set encoding
    or an ASCII-escaping YAML dump mangles them while everything still parses.
    """
    _, out = migrated
    skull, heart = [], []
    for plant in tracker_json(SPEC)["plants"]:
        plant_id = plant["id"]
        got = _plant(out, plant_id)
        assert got["original_notes"] == plant["original_notes"], plant_id
        body = _body(out, plant_id)
        assert body == plant["observation_log"], plant_id
        if "\u2620\ufe0f" in body:
            skull.append(plant_id)
        if "\U0001f49a" in body:
            heart.append(plant_id)
    assert sorted(skull) == ["Ltz01", "Ltz03", "Ltz06"]
    assert sorted(heart) == ["Ltz07"]

    # Curly quotes/apostrophes in the source prose, preserved verbatim.
    assert "\u201c" in _body(out, "Ltz01") or "\u2019" in _body(out, "Ltz01")


def test_original_notes_stay_a_substring_of_the_observation_log(migrated):
    """The two fields overlap by construction (the log wraps the raw Doc text
    under a tab heading). Truncating either independently breaks the
    relationship while both still look populated."""
    _, out = migrated
    for plant in tracker_json(SPEC)["plants"]:
        got = _plant(out, plant["id"])
        body = _body(out, plant["id"])
        assert got["original_notes"] in body, plant["id"]
        assert body.startswith("\n### Original Notes from Google Doc"), plant["id"]


def test_exactly_nine_of_the_ten_nullable_columns_are_null_on_every_plant():
    """Guards the premise: `selection_notes` is populated on Ltz01 alone.

    That those nine survive — through the reader AND as explicit `field: null`
    in the migrated bytes — is asserted for every project by the shared
    contract. What is pinned here is *which* fields those are, so a coercion
    that moved `selection_notes` or `photos_drive_url` into the set is caught
    rather than passing against a weaker, self-derived list.
    """
    plants = tracker_json(SPEC)["plants"]
    common = set(plants[0])
    for p in plants:
        common &= set(p)
    empty = sorted(k for k in common if all(p[k] is None for p in plants))
    assert empty == ALL_NULL_FIELDS
    assert "selection_notes" not in empty
    assert "photos_drive_url" not in empty
    assert [p["id"] for p in plants if p["selection_notes"] is not None] == [
        CORRECTION_CARRIER
    ]
