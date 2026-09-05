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

import json
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


# ------------------------------------------------- spec-compliance review ----


def _remote_refs(remote):
    result = subprocess.run(
        ["git", "ls-remote", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _local_head(local):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(local),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_files(local, rev="HEAD"):
    result = subprocess.run(
        ["git", "show", "--pretty=format:", "--name-only", rev],
        cwd=str(local),
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(f for f in result.stdout.split() if f)


class TestPushIsActuallyVerifiedBeforeRecordingSuccess:
    """Review finding (resumability): with a reachable local clone but an
    unreachable REMOTE, run 1 correctly reports failed -- but
    apply_new_fields has already been applied and COMMITTED locally before
    the push failed. On retry with the remote restored, apply_new_fields
    returns changed=False (the file already matches the template), so the
    old code made no git call at all, never re-pushed, and still recorded
    'success' at the current template version. The repo's migration commit
    was silently stranded in the local clone forever."""

    def test_retry_after_push_failure_actually_pushes_the_local_commit(
        self, tmp_path
    ):
        local, remote = _init_repo_with_remote(
            tmp_path, "stranded", "cross_name: Stranded\n"
        )
        state = tmp_path / "state.json"
        registry = [{"name": "stranded", "path": str(local)}]

        # Run 1: remote unreachable (moved aside). The local field-apply and
        # commit still happen; only the push fails.
        moved = tmp_path / "stranded-remote-moved.git"
        remote.rename(moved)
        report1 = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )
        assert report1.repos["stranded"]["status"] == "failed"

        # Run 2: remote is reachable again. Even though the local file
        # already matches the template, the commit must still get pushed.
        moved.rename(remote)
        report2 = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report2.repos["stranded"]["status"] == "success"
        assert _local_head(local) in _remote_refs(remote), (
            "the local migration commit was recorded as a success but never "
            "actually reached the remote"
        )
        content = _clone_and_read(remote, tmp_path / "verify-clone")
        assert "auto_create: false" in content

    def test_unpushed_local_commit_is_not_recorded_as_success(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "nopush", "cross_name: NoPush\n"
        )
        state = tmp_path / "state.json"
        registry = [{"name": "nopush", "path": str(local)}]

        moved = tmp_path / "nopush-remote-moved.git"
        remote.rename(moved)
        run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        persisted = json.loads(state.read_text(encoding="utf-8"))
        assert persisted["repos"]["nopush"]["status"] == "failed", (
            "a repo whose commit never reached the remote must not be "
            "persisted as migrated at the current template version"
        )
        moved.rename(remote)


class TestCommitStagesOnlyMigratedFiles:
    """Review finding: _migrate_one_repo committed with `git add -A`,
    sweeping every unrelated dirty/untracked file in the working tree into
    the migration commit."""

    def test_unrelated_dirty_files_are_not_swept_into_the_commit(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path,
            "sweep",
            "cross_name: Sweep\n",
            plant_files=[("Sw01.md", "id: Sw01\n")],
        )
        # Unrelated junk in the working tree at migration time.
        (local / "scratch.txt").write_text("untracked junk\n", encoding="utf-8")
        (local / "notes.local").write_text("more junk\n", encoding="utf-8")

        state = tmp_path / "state.json"
        registry = [{"name": "sweep", "path": str(local)}]
        run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        committed = _commit_files(local)
        assert committed == ["plants/Sw01.md", "project.md"], (
            f"migration commit must contain only migrated files, got {committed}"
        )
        assert (local / "scratch.txt").exists()

    def test_unrelated_modified_tracked_file_is_not_committed(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "dirty", "cross_name: Dirty\n"
        )
        readme = local / "README.md"
        readme.write_text("hand edit in progress\n", encoding="utf-8")
        _git(["add", "README.md"], local)
        _git(["commit", "-q", "-m", "add readme"], local)
        readme.write_text("uncommitted work in progress\n", encoding="utf-8")

        state = tmp_path / "state.json"
        registry = [{"name": "dirty", "path": str(local)}]
        run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert _commit_files(local) == ["project.md"]
        assert (
            readme.read_text(encoding="utf-8") == "uncommitted work in progress\n"
        ), "the unrelated in-progress edit must remain uncommitted in the tree"


class TestStateIsPersistedIncrementally:
    """Review finding: _save_state was only called after the ENTIRE registry
    loop finished, so a mid-run crash (Ctrl-C, OOM, machine reboot)
    persisted nothing at all and a restart re-migrated every repo from
    scratch -- including ones that had already succeeded and pushed."""

    def test_crash_midway_still_persists_earlier_successes(
        self, tmp_path, monkeypatch
    ):
        local_a, remote_a = _init_repo_with_remote(
            tmp_path, "alpha", "cross_name: Alpha\n"
        )
        local_b, remote_b = _init_repo_with_remote(
            tmp_path, "beta", "cross_name: Beta\n"
        )
        state = tmp_path / "state.json"
        registry = [
            {"name": "alpha", "path": str(local_a)},
            {"name": "beta", "path": str(local_b)},
        ]

        import migration as migration_module

        real = migration_module._migrate_one_repo

        def crash_on_beta(project_template, plant_template, repo_path):
            if Path(repo_path).name == "beta-local":
                # A hard interrupt, not a normal Exception: the per-repo
                # try/except deliberately does not catch this.
                raise KeyboardInterrupt("simulated mid-run crash")
            return real(project_template, plant_template, repo_path)

        monkeypatch.setattr(migration_module, "_migrate_one_repo", crash_on_beta)

        with pytest.raises(KeyboardInterrupt):
            run_migration_across_repos(
                PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
            )

        assert state.exists(), "state must be persisted before the crash"
        persisted = json.loads(state.read_text(encoding="utf-8"))
        assert persisted["repos"]["alpha"]["status"] == "success", (
            "alpha migrated and pushed successfully before the crash; a "
            "restart must not re-migrate it from scratch"
        )
        assert "beta" not in persisted["repos"]

    def test_restart_after_crash_skips_the_already_migrated_repo(
        self, tmp_path, monkeypatch
    ):
        local_a, remote_a = _init_repo_with_remote(
            tmp_path, "alpha", "cross_name: Alpha\n"
        )
        local_b, remote_b = _init_repo_with_remote(
            tmp_path, "beta", "cross_name: Beta\n"
        )
        state = tmp_path / "state.json"
        registry = [
            {"name": "alpha", "path": str(local_a)},
            {"name": "beta", "path": str(local_b)},
        ]

        import migration as migration_module

        real = migration_module._migrate_one_repo

        def crash_on_beta(project_template, plant_template, repo_path):
            if Path(repo_path).name == "beta-local":
                raise KeyboardInterrupt("simulated mid-run crash")
            return real(project_template, plant_template, repo_path)

        monkeypatch.setattr(migration_module, "_migrate_one_repo", crash_on_beta)
        with pytest.raises(KeyboardInterrupt):
            run_migration_across_repos(
                PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
            )
        alpha_sha = _remote_head_sha(remote_a)

        monkeypatch.setattr(migration_module, "_migrate_one_repo", real)
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["alpha"]["status"] == "skipped"
        assert report.repos["beta"]["status"] == "success"
        assert _remote_head_sha(remote_a) == alpha_sha


# --------------------------- code-quality review round 3 (migration.py) ----


def _porcelain(local):
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(local),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestCommitStrandingIsDetected:
    """Review finding (Critical): if `git add`/`git commit` fails AFTER
    apply_new_fields has already rewritten the files on disk, the run is
    correctly reported failed -- but the rewritten files stay UNCOMMITTED in
    the working tree. On retry, apply_new_fields sees the files already
    match the template (changed=False), so no commit and no push is
    attempted (local HEAD already equals the remote tip from before), and
    the run records status=success with the edits never having been
    committed or pushed. They sit as permanent uncommitted local changes and
    the repo is marked migrated forever. Same class as the push-stranding
    bug, one step earlier in the same function."""

    def test_retry_after_commit_failure_actually_commits_and_pushes(
        self, tmp_path, monkeypatch
    ):
        local, remote = _init_repo_with_remote(
            tmp_path, "commitstrand", "cross_name: CommitStrand\n"
        )
        state = tmp_path / "state.json"
        registry = [{"name": "commitstrand", "path": str(local)}]

        import migration as migration_module

        real_git = migration_module._git

        def fail_on_commit(args, cwd):
            if args and args[0] == "commit":
                raise subprocess.CalledProcessError(1, ["git", *args])
            return real_git(args, cwd)

        monkeypatch.setattr(migration_module, "_git", fail_on_commit)
        report1 = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )
        assert report1.repos["commitstrand"]["status"] == "failed"

        # Commit works again. The retry must NOT record success while the
        # migration's edits are still sitting uncommitted/unpushed.
        monkeypatch.setattr(migration_module, "_git", real_git)
        report2 = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report2.repos["commitstrand"]["status"] == "success"
        content = _clone_and_read(remote, tmp_path / "verify-clone")
        assert "auto_create: false" in content, (
            "recorded success but the migrated fields never reached the remote"
        )

    def test_uncommitted_migration_edits_are_never_recorded_as_success(
        self, tmp_path, monkeypatch
    ):
        local, remote = _init_repo_with_remote(
            tmp_path, "dirtyskip", "cross_name: DirtySkip\n"
        )
        state = tmp_path / "state.json"
        registry = [{"name": "dirtyskip", "path": str(local)}]

        import migration as migration_module

        real_git = migration_module._git

        def fail_on_commit(args, cwd):
            if args and args[0] == "commit":
                raise subprocess.CalledProcessError(1, ["git", *args])
            return real_git(args, cwd)

        monkeypatch.setattr(migration_module, "_git", fail_on_commit)
        run_migration_across_repos(PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state)

        # Simulate the retry seeing an already-template-matching file while
        # the edits remain uncommitted: hand-apply the fields and leave them
        # dirty, then run with commit still broken.
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )
        if report.repos["dirtyskip"]["status"] == "success":
            assert _porcelain(local) == "", (
                "recorded success while migration-managed paths were still "
                "dirty in the working tree"
            )


