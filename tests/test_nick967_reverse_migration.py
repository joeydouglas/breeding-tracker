"""Tests for NICK-967's reverse migration (markdown -> ``tracker.json``).

WHY THIS EXISTS. Task 7.2's per-project cutover cannot be marked done until a
full rollback rehearsal has been performed: forward-migrate, let Discord
observations land in markdown, reverse-migrate back into ``tracker.json``, and
diff for zero missing/duplicated observations (plan Task 7.2 step 7b/7c). The
forward half already exists (``tracker_migration``); this suite covers the
reverse half.

The single most important test here is
``test_round_trip_reproduces_every_original_plant_record``: it is the exact
assurance step 7c asks for.

Everything runs in ``tmp_path``. The live tree under ``~/.hermes/breeding`` is
only ever READ (``tracker.json`` + ``registry.json``); nothing in this module
writes to a live project.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import plant_markdown  # noqa: E402
import project_markdown  # noqa: E402
import reverse_migration  # noqa: E402
import reverse_migrate_project as rmp  # noqa: E402
import tracker_migration  # noqa: E402

LIVE_ROOT = Path.home() / ".hermes" / "breeding"
REGISTRY = LIVE_ROOT / "_shared" / "breeding-meta" / "registry.json"
PLANT_TEMPLATE = _REPO_ROOT / "templates" / "plant-template.md"
PROJECT_TEMPLATE = _REPO_ROOT / "templates" / "project-template.md"

ALL_SLUGS = [
    "lantz",
    "spaced-paste",
    "honey-badger-haze-pheno-hunt",
    "kibungan-pheno-hunt",
    "paloma-coma",
    "mule-fuel-x-nana-glue",
]

CANONICAL = tracker_migration.CANONICAL_PLANT_ID_KEY  # "plant_id"
SOURCE = tracker_migration.SOURCE_PLANT_ID_KEY  # "id"


@pytest.fixture
def plant_schema():
    return plant_markdown.load_schema(PLANT_TEMPLATE)


@pytest.fixture
def forward(tmp_path):
    """Forward-migrate a live project into ``tmp_path``; return its dir.

    This is the post-cutover state a rollback would start from.
    """

    def _make(slug, name="cutover"):
        out = tmp_path / name / slug
        tracker_migration.migrate_tracker(
            LIVE_ROOT / slug / "tracker.json",
            REGISTRY,
            slug,
            out,
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
        )
        return out

    return _make


def _live_tracker(slug):
    return json.loads(
        (LIVE_ROOT / slug / "tracker.json").read_text(encoding="utf-8")
    )


def _by_id(tracker):
    return {p[SOURCE]: p for p in tracker["plants"]}


# --------------------------------------------------------------- shape -----


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_produced_tracker_has_the_real_trackers_top_level_keys(
    slug, forward, plant_schema
):
    """Every key the real tracker.json carries must come back.

    This only checks ONE direction (nothing lost). The other direction --
    which keys the round trip ADDS -- is deliberately not asserted here
    because it cannot be a plain equality; see
    ``test_round_trip_top_level_keys_lose_nothing_and_add_only_known_defaults``
    below, which pins both directions exactly and carries the explanation.
    """
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    original = _live_tracker(slug)
    missing = set(original) - set(produced)
    assert not missing, f"{slug}: top-level keys lost: {sorted(missing)}"


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_produced_tracker_omits_markdown_only_and_registry_fields(
    slug, forward, plant_schema
):
    """``plant_order``/``body`` are markdown-only; routing fields are the
    registry's, never the tracker's."""
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    for field in ("plant_order", "body", "auto_create", "plant_id_prefixes"):
        assert field not in produced, f"{slug}: {field} leaked into tracker.json"


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_plant_records_use_the_trackers_native_id_spelling(
    slug, forward, plant_schema
):
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    assert produced["plants"], f"{slug}: no plants produced"
    for record in produced["plants"]:
        assert SOURCE in record
        assert CANONICAL not in record, "canonical markdown key leaked"


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_produced_tracker_is_json_serialisable(slug, forward, plant_schema):
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    assert json.loads(json.dumps(produced)) == produced


def _set_plant_order(project_dir, order):
    """Add the runtime's ``plant_order`` key to a project.md.

    The forward migration does not write it -- ``markdown_backend`` /
    ``generate_live_project_md`` do, and every LIVE project.md carries it. A
    reverse-migration test that only ever saw forward-migrated files would
    never exercise the key at all, which is precisely the file the rollback
    reads.
    """
    schema = project_markdown.load_schema(PROJECT_TEMPLATE)
    path = project_dir / "project.md"
    record = project_markdown.read_project(path, schema=schema)
    record["plant_order"] = list(order)
    project_markdown.write_project(path, record, schema=schema)


def test_plant_order_drives_the_plants_array_and_never_leaks(
    forward, plant_schema
):
    """``plant_order`` is a markdown-format construct: it orders the output,
    but no ``tracker.json`` has ever carried the key itself."""
    project_dir = forward("lantz")
    reversed_order = sorted(
        (p.stem for p in (project_dir / "plants").glob("*.md")), reverse=True
    )
    _set_plant_order(project_dir, reversed_order)

    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)

    assert "plant_order" not in produced
    assert [p[SOURCE] for p in produced["plants"]] == reversed_order
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert report.ok, report.as_dict()


# ---------------------------------------------------------- round trip -----


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_round_trip_reproduces_every_original_plant_record(
    slug, forward, plant_schema
):
    """forward(tracker.json) -> reverse() must reproduce every plant record.

    This is plan Task 7.2 step 7c's diff-for-zero-loss check, executed against
    all six real projects. Fields the markdown template materialised that the
    original JSON never had are ADDITIONS, not loss (same doctrine as
    ``tracker_migration.verify_migration``), so the assertion is that every
    ORIGINAL field is present and identical, under the original ``id``
    spelling, with the roster matching exactly.
    """
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    original = _live_tracker(slug)

    got = _by_id(produced)
    want = _by_id(original)
    assert sorted(got) == sorted(want), f"{slug}: roster changed"
    assert len(produced["plants"]) == len(original["plants"]), "duplication"

    for plant_id, source in want.items():
        for field, value in source.items():
            assert field in got[plant_id], f"{slug}.{plant_id}.{field} lost"
            assert got[plant_id][field] == value, (
                f"{slug}.{plant_id}.{field} changed"
            )


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_reverse_migration_is_idempotent(slug, forward, plant_schema):
    project_dir = forward(slug)
    first = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    second = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    assert first == second


# -------------------------------------------------------- verification -----


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_verification_passes_on_a_clean_reverse_migration(
    slug, forward, plant_schema
):
    project_dir = forward(slug)
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert report.ok, report.as_dict()
    assert report.verified_something
    assert report.records_compared > 0
    assert report.fields_compared > 0


def test_verification_is_not_vacuous_on_an_empty_directory(
    tmp_path, plant_schema
):
    """A gate that compared nothing must report failure, not success."""
    empty = tmp_path / "empty"
    (empty / "plants").mkdir(parents=True)
    report = reverse_migration.verify_reverse_migration(
        empty, {"plants": []}, plant_schema
    )
    assert not report.ok
    assert not report.verified_something


def test_verification_flags_a_plant_missing_from_the_produced_tracker(
    forward, plant_schema
):
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    dropped = produced["plants"].pop(0)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert dropped[SOURCE] in report.missing_records


def test_verification_flags_a_plant_the_markdown_does_not_have(
    forward, plant_schema
):
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    produced["plants"].append({SOURCE: "GHOST01", "cross": "Lantz"})
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert "GHOST01" in report.extra_records


def test_verification_flags_a_duplicated_plant_record(forward, plant_schema):
    """Step 7c requires zero DUPLICATED observations, not just zero missing."""
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    duplicated = dict(produced["plants"][0])
    produced["plants"].append(duplicated)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert duplicated[SOURCE] in report.duplicate_records


def test_verification_flags_a_changed_field_value(forward, plant_schema):
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    victim = produced["plants"][0]
    victim["status"] = "TAMPERED"
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    changed = report.changed_fields[victim[SOURCE]]
    assert any(entry["field"] == "status" for entry in changed)


def test_verification_flags_a_lost_field(forward, plant_schema):
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    victim = produced["plants"][0]
    victim.pop("terpene_notes")
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert "terpene_notes" in report.lost_fields[victim[SOURCE]]


def test_verification_flags_a_leaked_canonical_plant_id_key(
    forward, plant_schema
):
    """``plant_id`` is the markdown spelling; tracker.json must not carry it."""
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    victim = produced["plants"][0]
    victim[CANONICAL] = victim[SOURCE]
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert CANONICAL in report.illegal_fields[victim[SOURCE]]


def test_verification_flags_body_content_absent_from_the_produced_tracker(
    forward, plant_schema
):
    """The zero-loss check: markdown body text the tracker does not carry.

    Silently dropping it is exactly the failure step 7c exists to catch, so
    the report must name it rather than the diff coming back clean.
    """
    project_dir = forward("kibungan-pheno-hunt")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)

    target = project_dir / "plants" / "PK07.md"
    stamp = "2026-09-07T09:15:00.000001"
    text = target.read_text(encoding="utf-8")
    assert stamp not in text, "fixture already carries the observation"
    target.write_text(
        text.rstrip("\n") + f"\n\n### {stamp}\nPK07 post-cutover note\n",
        encoding="utf-8",
    )

    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    orphans = report.unrepresented_observations["PK07"]
    assert any("post-cutover note" in o["text"] for o in orphans)


# ------------------------------- the case the rollback procedure exists for -


def test_observation_written_after_cutover_survives_the_reverse_migration(
    forward, plant_schema
):
    """Task 7.2 step 7b, end to end.

    Simulates the real sequence: the project is cut over to markdown, a
    Discord observation is appended to a plant's ``observation_log`` body by
    the runtime write path's writer, and the rollback then reverse-migrates
    back to ``tracker.json``. The new text must be in the produced tracker's
    ``observation_log``, and the verification must come back clean.
    """
    project_dir = forward("paloma-coma")
    path = next(iter(sorted((project_dir / "plants").glob("*.md"))))
    plant_id = path.stem

    record = plant_markdown.read_plant(path, schema=plant_schema)
    stamp = "2026-09-07T10:00:00.000002"
    new_text = "purple stems showing, strong gas nose"
    record[plant_markdown.BODY_FIELD] = (
        (record.get(plant_markdown.BODY_FIELD) or "").rstrip("\n")
        + f"\n\n### {stamp}\n{new_text}\n"
    )
    plant_markdown.write_plant(path, record, schema=plant_schema)

    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    got = _by_id(produced)[plant_id]

    assert stamp in got["observation_log"]
    assert new_text in got["observation_log"]

    original_log = _by_id(_live_tracker("paloma-coma"))[plant_id][
        "observation_log"
    ] or ""
    assert original_log.strip() in got["observation_log"], "history truncated"
    assert got["observation_log"].count(new_text) == 1, "observation duplicated"

    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert report.ok, report.as_dict()


# ------------------------------------------------------------------ cli -----


def test_cli_dry_run_writes_nothing(forward, capsys):
    project_dir = forward("lantz")
    target = project_dir / "tracker.json"
    before = {p.name: p.read_bytes() for p in (project_dir / "plants").glob("*.md")}

    exit_code = rmp.main(
        [
            "lantz",
            "--breeding-root",
            str(project_dir.parent),
            "--registry",
            str(REGISTRY),
            "--template",
            str(PLANT_TEMPLATE),
        ]
    )

    assert exit_code == 0
    assert not target.exists(), "dry run wrote tracker.json"
    after = {p.name: p.read_bytes() for p in (project_dir / "plants").glob("*.md")}
    assert after == before
    assert "dry run" in capsys.readouterr().out


def test_cli_apply_writes_one_tracker_json_and_no_markdown(forward):
    project_dir = forward("lantz")
    target = project_dir / "tracker.json"
    before = {p.name: p.read_bytes() for p in (project_dir / "plants").glob("*.md")}

    exit_code = rmp.main(
        [
            "lantz",
            "--breeding-root",
            str(project_dir.parent),
            "--registry",
            str(REGISTRY),
            "--template",
            str(PLANT_TEMPLATE),
            "--apply",
        ]
    )

    assert exit_code == 0
    assert target.is_file()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert {p[SOURCE] for p in written["plants"]} == {
        p[SOURCE] for p in _live_tracker("lantz")["plants"]
    }
    after = {p.name: p.read_bytes() for p in (project_dir / "plants").glob("*.md")}
    assert after == before, "the reverse migration touched plants/*.md"


def test_cli_refuses_to_write_when_verification_fails(forward, plant_schema):
    """Falsification: nothing reaches disk when the diff is not clean."""
    project_dir = forward("lantz")
    result = rmp.plan(project_dir, REGISTRY, "lantz", PLANT_TEMPLATE)
    result.report.missing_records.append("synthetic failure")
    target = project_dir / "tracker.json"

    with pytest.raises(rmp.ReverseMigrationError):
        rmp.apply(result, target)
    assert not target.exists()


def test_cli_refuses_a_target_that_is_not_a_tracker_json(forward):
    project_dir = forward("lantz")
    result = rmp.plan(project_dir, REGISTRY, "lantz", PLANT_TEMPLATE)
    with pytest.raises(rmp.ReverseMigrationError):
        rmp.apply(result, project_dir / "plants" / "Ltz01.md")


def test_cli_refuses_when_nothing_was_compared(tmp_path):
    empty = tmp_path / "ghost"
    (empty / "plants").mkdir(parents=True)
    with pytest.raises(rmp.ReverseMigrationError):
        rmp.plan(empty, REGISTRY, "lantz", PLANT_TEMPLATE)


def test_cli_plan_carries_post_cutover_observations_into_the_tracker(forward):
    """The markdown IS the source, so an appended observation must land in the
    planned tracker and the diff must still come back clean."""
    project_dir = forward("kibungan-pheno-hunt")
    target = project_dir / "plants" / "PK07.md"
    target.write_text(
        target.read_text(encoding="utf-8").rstrip("\n")
        + "\n\n### 2026-09-07T11:00:00.000003\nunrepresented\n",
        encoding="utf-8",
    )
    result = rmp.plan(
        project_dir, REGISTRY, "kibungan-pheno-hunt", PLANT_TEMPLATE
    )
    assert result.report.ok, result.report.as_dict()
    assert "unrepresented" in json.dumps(result.tracker)


# ------------------------------------- project-level verification (GAP 1) ---
#
# The first cut of ``verify_reverse_migration`` compared ONLY the ``plants``
# array. Every top-level project field -- cross_name, google_sheet_id,
# drive_folders, github_repo -- could be corrupted, deleted, retyped or
# invented and the report still came back ``ok=True``. That defeats the whole
# purpose of the gate: plan Task 7.2 step 7c says "diff the reverse-migration
# output against the markdown source [...] if the diff shows any discrepancy,
# STOP", and that requirement is scoped to the whole tracker.json, not to the
# plants array. These five cases are the reviewer's exact reproductions.


PROJECT_ID = reverse_migration.PROJECT_RECORD_ID


def _clean(project_dir, plant_schema):
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert report.ok, report.as_dict()
    return produced


def test_verification_flags_a_garbage_cross_name(forward, plant_schema):
    project_dir = forward("lantz")
    produced = _clean(project_dir, plant_schema)
    produced["cross_name"] = "GARBAGE-NOT-THE-REAL-NAME"
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    changed = report.changed_fields[PROJECT_ID]
    assert any(entry["field"] == "cross_name" for entry in changed), changed


def test_verification_flags_a_deleted_google_sheet_id(forward, plant_schema):
    project_dir = forward("lantz")
    produced = _clean(project_dir, plant_schema)
    del produced["google_sheet_id"]
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert "google_sheet_id" in report.lost_fields[PROJECT_ID]


def test_verification_flags_corrupted_drive_folders(forward, plant_schema):
    """A dict retyped to a string is a change, not an equal value."""
    project_dir = forward("lantz")
    produced = _clean(project_dir, plant_schema)
    produced["drive_folders"] = "corrupted-into-a-string"
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    changed = report.changed_fields[PROJECT_ID]
    assert any(entry["field"] == "drive_folders" for entry in changed), changed


def test_verification_flags_a_nulled_github_repo(forward, plant_schema):
    project_dir = forward("lantz")
    produced = _clean(project_dir, plant_schema)
    produced["github_repo"] = None
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    changed = report.changed_fields[PROJECT_ID]
    assert any(entry["field"] == "github_repo" for entry in changed), changed


def test_verification_flags_an_invented_top_level_key(forward, plant_schema):
    """A field the markdown never had must not appear in the tracker."""
    project_dir = forward("lantz")
    produced = _clean(project_dir, plant_schema)
    produced["invented_key"] = "where did this come from"
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert "invented_key" in report.illegal_fields[PROJECT_ID]


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_project_fields_are_actually_counted_as_compared(
    slug, forward, plant_schema
):
    """``fields_compared`` must grow by the project's own fields.

    Otherwise a future regression could stop comparing project fields and
    ``verified_something`` would not notice.
    """
    project_dir = forward(slug)
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    record, _order = reverse_migration.read_project_record(project_dir)

    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    plants_only = sum(
        len(p) for p in produced["plants"]
    )
    assert report.fields_compared == plants_only + len(record)
    assert report.records_compared == len(produced["plants"]) + 1


def test_markdown_only_fields_leaking_into_the_tracker_are_flagged(
    forward, plant_schema
):
    """``plant_order``/``auto_create`` are never tracker.json fields."""
    project_dir = forward("lantz")
    produced = _clean(project_dir, plant_schema)
    produced["plant_order"] = ["Ltz01"]
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert not report.ok
    assert "plant_order" in report.illegal_fields[PROJECT_ID]


def test_cli_second_apply_without_overwrite_is_a_clean_refusal(forward, capsys):
    """No raw traceback for an expected refusal.

    Re-running --apply against an existing tracker.json is an ordinary
    operator mistake during a rehearsal. It used to escape as an uncaught
    ReverseMigrationError traceback while the verification-failure path
    printed a tidy 'REFUSING TO WRITE' and exited 1; both must behave alike.
    """
    project_dir = forward("lantz")
    argv = [
        "lantz",
        "--breeding-root", str(project_dir.parent),
        "--registry", str(REGISTRY),
        "--template", str(PLANT_TEMPLATE),
        "--apply",
    ]
    assert rmp.main(argv) == 0
    target = project_dir / "tracker.json"
    first = target.read_bytes()
    capsys.readouterr()

    exit_code = rmp.main(argv)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "REFUSING TO WRITE" in out
    assert target.read_bytes() == first, "the refused run still rewrote the file"


def test_cli_reports_a_corrupted_project_field(forward, capsys, monkeypatch):
    """A project-level discrepancy must reach the operator's screen."""
    project_dir = forward("lantz")
    real = reverse_migration.reverse_migrate_tracker

    def _corrupting(directory, schema):
        tracker = real(directory, schema)
        tracker["cross_name"] = "GARBAGE"
        return tracker

    monkeypatch.setattr(
        reverse_migration, "reverse_migrate_tracker", _corrupting
    )
    exit_code = rmp.main(
        [
            "lantz",
            "--breeding-root", str(project_dir.parent),
            "--registry", str(REGISTRY),
            "--template", str(PLANT_TEMPLATE),
            "--apply",
        ]
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "cross_name" in out
    assert not (project_dir / "tracker.json").exists()


# ------------------------------- top-level key fidelity (GAP 2, measured) ---
#
# The round-trip's top-level key set is NOT exactly equal to the original
# tracker.json's for all six projects, and cannot be made so from the markdown
# alone. Proof, from the live corpus:
#
#     lantz/project.md contains  `genetics: null`  and  `google_sheet_id: null`
#
# Byte-identical declarations, identical template defaults (both null) -- yet
# `google_sheet_id` IS a key of lantz's real tracker.json and `genetics` is
# NOT. No function of project.md can separate them, because the distinguishing
# information was destroyed EARLIER, by the forward migration:
# `tracker_migration._apply_defaults` materialises every template-declared
# field into project.md whether or not the source tracker had it. By the time
# a reverse migration reads the file, "absent from the tracker" and "present
# and null" look the same.
#
# `read_project_record` already restricts to the file's own keys (via
# `_restrict_to_present`, same as the plant side) -- that is not the defect.
# The residue is upstream and is a genuine, if minor, rollback-fidelity bug:
# the rolled-back tracker.json gains null-valued keys the pre-cutover file
# lacked. Fixing it means changing what the forward migration writes into
# every live project.md, which is out of this change's scope.
#
# So this test pins the EXACT measured deviation rather than asserting a
# one-directional subset (which would hide any new drift) or exact equality
# (which would be a known-failing assertion). Zero keys may be LOST in any
# project, and only these precise, null-valued extras may be gained.

#: The exact spurious top-level keys each project's round trip adds, all of
#: them template defaults materialised by the forward migration. Any change
#: to this map is a real behavioural change and must be justified.
#:
#: This map is NOT re-declared here. It lives in the module under test, which
#: needs it to surface these deviations to an operator (see the
#: known-deviation tests at the end of this file), and a second copy kept in
#: the tests could drift from the one the tool actually acts on -- the tests
#: would then keep passing while the shipped behaviour changed.
KNOWN_MATERIALISED_EXTRAS = reverse_migration.KNOWN_MATERIALISED_EXTRAS


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_round_trip_top_level_keys_lose_nothing_and_add_only_known_defaults(
    slug, forward, plant_schema
):
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    original = _live_tracker(slug)

    lost = set(original) - set(produced)
    assert not lost, f"{slug}: top-level keys LOST: {sorted(lost)}"

    gained = set(produced) - set(original)
    assert gained == KNOWN_MATERIALISED_EXTRAS[slug], (
        f"{slug}: top-level key drift -- expected extras "
        f"{sorted(KNOWN_MATERIALISED_EXTRAS[slug])}, got {sorted(gained)}"
    )


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_every_gained_top_level_key_is_an_empty_template_default(
    slug, forward, plant_schema
):
    """The extras must be inert defaults, never invented CONTENT.

    A materialised `genetics: null` is a cosmetic blemish on a rolled-back
    file. A materialised key carrying a real-looking value would be fabricated
    data, which is a different and far more serious thing.
    """
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    schema = project_markdown.load_schema(PROJECT_TEMPLATE)
    for key in KNOWN_MATERIALISED_EXTRAS[slug]:
        assert produced[key] in (None, {}, [], ""), (
            f"{slug}: gained key {key!r} carries invented content "
            f"{produced[key]!r}"
        )
        assert produced[key] == schema[key]["default"]


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_round_trip_preserves_every_original_top_level_value(
    slug, forward, plant_schema
):
    """Not just the keys -- every original top-level VALUE must survive."""
    produced = reverse_migration.reverse_migrate_tracker(
        forward(slug), plant_schema
    )
    original = _live_tracker(slug)
    for field, value in original.items():
        if field == "plants":
            continue
        assert produced[field] == value, f"{slug}.{field} changed"


# ------------------------------- known-deviation surfacing (GAP 2 note) -----
#
# Joey's decision (2026-09-07): the phantom fields documented above are inert
# template defaults, their root cause is upstream in NICK-966's already-shipped
# forward migration, and they must NOT block the rollback-safety gate. But
# "does not block" must not mean "invisible": an operator running an actual
# rollback has to SEE that the file they are about to restore differs from the
# pre-cutover one, rather than reading a bare ``ok=True`` that quietly hides it.
#
# So the carve-out is deliberately narrow and is tested from both sides: the
# EXACT known keys land in ``known_deviations`` and keep the gate green, while
# ANY other unexpected key must still fail the gate as an illegal field. A
# carve-out that swallowed a genuine new bug would be worse than no carve-out.


def test_known_deviations_are_exposed_in_as_dict_and_repr(forward, plant_schema):
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert "known_deviations" in report.as_dict()
    assert "known_deviations" in repr(report)


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_known_deviations_report_exactly_the_materialised_extras(
    slug, forward, plant_schema
):
    """Each affected project reports its own known extras; the rest report none.

    The comparison is against the LIVE tracker.json, i.e. what a real rollback
    would be restoring over -- the same source the KNOWN_MATERIALISED_EXTRAS
    map was measured from.
    """
    project_dir = forward(slug)
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )

    expected = KNOWN_MATERIALISED_EXTRAS[slug]
    reported = set(report.known_deviations.get(PROJECT_ID, []))
    assert reported == expected, (
        f"{slug}: known_deviations {sorted(reported)} != expected "
        f"{sorted(expected)}"
    )
    if not expected:
        assert PROJECT_ID not in report.known_deviations, (
            f"{slug} has no known extras and must not appear at all"
        )


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_known_deviations_alone_keep_the_gate_green(slug, forward, plant_schema):
    """Joey's decision: known inert extras are surfaced, never blocking."""
    project_dir = forward(slug)
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )
    assert report.ok, report.as_dict()
    assert not report.illegal_fields.get(PROJECT_ID), (
        f"{slug}: a KNOWN extra was miscounted as illegal: "
        f"{report.illegal_fields.get(PROJECT_ID)}"
    )


