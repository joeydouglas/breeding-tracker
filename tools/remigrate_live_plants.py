#!/usr/bin/env python3
"""Re-migrate a live project's ``plants/<ID>.md`` from ``tracker.json`` (NICK-966).

WHY THIS EXISTS. Phase 3's migration was only ever proven in a SANDBOX:
``tracker_migration.assert_sandbox_destination`` explicitly refuses to write
anywhere under ``~/.hermes/breeding``, so its output never landed in a live
project. What IS on disk in every live ``plants/`` directory was written by an
old derived-view writer (``breeding_core.update_markdown()``, removed in Task
2.1): a lossy 3-field projection (``plant_id``/``cross``/``status``) of 19-field
records, and for several projects not even one file per plant.

This tool is the forward fix, in the same shape as NICK-948's
``generate_live_project_md.py``: it reuses Phase 3's own tested
``build_plant_record`` and Phase 1's ``write_plant`` against the real live
path, rather than re-implementing either. It writes ONLY ``plants/<ID>.md``;
it never writes ``tracker.json`` (md5 asserted before and after) and never
touches ``project.md``.

SAFETY MODEL. Everything is computed and verified BEFORE the first live byte
is written:

1. :func:`plan` reads the tracker, builds every record through
   ``build_plant_record``, and diffs each built record field-by-field back
   against the source. A plan whose verification did not pass -- or which
   compared nothing at all -- cannot be applied.
2. The planned ID set is checked against the tracker roster exactly: no
   extras, no omissions.
3. ``only=`` restricts the run to an explicit subset. Files outside the
   selection are not read, written, or deleted. This is what makes it safe to
   fix mule-fuel-x-nana-glue's 9 stubs without touching its 36 richer
   ``id:``-keyed legacy records.
4. Body content present in the CURRENT file but absent from ``tracker.json``
   is detected and reported as :attr:`Plan.orphan_observations` rather than
   silently overwritten -- re-migration reads from the tracker, so anything
   the tracker lacks would otherwise vanish without a trace.

Run:  .venv/bin/python tools/remigrate_live_plants.py <slug> [--only ID ...]
      (add --apply to actually write; the default is a dry run)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

from breeding_tracker import plant_markdown  # noqa: E402
from breeding_tracker import tracker_migration  # noqa: E402

DEFAULT_REGISTRY = (
    Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
)
DEFAULT_TEMPLATE = _REPO_ROOT / "breeding_tracker" / "templates" / "plant-template.md"
DEFAULT_BREEDING_ROOT = Path.home() / ".hermes" / "breeding"

#: A timestamped observation block header, as written by
#: ``breeding_core.update_plant``: ``### 2026-08-31T21:46:25.809980``.
_OBSERVATION_HEADER = re.compile(
    r"^### (\d{4}-\d{2}-\d{2}T[\d:.]+)\s*$", re.MULTILINE
)


class RemigrationError(Exception):
    """The re-migration cannot be performed as requested."""


class Plan:
    """Everything one project's re-migration WOULD write, plus its proof.

    Constructed by :func:`plan` and consumed by :func:`apply`. Holding the
    verification result on the plan (rather than checking inside ``apply``)
    is what lets a caller inspect and print the whole thing before deciding
    to write, and lets a test falsify the gate by marking an otherwise-valid
    plan as failed.
    """

    def __init__(self, project_dir, plant_ids, records, tracker_md5):
        self.project_dir = Path(project_dir)
        #: Ordered exactly as the tracker's ``plants`` array.
        self.plant_ids = list(plant_ids)
        #: {plant_id -> the dict that will be written}
        self.records = dict(records)
        self.tracker_md5 = tracker_md5
        #: Human-readable verification failures; empty means verified.
        self.verification_problems: list[str] = []
        #: Individual source field values actually compared.
        self.fields_compared = 0
        #: {plant_id -> [{"timestamp", "text"}]} present on disk, not in the
        #: tracker. Reported, never written.
        self.orphan_observations: dict[str, list[dict]] = {}

    @property
    def verification_ok(self) -> bool:
        """True only when nothing failed AND something was actually checked.

        The second half matters: a run that compared zero fields records no
        problem and would otherwise be indistinguishable from a clean one.
        """
        return not self.verification_problems and self.fields_compared > 0

    def path_for(self, plant_id) -> Path:
        return self.project_dir / "plants" / f"{plant_id}.md"


class Result:
    """What one :func:`apply` call actually wrote."""

    def __init__(self, written, created, tracker_md5_before, tracker_md5_after):
        self.written = list(written)
        #: Subset of ``written`` that had no file on disk beforehand.
        self.created = list(created)
        self.tracker_md5_before = tracker_md5_before
        self.tracker_md5_after = tracker_md5_after

    @property
    def tracker_unchanged(self) -> bool:
        return self.tracker_md5_before == self.tracker_md5_after


# ------------------------------------------------------------------ plan ----


def _observation_blocks(text):
    """``{timestamp: block_text}`` for each ``### <iso timestamp>`` section."""
    blocks = {}
    parts = _OBSERVATION_HEADER.split(text or "")
    for index in range(1, len(parts), 2):
        blocks[parts[index]] = parts[index + 1].split("\n##", 1)[0].strip()
    return blocks


