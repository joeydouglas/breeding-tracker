"""Task 2.1 acceptance criteria: the six per-project wrappers are UNMODIFIED
and still work against the new markdown backend.

The plan's acceptance criteria for Task 2.1 is precisely: *existing wrapper
code is NOT modified and still works against the new backend in a sandbox*.
That is two claims, and this file tests both:

* **Not modified** -- each wrapper's SHA-256 is pinned to the value it had
  before Task 2.1 began. If anyone edits a wrapper to accommodate the new
  backend, these tests fail and the acceptance criteria is provably violated.
* **Still works** -- each wrapper is imported verbatim from its real project
  directory, with ``BREEDING_DIR`` pointed at a pytest ``tmp_path`` sandbox,
  and its own ``load_tracker()`` / ``save_tracker()`` wrapper functions are
  exercised. Nothing here touches a real project dir, Discord, Drive, or git.

The wrappers call ``core.load_tracker(TRACKER_FILE)`` and
``core.save_tracker(tracker, TRACKER_FILE)`` where ``TRACKER_FILE`` is
``BREEDING_DIR / 'tracker.json'`` -- so this file is also the proof that the
external signature (positional args, argument order) is preserved.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BREEDING_ROOT = Path.home() / ".hermes" / "breeding"

# Baselines captured from the working tree at the start of Task 2.1, BEFORE
# any production change. Any edit to a wrapper changes these.
WRAPPER_SHA256 = {
    "honey-badger-haze-pheno-hunt":
        "c2d385f838b9e899bdffd7e0934e561092c9b03e07d4eb75f787e27270bedeb0",
    "kibungan-pheno-hunt":
        "e32b8e29f392ba1a729dcb5087662f8d6068c53ba4119334252b4b9f830de31b",
    "lantz":
        "5b524afb1de604c813db3ca056610a6ea94ddb04841cb8fc49a8b3501bd56a3c",
    "mule-fuel-x-nana-glue":
        "f0f179c70fc004d43242a223512f1ae2be94bd57fc8b081574e2d5f2bbace66f",
    "paloma-coma":
        "19576dd2e06a32e1075132acb924805c6aea624f3f375a55610d76a845dabc62",
    "spaced-paste":
        "bc5d4c72051ceef1f2f08183d40b69796d17e6c0f3f4b137c794ecced617ab93",
}

PROJECTS = sorted(WRAPPER_SHA256)


def _wrapper_path(project):
    return BREEDING_ROOT / project / "monitor_breeding_notes.py"


def _load_wrapper(project, sandbox_dir, monkeypatch):
    """Import a project's wrapper VERBATIM, pointed at a sandbox dir.

    ``BREEDING_DIR`` is read from the environment at import time by every
    wrapper (that env hook already exists in the shipped code -- it is not
    something Task 2.1 added), so a sandbox redirect needs no source change.
    """
    path = _wrapper_path(project)
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")

    monkeypatch.setenv("BREEDING_DIR", str(sandbox_dir))
    monkeypatch.setenv("BREEDING_DISABLE_PUSH", "1")

    mod_name = f"_sandbox_wrapper_{project.replace('-', '_')}"
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


def _real_tracker(project):
    path = BREEDING_ROOT / project / "tracker.json"
    if not path.exists():
        pytest.skip(f"real tracker for {project} not present")
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------ not modified ------


@pytest.mark.parametrize("project", PROJECTS)
def test_wrapper_source_is_byte_identical_to_the_pre_task_baseline(project):
    path = _wrapper_path(project)
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == WRAPPER_SHA256[project], (
        f"{project}/monitor_breeding_notes.py was modified -- Task 2.1's "
        "acceptance criteria requires wrapper code to stay untouched"
    )


# -------------------------------------------------------- still works -----


@pytest.mark.parametrize("project", PROJECTS)
def test_wrapper_save_then_load_round_trips_against_the_markdown_backend(
    project, tmp_path, monkeypatch
):
    sandbox = tmp_path / project
    sandbox.mkdir()
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    tracker = _real_tracker(project)

    # The wrapper's own zero/one-arg façades, called exactly as the gateway
    # plugin calls them.
    wrapper.save_tracker(tracker)
    loaded = wrapper.load_tracker()

    assert loaded == tracker


@pytest.mark.parametrize("project", PROJECTS)
def test_wrapper_writes_markdown_into_its_own_breeding_dir(
    project, tmp_path, monkeypatch
):
    sandbox = tmp_path / project
    sandbox.mkdir()
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    tracker = _real_tracker(project)

    wrapper.save_tracker(tracker)

    assert wrapper.BREEDING_DIR == sandbox
    assert (sandbox / "project.md").is_file()
    assert not (sandbox / "tracker.json").exists()
    plant_files = sorted(p.stem for p in (sandbox / "plants").glob("*.md"))
    assert plant_files == sorted(p["id"] for p in tracker["plants"])


@pytest.mark.parametrize("project", PROJECTS)
def test_wrapper_save_tracker_returns_none_as_before(
    project, tmp_path, monkeypatch
):
    sandbox = tmp_path / project
    sandbox.mkdir()
    wrapper = _load_wrapper(project, sandbox, monkeypatch)
    assert wrapper.save_tracker(_real_tracker(project)) is None


def test_no_wrapper_run_touched_a_real_project_directory(tmp_path, monkeypatch):
    """Side-effect isolation: exercising every wrapper leaves all six real
    tracker.json files and every real project dir byte-identical."""
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/tracker.json"))
    }
    if not before:
        pytest.skip("no real trackers present")

    # NICK-948: live project.md files now legitimately exist -- see the same
    # note in test_update_plant_end_to_end.py. Assert non-MUTATION, not absence.
    project_md_before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/project.md"))
    }

    for project in PROJECTS:
        sandbox = tmp_path / f"iso-{project}"
        sandbox.mkdir()
        with monkeypatch.context() as ctx:
            wrapper = _load_wrapper(project, sandbox, ctx)
            wrapper.save_tracker(_real_tracker(project))
            wrapper.load_tracker()

    after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/tracker.json"))
    }
    assert after == before
    project_md_after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(BREEDING_ROOT.glob("*/project.md"))
    }
    assert project_md_after == project_md_before, (
        "a sandbox wrapper run modified a real project.md"
    )
