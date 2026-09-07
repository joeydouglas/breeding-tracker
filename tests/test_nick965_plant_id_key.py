"""NICK-965 -- TDD: ``plant_id`` is the canonical plant key for markdown.

WHY THIS SUITE EXISTS. Every pre-existing test in this package builds its
plant fixtures either synthetically (``{'id': 'SB01', ...}``) or from a
project's JSON-era ``tracker.json`` (also ``id``-keyed), and then feeds them
THROUGH the markdown backend. That is a closed loop: the backend wrote what
the test handed it and read the same spelling back, so 414 tests passed while
the code was incapable of reading the corpus that is ACTUALLY on disk. The
real ``plants/<ID>.md`` files carry ``plant_id:`` frontmatter -- 5 of the 6
live projects are 100% ``plant_id``, and ``mule-fuel-x-nana-glue`` is mixed
(36 ``id`` files, 9 ``plant_id``).

PROVENANCE NOTE (verified here, and it corrects the assumption recorded on
NICK-701). The live ``plant_id:`` files are NOT the migration tool's output.
``tracker_migration._plant_id`` reads ``plant.get("id")`` and
``build_plant_record`` copies the source record verbatim, so a real Phase 3
migration emits ``id:``. The ``plant_id``-keyed files on disk are residue of
the OLD derived-view ``update_markdown()`` writer, which wrote exactly
``plant_id``/``cross``/``status`` -- which is precisely the 3-key shape every
one of these files has. That does not change the fix (Joey's canonical-key
decision stands, and this code must read what is on disk either way), but it
does mean the live markdown corpus is impoverished rather than merely
mis-keyed, and Task 7.2 step 2's re-migration is what restores the missing
fields. It also means the breeding-markdown plant template still declares
the field as ``id``; aligning that template is re-migration work, out of
scope here.

So the tests below are written against REAL on-disk data shapes:

* ``plant_id`` -- what ``markdown_backend.load_tracker`` returns for every
  live migrated project (asserted directly against the real project dirs).
* ``id`` -- what ``json_backend.load_tracker`` returns, which is correct for
  its era and is part of NICK-949's byte-for-byte rollback contract.

Joey's decision (NICK-701, 2026-09-07): ``plant_id`` is canonical going
forward. ``id`` remains READABLE as the legacy spelling so mule-fuel's 36
un-remigrated files and every rolled-back ``tracker.json`` keep working
until Task 7.2 step 2 re-migrates them.

Sandbox-only: real project directories are read-only inputs; every write
goes to a pytest ``tmp_path``.
"""

import json
import re
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_ROOT = MONITOR_CORE_DIR.parents[1]

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

import breeding_core as core  # noqa: E402
import markdown_backend  # noqa: E402

LIVE_PROJECTS = sorted(p.parent.name for p in BREEDING_ROOT.glob("*/project.md"))


# ------------------------------------------------------------- helpers ----


def _config(project_dir, backend=None, auto_create=False):
    config = {
        'BREEDING_DIR': project_dir,
        'TRACKER_FILE': project_dir / 'tracker.json',
        'CROSS_NAME': 'Sandbox Cross',
        'AUTO_CREATE': auto_create,
        'GITHUB_REPO': 'sandbox/none',
        'DISABLE_GITHUB_PUSH': True,
    }
    if backend is not None:
        config['BACKEND'] = backend
    return config


@pytest.fixture
def no_side_effects(monkeypatch):
    """update_plant shells out to generate_dashboard.py and pushes to git."""
    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **k: None)
    monkeypatch.setattr(core, 'push_to_github', lambda *a, **k: None)


# ================================================================== #
# 1. The real corpus's shape, asserted against the live project dirs #
# ================================================================== #


def test_at_least_one_live_project_is_present():
    """Guard against this whole file silently degrading into skips."""
    assert LIVE_PROJECTS, "no live migrated project found under the breeding root"


@pytest.mark.parametrize("project", LIVE_PROJECTS)
def test_live_markdown_projects_load_with_a_usable_plant_id(project):
    """Every plant in every live project must expose an id under one of the
    two accepted spellings -- and ``plant_id_of`` must find it.

    This is the assertion whose absence let NICK-965 ship: it reads the REAL
    ``plants/*.md`` files rather than fixtures the backend itself produced.
    """
    tracker = markdown_backend.load_tracker(
        BREEDING_ROOT / project / "tracker.json"
    )
    for plant in tracker["plants"]:
        assert core.plant_id_of(plant), (
            f"{project}: a live plant record exposes no usable id "
            f"(keys={sorted(plant)})"
        )


