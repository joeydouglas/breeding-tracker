"""NICK-1013: datetime-valued YAML scalars must survive JSON serialisation.

WHY THIS EXISTS. NICK-967's rollback rehearsal for ``mule-fuel-x-nana-glue``
crashed in ``reverse_migrate_project.apply()`` with::

    TypeError: Object of type datetime is not JSON serializable
    when serializing dict item 'last_updated'

Root cause: some real plant markdown carries an UNQUOTED timestamp in its YAML
frontmatter, e.g. ``last_updated: 2026-08-22 17:14:06.760534``. PyYAML's
implicit timestamp resolver turns that into a native ``datetime.datetime``, and
``json.dumps`` has no encoder for it. ``verify_reverse_migration()`` is happy --
only the write step blows up.

The fix is deliberately GENERAL rather than scoped to ``last_updated``: any
field, present or future, whose value parses as a date/datetime must serialise
to ISO-8601 instead of crashing. A real value's actual type must never cause an
unhandled crash in a rollback tool.

Everything runs in ``tmp_path``; the live tree is only ever READ.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import plant_markdown  # noqa: E402
import reverse_migration  # noqa: E402
import reverse_migrate_project as rmp  # noqa: E402
import tracker_migration  # noqa: E402

LIVE_ROOT = Path.home() / ".hermes" / "breeding"
REGISTRY = LIVE_ROOT / "_shared" / "breeding-meta" / "registry.json"
PLANT_TEMPLATE = _REPO_ROOT / "templates" / "plant-template.md"
PROJECT_TEMPLATE = _REPO_ROOT / "templates" / "project-template.md"

#: The exact unquoted scalar that crashed the real rehearsal, copied from
#: ``~/.hermes/breeding/mule-fuel-x-nana-glue/plants/MG01.md``.
REAL_TIMESTAMP_TEXT = "2026-08-22 17:14:06.760534"
REAL_TIMESTAMP = dt.datetime(2026, 8, 22, 17, 14, 6, 760534)

SLUG = "mule-fuel-x-nana-glue"


@pytest.fixture
def plant_schema():
    return plant_markdown.load_schema(PLANT_TEMPLATE)


@pytest.fixture
def project_with_unquoted_timestamp(tmp_path):
    """A forward-migrated project whose first plant grew an extra timestamp.

    Reproduces the real shape: an "extra" field outside the canonical plant
    template, written unquoted, therefore parsed as a native ``datetime``.
    """
    out = tmp_path / "cutover" / SLUG
    tracker_migration.migrate_tracker(
        LIVE_ROOT / SLUG / "tracker.json",
        REGISTRY,
        SLUG,
        out,
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
    )
    plant_path = sorted((out / "plants").glob("*.md"))[0]
    text = plant_path.read_text(encoding="utf-8")
    marker = "---\n"
    end = text.index(marker, len(marker))
    patched = (
        text[:end] + f"last_updated: {REAL_TIMESTAMP_TEXT}\n" + text[end:]
    )
    plant_path.write_text(patched, encoding="utf-8")
    return out, plant_path


# ------------------------------------------------------------ unit level ----


def test_yaml_really_parses_the_unquoted_scalar_as_a_datetime(
    project_with_unquoted_timestamp, plant_schema
):
    """Guard the premise: if PyYAML stopped doing this the bug is moot."""
    project_dir, _ = project_with_unquoted_timestamp
    tracker = reverse_migration.reverse_migrate_tracker(
        project_dir, plant_schema
    )
    values = [
        p["last_updated"] for p in tracker["plants"] if "last_updated" in p
    ]
    assert values, "fixture did not land a last_updated on any plant"
    assert isinstance(values[0], dt.datetime)
    assert values[0] == REAL_TIMESTAMP


def test_json_default_renders_datetime_as_iso8601():
    assert (
        reverse_migration.json_default(REAL_TIMESTAMP)
        == REAL_TIMESTAMP.isoformat()
        == "2026-08-22T17:14:06.760534"
    )


def test_json_default_renders_date_as_iso8601():
    assert reverse_migration.json_default(dt.date(2026, 8, 22)) == "2026-08-22"


def test_json_default_still_refuses_genuinely_unserialisable_objects():
    """The fix must widen the encoder, not silence every type error."""
    with pytest.raises(TypeError):
        reverse_migration.json_default(object())


def test_dumps_tracker_round_trips_a_datetime_to_an_exact_iso_string():
    """Not just crash-free -- the value must come back readable and exact."""
    payload = {"plants": [{"id": "MG01", "last_updated": REAL_TIMESTAMP}]}
    loaded = json.loads(reverse_migration.dumps_tracker(payload))
    got = loaded["plants"][0]["last_updated"]
    assert isinstance(got, str)
    assert got == "2026-08-22T17:14:06.760534"
    # Round-trips back to the identical datetime: nothing truncated or
    # reformatted away (str(datetime) would use a space, not "T").
    assert dt.datetime.fromisoformat(got) == REAL_TIMESTAMP


# ---------------------------------------------------------- pipeline end ----


def test_apply_writes_loadable_json_despite_a_datetime_valued_field(
    project_with_unquoted_timestamp, plant_schema, tmp_path
):
    """The exact crash: plan+verify pass, then apply() used to blow up."""
    project_dir, _ = project_with_unquoted_timestamp
    plan = rmp.plan(project_dir, REGISTRY, SLUG, PLANT_TEMPLATE)
    assert plan.verification_ok, plan.report.as_dict()

    target = tmp_path / "out" / "tracker.json"
    written = rmp.apply(plan, target)

    loaded = json.loads(written.read_text(encoding="utf-8"))
    stamped = [p for p in loaded["plants"] if "last_updated" in p]
    assert stamped, "the datetime field vanished from the written tracker"
    assert stamped[0]["last_updated"] == "2026-08-22T17:14:06.760534"


def test_written_tracker_is_reloadable_by_the_forward_migration(
    project_with_unquoted_timestamp, tmp_path
):
    """A rolled-back tracker.json must still be valid input downstream."""
    project_dir, _ = project_with_unquoted_timestamp
    plan = rmp.plan(project_dir, REGISTRY, SLUG, PLANT_TEMPLATE)
    target = tmp_path / "out" / "tracker.json"
    rmp.apply(plan, target)

    tracker_migration.migrate_tracker(
        target,
        REGISTRY,
        SLUG,
        tmp_path / "reforward" / SLUG,
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
    )
    assert (tmp_path / "reforward" / SLUG / "project.md").exists()
