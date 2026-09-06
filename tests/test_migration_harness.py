"""Unit tests for `migration_harness`, the shared Task 3.x verification scaffolding.

These cover the three code-quality defects found in Task 3.2's tooling before
Task 3.3 replicates them:

1. **The git-diff gate was a suffix whitelist.** `verify_*_migration.py` decided
   "no unexpected git changes" by discarding every porcelain line ending in one
   of a hardcoded list of paths. That whitelist grows by one entry per project,
   is order-insensitive to *what* changed (a wipe of `src/tracker_migration.py`
   reads the same as an edit), silently forgives a *pre-existing* dirty file it
   happens to name, and — in the mule-fuel copy — contained a blanket
   `"tools/" not in line` escape that forgave any change under `tools/`
   whatsoever. The gate is replaced by a before/after baseline diff: whatever
   the tree looked like when the run started is the baseline, and *any*
   divergence from it is reported, with no path ever whitelisted.

2. **The live-dir fingerprint was flaky.** `(size, mtime_ns)` over
   `LIVE_DIR.rglob("*")` includes `__pycache__/`, `cache/`, `.pytest_cache/`
   and the nested `dashboard/.git/` working repo — all of which are written by
   unrelated processes (a python import, the dashboard generator, a `git fetch`)
   at arbitrary times, so the check can go red without the migration having done
   anything. Volatile paths are now excluded *by an explicit, tested classifier*
   and the nested git repos they contain are covered by a strictly stronger,
   non-timing check (HEAD sha + porcelain status) instead of file mtimes.

3. Per-project duplication — covered by the shared `ProjectSpec` contract
   exercised from the per-project test modules, not here.

Every exclusion below is paired with a negative control: a test proving the
classifier still *includes* the data-bearing paths, and a test proving the
check actually flips to red when one of those is touched. A green check that
has never been observed to go red is not evidence (DECISIONS.md, Task 3.2).
"""

import subprocess
from pathlib import Path

import pytest

from migration_harness import (
    ProjectSpec,
    fingerprint_tree,
    git_status_snapshot,
    is_volatile_path,
    live_tree_state,
    nested_repo_state,
    unexpected_git_changes,
)


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one committed file."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "keep.py").write_text("x = 1\n", encoding="utf-8")
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    return root


# --------------------------------------------------------------------------
# 1. the git gate: baseline diff, not a suffix whitelist
# --------------------------------------------------------------------------


def test_clean_repo_snapshot_is_empty(repo):
    assert git_status_snapshot(repo) == {}


def test_a_file_modified_after_the_baseline_is_reported(repo):
    before = git_status_snapshot(repo)
    (repo / "src" / "keep.py").write_text("x = 2\n", encoding="utf-8")
    after = git_status_snapshot(repo)
    assert unexpected_git_changes(before, after) == ["src/keep.py: '  ' -> ' M'"]


def test_an_untracked_file_created_after_the_baseline_is_reported(repo):
    before = git_status_snapshot(repo)
    (repo / "brand-new.txt").write_text("hi\n", encoding="utf-8")
    changes = unexpected_git_changes(before, git_status_snapshot(repo))
    assert len(changes) == 1
    assert "brand-new.txt" in changes[0]


def test_a_file_already_dirty_at_baseline_is_not_reported(repo):
    """The whitelist existed to forgive the task's own in-flight edits.

    A baseline captures them for free and without naming any path, so a NEW
    change to a DIFFERENT file is still caught.
    """
    (repo / "src" / "keep.py").write_text("in flight\n", encoding="utf-8")
    before = git_status_snapshot(repo)
    assert unexpected_git_changes(before, git_status_snapshot(repo)) == []


def test_a_baseline_dirty_file_that_changes_state_is_still_reported(repo):
    """The whitelist could not see this: `src/tracker_migration.py` was forgiven
    whether it was modified, staged, or deleted."""
    (repo / "src" / "keep.py").write_text("in flight\n", encoding="utf-8")
    before = git_status_snapshot(repo)
    _git(repo, "add", "src/keep.py")
    changes = unexpected_git_changes(before, git_status_snapshot(repo))
    assert changes == ["src/keep.py: ' M' -> 'M '"]


def test_a_baseline_modification_that_disappears_is_reported(repo):
    """Something reverted the tree mid-run (a stray checkout/stash). The
    whitelist reported PASS for this; a baseline diff calls it out."""
    (repo / "src" / "keep.py").write_text("in flight\n", encoding="utf-8")
    before = git_status_snapshot(repo)
    _git(repo, "checkout", "--", "src/keep.py")
    changes = unexpected_git_changes(before, git_status_snapshot(repo))
    assert changes == ["src/keep.py: ' M' -> gone"]


