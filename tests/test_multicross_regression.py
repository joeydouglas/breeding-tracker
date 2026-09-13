"""Phase 2 / Task 2.4 -- FULL MULTI-CROSS REGRESSION PASS.

WHAT THE "NICK-592 MULTI-CROSS CYCLING TEST" IS
-----------------------------------------------
Task 2.4's spec says to "replay the NICK-592 multi-cross cycling test".
There is no such runnable artifact anywhere in this repo, in
``breeding-markdown``, in the six wrappers, or in git history: searching for
``NICK-592`` / ``multi-cross`` / ``cycling`` turns up only PROSE. What the
prose actually describes is:

  * ``breeding_core.py``'s module docstring -- NICK-592 consolidated six
    drifted per-project copies of ``parse_observation`` / ``update_plant`` /
    ``update_markdown`` / ``push_to_github`` / ``process_message`` into this
    one module after NICK-589 found Mule Fuel, Lantz and Spaced Paste missing
    keeper/culled detection entirely.
  * each wrapper's own comment about the gateway plugin "cycling through
    crosses in one long-lived process via ``importlib.reload()``" -- THAT is
    the "cycling": one process, one shared ``breeding_core``, six crosses
    handled in turn, each with its own BREEDING_DIR / roster / ID pattern /
    AUTO_CREATE policy.

So the "multi-cross cycling test" was an ad-hoc historical verification, not
a committed script. This file is the faithful, committed equivalent: it
replays a realistic observation sequence ROUND-ROBIN across sandboxed copies
of all six real projects -- reloading each wrapper the way the gateway does
-- through the FULL new pipeline
(``process_message``/``parse_observation`` -> ``update_plant`` ->
``save_tracker`` -> ``markdown_backend`` -> ``push_to_github``), and checks
the result two ways:

  1. **Differential (the Task 2.2 philosophy).** The identical observation
     sequence is applied to a second copy of the same real starting data
     using the FROZEN JSON-era implementation
     (``tests/fixtures/baseline_breeding_core_2dd0537.py``). The final state
     of every plant in every project must be equal, field for field, modulo
     the ONE already-approved deviation (``vigor`` int -> str, see
     DECISIONS.md "Task 2.2").
  2. **Byte-for-byte against Task 2.2's committed fixture.** Where a fixture
     case applies -- i.e. an observation landing on a freshly auto-created
     blank plant, which is exactly the state ``plant_after`` was derived
     against -- the resulting plant fields and the Discord reply string must
     equal the fixture verbatim.

SAFETY. Everything is SANDBOX-ONLY. Real project dirs are read (copied) and
never written; ``test_the_six_real_project_dirs_are_untouched`` checksums
every file under all six before and after a full replay. Pushes go to
throwaway LOCAL BARE repos under ``tmp_path`` -- never a real GitHub remote.
No Discord, no Drive, no network. ``generate_dashboard.py`` is deliberately
NOT copied into the sandbox, so ``update_plant``'s dashboard subprocess is a
harmless no-op failure (it is already capture_output'd and unchecked).
"""

import contextlib
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_ROOT = MONITOR_CORE_DIR.parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nick592_parsing_spec.json"
BASELINE_COMMIT = "2dd0537"
BASELINE_SNAPSHOT_PATH = (
    Path(__file__).parent / "fixtures" / f"baseline_breeding_core_{BASELINE_COMMIT}.py"
)

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

from breeding_tracker import breeding_core  # noqa: E402
from breeding_tracker.plant_record import ID_KEYS  # noqa: E402

SPEC = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = SPEC["cases"]

# The six crosses NICK-592 consolidated, with the wrapper facts this test
# needs. Everything else (ID pattern, cross name, AUTO_CREATE) is read from
# the wrapper itself so this table can never drift from the shipped config.
PROJECTS = [
    "honey-badger-haze-pheno-hunt",
    "kibungan-pheno-hunt",
    "lantz",
    "mule-fuel-x-nana-glue",
    "paloma-coma",
    "spaced-paste",
]

# A plant ID that does NOT exist in any real roster, used to exercise the
# AUTO_CREATE branch (pheno hunts) and the "not found" branch (doc-imported
# rosters) in the same replay.
NOVEL_SUFFIX = 99


# --------------------------------------------------------------------------
# Loading the six wrappers exactly as the gateway plugin does
# --------------------------------------------------------------------------


