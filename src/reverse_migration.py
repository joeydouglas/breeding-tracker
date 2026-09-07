"""Reverse migration: a project's markdown tree back into ``tracker.json`` (NICK-967).

WHY THIS EXISTS. The approved plan's Task 7.2 gives every per-project cutover
a rollback procedure, and steps 7b/7c of it require exactly this direction:

    b. Reverse-migrate every markdown observation committed to that project's
       repo since cutover back into tracker.json [...]
    c. Diff the reverse-migration output against the markdown source; confirm
       zero missing/duplicated observations before proceeding. If the diff
       shows any discrepancy, STOP.

Task 1.3's forward runner (:mod:`tracker_migration`) only goes
``tracker.json`` -> markdown, so a rollback had no verified way back. This
module is its structural mirror: :func:`reverse_migrate_tracker` is the
counterpart of ``migrate_tracker``, and :func:`verify_reverse_migration` is
the counterpart of ``verify_migration`` -- same report shape, same doctrine
that "zero data loss" is *verified*, not asserted, and that a verification
which compared nothing is a failure rather than a success.

THE ID FIELD. The two spellings are not re-declared here; they are imported
from :mod:`tracker_migration` (``SOURCE_PLANT_ID_KEY`` = ``id``,
``CANONICAL_PLANT_ID_KEY`` = ``plant_id``) precisely so the two directions can
never drift about which spelling belongs on which side. The forward migration
renames ``id`` -> ``plant_id`` on the way OUT; this one renames ``plant_id``
-> ``id`` on the way IN, because ``id`` is ``tracker.json``'s own native key
and ``json_backend`` -- restored verbatim for a NICK-949 rollback -- reads
nothing else.

WHAT IS DELIBERATELY NOT CARRIED BACK:

* ``plant_order`` and the project ``body`` are markdown-format constructs. No
  ``tracker.json`` has ever had either, and inventing them would make a
  rolled-back file differ from the format ``json_backend`` expects.
* ``auto_create`` and ``plant_id_prefixes`` belong to ``registry.json``, not
  to the tracker (Task 3.0 §8). The forward migration sources them FROM the
  registry; writing them into a tracker here would create a second, silently
  diverging copy of the routing configuration.

This module is READ-ONLY with respect to the markdown corpus: it opens plant
and project files for reading and never writes anything anywhere. The single
tracker.json write lives in ``tools/reverse_migrate_project.py``, behind an
explicit ``--apply``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import plant_markdown
import project_markdown
from tracker_migration import (
    CANONICAL_PLANT_ID_KEY,
    PLANT_BODY_FIELD,
    PLANTS_KEY,
    PROJECT_BODY_FIELD,
    REGISTRY_SOURCED_FIELDS,
    SOURCE_PLANT_ID_KEY,
)

__all__ = [
    "ReverseMigrationError",
    "ReverseVerificationReport",
    "ORDER_KEY",
    "PROJECT_RECORD_ID",
    "MARKDOWN_ONLY_PROJECT_FIELDS",
    "read_project_record",
    "read_plant_records",
    "reverse_migrate_tracker",
    "verify_reverse_migration",
]

PROJECT_FILE = "project.md"
PLANTS_DIR = "plants"

#: Synthetic record id under which the PROJECT's own top-level fields are
#: reported in a :class:`ReverseVerificationReport`. Plants are keyed by their
#: real plant id; the project is not a plant and has no id of its own, so it
#: needs a name that no plant file can ever collide with (a plant id is a
#: filename stem, and ``__project__`` is not a legal one here).
PROJECT_RECORD_ID = "__project__"

#: ``markdown_backend``'s own name for the ordering key it writes into
#: ``project.md``. Matched here so the reverse migration strips exactly the
#: key the runtime adds, rather than a lookalike.
ORDER_KEY = "plant_order"

#: Project frontmatter fields that must NOT appear in a produced
#: ``tracker.json``: markdown-format constructs plus the registry's routing
#: fields (see the module docstring).
MARKDOWN_ONLY_PROJECT_FIELDS = (
    ORDER_KEY,
    PROJECT_BODY_FIELD,
    *REGISTRY_SOURCED_FIELDS,
)

#: Keys ``plant_markdown.read_plant`` guarantees on every read regardless of
#: what the file held. Kept even when restricting to the file's own keys, so
#: an empty observation log still round-trips as a present-but-empty field
#: rather than vanishing (same rule as ``markdown_backend``'s
#: ``_ALWAYS_PRESENT_PLANT_KEYS``).
_ALWAYS_PRESENT_PLANT_KEYS = frozenset({PLANT_BODY_FIELD})

#: A timestamped observation block header as written by the runtime
#: (``### 2026-08-31T21:46:25.809980``). Same pattern as
#: ``tools/remigrate_live_plants.py`` uses in the other direction.
_OBSERVATION_HEADER = re.compile(
    r"^### (\d{4}-\d{2}-\d{2}T[\d:.]+)\s*$", re.MULTILINE
)


class ReverseMigrationError(Exception):
    """The reverse migration cannot be performed as requested."""


class ReverseVerificationReport:
    """Structured result of re-reading the markdown and diffing the tracker.

    Mirrors :class:`tracker_migration.VerificationReport`: ``ok`` is True only
    when nothing was lost, altered, duplicated or invented **and the
    verification actually compared something**. The counts are load-bearing
    for the same reason they are there -- a verification that silently
    degraded to a no-op (wrong directory, no plant files found) records no
    discrepancy and would otherwise be indistinguishable from a clean run.

    Two containers exist here that the forward report has no need for:

    ``illegal_fields``
        Fields present in the produced tracker that must never be there --
        today, the canonical markdown ``plant_id`` key. A tracker carrying
        both spellings is exactly the shape ``plant_record.plant_id_of``
        rejects as corrupt.
    ``unrepresented_observations``
        Body content on disk that the produced tracker's ``observation_log``
        does not carry. This is the plan's step 7c zero-loss check: such
        content is FLAGGED, never silently dropped.
    """

    def __init__(self) -> None:
        self.missing_records: list[str] = []
        self.extra_records: list[str] = []
        self.duplicate_records: list[str] = []
        self.lost_fields: dict[str, list[str]] = {}
        self.changed_fields: dict[str, list[dict[str, Any]]] = {}
        self.illegal_fields: dict[str, list[str]] = {}
        self.unrepresented_observations: dict[str, list[dict[str, Any]]] = {}
        self.plant_count_markdown: int = 0
        self.plant_count_produced: int = 0
        self.records_compared: int = 0
        self.fields_compared: int = 0

    @property
    def plant_count_matches(self) -> bool:
        return self.plant_count_markdown == self.plant_count_produced

    @property
    def verified_something(self) -> bool:
        """Whether this report is evidence of anything at all."""
        return self.records_compared > 0 and self.fields_compared > 0

    @property
    def ok(self) -> bool:
        return (
            self.verified_something
            and not self.missing_records
            and not self.extra_records
            and not self.duplicate_records
            and not self.lost_fields
            and not self.changed_fields
            and not self.illegal_fields
            and not self.unrepresented_observations
            and self.plant_count_matches
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verified_something": self.verified_something,
            "records_compared": self.records_compared,
            "fields_compared": self.fields_compared,
            "plant_count_markdown": self.plant_count_markdown,
            "plant_count_produced": self.plant_count_produced,
            "plant_count_matches": self.plant_count_matches,
            "missing_records": self.missing_records,
            "extra_records": self.extra_records,
            "duplicate_records": self.duplicate_records,
            "lost_fields": self.lost_fields,
            "changed_fields": self.changed_fields,
            "illegal_fields": self.illegal_fields,
            "unrepresented_observations": self.unrepresented_observations,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ReverseVerificationReport(ok={self.ok}, {self.as_dict()!r})"


# ----------------------------------------------------------------- read ----


def _restrict_to_present(
    typed: Mapping[str, Any], present_keys, always_keep=frozenset()
) -> dict:
    """Keep only the keys the file really held, plus any ``always_keep`` key.

    A schema-typed read materialises every template field, present in the file
    or not. Carrying those materialised defaults into ``tracker.json`` would
    invent fields the pre-cutover file never had (e.g. ``corrected_reading``
    on all but one lantz plant), which a byte-level rollback comparison would
    then report as a difference. So the typed VALUES are used -- the schema is
    what makes ``photo_count: 07`` an int and ``id: 07`` a string -- while the
    KEY SET comes from the file itself. Same technique as
    ``markdown_backend.load_tracker``, which reads the same corpus at runtime.
    """
    return {
        key: value
        for key, value in typed.items()
        if key in present_keys or key in always_keep
    }


def _plant_path_order(project_dir: Path, order) -> list[Path]:
    """Plant files, ordered by ``plant_order`` first, then the rest sorted.

    Mirrors ``markdown_backend.load_tracker``'s ordering exactly: an id listed
    in ``plant_order`` but with no file on disk is skipped (the file is the
    record of truth), and a file not listed is appended in sorted order rather
    than dropped.
    """
    plants_dir = project_dir / PLANTS_DIR
    on_disk = (
        {path.stem: path for path in sorted(plants_dir.glob("*.md"))}
        if plants_dir.is_dir()
        else {}
    )
    ordered = [on_disk[pid] for pid in (order or []) if pid in on_disk]
    listed = {path.stem for path in ordered}
    ordered += [path for stem, path in sorted(on_disk.items()) if stem not in listed]
    return ordered


def read_project_record(
    project_dir: str | Path, project_schema: Mapping[str, Mapping[str, Any]] | None = None
) -> tuple[dict, list[str]]:
    """``project.md``'s tracker-bound fields, plus its ``plant_order``.

    Returns ``(record, order)``. Every markdown-only and registry-owned field
    is stripped from ``record`` (see :data:`MARKDOWN_ONLY_PROJECT_FIELDS`);
    ``order`` is returned separately because the reverse migration needs it to
    order the plants array but must not write it into the tracker.
    """
    project_dir = Path(project_dir)
    path = project_dir / PROJECT_FILE
    if not path.is_file():
        raise ReverseMigrationError(
            f"{path} does not exist; a project's markdown tree must have a "
            f"{PROJECT_FILE} to reverse-migrate"
        )

    present = set(project_markdown.read_project(path))
    typed = project_markdown.read_project(path, schema=project_schema)
    record = _restrict_to_present(typed, present)

    order = record.pop(ORDER_KEY, None) or []
    for field in MARKDOWN_ONLY_PROJECT_FIELDS:
        record.pop(field, None)
    # `plants` is rebuilt from plants/*.md; a stale copy in frontmatter (only
    # possible in a hand-edited file) must never win over the real files.
    record.pop(PLANTS_KEY, None)
    return record, list(order)


def _to_tracker_plant(record: Mapping[str, Any], path: Path) -> dict:
    """One markdown record as ``tracker.json`` spells it.

    The canonical ``plant_id`` is RENAMED to the tracker's native ``id``, in
    place, so the key keeps its position and the produced record carries
    exactly one id spelling.
    """
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == CANONICAL_PLANT_ID_KEY:
            out[SOURCE_PLANT_ID_KEY] = value
        elif key == SOURCE_PLANT_ID_KEY:
            # A file that already uses the tracker's spelling (mule-fuel's
            # pre-migration legacy records) passes straight through; a file
            # carrying BOTH is caught by the disagreement check below.
            out.setdefault(SOURCE_PLANT_ID_KEY, value)
        else:
            out[key] = value

    canonical = record.get(CANONICAL_PLANT_ID_KEY)
    legacy = record.get(SOURCE_PLANT_ID_KEY)
    if canonical is not None and legacy is not None and canonical != legacy:
        raise ReverseMigrationError(
            f"{path} has conflicting ids: {CANONICAL_PLANT_ID_KEY}={canonical!r} "
            f"vs {SOURCE_PLANT_ID_KEY}={legacy!r}"
        )

    plant_id = out.get(SOURCE_PLANT_ID_KEY)
    if not isinstance(plant_id, str) or not plant_id.strip():
        raise ReverseMigrationError(
            f"{path} has no usable plant id under either "
            f"{CANONICAL_PLANT_ID_KEY!r} or {SOURCE_PLANT_ID_KEY!r}"
        )
    if plant_id != path.stem:
        raise ReverseMigrationError(
            f"{path} declares id {plant_id!r}, which does not match its "
            "filename; refusing to guess which one is right"
        )
    return out


def read_plant_records(
    project_dir: str | Path,
    plant_schema: Mapping[str, Mapping[str, Any]],
    order=None,
) -> list[dict]:
    """Every ``plants/<ID>.md`` as a tracker-shaped plant record."""
    project_dir = Path(project_dir)
    records: list[dict] = []
    seen: set[str] = set()
    for path in _plant_path_order(project_dir, order):
        present = set(plant_markdown.read_plant(path))
        typed = plant_markdown.read_plant(path, schema=plant_schema)
        record = _restrict_to_present(typed, present, _ALWAYS_PRESENT_PLANT_KEYS)
        converted = _to_tracker_plant(record, path)
        plant_id = converted[SOURCE_PLANT_ID_KEY]
        if plant_id in seen:  # pragma: no cover - filenames are unique per dir
            raise ReverseMigrationError(f"duplicate plant id {plant_id!r} on disk")
        seen.add(plant_id)
        records.append(converted)
    return records


# -------------------------------------------------------------- migrate ----


def reverse_migrate_tracker(
    project_dir: str | Path, plant_schema: Mapping[str, Mapping[str, Any]]
) -> dict:
    """Build a ``tracker.json``-shaped dict from a project's markdown tree.

    Nothing is written: the caller decides whether the result ever reaches
    disk, and ``tools/reverse_migrate_project.py`` only does so after
    :func:`verify_reverse_migration` passes.
    """
    project_dir = Path(project_dir)
    record, order = read_project_record(project_dir)
    record[PLANTS_KEY] = read_plant_records(project_dir, plant_schema, order)
    return record


# --------------------------------------------------------------- verify ----


def _observation_blocks(text: str | None) -> dict[str, str]:
    """``{timestamp: block_text}`` for each ``### <iso timestamp>`` section."""
    blocks: dict[str, str] = {}
    parts = _OBSERVATION_HEADER.split(text or "")
    for index in range(1, len(parts), 2):
        blocks[parts[index]] = parts[index + 1].split("\n##", 1)[0].strip()
    return blocks


