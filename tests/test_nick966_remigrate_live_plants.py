"""Tests for the NICK-966 live ``plants/*.md`` re-migration glue.

The migration itself is covered by Phase 3's suite; these tests cover only
what this glue adds on top:

* it selects the right plants (whole-project, or an explicit subset for
  mule-fuel's 9 stubs);
* it VERIFIES field-by-field against ``tracker.json`` before a single live
  byte is written, and refuses to write if verification fails;
* it never writes ``tracker.json`` (md5 asserted before/after);
* it never touches a plant file outside the requested selection -- the
  guarantee mule-fuel's 36 legacy records depend on;
* it reports, rather than silently discards, body content that exists in the
  file on disk but NOT in ``tracker.json``.

Everything here runs against a COPY of a live project in ``tmp_path``.
Nothing reads or writes ``~/.hermes/breeding/<project>``.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "tools"))

from breeding_tracker import plant_markdown  # noqa: E402
import remigrate_live_plants as remig  # noqa: E402
from breeding_tracker import tracker_migration  # noqa: E402

LIVE_ROOT = Path.home() / ".hermes" / "breeding"
REGISTRY = LIVE_ROOT / "_shared" / "breeding-meta" / "registry.json"
PLANT_TEMPLATE = _REPO_ROOT / "breeding_tracker" / "templates" / "plant-template.md"

ALL_SLUGS = [
    "lantz",
    "spaced-paste",
    "honey-badger-haze-pheno-hunt",
    "kibungan-pheno-hunt",
    "paloma-coma",
    "mule-fuel-x-nana-glue",
]


@pytest.fixture
def sandbox(tmp_path):
    """A tmp copy of one live project (tracker.json + plants/)."""

    def _make(slug):
        project_dir = tmp_path / slug
        project_dir.mkdir()
        shutil.copy2(LIVE_ROOT / slug / "tracker.json", project_dir / "tracker.json")
        shutil.copytree(LIVE_ROOT / slug / "plants", project_dir / "plants")
        return project_dir

    return _make


def _tracker(project_dir):
    return json.loads((project_dir / "tracker.json").read_text(encoding="utf-8"))


def _by_id(project_dir):
    return {p["id"]: p for p in _tracker(project_dir)["plants"]}


# ------------------------------------------------------------- selection ----


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_plan_defaults_to_every_plant_in_the_tracker(slug, sandbox):
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    assert sorted(plan.plant_ids) == sorted(_by_id(project_dir))


def test_plan_honours_an_explicit_subset(sandbox):
    """mule-fuel: only the 9 stubs, never the 36 legacy records."""
    project_dir = sandbox("mule-fuel-x-nana-glue")
    only = ["MG05", "MG07", "MG15"]
    plan = remig.plan(
        project_dir, REGISTRY, "mule-fuel-x-nana-glue", PLANT_TEMPLATE, only=only
    )
    assert sorted(plan.plant_ids) == sorted(only)


def test_plan_rejects_an_id_that_is_not_in_the_tracker(sandbox):
    project_dir = sandbox("lantz")
    with pytest.raises(remig.RemigrationError) as exc:
        remig.plan(project_dir, REGISTRY, "lantz", PLANT_TEMPLATE, only=["NOPE01"])
    assert "NOPE01" in str(exc.value)


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_planned_ids_match_the_tracker_roster_exactly(slug, sandbox):
    """No extras, no omissions -- the pre-write roster gate."""
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    roster = set(_by_id(project_dir))
    assert set(plan.plant_ids) == roster
    assert len(plan.plant_ids) == len(roster)


# ----------------------------------------------------- content correctness --


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_every_planned_record_carries_the_canonical_plant_id_key(slug, sandbox):
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    for plant_id, record in plan.records.items():
        assert record[tracker_migration.CANONICAL_PLANT_ID_KEY] == plant_id
        assert tracker_migration.SOURCE_PLANT_ID_KEY not in record


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_every_source_field_survives_into_the_planned_record(slug, sandbox):
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    source = _by_id(project_dir)
    for plant_id, record in plan.records.items():
        for key, value in source[plant_id].items():
            target = (
                tracker_migration.CANONICAL_PLANT_ID_KEY
                if key == tracker_migration.SOURCE_PLANT_ID_KEY
                else key
            )
            assert target in record, f"{plant_id}.{key} lost"
            assert record[target] == value, f"{plant_id}.{key} changed"


# ---------------------------------------------------------------- writing --


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_apply_writes_a_file_for_every_planned_plant(slug, sandbox):
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    result = remig.apply(plan)
    for plant_id in plan.plant_ids:
        path = project_dir / "plants" / f"{plant_id}.md"
        assert path.is_file()
        assert f"plant_id: {plant_id}\n" in path.read_text(encoding="utf-8")
    assert sorted(result.written) == sorted(plan.plant_ids)


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_written_files_read_back_equal_to_the_tracker(slug, sandbox):
    """The post-write proof, re-read from disk rather than from memory."""
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    remig.apply(plan)
    schema = plant_markdown.load_schema(PLANT_TEMPLATE)
    source = _by_id(project_dir)
    for plant_id in plan.plant_ids:
        got = plant_markdown.read_plant(
            project_dir / "plants" / f"{plant_id}.md", schema=schema
        )
        for key, value in source[plant_id].items():
            target = (
                tracker_migration.CANONICAL_PLANT_ID_KEY
                if key == tracker_migration.SOURCE_PLANT_ID_KEY
                else key
            )
            assert got[target] == value, f"{plant_id}.{key}"


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_tracker_json_is_byte_identical_after_a_full_run(slug, sandbox):
    project_dir = sandbox(slug)
    before = (project_dir / "tracker.json").read_bytes()
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    remig.apply(plan)
    assert (project_dir / "tracker.json").read_bytes() == before


def test_files_outside_the_selection_are_left_byte_identical(sandbox):
    """mule-fuel's 36 legacy records must not be touched by the 9-stub run."""
    project_dir = sandbox("mule-fuel-x-nana-glue")
    only = ["MG05", "MG07", "MG15"]
    before = {
        p.name: p.read_bytes()
        for p in (project_dir / "plants").glob("*.md")
        if p.stem not in only
    }
    assert len(before) == 42, "fixture no longer discriminates"
    plan = remig.plan(
        project_dir, REGISTRY, "mule-fuel-x-nana-glue", PLANT_TEMPLATE, only=only
    )
    remig.apply(plan)
    after = {
        p.name: p.read_bytes()
        for p in (project_dir / "plants").glob("*.md")
        if p.stem not in only
    }
    assert after == before