def test_no_path_is_ever_whitelisted(repo):
    """A change to a path the old whitelist named must now be reported."""
    before = git_status_snapshot(repo)
    for name in ("DECISIONS.md", "tools/verify_x.py", "src/tracker_migration.py"):
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("touched\n", encoding="utf-8")
    changes = unexpected_git_changes(before, git_status_snapshot(repo))
    assert len(changes) == 3
    assert any("DECISIONS.md" in c for c in changes)
    assert any("tools/verify_x.py" in c for c in changes)
    assert any("src/tracker_migration.py" in c for c in changes)


def test_paths_with_spaces_and_quotes_are_parsed_intact(repo):
    """`git status --porcelain` C-quotes such paths; the -z form does not.

    ec18b34 already fixed exactly this class of parsing bug in migration.py;
    the verifier's own gate must not reintroduce it.
    """
    before = git_status_snapshot(repo)
    weird = repo / 'a file "with" spaces.txt'
    weird.write_text("hi\n", encoding="utf-8")
    after = git_status_snapshot(repo)
    assert 'a file "with" spaces.txt' in after
    assert any('a file "with" spaces.txt' in c for c in unexpected_git_changes(
        before, after
    ))


def test_renames_record_the_destination_path(repo):
    before = git_status_snapshot(repo)
    _git(repo, "mv", "src/keep.py", "src/renamed.py")
    after = git_status_snapshot(repo)
    assert "src/renamed.py" in after
    assert unexpected_git_changes(before, after)


def test_snapshot_of_a_non_repo_raises(tmp_path):
    """Silently returning {} for a path that is not a repo would make the gate
    vacuous — the exact failure class VerificationReport's counters exist for."""
    with pytest.raises(Exception):
        git_status_snapshot(tmp_path)


# --------------------------------------------------------------------------
# 2a. the volatile-path classifier
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "__pycache__/monitor_breeding_notes.cpython-311.pyc",
        "monitor_breeding_notes.pyc",
        "cache/all_doc_images.json",
        "cache",
        ".pytest_cache/v/cache/nodeids",
        "dashboard/.pytest_cache/CACHEDIR.TAG",
        "dashboard/.git/FETCH_HEAD",
        "dashboard/.git/objects/ab/cdef",
        "dashboard/breeding_tracker/__pycache__/x.cpython-311.pyc",
        ".DS_Store",
        "photo_staging/.tmp-download",
    ],
)
def test_volatile_paths_are_classified_volatile(rel):
    assert is_volatile_path(Path(rel)) is True


@pytest.mark.parametrize(
    "rel",
    [
        "tracker.json",
        "generate_dashboard.py",
        "monitor_breeding_notes.py",
        "photo_handler.py",
        "plants/HBH01.md",
        "dashboard/index.html",
        "dashboard/style.css",
        "dashboard/README.md",
        "dashboard/plants/HBH05.html",
        "dashboard/.gitignore",
        "dashboard/.github/workflows/trigger-do-deploy.yml",
        "dashboard/.deploy-verify.txt",
        "photo_staging/IMG_0001.jpg",
    ],
)
def test_data_bearing_paths_are_never_classified_volatile(rel):
    """The negative control for the exclusion: an over-broad classifier that
    swallowed tracker.json would make the whole fingerprint worthless."""
    assert is_volatile_path(Path(rel)) is False


# --------------------------------------------------------------------------
# 2b. the fingerprint itself
# --------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "live"
    (root / "plants").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / "cache").mkdir()
    (root / "tracker.json").write_text('{"plants": []}', encoding="utf-8")
    (root / "plants" / "HBH01.md").write_text("# one\n", encoding="utf-8")
    (root / "__pycache__" / "m.cpython-311.pyc").write_bytes(b"\x00")
    (root / "cache" / "docs.json").write_text("{}", encoding="utf-8")
    return root


def test_fingerprint_covers_the_data_files(tree):
    fp = fingerprint_tree(tree)
    assert "tracker.json" in fp
    assert "plants/HBH01.md" in fp


def test_fingerprint_excludes_volatile_files(tree):
    fp = fingerprint_tree(tree)
    assert not [k for k in fp if "__pycache__" in k or k.startswith("cache/")]


def test_churn_in_a_volatile_dir_does_not_change_the_fingerprint(tree):
    """The flake, reproduced: importing a module or running the dashboard
    generator rewrites these while the migration runs."""
    before = fingerprint_tree(tree)
    (tree / "__pycache__" / "m.cpython-314.pyc").write_bytes(b"\x01\x02")
    (tree / "cache" / "docs.json").write_text('{"new": 1}', encoding="utf-8")
    (tree / "cache" / "extra.json").write_text("{}", encoding="utf-8")
    (tree / "__pycache__" / "m.cpython-311.pyc").unlink()
    assert fingerprint_tree(tree) == before