def test_the_migrated_corpus_really_uses_plant_id_not_id():
    """Pins the premise of this fix. If a future change re-migrates the corpus
    to some other spelling, this fails loudly rather than letting the code
    drift away from the data again."""
    seen = set()
    for project in LIVE_PROJECTS:
        tracker = markdown_backend.load_tracker(
            BREEDING_ROOT / project / "tracker.json"
        )
        for plant in tracker["plants"]:
            seen.update(k for k in plant if k in {"plant_id", "id"})
    assert "plant_id" in seen, (
        "no live plant uses 'plant_id' -- the premise of NICK-965 no longer holds"
    )


# ====================================================== #
# 2. plant_id_of(): the canonical accessor's own contract #
# ====================================================== #


def test_plant_id_of_prefers_the_canonical_plant_id_key():
    assert core.plant_id_of({"plant_id": "Ltz01", "status": "culled"}) == "Ltz01"


def test_plant_id_of_falls_back_to_the_legacy_id_key():
    """mule-fuel's 36 un-remigrated files, and every JSON-backend tracker."""
    assert core.plant_id_of({"id": "MG01", "status": "culled"}) == "MG01"


def test_plant_id_of_returns_none_for_a_plant_with_neither_key():
    """A hand-edited/corrupted record must degrade to None so save_tracker's
    own informative ValueError is the error that surfaces -- not a KeyError
    from the roster scan (the NICK-948-era hardening, preserved)."""
    assert core.plant_id_of({"status": "keeper"}) is None


def test_plant_id_of_rejects_a_record_carrying_two_different_ids():
    """Never silently pick one. A file with both spellings disagreeing is a
    corrupt record, and guessing which one is authoritative could route an
    observation onto the wrong plant."""
    with pytest.raises(ValueError, match="conflicting"):
        core.plant_id_of({"plant_id": "Ltz01", "id": "Ltz07"})


def test_plant_id_of_accepts_a_record_where_both_keys_agree():
    assert core.plant_id_of({"plant_id": "Ltz01", "id": "Ltz01"}) == "Ltz01"


def test_plant_id_of_ignores_a_null_canonical_key():
    """A schema-filled plant can carry ``plant_id: None``; the legacy key
    still wins over an absent value rather than the record reading as id-less."""
    assert core.plant_id_of({"plant_id": None, "id": "MG01"}) == "MG01"


# ================================================== #
# 3. Backend-aware key selection for NEW plant records #
# ================================================== #


def test_plant_id_key_is_plant_id_for_the_markdown_backend(tmp_path):
    assert core.plant_id_key(_config(tmp_path, 'markdown')) == 'plant_id'


def test_plant_id_key_is_id_for_the_json_backend(tmp_path):
    """The JSON backend's on-disk format is the pre-Phase-2 tracker.json,
    restored verbatim for NICK-949's rollback contract. That era used 'id'
    and a rolled-back project must keep producing exactly that."""
    assert core.plant_id_key(_config(tmp_path, 'json')) == 'id'


def test_plant_id_key_defaults_to_the_markdown_spelling(tmp_path):
    assert core.plant_id_key(_config(tmp_path)) == 'plant_id'


def test_every_registered_backend_declares_a_plant_id_key():
    """A backend added to STORAGE_BACKENDS without an entry here would fall
    back to some default and silently write the wrong spelling."""
    assert set(core.PLANT_ID_KEYS) == set(core.STORAGE_BACKENDS)


def test_make_blank_plant_uses_the_canonical_key_by_default():
    plant = core.make_blank_plant("Ltz01", "Lantz")
    assert plant["plant_id"] == "Ltz01"
    assert "id" not in plant


def test_make_blank_plant_can_emit_the_legacy_key_for_the_json_backend():
    plant = core.make_blank_plant("Ltz01", "Lantz", id_key="id")
    assert plant["id"] == "Ltz01"
    assert "plant_id" not in plant


def test_make_blank_plant_field_set_is_otherwise_unchanged():
    """Only the id key's SPELLING changes; the record's shape is contract."""
    canonical = core.make_blank_plant("Ltz01", "Lantz")
    legacy = core.make_blank_plant("Ltz01", "Lantz", id_key="id")
    assert set(canonical) - {"plant_id"} == set(legacy) - {"id"}
    for field in set(canonical) - {"plant_id"}:
        assert canonical[field] == legacy[field]


