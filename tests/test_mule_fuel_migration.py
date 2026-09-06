"""Task 3.1 — migrate the REAL mule-fuel-x-nana-glue tracker, sandbox-only.

This is the acceptance test for Phase 3's first project. It runs the actual
migration against the actual `/home/joey/.hermes/breeding/mule-fuel-x-nana-glue/
tracker.json` and proves, per the plan's Task 3.x acceptance criteria:

(a) plant count matches exactly;
(b) every field round-trips with zero data loss, diffed against Task 3.0's
    field inventory rather than a hand-listed subset;
(c) the migration is sandbox-only (writes land in pytest's tmp_path, and the
    module-level sandbox guard refuses anything else);
(d) `tracker.json`'s md5 is unchanged afterwards, AND no real Discord/Drive/
    git-push side effect was possible — proven by booby-trapping subprocess,
    socket and urllib for the duration of the run, and by fingerprinting the
    entire live project directory before and after.

Skips cleanly if the real tracker is not present on this machine.
"""

import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest

from tracker_migration import file_md5, migrate_tracker, verify_migration

REPO = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATE = REPO / "templates" / "project-template.md"
PLANT_TEMPLATE = REPO / "templates" / "plant-template.md"

SLUG = "mule-fuel-x-nana-glue"
LIVE_DIR = Path.home() / ".hermes" / "breeding" / SLUG
TRACKER = LIVE_DIR / "tracker.json"
REGISTRY = Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"

#: Task 3.0 field inventory, §1/§2, restricted to this project.
INVENTORY_PROJECT_KEYS = {
    "created",
    "cross_name",
    "drive_folders",
    "github_pages_url",
    "github_repo",
    "google_sheet_id",
    "google_sheet_url",
    "last_updated",
    "plants",
}
INVENTORY_PLANT_KEYS = {
    "cross",
    "flower_flip",
    "germ_date",
    "harvest_date",
    "id",
    "issues",
    "observation_log",
    "original_notes",
    "photo_count",
    "photos",
    "photos_drive_url",
    "selection_notes",
    "sex",
    "status",
    "structure",
    "terpene_notes",
    "veg_start",
    "vigor",
}
INVENTORY_PLANT_COUNT = 45

requires_real_data = pytest.mark.skipif(
    not TRACKER.exists() or not REGISTRY.exists(),
    reason="real mule-fuel-x-nana-glue tracker.json / registry.json not present",
)


def _tracker_json():
    return json.loads(TRACKER.read_text(encoding="utf-8"))


def _fingerprint_live_dir():
    """(path, size, mtime_ns) for every file under the live project dir.

    Cheap, total, and sensitive to any write: a migration that touched a
    dashboard file, a cache entry or a .git ref would show up here even
    though `tracker.json`'s md5 alone would not.
    """
    entries = {}
    for path in sorted(LIVE_DIR.rglob("*")):
        try:
            stat = path.lstat()
        except OSError:  # pragma: no cover - racing with nothing in practice
            continue
        entries[str(path.relative_to(LIVE_DIR))] = (stat.st_size, stat.st_mtime_ns)
    return entries