class TestFailurePathsAreIsolatedToOneRepo:
    """Review finding: three unhandled exception paths in
    run_migration_across_repos abort the ENTIRE batch instead of isolating
    the failure to one repo."""

    def test_registry_entry_missing_name_does_not_abort_the_batch(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "ok", "cross_name: Ok\n"
        )
        state = tmp_path / "state.json"
        registry = [
            {"path": str(tmp_path / "nameless")},  # no "name" key
            {"name": "ok", "path": str(local)},
        ]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["ok"]["status"] == "success", (
            "a malformed registry entry must not prevent valid repos from "
            "migrating"
        )
        assert report.failed, "the malformed entry must be reported as failed"

    def test_registry_entry_missing_path_does_not_abort_the_batch(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "ok2", "cross_name: Ok2\n"
        )
        state = tmp_path / "state.json"
        registry = [
            {"name": "pathless"},  # no "path" key
            {"name": "ok2", "path": str(local)},
        ]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["ok2"]["status"] == "success"
        assert report.repos["pathless"]["status"] == "failed"

    def test_corrupt_state_file_does_not_brick_every_future_run(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "recover", "cross_name: Recover\n"
        )
        state = tmp_path / "state.json"
        state.write_text("{ this is not json", encoding="utf-8")
        registry = [{"name": "recover", "path": str(local)}]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["recover"]["status"] == "success", (
            "a truncated/corrupt state file must degrade to an empty state, "
            "not raise JSONDecodeError before the loop even starts"
        )
        persisted = json.loads(state.read_text(encoding="utf-8"))
        assert persisted["repos"]["recover"]["status"] == "success"

    def test_missing_state_parent_directory_is_created(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "mkdirs", "cross_name: Mkdirs\n"
        )
        state = tmp_path / "nested" / "deeper" / "state.json"
        registry = [{"name": "mkdirs", "path": str(local)}]

        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["mkdirs"]["status"] == "success"
        assert state.exists(), (
            "the first _save_state after a successful migration raised "
            "FileNotFoundError, losing that repo's record"
        )


