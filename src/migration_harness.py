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

import hashlib
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Bound at import time, deliberately.
#:
#: The acceptance suite booby-traps `subprocess.run`, `Popen`, `call`,
#: `check_call` and `check_output` for the duration of a migration so the code
#: under test physically cannot reach a git remote, Drive or Discord. This
#: module's git calls are *verification scaffolding*, not code under test, and
#: must keep working through that trap — otherwise the strongest live-dir
#: check (nested repo HEAD/status) could not be armed at the same time as the
#: strongest side-effect check.
#:
#: `subprocess.run` is not enough on its own: it resolves `Popen` from the
#: module globals at call time, so a trapped `Popen` still fires through a
#: saved `run`. The real `Popen` is captured and driven directly.
#:
#: This costs no coverage: `tracker_migration` is statically proven to import
#: no subprocess, socket, urllib or http at all, so the trap is what guards
#: the migration and this alias only guards the observer.
_Popen = subprocess.Popen
_CalledProcessError = subprocess.CalledProcessError
_PIPE = subprocess.PIPE


def _run(argv, *, cwd, check=True, text=True):
    """`subprocess.run(capture_output=True)` built on the import-time `Popen`."""
    with _Popen(argv, cwd=cwd, stdout=_PIPE, stderr=_PIPE, text=text) as proc:
        stdout, stderr = proc.communicate()
        code = proc.returncode
    if check and code:
        raise _CalledProcessError(code, argv, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(argv, code, stdout, stderr)

__all__ = [
    "ProjectSpec",
    "ROUTING_FLAGS",
    "ROUTING_OPTIONAL_SEPARATORS",
    "ROUTING_SEPARATORS",
    "declared_separators",
    "describe_baseline_dirt",
    "fingerprint_tree",
    "git_head_sha",
    "git_repo_state",
    "git_status_snapshot",
    "is_volatile_path",
    "live_tree_state",
    "nested_repo_state",
    "routing_failures",
    "unexpected_git_changes",
    "unexpected_repo_changes",
]


# --------------------------------------------------------------------------
# plant-ID routing: does the MIGRATED pattern still route, as production runs it
# --------------------------------------------------------------------------

#: The flags production compiles routing patterns with.
#: `breeding_core._compile_prefixes` passes `re.IGNORECASE`, matching
#: `extract_plant_ids_single`'s `re.findall(..., re.IGNORECASE)`. Compiling
#: with no flags here would test a STRICTER matcher than the one that runs:
#: a pattern that routes `PC01` but not `pc01` would read as clean while
#: production silently accepted (or, for a `(?-i:)`-scoped pattern, dropped)
#: half the real Discord traffic. The parity is asserted in
#: `tests/test_routing_checks.py` against production's source.
ROUTING_FLAGS = re.IGNORECASE

#: Every separator spelling a real pattern's separator class must accept.
#: Each live pattern carries one (`[\s\-]?`, `\s*[-#]?\s*`), and people type
#: all three spellings into Discord. Probing only the bare `PC01` form leaves
#: the class unexercised, so a migration that ate it keeps every other
#: assertion green while `PC 01` and `PC-01` stop routing.
ROUTING_SEPARATORS = ("", " ", "-")

#: Separators a pattern must route *if its own separator class declares them*.
#:
#: `#` cannot join `ROUTING_SEPARATORS`: that set is what EVERY pattern must
#: accept, and paloma-coma's live `[\s\-]?` legitimately does not route
#: `PC#01` — demanding it would fail a healthy project. But kibungan's live
#: class is `[-#]?`: it advertises `#`, people type `PK#7`, and the
#: universal-only probe set meant no `#` was ever sent through any pattern, so
#: a migration that kept the class shape while breaking that one branch stayed
#: green. The probe set is therefore per-pattern — the universal three plus
#: whatever the pattern itself declares — via `declared_separators`.
ROUTING_OPTIONAL_SEPARATORS = ("#",)

#: Characters inside a `[...]` class that are separator constructs, not part
#: of the ID. Matched against the class body of the pattern's separator class.
_SEPARATOR_CLASS = re.compile(r"\[([^\]]*)\]\??")


def declared_separators(pattern: str) -> tuple[str, ...]:
    """`ROUTING_SEPARATORS` plus every optional separator `pattern` declares.

    Deliberately syntactic — it reads the pattern's own character classes —
    because the question is "what does this pattern claim to accept", and the
    answer has to be derivable from a pattern read out of migrated markdown.

    Note the limit this has on its own: a migration that NARROWS `[-#]?` to
    `[-]?` also erases the evidence that `#` was expected, so a self-derived
    set shrinks with the bug. Callers that hold a migrated pattern against its
    source pass the SOURCE's separators explicitly to `routing_failures`.
    """
    declared = list(ROUTING_SEPARATORS)
    for body in _SEPARATOR_CLASS.findall(pattern):
        for sep in ROUTING_OPTIONAL_SEPARATORS:
            if sep in body and sep not in declared:
                declared.append(sep)
    return tuple(declared)


def _representative_ids(prefix: str) -> list[str]:
    """Plausible IDs for `prefix` when that project's real roster is unavailable.

    Used only for the cross-project collision probe, where the question is
    "would a message naming another cross's plant be swallowed by THIS
    project's pattern" — for which the sibling's declared prefix is enough,
    and which must keep working on a machine that has only some trackers.
    """
    return [f"{prefix}{n:02d}" for n in (1, 7, 12)]


def routing_failures(
    prefixes: Sequence[Mapping[str, str]],
    plant_ids: Sequence[str],
    other_projects: Sequence[tuple[str, Sequence[Mapping[str, str]]]] = (),
    separators: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Every way `prefixes` fails to route `plant_ids` the way production does.

    Returns a list of human-readable failures; empty means the migrated
    patterns route exactly as they must. One implementation, shared by the
    contract suite and the out-of-band verifier, so the two cannot drift.

    Checked, per prefix entry:

    * it routes exactly its own family's real IDs and no other family's;
    * it routes each of those IDs inside free text, in every separator
      spelling of `ROUTING_SEPARATORS`, returning the right captured number
      (the monitor uses that group to pick the plant);
    * it does NOT match with an extra leading character, which is what proves
      the boundary/lookbehind construct survived the migration.

    Across entries: every real ID is routed by exactly one pattern.

    Across projects: no pattern of this project matches another project's IDs,
    and no other project's pattern matches this project's IDs. Production
    routes one Discord message against the whole registry, so a pattern
    widened during migration to swallow a sibling family is a live break that
    no single-project check can see — both projects pass in isolation while
    one silently steals the other's notes.

    Everything compiles with `ROUTING_FLAGS`, i.e. exactly what
    `breeding_core._compile_prefixes` uses.
    """
    failures: list[str] = []
    if not prefixes:
        return ["no routing patterns declared -- no message could ever route"]
    if not plant_ids:
        return ["no real plant IDs -- the routing check would be vacuous"]

    ids = sorted(plant_ids)
    routed_by: dict[str, list[str]] = {i: [] for i in ids}

    for entry in prefixes:
        prefix = entry["prefix"]
        try:
            compiled = re.compile(entry["pattern"], ROUTING_FLAGS)
        except re.error as exc:
            failures.append(f"{prefix}: pattern does not compile: {exc}")
            continue

        own = [i for i in ids if i.upper().startswith(prefix.upper())]
        matched = [i for i in ids if compiled.search(i)]
        if not own:
            failures.append(f"{prefix}: routes no real ID in this project")
        if matched != own:
            failures.append(f"{prefix}: routes {matched}, expected {own}")
        for i in matched:
            routed_by[i].append(prefix)

        # The universal three, plus whatever THIS pattern declares -- unless
        # the caller supplied the source pattern's set, which is the only way
        # to catch a class NARROWED away from a separator it used to accept.
        if separators is not None and prefix in separators:
            probe_separators = tuple(separators[prefix])
        else:
            probe_separators = declared_separators(entry["pattern"])

        for plant_id in own:
            digits = re.search(r"(\d+)$", plant_id).group(1)
            body = plant_id[: -len(digits)]
            for sep in probe_separators:
                canonical = f"{body}{sep}{digits}"
                # Both cases, because production compiles with IGNORECASE and
                # people type both: a pattern that re-locked its own case (a
                # scoped `(?-i:)`, a lost inline `(?i)`) routes the canonical
                # spelling perfectly and drops the other half of the traffic.
                for spelling in (canonical, canonical.swapcase()):
                    match = compiled.search(f"checked {spelling} today, looking good")
                    if not match:
                        failures.append(
                            f"{plant_id}: not routed in free text as "
                            f"{spelling!r} (separator {sep!r})"
                        )
                    elif int(match.group(1)) != int(digits):
                        failures.append(
                            f"{plant_id}: routed as {spelling!r} but captured "
                            f"{match.group(1)!r}, expected {digits!r}"
                        )
            if compiled.search(f"X{plant_id}"):
                failures.append(
                    f"{plant_id}: matches with a leading char (boundary lost)"
                )

    for plant_id, hits in routed_by.items():
        if len(hits) != 1:
            failures.append(f"{plant_id}: routed by {hits}, expected exactly one")

    own_prefixes = {e["prefix"].upper() for e in prefixes}
    for slug, sibling_prefixes in other_projects:
        for sibling in sibling_prefixes:
            sibling_prefix = sibling["prefix"]
            if sibling_prefix.upper() in own_prefixes:
                # NOT a reason to skip: this is the WORST collision there is.
                # `breeding_core`'s registry validator raises on two projects
                # declaring the same prefix (case-insensitively) precisely
                # because one message would route to two crosses -- production
                # refuses to start. Treating it as `continue` meant the one
                # state production rejects outright was the only collision the
                # probe could never report.
                failures.append(
                    f"duplicate prefix: {slug} also declares "
                    f"{sibling_prefix!r} -- production's registry validator "
                    f"rejects this outright (one message would route to two "
                    f"crosses)"
                )
                continue
            try:
                sibling_compiled = re.compile(sibling["pattern"], ROUTING_FLAGS)
            except re.error:
                continue  # the sibling project's own check owns that failure
            stolen = [i for i in ids if sibling_compiled.search(i)]
            if stolen:
                failures.append(
                    f"cross-project collision: {slug}'s {sibling_prefix!r} "
                    f"pattern also routes this project's {stolen}"
                )
            sibling_ids = _representative_ids(sibling_prefix)
            for entry in prefixes:
                if entry["prefix"].upper() == sibling_prefix.upper():
                    continue
                try:
                    compiled = re.compile(entry["pattern"], ROUTING_FLAGS)
                except re.error:
                    continue  # already reported above
                swallowed = [i for i in sibling_ids if compiled.search(i)]
                if swallowed:
                    failures.append(
                        f"cross-project collision: this project's "
                        f"{entry['prefix']!r} pattern also routes {slug}'s "
                        f"{swallowed}"
                    )

    return failures


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
    out = _run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=str(repo),
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
# git: the full repo state (HEAD + status codes + content digests)
# --------------------------------------------------------------------------
#
# `git_status_snapshot` + `unexpected_git_changes` prove "this invocation
# changed nothing", which is strictly weaker than what the gate claims. Three
# gaps survive a pure same-invocation code diff:
#
#   A. The baseline is captured inside the run, so a repo that was ALREADY
#      dirty launders that dirt into the allowance. A stray artefact left by
#      an earlier verifier run is then never reported at all. Whether that
#      dirt is *acceptable* is a judgement call for the caller (a task's own
#      in-flight edits are legitimate; a leaked sandbox file is not), so the
#      harness's job is to make it VISIBLE -- `describe_baseline_dirt` -- and
#      never to decide silently that it is fine.
#   B. A two-character porcelain code is not a content hash. Appending to an
#      already-modified file keeps it at ' M', and to an untracked file at
#      '??', so the code diff is empty while the bytes moved.
#   C. `git commit` mid-run returns porcelain to clean, which is indis-
#      tinguishable from having touched nothing. HEAD is what moves, and only
#      nested repos were ever checked for it.


def git_head_sha(repo: Path) -> str:
    """The current commit sha, or `'<unborn>'` before the first commit.

    An unborn HEAD must not raise: a repo with no commits is a legitimate
    state to take a baseline in, and raising here would push the gate toward
    the fail-open behaviour the rest of this module exists to remove.
    """
    out = _run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=False)
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "<unborn>"


def _digest_path(repo: Path, rel: str) -> str:
    """A content digest for one porcelain path, whatever kind of thing it is.

    Porcelain reports an untracked *directory* as a single `dir/` entry, so a
    digest that only stat'd the named path would miss a file appearing inside
    it. Directories are digested over their whole recursive contents.
    """
    target = repo / rel
    try:
        if target.is_symlink():
            return f"symlink:{target.readlink()}"
        if target.is_dir():
            parts = []
            for child in sorted(target.rglob("*")):
                if child.is_dir():
                    parts.append(f"{child.relative_to(target)}/")
                else:
                    parts.append(
                        f"{child.relative_to(target)}:{_digest_path(repo, str(child.relative_to(repo)))}"
                    )
            return "dir:" + _sha256(("\n".join(parts)).encode("utf-8"))
        return _sha256(target.read_bytes())
    except OSError:
        # Deleted, or unreadable. Both are states worth reporting rather than
        # crashing on; a distinct marker keeps them comparable.
        return "<absent>"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_repo_state(repo: Path) -> dict[str, object]:
    """HEAD sha + porcelain codes + a content digest per non-clean path.

    This is `git_status_snapshot` promoted to the same strength that
    `nested_repo_state` already applied to nested repos, plus the content
    layer neither of them had.

    Raises `subprocess.CalledProcessError` if `repo` is not a git work tree,
    for the same fail-toward-reject reason as `git_status_snapshot`.
    """
    status = git_status_snapshot(repo)
    return {
        "head": git_head_sha(repo),
        "status": status,
        "digests": {path: _digest_path(repo, path) for path in status},
    }


def describe_baseline_dirt(state: dict[str, object]) -> list[str]:
    """Every path already non-clean when the baseline was taken.

    The gate's own allowance, made explicit. A same-invocation diff adopts
    this set silently; surfacing it is what lets a caller assert the stronger
    property ("the tree was clean to begin with") instead of only the weaker
    one ("this run changed nothing").
    """
    status: dict[str, str] = state["status"]  # type: ignore[assignment]
    return [f"{path}: '{code}'" for path, code in sorted(status.items())]


def unexpected_repo_changes(
    before: dict[str, object], after: dict[str, object]
) -> list[str]:
    """Every way the repo moved between two `git_repo_state` calls.

    Reports a HEAD move, a porcelain code change, and -- the part a code-only
    diff cannot see -- a content change to a path that was already dirty at
    baseline and stayed at the same code.
    """
    changes: list[str] = []
    if before["head"] != after["head"]:
        changes.append(f"HEAD: {before['head']} -> {after['head']}")

    before_status: dict[str, str] = before["status"]  # type: ignore[assignment]
    after_status: dict[str, str] = after["status"]  # type: ignore[assignment]
    changes.extend(unexpected_git_changes(before_status, after_status))

    before_digests: dict[str, str] = before["digests"]  # type: ignore[assignment]
    after_digests: dict[str, str] = after["digests"]  # type: ignore[assignment]
    for path in sorted(set(before_digests) & set(after_digests)):
        if before_status.get(path) != after_status.get(path):
            continue  # already reported as a code transition
        if before_digests[path] != after_digests[path]:
            changes.append(
                f"{path}: content changed while its porcelain code stayed "
                f"'{after_status.get(path)}' "
                f"({before_digests[path][:12]} -> {after_digests[path][:12]})"
            )
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
        head = _run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(work_tree),
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
