"""Phase 2 / Task 2.3 -- ``breeding_core.push_to_github()`` against the
markdown data repo.

SAFETY (non-negotiable, and enforced by a test in this file). Nothing here
may ever reach a real GitHub repo. Every push in this suite targets a
THROWAWAY LOCAL BARE REPO created with ``git init --bare`` inside pytest's
``tmp_path``, standing in for GitHub; ``GITHUB_TOKEN`` is scrubbed from the
environment for every test, and ``test_no_command_ever_mentions_github_com``
records every ``subprocess.run`` argv the function issues and fails if any of
them so much as names ``github.com``.

What is being pinned (the Task 2.3 acceptance criteria):

* a change that genuinely touches ONE file commits EXACTLY that one file --
  and, separately and explicitly,
* a legitimately multi-file change (new-plant creation, which writes
  ``plants/<NEW>.md`` AND rewrites ``project.md``'s ``plant_order``) lands
  BOTH files in ONE commit. The two cases are asserted independently; the
  multi-file case is an allowed outcome, not a relaxation of the first.

Plus the surrounding mechanics that make those two claims meaningful: the
commit actually reaches the remote, unrelated working-tree junk is never
swept in, an unchanged tree makes no commit, and ``disable_push`` still
short-circuits everything.
"""

import subprocess
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

from breeding_tracker import breeding_core  # noqa: E402
from breeding_tracker import markdown_backend  # noqa: E402

REPO = "joeydouglas/example-breeding"  # never contacted; see module docstring


# --------------------------------------------------------------- helpers ----


def git(repo, *args, check=True):
    """Run one git command in ``repo`` and return its stdout."""
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}"
        )
    return result.stdout


def files_in_head(repo):
    """Paths touched by the repo's most recent commit."""
    out = git(repo, "show", "--name-only", "--pretty=format:", "HEAD")
    return sorted(p for p in out.splitlines() if p.strip())


def commit_count(repo):
    return int(git(repo, "rev-list", "--count", "HEAD").strip())


def seed_tracker():
    """A small but realistic two-plant roster."""
    return {
        "cross_name": "Sandbox Cross",
        "plants": [
            {
                "id": "PK01",
                "cross": "Sandbox Cross",
                "status": "active",
                "vigor": "8",
                "observation_log": "\n### 2026-09-01T00:00:00\nlooking good\n",
            },
            {
                "id": "PK02",
                "cross": "Sandbox Cross",
                "status": "active",
                "vigor": "7",
                "observation_log": "\n### 2026-09-01T00:00:00\nsteady\n",
            },
        ],
    }


