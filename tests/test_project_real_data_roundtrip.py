"""Round-trip every real project's top-level fields through project markdown.

This is the reality check on Task 1.2, mirroring
``test_real_data_roundtrip.py`` for plants: synthetic fixtures can agree with
a buggy implementation, real breeding data cannot be argued with. Read-only
with respect to the trackers; all writes go to a temp dir.
"""

import glob
import json
import tempfile
from pathlib import Path

import pytest

from breeding_tracker.project_markdown import load_schema, read_project, write_project

TEMPLATE = Path(__file__).resolve().parents[1] / "breeding_tracker" / "templates" / "project-template.md"
TRACKERS = sorted(glob.glob("/home/joey/.hermes/breeding/*/tracker.json"))


def _project_fields(tracker_path):
    data = json.loads(Path(tracker_path).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k != "plants"}


@pytest.mark.skipif(not TRACKERS, reason="no real tracker.json files present")
@pytest.mark.parametrize("tracker", TRACKERS, ids=lambda p: Path(p).parent.name)
def test_every_real_project_round_trips_with_zero_data_loss(tracker):
    schema = load_schema(TEMPLATE)
    fields = _project_fields(tracker)
    assert fields, f"{tracker} has no top-level project fields"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "project.md"
        write_project(path, fields, schema=schema)
        got = read_project(path, schema=schema)
        for field, original in fields.items():
            assert got[field] == original, (
                f"{Path(tracker).parent.name} field {field!r} changed: "
                f"{original!r} -> {got[field]!r}"
            )


@pytest.mark.skipif(not TRACKERS, reason="no real tracker.json files present")
@pytest.mark.parametrize("tracker", TRACKERS, ids=lambda p: Path(p).parent.name)
def test_real_project_fields_are_all_covered_by_the_template(tracker):
    schema = load_schema(TEMPLATE)
    found = set(_project_fields(tracker))
    missing = found - set(schema)
    assert not missing, f"template is missing real fields: {sorted(missing)}"


@pytest.mark.skipif(not TRACKERS, reason="no real tracker.json files present")
@pytest.mark.parametrize("tracker", TRACKERS, ids=lambda p: Path(p).parent.name)
def test_real_projects_are_byte_stable_across_rewrites(tracker):
    """Once a project is in canonical form (schema defaults materialised),
    further read/write cycles must not churn a single byte - otherwise every
    ingestion run would produce noise commits."""
    schema = load_schema(TEMPLATE)
    fields = _project_fields(tracker)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "project.md"
        write_project(path, fields, schema=schema)
        write_project(path, read_project(path, schema=schema), schema=schema)
        canonical = path.read_bytes()
        write_project(path, read_project(path, schema=schema), schema=schema)
        assert path.read_bytes() == canonical