def _wrapper_path(project):
    return BREEDING_ROOT / project / "monitor_breeding_notes.py"


def _real_tracker_path(project):
    return BREEDING_ROOT / project / "tracker.json"


def _require_project(project):
    if not _wrapper_path(project).exists() or not _real_tracker_path(project).exists():
        pytest.skip(f"real project {project} not present")


@contextlib.contextmanager
def _sandbox_env(sandbox_dir, disable_push):
    """Point the wrappers' import-time env hooks at a sandbox, then restore.

    ``monkeypatch`` is function-scoped and this module's replay is
    module-scoped (see :func:`replay`), so the env is saved/restored by hand
    rather than left mutated for the rest of the session.
    """
    saved = {k: os.environ.get(k) for k in ("BREEDING_DIR", "BREEDING_DISABLE_PUSH")}
    os.environ["BREEDING_DIR"] = str(sandbox_dir)
    if disable_push:
        os.environ["BREEDING_DISABLE_PUSH"] = "1"
    else:
        os.environ.pop("BREEDING_DISABLE_PUSH", None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_wrapper(project, sandbox_dir, disable_push):
    """Import a project's wrapper VERBATIM, pointed at a sandbox dir.

    Same mechanism ``test_wrapper_compatibility.py`` uses (and the same env
    hook the shipped code already had): ``BREEDING_DIR`` is read at import
    time, so no source edit is needed to redirect a wrapper at a sandbox.
    This is also how the gateway "cycles" crosses -- a fresh module object
    per cross in one long-lived process.
    """
    mod_name = f"_t24_wrapper_{project.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, _wrapper_path(project))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        with _sandbox_env(sandbox_dir, disable_push):
            spec.loader.exec_module(module)
    finally:
        sys.modules.pop(mod_name, None)
    return module


def _json_era_module():
    """The frozen pre-Phase-2 ``breeding_core``. No git, no subprocess."""
    source = BASELINE_SNAPSHOT_PATH.read_text(encoding="utf-8")
    module = types.ModuleType("_json_era_breeding_core_t24")
    module.__file__ = str(MONITOR_CORE_DIR / "breeding_tracker" / "breeding_core.py")
    exec(
        compile(source, f"<json-era breeding_core.py @{BASELINE_COMMIT}>", "exec"),
        module.__dict__,
    )
    return module


# --------------------------------------------------------------------------
# Sandbox construction
# --------------------------------------------------------------------------


def _real_tracker(project):
    return json.loads(_real_tracker_path(project).read_text(encoding="utf-8"))


def _sandbox_markdown(project, root):
    """A sandboxed copy of a real project, MIGRATED to the markdown backend.

    The real starting data (``tracker.json``) is copied in and written out
    through the new backend -- i.e. the Phase 2 cutover -- so the replay
    starts from real per-project state, not a synthetic roster.
    ``generate_dashboard.py`` is intentionally absent (see module docstring).
    """
    project_dir = root / f"md-{project}"
    project_dir.mkdir(parents=True)
    tracker_file = project_dir / "tracker.json"
    breeding_core.save_tracker(_real_tracker(project), tracker_file)
    return project_dir, tracker_file


def _sandbox_json(project, root, json_era):
    """A sandboxed copy of the same real project on the JSON-era backend."""
    project_dir = root / f"json-{project}"
    (project_dir / "plants").mkdir(parents=True)
    tracker_file = project_dir / "tracker.json"
    json_era.save_tracker(_real_tracker(project), tracker_file)
    return project_dir, tracker_file


def _config(wrapper, project_dir, tracker_file, disable_push):
    config = dict(wrapper.CONFIG)
    config["BREEDING_DIR"] = project_dir
    config["TRACKER_FILE"] = tracker_file
    config["DISABLE_GITHUB_PUSH"] = disable_push
    return config


def _init_repo_with_bare_origin(project_dir, root, name):
    """Make the sandbox project a git repo whose origin is a THROWAWAY LOCAL
    BARE repo. Never a real remote."""
    bare = root / f"bare-{name}.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(project_dir)], check=True)
    for key, value in (
        ("user.email", "task24@example.invalid"),
        ("user.name", "Task 2.4 sandbox"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "config", key, value], cwd=project_dir, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)], cwd=project_dir, check=True
    )
    return bare


# --------------------------------------------------------------------------
# The observation sequence
# --------------------------------------------------------------------------


