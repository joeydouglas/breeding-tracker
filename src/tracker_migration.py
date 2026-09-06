"""One-shot ``tracker.json`` -> markdown migration for a single project (Task 3.x).

This is the Phase 3 data migration. It is deliberately **pure filesystem
work**: it reads one ``tracker.json`` plus ``registry.json``, and writes a
tree of markdown files into a caller-supplied output directory using Phase
1's writers. It performs **no git, network, Discord or Drive operation of any
kind** — those are separate, later steps that a human runs deliberately. See
:func:`assert_sandbox_destination` for the guard that keeps a sandbox run
from accidentally landing in a real repo.

Three things the Task 3.0 field inventory flagged, all handled here:

* ``auto_create`` and ``plant_id_prefixes`` do **not** exist in any
  ``tracker.json`` — they live in ``registry.json``. Sourcing them from the
  tracker would silently take the template defaults (``false`` / ``[]``) and
  break ID routing, so :func:`build_project_record` takes them from the
  registry entry and refuses to run without one (§8 of the inventory).
* ``plants`` is a JSON **array**, not a dict (§9.2).
* Real plants may be missing template fields (``MG07`` has no
  ``photo_count``/``photos_drive_url``), so missing fields are materialised
  from the template's declared defaults rather than assumed present (§9.3).

"Zero data loss" is not asserted, it is *verified*: :func:`verify_migration`
re-reads every written file and compares it back against the original JSON,
returning a structured report that must be empty for the migration to be
accepted.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import plant_markdown
import project_markdown

__all__ = [
    "SandboxViolationError",
    "TrackerMigrationError",
    "MigrationSummary",
    "VerificationReport",
    "assert_sandbox_destination",
    "load_registry_entry",
    "build_project_record",
    "build_plant_record",
    "file_md5",
    "migrate_tracker",
    "verify_migration",
]

#: Frontmatter/body field names that are stored as the markdown body.
PLANT_BODY_FIELD = "observation_log"
PROJECT_BODY_FIELD = "body"

#: The tracker key holding the plant array; never a project frontmatter field.
PLANTS_KEY = "plants"


class TrackerMigrationError(Exception):
    """The migration cannot be performed as requested."""


class SandboxViolationError(TrackerMigrationError):
    """The requested destination is not a safe, side-effect-free sandbox."""


class MigrationSummary:
    """What one :func:`migrate_tracker` call produced."""

    def __init__(
        self,
        slug: str,
        output_dir: Path,
        project_file: Path,
        plant_files: list[Path],
        defaulted_fields: dict[str, list[str]],
        tracker_md5_before: str,
        tracker_md5_after: str,
    ) -> None:
        self.slug = slug
        self.output_dir = output_dir
        self.project_file = project_file
        self.plant_files = plant_files
        #: {record -> [field, ...]} materialised from a template default
        #: because the source JSON did not carry the field at all.
        self.defaulted_fields = defaulted_fields
        self.tracker_md5_before = tracker_md5_before
        self.tracker_md5_after = tracker_md5_after

    @property
    def plant_count(self) -> int:
        return len(self.plant_files)

    @property
    def tracker_unchanged(self) -> bool:
        return self.tracker_md5_before == self.tracker_md5_after

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"MigrationSummary(slug={self.slug!r}, plants={self.plant_count}, "
            f"tracker_unchanged={self.tracker_unchanged})"
        )


class VerificationReport:
    """Structured result of re-reading a migration and diffing it back.

    ``ok`` is True only when nothing at all was lost or altered. Every
    container is keyed by record name (``"project"`` or a plant id).
    """

    def __init__(self) -> None:
        self.missing_records: list[str] = []
        self.extra_records: list[str] = []
        self.lost_fields: dict[str, list[str]] = {}
        self.changed_fields: dict[str, list[dict[str, Any]]] = {}
        self.plant_count_source: int = 0
        self.plant_count_migrated: int = 0

    @property
    def plant_count_matches(self) -> bool:
        return self.plant_count_source == self.plant_count_migrated

    @property
    def ok(self) -> bool:
        return (
            not self.missing_records
            and not self.extra_records
            and not self.lost_fields
            and not self.changed_fields
            and self.plant_count_matches
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "plant_count_source": self.plant_count_source,
            "plant_count_migrated": self.plant_count_migrated,
            "plant_count_matches": self.plant_count_matches,
            "missing_records": self.missing_records,
            "extra_records": self.extra_records,
            "lost_fields": self.lost_fields,
            "changed_fields": self.changed_fields,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"VerificationReport(ok={self.ok}, {self.as_dict()!r})"


# ------------------------------------------------------------ sandboxing ----


def _enclosing_git_repo(path: Path) -> Path | None:
    """The nearest ancestor (or ``path`` itself) containing a ``.git`` entry."""
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def assert_sandbox_destination(
    output_dir: str | Path, *, allow_git_repo: bool = False
) -> Path:
    """Refuse any destination where this migration could cause a real effect.

    Task 3.x's acceptance criteria require the migration to be *sandbox-only
    first*, and a hash check on ``tracker.json`` alone does not prove that.
    The concrete danger is writing into a real project clone: nothing here
    pushes, but files landing in a git work tree get swept into somebody
    else's later ``git add``/push, which is a real side effect caused by this
    task. So:

    * the destination must not already exist as a non-empty directory —
      a migration must never merge into or overwrite an existing tree;
    * the destination must not live inside a git work tree unless the caller
      explicitly opts in (``allow_git_repo=True``, for the eventual real run);
    * the destination must not be inside ``~/.hermes/breeding/<project>``,
      i.e. the live data directories the ingestion pipeline reads and writes.

    Returns the resolved destination path.
    """
    target = Path(output_dir).expanduser().resolve()

    if target.exists():
        if not target.is_dir():
            raise SandboxViolationError(f"destination is not a directory: {target}")
        if any(target.iterdir()):
            raise SandboxViolationError(
                f"destination already exists and is not empty: {target} -- "
                "a migration must never merge into an existing tree"
            )

    if not allow_git_repo:
        repo = _enclosing_git_repo(target)
        if repo is not None:
            raise SandboxViolationError(
                f"destination {target} is inside the git work tree at {repo}; "
                "a sandbox migration must not place files where a later "
                "commit/push could sweep them up (pass allow_git_repo=True "
                "for a deliberate real run)"
            )

    live_root = (Path.home() / ".hermes" / "breeding").resolve()
    if target == live_root or live_root in target.parents:
        raise SandboxViolationError(
            f"destination {target} is inside the live breeding data tree "
            f"{live_root}; sandbox migrations must write elsewhere"
        )

    return target


# ---------------------------------------------------------------- inputs ----


def file_md5(path: str | Path) -> str:
    """Hex md5 of a file's bytes (used to prove ``tracker.json`` is untouched)."""
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> Any:
    # Explicitly read-only: opened "r", never reopened for writing anywhere
    # in this module.
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_registry_entry(registry_path: str | Path, slug: str) -> dict:
    """The ``registry.json`` entry for ``slug``.

    Raises rather than defaulting: ``auto_create``/``plant_id_prefixes`` are
    only obtainable here (Task 3.0 §8), so a missing entry must abort the
    migration instead of silently producing a project.md with template
    defaults that break ID routing and auto-create.
    """
    registry = _read_json(registry_path)
    projects = registry.get("projects") if isinstance(registry, Mapping) else None
    if not isinstance(projects, list):
        raise TrackerMigrationError(
            f"{registry_path} has no 'projects' list; cannot source "
            "auto_create/plant_id_prefixes"
        )
    for entry in projects:
        if isinstance(entry, Mapping) and entry.get("slug") == slug:
            return dict(entry)
    raise TrackerMigrationError(
        f"no registry entry for slug {slug!r} in {registry_path}; refusing to "
        "migrate with template defaults for auto_create/plant_id_prefixes"
    )


