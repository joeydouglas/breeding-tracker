"""Phase 2 / Task 2.3 review round-1: the FAILURE paths of
``breeding_core.push_to_github()``.

The existing ``test_push_to_github.py`` pins the happy paths. This module
pins what happens when git *fails*, which is the case that actually matters
operationally: ``push_to_github()`` runs inside a Discord message handler, so
it must NEVER raise -- but "never raise" was implemented as "never say
anything", which made a wedged remote indistinguishable from a healthy one.

Two contracts are pinned here:

1. **Never-raise is absolute.** Not just non-zero git exits: an OSError from
   ``subprocess.run`` itself (missing/unexecutable git binary -- EACCES,
   ENOMEM, empty PATH) must also be swallowed, because it happens BEFORE the
   child process exists and would otherwise propagate straight out into the
   message handler and take the bot down.
2. **Failure is visible.** Every swallowed git failure emits a
   ``WARN: ...`` line on stderr, the same idiom ``update_plant`` already uses
   for failed photo uploads, which ``hermes_gateway.py`` captures.

SAFETY: as in the sibling module, every remote here is a throwaway local
bare repo under ``tmp_path`` (or a path that deliberately does not exist).
No network, no real GitHub, no credentials.
"""

import subprocess
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

import breeding_core  # noqa: E402
import markdown_backend  # noqa: E402

from test_push_to_github import (  # noqa: E402
    REPO,
    commit_count,
    git,
    seed_tracker,
)


@pytest.fixture(autouse=True)
def no_real_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture
def data_repo(tmp_path):
    """Same shape as the sibling module's fixture: a migrated project dir
    wired to a throwaway local bare repo standing in for GitHub."""
    project = tmp_path / "sandbox-cross"
    project.mkdir()
    tracker_file = project / "tracker.json"
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


def dirty(tracker_file, plant_id="PK01", vigor="9"):
    """Make a real one-file change so a commit/push is actually attempted."""
    tracker = markdown_backend.load_tracker(tracker_file)
    next(p for p in tracker["plants"] if p["id"] == plant_id)["vigor"] = vigor
    markdown_backend.save_tracker(tracker, tracker_file)


def warn_lines(capsys):
    return [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("WARN:")
    ]


# ------------------------------------- (a) non-fast-forward push rejection ----


def test_non_fast_forward_push_does_not_raise_and_warns(data_repo, capsys, tmp_path):
    """The reviewer's reproduction: a diverged origin. The local commit must
    survive (so the next push can still deliver it -- Phase 1's stranding
    lesson), the call must not raise, and the operator must SEE the failure
    instead of a silent no-op indistinguishable from success."""
    project, tracker_file, bare = data_repo

    # A second clone pushes first, so origin/main moves ahead of us.
    other = tmp_path / "other-clone"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True, check=True
    )
    git(other, "config", "user.email", "other@example.invalid")
    git(other, "config", "user.name", "Other")
    (other / "unrelated.md").write_text("from elsewhere\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-m", "diverge origin")
    git(other, "push", "-q", "origin", "main")
    ahead = git(bare, "rev-parse", "refs/heads/main").strip()

    dirty(tracker_file)
    before = commit_count(project)

    breeding_core.push_to_github(project, REPO, False)  # must not raise

    local = git(project, "rev-parse", "HEAD").strip()
    assert commit_count(project) == before + 1, "local commit must survive"
    assert git(bare, "rev-parse", "refs/heads/main").strip() == ahead, (
        "the rejected push must not have moved the remote"
    )
    assert local != ahead

    warns = warn_lines(capsys)
    assert any("git push failed" in w for w in warns), warns


def test_repeated_rejected_pushes_keep_warning(data_repo, capsys, tmp_path):
    """The reviewer ran the push three times and got three stranded commits
    with zero signal. Each attempt must now warn."""
    project, tracker_file, bare = data_repo

    other = tmp_path / "other-clone"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], capture_output=True, check=True
    )
    git(other, "config", "user.email", "other@example.invalid")
    git(other, "config", "user.name", "Other")
    (other / "unrelated.md").write_text("x\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-m", "diverge")
    git(other, "push", "-q", "origin", "main")

    for i, vigor in enumerate(("5", "6", "7")):
        dirty(tracker_file, vigor=vigor)
        capsys.readouterr()
        breeding_core.push_to_github(project, REPO, False)
        assert any("git push failed" in w for w in warn_lines(capsys)), (
            f"attempt {i + 1} was silent"
        )


# ------------------------------------------------ (b) unreachable origin ----


