"""Unit tests for the shared ID-routing check used by the Task 3.x contract.

Task 3.4 lifted "compile the migrated patterns and actually route the real
IDs" out of kibungan's module into the shared contract, and copied the same
logic a second time into `tools/verify_migration.py`. A review of that lifted
check found three gaps between what it asserts and what production
(`breeding_core._compile_prefixes` / `extract_plant_ids_*`) actually does:

1. **Cross-project collisions are not checked.** The lifted check only proves
   a project's patterns are unambiguous *among themselves*. Production routes
   one Discord message against **every** project in `registry.json`, and
   `_compile_prefixes`' caller rejects a duplicated prefix precisely because a
   collision routes one message to two crosses. A pattern widened during
   migration so that it also swallows a sibling family's IDs passes the lifted
   check on both projects and silently steals the sibling's notes.
2. **The separator class is never exercised.** Every real pattern carries a
   separator construct (`[\\s\\-]?` or `[-#]?\\s*`) and the free-text probe only
   ever used the bare `PC01` spelling, so a migration that ate the class kept
   every assertion green while `PC 01` and `PC-01` — the spellings people
   actually type in Discord — stopped routing.
3. **The compile flags did not match production.** Production compiles every
   pattern with `re.IGNORECASE`; the lifted check compiled with no flags at
   all, so it was testing a stricter matcher than the one that runs and could
   not see a pattern that routes only in one letter case.

The check is therefore one function, `migration_harness.routing_failures`,
exercised here on synthetic registry entries where each failure mode can be
constructed deliberately, and reused verbatim by the contract suite and by
the out-of-band verifier so the three cannot drift apart again.
"""

import re
from pathlib import Path

import pytest

from migration_harness import ROUTING_FLAGS, ROUTING_SEPARATORS, routing_failures

#: A well-formed single-prefix project, shaped exactly like paloma-coma's.
PC = [{"prefix": "PC", "pattern": r"\bPC[\s\-]?(\d{1,2})\b"}]
PC_IDS = ["PC01", "PC04", "PC05"]

#: A well-formed two-prefix project, shaped exactly like kibungan's.
PK_PL = [
    {"prefix": "PK", "pattern": r"(?i)(?<![A-Z0-9])PK\s*[-#]?\s*0*(\d{1,3})(?!\d)"},
    {"prefix": "PL", "pattern": r"(?i)(?<![A-Z0-9])PL\s*[-#]?\s*0*(\d{1,3})(?!\d)"},
]
PK_PL_IDS = ["PK01", "PK03", "PL05"]


def test_a_healthy_single_prefix_project_has_no_routing_failures():
    assert routing_failures(PC, PC_IDS) == []


def test_a_healthy_multi_prefix_project_has_no_routing_failures():
    assert routing_failures(PK_PL, PK_PL_IDS) == []


# ------------------------------------------------ gap 1: collisions ---------


def test_a_sibling_pattern_that_also_routes_these_ids_is_a_failure():
    """The gap no single-project check can see.

    A sibling pattern widened during migration (`\\bPL` -> `\\bP[A-Z]?`) still
    routes all of its own family, is unambiguous among its own project's
    patterns, and so passes every per-project assertion — while stealing every
    `PC..` message from paloma-coma. Production routes one message against all
    projects, so the collision is a real production break.
    """
    widened = [{"prefix": "PL", "pattern": r"\bP[A-Z]?[\s\-]?(\d{1,2})\b"}]
    failures = routing_failures(
        PC, PC_IDS, other_projects=[("kibungan-pheno-hunt", widened)]
    )
    assert failures, "a sibling pattern swallowing these IDs went unreported"
    assert any("kibungan-pheno-hunt" in f for f in failures), failures
    assert any("PC01" in f for f in failures), failures


def test_this_projects_pattern_swallowing_a_sibling_family_is_a_failure():
    """The same collision seen from the other side.

    The sibling's real IDs are not needed: a representative ID built from the
    sibling's declared prefix is enough, and it is what keeps this check
    honest for a project whose tracker is not on this machine.
    """
    greedy = [{"prefix": "PC", "pattern": r"\bP[A-Z]?[\s\-]?(\d{1,2})\b"}]
    failures = routing_failures(
        greedy, PC_IDS, other_projects=[("kibungan-pheno-hunt", PK_PL)]
    )
    assert failures, "this project's pattern swallowing PK/PL went unreported"
    assert any("PK" in f for f in failures), failures


def test_a_non_colliding_sibling_is_not_reported():
    """Guards against the collision check being trivially always-failing."""
    assert routing_failures(PC, PC_IDS, other_projects=[("kibungan", PK_PL)]) == []