def test_a_new_file_in_a_volatile_dir_does_not_move_its_parent_dir_entry(tree):
    """Directory mtimes bump when a child is created; fingerprinting directory
    mtimes would reintroduce the flake through the back door."""
    before = fingerprint_tree(tree)
    (tree / "cache" / "later.json").write_text("{}", encoding="utf-8")
    assert fingerprint_tree(tree) == before


def test_a_volatile_dir_created_inside_a_data_dir_does_not_move_the_data_dir(tree):
    """The real leak path, and the reason directories carry no mtime.

    `dashboard/breeding_tracker/` is project data and is fingerprinted; the
    first import of anything in it creates `dashboard/breeding_tracker/
    __pycache__/`, which bumps the *parent's* mtime. Excluding the
    `__pycache__` entry alone is not enough — the parent would still flip.
    """
    pkg = tree / "dashboard" / "breeding_tracker"
    pkg.mkdir(parents=True)
    (pkg / "app.py").write_text("x = 1\n", encoding="utf-8")
    before = fingerprint_tree(tree)
    assert "dashboard/breeding_tracker" in before

    cachedir = pkg / "__pycache__"
    cachedir.mkdir()
    (cachedir / "app.cpython-311.pyc").write_bytes(b"\x00")
    assert fingerprint_tree(tree) == before


def test_a_modified_data_file_does_change_the_fingerprint(tree):
    """Negative control: the check can still go red."""
    before = fingerprint_tree(tree)
    (tree / "tracker.json").write_text('{"plants": [1]}', encoding="utf-8")
    assert fingerprint_tree(tree) != before


def test_a_new_data_file_does_change_the_fingerprint(tree):
    before = fingerprint_tree(tree)
    (tree / "plants" / "HBH02.md").write_text("# two\n", encoding="utf-8")
    assert fingerprint_tree(tree) != before


def test_a_deleted_data_file_does_change_the_fingerprint(tree):
    before = fingerprint_tree(tree)
    (tree / "plants" / "HBH01.md").unlink()
    assert fingerprint_tree(tree) != before


def test_a_new_empty_data_directory_does_change_the_fingerprint(tree):
    """Directories are tracked by presence (not mtime), so a migration that
    created a stray `markdown/` dir in the live tree is still caught."""
    before = fingerprint_tree(tree)
    (tree / "markdown").mkdir()
    assert fingerprint_tree(tree) != before


# --------------------------------------------------------------------------
# 2c. nested git repos: a stronger check than mtimes
# --------------------------------------------------------------------------