def _unrepresented_observations(
    on_disk_body: str | None, produced_log: str | None
) -> list[dict[str, Any]]:
    """Body content the markdown has that the produced tracker does not.

    Checked two ways, because a plant's log is not always block-structured:
    every timestamped ``### <iso>`` block must appear in the produced log with
    its text intact, AND a log with no blocks at all must still be carried
    across in full. Anything unaccounted for is returned for reporting -- the
    plan's step 7c requires the diff to be clean, so this must never be
    silently swallowed.
    """
    body = on_disk_body or ""
    produced = produced_log or ""
    if not body.strip():
        return []

    blocks = _observation_blocks(body)
    if blocks:
        missing = []
        for stamp, text in blocks.items():
            if stamp not in produced or (text and text not in produced):
                missing.append({"timestamp": stamp, "text": text})
        return missing

    return (
        []
        if body.strip() in produced
        else [{"timestamp": None, "text": body.strip()}]
    )


def _verify_project_record(
    expected: Mapping[str, Any],
    produced_tracker: Mapping[str, Any],
    report: ReverseVerificationReport,
) -> None:
    """Diff the produced tracker's TOP-LEVEL fields against ``project.md``.

    Reported under :data:`PROJECT_RECORD_ID` in the very same containers the
    plants use, so ``ReverseVerificationReport.ok`` -- which already returns
    False for any non-empty ``lost_fields``/``changed_fields``/
    ``illegal_fields`` -- needs no new boolean logic to cover the project.

    Three directions are checked, because each is a distinct real failure:

    * a field the markdown HAS and the tracker LACKS is ``lost``;
    * a field both have but with different values is ``changed`` (this is
      what catches a garbage ``cross_name``, a nulled ``github_repo``, or a
      ``drive_folders`` dict retyped to a string);
    * a top-level key the markdown never had is ``illegal`` -- an invented
      field is data corruption in a rollback artifact just as much as a
      missing one, and ``plants`` aside, nothing may appear from nowhere.

    ``records_compared`` counts the project as one record and
    ``fields_compared`` counts each of its fields, exactly as for a plant, so
    ``verified_something`` stays an honest measure of what was checked.
    """
    report.records_compared += 1
    for field, value in expected.items():
        report.fields_compared += 1
        if field not in produced_tracker:
            report.lost_fields.setdefault(PROJECT_RECORD_ID, []).append(field)
        elif produced_tracker[field] != value:
            report.changed_fields.setdefault(PROJECT_RECORD_ID, []).append(
                {
                    "field": field,
                    "expected": value,
                    "got": produced_tracker[field],
                }
            )

    # `plants` is the array this function's caller verifies element by
    # element; it is legitimately present and is not a project field.
    for field in produced_tracker:
        if field != PLANTS_KEY and field not in expected:
            report.illegal_fields.setdefault(PROJECT_RECORD_ID, []).append(field)