# ------------------------------------------------ gap 2: separators ---------


def test_a_pattern_that_lost_its_separator_class_is_a_failure():
    """`PC 01` and `PC-01` are how people actually type IDs into Discord.

    The pattern below routes every bare ID perfectly, so a check that only
    probes `checked PC01 today` stays green while both separated spellings
    stop routing.
    """
    no_separator = [{"prefix": "PC", "pattern": r"\bPC(\d{1,2})\b"}]
    failures = routing_failures(no_separator, PC_IDS)
    assert failures, "a dropped separator class went unreported"
    assert any(" " in f or "-" in f for f in failures), failures


def test_every_separator_spelling_is_probed():
    """The empty, space and hyphen separators are all exercised.

    Named explicitly so the set cannot silently shrink back to the bare
    spelling that hid gap 2.
    """
    assert ROUTING_SEPARATORS == ("", " ", "-")


def test_a_wrong_captured_group_is_a_failure():
    """The monitor uses the captured group to pick the plant, so matching is
    not enough — the number has to come back right."""
    swallowed_digit = [{"prefix": "PC", "pattern": r"\bPC[\s\-]?\d(\d)\b"}]
    failures = routing_failures(swallowed_digit, ["PC12"])
    assert failures, "a pattern capturing the wrong number went unreported"


# ------------------------------------------------ gap 3: compile flags ------


def test_patterns_are_compiled_with_the_flags_production_uses():
    assert ROUTING_FLAGS == re.IGNORECASE


def test_the_production_prefix_compiler_really_uses_those_flags():
    """Parity is asserted against production's source, not assumed.

    `breeding_core._compile_prefixes` is the code that runs; if it ever stops
    passing `re.IGNORECASE`, this contract is testing a matcher that no longer
    exists. Read statically rather than imported: importing the monitor pulls
    in its Discord/Drive machinery, which the migration suite must never do.
    """
    core = (
        Path.home()
        / ".hermes"
        / "breeding"
        / "_shared"
        / "monitor-core"
        / "breeding_core.py"
    )
    if not core.exists():
        pytest.skip("production breeding_core.py not present on this machine")
    source = core.read_text(encoding="utf-8")
    assert "re.compile(spec['pattern'], re.IGNORECASE)" in source, (
        "production no longer compiles routing patterns with re.IGNORECASE -- "
        "the migration contract is now testing a different matcher"
    )


def test_a_pattern_that_routes_in_only_one_case_is_a_failure():
    """Production compiles with `re.IGNORECASE`, so `pc-01` routes in real
    life. A scoped `(?-i:...)` makes the prefix case-sensitive again: it
    passes a no-flags check and fails under production's flags."""
    case_locked = [{"prefix": "PC", "pattern": r"(?-i:\bPC)[\s\-]?(\d{1,2})\b"}]
    failures = routing_failures(case_locked, PC_IDS)
    assert failures, "a case-locked pattern went unreported"


def test_a_lowercase_prefix_project_routes_under_production_flags():
    """spaced-paste really does use a lowercase `sp`; under production's
    IGNORECASE both spellings must route, and neither may be reported."""
    sp = [{"prefix": "sp", "pattern": r"\bsp[\s\-]?(\d{1,2})\b"}]
    assert routing_failures(sp, ["sp01", "sp05"]) == []


# ------------------------------------------------ retained properties -------


def test_a_pattern_matching_a_sibling_prefixs_ids_within_one_project_is_a_failure():
    ambiguous = [
        {"prefix": "PK", "pattern": r"(?<![A-Z0-9])P[KL]\s*[-#]?\s*0*(\d{1,3})(?!\d)"},
        {"prefix": "PL", "pattern": r"(?<![A-Z0-9])PL\s*[-#]?\s*0*(\d{1,3})(?!\d)"},
    ]
    failures = routing_failures(ambiguous, PK_PL_IDS)
    assert failures, "an intra-project collision went unreported"
    assert any("PL05" in f for f in failures), failures


def test_a_lost_boundary_construct_is_a_failure():
    unanchored = [{"prefix": "PC", "pattern": r"PC[\s\-]?(\d{1,2})"}]
    failures = routing_failures(unanchored, PC_IDS)
    assert failures, "a dropped boundary construct went unreported"


def test_no_patterns_or_no_ids_is_a_failure_rather_than_a_vacuous_pass():
    assert routing_failures([], PC_IDS), "an empty pattern list passed vacuously"
    assert routing_failures(PC, []), "an empty ID list passed vacuously"