def test_apply_creates_a_file_that_did_not_exist(sandbox):
    """A plant with no markdown file at all must be created, not skipped.

    Lantz's Ltz03/Ltz06 and spaced-paste's four missing plants were exactly
    this case before NICK-966 ran. The missing file is created HERE by
    deleting it from the sandbox copy, rather than by relying on the live
    tree still being in its broken pre-migration state -- otherwise this test
    silently stops testing anything the moment the fix it guards is applied.
    """
    project_dir = sandbox("lantz")
    victim = project_dir / "plants" / "Ltz03.md"
    victim.unlink(missing_ok=True)
    assert not victim.exists()

    plan = remig.plan(project_dir, REGISTRY, "lantz", PLANT_TEMPLATE)
    result = remig.apply(plan)

    assert victim.is_file()
    assert "Ltz03" in result.created


# --------------------------------------------------------------- the gate --


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_plan_verification_passes_on_real_data(slug, sandbox):
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    assert plan.verification_ok, plan.verification_problems
    assert plan.fields_compared > 0


def test_apply_refuses_when_verification_failed(sandbox, monkeypatch):
    """Falsification: a plan that did not verify must never reach the disk."""
    project_dir = sandbox("lantz")
    plan = remig.plan(project_dir, REGISTRY, "lantz", PLANT_TEMPLATE)
    plan.verification_problems.append("synthetic failure")
    before = {
        p.name: p.read_bytes() for p in (project_dir / "plants").glob("*.md")
    }
    with pytest.raises(remig.RemigrationError):
        remig.apply(plan)
    after = {p.name: p.read_bytes() for p in (project_dir / "plants").glob("*.md")}
    assert after == before, "a failed plan still wrote to disk"


def test_verification_is_not_vacuous(sandbox):
    """A gate that compared nothing must report as failed, not as clean."""
    project_dir = sandbox("lantz")
    plan = remig.plan(project_dir, REGISTRY, "lantz", PLANT_TEMPLATE, only=[])
    assert not plan.verification_ok


# ------------------------------------------- orphan (unaccounted) content ---


def test_orphan_observations_are_reported_not_silently_dropped(sandbox):
    """Live md bodies may hold observation blocks tracker.json never got.

    Found during NICK-966: HBH07, PK07, MG07 and MG15 each carried
    timestamped ``### <iso>`` blocks on disk that were ABSENT from their
    tracker record (misrouted copies of a Paloma Coma message, plus two
    NICK-9 pipeline test strings). Re-migrating from the tracker necessarily
    drops them, so the tool must surface them for a human decision rather
    than quietly overwrite.

    The orphan block is INJECTED into the sandbox copy here rather than read
    from the live tree: those real orphans no longer exist on disk once this
    task's re-migration has run, and a test that depends on them would go
    quietly vacuous exactly when the behaviour still needs guarding.
    """
    project_dir = sandbox("kibungan-pheno-hunt")
    target = project_dir / "plants" / "PK07.md"
    stamp = "2026-08-31T21:46:25.809980"
    text = target.read_text(encoding="utf-8")
    assert stamp not in text, "fixture already carries the orphan"
    target.write_text(
        text.rstrip("\n") + f"\n\n### {stamp}\nPK07 orphaned observation\n",
        encoding="utf-8",
    )

    plan = remig.plan(project_dir, REGISTRY, "kibungan-pheno-hunt", PLANT_TEMPLATE)

    assert "PK07" in plan.orphan_observations
    orphans = plan.orphan_observations["PK07"]
    assert [o["timestamp"] for o in orphans] == [stamp]
    assert "orphaned observation" in orphans[0]["text"]


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_orphan_detection_never_reports_content_the_tracker_does_have(
    slug, sandbox
):
    project_dir = sandbox(slug)
    plan = remig.plan(project_dir, REGISTRY, slug, PLANT_TEMPLATE)
    source = _by_id(project_dir)
    for plant_id, orphans in plan.orphan_observations.items():
        log = source[plant_id].get("observation_log") or ""
        for orphan in orphans:
            assert orphan["timestamp"] not in log


def test_a_plant_with_no_orphans_is_absent_from_the_report(sandbox):
    project_dir = sandbox("paloma-coma")
    plan = remig.plan(project_dir, REGISTRY, "paloma-coma", PLANT_TEMPLATE)
    assert "PC07" not in plan.orphan_observations
