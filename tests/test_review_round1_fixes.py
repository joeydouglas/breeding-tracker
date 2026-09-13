"""Round-1 code-quality review regression tests (Phase 2 / Task 2.1).

Each test here pins a specific finding from the round-1 code-quality review
of the markdown persistence backend. They were written BEFORE the fixes and
watched failing.

SANDBOX-ONLY, like the rest of this suite: real project dirs are read-only
inputs, every write lands in a pytest ``tmp_path``, and no Discord, Drive,
network or git-push side effect is performed.
"""

import json
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

from breeding_tracker import breeding_core as core  # noqa: E402
from breeding_tracker import markdown_backend  # noqa: E402


# ----------------------------------------------------------- helpers ------


def _seed(project_dir, tracker):
    core.save_tracker(tracker, project_dir / "tracker.json")
    return project_dir / "tracker.json"


class _Unserialisable:
    """A value PyYAML has no representer for -- stands in for any value-level
    write failure that only shows up once a plant is actually rendered."""


# ============ IMPORTANT #1: observation_log guarantee is enforced HERE =====


def test_observation_log_survives_even_if_phase_1_stops_guaranteeing_it(
    sandbox_project, lantz_tracker, monkeypatch
):
    """``observation_log`` must be exempted from the restrict-to-present
    filter by THIS module, not merely inherited from Phase 1's contract.

    The module docstring claims ``_ALWAYS_PRESENT_PLANT_KEYS`` is the
    mechanism, but ``_restrict_to_present`` never consulted it -- the
    behaviour came for free because Phase 1's ``read_plant`` unconditionally
    adds ``observation_log``. This test simulates Phase 1 dropping that
    guarantee from its schema-less read: with no local enforcement the key
    is silently filtered away and the round-trip becomes asymmetric.
    """
    tracker = dict(lantz_tracker)
    tracker["plants"] = [dict(lantz_tracker["plants"][0])]
    tracker_file = _seed(sandbox_project, tracker)

    _, plant_markdown = markdown_backend._import_markdown_modules()
    real_read_plant = plant_markdown.read_plant

    def read_plant_without_body_guarantee(path, schema=None):
        result = real_read_plant(path, schema=schema)
        if schema is None:
            # Phase 1 hypothetically stops adding the body key here.
            result.pop(plant_markdown.BODY_FIELD, None)
        return result

    monkeypatch.setattr(
        plant_markdown, "read_plant", read_plant_without_body_guarantee
    )

    loaded = core.load_tracker(tracker_file)
    assert "observation_log" in loaded["plants"][0], (
        "observation_log was filtered away -- the guarantee is not enforced "
        "locally, it was silently depending on Phase 1's exact contract"
    )


# ==== IMPORTANT #2: a failed roster save must not leave a partial project ==


def test_a_failing_plant_write_leaves_the_whole_project_untouched(
    sandbox_project, lantz_tracker
):
    """``save_tracker``'s pre-pass only validated ids/duplicates, so a
    value-level failure on plant #3 of 4 still left plants #1-#2 rewritten
    AND ``project.md`` rewritten with the new ``plant_order`` -- a partially
    applied roster, contradicting the comment's 'must not leave a
    half-written project on disk' promise."""
    tracker = dict(lantz_tracker)
    tracker["plants"] = [dict(p) for p in lantz_tracker["plants"][:4]]
    assert len(tracker["plants"]) == 4, "fixture needs >=4 plants"
    tracker_file = _seed(sandbox_project, tracker)

    plants_dir = sandbox_project / "plants"
    before_plants = {p.name: p.read_text(encoding="utf-8")
                     for p in sorted(plants_dir.glob("*.md"))}
    before_project = (sandbox_project / "project.md").read_text(encoding="utf-8")
    assert len(before_plants) == 4

    doomed = [dict(p) for p in tracker["plants"]]
    for i, plant in enumerate(doomed):
        plant["selection_notes"] = f"MUTATED-{i}"
    doomed[2]["selection_notes"] = _Unserialisable()
    bad_tracker = dict(tracker)
    bad_tracker["plants"] = doomed
    bad_tracker["cross_name"] = "MUTATED-PROJECT"

    with pytest.raises(Exception):
        core.save_tracker(bad_tracker, tracker_file)

    after_plants = {p.name: p.read_text(encoding="utf-8")
                    for p in sorted(plants_dir.glob("*.md"))}
    assert after_plants == before_plants, (
        "a failed save partially rewrote the plant roster: "
        f"{sorted(k for k in before_plants if before_plants[k] != after_plants.get(k))}"
    )
    assert (sandbox_project / "project.md").read_text(encoding="utf-8") == (
        before_project
    ), "a failed save still rewrote project.md"


def test_a_failing_plant_write_does_not_delete_plants(
    sandbox_project, lantz_tracker
):
    """The stale-file sweep must not run for a save that never completed."""
    tracker = dict(lantz_tracker)
    tracker["plants"] = [dict(p) for p in lantz_tracker["plants"][:4]]
    tracker_file = _seed(sandbox_project, tracker)
    plants_dir = sandbox_project / "plants"
    before = sorted(p.name for p in plants_dir.glob("*.md"))

    doomed = [dict(p) for p in tracker["plants"][:2]]
    doomed[1]["selection_notes"] = _Unserialisable()
    bad = dict(tracker)
    bad["plants"] = doomed

    with pytest.raises(Exception):
        core.save_tracker(bad, tracker_file)

    assert sorted(p.name for p in plants_dir.glob("*.md")) == before


