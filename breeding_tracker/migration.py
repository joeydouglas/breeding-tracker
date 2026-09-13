"""Template-field-addition and cross-repo migration runner (Task 1.3).

Two responsibilities, kept in one module because the second is built
directly on the first:

* :func:`apply_new_fields` — add any field present in a template's schema
  but missing from one target markdown file. Never overwrites an existing
  value; never removes a field the target has that the template doesn't
  (a field's *removal* from a template is purely a frontend rendering
  concern — see the plan's "Template propagation" section). Idempotent: a
  second call against an already-current file changes nothing and reports
  ``changed=False``.
* :func:`run_migration_across_repos` — apply the above to every repo listed
  in a registry, committing and pushing each repo that actually changed,
  tracking per-repo success/failure in a small JSON state file so the run is
  safely resumable: a repo already migrated to the current template version
  is skipped, a repo that failed is retried, and repos that already
  succeeded are never re-touched by a retry of a *different* repo.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import plant_markdown
import project_markdown

__all__ = [
    "MigrationResult",
    "MigrationReport",
    "RepoMigrationError",
    "apply_new_fields",
    "run_migration_across_repos",
]


class RepoMigrationError(Exception):
    """One repo's migration failed, carrying what it had already touched.

    The failure report used to hardcode ``added_fields={}``, discarding the
    information about which files/fields this run had actually rewritten
    before the failure -- exactly the information a human needs to work out
    what state the repo was left in. Raising this instead keeps the partial
    result attached to the failure.
    """

    def __init__(self, message: str, added_fields: dict[str, list[str]] | None = None):
        super().__init__(message)
        self.added_fields = added_fields or {}


class MigrationResult:
    """Outcome of applying one template to one target file."""

    def __init__(self, added_fields: list[str], changed: bool):
        self.added_fields = added_fields
        self.changed = changed

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"MigrationResult(added_fields={self.added_fields!r}, "
            f"changed={self.changed!r})"
        )


class MigrationReport:
    """Per-repo outcome of one :func:`run_migration_across_repos` call."""

    def __init__(self) -> None:
        self.repos: dict[str, dict[str, Any]] = {}

    @property
    def successful(self) -> list[str]:
        return [n for n, info in self.repos.items() if info["status"] == "success"]

    @property
    def failed(self) -> list[str]:
        return [n for n, info in self.repos.items() if info["status"] == "failed"]

    @property
    def skipped(self) -> list[str]:
        return [n for n, info in self.repos.items() if info["status"] == "skipped"]


def _module_for(path: str | Path) -> Any:
    """Project files are always named ``project.md``; everything else is a plant."""
    return project_markdown if Path(path).name == "project.md" else plant_markdown


def apply_new_fields(
    template_path: str | Path, target_path: str | Path
) -> MigrationResult:
    """Add fields present in ``template_path``'s schema but missing from ``target_path``.

    Reads the file once WITHOUT a schema to learn exactly which keys are
    physically present (schema-driven defaulting must not be mistaken for a
    field the file already has). If nothing is missing, the file is left
    completely untouched (not even rewritten byte-identically) so migration
    runs never produce noise commits. Otherwise the file is re-read WITH the
    schema (which type-coerces present values and fills in the newly-missing
    ones with their declared defaults) and written back once.
    """
    module = _module_for(target_path)
    schema = module.load_schema(template_path)
    body_field = "observation_log" if module is plant_markdown else "body"

    if module is plant_markdown:
        raw_present = module.read_plant(target_path)
    else:
        raw_present = module.read_project(target_path)

    added = [field for field in schema if field != body_field and field not in raw_present]
    if not added:
        return MigrationResult(added_fields=[], changed=False)

    if module is plant_markdown:
        merged = module.read_plant(target_path, schema=schema)
        module.write_plant(target_path, merged, schema=schema)
    else:
        merged = module.read_project(target_path, schema=schema)
        module.write_project(target_path, merged, schema=schema)

    return MigrationResult(added_fields=added, changed=True)


def _template_version(project_template: str | Path, plant_template: str | Path) -> str:
    """A stable fingerprint of both templates, used to detect 'already migrated'."""
    digest = hashlib.sha256()
    digest.update(Path(project_template).read_bytes())
    digest.update(Path(plant_template).read_bytes())
    return digest.hexdigest()


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )


def _has_origin(repo_path: Path) -> bool:
    """True if this clone has an ``origin`` remote to push to at all."""
    result = subprocess.run(
        ["git", "remote"],
        cwd=str(repo_path),
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )
    return "origin" in result.stdout.split()


def _remote_sha(repo_path: Path, branch: str) -> str | None:
    """The sha ``origin`` currently has for ``branch``, or None if absent.

    Raises (via ``check=True``) if the remote is unreachable -- that is a
    genuine migration failure for this repo, not an "already pushed" answer.
    """
    result = _git(["ls-remote", "origin", f"refs/heads/{branch}"], repo_path)
    line = result.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def _managed_paths(repo_path: Path) -> list[str]:
    """Every repo-relative path this migration is allowed to touch.

    Used for the post-run cleanliness check: "the local file already matches
    the template" must never be conflated with "this repo's edits were
    committed". A file left dirty here means a previous run rewrote it and
    never got it committed, so the migration is NOT done.
    """
    paths: list[str] = []
    if (repo_path / "project.md").exists():
        paths.append("project.md")
    plants_dir = repo_path / "plants"
    if plants_dir.is_dir():
        paths.extend(f"plants/{p.name}" for p in sorted(plants_dir.glob("*.md")))
    return paths


def _porcelain_status(repo_path: Path, paths: Sequence[str]) -> str:
    """``git status --porcelain`` restricted to ``paths`` (empty == clean).

    Returned VERBATIM -- deliberately not ``.strip()``ed. Porcelain v1 is a
    fixed-width format: two status characters (XY) then a space then the
    path, so an unstaged entry legitimately begins with a space
    (``" M project.md"``). Stripping the output would eat that leading
    space and shift every subsequent column, so :func:`_dirty_paths` would
    slice the first character off the filename. Callers that want a tidy
    string for a human-facing message strip it themselves.
    """
    if not paths:
        return ""
    result = _git(["status", "--porcelain", "--", *paths], repo_path)
    return result.stdout


def _dirty_paths(porcelain: str) -> list[str]:
    """Repo-relative paths named by ``git status --porcelain`` output.

    ``porcelain`` must be the RAW output (see :func:`_porcelain_status`).
    The path starts at a fixed column 3, after the two XY status characters
    and their separating space, for every shape: staged (``"M  path"``),
    unstaged (``" M path"``) and untracked (``"?? path"``). Renames are
    reported as ``"R  old -> new"``; only the new path exists on disk, so
    that is the one to stage.
    """
    paths: set[str] = set()
    for raw_line in porcelain.split("\n"):
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path.strip('"'))
    return sorted(paths)


def _rollback(repo_path: Path, paths: Sequence[str]) -> None:
    """Best-effort restore of ``paths`` to HEAD after a failed migration.

    Without this, every failure path left half-applied edits dirty in the
    working tree: the next run (or a human/data-api's ``git pull``) collides
    with them, and the very next ``apply_new_fields`` sees a file that
    already matches the template and reports nothing to do. Best-effort by
    design -- a rollback that itself fails must not mask the original
    failure being reported.
    """
    for relative_path in paths:
        for args in (
            ["reset", "-q", "HEAD", "--", relative_path],
            ["checkout", "--", relative_path],
        ):
            try:
                _git(args, repo_path)
            except Exception:  # noqa: BLE001 - never mask the real failure
                pass


def _migrate_one_repo(
    project_template: str | Path, plant_template: str | Path, repo_path: Path
) -> dict[str, list[str]]:
    """Apply both templates to one repo, rolling back on any failure.

    Wraps :func:`_migrate_one_repo_unguarded` so that a failure anywhere in
    the sequence (a) reverts the migration's own half-applied edits and
    (b) reports which paths/fields had been touched before it failed.
    """
    touched: dict[str, list[str]] = {}
    try:
        return _migrate_one_repo_unguarded(
            project_template, plant_template, repo_path, touched
        )
    except Exception as exc:  # noqa: BLE001 - re-raised, enriched, below
        if repo_path.is_dir():
            _rollback(repo_path, sorted(touched))
        raise RepoMigrationError(str(exc) or exc.__class__.__name__, touched) from exc


def _migrate_one_repo_unguarded(
    project_template: str | Path,
    plant_template: str | Path,
    repo_path: Path,
    added_fields: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Apply both templates to one repo's ``project.md`` and ``plants/*.md``.

    Returns a map of ``{relative_path: [added_field, ...]}`` for every file
    that actually changed.

    Push is verified, not assumed. "The local file already matches the
    template" is NOT the same claim as "this repo's committed state reached
    the remote": a previous run can legitimately have applied the fields and
    committed locally, then failed on the push (unreachable remote). On the
    next run ``apply_new_fields`` reports ``changed=False`` for that repo, so
    a naive implementation makes no git call at all, never retries the push,
    and still records success -- permanently stranding the migration commit
    in the local clone. So after the (possibly empty) field-apply, the local
    HEAD is always compared against the remote branch tip and pushed if they
    differ, then re-checked to confirm the push actually landed.
    """
    if not repo_path.is_dir():
        raise FileNotFoundError(f"repo path does not exist: {repo_path}")

    project_file = repo_path / "project.md"
    if project_file.exists():
        result = apply_new_fields(project_template, project_file)
        if result.changed:
            added_fields["project.md"] = result.added_fields

    plants_dir = repo_path / "plants"
    if plants_dir.is_dir():
        for plant_file in sorted(plants_dir.glob("*.md")):
            result = apply_new_fields(plant_template, plant_file)
            if result.changed:
                added_fields[f"plants/{plant_file.name}"] = result.added_fields

    if added_fields:
        # Stage ONLY the files this migration actually rewrote. `git add -A`
        # would sweep every unrelated dirty or untracked file in the working
        # tree (a half-finished hand edit, scratch files, editor droppings)
        # into the migration commit.
        for relative_path in sorted(added_fields):
            _git(["add", "--", relative_path], repo_path)
        _git(
            [
                "commit",
                "-q",
                "-m",
                "chore: migrate to latest template fields",
                "--only",
                "--",
                *sorted(added_fields),
            ],
            repo_path,
        )

    # Commit-stranding guard. If a PREVIOUS run's `git add`/`git commit`
    # failed after apply_new_fields had already rewritten the files, those
    # edits sit uncommitted in the working tree. On this run
    # apply_new_fields reports changed=False (the file already matches the
    # template), so nothing above would commit or push them, and local HEAD
    # still equals the remote tip -- the repo would be recorded as
    # successfully migrated with its edits never committed anywhere. Any
    # dirtiness in the migration-managed paths is therefore a failure
    # requiring a commit+push retry, never a skip-as-already-done.
    managed = _managed_paths(repo_path)
    dirty = _porcelain_status(repo_path, managed)
    if dirty:
        if not added_fields:
            # Recover the stranded edits: commit exactly the managed paths
            # that are dirty, then fall through to the normal push check.
            dirty_paths = _dirty_paths(dirty)
            for relative_path in dirty_paths:
                _git(["add", "--", relative_path], repo_path)
            _git(
                [
                    "commit",
                    "-q",
                    "-m",
                    "chore: migrate to latest template fields",
                    "--only",
                    "--",
                    *dirty_paths,
                ],
                repo_path,
            )
            for relative_path in dirty_paths:
                added_fields.setdefault(relative_path, [])
        still_dirty = _porcelain_status(repo_path, managed)
        if still_dirty:
            raise RuntimeError(
                "migration-managed paths are still uncommitted after the "
                f"commit step -- refusing to record this repo as migrated: "
                f"{still_dirty.strip()}"
            )

    if not _has_origin(repo_path):
        # A local-only clone has nothing to push to; the commit above is the
        # whole migration.
        return added_fields

    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path).stdout.strip()
    if branch == "HEAD":
        # Detached HEAD: `rev-parse --abbrev-ref HEAD` yields the literal
        # string "HEAD", which would previously be used as the push TARGET
        # (`push origin HEAD:refs/heads/HEAD`), creating a garbage branch on
        # the remote while reporting success and never reaching the real
        # branch. There is no correct branch to infer here, so this is a
        # hard failure for this repo.
        raise RuntimeError(
            f"{repo_path} is on a detached HEAD; refusing to push to a "
            "literal refs/heads/HEAD branch"
        )
    local_head = _git(["rev-parse", "HEAD"], repo_path).stdout.strip()

    if _remote_sha(repo_path, branch) == local_head:
        return added_fields  # already on the remote; nothing to push

    _git(["push", "-q", "origin", f"HEAD:refs/heads/{branch}"], repo_path)

    if _remote_sha(repo_path, branch) != local_head:
        raise RuntimeError(
            f"push reported success but {branch} on origin is not at "
            f"{local_head} -- refusing to record this repo as migrated"
        )

    return added_fields