def test_an_unknown_extra_key_still_fails_the_gate(forward, plant_schema):
    """The carve-out must not swallow a genuine new bug.

    This is the test that makes the carve-out safe to have at all: a key that
    is NOT in the known set stays an illegal field and still drives ``ok``
    False, even on a project (lantz) that legitimately carries known
    deviations at the same time.
    """
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    produced["totally_new_bug"] = "fabricated content"

    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )

    assert not report.ok, report.as_dict()
    assert "totally_new_bug" in report.illegal_fields[PROJECT_ID]
    assert "totally_new_bug" not in report.known_deviations.get(PROJECT_ID, [])
    # ...and the known ones are still classified as known, not promoted to
    # illegal just because something else went wrong.
    assert set(report.known_deviations[PROJECT_ID]) == KNOWN_MATERIALISED_EXTRAS[
        "lantz"
    ]


def test_a_known_key_carrying_real_content_is_not_excused(forward, plant_schema):
    """The carve-out covers inert DEFAULTS, not the key name in the abstract.

    ``genetics`` is a known materialised extra only while it is the template's
    own empty default. If it ever comes back holding invented content, that is
    fabricated data in a rollback artifact: it must fail the gate and must
    stop being reported as a benign known deviation.
    """
    project_dir = forward("lantz")
    produced = reverse_migration.reverse_migrate_tracker(project_dir, plant_schema)
    produced["genetics"] = "INVENTED STRAIN LINEAGE"

    report = reverse_migration.verify_reverse_migration(
        project_dir, produced, plant_schema
    )

    assert not report.ok, report.as_dict()
    changed = report.changed_fields[PROJECT_ID]
    assert any(entry["field"] == "genetics" for entry in changed), changed
    assert "genetics" not in report.known_deviations.get(PROJECT_ID, [])


