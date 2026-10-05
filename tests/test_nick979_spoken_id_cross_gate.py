"""NICK-979 -- TDD: deterministic cross-name pre-filter gates the spoken-ID
LLM fallback so it can no longer hallucinate a cross with zero cross-name
evidence in the transcript.

WHY THIS EXISTS. The original NICK-979 bug (one ambiguous message like
"number seven" simultaneously misrouting into all 4 crosses sharing that
digit) was fixed on 2026-09-04 by making the spoken-ID resolver issue ONE
LLM call across all crosses, requiring the transcript to name/imply exactly
one cross. That fix is real and verified working for its own reproduction
case. But it is a PROMPT-level constraint, not a structural one -- the model
is still free to invent a cross match. Reproduced live (2026-09-07, this
investigation): with real Ollama/qwen2.5:7b-instruct running,

    "Totally keeping number seven."
    "Keeping number seven."
    "Definitely keeping number seven, its a top keeper."

all resolve to PC07 with ZERO cross name or alias anywhere in the text --
100% reproducible across 5 runs. This is the same bug CLASS as the original
report (a bare "number N" phrase resolving to a real cross with no
disambiguating evidence), just narrower in trigger phrasing.

THE FIX. A deterministic, LLM-free pre-filter runs BEFORE any LLM call:
``_mentions_known_cross(text, known)`` does a case-insensitive word-boundary
substring match of each cross's short spoken alias (not its full
tracker.json cross_name, which for two projects both contain the shared
substring "Nana Glue" and would falsely co-match -- see
CROSS_ALIASES's own docstring). The LLM is invoked ONLY when the filter
finds EXACTLY ONE candidate cross; zero matches or more than one match skip
the LLM call entirely and return no plant ID (a dropped/no-op message is the
safe failure -- a misrouted one is not). This closes the bug class
structurally: there is no code path left where the model can produce an ID
for a transcript that never named its cross, because that transcript never
reaches the model in the first place.

Every test here is fully offline/deterministic -- no real LLM call, no
real breeding_dir/tracker.json write. ``known`` is a synthetic
{prefix: (cross_name, [ids])} map matching _known_plant_ids()'s real return
shape, built inline per test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN_DIR = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "hermes-breeding-ingest"
)
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


@pytest.fixture
def plugin_module(monkeypatch):
    """Import the plugin module without its real _CROSS_DIRS filesystem
    check blocking import (it validates real ~/.hermes/breeding paths at
    import time, which is fine in this environment -- real dirs DO exist --
    but keeping this fixture explicit documents the dependency rather than
    relying on it silently)."""
    import importlib

    import __init__ as module  # the plugin package itself

    importlib.reload(module)
    return module


# --------------------------------------------------- _mentions_known_cross --


def test_bare_number_with_no_cross_name_matches_nothing(plugin_module):
    """The exact reproduced bug input: must NOT identify any cross."""
    known = {
        "PC": ("Paloma Coma", ["PC07"]),
        "MG": ("Mule Fuel x Nana Glue", ["MG07"]),
    }
    assert plugin_module._mentions_known_cross("Totally keeping number seven.", known) == []
    assert plugin_module._mentions_known_cross("Keeping number seven.", known) == []
    assert (
        plugin_module._mentions_known_cross(
            "Definitely keeping number seven, its a top keeper.", known
        )
        == []
    )


def test_explicit_cross_name_matches_exactly_that_cross(plugin_module):
    known = {
        "PC": ("Paloma Coma", ["PC07"]),
        "MG": ("Mule Fuel x Nana Glue", ["MG07"]),
    }
    assert plugin_module._mentions_known_cross(
        "Hello, Paloma Coma. Number seven is fucking good.", known
    ) == ["PC"]


def test_two_crosses_sharing_nana_glue_substring_do_not_cross_match(plugin_module):
    """Mule Fuel x Nana Glue and Spaced Paste (Dulce de Uva x Nana Glue)
    both genuinely contain 'Nana Glue' in their real tracker.json cross_name
    -- a naive full-cross_name substring match would treat any mention of
    'Nana Glue' as ambiguous between them (or worse, silently match the
    wrong one). The short-alias design must not use 'Nana Glue' as either
    project's matching alias."""
    known = {
        "MG": ("Mule Fuel x Nana Glue", ["MG07"]),
        "SP": ("Spaced Paste (Dulce de Uva x Nana Glue)", ["SP05"]),
    }
    assert plugin_module._mentions_known_cross("Nana Glue looking healthy today", known) == []
    assert plugin_module._mentions_known_cross("Mule Fuel number seven, vigor 8", known) == ["MG"]
    assert plugin_module._mentions_known_cross("Spaced Paste number five is a keeper", known) == ["SP"]


