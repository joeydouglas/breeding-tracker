"""Task 3.x — unit tests for the tracker.json -> markdown migration.

Synthetic fixtures only; the real-data proof lives in
``test_mule_fuel_migration.py``.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from breeding_tracker import tracker_migration as tm
from breeding_tracker.tracker_migration import (
    MigrationSummary,
    SandboxViolationError,
    TrackerMigrationError,
    assert_sandbox_destination,
    build_plant_record,
    build_project_record,
    file_md5,
    load_registry_entry,
    migrate_tracker,
    verify_migration,
)

REPO = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATE = REPO / "breeding_tracker" / "templates" / "project-template.md"
PLANT_TEMPLATE = REPO / "breeding_tracker" / "templates" / "plant-template.md"
SLUG = "test-cross"


# ------------------------------------------------------------- fixtures ----


def _tracker(**overrides):
    data = {
        "cross_name": "Test Cross",
        "created": "2026-01-01T00:00:00",
        "last_updated": "2026-01-02T00:00:00",
        "github_repo": "joeydouglas/test",
        "github_pages_url": "https://example.invalid/pages",
        "google_sheet_id": None,
        "google_sheet_url": None,
        "drive_folders": {"root": "abc", "root_url": "https://example.invalid/abc"},
        "plants": [
            {
                "id": "TT01",
                "cross": "Test Cross",
                "status": "keeper",
                "sex": None,
                "photos": [],
                "photo_count": 0,
                "photos_drive_url": "",
                "original_notes": "hello",
                "observation_log": "### note\nbody text\n",
            }
        ],
    }
    data.update(overrides)
    return data


def _registry(**overrides):
    entry = {
        "slug": "test-cross",
        "cross_name": "Test Cross",
        "breeding_dir": "~/.hermes/breeding/test-cross",
        "github_repo": "joeydouglas/test",
        "auto_create": True,
        "plant_id_prefixes": [{"prefix": "TT", "pattern": r"\bTT(\d{1,2})\b"}],
    }
    entry.update(overrides)
    return {"schema_version": 1, "projects": [entry]}


@pytest.fixture
def inputs(tmp_path):
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(_tracker(), indent=2), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry(), indent=2), encoding="utf-8")
    return tracker_path, registry_path


def _run(tracker_path, registry_path, out, slug="test-cross"):
    return migrate_tracker(
        tracker_path,
        registry_path,
        slug,
        out,
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
    )


# ------------------------------------------------------------- happy path ----


def test_migration_writes_project_and_one_file_per_plant(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox" / "test-cross"

    summary = _run(tracker_path, registry_path, out)

    assert isinstance(summary, MigrationSummary)
    assert (out / "project.md").is_file()
    assert (out / "plants" / "TT01.md").is_file()
    assert summary.plant_count == 1
    assert summary.tracker_unchanged


def test_round_trip_has_zero_data_loss(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox" / "test-cross"
    _run(tracker_path, registry_path, out)

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert report.ok, report.as_dict()
    assert report.plant_count_source == report.plant_count_migrated == 1


def test_observation_log_becomes_the_markdown_body_not_frontmatter(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox" / "test-cross"
    _run(tracker_path, registry_path, out)

    text = (out / "plants" / "TT01.md").read_text(encoding="utf-8")
    _, _, body = text.split("---\n", 2)
    assert "observation_log:" not in text.split("---\n")[1]
    assert body == "### note\nbody text\n"


def test_plants_key_is_not_written_into_project_frontmatter(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox" / "test-cross"
    _run(tracker_path, registry_path, out)

    from breeding_tracker.project_markdown import load_schema, read_project

    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert "plants" not in got


# --------------------------------------------- registry-sourced fields ----


def test_auto_create_and_prefixes_come_from_the_registry_not_the_template(
    inputs, tmp_path
):
    """Task 3.0 §8: the single highest-risk item in the whole migration."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox" / "test-cross"
    _run(tracker_path, registry_path, out)

    from breeding_tracker.project_markdown import load_schema, read_project

    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["auto_create"] is True  # template default is False
    assert got["plant_id_prefixes"] == [
        {"prefix": "TT", "pattern": r"\bTT(\d{1,2})\b"}
    ]