def _orphans_for(existing_path, source_log):
    """Observation blocks the FILE has that the TRACKER does not.

    Re-migration sources everything from ``tracker.json``, so any such block
    would be dropped by the rewrite. Returned for reporting rather than
    merged: merging would invent a record shape neither side actually has,
    and the right resolution (is the tracker stale, or is the file's extra
    content itself an artefact?) is a human call.
    """
    if not existing_path.exists():
        return []
    try:
        current = plant_markdown.read_plant(existing_path)
    except plant_markdown.PlantMarkdownError:
        # An unparseable current file has no salvageable blocks to compare;
        # the rewrite replaces it wholesale from the tracker either way.
        return []
    on_disk = _observation_blocks(current.get(plant_markdown.BODY_FIELD, ""))
    in_tracker = _observation_blocks(source_log or "")
    return [
        {"timestamp": stamp, "text": on_disk[stamp]}
        for stamp in sorted(set(on_disk) - set(in_tracker))
    ]


def plan(project_dir, registry_path, slug, plant_template, *, only=None) -> Plan:
    """Compute (and verify) every record this project's re-migration would write.

    Pure with respect to the live tree: reads only. ``only`` restricts the run
    to an explicit list of plant IDs; omitted, every plant in the tracker is
    planned. Passing ``only=[]`` plans nothing, which deliberately fails
    verification rather than reporting a vacuous success.
    """
    project_dir = Path(project_dir)
    tracker_path = project_dir / "tracker.json"
    tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
    # `registry_path`/`slug` are read purely to fail loud on an unregistered
    # project, matching migrate_tracker's refusal to migrate without one.
    tracker_migration.load_registry_entry(registry_path, slug)
    schema = plant_markdown.load_schema(plant_template)

    source = {}
    order = []
    for index, entry in enumerate(tracker.get("plants", [])):
        plant_id = tracker_migration._plant_id(entry, index)
        if plant_id in source:
            raise RemigrationError(
                f"duplicate plant id {plant_id!r} in {tracker_path}"
            )
        source[plant_id] = entry
        order.append(plant_id)

    if only is None:
        selected = list(order)
    else:
        unknown = [pid for pid in only if pid not in source]
        if unknown:
            raise RemigrationError(
                f"{unknown} not in {tracker_path}'s roster; refusing to write "
                "a plant the authoritative source does not have"
            )
        selected = [pid for pid in order if pid in set(only)]

    records = {}
    for plant_id in selected:
        record, _defaulted = tracker_migration.build_plant_record(
            source[plant_id], schema
        )
        records[plant_id] = record

    result = Plan(
        project_dir, selected, records, tracker_migration.file_md5(tracker_path)
    )

    # (1) field-by-field verification of every built record against its source
    canonical = tracker_migration.CANONICAL_PLANT_ID_KEY
    legacy = tracker_migration.SOURCE_PLANT_ID_KEY
    for plant_id in selected:
        record = records[plant_id]
        if record.get(canonical) != plant_id:
            result.verification_problems.append(
                f"{plant_id}: record's {canonical} is {record.get(canonical)!r}"
            )
        if legacy in record:
            result.verification_problems.append(
                f"{plant_id}: record still carries the legacy {legacy!r} key"
            )
        for key, value in source[plant_id].items():
            target = canonical if key == legacy else key
            result.fields_compared += 1
            if target not in record:
                result.verification_problems.append(f"{plant_id}.{key} lost")
            elif record[target] != value:
                result.verification_problems.append(
                    f"{plant_id}.{key} changed: {value!r} -> {record[target]!r}"
                )

    # (2) roster gate -- only meaningful for a whole-project run
    if only is None and set(selected) != set(source):
        result.verification_problems.append(
            "planned ids do not match the tracker roster: "
            f"missing={sorted(set(source) - set(selected))} "
            f"extra={sorted(set(selected) - set(source))}"
        )

    # (3) content on disk that the tracker does not have
    for plant_id in selected:
        orphans = _orphans_for(
            result.path_for(plant_id), source[plant_id].get("observation_log")
        )
        if orphans:
            result.orphan_observations[plant_id] = orphans

    return result


