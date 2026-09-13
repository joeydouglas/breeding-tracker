"""End-to-end regression tests for the plants/<ID>.md filename collision.

The bug this file pins down (found by the Task 2.1 spec-compliance review):

``breeding_core.update_markdown()`` was a JSON-era **derived view** -- it
regenerated a human-readable report at ``plants/<ID>.md`` from the record of
truth, which back then was ``tracker.json``. After Task 2.1 moved persistence
to markdown, ``plants/<ID>.md`` IS the record of truth (written by
``markdown_backend.save_tracker`` via Phase 1's ``plant_markdown.write_plant``).
``update_plant()`` calls ``save_tracker()`` and then ``update_markdown()``, so
the derived view overwrote the authoritative record with its own minimal
3-key frontmatter (``plant_id``/``cross``/``status``) -- destroying every other
field, including the ``id`` that the very next observation looks the plant up by.

Everything here is SANDBOX-ONLY (pytest ``tmp_path``); real project dirs are
read-only inputs, GitHub push is disabled and no Discord/Drive call is made.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_ROOT = MONITOR_CORE_DIR.parents[1]

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

import breeding_core  # noqa: E402
import markdown_backend  # noqa: E402

PROJECTS = sorted(p.parent.name for p in BREEDING_ROOT.glob("*/tracker.json"))

# Per-project (plant-id prefix, a real plant id, observation text) so the
# end-to-end message actually matches each wrapper's own ID regex.
OBSERVATION_TEXT = {
    "honey-badger-haze-pheno-hunt": "{pid} vigor 8, fuel and citrus, keeper",
    "kibungan-pheno-hunt": "{pid} vigor 8, fuel and citrus, keeper",
    "lantz": "{pid} vigor 8, fuel and citrus, keeper",
    "mule-fuel-x-nana-glue": "{pid} vigor 8, fuel and citrus, keeper",
    "paloma-coma": "{pid} vigor 8, fuel and citrus, keeper",
    "spaced-paste": "{pid} vigor 8, fuel and citrus, keeper",
    "marshmallow-og-pheno-hunt": "{pid} vigor 8, fuel and citrus, keeper",
    "pink-perfume-pheno-hunt": "{pid} vigor 8, fuel and citrus, keeper",
    "ms-universe-pheno-hunt": "{pid} vigor 8, fuel and citrus, keeper",
}


def _real_tracker(project):
    path = BREEDING_ROOT / project / "tracker.json"
    if not path.exists():
        pytest.skip(f"real tracker for {project} not present")
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_sandbox(project, tmp_path):
    """A sandbox copy of a real project, already migrated to markdown."""
    tracker = _real_tracker(project)
    sandbox = tmp_path / project
    sandbox.mkdir(parents=True, exist_ok=True)
    markdown_backend.save_tracker(tracker, sandbox / "tracker.json")
    return sandbox, tracker


def _load_wrapper(project, sandbox_dir, monkeypatch):
    """Import a project's UNMODIFIED wrapper, pointed at the sandbox."""
    path = BREEDING_ROOT / project / "monitor_breeding_notes.py"
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")

    monkeypatch.setenv("BREEDING_DIR", str(sandbox_dir))
    monkeypatch.setenv("BREEDING_DISABLE_PUSH", "1")

    mod_name = f"_e2e_wrapper_{project.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    monkeypatch.delitem(sys.modules, mod_name, raising=False)
    return module


# ------------------------------------------- the data-destruction bug ------


@pytest.mark.parametrize("project", PROJECTS)
def test_process_message_preserves_every_plant_field(project, tmp_path, monkeypatch):
    """The Ltz01 scenario: one real message through the real entry point must
    not shrink the plant's key set or change any untouched field's value."""
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    target = tracker["plants"][0]
    plant_id = target["id"]

    result = wrapper.process_message(OBSERVATION_TEXT[project].format(pid=plant_id))
    assert result is not None, f"{plant_id} was not recognised in the message text"
    assert "\u274c" not in result, result

    after = breeding_core.load_tracker(sandbox / "tracker.json")
    updated = next(p for p in after["plants"] if p.get("id") == plant_id)

    assert set(updated) == set(target), (
        "plants/<ID>.md key set changed: "
        f"lost {sorted(set(target) - set(updated))}, "
        f"gained {sorted(set(updated) - set(target))}"
    )
    # Fields the observation does not touch must be byte-identical.
    untouched = set(target) - {"vigor", "terpene_notes", "status", "observation_log"}
    for field in sorted(untouched):
        assert updated[field] == target[field], f"{field} was corrupted"

    # And the roster as a whole is intact.
    assert [p["id"] for p in after["plants"]] == [p["id"] for p in tracker["plants"]]


@pytest.mark.parametrize("project", PROJECTS)
def test_two_consecutive_observations_do_not_raise(project, tmp_path, monkeypatch):
    """The corrupted record used to raise KeyError('id') on the NEXT
    observation, because 'id' had been replaced by a spurious 'plant_id'."""
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    plant_id = tracker["plants"][0]["id"]
    text = OBSERVATION_TEXT[project].format(pid=plant_id)

    wrapper.process_message(text)
    second = wrapper.process_message(text)  # used to raise KeyError('id')

    assert second is not None and "\u274c" not in second