# ============================================================== #
# 4. update_plant() against REAL migrated data -- the actual bug  #
# ============================================================== #


def _sandbox_copy_of_live_project(project, tmp_path):
    """A byte-copy of a real migrated project dir. Copied, not regenerated
    through the backend, so the sandbox carries the migration tool's OWN
    frontmatter spelling rather than one this test chose.

    NICK-965 stage-2 review (I2): an unfiltered copytree of a live project
    dir pulls in that project's photo/dashboard/export payload too -- for
    mule-fuel-x-nana-glue that's ~225 MB per test, times pytest's default
    retention of the last 3 run dirs, which was enough to exhaust /tmp's
    disk quota outright (a full-suite run died with
    'OSError: Disk quota exceeded' / INTERNALERROR, not a clean test
    failure). This test only ever reads tracker.json, project.md, plants/,
    and the wrapper -- ignore everything else so the copy is representative
    of the real corpus's SHAPE without also copying its unrelated bulk.
    """
    import shutil

    source = BREEDING_ROOT / project
    if not (source / "project.md").exists():
        pytest.skip(f"{project} is not migrated to markdown")
    sandbox = tmp_path / project
    shutil.copytree(
        source,
        sandbox,
        ignore=shutil.ignore_patterns(
            "cache", "dashboard", "photo_staging", "__pycache__",
            "*.tar.gz", "*.json", "*.txt", "*.html",
            "auto_process_breeding.py", "breeding_tools.py",
            "discord_monitor.py", "fetch_breeding_messages.py",
            "generate_dashboard.py", "observation_logger.py",
            "photo_handler.py", "process_recent.py",
        ),
    )
    # tracker.json is deliberately NOT ignored above by name alone (the glob
    # "*.json" would also catch it) -- restore it explicitly, since several
    # tests in this file read it as the source of truth.
    tracker_src = source / "tracker.json"
    if tracker_src.exists():
        shutil.copy2(tracker_src, sandbox / "tracker.json")
    return sandbox


def test_update_plant_finds_a_real_plant_id_keyed_plant(tmp_path, no_side_effects):
    """THE NICK-965 REGRESSION. Against the real Lantz corpus, an observation
    naming a real plant used to return "Plant Ltz01 not found" because the
    roster scan looked for 'id' while every migrated record carries
    'plant_id'."""
    sandbox = _sandbox_copy_of_live_project("lantz", tmp_path)
    config = _config(sandbox, 'markdown', auto_create=False)

    tracker = core.load_tracker_for(config)
    plant_id = core.plant_id_of(tracker["plants"][0])

    result = core.update_plant(
        plant_id, core.parse_observation(f"{plant_id} vigor 8, gassy terps"), config
    )

    assert "\u274c" not in result, result
    assert plant_id in result

    reloaded = core.load_tracker_for(config)
    plant = next(
        p for p in reloaded["plants"] if core.plant_id_of(p) == plant_id
    )
    assert plant["vigor"] == "8"
    # NOTE: only fields the live file already carries are asserted. The live
    # markdown corpus is IMPOVERISHED -- Lantz's plant files hold just
    # plant_id/cross/status plus the body, because they are residue of the
    # old derived-view writer, not full migration output (see this module's
    # docstring). Restoring the missing fields is Task 7.2 step 2's
    # re-migration, not NICK-965's job; this test pins that the plant is
    # FOUND and UPDATED, which is the bug being fixed.
    assert f"{plant_id} vigor 8" in plant["observation_log"]