def test_nested_repo_state_reports_head_and_status(tmp_path):
    live = tmp_path / "live"
    dash = live / "dashboard"
    dash.mkdir(parents=True)
    (dash / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    _git(live, "init", "-q", str(dash))
    _git(dash, "config", "user.email", "t@example.invalid")
    _git(dash, "config", "user.name", "t")
    _git(dash, "add", "-A")
    _git(dash, "commit", "-qm", "initial")

    state = nested_repo_state(live)
    assert set(state) == {"dashboard"}
    head, status = state["dashboard"]
    assert len(head) == 40
    assert status == {}


def test_nested_repo_state_flags_a_new_commit(tmp_path):
    """`dashboard/.git` is excluded from the mtime fingerprint, so this is the
    check that keeps a `git commit`/`git push` in the live dashboard visible."""
    live = tmp_path / "live"
    dash = live / "dashboard"
    dash.mkdir(parents=True)
    (dash / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    _git(live, "init", "-q", str(dash))
    _git(dash, "config", "user.email", "t@example.invalid")
    _git(dash, "config", "user.name", "t")
    _git(dash, "add", "-A")
    _git(dash, "commit", "-qm", "initial")
    before = nested_repo_state(live)

    (dash / "index.html").write_text("<p>changed</p>", encoding="utf-8")
    _git(dash, "commit", "-aqm", "second")
    assert nested_repo_state(live) != before


def test_nested_repo_state_flags_a_dirty_working_tree(tmp_path):
    live = tmp_path / "live"
    dash = live / "dashboard"
    dash.mkdir(parents=True)
    (dash / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    _git(live, "init", "-q", str(dash))
    _git(dash, "config", "user.email", "t@example.invalid")
    _git(dash, "config", "user.name", "t")
    _git(dash, "add", "-A")
    _git(dash, "commit", "-qm", "initial")
    before = nested_repo_state(live)

    (dash / "index.html").write_text("<p>dirty</p>", encoding="utf-8")
    assert nested_repo_state(live) != before


def test_nested_repo_state_is_stable_across_a_gc_style_mtime_bump(tmp_path):
    """Touching files under .git (what `git gc`/`git fetch` do) must NOT move
    the state — that is precisely the flake being removed."""
    live = tmp_path / "live"
    dash = live / "dashboard"
    dash.mkdir(parents=True)
    (dash / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    _git(live, "init", "-q", str(dash))
    _git(dash, "config", "user.email", "t@example.invalid")
    _git(dash, "config", "user.name", "t")
    _git(dash, "add", "-A")
    _git(dash, "commit", "-qm", "initial")
    before = nested_repo_state(live)

    (dash / ".git" / "FETCH_HEAD").write_text("whatever\n", encoding="utf-8")
    for p in (dash / ".git").rglob("*"):
        if p.is_file():
            p.touch()
    assert nested_repo_state(live) == before


# --------------------------------------------------------------------------
# 2d. the composite state used by the acceptance tests
# --------------------------------------------------------------------------


def test_live_tree_state_combines_the_fingerprint_and_the_repo_state(tree):
    state = live_tree_state(tree)
    assert set(state) == {"files", "repos"}
    assert "tracker.json" in state["files"]
    assert state["repos"] == {}


def test_live_tree_state_is_stable_under_pure_volatile_churn(tree):
    before = live_tree_state(tree)
    (tree / "__pycache__" / "later.cpython-314.pyc").write_bytes(b"\x03")
    assert live_tree_state(tree) == before


def test_live_tree_state_still_catches_a_data_write(tree):
    before = live_tree_state(tree)
    (tree / "tracker.json").write_text("{}", encoding="utf-8")
    assert live_tree_state(tree) != before


# --------------------------------------------------------------------------
# 3. ProjectSpec: the per-project delta, as data
# --------------------------------------------------------------------------


def _spec(**kw):
    base = dict(
        slug="demo-project",
        plant_count=3,
        project_keys=frozenset({"created", "cross_name"}),
        plant_keys=frozenset({"id", "cross"}),
    )
    base.update(kw)
    return ProjectSpec(**base)


def test_spec_derives_the_live_paths_from_the_slug():
    spec = _spec()
    assert spec.live_dir == Path.home() / ".hermes" / "breeding" / "demo-project"
    assert spec.tracker == spec.live_dir / "tracker.json"
    assert spec.registry.name == "registry.json"
    assert spec.registry.parent.name == "breeding-meta"


def test_expected_records_is_one_project_plus_the_plants():
    assert _spec(plant_count=23).expected_records == 24
    assert _spec(plant_count=45).expected_records == 46


def test_expected_fields_is_rederived_from_the_source_not_hardcoded():
    """The +2 are auto_create/plant_id_prefixes, which exist in no tracker."""
    source = {
        "created": "x",
        "cross_name": "y",
        "plants": [{"id": "A", "cross": "c"}, {"id": "B", "cross": "c", "extra": 1}],
    }
    assert _spec().expected_fields(source) == (2 + 3) + 2 + 2


def test_expected_fields_matches_the_honey_badger_number_from_task_3_2():
    """23 plants x 18 keys + 11 project keys + 2 routing fields = 427."""
    source = {
        **{f"k{i}": i for i in range(11)},
        "plants": [{f"f{j}": j for j in range(18)} for _ in range(23)],
    }
    assert _spec(plant_count=23).expected_fields(source) == 427


def test_spec_is_frozen_so_a_test_cannot_mutate_another_projects_contract():
    spec = _spec()
    with pytest.raises(Exception):
        spec.slug = "something-else"


def test_default_expected_plant_defaults_is_corrected_reading():
    assert _spec().expected_plant_defaults == frozenset({"corrected_reading"})
    assert _spec().expected_project_defaults == frozenset()
    assert _spec().incomplete_plants == frozenset()


# --------------------------------------------------------------------------
# 4. the harness must survive the acceptance suite's own booby-traps
# --------------------------------------------------------------------------


def test_harness_git_calls_survive_a_patched_subprocess_run(repo, monkeypatch):
    """The acceptance suite booby-traps `subprocess.run` so the migration
    cannot reach a git remote. The harness's OWN git calls are verification
    scaffolding, not code under test, and must keep working through that trap
    — otherwise the strongest live-dir check cannot be armed at the same time
    as the strongest side-effect check.

    Safe because `tracker_migration` is statically proven to import no
    subprocess at all, so the trap loses no coverage of the code under test.
    """

    def boom(*args, **kwargs):
        raise AssertionError("trapped")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, boom)
    assert git_status_snapshot(repo) == {}


def test_harness_nested_repo_state_survives_a_patched_subprocess_run(
    tmp_path, monkeypatch
):
    live = tmp_path / "live"
    dash = live / "dashboard"
    dash.mkdir(parents=True)
    (dash / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    _git(live, "init", "-q", str(dash))
    _git(dash, "config", "user.email", "t@example.invalid")
    _git(dash, "config", "user.name", "t")
    _git(dash, "add", "-A")
    _git(dash, "commit", "-qm", "initial")

    def boom(*args, **kwargs):
        raise AssertionError("trapped")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, boom)
    assert set(nested_repo_state(live)) == {"dashboard"}
