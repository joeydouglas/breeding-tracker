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

  **One documented exception: ``observation_log``.** Phase 1 makes it the
  markdown BODY rather than a frontmatter field, and ``plant_markdown``
  guarantees it on BOTH sides -- ``write_plant`` always emits a body and
  ``read_plant`` always returns ``observation_log`` (see its "Always return
  the body ... omitting it here would break read_plant(write_plant(x))"
  comment). It is therefore a schema-guaranteed field, not an accident: a
  plant dict saved WITHOUT ``observation_log`` loads back WITH
  ``observation_log: ''``. Restricting it away here would contradict the
  Phase 1 contract and make the round-trip asymmetric, so it is deliberately
  exempted from the restrict-to-present rule via
  ``_ALWAYS_PRESENT_PLANT_KEYS``, which ``_restrict_to_present`` consults
  directly. That exemption is enforced HERE rather than merely inherited
  from Phase 1: if ``read_plant`` ever stopped adding the body key to its
  schema-less output, this module would otherwise start silently dropping
  every plant's observation log. All six real projects' plants already carry
  the field, so no real record is affected; only a synthetic
  ``{id, status, vigor}`` plant sees the addition. Regression-tested in
  ``test_tracker_persistence.py`` and ``test_review_round1_fixes.py``.
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
import tempfile
from pathlib import Path

from plant_record import CANONICAL_ID_KEY, ID_KEYS, plant_id_of

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
    src = repo / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        import plant_markdown
        import project_markdown
    except ModuleNotFoundError as exc:
        # A bare "No module named 'plant_markdown'" tells an operator nothing
        # about where this looked or how to redirect it. Name both.
        raise ModuleNotFoundError(
            f"could not import the Phase 1 breeding-markdown modules from "
            f"{src} (repo root {repo}). Set the BREEDING_MARKDOWN_DIR "
            "environment variable to the breeding-markdown checkout if it "
            f"does not sit next to monitor-core. Original error: {exc}"
        ) from exc

    return project_markdown, plant_markdown


PROJECT_FILE = "project.md"
PLANTS_DIR = "plants"
PLANTS_KEY = "plants"
ORDER_KEY = "plant_order"

# Keys ``plant_markdown`` guarantees on every read regardless of what the
# file held (see the module docstring's "Exact key set" note). Restricting
# these away would break Phase 1's read_plant(write_plant(x)) symmetry, so
# ``_restrict_to_present`` always keeps them -- enforced locally rather than
# relying on Phase 1 continuing to add them for us.
_ALWAYS_PRESENT_PLANT_KEYS = frozenset({"observation_log"})


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
    loudly rather than silently writing outside the project.

    Scope note: this rejects path separators, NUL, and the relative-directory
    names ``'.'``/``'..'``. It deliberately does NOT check Windows reserved
    device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) -- this deployment is
    Linux-only and those are legal filenames here, so the error message names
    exactly what is enforced rather than implying broader coverage.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"plant record has a missing or non-string {CANONICAL_ID_KEY}: {value!r}"
        )
    if value != value.strip():
        raise ValueError(f"plant id has leading/trailing whitespace: {value!r}")
    if value in (".", "..") or "/" in value or "\\" in value or "\0" in value:
        raise ValueError(
            "unsafe plant id (path separator, NUL, or the relative-directory "
            f"names '.' / '..'): {value!r}"
        )
    if Path(value).name != value or Path(value).is_absolute():
        raise ValueError(f"unsafe plant id (not a bare filename): {value!r}")
    return value


def _plant_id_for_write(plant):
    """The validated id of a plant about to be written.

    NICK-965: reads either accepted spelling via ``plant_id_of`` -- this
    module used to hard-code ``plant.get("id")``, which made it unable to
    save the very corpus Phase 3's migration produced (all live plant files
    are ``plant_id:``-keyed). ``plant_id_of`` raises on a record whose two
    id keys disagree, and returns ``None`` for one carrying neither, so the
    informative ``_validate_plant_id`` error is still what a hand-edited,
    id-less file produces.
    """
    return _validate_plant_id(plant_id_of(plant))


