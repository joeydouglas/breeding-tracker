#!/usr/bin/env python3
"""Reverse-migrate one project's markdown tree back into ``tracker.json`` (NICK-967).

WHY THIS EXISTS. The approved plan's Task 7.2 step 7 makes a full rollback
rehearsal mandatory before a per-project cutover can be marked done:

    b. Reverse-migrate every markdown observation committed to that project's
       repo since cutover back into tracker.json [...]
    c. Diff the reverse-migration output against the markdown source; confirm
       zero missing/duplicated observations before proceeding. If the diff
       shows any discrepancy, STOP -- do not flip the backend config with
       unverified data; escalate to Joey.

This is the glue that performs (b) and enforces (c). The transformation itself
lives in ``src/reverse_migration.py``; this file is UX and safety only, in the
same shape as ``tools/remigrate_live_plants.py`` (its forward-direction twin).

SAFETY MODEL -- plan, then verify, then apply; nothing is written before
verification passes:

1. :func:`plan` reads ``project.md`` + every ``plants/<ID>.md``, builds the
   tracker-shaped dict, and re-reads the markdown INDEPENDENTLY to diff it.
   A plan whose verification failed -- or which compared nothing at all --
   cannot be applied.
2. :func:`apply` writes exactly ONE file, and refuses any target that is not
   named ``tracker.json``. It refuses to overwrite an existing tracker unless
   ``--overwrite`` is passed as well, so a rehearsal cannot silently clobber
   the pre-cutover file a rollback may still need.
3. Nothing here ever opens a ``plants/*.md`` or ``project.md`` for writing.
   The markdown corpus is strictly read-only in this direction.

Run:  .venv/bin/python tools/reverse_migrate_project.py <slug>
      (add --apply to actually write tracker.json; the default is a dry run)

NOTE -- ``--overwrite`` IS STRICTER THAN THE SPEC. The spec says the tool
"refuses to overwrite an existing tracker.json unless --apply passed AND
verification passed". This tool additionally requires an explicit
``--overwrite`` before it will replace a tracker.json that already exists.
That is a deliberate belt-and-braces choice, not an oversight: a rollback
rehearsal is run repeatedly, and the pre-cutover tracker.json is the very file
a real rollback would need, so clobbering it must be spelled out rather than
implied by --apply. Documented here so the extra flag is not a silent surprise
to anyone working from the spec.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

import plant_markdown  # noqa: E402
import reverse_migration  # noqa: E402
import tracker_migration  # noqa: E402

from reverse_migration import ReverseMigrationError  # noqa: E402,F401

DEFAULT_REGISTRY = (
    Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
)
DEFAULT_TEMPLATE = _REPO_ROOT / "templates" / "plant-template.md"
DEFAULT_BREEDING_ROOT = Path.home() / ".hermes" / "breeding"

TRACKER_FILENAME = "tracker.json"


class Plan:
    """The tracker one reverse migration WOULD write, plus its proof.

    Holding the verification report ON the plan (rather than checking inside
    :func:`apply`) is what lets a caller print the whole diff before deciding
    to write, and lets a test falsify the gate by marking an otherwise-valid
    plan as failed.
    """

    def __init__(self, project_dir, tracker, report):
        self.project_dir = Path(project_dir)
        #: The ``tracker.json``-shaped dict this plan would write.
        self.tracker = tracker
        #: :class:`reverse_migration.ReverseVerificationReport`.
        self.report = report

    @property
    def plant_ids(self) -> list[str]:
        return [
            p[tracker_migration.SOURCE_PLANT_ID_KEY]
            for p in self.tracker.get("plants", [])
        ]

    @property
    def verification_ok(self) -> bool:
        return self.report.ok


# ------------------------------------------------------------------ plan ----


def plan(project_dir, registry_path, slug, plant_template) -> Plan:
    """Build and verify the tracker this project's markdown implies.

    Pure with respect to the tree: reads only. ``registry_path``/``slug`` are
    read purely to fail loud on an unregistered project, matching
    ``migrate_tracker``'s refusal to migrate without a registry entry.
    """
    project_dir = Path(project_dir)
    tracker_migration.load_registry_entry(registry_path, slug)
    schema = plant_markdown.load_schema(plant_template)

    tracker = reverse_migration.reverse_migrate_tracker(project_dir, schema)
    report = reverse_migration.verify_reverse_migration(
        project_dir, tracker, schema
    )
    if not report.verified_something:
        raise ReverseMigrationError(
            f"{project_dir} yielded nothing to verify "
            f"({report.records_compared} records, {report.fields_compared} "
            "field values compared); refusing to report a vacuous success"
        )
    return Plan(project_dir, tracker, report)


# ----------------------------------------------------------------- apply ----


def apply(plan_obj: Plan, target, *, overwrite: bool = False) -> Path:
    """Write the planned tracker to ONE explicit ``tracker.json`` path."""
    target = Path(target)

    if not plan_obj.verification_ok:
        raise ReverseMigrationError(
            "refusing to write: the reverse migration did not verify against "
            f"the markdown source ({plan_obj.report.as_dict()})"
        )
    if target.name != TRACKER_FILENAME:
        raise ReverseMigrationError(
            f"refusing to write {target}: this tool writes exactly one "
            f"{TRACKER_FILENAME} and must never touch any other file"
        )
    if target.exists() and not overwrite:
        raise ReverseMigrationError(
            f"refusing to overwrite the existing {target}; pass --overwrite if "
            "replacing the pre-cutover tracker is genuinely intended"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan_obj.tracker, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


# ------------------------------------------------------------------- cli ----


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--breeding-root", type=Path, default=DEFAULT_BREEDING_ROOT)
    parser.add_argument("--output", type=Path, default=None,
                        help=f"where to write (default: <project>/{TRACKER_FILENAME})")
    parser.add_argument("--overwrite", action="store_true",
                        help="allow replacing an existing tracker.json (required "
                             "in addition to --apply when the target already "
                             "exists; stricter than the spec, see module docstring)")
    parser.add_argument("--apply", action="store_true",
                        help="actually write (default: dry run)")
    args = parser.parse_args(argv)

    project_dir = args.breeding_root / args.slug
    result = plan(project_dir, args.registry, args.slug, args.template)
    report = result.report

    target = args.output or (project_dir / TRACKER_FILENAME)
    print(f"{args.slug}: {len(result.plant_ids)} plants read from markdown")
    print(f"  verification: {'OK' if report.ok else 'FAILED'} "
          f"({report.records_compared} records, {report.fields_compared} "
          "field values compared)")
    for label, values in (
        ("missing from produced tracker", report.missing_records),
        ("present in tracker but not on disk", report.extra_records),
        ("duplicated in produced tracker", report.duplicate_records),
    ):
        if values:
            print(f"    PROBLEM: {label}: {values}")
    # `record` is a plant id, or reverse_migration.PROJECT_RECORD_ID for the
    # project's own top-level fields -- both are reported the same way.
    for record, fields in sorted(report.lost_fields.items()):
        print(f"    PROBLEM: {record} lost fields: {fields}")
    for record, changes in sorted(report.changed_fields.items()):
        for change in changes:
            print(f"    PROBLEM: {record}.{change['field']} changed: "
                  f"{change['expected']!r} -> {change['got']!r}")
    for record, fields in sorted(report.illegal_fields.items()):
        print(f"    PROBLEM: {record} carries fields the markdown does not: "
              f"{fields}")
    for plant_id, orphans in sorted(report.unrepresented_observations.items()):
        for orphan in orphans:
            print(f"    PROBLEM: {plant_id} observation {orphan['timestamp']} "
                  f"is NOT represented in the produced tracker: "
                  f"{orphan['text'][:100]!r}")

    if not args.apply:
        print(f"  [dry run] nothing written; pass --apply to write {target}")
        return 0 if report.ok else 1
    if not report.ok:
        print("  REFUSING TO WRITE: verification failed -- escalate (plan 7.2 §7c)")
        return 1

    # apply() re-checks every gate itself (verification, filename, overwrite).
    # Those refusals are expected operator outcomes, not crashes: a second
    # --apply without --overwrite used to escape as a raw ReverseMigrationError
    # traceback while the verification-failure path above printed a clean
    # message and exited 1. Both now look the same to whoever is running it.
    try:
        written = apply(result, target, overwrite=args.overwrite)
    except ReverseMigrationError as exc:
        print(f"  REFUSING TO WRITE: {exc}")
        return 1
    print(f"  [written] {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