def test_save_tracker_comment_does_not_overclaim_atomicity():
    """The docstring must describe the real guarantee, not a stronger one."""
    doc = markdown_backend.save_tracker.__doc__ or ""
    assert "atomic" in doc.lower() or "staged" in doc.lower(), (
        "save_tracker's write-ordering guarantee is undocumented"
    )


# ==== IMPORTANT #3a: corrupt plant file policy is fail-loud, documented ====


def test_one_corrupt_plant_file_fails_the_whole_load_loudly(
    sandbox_project, lantz_tracker
):
    """POLICY PIN: a single malformed plant file makes the ENTIRE project
    load raise, rather than being skipped.

    This is deliberate (see the docstrings). Skip-and-warn would silently
    drop the plant from the roster, and ``save_tracker``'s whole-roster
    rewrite semantics would then DELETE its file on the very next
    observation -- turning one recoverable parse error into permanent data
    loss."""
    _, plant_markdown = markdown_backend._import_markdown_modules()

    tracker = dict(lantz_tracker)
    tracker["plants"] = [dict(p) for p in lantz_tracker["plants"][:3]]
    tracker_file = _seed(sandbox_project, tracker)

    victim = sorted((sandbox_project / "plants").glob("*.md"))[1]
    victim.write_text("---\nid: [unclosed\n---\nbody\n", encoding="utf-8")

    with pytest.raises(plant_markdown.MalformedFrontmatterError):
        core.load_tracker(tracker_file)


def test_fail_loud_on_corrupt_plant_is_documented_in_both_docstrings():
    """An undocumented whole-project failure mode is a diagnosability bug:
    both the backend and the caller-facing wrapper must state it."""
    for func in (markdown_backend.load_tracker, core.load_tracker):
        doc = (func.__doc__ or "").lower()
        assert "malformed" in doc or "corrupt" in doc, (
            f"{func.__module__}.{func.__name__} does not document what happens "
            "when one plant file is unparseable"
        )


# ==== IMPORTANT #3b: id-less plant in roster must not raise bare KeyError ==


def test_idless_plant_in_roster_surfaces_the_informative_validator_error(
    sandbox_project, lantz_tracker, monkeypatch
):
    """``update_plant``'s roster scan did a bare ``p['id']``, so an id-less
    plant raised an opaque ``KeyError('id')`` BEFORE ``save_tracker``'s own
    clean ``ValueError('plant record has a missing or non-string id')`` could
    ever surface. The informative error must win."""
    tracker = dict(lantz_tracker)
    tracker["plants"] = [dict(lantz_tracker["plants"][0])]
    tracker_file = _seed(sandbox_project, tracker)

    # save_tracker refuses to persist an id-less plant, so the only way this
    # roster shape reaches update_plant is a hand-edited/corrupted file on
    # disk: write one directly, with no ``id`` field.
    idless = sandbox_project / "plants" / "Ltz99.md"
    idless.write_text("---\ncross: Lantz\nstatus: active\n---\n", encoding="utf-8")

    monkeypatch.setattr(core, "push_to_github", lambda *a, **k: None)
    monkeypatch.setattr(
        core.subprocess, "run", lambda *a, **k: None
    )

    config = {
        "TRACKER_FILE": tracker_file,
        "BREEDING_DIR": sandbox_project,
        "GITHUB_REPO": "example/none",
        "DISABLE_GITHUB_PUSH": True,
        "CROSS_NAME": "Lantz",
        "AUTO_CREATE": True,
    }
    observation = core.parse_observation("Ltz42 vigor 8, fuel, keeper")

    with pytest.raises(ValueError, match="missing or non-string plant_id"):
        core.update_plant("Ltz42", observation, config)


# ------------------------------- MINOR: friendlier missing-repo error -----


def test_breeding_markdown_dir_override_redirects_the_templates(
    tmp_path, monkeypatch
):
    """The markdown modules now ship inside this package, so the historical
    missing-repo ModuleNotFoundError path is gone. What BREEDING_MARKDOWN_DIR
    still controls is WHICH templates directory the backend reads, and that
    override must keep working for sandboxes and the data-api container."""
    override = tmp_path / "alt-checkout"
    (override / "templates").mkdir(parents=True)
    monkeypatch.setenv("BREEDING_MARKDOWN_DIR", str(override))
    assert markdown_backend._templates_dir() == override / "templates"

    monkeypatch.delenv("BREEDING_MARKDOWN_DIR")
    default = markdown_backend._templates_dir()
    assert default.name == "templates"
    assert (default / "plant-template.md").is_file()


# ------------------------- MINOR: id error message must not overstate -----


def test_unsafe_plant_id_error_message_does_not_overstate_its_coverage():
    """The message advertised 'reserved name' checking but only ever
    checked ``.`` and ``..``; it must name what it actually enforces."""
    with pytest.raises(ValueError) as excinfo:
        markdown_backend._validate_plant_id("a/b")
    message = str(excinfo.value)
    assert "'.'" in message and "'..'" in message, (
        f"error message overstates or under-specifies its coverage: {message}"
    )


def test_dot_and_dotdot_plant_ids_are_still_rejected():
    for bad in (".", ".."):
        with pytest.raises(ValueError):
            markdown_backend._validate_plant_id(bad)