def _project_dir(tracker_file) -> Path:
    """``tracker_file`` is the JSON-era path the wrappers still pass
    (``BREEDING_DIR / 'tracker.json'``). Its PARENT is the project dir --
    the file itself is neither read nor written any more."""
    return Path(tracker_file).expanduser().parent


# ----------------------------------------------------------------- read ----


def _restrict_to_present(typed: dict, present_keys, always_keep=frozenset()) -> dict:
    """Keep only the keys the file really held, plus any ``always_keep`` key.

    ``always_keep`` exists so this module enforces the ``observation_log``
    guarantee itself (see ``_ALWAYS_PRESENT_PLANT_KEYS``) rather than relying
    on Phase 1's ``read_plant`` continuing to inject the body key into its
    schema-less output. If that ever changed, the schema-typed read still
    carries the body, and this keeps it.
    """
    return {
        k: v for k, v in typed.items() if k in present_keys or k in always_keep
    }


def load_tracker(tracker_file) -> dict:
    """Markdown-backed replacement for the JSON ``load_tracker``.

    Raises ``FileNotFoundError`` (exactly as the JSON ``open()`` did) when the
    project has no ``project.md``.

    FAIL-LOUD ON CORRUPTION (deliberate policy). A single unparseable file --
    ``project.md`` or ANY ONE ``plants/<ID>.md`` -- makes this whole call
    raise Phase 1's ``MalformedFrontmatterError`` / ``UnsafeYamlError``. There
    is no per-plant isolation and no skip-and-warn. Since ``plants/<ID>.md``
    is now the record of truth, a skipped plant would be ABSENT from the
    returned roster, and ``save_tracker``'s whole-roster rewrite semantics
    would then DELETE its file on the very next observation -- turning one
    recoverable parse error into permanent data loss. Refusing to serve a
    partial roster is the safe failure. This matches the precedent set
    elsewhere in the refactor for the record of truth (as opposed to
    ``migration.py``, which isolates per-repo failures because each repo
    there is an independent, retryable unit of work with no cross-repo
    delete semantics).
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
        plants.append(
            _restrict_to_present(
                plant_typed, plant_present, _ALWAYS_PRESENT_PLANT_KEYS
            )
        )

    tracker[PLANTS_KEY] = plants
    return tracker


# ---------------------------------------------------------------- write ----


def save_plant(plant, project_dir) -> None:
    """Write ONE plant's record to ``<project_dir>/plants/<ID>.md``.

    Backs ``breeding_core.update_markdown()``, which the six wrappers expose
    directly. Unlike ``save_tracker`` this is a merge, not a whole-roster
    rewrite: the supplied fields are laid over whatever the file already
    holds, so calling it with a partial plant dict can never truncate a
    stored record, and it never touches ``project.md`` or any other plant.
    """
    if not isinstance(plant, dict):
        raise TypeError(f"plant must be a dict, got {type(plant).__name__}")

    project_markdown, plant_markdown, _project_schema, plant_schema = _schemas()
    plant_id = _plant_id_for_write(plant)

    path = Path(project_dir).expanduser() / PLANTS_DIR / f"{plant_id}.md"
    merged = {}
    if path.exists():
        existing_present = set(plant_markdown.read_plant(path))
        existing_typed = plant_markdown.read_plant(path, schema=plant_schema)
        merged.update(
            _restrict_to_present(
                existing_typed, existing_present, _ALWAYS_PRESENT_PLANT_KEYS
            )
        )
    # NICK-965 stage-2 review (I1): a plain merged.update(plant) can leave a
    # file carrying BOTH id spellings if the on-disk file uses one spelling
    # (say 'id', a Mule-Fuel legacy record) and the caller's `plant` dict uses
    # the other ('plant_id', e.g. a fresh update built by a config-aware
    # caller) -- update() layers keys, it doesn't replace them. A file with
    # both keys is then only ever one edit away from `plant_id_of`'s
    # "conflicting ids" ValueError if the two spellings ever disagree, and
    # even while they happen to agree it violates the "records keep whichever
    # single spelling they arrived with" invariant this whole fix is built
    # on. Drop every OTHER id key before merging in `plant`'s own -- the
    # write path picks exactly one spelling, same guarantee `update_plant`
    # already has for the JSON-roster path.
    incoming_id_keys = {k for k in ID_KEYS if k in plant}
    for key in ID_KEYS:
        if key not in incoming_id_keys:
            merged.pop(key, None)
    merged.update(plant)

    plant_markdown.write_plant(path, merged, schema=plant_schema)


def save_tracker(tracker, tracker_file) -> None:
    """Markdown-backed replacement for the JSON ``save_tracker``.

    The caller's dict is never mutated. Returns ``None``, as before.

    WRITE ORDERING / ATOMICITY. ``json.dump`` wrote one file, so a failed save
    could not half-apply a roster. This backend writes ``project.md`` plus one
    file per plant, so the roster is staged in two passes before any real file
    is touched:

    1. **Validation pass** -- every plant's id is checked (type, whitespace,
       path-safety, duplicates) with nothing written.
    2. **Render pass** -- ``project.md`` and every plant file are rendered in
       full into a scratch directory inside the project dir. This is what
       catches a value-level failure (an unserialisable field value, a
       non-string ``observation_log``) that only surfaces once a specific
       plant is actually rendered. Previously such a failure on plant #3 of 4
       left plants #1-#2 rewritten and ``project.md`` already carrying the
       new ``plant_order``.

    Only once BOTH passes succeed for the whole roster does anything get
    written to the real paths. The individual writes are each atomic via
    Phase 1's ``mkstemp`` + ``os.replace``; the roster as a whole is still not
    one filesystem transaction (a mid-sequence ``ENOSPC``/crash can leave some
    files updated), but every failure this code can raise on its own is now
    raised before the first real byte is written.
    """
    if not isinstance(tracker, dict):
        raise TypeError(f"tracker must be a dict, got {type(tracker).__name__}")

    project_markdown, plant_markdown, project_schema, plant_schema = _schemas()

    directory = _project_dir(tracker_file)
    plants = tracker.get(PLANTS_KEY) or []
    if not isinstance(plants, list):
        raise TypeError(f"tracker['plants'] must be a list, got {type(plants).__name__}")

    # Pass 1 -- validate the whole roster before writing anything.
    order = []
    for plant in plants:
        if not isinstance(plant, dict):
            raise TypeError(f"each plant must be a dict, got {type(plant).__name__}")
        plant_id = _plant_id_for_write(plant)
        if plant_id in order:
            raise ValueError(f"duplicate plant id in roster: {plant_id!r}")
        order.append(plant_id)

    project_fields = {k: v for k, v in tracker.items() if k != PLANTS_KEY}
    project_fields[ORDER_KEY] = order

    directory.mkdir(parents=True, exist_ok=True)
    plants_dir = directory / PLANTS_DIR

    # Pass 2 -- render everything into a scratch dir. A render failure on any
    # plant aborts here, with every real file still untouched. The scratch
    # dir lives inside the project dir so it is on the same filesystem and is
    # swept up by the same backup/ignore rules as the rest of the project.
    with tempfile.TemporaryDirectory(
        dir=str(directory), prefix=".save_tracker-staging-"
    ) as staging:
        staging_dir = Path(staging)
        project_markdown.write_project(
            staging_dir / PROJECT_FILE, project_fields, schema=project_schema
        )
        for plant, plant_id in zip(plants, order):
            plant_markdown.write_plant(
                staging_dir / PLANTS_DIR / f"{plant_id}.md", plant, schema=plant_schema
            )

    # Both passes succeeded: now write for real. Re-rendering through
    # write_plant/write_project (rather than moving the staged files) keeps
    # Phase 1's own atomic-replace and existing-file-mode handling intact --
    # moving a scratch file into place would reset a git-tracked file's mode.
    project_markdown.write_project(
        directory / PROJECT_FILE, project_fields, schema=project_schema
    )
    for plant, plant_id in zip(plants, order):
        plant_markdown.write_plant(
            plants_dir / f"{plant_id}.md", plant, schema=plant_schema
        )

    # Whole-roster rewrite semantics: drop files for plants no longer listed.
    if plants_dir.is_dir():
        keep = set(order)
        for stale in plants_dir.glob("*.md"):
            if stale.stem not in keep:
                stale.unlink()