def test_registry_overrides_a_conflicting_tracker_value(tmp_path):
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(
        json.dumps(_tracker(auto_create=False, plant_id_prefixes=["WRONG"])),
        encoding="utf-8",
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"

    _run(tracker_path, registry_path, out)

    from breeding_tracker.project_markdown import load_schema, read_project

    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert got["auto_create"] is True
    assert got["plant_id_prefixes"][0]["prefix"] == "TT"


def test_missing_registry_entry_aborts_instead_of_defaulting(inputs, tmp_path):
    tracker_path, registry_path = inputs
    with pytest.raises(TrackerMigrationError, match="no registry entry"):
        _run(tracker_path, registry_path, tmp_path / "sandbox", slug="nope")


def test_registry_entry_missing_auto_create_aborts(tmp_path):
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(_tracker()), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    entry = _registry()["projects"][0]
    del entry["auto_create"]
    registry_path.write_text(
        json.dumps({"projects": [entry]}), encoding="utf-8"
    )

    with pytest.raises(TrackerMigrationError, match="auto_create"):
        _run(tracker_path, registry_path, tmp_path / "sandbox")


def test_registry_without_projects_list_aborts(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(TrackerMigrationError, match="no 'projects' list"):
        load_registry_entry(registry_path, "test-cross")


def test_plant_id_prefixes_are_deep_copied_from_the_registry(tmp_path):
    """Mutating the migrated record must never corrupt the registry dict."""
    registry = _registry()
    entry = registry["projects"][0]
    schema = __import__(
        "breeding_tracker.project_markdown", fromlist=["load_schema"]
    ).load_schema(PROJECT_TEMPLATE)
    record, _ = build_project_record(_tracker(), entry, schema)
    record["plant_id_prefixes"][0]["prefix"] = "MUTATED"
    assert entry["plant_id_prefixes"][0]["prefix"] == "TT"


# ---------------------------------------------- template-default filling ----


def test_plant_missing_fields_get_template_defaults_and_are_reported(tmp_path):
    """Task 3.0 §9.3 — MG07 lacks photo_count/photos_drive_url."""
    tracker = _tracker()
    del tracker["plants"][0]["photo_count"]
    del tracker["plants"][0]["photos_drive_url"]
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"

    summary = _run(tracker_path, registry_path, out)

    assert set(summary.defaulted_fields["TT01"]) >= {
        "photo_count",
        "photos_drive_url",
    }
    from breeding_tracker.plant_markdown import load_schema, read_plant

    got = read_plant(out / "plants" / "TT01.md", schema=load_schema(PLANT_TEMPLATE))
    assert got["photo_count"] == 0
    assert got["photos_drive_url"] == ""


def test_defaulted_fields_are_not_reported_as_data_loss(tmp_path):
    tracker = _tracker()
    del tracker["plants"][0]["photo_count"]
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    assert verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    ).ok


def test_project_missing_notes_meta_gets_the_template_default(inputs, tmp_path):
    """Task 3.0 §9.6 — notes_meta is absent on mule-fuel-x-nana-glue."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    summary = _run(tracker_path, registry_path, out)
    assert "notes_meta" in summary.defaulted_fields["project"]


def test_defaulted_mutable_defaults_do_not_alias_across_plants(tmp_path):
    tracker = _tracker()
    tracker["plants"] = [
        {"id": "TT01", "cross": "Test Cross", "observation_log": ""},
        {"id": "TT02", "cross": "Test Cross", "observation_log": ""},
    ]
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    from breeding_tracker.plant_markdown import load_schema, read_plant

    schema = load_schema(PLANT_TEMPLATE)
    one = read_plant(out / "plants" / "TT01.md", schema=schema)
    one["photos"].append("x")
    two = read_plant(out / "plants" / "TT02.md", schema=schema)
    assert two["photos"] == []


# ----------------------------------------------------- malformed inputs ----


def test_duplicate_plant_ids_abort_before_any_file_is_written(tmp_path):
    tracker = _tracker()
    tracker["plants"].append(dict(tracker["plants"][0]))
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"

    with pytest.raises(TrackerMigrationError, match="duplicate plant id"):
        _run(tracker_path, registry_path, out)
    assert not out.exists()


def test_plant_without_an_id_aborts_before_any_file_is_written(tmp_path):
    tracker = _tracker()
    tracker["plants"][0].pop("id")
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"

    with pytest.raises(TrackerMigrationError, match="no usable 'id'"):
        _run(tracker_path, registry_path, out)
    assert not out.exists()


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "..", "sub\\dir"])
def test_plant_id_that_would_escape_the_plants_dir_is_rejected(tmp_path, bad_id):
    tracker = _tracker()
    tracker["plants"][0]["id"] = bad_id
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")

    with pytest.raises(TrackerMigrationError, match="unsafe as a filename"):
        _run(tracker_path, registry_path, tmp_path / "sandbox")


def test_plants_as_a_dict_is_accepted(tmp_path):
    tracker = _tracker()
    tracker["plants"] = {"TT01": tracker["plants"][0]}
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
    out = tmp_path / "sandbox"

    assert _run(tracker_path, registry_path, out).plant_count == 1


def test_plants_of_the_wrong_type_aborts(tmp_path):
    tracker = _tracker(plants="not a list")
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")

    with pytest.raises(TrackerMigrationError, match="must be an array"):
        _run(tracker_path, registry_path, tmp_path / "sandbox")


def test_tracker_that_is_not_an_object_aborts(tmp_path):
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text("[1, 2, 3]", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")

    with pytest.raises(TrackerMigrationError, match="JSON object"):
        _run(tracker_path, registry_path, tmp_path / "sandbox")


# ------------------------------------------------------- sandbox guards ----


def test_non_empty_destination_is_refused(tmp_path):
    out = tmp_path / "sandbox"
    out.mkdir()
    (out / "leftover.md").write_text("x", encoding="utf-8")
    with pytest.raises(SandboxViolationError, match="not empty"):
        assert_sandbox_destination(out)


def test_empty_existing_destination_is_allowed(tmp_path):
    out = tmp_path / "sandbox"
    out.mkdir()
    assert assert_sandbox_destination(out) == out.resolve()


def test_destination_that_is_a_file_is_refused(tmp_path):
    out = tmp_path / "afile"
    out.write_text("x", encoding="utf-8")
    with pytest.raises(SandboxViolationError, match="not a directory"):
        assert_sandbox_destination(out)


def test_destination_inside_a_git_work_tree_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(SandboxViolationError, match="git work tree"):
        assert_sandbox_destination(repo / "nested" / "out")


def test_destination_inside_a_git_work_tree_is_allowed_when_opted_in(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    out = repo / "nested" / "out"
    assert assert_sandbox_destination(out, allow_git_repo=True) == out.resolve()


def test_destination_inside_the_live_breeding_tree_is_refused(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    (fake_home / ".hermes" / "breeding" / "some-project").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    with pytest.raises(SandboxViolationError, match="live breeding data tree"):
        assert_sandbox_destination(
            fake_home / ".hermes" / "breeding" / "some-project" / "md"
        )


def test_live_breeding_tree_guard_beats_the_git_opt_in(monkeypatch, tmp_path):
    """allow_git_repo must not become a blanket 'write into live data' switch."""
    fake_home = tmp_path / "home"
    live = fake_home / ".hermes" / "breeding" / "some-project"
    live.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    with pytest.raises(SandboxViolationError, match="live breeding data tree"):
        assert_sandbox_destination(live / "md", allow_git_repo=True)


def test_migrate_refuses_a_git_destination_before_writing_anything(inputs, tmp_path):
    tracker_path, registry_path = inputs
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    out = repo / "out"

    with pytest.raises(SandboxViolationError):
        _run(tracker_path, registry_path, out)
    assert not out.exists()


# --------------------------------------------------- verification checks ----


def test_verify_detects_a_deleted_plant_file(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    (out / "plants" / "TT01.md").unlink()

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert not report.ok
    assert report.missing_records == ["TT01"]
    assert not report.plant_count_matches


def test_verify_detects_a_missing_project_file(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    (out / "project.md").unlink()

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert not report.ok
    assert "project" in report.missing_records


def test_verify_detects_a_tampered_field_value(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    plant_file = out / "plants" / "TT01.md"
    plant_file.write_text(
        plant_file.read_text(encoding="utf-8").replace("keeper", "culled"),
        encoding="utf-8",
    )

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert not report.ok
    assert report.changed_fields["TT01"][0]["field"] == "status"


def test_verify_detects_an_extra_unexpected_plant_file(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    (out / "plants" / "TT99.md").write_text("---\nid: TT99\n---\n", encoding="utf-8")

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert not report.ok
    assert report.extra_records == ["TT99"]


def test_verify_reports_an_ok_dict_shape(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    data = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    ).as_dict()
    assert data["ok"] is True
    assert set(data) == {
        "ok",
        "verified_something",
        "records_compared",
        "fields_compared",
        "plant_count_source",
        "plant_count_migrated",
        "plant_count_matches",
        "missing_records",
        "extra_records",
        "lost_fields",
        "changed_fields",
    }


# ------------------------------------------------------------ md5 helper ----


def test_file_md5_matches_the_system_md5sum(inputs):
    tracker_path, _ = inputs
    out = subprocess.run(
        ["md5sum", str(tracker_path)], capture_output=True, text=True, check=True
    )
    assert file_md5(tracker_path) == out.stdout.split()[0]


def test_migration_does_not_modify_the_source_tracker(inputs, tmp_path):
    tracker_path, registry_path = inputs
    before = file_md5(tracker_path)
    before_mtime = os.stat(tracker_path).st_mtime_ns
    summary = _run(tracker_path, registry_path, tmp_path / "sandbox")
    assert summary.tracker_md5_before == before
    assert summary.tracker_md5_after == before
    assert os.stat(tracker_path).st_mtime_ns == before_mtime


# ------------------------------------------------- side-effect isolation ----


def test_module_imports_no_side_effect_capable_library():
    """Static proof: nothing in this module can push, POST or message anyone."""
    source = (REPO / "breeding_tracker" / "tracker_migration.py").read_text(encoding="utf-8")
    forbidden = (
        "import subprocess",
        "import socket",
        "import requests",
        "import urllib",
        "import http",
        "import smtplib",
        "import ftplib",
        "from subprocess",
        "from socket",
        "from urllib",
        "os.system",
        "os.popen",
    )
    hits = [token for token in forbidden if token in source]
    assert not hits, f"tracker_migration.py must stay side-effect free: {hits}"


def test_migration_runs_with_subprocess_and_network_disabled(
    inputs, tmp_path, monkeypatch
):
    """Runtime proof: it completes with every escape hatch booby-trapped."""
    import socket
    import urllib.request

    def boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("migration attempted a real side effect")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(os, "system", boom)

    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    summary = _run(tracker_path, registry_path, out)
    assert summary.plant_count == 1
    assert verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    ).ok


def test_migration_writes_nothing_outside_the_output_dir(inputs, tmp_path):
    """Every path opened for writing must be under the sandbox."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"

    real_open = os.open
    written: list[str] = []

    def spy_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
            written.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    os.open = spy_open
    try:
        _run(tracker_path, registry_path, out)
    finally:
        os.open = real_open

    assert written, "expected the migration to write something"
    outside = [p for p in written if not Path(p).resolve().is_relative_to(out.resolve())]
    assert not outside, f"wrote outside the sandbox: {outside}"


# ------------------------------------- verification carries its evidence ----
#
# Code-quality round 4, Important #1: `report.ok` was a *blind* gate. It was
# True whenever no discrepancy had been recorded, which is also what an
# inspection that compared nothing at all looks like. A verifier that
# silently degrades to a no-op and still returns ok=True is the one failure
# mode a migration gate must not have, so the report now carries the count of
# what it actually compared and refuses to pass vacuously.


def _write_inputs(tmp_path, tracker, registry=None):
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(json.dumps(tracker), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(registry if registry is not None else _registry()), encoding="utf-8"
    )
    return tracker_path, registry_path


def test_verification_reports_how_many_records_and_fields_it_compared(
    inputs, tmp_path
):
    """The gate must prove it did the work, not merely find no problem."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert report.ok, report.as_dict()
    # 1 project record + 1 plant record.
    assert report.records_compared == 2
    # 8 project tracker fields (9 keys minus 'plants') + 2 registry-sourced
    # routing fields + 9 plant fields.
    assert report.fields_compared == 19


def test_verification_that_compared_nothing_is_not_ok(tmp_path):
    """A vacuous pass must be reported as a failure, not as success.

    An empty tracker is no longer vacuous on its own: the two registry-sourced
    routing fields are always compared, which is the point of the fix. The
    genuinely blind case is a tree with nothing to re-read at all.
    """
    tracker_path, registry_path = _write_inputs(tmp_path, {"plants": []})
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    (out / "project.md").unlink()

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert report.fields_compared == 0
    assert not report.ok, "a verification that compared no field value is blind"
    assert not report.verified_something


def test_an_empty_tracker_still_verifies_the_registry_routing_fields(tmp_path):
    """Even with zero plants, auto_create/plant_id_prefixes are checked."""
    tracker_path, registry_path = _write_inputs(tmp_path, {"plants": []})
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert report.fields_compared == 2
    assert report.ok, report.as_dict()


def test_verification_of_an_unwritten_tree_is_not_silently_ok(inputs, tmp_path):
    """Pointing the gate at a directory no migration wrote must fail loudly."""
    tracker_path, registry_path = inputs
    empty = tmp_path / "never-migrated"
    empty.mkdir()

    report = verify_migration(
        tracker_path, empty, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert not report.ok
    assert report.fields_compared == 0
    assert "project" in report.missing_records


def test_verification_counts_appear_in_the_report_dict(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    data = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    ).as_dict()
    assert data["records_compared"] == 2
    assert data["fields_compared"] == 19


# ---------------------------------------- rollback on a mid-write failure ----
#
# Code-quality round 4, Important #2: all *validation* ran before the first
# byte, but the write loop itself had no guard. A failure partway through
# (ENOSPC, a permission change, a writer bug on record N of M) left a
# half-written tree on disk that looks exactly like a complete migration to
# anything that later inspects the directory.


def _multi_plant_tracker():
    tracker = _tracker()
    tracker["plants"] = [
        {"id": f"TT0{n}", "cross": "Test Cross", "observation_log": f"note {n}\n"}
        for n in (1, 2, 3)
    ]
    return tracker


def test_a_failed_plant_write_leaves_no_half_written_tree(tmp_path, monkeypatch):
    from breeding_tracker import plant_markdown

    tracker_path, registry_path = _write_inputs(tmp_path, _multi_plant_tracker())
    out = tmp_path / "sandbox"

    real_write_plant = plant_markdown.write_plant
    calls = {"n": 0}

    def failing_write_plant(path, record, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_write_plant(path, record, **kwargs)

    monkeypatch.setattr(plant_markdown, "write_plant", failing_write_plant)

    with pytest.raises(OSError, match="disk full"):
        _run(tracker_path, registry_path, out)

    assert not out.exists(), (
        f"a failed migration must not leave a tree behind: "
        f"{sorted(p.name for p in out.rglob('*'))}"
    )


def test_a_failed_project_write_leaves_no_half_written_tree(tmp_path, monkeypatch):
    from breeding_tracker import project_markdown

    tracker_path, registry_path = _write_inputs(tmp_path, _multi_plant_tracker())
    out = tmp_path / "sandbox"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(project_markdown, "write_project", boom)

    with pytest.raises(OSError, match="disk full"):
        _run(tracker_path, registry_path, out)

    assert not out.exists()


def test_rollback_keeps_a_preexisting_empty_destination_directory(
    tmp_path, monkeypatch
):
    """Roll back only what this run created; don't delete the caller's dir."""
    from breeding_tracker import plant_markdown

    tracker_path, registry_path = _write_inputs(tmp_path, _multi_plant_tracker())
    out = tmp_path / "sandbox"
    out.mkdir()  # caller pre-created it (empty, so the sandbox guard allows it)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(plant_markdown, "write_plant", boom)

    with pytest.raises(OSError, match="disk full"):
        _run(tracker_path, registry_path, out)

    assert out.is_dir(), "a pre-existing destination must survive the rollback"
    assert not any(out.iterdir()), "but it must be left empty, not half-written"


def test_rollback_does_not_mask_the_original_failure(tmp_path, monkeypatch):
    """A rollback that itself fails must not replace the real exception."""
    from breeding_tracker import plant_markdown

    tracker_path, registry_path = _write_inputs(tmp_path, _multi_plant_tracker())
    out = tmp_path / "sandbox"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(plant_markdown, "write_plant", boom)

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        raise PermissionError("cannot remove")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(OSError, match="disk full"):
        _run(tracker_path, registry_path, out)

    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_successful_migration_is_untouched_by_the_rollback_guard(inputs, tmp_path):
    """The guard must be inert on the happy path."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    summary = _run(tracker_path, registry_path, out)
    assert summary.plant_count == 1
    assert (out / "project.md").is_file()
    assert (out / "plants" / "TT01.md").is_file()


# ------------------------- verification of registry-sourced routing fields ----
#
# Code-quality round 5: `verify_migration` diffed the migrated project.md
# against `tracker.json` alone. But `auto_create` and `plant_id_prefixes` do
# not exist in any tracker (Task 3.0 §8) -- they are read from `registry.json`
# by `build_project_record`. Fields absent from the source are treated as
# additions, not loss, so the two fields whose whole reason for existing is
# that they can't be sourced from the tracker were the two fields the
# zero-data-loss gate never looked at. A project.md carrying the template
# defaults (false / []) -- which silently breaks ID routing and auto-create in
# production, the exact failure `build_project_record` raises to prevent --
# passed verification with ok=True.


def test_verify_detects_a_tampered_auto_create(inputs, tmp_path):
    """The reviewer's repro: flip auto_create in project.md; gate must fail."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    pf = out / "project.md"
    pf.write_text(
        pf.read_text(encoding="utf-8").replace(
            "auto_create: true", "auto_create: false"
        ),
        encoding="utf-8",
    )

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert not report.ok, "auto_create was flipped but verification passed"
    changed = {c["field"] for c in report.changed_fields["project"]}
    assert "auto_create" in changed


def test_verify_detects_tampered_plant_id_prefixes(inputs, tmp_path):
    """Blanking the routing prefixes to the template default must fail."""
    import re

    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    pf = out / "project.md"
    pf.write_text(
        re.sub(
            r"plant_id_prefixes:\n(?:- .*\n|  .*\n)+",
            "plant_id_prefixes: []\n",
            pf.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert not report.ok, "plant_id_prefixes was blanked but verification passed"
    changed = {c["field"] for c in report.changed_fields["project"]}
    assert "plant_id_prefixes" in changed


def test_verify_detects_a_dropped_routing_field(inputs, tmp_path):
    """A routing field missing from project.md entirely is loss, not silence."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)
    pf = out / "project.md"
    pf.write_text(
        "".join(
            line
            for line in pf.read_text(encoding="utf-8").splitlines(keepends=True)
            if not line.startswith("auto_create:")
        ),
        encoding="utf-8",
    )

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    assert not report.ok
    assert "auto_create" in report.lost_fields.get(
        "project", []
    ) or "auto_create" in {c["field"] for c in report.changed_fields.get("project", [])}


def test_verify_compares_routing_fields_against_registry_not_tracker(tmp_path):
    """A tracker key of the same name must not be able to satisfy the gate.

    The registry is the routing source of truth on the way in, so it must be
    the source of truth on the way back out. A tracker that happens to carry a
    stale `auto_create` must not let a migrated file matching *that* value pass.
    """
    tracker = _tracker()
    tracker["auto_create"] = False  # stale/wrong value living in the tracker
    tracker_path, registry_path = _write_inputs(tmp_path, tracker)  # registry: True
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    report = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )

    # The migration wrote the registry value (True); verifying against the
    # tracker's False would report a bogus discrepancy.
    assert report.ok, report.as_dict()

    pf = out / "project.md"
    pf.write_text(
        pf.read_text(encoding="utf-8").replace(
            "auto_create: true", "auto_create: false"
        ),
        encoding="utf-8",
    )
    tampered = verify_migration(
        tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
    )
    assert not tampered.ok, (
        "matching the tracker's stale value must not satisfy the gate"
    )


def test_verify_requires_the_registry(inputs, tmp_path):
    """The registry is not optional; omitting it must be a TypeError, not a pass."""
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    with pytest.raises(TypeError):
        verify_migration(tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE)


def test_verify_aborts_when_the_registry_has_no_entry_for_the_slug(inputs, tmp_path):
    tracker_path, registry_path = inputs
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    with pytest.raises(TrackerMigrationError, match="no registry entry"):
        verify_migration(
            tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, "nope"
        )


def test_verify_aborts_when_the_registry_entry_lacks_a_routing_field(tmp_path):
    """Never fall back to a template default while *verifying*, either."""
    tracker_path, registry_path = _write_inputs(tmp_path, _tracker())
    out = tmp_path / "sandbox"
    _run(tracker_path, registry_path, out)

    registry = _registry()
    del registry["projects"][0]["auto_create"]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(TrackerMigrationError, match="auto_create"):
        verify_migration(
            tracker_path, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry_path, SLUG
        )