def test_cli_dry_run_prints_the_known_deviation_warning(forward, capsys):
    """An operator must see the deviation before deciding to roll back."""
    project_dir = forward("lantz")
    exit_code = rmp.main(
        [
            "lantz",
            "--breeding-root", str(project_dir.parent),
            "--registry", str(REGISTRY),
            "--template", str(PLANT_TEMPLATE),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "KNOWN DEVIATION" in out
    assert "breeder_lineage" in out
    assert "genetics" in out


def test_cli_apply_still_warns_and_writes(forward, capsys):
    """The warning precedes the write; it does not replace it."""
    project_dir = forward("lantz")
    exit_code = rmp.main(
        [
            "lantz",
            "--breeding-root", str(project_dir.parent),
            "--registry", str(REGISTRY),
            "--template", str(PLANT_TEMPLATE),
            "--apply",
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "KNOWN DEVIATION" in out
    assert (project_dir / "tracker.json").is_file()
    assert out.index("KNOWN DEVIATION") < out.index("[written]")


def test_cli_says_nothing_about_deviations_when_there_are_none(forward, capsys):
    """No noise on the three clean projects."""
    project_dir = forward("paloma-coma")
    rmp.main(
        [
            "paloma-coma",
            "--breeding-root", str(project_dir.parent),
            "--registry", str(REGISTRY),
            "--template", str(PLANT_TEMPLATE),
        ]
    )
    assert "KNOWN DEVIATION" not in capsys.readouterr().out