# ----------------------------------------------------------------- apply ----


def apply(plan_obj, plant_template=DEFAULT_TEMPLATE) -> Result:
    """Write the planned records to the live ``plants/`` directory.

    Refuses outright unless the plan verified. Writes only the planned files:
    no file outside ``plan_obj.plant_ids`` is opened, and nothing is ever
    deleted -- unlike ``markdown_backend.save_tracker``, this is not a
    whole-roster rewrite, so a plant absent from the selection simply stays as
    it is.
    """
    if not plan_obj.verification_ok:
        raise RemigrationError(
            "refusing to write: plan did not verify against tracker.json "
            f"({plan_obj.verification_problems or 'nothing was compared'})"
        )

    tracker_path = plan_obj.project_dir / "tracker.json"
    md5_before = tracker_migration.file_md5(tracker_path)
    schema = plant_markdown.load_schema(plant_template)

    written, created = [], []
    for plant_id in plan_obj.plant_ids:
        path = plan_obj.path_for(plant_id)
        if not path.exists():
            created.append(plant_id)
        plant_markdown.write_plant(path, plan_obj.records[plant_id], schema=schema)
        written.append(plant_id)

    md5_after = tracker_migration.file_md5(tracker_path)
    if md5_before != md5_after:  # pragma: no cover - nothing here writes it
        raise RemigrationError(
            f"{tracker_path} changed during re-migration ({md5_before} -> "
            f"{md5_after}); this tool must never write it"
        )
    return Result(written, created, md5_before, md5_after)


# ------------------------------------------------------------------- cli ----


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--only", nargs="*", default=None,
                        help="restrict to these plant IDs (default: all)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--breeding-root", type=Path,
                        default=DEFAULT_BREEDING_ROOT)
    parser.add_argument("--apply", action="store_true",
                        help="actually write (default: dry run)")
    args = parser.parse_args(argv)

    project_dir = args.breeding_root / args.slug
    result = plan(
        project_dir, args.registry, args.slug, args.template, only=args.only
    )

    print(f"{args.slug}: {len(result.plant_ids)} plants planned")
    print(f"  verification: {'OK' if result.verification_ok else 'FAILED'} "
          f"({result.fields_compared} field values compared)")
    for problem in result.verification_problems:
        print(f"    PROBLEM: {problem}")
    if result.orphan_observations:
        total = sum(len(v) for v in result.orphan_observations.values())
        print(f"  WARNING: {total} observation block(s) on disk are NOT in "
              f"tracker.json and WOULD BE LOST by this rewrite:")
        for plant_id, orphans in sorted(result.orphan_observations.items()):
            for orphan in orphans:
                print(f"    {plant_id} {orphan['timestamp']}: "
                      f"{orphan['text'][:100]!r}")

    if not args.apply:
        print("  [dry run] nothing written; pass --apply to write")
        return 0 if result.verification_ok else 1

    applied = apply(result, args.template)
    print(f"  [written] {len(applied.written)} files "
          f"({len(applied.created)} newly created)")
    print(f"  tracker.json unchanged: {applied.tracker_unchanged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
