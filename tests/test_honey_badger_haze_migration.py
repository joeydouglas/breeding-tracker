"""Task 3.2 — migrate the REAL honey-badger-haze-pheno-hunt tracker, sandbox-only.

Acceptance test for Phase 3's second project. Runs the actual migration
against the actual `/home/joey/.hermes/breeding/honey-badger-haze-pheno-hunt/
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

This project differs from Task 3.1's mule-fuel-x-nana-glue in ways that matter
to the migration, and each difference is asserted rather than assumed:

* `auto_create` is **true** here, while the project template's default is
  `false`. On mule-fuel the registry value and the template default were both
  `false`, so that project's "sourced from the registry" assertion could not
  actually distinguish a registry read from a silent template default. Here
  the two differ, so this is the first project whose data can *prove* Task
  3.0 §8's highest-risk finding was handled. See
  `test_auto_create_is_registry_true_and_not_the_template_default`.
* `notes_meta` is **present** (it was absent on mule-fuel, where it had to be
  materialised from the template default).
* Every plant carries all 18 inventoried keys — there is no MG07-style record
  missing `photo_count`/`photos_drive_url` — so `corrected_reading` must be
  the *only* defaulted plant field anywhere in this project.

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

SLUG = "honey-badger-haze-pheno-hunt"
LIVE_DIR = Path.home() / ".hermes" / "breeding" / SLUG
TRACKER = LIVE_DIR / "tracker.json"
REGISTRY = (
    Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
)

#: Task 3.0 field inventory, §1/§2, restricted to this project. Unlike
#: mule-fuel, this project HAS `breeder_lineage`, `genetics` and `notes_meta`.
INVENTORY_PROJECT_KEYS = {
    "breeder_lineage",
    "created",
    "cross_name",
    "drive_folders",
    "genetics",
    "github_pages_url",
    "github_repo",
    "google_sheet_id",
    "google_sheet_url",
    "last_updated",
    "notes_meta",
    "plants",
}
#: Task 3.0 §2b: 18 keys, i.e. the union minus `corrected_reading`.
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
INVENTORY_PLANT_COUNT = 23

requires_real_data = pytest.mark.skipif(
    not TRACKER.exists() or not REGISTRY.exists(),
    reason="real honey-badger-haze-pheno-hunt tracker.json / registry.json not present",
)


def _tracker_json():
    return json.loads(TRACKER.read_text(encoding="utf-8"))


def _registry_entry():
    return next(
        e
        for e in json.loads(REGISTRY.read_text(encoding="utf-8"))["projects"]
        if e["slug"] == SLUG
    )


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


@requires_real_data
def test_plant_ids_are_the_contiguous_hbh01_to_hbh23_run(migrated):
    """This project has no numbering gap (mule-fuel skips MG09); a migration
    that renumbered or dropped a record would show up as a changed run."""
    _, out = migrated
    expected = [f"HBH{n:02d}" for n in range(1, INVENTORY_PLANT_COUNT + 1)]
    assert sorted(p["id"] for p in _tracker_json()["plants"]) == expected
    assert sorted(p.stem for p in (out / "plants").glob("*.md")) == expected


# ------------------------------------------------ (b) zero data loss ------


@requires_real_data
def test_full_verification_reports_zero_loss(migrated):
    _, out = migrated
    report = verify_migration(
        TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
    )
    assert report.ok, json.dumps(report.as_dict(), indent=2, default=str)[:4000]


@requires_real_data
def test_verification_actually_compared_every_record_and_field(migrated):
    """`ok` is only evidence if the gate inspected the whole dataset.

    23 plants x 18 keys + 11 project keys + the 2 registry-sourced routing
    fields = 427 field values across 24 records.
    """
    _, out = migrated
    report = verify_migration(
        TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
    )
    source = _tracker_json()
    expected_fields = (
        sum(len(p) for p in source["plants"])
        + len([k for k in source if k != "plants"])
        + 2
    )
    assert report.records_compared == 1 + INVENTORY_PLANT_COUNT
    assert report.fields_compared == expected_fields == 427


@requires_real_data
def test_verification_of_a_never_migrated_dir_is_not_ok(tmp_path):
    """The gate must fail closed, not report a vacuous pass."""
    report = verify_migration(
        TRACKER, tmp_path / "nothing-here", PROJECT_TEMPLATE, PLANT_TEMPLATE,
        REGISTRY, SLUG,
    )
    assert not report.ok


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
def test_the_whole_plants_array_reconstructs_from_markdown(migrated):
    """Whole-object equality, not just per-field: catches ordering/shape drift."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    source_plants = _tracker_json()["plants"]
    rebuilt = []
    for plant in source_plants:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        rebuilt.append({k: got[k] for k in plant})
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(
        source_plants, sort_keys=True
    )


