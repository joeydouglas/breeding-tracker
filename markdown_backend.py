"""Markdown persistence backend for ``breeding_core``'s tracker functions.

Phase 2 / Task 2.1 of the breeding-tracker v2 refactor. ``breeding_core``'s
``load_tracker`` / ``save_tracker`` keep their exact JSON-era signatures and
their exact caller-visible data shape; only the bytes on disk change:

    <project>/tracker.json          (before)
    <project>/project.md            (after)
    <project>/plants/<ID>.md

All reading/writing is delegated to the Phase 1 modules in the sibling
``breeding-markdown`` repo (``project_markdown`` / ``plant_markdown``), which
own frontmatter parsing, declared-type coercion, verbatim body round-tripping
and atomic writes. Nothing in this module re-implements any of that.

Shape-preservation rules (why this module is more than two one-liners):

* **Exact key set.** ``read_plant(path, schema=...)`` materialises a default
  for every schema field, so a plant that never had ``corrected_reading``
  would come back carrying one. Callers (``update_plant``, the dashboard
  generators) see this dict verbatim, so each file is parsed twice: once
  without a schema to learn which keys the file actually holds, once with the
  schema to get correctly-typed values. The result is the typed values
  restricted to the keys that were really there.
* **Plant order.** A JSON ``plants`` list is ordered and at least one real
  project (spaced-paste) is not in ID order, so order is caller-visible
  state. It is recorded in ``project.md``'s ``plant_order`` frontmatter key
  and stripped back out on load. Plant files present on disk but absent from
  ``plant_order`` (a hand-added file) are appended in sorted order rather
  than dropped.
* **Whole-roster semantics.** ``json.dump`` rewrote the entire roster, so a
  plant removed from the list disappeared. ``save_tracker`` matches that by
  deleting plant files that are no longer in the roster.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DEFAULT_MARKDOWN_REPO = Path(__file__).resolve().parents[1] / "breeding-markdown"


def _markdown_repo() -> Path:
    """Locate the breeding-markdown repo.

    Defaults to the sibling checkout next to ``monitor-core`` (the layout in
    ``~/.hermes/breeding/_shared/``); ``BREEDING_MARKDOWN_DIR`` overrides it
    so a sandbox or the data-api container can point somewhere else without a
    code change.
    """
    override = os.environ.get("BREEDING_MARKDOWN_DIR")
    return Path(override).expanduser() if override else _DEFAULT_MARKDOWN_REPO


def _import_markdown_modules():
    repo = _markdown_repo()
    src = str(repo / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import plant_markdown
    import project_markdown

    return project_markdown, plant_markdown


PROJECT_FILE = "project.md"
PLANTS_DIR = "plants"
PLANTS_KEY = "plants"
ORDER_KEY = "plant_order"


# ------------------------------------------------------------- schemas ----


def _schemas():
    project_markdown, plant_markdown = _import_markdown_modules()
    templates = _markdown_repo() / "templates"
    return (
        project_markdown,
        plant_markdown,
        project_markdown.load_schema(templates / "project-template.md"),
        plant_markdown.load_schema(templates / "plant-template.md"),
    )


# ----------------------------------------------------------- validation ----


def _validate_plant_id(value):
    """Plant IDs reach this layer from Discord message text via a regex and
    become filenames, so an id that escapes ``plants/`` must be refused
    loudly rather than silently writing outside the project."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"plant record has a missing or non-string id: {value!r}")
    if value != value.strip():
        raise ValueError(f"plant id has leading/trailing whitespace: {value!r}")
    if value in (".", "..") or "/" in value or "\\" in value or "\0" in value:
        raise ValueError(f"unsafe plant id (path separator or reserved name): {value!r}")
    if Path(value).name != value or Path(value).is_absolute():
        raise ValueError(f"unsafe plant id (not a bare filename): {value!r}")
    return value