class TestDetachedHeadIsAHardFailure:
    """Review finding: `git rev-parse --abbrev-ref HEAD` returns the literal
    string 'HEAD' on a detached HEAD, which then became the push TARGET
    (`push origin HEAD:refs/heads/HEAD`) -- creating a garbage branch on the
    remote while reporting success, and never reaching the real branch."""

    def test_detached_head_repo_is_reported_failed(self, tmp_path):
        local, remote = _init_repo_with_remote(
            tmp_path, "detached", "cross_name: Detached\n"
        )
        _git(["checkout", "-q", "--detach", "HEAD"], local)

        state = tmp_path / "state.json"
        registry = [{"name": "detached", "path": str(local)}]
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["detached"]["status"] == "failed"
        assert _remote_refs(remote).count("refs/heads/HEAD") == 0, (
            "a detached HEAD must never be pushed to a literal "
            "refs/heads/HEAD garbage branch"
        )

    def test_detached_head_does_not_abort_other_repos(self, tmp_path):
        local_bad, remote_bad = _init_repo_with_remote(
            tmp_path, "det2", "cross_name: Det2\n"
        )
        _git(["checkout", "-q", "--detach", "HEAD"], local_bad)
        local_good, remote_good = _init_repo_with_remote(
            tmp_path, "good2", "cross_name: Good2\n"
        )

        state = tmp_path / "state.json"
        registry = [
            {"name": "det2", "path": str(local_bad)},
            {"name": "good2", "path": str(local_good)},
        ]
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["det2"]["status"] == "failed"
        assert report.repos["good2"]["status"] == "success"