def test_multiple_named_crosses_in_one_message_is_ambiguous_not_a_pick(plugin_module):
    known = {
        "PC": ("Paloma Coma", ["PC07"]),
        "MG": ("Mule Fuel x Nana Glue", ["MG07"]),
    }
    text = "Paloma Coma number seven and Mule Fuel number seven both look great"
    # Ambiguous input must not silently resolve to either -- both matched,
    # which the resolver (tested below) must treat as "do not call the LLM".
    assert sorted(plugin_module._mentions_known_cross(text, known)) == ["MG", "PC"]


def test_short_alias_is_case_insensitive_and_word_bounded(plugin_module):
    known = {"HBH": ("Honey Badger Haze", ["HBH07"])}
    assert plugin_module._mentions_known_cross("honey badger haze, number seven", known) == ["HBH"]
    assert plugin_module._mentions_known_cross("HONEY BADGER HAZE NUMBER SEVEN", known) == ["HBH"]
    # Must not fire on an unrelated word that merely shares a substring
    # ("honeybadgerhazelnut" is contrived but proves word-boundary, not
    # naive .contains()).
    assert plugin_module._mentions_known_cross("honeybadgerhazelnut number seven", known) == []


# ------------------------------------------------ _make_spoken_id_resolver -


def test_resolver_skips_the_llm_entirely_when_no_cross_is_named(plugin_module, monkeypatch):
    """The structural fix: zero cross mentions -> zero LLM calls, full stop."""
    called = {"n": 0}

    def _fake_known():
        return {"PC": ("Paloma Coma", ["PC07"])}

    def _fake_llm(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("LLM must not be called when no cross was named")

    monkeypatch.setattr(plugin_module, "_known_plant_ids", _fake_known)
    monkeypatch.setattr(plugin_module, "_call_default_llm", _fake_llm)

    resolver = plugin_module._make_spoken_id_resolver()
    result = resolver("Totally keeping number seven.")

    assert result == []
    assert called["n"] == 0


def test_resolver_skips_the_llm_when_two_crosses_named_ambiguously(plugin_module, monkeypatch):
    def _fake_known():
        return {
            "PC": ("Paloma Coma", ["PC07"]),
            "MG": ("Mule Fuel x Nana Glue", ["MG07"]),
        }

    def _fake_llm(*args, **kwargs):
        raise AssertionError("LLM must not be called on ambiguous multi-cross input")

    monkeypatch.setattr(plugin_module, "_known_plant_ids", _fake_known)
    monkeypatch.setattr(plugin_module, "_call_default_llm", _fake_llm)

    resolver = plugin_module._make_spoken_id_resolver()
    result = resolver("Paloma Coma number seven and Mule Fuel number seven")

    assert result == []


def test_resolver_still_calls_the_llm_when_exactly_one_cross_is_named(plugin_module, monkeypatch):
    """The gate must not become a second way to silently drop legitimate
    messages -- a single, unambiguous cross mention still reaches the LLM."""
    called = {"n": 0}

    def _fake_known():
        return {"PC": ("Paloma Coma", ["PC07"])}

    def _fake_llm(*args, **kwargs):
        called["n"] += 1
        import json

        return json.dumps({"cross_prefix": "PC", "plant_id": "PC07"})

    monkeypatch.setattr(plugin_module, "_known_plant_ids", _fake_known)
    monkeypatch.setattr(plugin_module, "_call_default_llm", _fake_llm)

    resolver = plugin_module._make_spoken_id_resolver()
    result = resolver("Hello, Paloma Coma. Number seven is fucking good.")

    assert called["n"] == 1
    assert result == ["PC07"]


def test_resolver_rejects_llm_answer_that_disagrees_with_the_deterministic_gate(
    plugin_module, monkeypatch
):
    """Belt-and-suspenders: even if exactly one cross was named, an LLM
    answer for a DIFFERENT cross must still be rejected, not trusted."""

    def _fake_known():
        return {
            "PC": ("Paloma Coma", ["PC07"]),
            "MG": ("Mule Fuel x Nana Glue", ["MG07"]),
        }

    def _fake_llm(*args, **kwargs):
        import json

        return json.dumps({"cross_prefix": "MG", "plant_id": "MG07"})

    monkeypatch.setattr(plugin_module, "_known_plant_ids", _fake_known)
    monkeypatch.setattr(plugin_module, "_call_default_llm", _fake_llm)

    resolver = plugin_module._make_spoken_id_resolver()
    result = resolver("Hello, Paloma Coma. Number seven is fucking good.")

    assert result == []