def verify_reverse_migration(
    markdown_dir: str | Path,
    produced_tracker: Mapping[str, Any],
    plant_schema: Mapping[str, Mapping[str, Any]],
) -> ReverseVerificationReport:
    """Re-read the markdown independently and diff the produced tracker at it.

    Deliberately re-reads from disk rather than trusting whatever
    :func:`reverse_migrate_tracker` returned: a verification that shares the
    producer's in-memory state can only ever confirm the producer's own bugs.

    Every field the MARKDOWN carries must be present and equal in the produced
    tracker, under the tracker's ``id`` spelling. Fields the tracker has that
    the markdown does not are reported as changes/extras, not ignored, because
    in this direction the markdown is the source of truth.

    BOTH halves of the tracker are checked: the ``plants`` array AND the
    project's own top-level fields. Checking only the plants was the original
    defect here -- it let ``cross_name``, ``google_sheet_id``,
    ``drive_folders`` and friends be corrupted, dropped, retyped or invented
    while the report still said ``ok``. Plan step 7c's "if the diff shows any
    discrepancy, STOP" is scoped to the whole ``tracker.json``, so the project
    record is diffed under the synthetic id :data:`PROJECT_RECORD_ID` using
    the same lost/changed/illegal containers as the plants.
    """
    markdown_dir = Path(markdown_dir)
    report = ReverseVerificationReport()

    plants = produced_tracker.get(PLANTS_KEY) or []
    report.plant_count_produced = len(plants)

    produced_by_id: dict[str, dict] = {}
    for entry in plants:
        if not isinstance(entry, Mapping):
            raise ReverseMigrationError(f"plant record is not an object: {entry!r}")
        plant_id = entry.get(SOURCE_PLANT_ID_KEY) or entry.get(
            CANONICAL_PLANT_ID_KEY
        )
        if plant_id in produced_by_id:
            report.duplicate_records.append(plant_id)
            continue
        produced_by_id[plant_id] = dict(entry)

    order = []
    if (markdown_dir / PROJECT_FILE).is_file():
        expected_project, order = read_project_record(markdown_dir)
        _verify_project_record(expected_project, produced_tracker, report)

    paths = _plant_path_order(markdown_dir, order)
    report.plant_count_markdown = len(paths)

    for path in paths:
        present = set(plant_markdown.read_plant(path))
        typed = plant_markdown.read_plant(path, schema=plant_schema)
        expected = _to_tracker_plant(
            _restrict_to_present(typed, present, _ALWAYS_PRESENT_PLANT_KEYS), path
        )
        plant_id = expected[SOURCE_PLANT_ID_KEY]

        got = produced_by_id.get(plant_id)
        if got is None:
            report.missing_records.append(plant_id)
            continue

        report.records_compared += 1
        if CANONICAL_PLANT_ID_KEY in got:
            report.illegal_fields.setdefault(plant_id, []).append(
                CANONICAL_PLANT_ID_KEY
            )
        for field, value in expected.items():
            report.fields_compared += 1
            if field not in got:
                report.lost_fields.setdefault(plant_id, []).append(field)
            elif got[field] != value:
                report.changed_fields.setdefault(plant_id, []).append(
                    {"field": field, "expected": value, "got": got[field]}
                )

        unrepresented = _unrepresented_observations(
            expected.get(PLANT_BODY_FIELD), got.get(PLANT_BODY_FIELD)
        )
        if unrepresented:
            report.unrepresented_observations[plant_id] = unrepresented

    markdown_ids = {path.stem for path in paths}
    report.extra_records = sorted(
        str(pid) for pid in produced_by_id if pid not in markdown_ids
    )
    return report