# --------------------------------------------------------------- records ----


def _materialize(schema: Mapping[str, Mapping[str, Any]], field: str) -> Any:
    default = schema[field].get("default")
    return copy.deepcopy(default) if isinstance(default, (list, dict)) else default


def _apply_defaults(
    record: dict, schema: Mapping[str, Mapping[str, Any]], body_field: str
) -> list[str]:
    """Fill schema fields absent from ``record``; return the names filled in."""
    defaulted = []
    for field in schema:
        if field == body_field:
            continue
        if field not in record:
            record[field] = _materialize(schema, field)
            defaulted.append(field)
    return defaulted


def build_project_record(
    tracker: Mapping[str, Any],
    registry_entry: Mapping[str, Any],
    schema: Mapping[str, Mapping[str, Any]],
) -> tuple[dict, list[str]]:
    """Project frontmatter values from the tracker + registry.

    ``plants`` is intentionally dropped (it becomes ``plants/<ID>.md`` files,
    per Task 3.0 §6). ``auto_create`` and ``plant_id_prefixes`` come from the
    registry entry and OVERRIDE anything of that name in the tracker, because
    the registry is the routing source of truth.
    """
    record = {k: v for k, v in tracker.items() if k != PLANTS_KEY}

    for field in ("auto_create", "plant_id_prefixes"):
        if field not in registry_entry:
            raise TrackerMigrationError(
                f"registry entry for {registry_entry.get('slug')!r} is missing "
                f"{field!r}; refusing to fall back to the template default"
            )
        record[field] = copy.deepcopy(registry_entry[field])

    defaulted = _apply_defaults(record, schema, PROJECT_BODY_FIELD)
    record.setdefault(PROJECT_BODY_FIELD, "")
    return record, defaulted


