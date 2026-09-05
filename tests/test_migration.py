"""RED-phase tests for migration.py (Task 1.3).

Covers the plan's acceptance criteria:
  (a) missing field added with template default
  (b) existing real value never overwritten
  (c) idempotent (same input twice = same output)
  (d) field in target but not template is left alone
  (e) one repo made deliberately unreachable in a test - migration completes
      for the others and the report clearly identifies the failure,
      re-running only retries the failed repo
  (f) running with no actual schema changes (already-current repos) makes
      zero commits
"""

import subprocess
from pathlib import Path

import pytest

from migration import (
    MigrationReport,
    MigrationResult,
    apply_new_fields,
    run_migration_across_repos,
)

PLANT_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "plant-template.md"
)
PROJECT_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "project-template.md"
)


def _git(args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo_with_remote(tmp_path, name, project_frontmatter, plant_files=()):
    """Create a bare 'remote' repo plus a local clone with an initial commit.

    ``project_frontmatter`` is the raw YAML frontmatter body (no delimiters)
    for project.md. ``plant_files`` is a list of (filename, frontmatter) for
    plants/<filename>.
    """
    remote = tmp_path / f"{name}-remote.git"
    remote.mkdir()
    _git(["init", "--bare", "-q"], remote)

    local = tmp_path / f"{name}-local"
    local.mkdir()
    _git(["init", "-q"], local)
    _git(["config", "user.email", "test@example.com"], local)
    _git(["config", "user.name", "Test"], local)
    _git(["remote", "add", "origin", str(remote)], local)

    (local / "project.md").write_text(
        f"---\n{project_frontmatter}---\n", encoding="utf-8"
    )
    if plant_files:
        (local / "plants").mkdir()
        for filename, fm in plant_files:
            (local / "plants" / filename).write_text(
                f"---\n{fm}---\n", encoding="utf-8"
            )

    _git(["add", "-A"], local)
    _git(["commit", "-q", "-m", "initial"], local)
    _git(["push", "-q", "origin", "HEAD:refs/heads/main"], local)
    _git(["branch", "-M", "main"], local)
    return local, remote


def _remote_head_sha(remote):
    result = subprocess.run(
        ["git", "rev-parse", "refs/heads/main"],
        cwd=str(remote),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _clone_and_read(remote, dest):
    _git(["clone", "-q", "--branch", "main", str(remote), str(dest)], dest.parent)
    return (dest / "project.md").read_text(encoding="utf-8")


# ------------------------------------------------------- apply_new_fields --


class TestApplyNewFields:
    def test_missing_field_added_with_template_default(self, tmp_path):
        p = tmp_path / "X1.md"
        p.write_text("---\nid: X1\n---\n", encoding="utf-8")
        result = apply_new_fields(PLANT_TEMPLATE, p)
        assert isinstance(result, MigrationResult)
        assert "photo_count" in result.added_fields
        assert result.changed is True
        text = p.read_text(encoding="utf-8")
        assert "photo_count: 0" in text

    def test_existing_real_value_never_overwritten(self, tmp_path):
        p = tmp_path / "X1.md"
        p.write_text("---\nid: X1\nvigor: 7\n---\n", encoding="utf-8")
        apply_new_fields(PLANT_TEMPLATE, p)
        text = p.read_text(encoding="utf-8")
        assert "vigor: '7'" in text

    def test_idempotent_same_input_twice_same_output(self, tmp_path):
        p = tmp_path / "X1.md"
        p.write_text("---\nid: X1\n---\n", encoding="utf-8")
        apply_new_fields(PLANT_TEMPLATE, p)
        first = p.read_bytes()
        second_result = apply_new_fields(PLANT_TEMPLATE, p)
        assert second_result.changed is False
        assert second_result.added_fields == []
        assert p.read_bytes() == first

    def test_field_in_target_but_not_template_is_left_alone(self, tmp_path):
        p = tmp_path / "X1.md"
        p.write_text(
            "---\nid: X1\nfuture_field: keep me\n---\n", encoding="utf-8"
        )
        apply_new_fields(PLANT_TEMPLATE, p)
        text = p.read_text(encoding="utf-8")
        assert "future_field: keep me" in text

    def test_running_with_no_schema_changes_makes_no_write(self, tmp_path):
        p = tmp_path / "X1.md"
        p.write_text("---\nid: X1\n---\n", encoding="utf-8")
        apply_new_fields(PLANT_TEMPLATE, p)
        before_mtime = p.stat().st_mtime_ns
        result = apply_new_fields(PLANT_TEMPLATE, p)
        assert result.changed is False
        assert p.stat().st_mtime_ns == before_mtime

    def test_project_file_detected_by_filename(self, tmp_path):
        p = tmp_path / "project.md"
        p.write_text("---\ncross_name: Lantz\n---\n", encoding="utf-8")
        result = apply_new_fields(PROJECT_TEMPLATE, p)
        assert "auto_create" in result.added_fields
        text = p.read_text(encoding="utf-8")
        assert "auto_create: false" in text

    def test_plant_body_observation_log_is_preserved_not_overwritten(
        self, tmp_path
    ):
        p = tmp_path / "X1.md"
        p.write_text("---\nid: X1\n---\n### Day 1\nnote\n", encoding="utf-8")
        apply_new_fields(PLANT_TEMPLATE, p)
        assert p.read_text(encoding="utf-8").endswith("### Day 1\nnote\n")

    def test_project_body_is_preserved_not_overwritten(self, tmp_path):
        p = tmp_path / "project.md"
        p.write_text(
            "---\ncross_name: Lantz\n---\n## Notes\nsome text\n", encoding="utf-8"
        )
        apply_new_fields(PROJECT_TEMPLATE, p)
        assert p.read_text(encoding="utf-8").endswith("## Notes\nsome text\n")


# ------------------------------------------------ run_migration_across_repos


class TestRunMigrationAcrossRepos:
    def test_migration_adds_missing_fields_and_pushes_commit(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path,
            "lantz",
            "cross_name: Lantz\n",
            plant_files=[("Ltz01.md", "id: Ltz01\n")],
        )
        before_sha = _remote_head_sha(remote)
        state = tmp_path / "state.json"
        registry = [{"name": "lantz", "path": str(local)}]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert isinstance(report, MigrationReport)
        assert report.repos["lantz"]["status"] == "success"
        after_sha = _remote_head_sha(remote)
        assert after_sha != before_sha

        check = tmp_path / "check-clone"
        content = _clone_and_read(remote, check)
        assert "auto_create: false" in content
        plant_content = (check / "plants" / "Ltz01.md").read_text(
            encoding="utf-8"
        )
        assert "photo_count: 0" in plant_content

    def test_idempotent_rerun_makes_zero_commits(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "lantz", "cross_name: Lantz\n"
        )
        state = tmp_path / "state.json"
        registry = [{"name": "lantz", "path": str(local)}]

        run_migration_across_repos(PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state)
        mid_sha = _remote_head_sha(remote)

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )
        after_sha = _remote_head_sha(remote)

        assert after_sha == mid_sha, "re-running with no schema change must push nothing new"
        assert report.repos["lantz"]["status"] == "skipped"

    def test_one_repo_unreachable_others_succeed_and_report_identifies_it(
        self, tmp_path
    ):
        local_good, remote_good = _init_repo_with_remote(
            tmp_path, "good", "cross_name: Good\n"
        )
        state = tmp_path / "state.json"
        registry = [
            {"name": "good", "path": str(local_good)},
            {"name": "bad", "path": str(tmp_path / "does-not-exist")},
        ]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["good"]["status"] == "success"
        assert report.repos["bad"]["status"] == "failed"
        assert report.repos["bad"]["error"]
        assert "good" in report.successful
        assert "bad" in report.failed

    def test_rerunning_only_retries_the_failed_repo(self, tmp_path):
        local_good, remote_good = _init_repo_with_remote(
            tmp_path, "good", "cross_name: Good\n"
        )
        bad_path = tmp_path / "bad-local"
        state = tmp_path / "state.json"
        registry = [
            {"name": "good", "path": str(local_good)},
            {"name": "bad", "path": str(bad_path)},
        ]

        run_migration_across_repos(PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state)
        good_sha_after_first = _remote_head_sha(remote_good)

        # "fix" bad repo by actually creating it now at the same path the
        # registry already points to (tmp_path / "bad-local").
        _, remote_bad = _init_repo_with_remote(tmp_path, "bad", "cross_name: Bad\n")
        assert bad_path.exists(), "helper must create the repo at bad_path"

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["good"]["status"] == "skipped"
        assert report.repos["bad"]["status"] == "success"
        good_sha_after_second = _remote_head_sha(remote_good)
        assert good_sha_after_second == good_sha_after_first, (
            "the already-successful repo must not be touched on retry"
        )
        after_bad_sha = _remote_head_sha(remote_bad)
        assert after_bad_sha  # bad repo now has a migration commit pushed

    def test_running_with_no_actual_schema_changes_makes_zero_commits(
        self, tmp_path
    ):
        # A repo that already has every current-template field present.
        full_fm = (
            "cross_name: Complete\n"
            "genetics: null\n"
            "breeder_lineage: null\n"
            "plant_id_prefixes: []\n"
            "auto_create: false\n"
            "github_repo: null\n"
            "github_pages_url: null\n"
            "google_sheet_id: null\n"
            "google_sheet_url: null\n"
            "drive_folders: {}\n"
            "notes_meta: {}\n"
            "created: null\n"
            "last_updated: null\n"
        )
        local, remote = _init_repo_with_remote(tmp_path, "complete", full_fm)
        before_sha = _remote_head_sha(remote)
        state = tmp_path / "state.json"
        registry = [{"name": "complete", "path": str(local)}]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        after_sha = _remote_head_sha(remote)
        assert after_sha == before_sha
        assert report.repos["complete"]["status"] == "success"
        assert report.repos["complete"]["added_fields"] == {}

    def test_report_repos_is_a_plain_dict_of_status_dicts(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "lantz", "cross_name: Lantz\n"
        )
        state = tmp_path / "state.json"
        registry = [{"name": "lantz", "path": str(local)}]
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )
        assert set(report.repos["lantz"]) >= {"status", "added_fields", "error"}
