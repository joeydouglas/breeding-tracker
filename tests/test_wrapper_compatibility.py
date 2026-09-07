"""Task 2.1 acceptance criteria: the six per-project wrappers matched a pinned
SHA-256 baseline and worked against the new markdown backend.

The plan's acceptance criteria for Task 2.1 is precisely: *existing wrapper
code is NOT modified and still works against the new backend in a sandbox*.
That is two claims, and this file tests both:

* **Not modified (Task 2.1's own change)** -- each wrapper's SHA-256 is
  pinned. Task 2.1 itself made no wrapper edits and these hashes proved it.
  NICK-949 (see the re-baseline note below) is a LATER, deliberate wrapper
  edit for a different reason -- the pin's job from that point on is drift
  detection against the NEW baseline, not a claim that wrappers have never
  changed since Task 2.1.
* **Still works** -- each wrapper is imported verbatim from its real project
  directory, with ``BREEDING_DIR`` pointed at a pytest ``tmp_path`` sandbox,
  and its own ``load_tracker()`` / ``save_tracker()`` wrapper functions are
  exercised. Nothing here touches a real project dir, Discord, Drive, or git.

Each wrapper's ``load_tracker``/``save_tracker`` façades now call
``core.load_tracker_for(CONFIG)`` and ``core.save_tracker_for(tracker,
CONFIG)`` (NICK-949) rather than the original path-only
``core.load_tracker(TRACKER_FILE)`` / ``core.save_tracker(tracker,
TRACKER_FILE)`` -- the config-aware calls are what let ``CONFIG['BACKEND']``
actually be honoured. The ORIGINAL path-only signature is still preserved
and tested, just not here: see ``tests/test_backend_selector.py``, which is
the current proof that ``core.load_tracker(path)``/``core.save_tracker(t,
path)`` keep working unchanged for any caller that doesn't go through a
CONFIG dict.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BREEDING_ROOT = Path.home() / ".hermes" / "breeding"

# Baselines ORIGINALLY captured from the working tree at the start of Task
# 2.1, before any production change, and RE-BASELINED by NICK-949 below (see
# that comment for why). These are NOT a "wrappers have never changed since
# 2.1" claim -- read the NICK-949 note immediately below for the current
# status. Any edit to a wrapper beyond NICK-949's own changes fails these.
#
# NICK-949 RE-BASELINE. Task 2.1's acceptance criteria was that its OWN change
# required no wrapper edit -- and it did not; these hashes went untouched
# through 2.1, 2.3 and 2.5. NICK-949 is a different, later change with the
# opposite intent: it adds the per-project ``CONFIG['BACKEND']`` key that Task
# 7.2's rollback rehearsal flips, and that key has to be written down in each
# wrapper (an implicit default cannot be flipped, and cannot be read). So each
# wrapper gained exactly two things -- an explicit ``'BACKEND': 'markdown'``
# entry and ``load_tracker``/``save_tracker`` façades routed through
# ``core.*_for(CONFIG)`` so the flip is actually honoured. The
# "still works" tests below are unchanged and remain the real proof that the
# markdown behaviour did not move. Pre-NICK-949 wrapper source was NOT
# recoverable from any backup (NICK-949 review finding A) -- these hashes
# were the only artifact of that prior state, and could not themselves be
# used to reconstruct it (a digest is not a preimage). Going forward this is
# fixed: ``pre-refactor-backup/wrappers-post-nick949/`` is a git-tracked
# mirror of the CURRENT wrapper source, and
# ``test_wrapper_source_matches_the_tracked_mirror`` below fails loudly if a
# live wrapper drifts from it without the mirror being updated in the same
# commit -- so the next edit (Task 7.2's real per-project flip) has an actual
# recoverable baseline, not just a hash.
WRAPPER_SHA256 = {
    "honey-badger-haze-pheno-hunt":
        "96a91064bdbeb49df0ed8023ea07fd226a7616ba9bf4a6f35c17c383874f3e17",
    "kibungan-pheno-hunt":
        "2768b6fefe7cf3246c7388e4765c5bddc6cc55c5fe6b3b363dc367273de19dc5",
    "lantz":
        "79c86a0b5c1ada77750cafdb94dbe0da290eef7e22b4d039cb89be5116fe56ac",
    "mule-fuel-x-nana-glue":
        "ac9e7b1521fcea5266e13ab3b648805e97bc7a661898d58e6c6d80acae83c959",
    "paloma-coma":
        "356b2c29b7973611a85a94fd23cabbe2c9b79ee0a060b813a92f53772a8100da",
    "spaced-paste":
        "c5fddf7507f115d30da0ed64a9c8b025719e11da9a546f36a8c1692c1a3cfe31",
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
        f"{project}/monitor_breeding_notes.py was modified against the "
        "current baseline -- if this is an intentional wrapper edit (as "
        "NICK-949 was), re-baseline WRAPPER_SHA256 for this project AND "
        "update the module docstring/comments above to say so; if it's "
        "not intentional, revert the wrapper"
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


# ------------------------------------------- tracked recoverable mirror ---

MIRROR_DIR = Path(__file__).resolve().parent.parent / "pre-refactor-backup" / "wrappers-post-nick949"


@pytest.mark.parametrize("project", PROJECTS)
def test_wrapper_source_matches_the_tracked_mirror(project):
    """The live wrapper must match its git-tracked mirror byte-for-byte.

    NICK-949 review finding A: wrapper files under ~/.hermes/breeding are not
    version-controlled, and pre-NICK-949 source proved unrecoverable once the
    files were edited (a SHA-256 pin only detects drift, it cannot reverse
    it). This test plus the mirror it checks against are the fix: any wrapper
    edit from this point on MUST update its mirror copy in the same commit,
    or this test catches the drift immediately -- turning "no undo" into "the
    tracked history has every wrapper revision".

    If this test fails because you intentionally edited a wrapper: copy the
    new wrapper source into MIRROR_DIR and commit both together (and, if the
    edit also changes wrapper behavior/content, re-baseline WRAPPER_SHA256
    above with a comment explaining why, per that test's own message).
    """
    live_path = _wrapper_path(project)
    if not live_path.exists():
        pytest.skip(f"wrapper for {project} not present")
    mirror_path = MIRROR_DIR / f"{project}_monitor_breeding_notes.py"
    assert mirror_path.exists(), (
        f"no tracked mirror for {project} at {mirror_path} -- every live "
        "wrapper must have one (see this test's docstring)"
    )
    assert live_path.read_bytes() == mirror_path.read_bytes(), (
        f"{project}/monitor_breeding_notes.py has drifted from its tracked "
        f"mirror at {mirror_path} -- if this edit is intentional, copy the "
        "new source into the mirror and commit both together"
    )