def test_update_plant_round_trips_real_data_without_renaming_the_key(
    tmp_path, no_side_effects
):
    """A save must not silently rewrite the corpus's frontmatter spelling.
    The key a record arrived with is DATA; normalising it on every write
    would churn all 89 live plant files behind the operator's back."""
    sandbox = _sandbox_copy_of_live_project("lantz", tmp_path)
    config = _config(sandbox, 'markdown')

    tracker = core.load_tracker_for(config)
    plant_id = core.plant_id_of(tracker["plants"][0])
    frontmatter_before = (
        (sandbox / "plants" / f"{plant_id}.md")
        .read_text(encoding="utf-8")
        .split("\n---\n", 1)[0]
    )
    assert "plant_id:" in frontmatter_before, "premise: real file is plant_id-keyed"

    core.update_plant(plant_id, core.parse_observation(f"{plant_id} keeper"), config)

    frontmatter_after = (
        (sandbox / "plants" / f"{plant_id}.md")
        .read_text(encoding="utf-8")
        .split("\n---\n", 1)[0]
    )
    # The record keeps the spelling it arrived with, and does NOT sprout a
    # second, duplicate id key. (Field ORDER within the frontmatter is not
    # asserted: plant_id sorts after the schema-declared fields because the
    # breeding-markdown plant template still declares the field as `id`.
    # Aligning the template is Task 7.2 step 2's re-migration work -- it
    # changes the migration tool's output, not this backend's behaviour.)
    assert "plant_id:" in frontmatter_after
    assert "\nid:" not in frontmatter_after
    assert not frontmatter_after.startswith("id:")


def test_update_plant_reports_not_found_for_a_genuinely_absent_plant(
    tmp_path, no_side_effects
):
    """The clean rejection AUTO_CREATE=False projects rely on must still
    happen for a plant that really is absent -- the fix must not make every
    id match something."""
    sandbox = _sandbox_copy_of_live_project("lantz", tmp_path)
    config = _config(sandbox, 'markdown', auto_create=False)

    result = core.update_plant(
        "Ltz99", core.parse_observation("Ltz99 vigor 8"), config
    )
    assert "\u274c" in result and "Ltz99" in result


def test_auto_create_on_real_markdown_data_saves_cleanly(tmp_path, no_side_effects):
    """The AUTO_CREATE=True crash. Against a real migrated project, an
    unmatched id used to auto-create a plant keyed 'id' and then die inside
    save_tracker with "plant record has a missing or non-string id: None" --
    after update_plant had already entered its write path."""
    sandbox = _sandbox_copy_of_live_project("paloma-coma", tmp_path)
    config = _config(sandbox, 'markdown', auto_create=True)

    result = core.update_plant(
        "PC99", core.parse_observation("PC99 vigor 7, keeper"), config
    )
    assert "\u274c" not in result, result

    reloaded = core.load_tracker_for(config)
    created = next(p for p in reloaded["plants"] if core.plant_id_of(p) == "PC99")
    assert created["plant_id"] == "PC99", "a NEW plant must use the canonical key"
    assert (sandbox / "plants" / "PC99.md").is_file()


def test_a_legacy_id_keyed_live_plant_still_works(tmp_path, no_side_effects):
    """mule-fuel-x-nana-glue is MIXED: 36 files still carry the pre-migration
    'id:' spelling. Those must keep matching (and keep their own spelling on
    disk) until Task 7.2 step 2 re-migrates the project -- this fix must not
    break the half of that project that works today."""
    sandbox = _sandbox_copy_of_live_project("mule-fuel-x-nana-glue", tmp_path)
    config = _config(sandbox, 'markdown', auto_create=False)

    tracker = core.load_tracker_for(config)
    legacy = next(
        (p for p in tracker["plants"] if "id" in p and "plant_id" not in p), None
    )
    if legacy is None:
        pytest.skip("mule-fuel no longer has legacy id-keyed plants (re-migrated)")
    plant_id = legacy["id"]

    result = core.update_plant(
        plant_id, core.parse_observation(f"{plant_id} vigor 6"), config
    )
    assert "\u274c" not in result, result

    text = (sandbox / "plants" / f"{plant_id}.md").read_text(encoding="utf-8")
    frontmatter = text.split("\n---\n", 1)[0]
    # The invariant is the SPELLING, not the field ORDER. NICK-966 removed
    # `id` from plant-template.md (canonical is `plant_id`), so a legacy
    # record's `id` key is no longer schema-ordered and now lands in the
    # unordered tail of the frontmatter instead of on line 2. What must still
    # hold -- and is what this test exists for -- is that the record keeps
    # its OWN spelling and does not silently gain the other one, which is the
    # dual-key shape `plant_id_of` rejects as corrupt.
    assert re.search(rf"^id: {plant_id}$", frontmatter, re.M), (
        f"a legacy record's own spelling was rewritten: {frontmatter!r}"
    )
    assert "plant_id:" not in frontmatter, (
        f"a legacy record gained the other spelling too: {frontmatter!r}"
    )


