#!/usr/bin/env python3
"""Generate the missing live ``<project>/project.md`` from ``tracker.json`` (NICK-948).

Phase 3 (Tasks 3.1-3.6) proved the tracker.json -> markdown migration in a
SANDBOX only -- ``tracker_migration.assert_sandbox_destination`` explicitly
REFUSES to write anywhere under ``~/.hermes/breeding``, so none of that output
ever landed in a live project directory. Task 2.1 (``breeding_core`` commit
f2bbca5) meanwhile switched ``load_tracker()`` to read ``<project>/project.md``,
which therefore did not exist for any of the 6 live projects: every Discord
ingestion has raised ``FileNotFoundError`` since 2026-09-05 14:13.

This tool is the minimal forward-fix. It writes **only** ``project.md``, using:

* the live ``tracker.json`` project-level fields as the source of truth,
* ``registry.json`` for the two routing fields that exist nowhere else
  (``auto_create`` / ``plant_id_prefixes`` -- Task 3.0 §8),
* Phase 3's own ``tracker_migration.build_project_record`` to assemble the
  record, and Phase 1's ``project_markdown.write_project`` to serialise it,

so the result matches the canonical schema exactly rather than re-implementing
either step.

DELIBERATELY OUT OF SCOPE: ``plants/*.md``. The per-project plant cutover is
Task 7.2's job. This tool never creates, edits or deletes a plant file, and
never touches ``tracker.json`` (verified by md5 before/after).

``plant_order`` IS written, because ``markdown_backend.load_tracker`` reads it
to reproduce the JSON array's caller-visible ordering, and one real project
(spaced-paste) is not stored in ID order. The order is taken verbatim from
``tracker.json``'s ``plants`` array; ids with no file on disk are simply
ignored by ``load_tracker``, so recording the full order is safe and becomes
correct automatically as plant files land.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

from breeding_tracker import project_markdown  # noqa: E402
from breeding_tracker import tracker_migration  # noqa: E402

#: Same key ``markdown_backend`` pops off the project record on load.
ORDER_KEY = "plant_order"

DEFAULT_REGISTRY = Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
DEFAULT_TEMPLATE = _REPO_ROOT / "breeding_tracker" / "templates" / "project-template.md"


def build_record(tracker_path: Path, registry_path: Path, slug: str, template_path: Path) -> dict:
    """The exact dict that will be written to ``project.md``.

    Pure: reads only, writes nothing. Split out from :func:`generate` so a test
    can assert the record's contents without touching a live directory.
    """
    tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
    registry_entry = tracker_migration.load_registry_entry(registry_path, slug)
    schema = project_markdown.load_schema(template_path)

    record, _defaulted = tracker_migration.build_project_record(
        tracker, registry_entry, schema
    )
    record[ORDER_KEY] = [p["id"] for p in tracker.get("plants", [])]
    return record


def generate(project_dir: Path, registry_path: Path, slug: str,
             template_path: Path, *, force: bool = False) -> dict:
    """Write ``<project_dir>/project.md``. Returns the record written.

    Refuses to clobber an existing ``project.md`` unless ``force``: this runs
    against live data, and an already-present file may hold hand-entered
    project notes in its body that ``tracker.json`` has no copy of.
    """
    tracker_path = project_dir / "tracker.json"
    target = project_dir / "project.md"
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} already exists; refusing to overwrite live data "
            "(pass --force only if you are certain)"
        )

    md5_before = tracker_migration.file_md5(tracker_path)
    record = build_record(tracker_path, registry_path, slug, template_path)
    schema = project_markdown.load_schema(template_path)
    project_markdown.write_project(target, record, schema=schema)

    md5_after = tracker_migration.file_md5(tracker_path)
    if md5_before != md5_after:  # pragma: no cover - nothing here writes it
        raise RuntimeError(
            f"{tracker_path} changed during generation ({md5_before} -> "
            f"{md5_after}); this tool must never write it"
        )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="+", help="registry slugs to generate")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--breeding-root", type=Path,
                        default=Path.home() / ".hermes" / "breeding")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for slug in args.slugs:
        project_dir = args.breeding_root / slug
        if args.dry_run:
            record = build_record(
                project_dir / "tracker.json", args.registry, slug, args.template
            )
            print(f"[dry-run] {slug}: {len(record)} fields, "
                  f"{len(record[ORDER_KEY])} plants in plant_order")
        else:
            record = generate(project_dir, args.registry, slug, args.template,
                              force=args.force)
            print(f"[written] {project_dir / 'project.md'}: {len(record)} fields, "
                  f"{len(record[ORDER_KEY])} plants in plant_order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
