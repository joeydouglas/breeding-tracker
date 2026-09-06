"""Shared scaffolding for the Task 3.x per-project migration verification.

Task 3.1 and 3.2 each grew their own copy of the same acceptance test module
and the same out-of-band verifier script, differing only in a slug, a plant
count and a field inventory. Four more projects remain. This module holds the
parts that are genuinely identical so a fix lands once instead of six times,
and so the two defects the duplication was about to propagate stay fixed:

**No path is ever whitelisted from the git gate.** The per-project verifiers
decided "no unexpected git changes" by dropping every `git status --porcelain`
line whose text ended with one of a hardcoded list of paths. That list grew by
one entry per project; it forgave a whitelisted path no matter *what* had
happened to it (edited, staged, truncated to zero, deleted); it forgave a file
that was already dirty before the run for reasons unrelated to it; and the
mule-fuel copy additionally carried a blanket `"tools/" not in line` escape
that excused every change anywhere under `tools/`. `git_status_snapshot` +
`unexpected_git_changes` replace it with a before/after baseline diff: the
tree's state at the start of the run *is* the allowance, expressed as data
rather than as a literal list of forgiven paths, and any divergence from it —
including a whitelisted-by-name path, including a baseline-dirty path whose
state merely *changes* — is reported.

**The live-directory fingerprint no longer trips over volatile paths.**
`(size, mtime_ns)` over every path under a live project directory includes
`__pycache__/`, `cache/`, `.pytest_cache/` and the nested `dashboard/.git/`
working repository. Those are rewritten by processes that have nothing to do
with the migration — importing a module writes a `.pyc`, the dashboard
generator refreshes `cache/*.json`, a `git fetch` rewrites `FETCH_HEAD` — so
the check could go red without the migration having touched anything, and a
verification gate that cries wolf gets ignored, which is worse than not having
it. `is_volatile_path` excludes exactly those, and `nested_repo_state` covers
what the exclusion gives up with a *stronger* check than a file mtime: the
nested repo's HEAD sha and porcelain status, which a `git commit`/`git push`
by the migration would move and a `git gc` would not.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ProjectSpec",
    "fingerprint_tree",
    "git_status_snapshot",
    "is_volatile_path",
    "live_tree_state",
    "nested_repo_state",
    "unexpected_git_changes",
]


# --------------------------------------------------------------------------
# git: baseline snapshot + diff (replaces the per-project suffix whitelist)
# --------------------------------------------------------------------------


def git_status_snapshot(repo: Path) -> dict[str, str]:
    """Map every non-clean path in `repo` to its two-character porcelain code.

    Uses `--porcelain -z`, not the plain porcelain form: plain porcelain
    C-quotes and escapes paths containing spaces, quotes or non-ASCII bytes,
    and parsing that by column or by `str.endswith` corrupts the filename.
    ec18b34 already fixed that exact bug once in `migration.py`; the gate that
    polices `migration.py` must not reintroduce it.

    Raises `subprocess.CalledProcessError` if `repo` is not a git work tree.
    Returning an empty dict there would make the gate vacuously green — the
    same fail-toward-accept mode `VerificationReport.verified_something`
    exists to prevent.
    """
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    records = [r for r in out.split("\0") if r]
    snapshot: dict[str, str] = {}
    i = 0
    while i < len(records):
        record = records[i]
        code, path = record[:2], record[3:]
        # Rename/copy entries are followed by a second NUL-terminated record
        # holding the ORIGINAL path. Record the destination; consume both.
        if code[0] in ("R", "C") or code[1] in ("R", "C"):
            i += 1
        snapshot[path] = code
        i += 1
    return snapshot


def unexpected_git_changes(
    before: dict[str, str], after: dict[str, str]
) -> list[str]:
    """Every way `after` diverges from the `before` baseline, as readable lines.

    A path absent from a snapshot is clean, rendered `'  '` on the left and
    `gone` on the right so "it stopped being dirty" (something reverted the
    tree mid-run) is reported too, rather than silently passing.
    """
    changes = []
    for path in sorted(set(before) | set(after)):
        was, now = before.get(path), after.get(path)
        if was == now:
            continue
        left = f"'{was}'" if was is not None else "'  '"
        right = f"'{now}'" if now is not None else "gone"
        changes.append(f"{path}: {left} -> {right}")
    return changes


# --------------------------------------------------------------------------
# volatile-path classification
# --------------------------------------------------------------------------

#: Directory names rewritten by tooling unrelated to the migration.
VOLATILE_DIR_NAMES = frozenset(
    {
        "__pycache__",
        "cache",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        ".git",
    }
)

#: File suffixes and names that are build/OS artefacts, never project data.
VOLATILE_SUFFIXES = (".pyc", ".pyo", ".pyd")
VOLATILE_NAMES = frozenset({".DS_Store", "Thumbs.db"})


def is_volatile_path(rel: Path) -> bool:
    """True if `rel` (relative to a live project dir) is not project data.

    Deliberately a *closed* list rather than a heuristic: an over-broad
    classifier that swallowed `tracker.json` would leave the fingerprint
    green no matter what the migration did, so the exclusion is paired in the
    tests with an explicit inventory of the real data-bearing paths that must
    keep being fingerprinted.
    """
    parts = rel.parts
    if any(part in VOLATILE_DIR_NAMES for part in parts):
        return True
    name = rel.name
    return (
        name in VOLATILE_NAMES
        or name.endswith(VOLATILE_SUFFIXES)
        or name.startswith(".tmp-")
    )


# --------------------------------------------------------------------------
# fingerprinting a live project tree
# --------------------------------------------------------------------------


def fingerprint_tree(root: Path) -> dict[str, object]:
    """`(size, mtime_ns)` for every data file under `root`, volatile paths out.

    Directories are recorded by presence only, never by mtime: a directory's
    mtime bumps whenever a child is created, so fingerprinting it would let
    churn inside an excluded directory leak back in through its parent. A
    stray directory the migration created is still caught, by its key.
    """
    entries: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if is_volatile_path(rel):
            continue
        try:
            stat = path.lstat()
        except OSError:  # pragma: no cover - path vanished mid-walk
            continue
        key = str(rel)
        if path.is_dir() and not path.is_symlink():
            entries[key] = "dir"
        else:
            entries[key] = (stat.st_size, stat.st_mtime_ns)
    return entries


def nested_repo_state(root: Path) -> dict[str, tuple[str, dict[str, str]]]:
    """HEAD sha + porcelain status for every git work tree nested under `root`.

    This is what replaces mtime-fingerprinting `dashboard/.git/`, and it is
    strictly stronger for the property under test: a commit or a push by the
    migration moves HEAD, and a stray write to the working tree moves the
    status, while `git gc`/`git fetch` rewriting loose objects moves neither.
    """
    state: dict[str, tuple[str, dict[str, str]]] = {}
    for git_dir in sorted(root.rglob(".git")):
        work_tree = git_dir.parent
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(work_tree),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        state[str(work_tree.relative_to(root))] = (
            head,
            git_status_snapshot(work_tree),
        )
    return state


def live_tree_state(root: Path) -> dict[str, object]:
    """The full "did anything move?" state of a live project directory."""
    return {"files": fingerprint_tree(root), "repos": nested_repo_state(root)}


# --------------------------------------------------------------------------
# the per-project contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectSpec:
    """Everything that actually differs between two Task 3.x project migrations.

    The acceptance suite and the out-of-band verifier are otherwise identical
    across projects; expressing the difference as data means Task 3.3 adds one
    of these instead of copying ~1200 lines of test and tool, and means a fix
    to the shared logic lands on every project at once.
    """

    slug: str
    plant_count: int
    project_keys: frozenset[str]
    plant_keys: frozenset[str]
    #: Plant fields the template legitimately materialises, per record.
    expected_plant_defaults: frozenset[str] = frozenset({"corrected_reading"})
    #: Project fields absent from this tracker and filled from the template.
    expected_project_defaults: frozenset[str] = frozenset()
    #: Plant IDs known to be missing required fields (e.g. mule-fuel's MG07).
    incomplete_plants: frozenset[str] = frozenset()
    notes: str = ""
    _extra: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def live_dir(self) -> Path:
        return Path.home() / ".hermes" / "breeding" / self.slug

    @property
    def tracker(self) -> Path:
        return self.live_dir / "tracker.json"

    @property
    def registry(self) -> Path:
        return (
            Path.home()
            / ".hermes"
            / "breeding"
            / "_shared"
            / "breeding-meta"
            / "registry.json"
        )

    @property
    def expected_records(self) -> int:
        """One project record plus one per plant."""
        return 1 + self.plant_count

    def expected_fields(self, source: dict) -> int:
        """Field values `verify_migration` must compare for this project.

        Re-derived from the tracker rather than hardcoded, and including the
        +2 registry-sourced routing fields (`auto_create`,
        `plant_id_prefixes`) that exist in no tracker.
        """
        plant_fields = sum(len(p) for p in source["plants"])
        project_fields = len([k for k in source if k != "plants"])
        return plant_fields + project_fields + 2