def test_both_spellings_coexist_in_one_roster_save(tmp_path, no_side_effects):
    """mule-fuel's real state: one project, one save, both spellings. The
    whole-roster write must not trip over the mixture."""
    sandbox = _sandbox_copy_of_live_project("mule-fuel-x-nana-glue", tmp_path)
    config = _config(sandbox, 'markdown')

    tracker = core.load_tracker_for(config)
    spellings = {
        "plant_id" if "plant_id" in p else "id" for p in tracker["plants"]
    }
    if spellings != {"plant_id", "id"}:
        pytest.skip("mule-fuel is no longer mixed (re-migrated)")

    core.save_tracker_for(tracker, config)
    assert core.load_tracker_for(config) == tracker


# ================================================== #
# 5. The JSON backend keeps its own native 'id' shape #
# ================================================== #


@pytest.fixture
def json_era_tracker():
    """The shape json_backend.load_tracker really returns: the pre-Phase-2
    tracker.json, which is 'id'-keyed throughout."""
    return {
        "cross_name": "Sandbox Cross",
        "plants": [
            {"id": "SB01", "status": "active", "vigor": "8", "observation_log": ""},
        ],
    }


def test_real_live_tracker_json_files_are_id_keyed():
    """Asserted against the actual on-disk JSON files, not a fixture: this is
    why json_backend must NOT be moved to 'plant_id'."""
    trackers = sorted(BREEDING_ROOT.glob("*/tracker.json"))
    if not trackers:
        pytest.skip("no real tracker.json present")
    for path in trackers:
        for plant in json.loads(path.read_text(encoding="utf-8")).get("plants", []):
            assert "id" in plant, f"{path.parent.name}: JSON plant is not 'id'-keyed"


def test_json_backend_matching_still_works(tmp_path, json_era_tracker, no_side_effects):
    config = _config(tmp_path, 'json')
    core.save_tracker_for(json_era_tracker, config)

    result = core.update_plant(
        "SB01", core.parse_observation("SB01 vigor 9, keeper"), config
    )
    assert "\u274c" not in result, result

    stored = json.loads((tmp_path / "tracker.json").read_text(encoding="utf-8"))
    plant = next(p for p in stored["plants"] if p["id"] == "SB01")
    assert plant["vigor"] == 9
    assert plant["status"] == "keeper"


def test_json_backend_auto_create_emits_the_legacy_id_key(
    tmp_path, json_era_tracker, no_side_effects
):
    """A rolled-back project must keep producing the ORIGINAL tracker.json
    shape -- a new plant keyed 'plant_id' would corrupt the rollback format
    NICK-949 restored byte-for-byte."""
    config = _config(tmp_path, 'json', auto_create=True)
    core.save_tracker_for(json_era_tracker, config)

    core.update_plant("SB99", core.parse_observation("SB99 vigor 5"), config)

    stored = json.loads((tmp_path / "tracker.json").read_text(encoding="utf-8"))
    created = next(p for p in stored["plants"] if p.get("id") == "SB99")
    assert "plant_id" not in created


def test_json_backend_reports_not_found_without_auto_create(
    tmp_path, json_era_tracker, no_side_effects
):
    config = _config(tmp_path, 'json', auto_create=False)
    core.save_tracker_for(json_era_tracker, config)

    result = core.update_plant("SB99", core.parse_observation("SB99 vigor 5"), config)
    assert "\u274c" in result


# ============================================ #
# 6. The markdown backend's own write contract #
# ============================================ #


def test_markdown_backend_accepts_a_plant_id_keyed_roster(tmp_path):
    tracker = {
        "cross_name": "Sandbox Cross",
        "plants": [{"plant_id": "SB01", "status": "active", "observation_log": ""}],
    }
    markdown_backend.save_tracker(tracker, tmp_path / "tracker.json")
    assert (tmp_path / "plants" / "SB01.md").is_file()
    assert markdown_backend.load_tracker(tmp_path / "tracker.json") == tracker


def test_markdown_backend_still_accepts_a_legacy_id_keyed_roster(tmp_path):
    tracker = {
        "cross_name": "Sandbox Cross",
        "plants": [{"id": "SB01", "status": "active", "observation_log": ""}],
    }
    markdown_backend.save_tracker(tracker, tmp_path / "tracker.json")
    assert (tmp_path / "plants" / "SB01.md").is_file()
    assert markdown_backend.load_tracker(tmp_path / "tracker.json") == tracker


