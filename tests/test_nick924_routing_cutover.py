"""NICK-924 (Task 7.2b) -- TDD: per-project routing-mechanism cutover.

WHY THIS EXISTS. NICK-924's acceptance criteria (see the plan doc, Phase 7
Task 7.2b, and the Multica issue) require, before any project is cut over
from the hardcoded ``_CROSS_DIRS`` dict to ``registry.json``-driven routing:

    (a) old vs registry-derived routing compared and confirmed identical
        for that project's prefix(es) before switching -- DONE separately
        (NICK-924 prerequisite fix: monitor-core's
        test_nick924_pattern_unification.py + this same commit's
        registry.json pattern sync).
    (b) the routing switch is independently rollbackable from the Task 7.2
        BACKEND flip -- a routing-only rollback must restore the hardcoded
        dict without touching the already-migrated markdown backend.
    (c) an explicit check + recovery procedure for observations misrouted
        to the wrong project during the cutover window.
    (d) Phase 7 is not complete until all 6 projects are confirmed on
        registry.json-driven routing.

THE MECHANISM this file tests (``_resolve_breeding_dir`` in the plugin
module): registry.json gains a per-project boolean, ``routing_active``.
``_resolve_breeding_dir(prefix)`` checks the registry FIRST -- if that
project's entry has ``routing_active: true``, its ``breeding_dir`` (read
fresh from registry.json, not a code constant) wins. Every other prefix
falls back to the existing hardcoded ``_CROSS_DIRS`` dict, UNCHANGED. This
directly satisfies (b): flipping one project's ``routing_active`` to
``false`` (or deleting the field) instantly and completely reverts that
project's routing to the hardcoded path with a ONE-LINE registry.json edit
-- no code change, no redeploy, and the other 5 projects' routing is
untouched by construction (the fallback path is the literal, unedited
original dict).

DEFAULT STATE, THIS COMMIT: every real project's ``routing_active`` was
absent (falsy) when this mechanism first landed, so live routing behavior
for all 6 projects was unchanged by that commit --
``test_real_registry_all_six_projects_now_migrated`` below records the
CURRENT state after the subsequent, deliberate per-project cutover
(2026-09-07): all 6 projects were flipped one at a time, each verified with
a real canary observation through the live gateway processor before moving
to the next, per ``routing_cutover_runbook.md``'s procedure. See NICK-924's
Multica comments and breeding-meta's git log for the full per-project
verification record.

Misroute detection/recovery (c) is documented in
``routing_cutover_runbook.md`` alongside this test file, not code -- a
misroute is a data-repair procedure (diff the wrongly-written project's
markdown against what should be there, per NICK-967's reverse-migration
tool), not something a unit test can exercise without real Discord traffic.

SANDBOX-ONLY: every test builds its own throwaway registry dict / _CROSS_DIRS
monkeypatch. No real breeding_dir, tracker.json, or registry.json write.
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
def plugin_module():
    import importlib

    import __init__ as module

    importlib.reload(module)
    return module


def test_real_registry_all_six_projects_now_migrated(plugin_module):
    """Phase 7 Task 7.2b acceptance criterion (d): all original 6 projects
    confirmed on registry.json-driven routing (cutover completed 2026-09-07,
    each verified individually via a real canary observation through the live
    gateway processor -- see NICK-924's Multica comments and
    breeding-meta's git log for the full per-project verification record).

    NICK-1056 (2026-09-08) onboarded three more projects -- Marshmallow OG,
    Pink Perfume, Ms Universe -- directly with routing_active: true (no
    phased cutover needed since they have no legacy hardcoded routing to
    migrate away from). They are included in the expected set below.

    If this test starts failing because a slug DROPPED OUT of the active
    set, that is a rollback (deliberate or accidental) and needs review --
    see routing_cutover_runbook.md's recovery procedure before re-enabling.
    """
    registry = plugin_module._load_registry_for_routing()
    active = {
        p["slug"] for p in registry.get("projects", []) if p.get("routing_active")
    }
    expected = {
        "mule-fuel-x-nana-glue",
        "honey-badger-haze-pheno-hunt",
        "kibungan-pheno-hunt",
        "spaced-paste",
        "paloma-coma",
        "lantz",
        "marshmallow-og-pheno-hunt",
        "pink-perfume-pheno-hunt",
        "ms-universe-pheno-hunt",
    }
    assert active == expected, (
        f"expected all 9 projects migrated, got {sorted(active)!r} -- "
        f"missing {sorted(expected - active)!r}, unexpected {sorted(active - expected)!r}"
    )


def test_prefix_falls_back_to_hardcoded_dict_when_not_migrated(plugin_module, tmp_path, monkeypatch):
    """The default, unmigrated case: registry.json exists but says nothing
    about this prefix (or says routing_active: false) -- old behavior,
    byte-identical."""
    fake_dir = tmp_path / "mule-fuel-x-nana-glue"
    fake_dir.mkdir()
    monkeypatch.setitem(plugin_module._CROSS_DIRS, "MG", fake_dir)
    monkeypatch.setattr(
        plugin_module,
        "_load_registry_for_routing",
        lambda: {"projects": [{"slug": "mule-fuel-x-nana-glue", "prefix_routing_active": {}}]},
    )
    resolved = plugin_module._resolve_breeding_dir("MG")
    assert resolved == fake_dir


def test_prefix_uses_registry_dir_when_routing_active_true(plugin_module, tmp_path, monkeypatch):
    """The migrated case: registry.json's breeding_dir wins, NOT the
    hardcoded dict -- proves the registry path is actually load-bearing,
    not just present-but-ignored."""
    old_dir = tmp_path / "old-hardcoded-path"
    old_dir.mkdir()
    new_dir = tmp_path / "registry-driven-path"
    new_dir.mkdir()
    monkeypatch.setitem(plugin_module._CROSS_DIRS, "MG", old_dir)
    monkeypatch.setattr(
        plugin_module,
        "_load_registry_for_routing",
        lambda: {
            "projects": [
                {
                    "slug": "mule-fuel-x-nana-glue",
                    "breeding_dir": str(new_dir),
                    "routing_active": True,
                    "plant_id_prefixes": [{"prefix": "MG", "pattern": r"\bMG(\d+)\b"}],
                }
            ]
        },
    )
    resolved = plugin_module._resolve_breeding_dir("MG")
    assert resolved == new_dir
    assert resolved != old_dir


def test_reverting_routing_active_instantly_restores_hardcoded_path(plugin_module, tmp_path, monkeypatch):
    """NICK-924 acceptance criterion (b): a routing-only rollback (flip
    routing_active back to false) must restore the hardcoded path with NO
    other change -- proven here by re-resolving after the flag flips."""
    old_dir = tmp_path / "old-hardcoded-path"
    old_dir.mkdir()
    new_dir = tmp_path / "registry-driven-path"
    new_dir.mkdir()
    monkeypatch.setitem(plugin_module._CROSS_DIRS, "MG", old_dir)

    registry_state = {
        "projects": [
            {
                "slug": "mule-fuel-x-nana-glue",
                "breeding_dir": str(new_dir),
                "routing_active": True,
                "plant_id_prefixes": [{"prefix": "MG", "pattern": r"\bMG(\d+)\b"}],
            }
        ]
    }
    monkeypatch.setattr(
        plugin_module, "_load_registry_for_routing", lambda: registry_state
    )
    assert plugin_module._resolve_breeding_dir("MG") == new_dir

    # The rollback: a ONE-FIELD registry.json edit, nothing else.
    registry_state["projects"][0]["routing_active"] = False
    assert plugin_module._resolve_breeding_dir("MG") == old_dir


def test_a_registry_read_failure_falls_back_safely_rather_than_crashing(
    plugin_module, tmp_path, monkeypatch
):
    """registry.json is `git pull`-refreshed data from a separate repo --
    it can be transiently missing/corrupt. A read failure here must fall
    back to the hardcoded dict (the always-safe path), never crash
    ingestion or silently drop the message."""
    fake_dir = tmp_path / "mule-fuel-x-nana-glue"
    fake_dir.mkdir()
    monkeypatch.setitem(plugin_module._CROSS_DIRS, "MG", fake_dir)

    def _raise():
        raise FileNotFoundError("registry.json missing")

    monkeypatch.setattr(plugin_module, "_load_registry_for_routing", _raise)
    resolved = plugin_module._resolve_breeding_dir("MG")
    assert resolved == fake_dir


def test_prefix_not_in_registry_at_all_falls_back_to_hardcoded(plugin_module, tmp_path, monkeypatch):
    """A prefix the registry doesn't mention (e.g. registry.json only lists
    a subset during a rolling per-project cutover) must still fall back
    cleanly, not raise."""
    fake_dir = tmp_path / "lantz"
    fake_dir.mkdir()
    monkeypatch.setitem(plugin_module._CROSS_DIRS, "LTZ", fake_dir)
    monkeypatch.setattr(
        plugin_module,
        "_load_registry_for_routing",
        lambda: {"projects": [{"slug": "mule-fuel-x-nana-glue", "routing_active": True}]},
    )
    resolved = plugin_module._resolve_breeding_dir("LTZ")
    assert resolved == fake_dir


def test_unknown_prefix_still_returns_none(plugin_module, monkeypatch):
    """A totally unknown prefix (not in _CROSS_DIRS OR registry.json) must
    still return None -- the existing 'no known cross prefix' warning path
    in _processor() depends on this."""
    monkeypatch.setattr(
        plugin_module, "_load_registry_for_routing", lambda: {"projects": []}
    )
    assert plugin_module._resolve_breeding_dir("ZZ") is None