def build_plant_record(
    plant: Mapping[str, Any], schema: Mapping[str, Mapping[str, Any]]
) -> tuple[dict, list[str]]:
    """One plant's values, with template defaults for anything absent."""
    record = dict(plant)
    defaulted = _apply_defaults(record, schema, PLANT_BODY_FIELD)
    record.setdefault(PLANT_BODY_FIELD, "")
    return record, defaulted


def _plants_of(tracker: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """``plants`` as a list — an array in all 6 real trackers (§9.2)."""
    plants = tracker.get(PLANTS_KEY, [])
    if isinstance(plants, Mapping):
        plants = list(plants.values())
    if not isinstance(plants, list):
        raise TrackerMigrationError(
            f"'plants' must be an array or object, got {type(plants).__name__}"
        )
    return plants


def _plant_id(plant: Mapping[str, Any], index: int) -> str:
    plant_id = plant.get("id")
    if not isinstance(plant_id, str) or not plant_id.strip():
        raise TrackerMigrationError(f"plant #{index} has no usable 'id': {plant!r}")
    if "/" in plant_id or "\\" in plant_id or plant_id in (".", ".."):
        raise TrackerMigrationError(
            f"plant #{index} has an id that is unsafe as a filename: {plant_id!r}"
        )
    return plant_id


# --------------------------------------------------------------- migrate ----


def migrate_tracker(
    tracker_path: str | Path,
    registry_path: str | Path,
    slug: str,
    output_dir: str | Path,
    project_template: str | Path,
    plant_template: str | Path,
    *,
    allow_git_repo: bool = False,
) -> MigrationSummary:
    """Convert one project's ``tracker.json`` into a markdown tree.

    Writes ``<output_dir>/project.md`` and ``<output_dir>/plants/<ID>.md``.
    ``tracker.json`` is read-only throughout; its md5 is captured before and
    after and reported on the summary so the caller can prove it untouched.
    """
    tracker_path = Path(tracker_path)
    md5_before = file_md5(tracker_path)

    target = assert_sandbox_destination(output_dir, allow_git_repo=allow_git_repo)

    tracker = _read_json(tracker_path)
    if not isinstance(tracker, Mapping):
        raise TrackerMigrationError(
            f"{tracker_path} does not contain a JSON object"
        )
    registry_entry = load_registry_entry(registry_path, slug)

    project_schema = project_markdown.load_schema(project_template)
    plant_schema = plant_markdown.load_schema(plant_template)

    plants = _plants_of(tracker)
    seen: set[str] = set()
    prepared: list[tuple[str, dict, list[str]]] = []
    for index, plant in enumerate(plants):
        if not isinstance(plant, Mapping):
            raise TrackerMigrationError(
                f"plant #{index} is not an object: {plant!r}"
            )
        plant_id = _plant_id(plant, index)
        if plant_id in seen:
            raise TrackerMigrationError(
                f"duplicate plant id {plant_id!r}; refusing to migrate because "
                "one record would silently overwrite the other"
            )
        seen.add(plant_id)
        record, defaulted = build_plant_record(plant, plant_schema)
        prepared.append((plant_id, record, defaulted))

    project_record, project_defaulted = build_project_record(
        tracker, registry_entry, project_schema
    )

    # Everything is validated before the first byte is written, so a bad
    # tracker never leaves a half-written tree behind.
    target.mkdir(parents=True, exist_ok=True)
    plants_dir = target / "plants"
    plants_dir.mkdir(exist_ok=True)

    defaulted_fields: dict[str, list[str]] = {}
    project_file = target / "project.md"
    project_markdown.write_project(project_file, project_record, schema=project_schema)
    if project_defaulted:
        defaulted_fields["project"] = project_defaulted

    plant_files: list[Path] = []
    for plant_id, record, defaulted in prepared:
        plant_file = plants_dir / f"{plant_id}.md"
        plant_markdown.write_plant(plant_file, record, schema=plant_schema)
        plant_files.append(plant_file)
        if defaulted:
            defaulted_fields[plant_id] = defaulted

    return MigrationSummary(
        slug=slug,
        output_dir=target,
        project_file=project_file,
        plant_files=plant_files,
        defaulted_fields=defaulted_fields,
        tracker_md5_before=md5_before,
        tracker_md5_after=file_md5(tracker_path),
    )


# ---------------------------------------------------------------- verify ----


def verify_migration(
    tracker_path: str | Path,
    output_dir: str | Path,
    project_template: str | Path,
    plant_template: str | Path,
) -> VerificationReport:
    """Re-read the migrated tree and diff it against the source JSON.

    Every key/value present in the source must be present and equal in the
    markdown. Fields the markdown has but the JSON did not (template defaults
    materialised for absent fields) are additions, not loss, and are not
    reported here — :attr:`MigrationSummary.defaulted_fields` records those.
    """
    tracker = _read_json(tracker_path)
    target = Path(output_dir)
    report = VerificationReport()

    project_schema = project_markdown.load_schema(project_template)
    plant_schema = plant_markdown.load_schema(plant_template)

    project_file = target / "project.md"
    if not project_file.exists():
        report.missing_records.append("project")
    else:
        got = project_markdown.read_project(project_file, schema=project_schema)
        _diff_record(
            "project",
            {k: v for k, v in tracker.items() if k != PLANTS_KEY},
            got,
            report,
        )

    plants = _plants_of(tracker)
    report.plant_count_source = len(plants)

    plants_dir = target / "plants"
    migrated_ids = (
        sorted(p.stem for p in plants_dir.glob("*.md")) if plants_dir.is_dir() else []
    )
    report.plant_count_migrated = len(migrated_ids)

    source_ids = []
    for index, plant in enumerate(plants):
        plant_id = _plant_id(plant, index)
        source_ids.append(plant_id)
        plant_file = plants_dir / f"{plant_id}.md"
        if not plant_file.exists():
            report.missing_records.append(plant_id)
            continue
        got = plant_markdown.read_plant(plant_file, schema=plant_schema)
        _diff_record(plant_id, plant, got, report)

    report.extra_records = sorted(set(migrated_ids) - set(source_ids))
    return report


def _diff_record(
    name: str,
    source: Mapping[str, Any],
    got: Mapping[str, Any],
    report: VerificationReport,
) -> None:
    for field, original in source.items():
        if field not in got:
            report.lost_fields.setdefault(name, []).append(field)
        elif got[field] != original:
            report.changed_fields.setdefault(name, []).append(
                {"field": field, "expected": original, "got": got[field]}
            )