def _roster_ids(project):
    return [p["id"] for p in _real_tracker(project)["plants"]]


def _id_for(wrapper, number):
    """Render a plant ID the way this project's wrapper would parse it."""
    if wrapper.CONFIG.get("PLANT_ID_REGISTRY"):
        prefix = wrapper.CONFIG["PLANT_ID_REGISTRY"][0][0]
    else:
        prefix = wrapper.CONFIG["PLANT_ID_PREFIX"]
    return f"{prefix}{number:02d}"


def _sequence_for(project, wrapper):
    """A realistic observation sequence for one project.

    Text comes from Task 2.2's committed 24-case fixture (the source of
    realistic observation text this task was told to use); the plant IDs are
    this project's REAL roster IDs, cycled, plus one novel ID that exercises
    AUTO_CREATE (pheno hunts) / not-found (doc-imported rosters).

    Returns a list of ``(plant_id, text, case_or_None)``.
    """
    roster = _roster_ids(project)
    assert roster, f"{project} has an empty roster"

    steps = []
    for index, case in enumerate(CASES):
        plant_id = roster[index % len(roster)]
        steps.append((plant_id, case["text"].format(pid=plant_id), case))

    # The novel ID, on a case with a full house of fields, so an auto-created
    # plant lands in exactly the state the fixture's ``plant_after`` records.
    novel_case = CASES[0]
    novel_id = _id_for(wrapper, NOVEL_SUFFIX)
    steps.append((novel_id, novel_case["text"].format(pid=novel_id), novel_case))
    return steps


def _apply(module, plant_id, observation, config):
    return module.update_plant(plant_id, observation, config)


def _plants_by_id(tracker):
    """Index a roster by plant ID, under either accepted spelling.

    NICK-965: the two arms of this differential replay now legitimately use
    DIFFERENT id keys -- the JSON-era arm mints ``id`` (its native format)
    and the markdown arm mints the canonical ``plant_id``. Indexing through
    ``plant_id_of`` is what lets the comparison stay about the plants'
    CONTENT, which is what this suite is pinning.
    """
    return {breeding_core.plant_id_of(p): p for p in tracker["plants"]}


# --------------------------------------------------------------------------
# The replay driver -- all six crosses, round-robin ("cycling")
# --------------------------------------------------------------------------


def _replay_all_projects(root, push=False):
    """Cycle round-robin through all six sandboxed projects, applying one
    observation per project per round, to BOTH backends from the same real
    starting data and the SAME parsed observation dict.

    Feeding both arms one observation dict (rather than parsing twice) makes
    the comparison exact: ``parse_observation`` stamps ``datetime.now()``,
    and parser equivalence itself is already pinned differentially by
    ``test_nick592_parsing_spec.py``.

    Returns ``{project: {...}}`` with each arm's final tracker, the replies,
    and (when ``push``) the bare origin.
    """
    json_era = _json_era_module()
    state = {}

    for project in PROJECTS:
        _require_project(project)
        md_dir, md_tracker = _sandbox_markdown(project, root)
        js_dir, js_tracker = _sandbox_json(project, root, json_era)
        wrapper = _load_wrapper(project, md_dir, disable_push=not push)
        bare = _init_repo_with_bare_origin(md_dir, root, project) if push else None
        state[project] = {
            "wrapper": wrapper,
            "md_dir": md_dir,
            "md_tracker": md_tracker,
            "js_dir": js_dir,
            "js_tracker": js_tracker,
            "md_config": _config(wrapper, md_dir, md_tracker, disable_push=not push),
            # The JSON-era arm NEVER pushes: its push_to_github() cd's into a
            # dashboard/ dir that does not exist in the sandbox. It is the
            # field-semantics oracle only; push behavior is pinned on the
            # markdown arm (and by Task 2.3's own tests).
            "js_config": _config(wrapper, js_dir, js_tracker, disable_push=True),
            "steps": _sequence_for(project, wrapper),
            "bare": bare,
            "md_replies": [],
            "js_replies": [],
        }

    rounds = max(len(s["steps"]) for s in state.values())
    for round_index in range(rounds):
        for project in PROJECTS:  # <- the cycling: six crosses, one process
            entry = state[project]
            if round_index >= len(entry["steps"]):
                continue
            plant_id, text, _case = entry["steps"][round_index]
            observation = breeding_core.parse_observation(text)

            entry["md_replies"].append(
                _apply(breeding_core, plant_id, observation, entry["md_config"])
            )
            entry["js_replies"].append(
                _apply(json_era, plant_id, observation, entry["js_config"])
            )

    for project in PROJECTS:
        entry = state[project]
        entry["md_final"] = breeding_core.load_tracker(entry["md_tracker"])
        entry["js_final"] = json.loads(
            entry["js_tracker"].read_text(encoding="utf-8")
        )
    return state


