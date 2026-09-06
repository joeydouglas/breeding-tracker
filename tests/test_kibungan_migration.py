"""Task 3.3 — assertions unique to kibungan-pheno-hunt's data.

The shared Task 3.x acceptance contract — plant count, zero field loss,
verification evidence counts, sandbox isolation, determinism, side-effect
proofs — lives in `tests/test_project_migration_contract.py` and runs against
this project via its `ProjectSpec` in `src/migration_specs.py`. Nothing from
that contract is repeated here; duplicating it is what let Task 3.1's and
3.2's copies drift apart.

What makes this project's data different, and why each matters:

* **Two plant-ID prefixes.** `registry.json` carries `PK` *and* `PL` for one
  landrace population. Every project migrated so far had exactly one entry, so
  a migration that took `plant_id_prefixes[0]`, or flattened the list to a
  single mapping, would have passed Tasks 3.1 and 3.2 unnoticed and silently
  stopped routing every `PL` note here. This is the first data that can catch
  it, and the checks below go past string equality to *behavioural* routing.
* **Harder regex escaping.** Both patterns use `(?i)` and a `(?<![A-Z0-9])`
  lookbehind — `[`, `]`, `(`, `)`, `?`, `<`, `!`, `#`, `*` and backslashes in
  one scalar — versus the plain `\\bXX[\\s\\-]?(\\d{1,2})\\b` of the earlier
  projects.
* **`google_sheet_url` is the empty string while `google_sheet_id` is null.**
  The first project where the two differ, so a reader that coerced `''` to
  `None` (or vice versa) is caught here and nowhere else.
* **`notes_meta` carries a non-null `source_doc` and a non-empty
  `flagged_ambiguities`** — both empty/null on the earlier projects.
* Plant IDs are non-contiguous within *both* families.

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
from migration_specs import KIBUNGAN as SPEC
from tracker_migration import verify_migration

requires_real_data = pytest.mark.skipif(
    not SPEC.tracker.exists(),
    reason=f"real tracker for {SPEC.slug} not present",
)

pytestmark = requires_real_data

#: The exact roster, both families, gaps included. Written out rather than
#: generated so a dropped or renumbered record fails on identity, not count.
EXPECTED_IDS = [
    "PK01",
    "PK03",
    "PK04",
    "PK07",
    "PK09",
    "PK10",
    "PK11",
    "PK12",
    "PK14",
    "PK19",
    "PL05",
    "PL06",
    "PL15",
]


@pytest.fixture
def migrated(tmp_path, no_side_effects):
    return migrate_project(SPEC, tmp_path)


def _project(out):
    from project_markdown import load_schema, read_project

    return read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))


# ------------------------------------------- the multi-prefix routing case --


def test_this_project_is_the_first_with_more_than_one_id_prefix():
    """Guards the premise of every check below.

    If the registry were ever reduced to a single prefix here, the multi-prefix
    assertions would still pass while testing nothing, so the fixture's own
    discriminating power is asserted rather than assumed.
    """
    entry = registry_entry(SPEC)
    assert len(entry["plant_id_prefixes"]) == 2
    assert [p["prefix"] for p in entry["plant_id_prefixes"]] == ["PK", "PL"]


def test_both_prefixes_survive_in_order_with_exact_patterns(migrated):
    """A migration reading `plant_id_prefixes[0]` passed Tasks 3.1 and 3.2."""
    _, out = migrated
    got = _project(out)["plant_id_prefixes"]
    assert got == registry_entry(SPEC)["plant_id_prefixes"]
    assert len(got) == 2
    assert got[0] == {
        "prefix": "PK",
        "pattern": r"(?i)(?<![A-Z0-9])PK\s*[-#]?\s*0*(\d{1,3})(?!\d)",
    }
    assert got[1] == {
        "prefix": "PL",
        "pattern": r"(?i)(?<![A-Z0-9])PL\s*[-#]?\s*0*(\d{1,3})(?!\d)",
    }


def test_the_migrated_patterns_still_route_realistic_discord_text(migrated):
    """The `(?i)` / `[-#]` specifics only this project's patterns have.

    The shared contract now compiles every project's patterns out of the
    migrated markdown and routes the real IDs and `checked <ID> today` prose
    (`test_the_migrated_patterns_still_route_this_projects_real_plant_ids`,
    `..._route_ids_embedded_in_free_text`), so that is not repeated here. What
    remains is what only these patterns can exercise: the `(?i)` inline flag
    against genuinely lowercase text, the `[-#]?\\s*` separator class, and the
    `(?<![A-Z0-9])` lookbehind against an alphanumeric neighbour rather than
    the generic contract's `X` prefix.

    Compiled with `ROUTING_FLAGS` — production's `re.IGNORECASE` — so this
    module tests the same matcher as the contract and as the monitor.
    """
    from migration_harness import ROUTING_FLAGS

    _, out = migrated
    patterns = {
        p["prefix"]: re.compile(p["pattern"], ROUTING_FLAGS)
        for p in _project(out)["plant_id_prefixes"]
    }

    assert patterns["PK"].search("checked pk-7 today").group(1) == "7"
    assert patterns["PK"].search("PK #12 stretching").group(1) == "12"
    assert patterns["PL"].search("PL 15 looks great").group(1) == "15"
    # cross-family and lookbehind negatives
    assert patterns["PK"].search("PL05") is None
    assert patterns["PL"].search("PK01") is None
    assert patterns["PK"].search("SPK12") is None


def test_verification_rejects_a_dropped_second_prefix(migrated):
    """The tamper the shared contract cannot express.

    `test_verification_rejects_routing_fields_reverted_to_template_defaults`
    blanks the whole list to `[]`. Losing *one* of two entries is the realistic
    multi-prefix regression — the list is still non-empty and still correct for
    ten of the thirteen plants — so it is proven separately that the gate is
    comparing the list's contents, not merely its presence.
    """
    _, out = migrated
    project_md = out / "project.md"
    pristine = project_md.read_text(encoding="utf-8")

    broken = re.sub(
        r"(plant_id_prefixes:\n)((?:- .*\n|  .*\n)+)",
        lambda m: m.group(1) + "".join(m.group(2).splitlines(True)[:2]),
        pristine,
    )
    assert broken != pristine, "tamper fixture did not modify the file"
    assert "prefix: PL" not in broken
    assert "prefix: PK" in broken

    try:
        project_md.write_text(broken, encoding="utf-8")
        report = verify_migration(
            SPEC.tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, SPEC.registry, SPEC.slug
        )
        flagged = {c["field"] for c in report.changed_fields.get("project", [])}
        assert not report.ok
        assert "plant_id_prefixes" in flagged
    finally:
        project_md.write_text(pristine, encoding="utf-8")

    assert verify_migration(
        SPEC.tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, SPEC.registry, SPEC.slug
    ).ok


# ------------------------------------------------- this project's records --


def test_plant_ids_are_the_two_families_with_their_gaps(migrated):
    """PK01..PK19 skips eight numbers and PL is 05/06/15 — a renumbering or a
    silently dropped record fails on the exact roster, not on a count."""
    _, out = migrated
    assert sorted(p["id"] for p in tracker_json(SPEC)["plants"]) == EXPECTED_IDS
    assert sorted(p.stem for p in (out / "plants").glob("*.md")) == EXPECTED_IDS


def test_every_plant_carries_all_eighteen_keys():
    """No MG07-style hole here, which is what makes the next test meaningful."""
    for plant in tracker_json(SPEC)["plants"]:
        assert set(plant) == set(SPEC.plant_keys), plant["id"]


def test_corrected_reading_is_the_only_defaulted_plant_field(migrated):
    from plant_markdown import load_schema, read_plant

    summary, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    for plant in tracker_json(SPEC)["plants"]:
        plant_id = plant["id"]
        assert summary.defaulted_fields[plant_id] == ["corrected_reading"], plant_id
        assert read_plant(out / "plants" / f"{plant_id}.md", schema=schema)[
            "corrected_reading"
        ] is None


def test_empty_string_sheet_url_and_null_sheet_id_stay_distinct(migrated):
    """The first project where `''` and `None` appear side by side.

    A reader that normalised empty strings to null (or null to `''`) round-trips
    cleanly on every earlier project and corrupts this one.
    """
    _, out = migrated
    source = tracker_json(SPEC)
    got = _project(out)

    assert source["google_sheet_id"] is None
    assert source["google_sheet_url"] == ""
    assert got["google_sheet_id"] is None
    assert got["google_sheet_url"] == ""
    assert got["google_sheet_url"] is not None
    assert "google_sheet_url: ''" in (out / "project.md").read_text(encoding="utf-8")


def test_notes_meta_survives_with_its_source_doc_and_flagged_ambiguity(migrated):
    """Present here with genuinely populated sub-fields, unlike the earlier
    projects (mule-fuel has no `notes_meta` at all; honey-badger's lists are
    all empty). The flagged ambiguity is the human-facing record of *why* two
    prefixes share one project, so losing it loses the explanation."""
    summary, out = migrated
    source = tracker_json(SPEC)["notes_meta"]
    got = _project(out)["notes_meta"]

    assert json.dumps(got, sort_keys=True) == json.dumps(source, sort_keys=True)
    assert got["source_doc"] is not None and got["source_doc"].startswith("https://")
    assert len(got["flagged_ambiguities"]) == 1
    assert "PK and PL" in got["flagged_ambiguities"][0]
    assert got["brand_assets_in_drive"] == []
    assert got["resolved_ambiguities"] == []
    assert "notes_meta" not in summary.defaulted_fields.get("project", [])


def test_statuses_and_review_flagged_selection_notes_survive(migrated):
    """Three of thirteen plants carry a human 'review and confirm' note whose
    status is deliberately NOT what the note suggests — the prose and the
    status must both survive, or a pending decision is silently resolved."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    seen_statuses = set()
    flagged = []
    for plant in tracker_json(SPEC)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert got["status"] == plant["status"], plant["id"]
        assert got["selection_notes"] == plant["selection_notes"], plant["id"]
        seen_statuses.add(got["status"])
        if plant["selection_notes"] is not None:
            flagged.append(plant["id"])
            assert "Review and confirm." in got["selection_notes"]
    assert seen_statuses == {"active", "culled", "keeper"}
    assert flagged == ["PK19", "PL06", "PL15"]


def test_every_plant_shares_the_one_photos_drive_folder(migrated):
    """Unlike the earlier projects, all 13 plants point at the SAME project-level
    photos folder with one photo each; a migration that de-duplicated repeated
    values or hoisted them to the project record would be caught."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    source_url = tracker_json(SPEC)["drive_folders"]["photos_url"]
    for plant in tracker_json(SPEC)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert got["photos_drive_url"] == source_url == plant["photos_drive_url"]
        assert got["photos"] == plant["photos"]
        assert got["photo_count"] == plant["photo_count"] == len(plant["photos"]) == 1
