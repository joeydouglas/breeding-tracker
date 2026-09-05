"""Fixture-driven regression tests for NICK-592 parsing / status detection.

WHAT THIS FILE PINS (Phase 2, Task 2.2)
---------------------------------------
Task 2.1 replaced ``breeding_core``'s persistence backend (``tracker.json``
-> ``project.md`` + ``plants/<ID>.md``). The explicit contract of that task
was *"same parsing/status-detection logic, only persistence calls change"*.
Nothing in the suite actually enforced that: before this file, zero tests
touched ``parse_observation()`` at all, and ``update_plant()``'s field-merge
was only covered incidentally (one ``vigor 8 / fuel / keeper`` string). So a
silent change to vigor extraction, the terpene or structure vocabulary, or
the status precedence chain would have shipped green.

The expectations live in a committed, versioned data file --
``tests/fixtures/nick592_parsing_spec.json`` -- not in inline magic strings
and not in a reference to any session transcript. See that file's own
``description`` for its provenance.

PROVENANCE OF THE SPEC (see also the fixture's ``description`` field):
  * The *status vocabulary* is documented in ``breeding_core.py``'s module
    docstring: NICK-592 consolidated six drifted copies of this logic after
    NICK-589 found Mule Fuel, Lantz and Spaced Paste missing keeper/culled
    detection entirely (a live Ltz07 cull note updated ``observation_log``
    but not ``plant['status']``).
  * The *exhaustive per-case expectations* are NOT documented anywhere; they
    were DERIVED from the JSON-era implementation. To keep that derivation
    honest rather than circular, ``test_baseline_differential.py``-style
    coverage is built in here: :func:`_json_era_module` loads
    ``breeding_core.py`` as it existed at the pre-Phase-2 baseline commit and
    every fixture case is asserted against BOTH implementations. The fixture
    is therefore a pin on the JSON era's real behavior, not merely on today's.

Everything here is SANDBOX-ONLY (pytest ``tmp_path``): no Discord, Drive,
network or git-push side effect, and no real project directory is written.
"""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nick592_parsing_spec.json"

# The pre-Phase-2 baseline: "Baseline: monitor-core as of pre-Phase-2 (JSON
# tracker persistence)". The JSON-era parse_observation/update_plant field
# logic is the specification this task must not have changed.
BASELINE_COMMIT = "2dd0537"

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

import breeding_core  # noqa: E402

SPEC = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = SPEC["cases"]
CASE_IDS = [c["name"] for c in CASES]

PLANT_ID = "MG04"


def _fmt(case_text):
    return case_text.format(pid=PLANT_ID)


# --------------------------------------------------------------------------
# The JSON-era implementation, loaded straight out of git history.
# --------------------------------------------------------------------------