def _tree_digest(root):
    """SHA-256 of every file under ``root`` (``__pycache__`` excluded, since
    importing a wrapper legitimately rewrites bytecode caches in the real
    project dir and that is not a data change)."""
    entries = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            entries[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return entries


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    """THE replay: one full multi-cross cycling pass, run ONCE per session.

    Module-scoped on purpose. The pass touches six projects x two backends x
    25 observations, each writing a whole roster of markdown files; running
    it per test function would multiply that by every assertion in this file
    for no added coverage (it is deterministic apart from timestamps).

    Pushes are ENABLED so the pipeline under test is the complete one --
    ``update_plant`` -> ``save_tracker`` -> ``markdown_backend`` ->
    ``push_to_github`` -- with each origin a throwaway LOCAL BARE repo.

    Safety checksums of the six REAL project dirs and of the Phase 1
    ``breeding-markdown`` repo are taken immediately before and after the
    pass and returned under the ``_safety`` key, so the isolation tests
    assert on THIS pass rather than on an extra one.
    """
    root = tmp_path_factory.mktemp("t24")

    present = [p for p in PROJECTS if _wrapper_path(p).exists()]
    markdown_repo = MONITOR_CORE_DIR.parent / "breeding-markdown"
    before = {p: _tree_digest(BREEDING_ROOT / p) for p in present}
    before_markdown = _tree_digest(markdown_repo) if markdown_repo.exists() else None

    state = _replay_all_projects(root, push=True)

    state["_safety"] = {
        "present": present,
        "before": before,
        "after": {p: _tree_digest(BREEDING_ROOT / p) for p in present},
        "markdown_repo": markdown_repo,
        "before_markdown": before_markdown,
        "after_markdown": (
            _tree_digest(markdown_repo) if markdown_repo.exists() else None
        ),
    }
    return state


# --------------------------------------------------------------------------
# 1. Differential: markdown era == JSON era, for every plant of all six
# --------------------------------------------------------------------------


VIGOR_DEVIATION_FIELD = SPEC["known_deviation_from_json_era"]["field"]


def _assert_plant_equal(project, plant_id, md_plant, js_plant):
    # NICK-965: the ID KEY is the one field allowed to be spelled differently
    # between the arms -- 'plant_id' is canonical for markdown, 'id' is the
    # JSON era's own native format (and part of NICK-949's byte-for-byte
    # rollback contract). Compare the id's VALUE explicitly, then exclude the
    # key from the field-set/field-value differential so this suite keeps
    # pinning content equivalence rather than re-asserting the spelling this
    # task deliberately changed.
    md_identity = breeding_core.plant_id_of(md_plant)
    js_identity = breeding_core.plant_id_of(js_plant)
    assert md_identity == js_identity == plant_id, (
        f"{project}/{plant_id}: plant identity diverged between backends -- "
        f"JSON era {js_identity!r}, markdown era {md_identity!r}"
    )

    md_fields = set(md_plant) - set(ID_KEYS)
    js_fields = set(js_plant) - set(ID_KEYS)
    assert md_fields == js_fields, (
        f"{project}/{plant_id}: field set changed between backends -- "
        f"only in markdown {md_fields - js_fields}, "
        f"only in JSON {js_fields - md_fields}"
    )
    for field in sorted(md_fields):
        md_value, js_value = md_plant[field], js_plant[field]
        if field == VIGOR_DEVIATION_FIELD and md_value != js_value:
            # The ONE approved deviation (DECISIONS.md, "Task 2.2"): vigor
            # round-trips as a string because Phase 1's approved
            # plant-template.md types it as free text. It must differ ONLY by
            # that coercion -- never in value.
            assert md_value == (None if js_value is None else str(js_value)), (
                f"{project}/{plant_id}: vigor diverged beyond the documented "
                f"str() coercion -- JSON {js_value!r} vs markdown {md_value!r}"
            )
            continue
        assert md_value == js_value, (
            f"{project}/{plant_id}: field {field!r} diverged -- "
            f"JSON era {js_value!r}, markdown era {md_value!r}"
        )


def test_the_vigor_deviation_is_actually_exercised(replay):
    """Non-vacuity guard for :func:`_assert_plant_equal`'s vigor branch.

    That branch is the ONLY tolerated difference between the two backends, so
    if the replay never produced a differing vigor, the differential above
    would be silently weaker than it claims. At least one plant must show the
    documented ``int`` -> ``str`` coercion.
    """
    seen = 0
    for project in PROJECTS:
        md_plants = _plants_by_id(replay[project]["md_final"])
        js_plants = _plants_by_id(replay[project]["js_final"])
        for plant_id, md_plant in md_plants.items():
            js_vigor = js_plants[plant_id][VIGOR_DEVIATION_FIELD]
            if js_vigor is not None and md_plant[VIGOR_DEVIATION_FIELD] != js_vigor:
                assert isinstance(js_vigor, int)
                assert md_plant[VIGOR_DEVIATION_FIELD] == str(js_vigor)
                seen += 1
    assert seen, (
        "no plant exercised the documented vigor int->str deviation; the "
        "differential test's tolerance is untested"
    )


@pytest.mark.parametrize("project", PROJECTS)
def test_final_state_matches_the_json_era_for_every_plant(project, replay):
    """THE Task 2.4 acceptance criterion, differential form: after the full
    multi-cross replay, every plant of every project holds the same state
    under the markdown backend that the JSON-era pipeline produced."""
    entry = replay[project]
    md_plants = _plants_by_id(entry["md_final"])
    js_plants = _plants_by_id(entry["js_final"])

    assert sorted(md_plants) == sorted(js_plants), (
        f"{project}: roster diverged -- markdown {sorted(md_plants)} vs "
        f"JSON {sorted(js_plants)}"
    )
    assert md_plants, f"{project}: replay produced an empty roster"

    for plant_id in sorted(md_plants):
        _assert_plant_equal(project, plant_id, md_plants[plant_id], js_plants[plant_id])


@pytest.mark.parametrize("project", PROJECTS)
def test_project_level_metadata_survives_the_replay(project, replay):
    """The tracker's own top-level fields (cross_name, drive_folders,
    github_repo, notes_meta, ...) must not be lost by the migration or by
    24+ observations flowing through save_tracker."""
    entry = replay[project]
    original = _real_tracker(project)
    md_final = entry["md_final"]

    for key, value in original.items():
        if key == "plants":
            continue
        assert md_final.get(key) == value, (
            f"{project}: top-level {key!r} changed -- {value!r} -> "
            f"{md_final.get(key)!r}"
        )


@pytest.mark.parametrize("project", PROJECTS)
def test_discord_replies_are_identical_under_both_backends(project, replay):
    """Every user-visible reply string -- including the ❌ not-found reply on
    the three doc-imported rosters -- must be unchanged."""
    entry = replay[project]
    assert entry["md_replies"] == entry["js_replies"]
    assert len(entry["md_replies"]) == len(entry["steps"])


@pytest.mark.parametrize("project", PROJECTS)
def test_auto_create_policy_is_honored_per_project(project, replay):
    """The novel ID is created on the three pheno hunts and refused on the
    three doc-imported rosters -- the per-cross policy the cycling gateway
    depends on."""
    entry = replay[project]
    novel_id = _id_for(entry["wrapper"], NOVEL_SUFFIX)
    auto_create = bool(entry["wrapper"].CONFIG.get("AUTO_CREATE"))
    present = novel_id in _plants_by_id(entry["md_final"])

    assert present is auto_create, (
        f"{project}: AUTO_CREATE={auto_create} but novel plant "
        f"{novel_id} present={present}"
    )
    if not auto_create:
        assert entry["md_replies"][-1] == f"\u274c Plant {novel_id} not found"


# --------------------------------------------------------------------------
# 2. Byte-for-byte against Task 2.2's committed fixture
# --------------------------------------------------------------------------


@pytest.mark.parametrize("project", PROJECTS)
def test_autocreated_plant_matches_the_committed_fixture_byte_for_byte(
    project, replay
):
    """Where the fixture applies, it applies verbatim.

    ``plant_after`` in ``nick592_parsing_spec.json`` was derived against a
    FRESH ``make_blank_plant()`` record, so the one plant in this replay that
    starts blank -- the auto-created novel ID on a pheno hunt -- must match it
    byte for byte, along with the reply string.
    """
    entry = replay[project]
    if not entry["wrapper"].CONFIG.get("AUTO_CREATE"):
        # Not a fail-open skip: the three doc-imported rosters genuinely never
        # auto-create, and their refusal path is asserted by
        # ``test_auto_create_policy_is_honored_per_project``. That the OTHER
        # three really do exercise this comparison is guarded by
        # ``test_the_fixture_comparison_is_not_vacuous`` below.
        pytest.skip(f"{project} is a doc-imported roster; nothing is auto-created")

    novel_id = _id_for(entry["wrapper"], NOVEL_SUFFIX)
    case = entry["steps"][-1][2]
    plant = _plants_by_id(entry["md_final"])[novel_id]

    for field, expected in case["plant_after"].items():
        assert plant[field] == expected, (
            f"{project}/{novel_id}: {field!r} -- fixture says {expected!r}, "
            f"got {plant[field]!r}"
        )
    assert entry["md_replies"][-1] == f"\u2713 {novel_id} updated: {case['summary']}"


@pytest.mark.parametrize("project", PROJECTS)
def test_status_transitions_follow_the_fixture_for_every_replayed_case(
    project, replay
):
    """Replay the sequence's status expectations: for each step that carried
    a status keyword, the LAST such step for a given plant decides its final
    status -- and that value comes from the committed fixture."""
    entry = replay[project]
    expected_status = {}
    for plant_id, _text, case in entry["steps"]:
        status = case["parse"]["status"]
        if status is not None:
            expected_status[plant_id] = status

    md_plants = _plants_by_id(entry["md_final"])
    for plant_id, status in expected_status.items():
        if plant_id not in md_plants:  # refused novel ID on a fixed roster
            continue
        assert md_plants[plant_id]["status"] == status, (
            f"{project}/{plant_id}: final status {md_plants[plant_id]['status']!r}, "
            f"fixture-derived expectation {status!r}"
        )


@pytest.mark.parametrize("project", PROJECTS)
def test_every_observation_is_appended_to_its_plants_log(project, replay):
    """No observation is lost across 24+ round-robin writes per project."""
    entry = replay[project]
    md_plants = _plants_by_id(entry["md_final"])
    for plant_id, text, _case in entry["steps"]:
        if plant_id not in md_plants:
            continue
        assert text in md_plants[plant_id]["observation_log"], (
            f"{project}/{plant_id}: observation {text!r} missing from the log"
        )


def test_the_fixture_comparison_is_not_vacuous(replay):
    """Guard the skips above: NICK-1058 flipped AUTO_CREATE on for every one
    of the 6 projects this suite replays, so the byte-for-byte fixture
    comparison for a fixed-roster "not found" branch no longer runs on any
    of them -- this test now instead confirms all 6 auto-create, so a config
    regression that silently turned one back off would be caught."""
    auto = {
        project
        for project in PROJECTS
        if replay[project]["wrapper"].CONFIG.get("AUTO_CREATE")
    }
    assert auto == set(PROJECTS)


def test_every_project_replayed_the_whole_fixture(replay):
    """Each project must have replayed all 24 committed cases plus the novel
    ID -- a trimmed fixture or a short-circuited round-robin would otherwise
    pass everything above trivially."""
    assert len(CASES) == 24
    for project in PROJECTS:
        assert len(replay[project]["steps"]) == len(CASES) + 1
        assert len(replay[project]["md_replies"]) == len(CASES) + 1


# --------------------------------------------------------------------------
# 3. The persistence layer itself: markdown on disk, and the push
# --------------------------------------------------------------------------


@pytest.mark.parametrize("project", PROJECTS)
def test_the_sandbox_is_markdown_not_json(project, replay):
    entry = replay[project]
    assert (entry["md_dir"] / "project.md").is_file()
    assert not (entry["md_dir"] / "tracker.json").exists()
    on_disk = sorted(p.stem for p in (entry["md_dir"] / "plants").glob("*.md"))
    assert on_disk == sorted(_plants_by_id(entry["md_final"]))
    # No staging scratch left behind by save_tracker.
    assert not list(entry["md_dir"].glob(".save_tracker-staging-*"))


@pytest.mark.parametrize("project", PROJECTS)
def test_reloading_the_markdown_is_idempotent(project, replay, tmp_path):
    """load -> save -> load leaves the roster identical: the record of truth
    is stable, not slowly reformatted by each observation."""
    once = replay[project]["md_final"]
    # Written into a FRESH dir, not the shared replay sandbox: this test must
    # not mutate state other tests in this module read.
    scratch = tmp_path / f"idem-{project}"
    scratch.mkdir()
    tracker_file = scratch / "tracker.json"
    breeding_core.save_tracker(once, tracker_file)
    assert breeding_core.load_tracker(tracker_file) == once


def test_push_publishes_the_markdown_data_repo_for_all_six(replay):
    """Task 2.3's publisher, exercised through the full multi-cross replay:
    each project's data repo lands in ITS OWN throwaway local bare repo, with
    project.md + plants/ and nothing else."""
    for project in PROJECTS:
        entry = replay[project]
        bare = entry["bare"]
        listed = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "main"],
            cwd=bare, capture_output=True, text=True, check=True,
        ).stdout.split()

        assert "project.md" in listed, f"{project}: project.md was not published"
        assert any(p.startswith("plants/") for p in listed), (
            f"{project}: no plant records published"
        )
        assert "tracker.json" not in listed, (
            f"{project}: tracker.json leaked into the data repo"
        )
        assert not [p for p in listed if p.startswith(".save_tracker-staging-")]

        published = {
            f"plants/{plant_id}.md"
            for plant_id in _plants_by_id(entry["md_final"])
        }
        assert published <= set(listed), (
            f"{project}: published tree is missing {published - set(listed)}"
        )