def _load_state(state_path: Path) -> dict:
    """Load the resume state, degrading to an empty state if it's unusable.

    A truncated/corrupt state file (an interrupted write, a bad hand-edit)
    used to raise ``JSONDecodeError`` before the registry loop even started,
    bricking EVERY future run of the migration rather than one repo's.
    Losing the resume record costs at worst some idempotent re-work: every
    step below is safe to repeat. Crashing costs the whole migration.
    """
    if not state_path.exists():
        return {"repos": {}}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {"repos": {}}
    if not isinstance(state, dict) or not isinstance(state.get("repos"), dict):
        return {"repos": {}}
    return state


def _save_state(state_path: Path, state: dict) -> None:
    # The state file's parent may not exist yet (a caller pointing at
    # e.g. ~/.cache/breeding/migration-state.json on a fresh machine).
    # Without this, the FIRST save -- which happens only AFTER a repo has
    # already been migrated and pushed -- raised FileNotFoundError, losing
    # that repo's record and aborting the whole batch.
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_migration_across_repos(
    project_template: str | Path,
    plant_template: str | Path,
    registry: Sequence[Mapping[str, str]],
    state_path: str | Path,
) -> MigrationReport:
    """Apply the current templates to every repo in ``registry``.

    ``registry`` is a sequence of ``{"name": ..., "path": ...}`` entries (a
    "path" is a local clone's working directory — this function does not
    itself clone or pull; that is the caller's/data-api's job). Resumable
    via ``state_path``: a repo already migrated to the current combined
    template fingerprint is skipped without touching disk or git; a repo
    that failed last time is retried on the next call regardless of whether
    the templates changed, while repos that already succeeded at the
    current version are never re-touched by that retry.

    State is persisted after EVERY repo, not once at the end: a mid-run
    crash (Ctrl-C, OOM, reboot) must not throw away the record of repos that
    already migrated and pushed successfully, forcing a restart to redo the
    whole registry from scratch.
    """
    state_path = Path(state_path)
    state = _load_state(state_path)
    version = _template_version(project_template, plant_template)

    report = MigrationReport()

    for index, entry in enumerate(registry):
        # Per-entry validation lives INSIDE the loop's failure handling: a
        # registry entry missing "name"/"path" used to raise a bare KeyError
        # from OUTSIDE the try block, aborting the entire batch over one
        # malformed line of config instead of isolating it to that entry.
        name = entry.get("name") if isinstance(entry, Mapping) else None
        if not isinstance(name, str) or not name:
            name = f"<malformed registry entry #{index}>"
            report.repos[name] = {
                "status": "failed",
                "error": f"registry entry #{index} has no usable 'name': {entry!r}",
                "added_fields": {},
            }
            continue

        raw_path = entry.get("path")
        if not isinstance(raw_path, (str, Path)) or not raw_path:
            error = f"registry entry {name!r} has no usable 'path': {entry!r}"
            state["repos"][name] = {
                "status": "failed",
                "error": error,
                "template_version": None,
                "added_fields": {},
            }
            report.repos[name] = {
                "status": "failed",
                "error": error,
                "added_fields": {},
            }
            _save_state(state_path, state)
            continue

        repo_path = Path(raw_path)
        prior = state["repos"].get(name)

        if (
            prior
            and prior.get("status") == "success"
            and prior.get("template_version") == version
        ):
            report.repos[name] = {
                "status": "skipped",
                "error": None,
                "added_fields": prior.get("added_fields", {}),
            }
            continue

        try:
            added_fields = _migrate_one_repo(project_template, plant_template, repo_path)
        except Exception as exc:  # noqa: BLE001 - one repo's failure must not abort the batch
            # Report what this run actually touched before failing, rather
            # than a hardcoded {} that discards it.
            touched = getattr(exc, "added_fields", {}) or {}
            state["repos"][name] = {
                "status": "failed",
                "error": str(exc),
                "template_version": prior.get("template_version") if prior else None,
                "added_fields": touched,
            }
            report.repos[name] = {
                "status": "failed",
                "error": str(exc),
                "added_fields": touched,
            }
            _save_state(state_path, state)
            continue

        state["repos"][name] = {
            "status": "success",
            "error": None,
            "template_version": version,
            "added_fields": added_fields,
        }
        report.repos[name] = {
            "status": "success",
            "error": None,
            "added_fields": added_fields,
        }
        _save_state(state_path, state)

    _save_state(state_path, state)
    return report