def test_missing_origin_path_does_not_raise_and_warns(data_repo, capsys, tmp_path):
    """origin points at a directory that does not exist (deleted repo, dead
    host). Best-effort: no raise, but a WARN."""
    project, tracker_file, _bare = data_repo
    git(project, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    dirty(tracker_file)
    before = commit_count(project)

    breeding_core.push_to_github(project, REPO, False)  # must not raise

    assert commit_count(project) == before + 1
    warns = warn_lines(capsys)
    assert any("git push failed" in w for w in warns), warns


# ---------------------------------------------- (c) stale .git/index.lock ----


def test_stale_index_lock_is_survived_and_warned(data_repo, capsys):
    """A crashed previous git leaves ``.git/index.lock`` behind; every
    ``git add`` then fails. Survive it, and say so."""
    project, tracker_file, _bare = data_repo
    dirty(tracker_file)
    (project / ".git" / "index.lock").write_text("", encoding="utf-8")
    before = commit_count(project)

    breeding_core.push_to_github(project, REPO, False)  # must not raise

    assert commit_count(project) == before, "nothing could be staged"
    warns = warn_lines(capsys)
    assert any("git add failed" in w for w in warns), warns


# --------------------------- never-raise is absolute: OSError from the exec ----


def test_broken_git_binary_lookup_does_not_raise(data_repo, capsys, monkeypatch):
    """With an empty PATH, ``subprocess.run`` raises FileNotFoundError BEFORE
    the child exists. That must not escape into the Discord handler."""
    project, tracker_file, _bare = data_repo
    dirty(tracker_file)
    monkeypatch.setenv("PATH", "")

    breeding_core.push_to_github(project, REPO, False)  # must not raise

    warns = warn_lines(capsys)
    assert warns, "a git binary that cannot be executed must be reported"


def test_oserror_from_subprocess_run_does_not_raise(data_repo, capsys, monkeypatch):
    """Generalisation: any OSError (EACCES, ENOMEM, ...) from the exec is
    swallowed and reported, not propagated."""
    project, tracker_file, _bare = data_repo
    dirty(tracker_file)

    def boom(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(breeding_core.subprocess, "run", boom)

    breeding_core.push_to_github(project, REPO, False)  # must not raise

    assert warn_lines(capsys)


def test_push_failure_warning_names_the_repo_and_git_stderr(data_repo, capsys, tmp_path):
    """The WARN must carry enough to act on: which repo, and git's own
    message -- and must NOT echo the argv (which carries credentials)."""
    project, tracker_file, _bare = data_repo
    git(project, "remote", "set-url", "origin", str(tmp_path / "nope.git"))
    dirty(tracker_file)

    breeding_core.push_to_github(project, REPO, False)

    warns = [w for w in warn_lines(capsys) if "git push failed" in w]
    assert warns
    line = warns[0]
    assert str(project) in line
    assert "extraHeader" not in line and "Authorization" not in line


# --------------------------------------- token never appears in the argv ----


def test_token_never_appears_in_any_subprocess_argv(data_repo, monkeypatch):
    """Important #3. The token (and its base64 Basic form) must not be an
    argv element of ANY git invocation -- argv is world-readable via
    /proc/<pid>/cmdline and ``ps -ef`` for the lifetime of the push. It is
    passed through the environment instead.

    Asserted positionally-agnostically: any argv element containing the
    secret fails, not just the one position the old test happened to look at.
    """
    import base64

    project, tracker_file, bare = data_repo
    secret = "ghp_sekrit_do_not_leak"
    basic = base64.b64encode(f"x-access-token:{secret}".encode()).decode()
    monkeypatch.setenv("GITHUB_TOKEN", secret)
    dirty(tracker_file, vigor="4")

    seen = []
    real_run = subprocess.run

    def recording_run(cmd, *a, **k):
        seen.append((list(cmd), k.get("env")))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(breeding_core.subprocess, "run", recording_run)

    breeding_core.push_to_github(project, REPO, False)

    assert seen
    for cmd, _env in seen:
        for part in cmd:
            assert secret not in str(part), f"token in argv: {cmd}"
            assert basic not in str(part), f"encoded token in argv: {cmd}"
            assert "extraHeader" not in str(part), f"header in argv: {cmd}"

    # ... and it still actually authenticated the way we intended: the header
    # was handed to git through the environment.
    pushes = [
        (cmd, env) for cmd, env in seen if "push" in cmd and env is not None
    ]
    assert pushes, "the push must carry an explicit env"
    _cmd, env = pushes[0]
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {basic}"
    assert git(bare, "rev-parse", "refs/heads/main").strip() == git(
        project, "rev-parse", "HEAD"
    ).strip()


def test_git_config_env_vars_are_actually_honoured_by_git(data_repo, monkeypatch):
    """Empirical check that the env-var route is a real substitute for
    ``-c http.extraHeader=...`` -- git must read the value back."""
    project, _tracker_file, _bare = data_repo
    out = subprocess.run(
        ["git", "config", "--get", "http.extraHeader"],
        cwd=str(project),
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": "Authorization: Basic sentinel",
        },
    )
    assert out.stdout.strip() == "Authorization: Basic sentinel"