# --------------------------------------------------------------------------
# 4. Safety: the real projects, wrappers and Phase 1 repo are untouched
# --------------------------------------------------------------------------


def test_the_six_real_project_dirs_are_untouched_by_a_full_replay(replay):
    """SANDBOX PROOF. Every file under all six real project dirs is
    checksummed immediately before and after the push-enabled replay (see the
    ``replay`` fixture); nothing may change."""
    safety = replay["_safety"]
    if not safety["present"]:
        pytest.skip("no real projects present")

    for project in safety["present"]:
        before, after = safety["before"][project], safety["after"][project]
        changed = sorted(set(after.items()) ^ set(before.items()))
        assert after == before, (
            f"{project}: the replay modified the REAL project directory "
            f"(changed: {changed[:5]})"
        )


def test_no_real_project_dir_gained_markdown_records(replay):
    """A replay must never MUTATE a live ``project.md``.

    NICK-948: this previously asserted no live ``project.md`` existed at all --
    correct while Phase 3 was sandbox-only, but false once the six live files
    were generated from tracker.json to unblock ``load_tracker``. The
    ``project.md`` content is covered byte-for-byte by
    ``test_the_six_real_project_dirs_are_untouched_by_a_full_replay`` above,
    which diffs every file in each real dir; this test now pins the specific
    claim that the replay neither created nor rewrote one.
    """
    safety = replay["_safety"]
    for project in safety["present"]:
        after = safety["after"][project]
        before = safety["before"][project]
        assert after.get("project.md") == before.get("project.md"), (
            f"the replay created or modified project.md in the real {project} dir"
        )