def _json_era_module():
    """``breeding_core`` as of the pre-Phase-2 baseline commit.

    Executed in an isolated module namespace. Only ``parse_observation`` and
    ``make_blank_plant`` are ever called from it -- both are pure, so nothing
    touches the filesystem, the network, or a real project directory.
    """
    proc = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:breeding_core.py"],
        cwd=MONITOR_CORE_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"baseline commit {BASELINE_COMMIT} not available")

    module = types.ModuleType("_json_era_breeding_core")
    module.__file__ = str(MONITOR_CORE_DIR / "breeding_core.py")
    exec(compile(proc.stdout, "<json-era breeding_core.py>", "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def json_era():
    return _json_era_module()


# --------------------------------------------------------------------------
# parse_observation() -- the fixture is the spec
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_parse_observation_matches_the_committed_spec(case):
    obs = breeding_core.parse_observation(_fmt(case["text"]))
    expected = case["parse"]

    assert obs["vigor"] == expected["vigor"], f"vigor: {case['name']}"
    assert obs["terpenes"] == expected["terpenes"], f"terpenes: {case['name']}"
    assert obs["structure"] == expected["structure"], f"structure: {case['name']}"
    assert obs["status"] == expected["status"], f"status: {case['name']}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_parse_observation_is_identical_to_the_json_era(case, json_era):
    """Differential test: today's parser vs. the pre-Phase-2 parser.

    This is what makes the fixture a pin on NICK-592's *established* behavior
    rather than a snapshot of whatever the code happens to do now.
    """
    text = _fmt(case["text"])
    now = breeding_core.parse_observation(text)
    then = json_era.parse_observation(text)

    for field in ("vigor", "terpenes", "structure", "status", "raw_text"):
        assert now[field] == then[field], (
            f"{case['name']}: parse_observation()['{field}'] changed since the "
            f"JSON era -- {then[field]!r} -> {now[field]!r}"
        )


def test_parse_observation_shape_is_unchanged(json_era):
    """The returned dict's key set is part of the contract (wrappers and
    photo_handler read it positionally by key)."""
    text = "MG04 vigor 8, fuel, keeper"
    assert set(breeding_core.parse_observation(text)) == set(
        json_era.parse_observation(text)
    )


def test_keyword_vocabularies_are_unchanged(json_era):
    assert breeding_core.TERPENE_KEYWORDS == json_era.TERPENE_KEYWORDS
    assert breeding_core.STRUCTURE_KEYWORDS == json_era.STRUCTURE_KEYWORDS


def test_make_blank_plant_is_unchanged(json_era):
    assert breeding_core.make_blank_plant("MG04", "X x Y") == json_era.make_blank_plant(
        "MG04", "X x Y"
    )


# --------------------------------------------------------------------------
# The three status keywords, called out explicitly
# --------------------------------------------------------------------------


def test_the_status_vocabulary_is_exactly_three_keywords():
    """NICK-592 established three status values; a fourth (or a rename) is a
    breaking change for the dashboard and every wrapper."""
    assert set(SPEC["status_vocabulary"]) == {"top_keeper", "culled", "keeper"}

    produced = {
        breeding_core.parse_observation(f"MG04 {trigger}")["status"]
        for entry in SPEC["status_vocabulary"].values()
        for trigger in entry["triggers"]
    }
    assert produced == {"top_keeper", "culled", "keeper"}


@pytest.mark.parametrize(
    "status,trigger",
    [
        (status, trigger)
        for status, entry in SPEC["status_vocabulary"].items()
        for trigger in entry["triggers"]
    ],
)
def test_every_documented_trigger_produces_its_status(status, trigger):
    assert breeding_core.parse_observation(f"MG04 {trigger}")["status"] == status


def test_status_precedence_order_is_pinned():
    """top_keeper > culled > keeper. 'top keeper' must not degrade to a bare
    'keeper', and a cull note must win over a keeper note in the same line."""
    assert breeding_core.parse_observation("MG04 top keeper")["status"] == "top_keeper"
    assert (
        breeding_core.parse_observation("MG04 keeper but cull it")["status"] == "culled"
    )
    assert (
        breeding_core.parse_observation("MG04 elite, cull its sibling")["status"]
        == "top_keeper"
    )


# --------------------------------------------------------------------------
# update_plant()'s field merge -- markdown era must equal the JSON era
# --------------------------------------------------------------------------


def _sandbox(tmp_path):
    """An empty, already-migrated sandbox project (AUTO_CREATE style)."""
    project = tmp_path / "sandbox-cross"
    project.mkdir()
    tracker_file = project / "tracker.json"
    breeding_core.save_tracker(
        {"cross": "Sandbox x Cross", "plants": []}, tracker_file
    )
    return project, tracker_file


def _config(project, tracker_file):
    return {
        "BREEDING_DIR": project,
        "TRACKER_FILE": tracker_file,
        "GITHUB_REPO": "example/none",
        "DISABLE_GITHUB_PUSH": True,
        "CROSS_NAME": "Sandbox x Cross",
        "AUTO_CREATE": True,
    }


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_update_plant_field_merge_matches_the_committed_spec(case, tmp_path):
    """The acceptance criterion: an observation carrying a status keyword must
    produce the identical ``plant['status']`` under markdown that the JSON era
    documented -- plus the same vigor / terpene_notes / structure handling."""
    project, tracker_file = _sandbox(tmp_path)
    config = _config(project, tracker_file)

    observation = breeding_core.parse_observation(_fmt(case["text"]))
    breeding_core.update_plant(PLANT_ID, observation, config)

    plant = next(
        p
        for p in breeding_core.load_tracker(tracker_file)["plants"]
        if p["id"] == PLANT_ID
    )
    for field, expected in case["plant_after"].items():
        assert plant[field] == expected, (
            f"{case['name']}: plant['{field}'] -- expected {expected!r}, "
            f"got {plant[field]!r}"
        )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_update_plant_summary_string_matches_the_committed_spec(case, tmp_path):
    """The Discord-visible reply string is part of the pinned behavior."""
    project, tracker_file = _sandbox(tmp_path)
    observation = breeding_core.parse_observation(_fmt(case["text"]))

    result = breeding_core.update_plant(
        PLANT_ID, observation, _config(project, tracker_file)
    )
    assert result == f"\u2713 {PLANT_ID} updated: {case['summary']}"


def test_status_is_left_alone_when_the_observation_has_no_keyword(tmp_path):
    """A statusless note must not reset a previously decided status."""
    project, tracker_file = _sandbox(tmp_path)
    config = _config(project, tracker_file)

    breeding_core.update_plant(
        PLANT_ID, breeding_core.parse_observation(f"{PLANT_ID} top keeper"), config
    )
    breeding_core.update_plant(
        PLANT_ID, breeding_core.parse_observation(f"{PLANT_ID} vigor 7"), config
    )

    plant = next(
        p
        for p in breeding_core.load_tracker(tracker_file)["plants"]
        if p["id"] == PLANT_ID
    )
    assert plant["status"] == "top_keeper"
    assert plant["vigor"] == "7"


def test_vigor_is_stored_as_a_string_by_the_markdown_backend(tmp_path):
    """The ONE documented deviation from the JSON era -- and it is a
    persistence-layer coercion, not a parsing change.

    ``parse_observation()`` still returns an ``int`` and ``update_plant()``
    still assigns that ``int`` in memory (both asserted below, against the
    JSON-era module). The type changes only on the round-trip through
    ``plants/<ID>.md``, because Phase 1's canonical, Joey-approved
    ``plant-template.md`` declares ``vigor`` as a free-text STRING -- an
    integer ``vigor`` was explicitly reverted as an unapproved schema change
    (see breeding-markdown/DECISIONS.md). Pinned here rather than "fixed",
    since fixing it would mean editing an approved schema this task must not
    touch. Impact on real data is nil: vigor is null on all 95 real plants.
    """
    deviation = SPEC["known_deviation_from_json_era"]
    assert deviation["field"] == "vigor"

    project, tracker_file = _sandbox(tmp_path)
    observation = breeding_core.parse_observation(f"{PLANT_ID} vigor 9")

    # In memory: still an int, exactly as in the JSON era.
    assert observation["vigor"] == 9
    assert isinstance(observation["vigor"], int)

    breeding_core.update_plant(PLANT_ID, observation, _config(project, tracker_file))

    plant = next(
        p
        for p in breeding_core.load_tracker(tracker_file)["plants"]
        if p["id"] == PLANT_ID
    )
    # On disk / after reload: a string.
    assert plant["vigor"] == "9"
    assert isinstance(plant["vigor"], str)


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.get("vigor_type_deviation")],
    ids=[c["name"] for c in CASES if c.get("vigor_type_deviation")],
)
def test_vigor_deviation_cases_differ_only_by_string_coercion(case):
    """Every case flagged with the deviation must differ from its recorded
    JSON-era expectation in exactly one way: ``str(vigor)``. Any other drift
    means the migration changed more than persistence."""
    now = case["plant_after"]
    then = case["plant_after_json_era"]

    assert set(now) == set(then)
    assert now["vigor"] == str(then["vigor"])
    for field in set(now) - {"vigor"}:
        assert now[field] == then[field], (
            f"{case['name']}: {field} drifted beyond the vigor coercion"
        )