def _project_dir(tracker_file) -> Path:
    """``tracker_file`` is the JSON-era path the wrappers still pass
    (``BREEDING_DIR / 'tracker.json'``). Its PARENT is the project dir --
    the file itself is neither read nor written any more."""
    return Path(tracker_file).expanduser().parent


# ----------------------------------------------------------------- read ----


def _restrict_to_present(typed: dict, present_keys) -> dict:
    return {k: v for k, v in typed.items() if k in present_keys}


def load_tracker(tracker_file) -> dict:
    """Markdown-backed replacement for the JSON ``load_tracker``.

    Raises ``FileNotFoundError`` (exactly as the JSON ``open()`` did) when the
    project has no ``project.md``.
    """
    project_markdown, plant_markdown, project_schema, plant_schema = _schemas()

    directory = _project_dir(tracker_file)
    project_path = directory / PROJECT_FILE

    present = set(project_markdown.read_project(project_path))
    typed = project_markdown.read_project(project_path, schema=project_schema)
    tracker = _restrict_to_present(typed, present)

    order = tracker.pop(ORDER_KEY, None) or []
    # `body` is always synthesised by read_project; the JSON era had no such
    # key, so only surface it when it actually carries text.
    if not tracker.get(project_markdown.BODY_FIELD):
        tracker.pop(project_markdown.BODY_FIELD, None)

    plants_dir = directory / PLANTS_DIR
    on_disk = (
        {p.stem: p for p in sorted(plants_dir.glob("*.md"))}
        if plants_dir.is_dir()
        else {}
    )

    ordered_ids = [pid for pid in order if pid in on_disk]
    ordered_ids += sorted(pid for pid in on_disk if pid not in ordered_ids)

    plants = []
    for plant_id in ordered_ids:
        path = on_disk[plant_id]
        plant_present = set(plant_markdown.read_plant(path))
        plant_typed = plant_markdown.read_plant(path, schema=plant_schema)
        plants.append(_restrict_to_present(plant_typed, plant_present))

    tracker[PLANTS_KEY] = plants
    return tracker


# ---------------------------------------------------------------- write ----


def save_tracker(tracker, tracker_file) -> None:
    """Markdown-backed replacement for the JSON ``save_tracker``.

    The caller's dict is never mutated. Returns ``None``, as before.
    """
    if not isinstance(tracker, dict):
        raise TypeError(f"tracker must be a dict, got {type(tracker).__name__}")

    project_markdown, plant_markdown, project_schema, plant_schema = _schemas()

    directory = _project_dir(tracker_file)
    plants = tracker.get(PLANTS_KEY) or []
    if not isinstance(plants, list):
        raise TypeError(f"tracker['plants'] must be a list, got {type(plants).__name__}")

    # Validate the whole roster BEFORE writing anything: a bad id halfway
    # through must not leave a half-written project on disk.
    order = []
    for plant in plants:
        if not isinstance(plant, dict):
            raise TypeError(f"each plant must be a dict, got {type(plant).__name__}")
        plant_id = _validate_plant_id(plant.get("id"))
        if plant_id in order:
            raise ValueError(f"duplicate plant id in roster: {plant_id!r}")
        order.append(plant_id)

    project_fields = {k: v for k, v in tracker.items() if k != PLANTS_KEY}
    project_fields[ORDER_KEY] = order

    directory.mkdir(parents=True, exist_ok=True)
    project_markdown.write_project(
        directory / PROJECT_FILE, project_fields, schema=project_schema
    )

    plants_dir = directory / PLANTS_DIR
    for plant in plants:
        plant_markdown.write_plant(
            plants_dir / f"{plant['id']}.md", plant, schema=plant_schema
        )

    # Whole-roster rewrite semantics: drop files for plants no longer listed.
    if plants_dir.is_dir():
        keep = set(order)
        for stale in plants_dir.glob("*.md"):
            if stale.stem not in keep:
                stale.unlink()