def test_the_six_wrappers_are_byte_identical_after_the_replay(replay):
    """The replay imports all six wrappers; none may be rewritten by it.
    (Their pinned pre-Task-2.1 hashes are asserted in
    ``test_wrapper_compatibility.py``; this asserts stability across THIS
    pass.)"""
    safety = replay["_safety"]
    for project in safety["present"]:
        key = "monitor_breeding_notes.py"
        assert safety["after"][project][key] == safety["before"][project][key], (
            f"{project}/monitor_breeding_notes.py changed during the replay"
        )


def test_the_phase_1_markdown_repo_is_not_written_by_a_replay(replay):
    """``breeding-markdown`` (Phase 1, approved) is a read-only dependency."""
    safety = replay["_safety"]
    if safety["before_markdown"] is None:
        pytest.skip("breeding-markdown not present")
    assert safety["after_markdown"] == safety["before_markdown"]


def test_no_replay_targets_a_real_remote(replay):
    """Every push in this file goes to a local bare repo under pytest's
    tmp dir -- never github.com."""
    for project in PROJECTS:
        entry = replay[project]
        remotes = subprocess.run(
            ["git", "remote", "-v"], cwd=entry["md_dir"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "github.com" not in remotes, f"{project}: real remote configured"
        assert str(entry["bare"]) in remotes