def test_status_result_is_identical_under_markdown_and_the_json_era(tmp_path):
    """THE Task 2.2 acceptance criterion, stated directly.

    For every fixture case, the ``plant['status']`` that survives a full
    markdown round-trip must equal the status the JSON-era pipeline produced.
    The JSON-era half is computed with the baseline module's own
    ``parse_observation`` + ``make_blank_plant`` and its literal field-merge
    rule (``if observation['status']: plant['status'] = observation['status']``),
    then persisted with ``json.dumps``/``json.loads`` to mirror the old
    backend exactly.
    """
    json_era = _json_era_module()

    for case in CASES:
        text = _fmt(case["text"])

        # --- JSON era ---
        legacy_plant = json_era.make_blank_plant(PLANT_ID, "Sandbox x Cross")
        legacy_obs = json_era.parse_observation(text)
        if legacy_obs.get("status"):
            legacy_plant["status"] = legacy_obs["status"]
        legacy_status = json.loads(json.dumps(legacy_plant))["status"]

        # --- markdown era, through the real update_plant() ---
        case_dir = tmp_path / case["name"]
        case_dir.mkdir()
        project, tracker_file = _sandbox(case_dir)
        breeding_core.update_plant(
            PLANT_ID,
            breeding_core.parse_observation(text),
            _config(project, tracker_file),
        )
        markdown_status = next(
            p
            for p in breeding_core.load_tracker(tracker_file)["plants"]
            if p["id"] == PLANT_ID
        )["status"]

        assert markdown_status == legacy_status, (
            f"{case['name']}: status diverged -- JSON era {legacy_status!r}, "
            f"markdown {markdown_status!r}"
        )
        assert markdown_status == case["plant_after"]["status"]