@pytest.fixture
def no_side_effects(monkeypatch):
    """Booby-trap every mechanism that could reach Discord, Drive or a git remote."""

    def boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError(
            f"the migration attempted a real side effect: {args!r} {kwargs!r}"
        )

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "call", boom)
    monkeypatch.setattr(subprocess, "check_call", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(os, "system", boom)
    return boom


@pytest.fixture
def migrated(tmp_path, no_side_effects):
    """Run the real migration into a throwaway sandbox, with guards armed."""
    out = tmp_path / "sandbox" / SLUG
    summary = migrate_tracker(
        TRACKER, REGISTRY, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
    )
    return summary, out


# ------------------------------------------------- (a) plant count match ----


@requires_real_data
def test_plant_count_matches_the_source_and_the_field_inventory(migrated):
    summary, out = migrated
    source_count = len(_tracker_json()["plants"])

    assert source_count == INVENTORY_PLANT_COUNT
    assert summary.plant_count == source_count
    assert len(list((out / "plants").glob("*.md"))) == source_count


@requires_real_data
def test_every_source_plant_id_has_exactly_one_markdown_file(migrated):
    _, out = migrated
    source_ids = sorted(p["id"] for p in _tracker_json()["plants"])
    written_ids = sorted(p.stem for p in (out / "plants").glob("*.md"))
    assert written_ids == source_ids


# ------------------------------------------------ (b) zero data loss ------


@requires_real_data
def test_full_verification_reports_zero_loss(migrated):
    _, out = migrated
    report = verify_migration(
        TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
    )
    assert report.ok, json.dumps(report.as_dict(), indent=2, default=str)[:4000]


@requires_real_data
def test_verification_catches_defaulted_routing_fields_on_real_data(migrated):
    """The real-data form of the round-5 blind spot.

    Rewrite the migrated project.md's routing fields to the template defaults
    -- what a migration that failed to consult registry.json would have
    produced -- and require the gate to reject it.
    """
    import re

    _, out = migrated
    pf = out / "project.md"
    original = pf.read_text(encoding="utf-8")
    try:
        broken = original.replace("auto_create: false", "auto_create: true")
        broken = re.sub(
            r"plant_id_prefixes:\n(?:- .*\n|  .*\n)+",
            "plant_id_prefixes: []\n",
            broken,
        )
        assert broken != original, "fixture did not actually change the file"
        pf.write_text(broken, encoding="utf-8")
        report = verify_migration(
            TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
        )
        assert not report.ok
        changed = {c["field"] for c in report.changed_fields.get("project", [])}
        assert "plant_id_prefixes" in changed
    finally:
        pf.write_text(original, encoding="utf-8")


@requires_real_data
def test_every_inventoried_plant_field_survives_on_every_plant(migrated):
    """Field-level diff against Task 3.0's inventory, not a hand-picked subset."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    problems = []
    for plant in _tracker_json()["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        for field, original in plant.items():
            if field not in got:
                problems.append(f"{plant['id']}.{field}: LOST")
            elif got[field] != original:
                problems.append(
                    f"{plant['id']}.{field}: {original!r} -> {got[field]!r}"
                )
    assert not problems, problems[:20]


@requires_real_data
def test_source_plant_keys_are_exactly_the_inventoried_set(migrated):
    """Guards against the tracker having drifted since Task 3.0 ran."""
    found = set()
    for plant in _tracker_json()["plants"]:
        found |= set(plant)
    assert found == INVENTORY_PLANT_KEYS


@requires_real_data
def test_source_project_keys_are_exactly_the_inventoried_set(migrated):
    assert set(_tracker_json()) == INVENTORY_PROJECT_KEYS


@requires_real_data
def test_every_project_field_survives(migrated):
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    for field, original in _tracker_json().items():
        if field == "plants":
            continue
        assert field in got, f"project field lost: {field}"
        assert got[field] == original, f"project field {field} changed"


@requires_real_data
def test_drive_folders_reports_subkeys_unique_to_this_project_survive(migrated):
    """Task 3.0 §4: `reports`/`reports_url` exist only on mule-fuel."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["drive_folders"] == _tracker_json()["drive_folders"]
    assert "reports" in got["drive_folders"]
    assert "reports_url" in got["drive_folders"]


@requires_real_data
def test_mg07_photo_extra_subkeys_and_missing_fields_are_handled(migrated):
    """Task 3.0 §7a/§9.3: MG07 carries `uploaded`/`context` and lacks
    `photo_count`/`photos_drive_url`."""
    from plant_markdown import load_schema, read_plant

    summary, out = migrated
    source = next(p for p in _tracker_json()["plants"] if p["id"] == "MG07")
    got = read_plant(out / "plants" / "MG07.md", schema=load_schema(PLANT_TEMPLATE))

    assert got["photos"] == source["photos"]
    assert set(got["photos"][0]) >= {"uploaded", "context"}
    # `corrected_reading` is absent from all 45 plants here (Task 3.0 §2b:
    # it exists on exactly one lantz plant), so it is defaulted on every
    # record; `photo_count`/`photos_drive_url` are defaulted on MG07 ALONE.
    assert set(summary.defaulted_fields["MG07"]) == {
        "corrected_reading",
        "photo_count",
        "photos_drive_url",
    }
    assert got["photo_count"] == 0
    assert got["photos_drive_url"] == ""
    assert got["corrected_reading"] is None


@requires_real_data
def test_only_mg07_needed_photo_count_and_drive_url_defaults(migrated):
    """Task 3.0 §9.3 says 94/95 plants have them — here, 44/45."""
    summary, _ = migrated
    needed = {
        plant_id
        for plant_id, fields in summary.defaulted_fields.items()
        if "photo_count" in fields or "photos_drive_url" in fields
    }
    assert needed == {"MG07"}


@requires_real_data
def test_corrected_reading_is_defaulted_on_every_plant_and_never_invented(migrated):
    """Task 3.0 §9.4: declared in the template, absent from this project's
    data — it must materialise as null, never as a fabricated value."""
    from plant_markdown import load_schema, read_plant

    summary, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    ids = [p["id"] for p in _tracker_json()["plants"]]
    for plant_id in ids:
        assert "corrected_reading" in summary.defaulted_fields[plant_id]
        got = read_plant(out / "plants" / f"{plant_id}.md", schema=schema)
        assert got["corrected_reading"] is None


@requires_real_data
def test_observation_logs_are_preserved_verbatim_as_the_body(migrated):
    _, out = migrated
    for plant in _tracker_json()["plants"]:
        text = (out / "plants" / f"{plant['id']}.md").read_text(
            encoding="utf-8", newline=""
        )
        frontmatter, body = text.split("\n---\n", 1)
        assert body == plant["observation_log"], plant["id"]
        assert "observation_log:" not in frontmatter


@requires_real_data
def test_registry_sourced_routing_fields_are_correct(migrated):
    """Task 3.0 §8 — the highest-risk item: these come from registry.json."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    entry = next(
        e
        for e in json.loads(REGISTRY.read_text(encoding="utf-8"))["projects"]
        if e["slug"] == SLUG
    )
    assert got["auto_create"] == entry["auto_create"]
    assert got["plant_id_prefixes"] == entry["plant_id_prefixes"]
    assert got["plant_id_prefixes"][0]["prefix"] == "MG"


@requires_real_data
def test_migrated_tree_is_byte_stable_across_a_rewrite(migrated):
    """A re-write of the canonical form must not churn a byte, or every
    later ingestion run produces noise commits."""
    from plant_markdown import load_schema as plant_schema_of
    from plant_markdown import read_plant, write_plant

    _, out = migrated
    schema = plant_schema_of(PLANT_TEMPLATE)
    for path in sorted((out / "plants").glob("*.md")):
        before = path.read_bytes()
        write_plant(path, read_plant(path, schema=schema), schema=schema)
        assert path.read_bytes() == before, path.name


# ----------------------- (c)/(d) sandbox-only, no real side effects -------


@requires_real_data
def test_tracker_json_md5_is_unchanged(migrated):
    summary, _ = migrated
    assert summary.tracker_md5_before == summary.tracker_md5_after
    assert file_md5(TRACKER) == summary.tracker_md5_before


@requires_real_data
def test_the_entire_live_project_directory_is_untouched(tmp_path, no_side_effects):
    """Stronger than the md5 check: nothing anywhere under the live dir moved."""
    before = _fingerprint_live_dir()
    migrate_tracker(
        TRACKER,
        REGISTRY,
        SLUG,
        tmp_path / "sandbox",
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
    )
    after = _fingerprint_live_dir()
    assert after == before


@requires_real_data
def test_registry_json_is_untouched(tmp_path, no_side_effects):
    before = file_md5(REGISTRY)
    migrate_tracker(
        TRACKER,
        REGISTRY,
        SLUG,
        tmp_path / "sandbox",
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
    )
    assert file_md5(REGISTRY) == before


@requires_real_data
def test_all_writes_land_inside_the_sandbox(tmp_path, no_side_effects):
    out = tmp_path / "sandbox"
    real_open = os.open
    written: list[str] = []

    def spy_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
            written.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    os.open = spy_open
    try:
        migrate_tracker(
            TRACKER, REGISTRY, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
    finally:
        os.open = real_open

    assert len(written) >= 46  # project.md + 45 plants (via temp files)
    outside = [
        p for p in written if not Path(p).resolve().is_relative_to(out.resolve())
    ]
    assert not outside, f"wrote outside the sandbox: {outside}"


@requires_real_data
def test_the_migration_refuses_to_write_into_the_live_project_dir(tmp_path):
    """The sandbox guard, exercised against the real path it must protect."""
    from tracker_migration import SandboxViolationError

    with pytest.raises(SandboxViolationError):
        migrate_tracker(
            TRACKER,
            REGISTRY,
            SLUG,
            LIVE_DIR / "markdown",
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
        )
    assert not (LIVE_DIR / "markdown").exists()
