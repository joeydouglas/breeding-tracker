"""Shared fixtures and helpers for the per-project migration test modules.

Not a test module. Holds the pieces `test_project_migration_contract.py` and
each per-project module both need, so the per-project modules stay small
enough to contain only what is genuinely unique to their project's data.
"""

import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest

from tracker_migration import (
    CANONICAL_PLANT_ID_KEY,
    SOURCE_PLANT_ID_KEY,
    migrate_tracker,
)

REPO = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATE = REPO / "templates" / "project-template.md"
PLANT_TEMPLATE = REPO / "templates" / "plant-template.md"


def tracker_json(spec):
    return json.loads(spec.tracker.read_text(encoding="utf-8"))


def expected_plant_record(plant):
    """A source ``tracker.json`` plant as the migration is expected to emit it.

    NICK-966 renamed the markdown corpus's ID field from ``id`` (still the
    tracker's own native spelling, and ``json_backend``'s) to the canonical
    ``plant_id``. Every "does the migrated file still carry every source
    field" assertion therefore has to compare against the RENAMED record, not
    the raw one -- otherwise ``id`` reads as lost on every plant.

    Defined once here, and derived from ``tracker_migration``'s own two
    constants rather than from literals, so a test cannot drift from the
    migration about which spelling lives on which side.
    """
    record = dict(plant)
    if SOURCE_PLANT_ID_KEY in record:
        record[CANONICAL_PLANT_ID_KEY] = record.pop(SOURCE_PLANT_ID_KEY)
    return record


def plant_id_of_source(plant):
    """The ID of a source tracker record, under the tracker's own spelling."""
    return plant[SOURCE_PLANT_ID_KEY]


def registry_entry(spec):
    return next(
        e
        for e in json.loads(spec.registry.read_text(encoding="utf-8"))["projects"]
        if e["slug"] == spec.slug
    )


def sibling_prefixes(spec):
    """Every OTHER registry project's `(slug, plant_id_prefixes)`.

    Production routes one Discord message against the whole registry, so a
    migrated pattern is only safe if it does not collide with any sibling.
    Read from `registry.json` rather than from `PROJECT_SPECS` deliberately:
    `PROJECT_SPECS` covers the whole registry as of Phase 3, but the registry
    is the live routing source of truth and can gain a project before a
    `ProjectSpec` exists for it. Reading the file keeps a collision with such
    a project just as real as one with a spec'd sibling.
    """
    projects = json.loads(spec.registry.read_text(encoding="utf-8"))["projects"]
    return [
        (e["slug"], e["plant_id_prefixes"])
        for e in projects
        if e["slug"] != spec.slug and e.get("plant_id_prefixes")
    ]


@pytest.fixture
def no_side_effects(monkeypatch):
    """Booby-trap every mechanism that could reach Discord, Drive or a git remote.

    `migration_harness` deliberately binds the real `subprocess.Popen` at
    import time so verification scaffolding still works through this trap;
    that costs no coverage because `tracker_migration` is statically proven to
    import no subprocess/socket/urllib/http at all.
    """

    def boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError(
            f"the migration attempted a real side effect: {args!r} {kwargs!r}"
        )

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "call", boom)
    monkeypatch.setattr(subprocess, "check_call", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(os, "system", boom)
    return boom


def migrate_project(spec, tmp_path, name="sandbox"):
    """Run the real migration for `spec` into a throwaway sandbox."""
    out = tmp_path / name / spec.slug
    summary = migrate_tracker(
        spec.tracker,
        spec.registry,
        spec.slug,
        out,
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
    )
    return summary, out