def test_terpene_notes_accumulate_across_observations(tmp_path):
    """Pinned from the fixture's ``terpene_accumulation`` block: terpene notes
    append with '; ' and never grow a leading separator."""
    for index, step in enumerate(SPEC["terpene_accumulation"]["steps"]):
        step_dir = tmp_path / f"step{index}"
        step_dir.mkdir()
        project, tracker_file = _sandbox(step_dir)
        config = _config(project, tracker_file)

        plant = breeding_core.make_blank_plant(PLANT_ID, "Sandbox x Cross")
        plant["terpene_notes"] = step["existing"]
        tracker = breeding_core.load_tracker(tracker_file)
        tracker["plants"].append(plant)
        breeding_core.save_tracker(tracker, tracker_file)

        observation = breeding_core.parse_observation(_fmt(step["text"]))
        breeding_core.update_plant(PLANT_ID, observation, config)

        stored = next(
            p
            for p in breeding_core.load_tracker(tracker_file)["plants"]
            if p["id"] == PLANT_ID
        )
        assert stored["terpene_notes"] == step["expected"], (
            f"existing={step['existing']!r} + {step['text']!r} -> "
            f"{stored['terpene_notes']!r}, expected {step['expected']!r}"
        )


def test_observation_log_gains_one_entry_per_observation(tmp_path):
    project, tracker_file = _sandbox(tmp_path)
    config = _config(project, tracker_file)

    for text in (f"{PLANT_ID} vigor 5", f"{PLANT_ID} keeper"):
        breeding_core.update_plant(
            PLANT_ID, breeding_core.parse_observation(text), config
        )

    plant = next(
        p
        for p in breeding_core.load_tracker(tracker_file)["plants"]
        if p["id"] == PLANT_ID
    )
    assert plant["observation_log"].count("### ") == 2
    assert f"{PLANT_ID} vigor 5" in plant["observation_log"]
    assert f"{PLANT_ID} keeper" in plant["observation_log"]


def test_structure_is_reported_but_never_persisted(tmp_path):
    """Pinned as-is, and deliberately called out: parse_observation fills
    ``observation['structure']`` and update_plant puts it in the reply
    summary, but it is never written to ``plant['structure']``. That asymmetry
    is JSON-era behavior; changing it is a product decision, not a refactor."""
    project, tracker_file = _sandbox(tmp_path)
    observation = breeding_core.parse_observation(f"{PLANT_ID} frosty and dense")
    assert observation["structure"] == ["frosty", "dense"]

    result = breeding_core.update_plant(
        PLANT_ID, observation, _config(project, tracker_file)
    )
    assert "frosty, dense" in result

    plant = next(
        p
        for p in breeding_core.load_tracker(tracker_file)["plants"]
        if p["id"] == PLANT_ID
    )
    assert plant["structure"] is None


# --------------------------------------------------------------------------
# Fixture hygiene
# --------------------------------------------------------------------------


def test_fixture_covers_every_required_behavior():
    """Guard against someone trimming the fixture down to the single 'cull'
    case that Revision 1 originally asked for."""
    covered_status = {c["parse"]["status"] for c in CASES}
    assert {"top_keeper", "culled", "keeper", None} <= covered_status

    assert any(c["parse"]["vigor"] for c in CASES), "no vigor coverage"
    assert any(c["parse"]["terpenes"] for c in CASES), "no terpene coverage"
    assert any(c["parse"]["structure"] for c in CASES), "no structure coverage"

    # Every declared keyword constant appears in at least one case.
    all_text = " ".join(c["text"] for c in CASES).lower()
    for kw in breeding_core.TERPENE_KEYWORDS:
        assert kw in all_text, f"terpene keyword {kw!r} is not exercised"


def test_fixture_case_names_are_unique():
    assert len(CASE_IDS) == len(set(CASE_IDS))


def test_fixture_is_versioned():
    assert SPEC["fixture_version"] >= 1
