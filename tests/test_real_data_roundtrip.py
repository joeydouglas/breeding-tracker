"""Round-trip every plant in all 6 real tracker.json files through markdown.

This is the reality check on Task 1.1: synthetic fixtures can agree with a
buggy implementation, real breeding data cannot be argued with. Read-only with
respect to the trackers; all writes go to a temp dir.
"""

import glob
import json
import tempfile
from pathlib import Path

import pytest

from plant_markdown import load_schema, read_plant, write_plant

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "plant-template.md"
TRACKERS = sorted(glob.glob("/home/joey/.hermes/breeding/*/tracker.json"))


def _plants(tracker_path):
    data = json.loads(Path(tracker_path).read_text(encoding="utf-8"))
    plants = data.get("plants", [])
    return plants if isinstance(plants, list) else list(plants.values())


@pytest.mark.skipif(not TRACKERS, reason="no real tracker.json files present")
@pytest.mark.parametrize("tracker", TRACKERS, ids=lambda p: Path(p).parent.name)
def test_every_real_plant_round_trips_with_zero_data_loss(tracker):
    schema = load_schema(TEMPLATE)
    plants = _plants(tracker)
    assert plants, f"{tracker} has no plants"

    with tempfile.TemporaryDirectory() as tmp:
        for plant in plants:
            path = Path(tmp) / f"{plant['id']}.md"
            write_plant(path, plant, schema=schema)
            got = read_plant(path, schema=schema)
            for field, original in plant.items():
                assert got[field] == original, (
                    f"{Path(tracker).parent.name}/{plant['id']} field {field!r} "
                    f"changed: {original!r} -> {got[field]!r}"
                )


@pytest.mark.skipif(not TRACKERS, reason="no real tracker.json files present")
@pytest.mark.parametrize("tracker", TRACKERS, ids=lambda p: Path(p).parent.name)
def test_real_plant_fields_are_all_covered_by_the_template(tracker):
    schema = load_schema(TEMPLATE)
    found = set()
    for plant in _plants(tracker):
        found |= set(plant)
    missing = found - set(schema)
    assert not missing, f"template is missing real fields: {sorted(missing)}"


@pytest.mark.skipif(not TRACKERS, reason="no real tracker.json files present")
@pytest.mark.parametrize("tracker", TRACKERS, ids=lambda p: Path(p).parent.name)
def test_real_plants_are_byte_stable_across_rewrites(tracker):
    """Once a plant is in canonical form (schema defaults materialised),
    further read/write cycles must not churn a single byte - otherwise every
    ingestion run would produce noise commits."""
    schema = load_schema(TEMPLATE)
    with tempfile.TemporaryDirectory() as tmp:
        for plant in _plants(tracker):
            path = Path(tmp) / f"{plant['id']}.md"
            write_plant(path, plant, schema=schema)
            write_plant(path, read_plant(path, schema=schema), schema=schema)
            canonical = path.read_bytes()
            write_plant(path, read_plant(path, schema=schema), schema=schema)
            assert path.read_bytes() == canonical, plant["id"]