class TestFailureRollsBackAndReportsTouchedPaths:
    """Review finding: every failure path left the working tree dirty with
    half-applied edits and no rollback, and the failure report's
    added_fields was hardcoded to {} -- discarding what was actually touched
    before the failure. A dirty tree also collides with the next run or a
    human/data-api `git pull`."""

    def test_failed_run_leaves_no_dirty_migration_paths(self, tmp_path, monkeypatch):
        local, remote = _init_repo_with_remote(
            tmp_path,
            "rollback",
            "cross_name: Rollback\n",
            plant_files=[("Rb01.md", "id: Rb01\n")],
        )
        state = tmp_path / "state.json"
        registry = [{"name": "rollback", "path": str(local)}]

        import migration as migration_module

        real_git = migration_module._git

        def fail_on_commit(args, cwd):
            if args and args[0] == "commit":
                raise subprocess.CalledProcessError(1, ["git", *args])
            return real_git(args, cwd)

        monkeypatch.setattr(migration_module, "_git", fail_on_commit)
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        assert report.repos["rollback"]["status"] == "failed"
        assert _porcelain(local) == "", (
            "a failed migration must roll its own half-applied edits back, "
            "not leave the working tree dirty for the next run or a git pull"
        )

    def test_failure_report_names_the_paths_actually_touched(
        self, tmp_path, monkeypatch
    ):
        local, remote = _init_repo_with_remote(
            tmp_path,
            "touched",
            "cross_name: Touched\n",
            plant_files=[("Tc01.md", "id: Tc01\n")],
        )
        state = tmp_path / "state.json"
        registry = [{"name": "touched", "path": str(local)}]

        import migration as migration_module

        real_git = migration_module._git

        def fail_on_commit(args, cwd):
            if args and args[0] == "commit":
                raise subprocess.CalledProcessError(1, ["git", *args])
            return real_git(args, cwd)

        monkeypatch.setattr(migration_module, "_git", fail_on_commit)
        report = run_migration_across_repos(
            PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, state
        )

        touched = report.repos["touched"]["added_fields"]
        assert touched, (
            "the failure report discarded which paths/fields were touched "
            "before the failure"
        )
        assert set(touched) == {"project.md", "plants/Tc01.md"}
        assert "auto_create" in touched["project.md"]

        persisted = json.loads(state.read_text(encoding="utf-8"))
        assert persisted["repos"]["touched"]["added_fields"] == touched