@pytest.mark.parametrize("project", PROJECTS)
def test_plant_file_never_gains_a_spurious_plant_id_key(
    project, tmp_path, monkeypatch
):
    """The derived view's frontmatter used 'plant_id'; the record uses 'id'."""
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    plant_id = tracker["plants"][0]["id"]

    wrapper.process_message(OBSERVATION_TEXT[project].format(pid=plant_id))

    text = (sandbox / "plants" / f"{plant_id}.md").read_text(encoding="utf-8")
    assert "\nplant_id:" not in text
    assert "\nid:" in text


def test_update_markdown_alone_does_not_destroy_the_plant_record(
    tmp_path, monkeypatch
):
    """The six wrappers each expose `update_markdown(plant)` directly, so it
    must be safe to call on its own too -- not only via update_plant()."""
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    plant = tracker["plants"][0]

    wrapper.update_markdown(plant)

    after = breeding_core.load_tracker(sandbox / "tracker.json")
    reloaded = next(p for p in after["plants"] if p.get("id") == plant["id"])
    assert reloaded == plant


def test_update_plant_return_value_is_unchanged(tmp_path, monkeypatch):
    """External behavior of update_plant() must be untouched by the fix."""
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    plant_id = tracker["plants"][0]["id"]

    observation = breeding_core.parse_observation(f"{plant_id} vigor 8, fuel, keeper")
    result = wrapper.update_plant(plant_id, observation, photo_count=2)

    assert result == f"\u2713 {plant_id} updated: vigor 8, fuel terps, 2 photo(s) uploaded"


def test_missing_plant_still_returns_the_not_found_string(tmp_path, monkeypatch):
    """breeding_core's "not found" branch (AUTO_CREATE=False) must still work.

    NICK-1058 flipped AUTO_CREATE to True for every live project, so no real
    wrapper exercises this branch anymore -- the CONFIG is monkeypatched back
    to False here specifically to keep covering that branch of
    breeding_core.update_plant() rather than deleting the test.
    """
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, _ = _seed_sandbox(project, tmp_path)
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    monkeypatch.setitem(wrapper.CONFIG, "AUTO_CREATE", False)

    observation = breeding_core.parse_observation("nothing here")
    assert wrapper.update_plant("ZZ99", observation) == "\u274c Plant ZZ99 not found"


def test_no_end_to_end_run_touched_a_real_project_directory(tmp_path, monkeypatch):
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/tracker.json"))
    }
    if not before:
        pytest.skip("no real trackers present")

    # NICK-948: the live project.md files now legitimately EXIST (they were
    # generated from tracker.json to unblock load_tracker's FileNotFoundError).
    # The invariant this test defends is "a sandbox run must not MUTATE live
    # data", so the live project.md is hashed before/after rather than asserted
    # absent -- an absence check would now fail on correct production state
    # while a leak that overwrote a real project.md would slip through.
    project_md_before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/project.md"))
    }

    for project in PROJECTS:
        with monkeypatch.context() as ctx:
            sandbox, tracker = _seed_sandbox(project, tmp_path / f"iso-{project}")
            wrapper = _load_wrapper(project, sandbox, ctx)
            wrapper.process_message(
                OBSERVATION_TEXT[project].format(pid=tracker["plants"][0]["id"])
            )

    after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/tracker.json"))
    }
    assert after == before
    project_md_after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/project.md"))
    }
    assert project_md_after == project_md_before


# --------------------------------- save_plant (update_markdown's backend) ---


def test_save_plant_merges_over_existing_fields(tmp_path):
    """A partial plant dict must never truncate the stored record."""
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    plant = tracker["plants"][0]

    markdown_backend.save_plant({"id": plant["id"], "status": "culled"}, sandbox)

    reloaded = next(
        p
        for p in breeding_core.load_tracker(sandbox / "tracker.json")["plants"]
        if p["id"] == plant["id"]
    )
    assert set(reloaded) == set(plant)
    assert reloaded["status"] == "culled"
    for field in set(plant) - {"status"}:
        assert reloaded[field] == plant[field]


def test_save_plant_creates_a_new_plant_file(tmp_path):
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, _ = _seed_sandbox(project, tmp_path)
    markdown_backend.save_plant({"id": "NEW01", "status": "active"}, sandbox)
    assert (sandbox / "plants" / "NEW01.md").is_file()


def test_save_plant_leaves_other_plants_and_project_md_untouched(tmp_path):
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, tracker = _seed_sandbox(project, tmp_path)
    if len(tracker["plants"]) < 2:
        pytest.skip("project has only one plant")
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [sandbox / "project.md"]
        + sorted((sandbox / "plants").glob("*.md"))
    }
    target = sandbox / "plants" / f"{tracker['plants'][0]['id']}.md"

    markdown_backend.save_plant(tracker["plants"][0], sandbox)

    for path, digest in before.items():
        if path == target:
            continue
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path


def test_save_plant_rejects_an_unsafe_id(tmp_path):
    project = "lantz" if "lantz" in PROJECTS else PROJECTS[0]
    sandbox, _ = _seed_sandbox(project, tmp_path)
    with pytest.raises(ValueError):
        markdown_backend.save_plant({"id": "../escape", "status": "x"}, sandbox)