def test_markdown_backend_rejects_an_id_less_plant_with_a_clear_error(tmp_path):
    tracker = {"plants": [{"status": "active"}]}
    with pytest.raises(ValueError, match="plant_id"):
        markdown_backend.save_tracker(tracker, tmp_path / "tracker.json")


def test_markdown_backend_rejects_a_conflicting_pair_of_ids(tmp_path):
    tracker = {"plants": [{"plant_id": "SB01", "id": "SB02"}]}
    with pytest.raises(ValueError, match="conflicting"):
        markdown_backend.save_tracker(tracker, tmp_path / "tracker.json")


def test_save_plant_accepts_the_canonical_key(tmp_path):
    markdown_backend.save_plant({"plant_id": "SB01", "status": "keeper"}, tmp_path)
    assert (tmp_path / "plants" / "SB01.md").is_file()


def _frontmatter_lines(plant_file):
    text = plant_file.read_text(encoding="utf-8")
    return text.split("---")[1].splitlines()


def test_save_plant_merge_never_leaves_both_id_spellings_legacy_then_canonical(tmp_path):
    """NICK-965 stage-2 review (I1): save_plant's merge is `merged.update(plant)`
    layered over whatever the file already had -- update() layers keys, it
    doesn't replace them, so an on-disk 'id'-keyed record (a Mule-Fuel-style
    legacy write) merged with a fresh 'plant_id'-keyed update used to leave
    the file holding BOTH spellings. That's not just untidy: plant_id_of()
    raises 'conflicting ids' the moment the two ever disagree, so a
    dual-keyed file is one edit away from becoming permanently unloadable.
    """
    markdown_backend.save_plant({"id": "MG01", "cross": "Test", "status": "active"}, tmp_path)
    markdown_backend.save_plant({"plant_id": "MG01", "vigor": "9"}, tmp_path)

    lines = _frontmatter_lines(tmp_path / "plants" / "MG01.md")
    assert any(line.startswith("plant_id:") for line in lines)
    assert not any(line.startswith("id:") for line in lines)


def test_save_plant_merge_never_leaves_both_id_spellings_canonical_then_legacy(tmp_path):
    """Same bug, opposite direction: a 'plant_id'-keyed file (the real
    corpus's own shape) merged with an 'id'-keyed update must end up with
    exactly 'id:', not both."""
    markdown_backend.save_plant({"plant_id": "Ltz01", "cross": "Lantz", "status": "active"}, tmp_path)
    markdown_backend.save_plant({"id": "Ltz01", "vigor": "7"}, tmp_path)

    lines = _frontmatter_lines(tmp_path / "plants" / "Ltz01.md")
    assert any(line.startswith("id:") for line in lines)
    assert not any(line.startswith("plant_id:") for line in lines)


def test_save_plant_merge_preserves_the_spelling_when_update_omits_the_id(tmp_path):
    """A partial update that only touches, say, vigor still has to name the
    plant to find its file -- _plant_id_for_write requires SOME id key on
    every call -- but the existing spelling must survive untouched when the
    update's own id key matches what's already on disk (the common case:
    most observations don't re-declare the ID at all beyond what routes the
    call)."""
    markdown_backend.save_plant({"id": "MG02", "cross": "Test", "status": "active"}, tmp_path)
    markdown_backend.save_plant({"id": "MG02", "vigor": "8"}, tmp_path)

    lines = _frontmatter_lines(tmp_path / "plants" / "MG02.md")
    assert any(line.startswith("id:") for line in lines)
    assert not any(line.startswith("plant_id:") for line in lines)
    assert any(line.startswith("vigor:") for line in lines)


def test_duplicate_detection_spans_both_spellings(tmp_path):
    """Two records for the SAME plant under different spellings would write
    one file twice and silently lose the first."""
    tracker = {"plants": [{"plant_id": "SB01"}, {"id": "SB01"}]}
    with pytest.raises(ValueError, match="duplicate"):
        markdown_backend.save_tracker(tracker, tmp_path / "tracker.json")


def test_path_traversal_is_still_refused_under_the_canonical_key(tmp_path):
    tracker = {"plants": [{"plant_id": "../../escaped"}]}
    with pytest.raises(ValueError, match="unsafe"):
        markdown_backend.save_tracker(tracker, tmp_path / "tracker.json")