@requires_real_data
def test_source_plant_keys_are_exactly_the_inventoried_set(migrated):
    """Guards against the tracker having drifted since Task 3.0 ran."""
    found = set()
    for plant in _tracker_json()["plants"]:
        found |= set(plant)
    assert found == INVENTORY_PLANT_KEYS


@requires_real_data
def test_every_plant_carries_all_eighteen_keys(migrated):
    """Task 3.0 §2b: unlike mule-fuel's MG07, no record here is missing a key."""
    for plant in _tracker_json()["plants"]:
        assert set(plant) == INVENTORY_PLANT_KEYS, plant["id"]


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
def test_plants_array_is_not_duplicated_into_project_frontmatter(migrated):
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert "plants" not in got


@requires_real_data
def test_drive_folders_survive_whole_without_the_mule_fuel_reports_subkeys(migrated):
    """Task 3.0 §4: `reports`/`reports_url` are unique to mule-fuel. This
    project's 8-subkey shape must round-trip exactly, and the migration must
    not invent the sibling project's extra keys."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    source = _tracker_json()["drive_folders"]
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


@requires_real_data
def test_notes_meta_is_present_and_survives_verbatim(migrated):
    """Task 3.0 §6: absent on mule-fuel (defaulted there), present here — so it
    must be preserved, not overwritten with the template's `{}` default.

    Includes its `migration_note`, whose text is factually stale (it claims
    `plants[]` is empty while 23 plants exist). Migration preserves data
    verbatim; it is not the migration's job to correct or drop stale prose.
    """
    from project_markdown import load_schema, read_project

    summary, out = migrated
    source = _tracker_json()["notes_meta"]
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["notes_meta"] == source
    assert got["notes_meta"] != {}
    assert got["notes_meta"]["source_doc"] is None
    assert "migration_note" in got["notes_meta"]
    assert "notes_meta" not in summary.defaulted_fields.get("project", [])


@requires_real_data
def test_no_project_level_field_needed_a_template_default(migrated):
    """All 11 non-`plants` keys exist in this tracker, so unlike mule-fuel
    (which defaulted notes_meta/genetics/breeder_lineage) nothing here should
    be materialised at project level."""
    summary, _ = migrated
    assert summary.defaulted_fields.get("project") is None


@requires_real_data
def test_corrected_reading_is_the_only_defaulted_plant_field(migrated):
    """Task 3.0 §9.4 — declared in the template, absent from this project's
    data, so it materialises as null on every plant and must never be
    fabricated. And because every plant here has all 18 other keys, it must be
    the ONLY defaulted field on every record."""
    from plant_markdown import load_schema, read_plant

    summary, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    for plant in _tracker_json()["plants"]:
        plant_id = plant["id"]
        assert summary.defaulted_fields[plant_id] == ["corrected_reading"], plant_id
        got = read_plant(out / "plants" / f"{plant_id}.md", schema=schema)
        assert got["corrected_reading"] is None


@requires_real_data
def test_no_plant_needed_photo_count_or_drive_url_defaults(migrated):
    """Task 3.0 §9.3's MG07 hazard is mule-fuel-specific; it must not silently
    appear here (which would mean a record lost those fields)."""
    summary, _ = migrated
    needed = {
        plant_id
        for plant_id, fields in summary.defaulted_fields.items()
        if "photo_count" in fields or "photos_drive_url" in fields
    }
    assert needed == set()


@requires_real_data
def test_photos_and_photo_counts_survive_including_the_one_photoless_plant(migrated):
    """22 of 23 plants carry photos; `photos[]` passes through opaquely and the
    empty-list plant must stay an empty list, not become null."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    photoless = []
    for plant in _tracker_json()["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert got["photos"] == plant["photos"], plant["id"]
        assert got["photo_count"] == plant["photo_count"], plant["id"]
        if not plant["photos"]:
            photoless.append(plant["id"])
            assert got["photos"] == []
    assert len(photoless) == 1


@requires_real_data
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
    for plant in _tracker_json()["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        for field in always_null:
            assert plant[field] is None, f"source drifted: {plant['id']}.{field}"
            assert got[field] is None, f"{plant['id']}.{field}"
        assert got["terpene_notes"] is None
        assert got["selection_notes"] == plant["selection_notes"]
        if plant["selection_notes"] is not None:
            with_selection_notes.append(plant["id"])
    assert with_selection_notes == ["HBH15"]


@requires_real_data
def test_statuses_survive_across_all_three_values(migrated):
    """active/culled/keeper all appear here; a status lost or normalised would
    change downstream dashboards."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    seen = set()
    for plant in _tracker_json()["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert got["status"] == plant["status"], plant["id"]
        seen.add(got["status"])
    assert seen == {"active", "culled", "keeper"}


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
def test_original_notes_survive_verbatim(migrated):
    """`original_notes` is the raw Discord text and is frontmatter, not body;
    every plant here has a non-empty one."""
    from plant_markdown import load_schema, read_plant

    _, out = migrated
    schema = load_schema(PLANT_TEMPLATE)
    for plant in _tracker_json()["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        assert plant["original_notes"] != ""
        assert got["original_notes"] == plant["original_notes"], plant["id"]


# ------------------------- registry-sourced routing fields (Task 3.0 §8) ----


@requires_real_data
def test_registry_sourced_routing_fields_are_correct(migrated):
    """Task 3.0 §8 — the highest-risk item: these come from registry.json."""
    from project_markdown import load_schema, read_project

    _, out = migrated
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    entry = _registry_entry()
    assert got["auto_create"] == entry["auto_create"]
    assert got["plant_id_prefixes"] == entry["plant_id_prefixes"]
    assert got["plant_id_prefixes"][0]["prefix"] == "HBH"
    # The regex must survive intact — a mangled backslash silently breaks ID
    # routing for every future Discord note in this project.
    assert got["plant_id_prefixes"][0]["pattern"] == r"\bHBH[\s\-]?(\d{1,2})\b"


@requires_real_data
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
    entry = _registry_entry()

    assert template_default is False
    assert entry["auto_create"] is True
    assert entry["auto_create"] != template_default

    got = read_project(out / "project.md", schema=project_schema)
    assert got["auto_create"] is True
    # `auto_create` appears in no tracker.json, so it was not copied from there.
    assert "auto_create" not in _tracker_json()


@requires_real_data
def test_verification_rejects_routing_fields_reverted_to_template_defaults(migrated):
    """The real-data form of the round-5 blind spot: a project.md carrying the
    template defaults must be rejected, per field."""
    import re

    _, out = migrated
    project_md = out / "project.md"
    pristine = project_md.read_text(encoding="utf-8")
    tampers = {
        "auto_create": pristine.replace("auto_create: true", "auto_create: false"),
        "plant_id_prefixes": re.sub(
            r"plant_id_prefixes:\n(?:- .*\n|  .*\n)+",
            "plant_id_prefixes: []\n",
            pristine,
        ),
    }
    try:
        for field, broken in tampers.items():
            assert broken != pristine, f"tamper fixture did not change {field}"
            project_md.write_text(broken, encoding="utf-8")
            report = verify_migration(
                TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
            )
            assert not report.ok, field
            changed = {c["field"] for c in report.changed_fields.get("project", [])}
            assert field in changed, field
    finally:
        project_md.write_text(pristine, encoding="utf-8")

    assert verify_migration(
        TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
    ).ok


@requires_real_data
def test_migration_aborts_when_the_registry_entry_is_missing(tmp_path, no_side_effects):
    """Rather than silently taking `auto_create: false` / `plant_id_prefixes: []`."""
    from tracker_migration import TrackerMigrationError

    stripped = json.loads(REGISTRY.read_text(encoding="utf-8"))
    stripped["projects"] = [e for e in stripped["projects"] if e["slug"] != SLUG]
    fake_registry = tmp_path / "registry.json"
    fake_registry.write_text(json.dumps(stripped), encoding="utf-8")

    out = tmp_path / "sandbox"
    with pytest.raises(TrackerMigrationError):
        migrate_tracker(
            TRACKER, fake_registry, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
    assert not out.exists()


# ---------------------------------------------------------- byte stability --


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


@requires_real_data
def test_migration_is_deterministic_across_two_runs(tmp_path, no_side_effects):
    """Two migrations of the same source must be byte-identical, or the Phase 5
    cutover would produce a spurious diff against this sandbox proof."""
    first = tmp_path / "one"
    second = tmp_path / "two"
    migrate_tracker(TRACKER, REGISTRY, SLUG, first, PROJECT_TEMPLATE, PLANT_TEMPLATE)
    migrate_tracker(TRACKER, REGISTRY, SLUG, second, PROJECT_TEMPLATE, PLANT_TEMPLATE)

    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
    for rel in files:
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), str(rel)


# ----------------------- (c)/(d) sandbox-only, no real side effects -------


@requires_real_data
def test_tracker_json_md5_is_unchanged(migrated):
    summary, _ = migrated
    assert summary.tracker_md5_before == summary.tracker_md5_after
    assert file_md5(TRACKER) == summary.tracker_md5_before
    assert summary.tracker_unchanged


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
    assert before, "fingerprint was empty -- the check would be vacuous"


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
def test_the_other_five_projects_are_untouched(tmp_path, no_side_effects):
    """Task 3.x migrates ONE project; the sibling live dirs must not move."""
    breeding = Path.home() / ".hermes" / "breeding"
    others = [
        d
        for d in sorted(breeding.iterdir())
        if d.is_dir() and d.name != SLUG and (d / "tracker.json").exists()
    ]
    assert len(others) == 5

    def fingerprint():
        return {
            str(p): (p.lstat().st_size, p.lstat().st_mtime_ns)
            for d in others
            for p in sorted(d.rglob("*"))
        }

    before = fingerprint()
    migrate_tracker(
        TRACKER, REGISTRY, SLUG, tmp_path / "sandbox", PROJECT_TEMPLATE, PLANT_TEMPLATE
    )
    assert fingerprint() == before


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

    assert len(written) >= 24  # project.md + 23 plants (via temp files)
    outside = [
        p for p in written if not Path(p).resolve().is_relative_to(out.resolve())
    ]
    assert not outside, f"wrote outside the sandbox: {outside}"


@requires_real_data
def test_the_migration_module_cannot_reach_the_network_or_a_shell():
    """Static proof, independent of whether any given run happens to try."""
    source = (REPO / "src" / "tracker_migration.py").read_text(encoding="utf-8")
    for forbidden in (
        "import subprocess",
        "import socket",
        "import urllib",
        "import http",
        "import requests",
        "import smtplib",
        "os.system",
        "os.popen",
    ):
        assert forbidden not in source, forbidden


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


@requires_real_data
def test_the_live_dir_guard_beats_the_git_opt_in(tmp_path):
    """`allow_git_repo=True` must never become a blanket write-into-live-data
    switch, even for the eventual deliberate real run."""
    from tracker_migration import SandboxViolationError

    with pytest.raises(SandboxViolationError):
        migrate_tracker(
            TRACKER,
            REGISTRY,
            SLUG,
            LIVE_DIR / "markdown",
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
            allow_git_repo=True,
        )
    assert not (LIVE_DIR / "markdown").exists()