@pytest.fixture(autouse=True)
def no_real_token(monkeypatch):
    """A real ``GITHUB_TOKEN`` in the ambient environment must never be able
    to leak into a test push. Removed for every test in this module."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture
def data_repo(tmp_path):
    """A migrated project directory that IS a git repo, wired to a throwaway
    local bare repo as its ``origin`` -- the stand-in for GitHub.

    Returns ``(project_dir, tracker_file, bare_remote)``.
    """
    project = tmp_path / "sandbox-cross"
    project.mkdir()
    tracker_file = project / "tracker.json"  # the JSON-era path wrappers pass

    markdown_backend.save_tracker(seed_tracker(), tracker_file)

    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )

    git(project, "init", "-b", "main")
    git(project, "config", "user.email", "sandbox@example.invalid")
    git(project, "config", "user.name", "Sandbox")
    git(project, "remote", "add", "origin", str(bare))
    git(project, "add", "--", "project.md", "plants")
    git(project, "commit", "-m", "seed")
    git(project, "push", "-q", "origin", "main")

    return project, tracker_file, bare


def remote_head(bare):
    return git(bare, "rev-parse", "refs/heads/main").strip()


# ------------------------------------------------- (a) single-file commit ----


def test_single_changed_plant_commits_exactly_that_one_file(data_repo):
    """A change that genuinely touches one file commits EXACTLY one file."""
    project, tracker_file, _bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    plant = next(p for p in tracker["plants"] if p["id"] == "PK02")
    plant["status"] = "keeper"
    markdown_backend.save_tracker(tracker, tracker_file)

    before = commit_count(project)
    breeding_core.push_to_github(project, REPO, False)

    assert commit_count(project) == before + 1
    assert files_in_head(project) == ["plants/PK02.md"]


def test_single_file_commit_reaches_the_local_bare_remote(data_repo):
    """The commit is genuinely pushed, not just made locally."""
    project, tracker_file, bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK01")["vigor"] = "9"
    markdown_backend.save_tracker(tracker, tracker_file)

    breeding_core.push_to_github(project, REPO, False)

    local = git(project, "rev-parse", "HEAD").strip()
    assert remote_head(bare) == local
    assert (
        git(bare, "show", "--name-only", "--pretty=format:", "HEAD").strip()
        == "plants/PK01.md"
    )


# ------------------------------------------ (b) legitimate multi-file case ----


def test_new_plant_commits_plant_file_and_project_md_together(data_repo):
    """EXPLICITLY ALLOWED multi-file case, tested on its own terms.

    Creating a plant writes ``plants/<NEW>.md`` and also rewrites
    ``project.md`` (its ``plant_order`` gains the new id). Both belong in ONE
    commit -- splitting them would publish a roster referencing a plant file
    that is not yet on the remote.
    """
    project, tracker_file, bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    tracker["plants"].append(
        breeding_core.make_blank_plant("PK03", "Sandbox Cross")
    )
    markdown_backend.save_tracker(tracker, tracker_file)

    before = commit_count(project)
    breeding_core.push_to_github(project, REPO, False)

    assert commit_count(project) == before + 1, "both files in ONE commit"
    assert files_in_head(project) == ["plants/PK03.md", "project.md"]
    assert remote_head(bare) == git(project, "rev-parse", "HEAD").strip()


def test_deleted_plant_is_staged_as_a_deletion(data_repo):
    """Whole-roster semantics: ``save_tracker`` unlinks a dropped plant's
    file, so the push must record the DELETION (a path-limited ``git add``
    that forgot ``--all`` semantics would silently leave the file on the
    remote forever)."""
    project, tracker_file, bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    tracker["plants"] = [p for p in tracker["plants"] if p["id"] != "PK02"]
    markdown_backend.save_tracker(tracker, tracker_file)

    breeding_core.push_to_github(project, REPO, False)

    assert files_in_head(project) == ["plants/PK02.md", "project.md"]
    assert "plants/PK02.md" not in git(bare, "ls-tree", "-r", "--name-only", "HEAD")


# ------------------------------------------------------- (c) the mechanics ----


def test_unrelated_working_tree_junk_is_never_committed(data_repo):
    """Only the markdown data files are staged.

    The live project dirs also hold ``tracker.json``, ``cache/``,
    ``photo_staging/``, ``__pycache__/`` and ``save_tracker``'s own
    ``.save_tracker-staging-*`` scratch dirs. A blanket ``git add .`` would
    publish all of it into the private data repo.
    """
    project, tracker_file, _bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK01")["vigor"] = "10"
    markdown_backend.save_tracker(tracker, tracker_file)

    (project / "tracker.json").write_text('{"legacy": true}', encoding="utf-8")
    (project / "photo_staging").mkdir()
    (project / "photo_staging" / "IMG_0001.jpg").write_bytes(b"not-a-real-photo")
    (project / "cache").mkdir()
    (project / "cache" / "state.json").write_text("{}", encoding="utf-8")
    (project / ".save_tracker-staging-xyz").mkdir()
    (project / ".save_tracker-staging-xyz" / "project.md").write_text(
        "scratch", encoding="utf-8"
    )

    breeding_core.push_to_github(project, REPO, False)

    assert files_in_head(project) == ["plants/PK01.md"]
    tracked = git(project, "ls-files")
    for junk in ("tracker.json", "photo_staging", "cache", ".save_tracker"):
        assert junk not in tracked


def test_no_changes_makes_no_commit(data_repo):
    """An observation that changed nothing on disk must not manufacture an
    empty commit on every Discord message."""
    project, _tracker_file, _bare = data_repo
    before = commit_count(project)

    breeding_core.push_to_github(project, REPO, False)

    assert commit_count(project) == before


def test_previously_stranded_commit_is_still_pushed(data_repo):
    """Phase 1's push-stranding lesson (breeding-markdown DECISIONS.md): a
    commit that exists locally but never reached the remote must be pushed by
    the next call even though THIS call changed nothing."""
    project, tracker_file, bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK02")["status"] = "culled"
    markdown_backend.save_tracker(tracker, tracker_file)
    git(project, "add", "--", "project.md", "plants")
    git(project, "commit", "-m", "stranded, never pushed")
    stranded = git(project, "rev-parse", "HEAD").strip()
    assert remote_head(bare) != stranded

    breeding_core.push_to_github(project, REPO, False)

    assert remote_head(bare) == stranded


def test_disable_push_makes_no_commit_and_no_git_call(data_repo, monkeypatch):
    project, tracker_file, _bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK01")["vigor"] = "3"
    markdown_backend.save_tracker(tracker, tracker_file)
    before = commit_count(project)

    calls = []
    real_run = subprocess.run
    monkeypatch.setattr(
        breeding_core.subprocess,
        "run",
        lambda *a, **k: (calls.append(a), real_run(*a, **k))[1],
    )

    breeding_core.push_to_github(project, REPO, True)

    assert calls == []
    assert commit_count(project) == before


def test_non_git_project_dir_does_not_raise(tmp_path):
    """Pre-migration reality: a project directory that is not a git repo (and
    has no ``dashboard/``) must be a safe no-op, not a crash inside the
    Discord ingestion path."""
    project = tmp_path / "not-a-repo"
    project.mkdir()
    markdown_backend.save_tracker(seed_tracker(), project / "tracker.json")

    breeding_core.push_to_github(project, REPO, False)  # must not raise

    assert not (project / ".git").exists()


def test_no_command_ever_mentions_github_com(data_repo, monkeypatch):
    """THE SAFETY TEST. Record every argv this function issues and prove none
    of them names github.com or any http(s) URL -- the whole suite pushes to
    a local bare repo only."""
    project, tracker_file, _bare = data_repo

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK01")["vigor"] = "6"
    markdown_backend.save_tracker(tracker, tracker_file)

    seen = []
    real_run = subprocess.run

    def recording_run(cmd, *a, **k):
        seen.append(list(cmd))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(breeding_core.subprocess, "run", recording_run)

    breeding_core.push_to_github(project, REPO, False)

    assert seen, "expected at least one git invocation"
    flat = " ".join(" ".join(str(part) for part in cmd) for cmd in seen)
    assert "github.com" not in flat
    assert "http://" not in flat and "https://" not in flat


# ------------------------------------------------- token handling (no leak) ----


def test_token_is_not_interpolated_into_a_remote_url(data_repo, monkeypatch):
    """A ``GITHUB_TOKEN`` must reach git as an ``http.extraHeader``, never
    baked into a remote URL where it lands in ``.git/config``, ``git remote
    -v`` and error logs. Still pushes to the local bare repo."""
    project, tracker_file, bare = data_repo
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_sekrit_do_not_leak")

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK01")["vigor"] = "4"
    markdown_backend.save_tracker(tracker, tracker_file)

    breeding_core.push_to_github(project, REPO, False)

    assert remote_head(bare) == git(project, "rev-parse", "HEAD").strip()
    config = (project / ".git" / "config").read_text(encoding="utf-8")
    assert "ghp_sekrit_do_not_leak" not in config
    assert git(project, "remote", "get-url", "origin").strip() == str(bare)


# ---------------------------------- transitional legacy dashboard/ push ----


@pytest.fixture
def legacy_dashboard(data_repo):
    """A project that ALSO still has the JSON-era ``dashboard/`` git repo,
    wired to its own separate throwaway local bare remote.

    Returns ``(project, tracker_file, data_bare, dashboard_dir, dash_bare)``.
    """
    project, tracker_file, data_bare = data_repo

    dashboard = project / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<h1>v1</h1>", encoding="utf-8")

    dash_bare = project.parent / "dashboard-origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(dash_bare)],
        capture_output=True,
        check=True,
    )
    git(dashboard, "init", "-b", "main")
    git(dashboard, "config", "user.email", "sandbox@example.invalid")
    git(dashboard, "config", "user.name", "Sandbox")
    git(dashboard, "remote", "add", "origin", str(dash_bare))
    git(dashboard, "add", "-A")
    git(dashboard, "commit", "-m", "seed dashboard")
    git(dashboard, "push", "-q", "origin", "main")

    return project, tracker_file, data_bare, dashboard, dash_bare


def test_legacy_dashboard_repo_is_still_pushed(legacy_dashboard):
    """TRANSITIONAL. Until Task 7.3 decommissions them, the six live projects
    still serve their dashboards from ``dashboard/``, and today NONE of the
    project dirs is a git repo. Dropping this push would silently freeze all
    six live dashboards for the whole Phase 3-7 window."""
    project, _tracker_file, _data_bare, dashboard, dash_bare = legacy_dashboard

    (dashboard / "index.html").write_text("<h1>v2</h1>", encoding="utf-8")
    before = commit_count(dashboard)

    breeding_core.push_to_github(project, REPO, False)

    assert commit_count(dashboard) == before + 1
    assert remote_head(dash_bare) == git(dashboard, "rev-parse", "HEAD").strip()
    assert "v2" in git(dash_bare, "show", "HEAD:index.html")


def test_data_repo_and_legacy_dashboard_are_pushed_independently(legacy_dashboard):
    """Two repos, two commits -- the data repo's commit still contains
    EXACTLY its own changed file and none of the dashboard's."""
    project, tracker_file, data_bare, dashboard, dash_bare = legacy_dashboard

    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == "PK02")["status"] = "keeper"
    markdown_backend.save_tracker(tracker, tracker_file)
    (dashboard / "index.html").write_text("<h1>v3</h1>", encoding="utf-8")

    breeding_core.push_to_github(project, REPO, False)

    assert files_in_head(project) == ["plants/PK02.md"]
    assert files_in_head(dashboard) == ["index.html"]
    assert remote_head(data_bare) == git(project, "rev-parse", "HEAD").strip()
    assert remote_head(dash_bare) == git(dashboard, "rev-parse", "HEAD").strip()


def test_dashboard_only_project_still_pushes_today(tmp_path):
    """The CURRENT live shape: ``dashboard/`` is a git repo, the project dir
    is not. The dashboard must still be published."""
    project = tmp_path / "pre-migration"
    project.mkdir()
    markdown_backend.save_tracker(seed_tracker(), project / "tracker.json")

    dashboard = project / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<h1>live</h1>", encoding="utf-8")
    bare = tmp_path / "dash.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )
    git(dashboard, "init", "-b", "main")
    git(dashboard, "config", "user.email", "sandbox@example.invalid")
    git(dashboard, "config", "user.name", "Sandbox")
    git(dashboard, "remote", "add", "origin", str(bare))

    breeding_core.push_to_github(project, REPO, False)

    assert commit_count(dashboard) == 1
    assert remote_head(bare) == git(dashboard, "rev-parse", "HEAD").strip()


def test_disable_push_also_skips_the_legacy_dashboard(legacy_dashboard):
    project, _tracker_file, _data_bare, dashboard, _dash_bare = legacy_dashboard
    (dashboard / "index.html").write_text("<h1>v9</h1>", encoding="utf-8")
    before = commit_count(dashboard)

    breeding_core.push_to_github(project, REPO, True)

    assert commit_count(dashboard) == before

