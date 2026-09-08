"""NICK-924 -- TDD: unify each wrapper's PLANT_ID_PATTERN with the gateway's
real, live PLANT_ID_REGISTRY extraction pattern (case-insensitive, '#'
syntax, leading zeros, up to 3 digits), so registry.json can then describe
one true routing/extraction contract instead of choosing between two
already-disagreeing live systems.

WHY THIS EXISTS. Investigating NICK-924's acceptance criterion (a) ("old vs
registry-derived routing compared and confirmed identical... before
switching") surfaced a live bug that predates NICK-924 entirely and is
independent of registry.json: for 5 of 6 projects, the GATEWAY's routing
regex (breeding-ingest/breeding_tracker/discord_ingest.py's
PLANT_ID_REGISTRY -- what decides which project a message routes to) is
MORE PERMISSIVE than that same project's own WRAPPER extraction regex
(monitor_breeding_notes.py's PLANT_ID_PATTERN -- what
breeding_core.process_message() actually uses to pull the ID out once
routed). Kibungan is the sole exception: its wrapper already uses the
permissive PLANT_ID_REGISTRY style, proving it is the correct shape.

Reproduced directly (2026-09-07, real regex objects, no live write):

    "MG04 looking great"   -> gateway routes to mule-fuel, wrapper extracts MG04  (agrees)
    "mg04 looking great"   -> gateway routes to mule-fuel, wrapper extracts MG04  (agrees)
    "MG#04 vigor 8"        -> gateway routes to mule-fuel, wrapper extracts NOTHING (SILENT DROP)
    "MG104 vigor 8"        -> gateway routes to mule-fuel, wrapper extracts NOTHING (SILENT DROP)
    "MG004 vigor 8"        -> gateway routes to mule-fuel, wrapper extracts NOTHING (SILENT DROP)

process_message() returns None on zero extracted IDs -- "no plant IDs found,
ignore message" -- so a message the gateway correctly routed is then
silently discarded by that project's own wrapper, with no error, no log
visible to the operator, and no record anywhere that it happened. Same class
of bug as NICK-979 (an ID a person plausibly typed silently failing to
route/record), different layer.

THE FIX. Each of the 5 affected wrappers' PLANT_ID_PATTERN is widened to the
exact shape already proven live by Kibungan's PLANT_ID_REGISTRY entries and
the gateway's PLANT_ID_REGISTRY: case-insensitive, optional '#' or '-'
separator, optional leading zeros, 1-3 digits, negative lookbehind/lookahead
so e.g. "MG104" is not truncated to a false partial match. This is a STRICT
WIDENING -- every message the old, narrower pattern matched, the new pattern
also matches with an IDENTICAL captured/normalized ID (verified per-project
below against a shared corpus). Nothing that worked before now behaves
differently; only previously-silently-dropped messages start being
recorded.

registry.json is then made to describe this SAME unified pattern (not the
old, narrower one) for all 6 projects, so it can genuinely serve as "the one
routing/extraction table both the gateway and each wrapper agree with" --
which is what NICK-924's cutover requires before any project can be flipped
onto it.

SANDBOX-ONLY / read-real-write-nowhere: every wrapper is imported read-only
(module-level constant introspection); no tracker.json, no plant markdown,
no git push, no BREEDING_DIR write anywhere in this suite.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_ROOT = MONITOR_CORE_DIR.parents[1]
BREEDING_INGEST_DIR = BREEDING_ROOT / "_shared" / "breeding-ingest"
BREEDING_META_DIR = BREEDING_ROOT / "_shared" / "breeding-meta"

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

# The five wrappers whose PLANT_ID_PATTERN historically disagreed with the
# gateway's permissive style. Kibungan is intentionally excluded -- it
# already uses PLANT_ID_REGISTRY (the correct, proven shape) and is the
# reference this fix widens the other five to match.
SINGLE_PREFIX_PROJECTS = {
    "mule-fuel-x-nana-glue": "MG",
    "lantz": "LTZ",
    "spaced-paste": "SP",
    "paloma-coma": "PC",
    "honey-badger-haze-pheno-hunt": "HBH",
}

# The corpus every project's OLD pattern already matched -- the fix must be
# a strict superset, producing the IDENTICAL normalized ID on every one of
# these for every project (parametrized per-prefix below).
ALREADY_WORKING_MESSAGES = [
    ("{p}04 looking great", "04"),
    ("{p} 04 looking great", "04"),
    ("{p}-04 looking great", "04"),
    ("{p}4 looking great", "04"),
]

# The corpus the OLD pattern silently dropped and the gateway already routed
# correctly -- the new pattern must extract these too, with the SAME
# normalized two-digit-minimum ID the gateway itself derives.
PREVIOUSLY_DROPPED_MESSAGES = [
    ("{p}#04 vigor 8", "04"),
    ("{p}04 vigor 8".lower(), "04"),  # placeholder, replaced per-prefix below
    ("{p}004 vigor 8", "04"),
    ("{p}104 vigor 8", "104"),
]


def _load_wrapper_module(project):
    path = BREEDING_ROOT / project / "monitor_breeding_notes.py"
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")
    mod_name = f"_nick924_sandbox_{project.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(mod_name, None)
    return module


def _gateway_pattern_for(prefix):
    """The real, live gateway pattern for ``prefix`` -- the widening target."""
    sys.path.insert(0, str(BREEDING_INGEST_DIR))
    from breeding_tracker.discord_ingest import PLANT_ID_REGISTRY

    for p, compiled in PLANT_ID_REGISTRY:
        if p == prefix:
            return compiled
    raise KeyError(f"no gateway pattern for prefix {prefix!r}")


@pytest.mark.parametrize("project,prefix", sorted(SINGLE_PREFIX_PROJECTS.items()))
def test_wrapper_pattern_now_matches_the_gateways_permissive_shape(project, prefix):
    """The core NICK-924 fix, proven per-project: wrapper extraction now
    agrees with the gateway's routing decision on messages that used to be
    silently dropped."""
    module = _load_wrapper_module(project)
    wrapper_pattern = module.PLANT_ID_PATTERN
    gateway_pattern = _gateway_pattern_for(prefix)

    previously_dropped = [
        f"{prefix}#04 vigor 8",
        f"{prefix.lower()}04 vigor 8",
        f"{prefix}004 vigor 8",
        f"{prefix}104 vigor 8",
    ]
    for text in previously_dropped:
        wrapper_matches = re.findall(wrapper_pattern, text, re.IGNORECASE)
        gateway_matches = gateway_pattern.findall(text)
        wrapper_ids = [f"{prefix}{int(d):02d}" for d in wrapper_matches]
        gateway_ids = [f"{prefix}{int(d):02d}" for d in gateway_matches]
        assert wrapper_ids, (
            f"{project}: {text!r} still silently drops -- wrapper pattern "
            f"{wrapper_pattern!r} extracted nothing"
        )
        assert wrapper_ids == gateway_ids, (
            f"{project}: {text!r} -- wrapper extracted {wrapper_ids!r}, "
            f"gateway would route/extract {gateway_ids!r}"
        )


@pytest.mark.parametrize("project,prefix", sorted(SINGLE_PREFIX_PROJECTS.items()))
def test_wrapper_pattern_is_a_strict_superset_of_the_old_behavior(project, prefix):
    """Nothing that worked before must now behave differently -- same ID,
    same match, for every message the OLD narrower pattern already handled."""
    OLD_PATTERNS = {
        "MG": r"\bMG[\s\-]?(\d{1,2})\b",
        "LTZ": r"\bLtz[\s\-]?(\d{1,2})\b",
        "SP": r"\bsp[\s\-]?(\d{1,2})\b",
        "PC": r"\bPC[\s\-]?(\d{1,2})\b",
        "HBH": r"\bHBH[\s\-]?(\d{1,2})\b",
    }
    module = _load_wrapper_module(project)
    new_pattern = module.PLANT_ID_PATTERN
    old_pattern = OLD_PATTERNS[prefix]

    still_working = [
        f"{prefix}04 looking great",
        f"{prefix} 04 looking great",
        f"{prefix}-04 looking great",
        f"{prefix}4 looking great",
    ]
    for text in still_working:
        old_matches = re.findall(old_pattern, text, re.IGNORECASE)
        new_matches = re.findall(new_pattern, text, re.IGNORECASE)
        old_ids = [f"{prefix}{int(d):02d}" for d in old_matches]
        new_ids = [f"{prefix}{int(d):02d}" for d in new_matches]
        assert old_ids, f"corpus bug: {text!r} should have matched the OLD pattern"
        assert new_ids == old_ids, (
            f"{project}: {text!r} -- OLD pattern gave {old_ids!r}, "
            f"NEW pattern gives {new_ids!r} (regression, not just a widening)"
        )


def test_registry_json_now_matches_the_unified_gateway_pattern_for_all_six():
    """registry.json's plant_id_prefixes patterns must equal the gateway's
    real PLANT_ID_REGISTRY pattern text for every one of the 6 projects --
    the actual NICK-924 acceptance-criterion-(a) equivalence check, now
    satisfiable because the wrappers were widened to match instead of
    registry.json being pointed at whichever side was more convenient."""
    import json as _json

    registry = _json.loads(
        (BREEDING_META_DIR / "registry.json").read_text(encoding="utf-8")
    )
    sys.path.insert(0, str(BREEDING_INGEST_DIR))
    from breeding_tracker.discord_ingest import PLANT_ID_REGISTRY

    gateway_by_prefix = {p: compiled.pattern for p, compiled in PLANT_ID_REGISTRY}

    checked = 0
    for project in registry["projects"]:
        for entry in project["plant_id_prefixes"]:
            prefix = entry["prefix"]
            assert prefix in gateway_by_prefix, (
                f"registry.json project {project['slug']!r} declares prefix "
                f"{prefix!r} which the gateway's PLANT_ID_REGISTRY does not know"
            )
            assert entry["pattern"] == gateway_by_prefix[prefix], (
                f"registry.json project {project['slug']!r} prefix {prefix!r} "
                f"pattern {entry['pattern']!r} != gateway pattern "
                f"{gateway_by_prefix[prefix]!r}"
            )
            checked += 1
    assert checked == 7, f"expected 7 prefix entries (6 projects, Kibungan has 2), got {checked}"
