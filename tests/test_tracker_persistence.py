"""Task 2.1 — TDD: ``load_tracker``/``save_tracker`` on the markdown backend.

These tests are written BEFORE the implementation and must be watched
failing. They pin three things:

1. The **external signatures are unchanged** -- ``load_tracker(tracker_file)``
   and ``save_tracker(tracker, tracker_file)``, called exactly the way the six
   existing per-project ``monitor_breeding_notes.py`` wrappers already call
   them (with ``BREEDING_DIR / 'tracker.json'``).
2. The **persistence backend is markdown**, not ``tracker.json``: reads come
   from ``project.md`` + ``plants/<ID>.md`` and writes go to those same files,
   never to ``tracker.json``.
3. The **caller-visible data shape/semantics are identical** to the JSON era:
   same top-level keys, same ``plants`` list (same order, same per-plant keys,
   same values), free-text ``observation_log`` bodies preserved verbatim.

Everything here is sandbox-only: real project dirs are read as immutable
input, all writes land in pytest ``tmp_path``.
"""

import json
from pathlib import Path

import pytest

from breeding_tracker import breeding_core as core


# ------------------------------------------------------------- helpers ----


def _seed_markdown_project(project_dir, tracker):
    """Materialise a tracker dict into a markdown project dir.

    Deliberately uses the PRODUCTION ``save_tracker`` -- the point of these
    tests is that save/load are inverses over the markdown backend, so
    seeding through a hand-rolled writer would test the wrong thing.
    """
    core.save_tracker(tracker, project_dir / "tracker.json")
    return project_dir


def _strip_plants(tracker):
    return {k: v for k, v in tracker.items() if k != "plants"}


# ------------------------------------------------------- signature pins ----


def test_load_tracker_signature_is_unchanged():
    import inspect

    params = list(inspect.signature(core.load_tracker).parameters)
    assert params == ["tracker_file"]


def test_save_tracker_signature_is_unchanged():
    import inspect

    params = list(inspect.signature(core.save_tracker).parameters)
    assert params == ["tracker", "tracker_file"]


# ------------------------------------------------------- backend is .md ----


def test_save_tracker_writes_markdown_files_not_tracker_json(
    sandbox_project, lantz_tracker
):
    tracker_file = sandbox_project / "tracker.json"
    core.save_tracker(lantz_tracker, tracker_file)

    assert not tracker_file.exists(), "save_tracker must no longer write tracker.json"
    assert (sandbox_project / "project.md").is_file()
    plants_dir = sandbox_project / "plants"
    assert plants_dir.is_dir()
    written = sorted(p.name for p in plants_dir.glob("*.md"))
    assert written == sorted(f"{p['id']}.md" for p in lantz_tracker["plants"])


def test_load_tracker_reads_markdown_with_no_tracker_json_present(
    sandbox_project, lantz_tracker
):
    """The core RED assertion: with markdown present and tracker.json absent,
    load_tracker must still return the tracker. The JSON-era implementation
    raises FileNotFoundError here."""
    tracker_file = _seed_markdown_project(sandbox_project, lantz_tracker) / "tracker.json"
    assert not tracker_file.exists()

    loaded = core.load_tracker(tracker_file)

    assert isinstance(loaded, dict)
    assert [p["id"] for p in loaded["plants"]] == [
        p["id"] for p in lantz_tracker["plants"]
    ]


def test_load_tracker_ignores_a_stale_tracker_json_sitting_next_to_markdown(
    sandbox_project, lantz_tracker
):
    """Migration safety: a leftover tracker.json must never win over the
    markdown store, or a half-migrated project would silently keep serving
    stale JSON data."""
    _seed_markdown_project(sandbox_project, lantz_tracker)
    stale = dict(lantz_tracker)
    stale["cross_name"] = "STALE-JSON-SHOULD-NOT-WIN"
    (sandbox_project / "tracker.json").write_text(
        json.dumps(stale), encoding="utf-8"
    )

    loaded = core.load_tracker(sandbox_project / "tracker.json")

    assert loaded["cross_name"] == lantz_tracker["cross_name"]


# ------------------------------------------------- shape/value fidelity ----


def test_round_trip_preserves_every_top_level_project_field(
    sandbox_project, lantz_tracker
):
    _seed_markdown_project(sandbox_project, lantz_tracker)
    loaded = core.load_tracker(sandbox_project / "tracker.json")

    original = _strip_plants(lantz_tracker)
    got = _strip_plants(loaded)
    assert got == original


def test_round_trip_preserves_every_plant_field_exactly(
    sandbox_project, lantz_tracker
):
    _seed_markdown_project(sandbox_project, lantz_tracker)
    loaded = core.load_tracker(sandbox_project / "tracker.json")

    assert loaded["plants"] == lantz_tracker["plants"]


def test_round_trip_adds_no_keys_and_drops_no_keys(sandbox_project, lantz_tracker):
    """Exact SHAPE preservation, not merely value preservation: a plant that
    never had ``corrected_reading`` must not acquire a defaulted one, because
    callers (and the dashboard generators) see this dict verbatim."""
    _seed_markdown_project(sandbox_project, lantz_tracker)
    loaded = core.load_tracker(sandbox_project / "tracker.json")

    assert set(loaded) == set(lantz_tracker)
    for before, after in zip(lantz_tracker["plants"], loaded["plants"]):
        assert set(after) == set(before), before["id"]


def test_observation_log_is_schema_guaranteed_on_every_plant_read(
    sandbox_project, lantz_tracker
):
    """Documented exception to exact key-set preservation.

    Phase 1's ``plant_markdown`` stores ``observation_log`` as the markdown
    BODY and guarantees it on both sides: ``write_plant`` always emits a body
    and ``read_plant`` always returns the field, precisely so that
    ``read_plant(write_plant(x))`` stays symmetric. It is therefore a
    schema-guaranteed field, and a plant saved WITHOUT it loads back WITH it
    as ``''``. This test pins that contract so it can never regress silently
    into either behaviour by accident.
    """
    tracker = dict(lantz_tracker)
    tracker["plants"] = [{"id": "SYN01", "status": "active", "vigor": "9"}]
    core.save_tracker(tracker, sandbox_project / "tracker.json")

    loaded = core.load_tracker(sandbox_project / "tracker.json")
    plant = loaded["plants"][0]

    assert set(plant) == {"id", "status", "vigor", "observation_log"}
    assert plant["observation_log"] == ""
    # ...and it is stable: a second round trip adds nothing further.
    core.save_tracker(loaded, sandbox_project / "tracker.json")
    assert core.load_tracker(sandbox_project / "tracker.json") == loaded


def test_every_real_plant_already_carries_observation_log(tmp_path):
    """Why the exception above is harmless in production: no real plant in
    any of the six projects is missing ``observation_log``, so the
    schema-guaranteed field never adds a key to a real record."""
    trackers = sorted((Path.home() / ".hermes" / "breeding").glob("*/tracker.json"))
    if not trackers:
        pytest.skip("no real trackers present")
    for source in trackers:
        tracker = json.loads(source.read_text(encoding="utf-8"))
        for plant in tracker["plants"]:
            assert "observation_log" in plant, f"{source.parent.name}/{plant['id']}"


@pytest.mark.parametrize(
    "tracker_name",
    ["mule-fuel-x-nana-glue", "spaced-paste", "kibungan-pheno-hunt",
     "honey-badger-haze-pheno-hunt", "paloma-coma", "lantz"],
)
def test_every_real_project_round_trips_with_zero_data_loss(
    tmp_path, tracker_name
):
    """Real breeding data across all six projects -- synthetic fixtures can
    agree with a buggy implementation, real data cannot be argued with.
    ``spaced-paste`` in particular has an UNSORTED plant list (sp06 first),
    which pins plant-order preservation."""
    source = Path.home() / ".hermes" / "breeding" / tracker_name / "tracker.json"
    if not source.exists():
        pytest.skip(f"real tracker for {tracker_name} not present")
    tracker = json.loads(source.read_text(encoding="utf-8"))

    project = tmp_path / tracker_name
    project.mkdir()
    core.save_tracker(tracker, project / "tracker.json")
    loaded = core.load_tracker(project / "tracker.json")

    assert loaded == tracker, f"{tracker_name} did not round-trip"


def test_plant_order_is_preserved_even_when_not_alphabetical(
    sandbox_project, lantz_tracker
):
    tracker = dict(lantz_tracker)
    tracker["plants"] = list(reversed(lantz_tracker["plants"]))
    _seed_markdown_project(sandbox_project, tracker)

    loaded = core.load_tracker(sandbox_project / "tracker.json")
    assert [p["id"] for p in loaded["plants"]] == [
        p["id"] for p in tracker["plants"]
    ]


def test_free_text_observation_log_survives_verbatim(sandbox_project, lantz_tracker):
    """The body is the highest-risk field: hand-written markdown structure,
    unicode, smart quotes, code fences, trailing whitespace and CRLF must all
    come back byte-identical."""
    tricky = (
        "\n### 2026-09-05T10:00:00\n"
        "Smells like \u201cripe fruit\u201d \u2014 caf\u00e9 note, 8/10.\n\n"
        "```\nnot: yaml\n---\nstill not yaml\n```\n\n"
        "| Date | Event |\n|------|-------|\n| TBD  | x |\n"
        "trailing spaces here:   \n\ttab-indented line\n"
    )
    tracker = dict(lantz_tracker)
    plants = [dict(p) for p in lantz_tracker["plants"]]
    plants[0]["observation_log"] = tricky
    tracker["plants"] = plants

    _seed_markdown_project(sandbox_project, tracker)
    loaded = core.load_tracker(sandbox_project / "tracker.json")

    assert loaded["plants"][0]["observation_log"] == tricky


def test_string_fields_are_not_retyped_by_yaml_guessing(sandbox_project, lantz_tracker):
    """A plant id like ``07`` or a status like ``true`` must stay a string --
    the JSON era guaranteed this for free and the markdown era must not
    regress it into an int/bool."""
    tracker = dict(lantz_tracker)
    plant = dict(lantz_tracker["plants"][0])
    plant["id"] = "07"
    plant["germ_date"] = "2026-08-25"
    plant["structure"] = "true"
    tracker["plants"] = [plant]

    _seed_markdown_project(sandbox_project, tracker)
    got = core.load_tracker(sandbox_project / "tracker.json")["plants"][0]

    assert got["id"] == "07"
    assert got["structure"] == "true"
    assert got["germ_date"] == "2026-08-25"


def test_photos_list_of_dicts_round_trips(sandbox_project, lantz_tracker):
    photos = [
        {
            "drive_id": "1abcDEF",
            "drive_url": "https://drive.google.com/file/d/1abcDEF/view",
            "filename": "Ltz01_2026-09-05_bud.jpg",
            "embed_url": "https://drive.google.com/uc?id=1abcDEF",
        }
    ]
    tracker = dict(lantz_tracker)
    plant = dict(lantz_tracker["plants"][0])
    plant["photos"] = photos
    plant["photo_count"] = 1
    tracker["plants"] = [plant]

    _seed_markdown_project(sandbox_project, tracker)
    got = core.load_tracker(sandbox_project / "tracker.json")["plants"][0]

    assert got["photos"] == photos
    assert got["photo_count"] == 1


def test_empty_plant_roster_round_trips(sandbox_project, lantz_tracker):
    """Auto-create pheno hunts start from an empty roster."""
    tracker = dict(lantz_tracker)
    tracker["plants"] = []
    _seed_markdown_project(sandbox_project, tracker)

    assert core.load_tracker(sandbox_project / "tracker.json")["plants"] == []


def test_saving_a_shrunk_roster_removes_the_dropped_plant_file(
    sandbox_project, lantz_tracker
):
    """tracker.json rewrote the whole roster, so a removed plant vanished.
    The markdown store must match that, or load(save(x)) != x."""
    _seed_markdown_project(sandbox_project, lantz_tracker)
    dropped = lantz_tracker["plants"][0]["id"]

    shrunk = dict(lantz_tracker)
    shrunk["plants"] = lantz_tracker["plants"][1:]
    core.save_tracker(shrunk, sandbox_project / "tracker.json")

    assert not (sandbox_project / "plants" / f"{dropped}.md").exists()
    loaded = core.load_tracker(sandbox_project / "tracker.json")
    assert [p["id"] for p in loaded["plants"]] == [
        p["id"] for p in shrunk["plants"]
    ]


def test_repeated_saves_are_byte_stable(sandbox_project, lantz_tracker):
    """Every ingestion run saves the tracker; a non-stable writer would emit
    a noise git diff on every single Discord message."""
    _seed_markdown_project(sandbox_project, lantz_tracker)
    core.save_tracker(
        core.load_tracker(sandbox_project / "tracker.json"),
        sandbox_project / "tracker.json",
    )
    snapshot = {
        p.relative_to(sandbox_project): p.read_bytes()
        for p in sorted(sandbox_project.rglob("*.md"))
    }
    core.save_tracker(
        core.load_tracker(sandbox_project / "tracker.json"),
        sandbox_project / "tracker.json",
    )
    again = {
        p.relative_to(sandbox_project): p.read_bytes()
        for p in sorted(sandbox_project.rglob("*.md"))
    }
    assert again == snapshot


def test_save_tracker_does_not_mutate_the_callers_dict(sandbox_project, lantz_tracker):
    before = json.dumps(lantz_tracker, sort_keys=True)
    core.save_tracker(lantz_tracker, sandbox_project / "tracker.json")
    assert json.dumps(lantz_tracker, sort_keys=True) == before


# --------------------------------------------------------- error paths ----


def test_load_tracker_raises_file_not_found_for_an_unmigrated_project(tmp_path):
    """JSON-era ``open()`` raised FileNotFoundError for a missing tracker;
    callers may rely on that, so a project dir with no project.md must raise
    the same type, not return an empty tracker."""
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        core.load_tracker(empty / "tracker.json")


def test_save_tracker_rejects_a_plant_id_that_escapes_the_plants_dir(
    sandbox_project, lantz_tracker
):
    """Plant IDs come from Discord message text via a regex; a traversal-ish
    id must never write outside plants/."""
    tracker = dict(lantz_tracker)
    plant = dict(lantz_tracker["plants"][0])
    plant["id"] = "../../escaped"
    tracker["plants"] = [plant]

    with pytest.raises(ValueError):
        core.save_tracker(tracker, sandbox_project / "tracker.json")


def test_save_tracker_rejects_a_plant_without_an_id(sandbox_project, lantz_tracker):
    tracker = dict(lantz_tracker)
    tracker["plants"] = [{"cross": "Lantz"}]
    with pytest.raises(ValueError):
        core.save_tracker(tracker, sandbox_project / "tracker.json")


def test_save_tracker_rejects_duplicate_plant_ids(sandbox_project, lantz_tracker):
    """Two plants sharing an id would silently collapse into one file, losing
    one plant's data -- the JSON list could hold both, so this must be loud."""
    tracker = dict(lantz_tracker)
    plant = dict(lantz_tracker["plants"][0])
    tracker["plants"] = [plant, dict(plant)]
    with pytest.raises(ValueError):
        core.save_tracker(tracker, sandbox_project / "tracker.json")


def test_save_tracker_accepts_a_string_path(sandbox_project, lantz_tracker):
    """Wrappers pass a Path, but nothing in the signature forbids a str and
    the JSON-era ``open()`` accepted both."""
    core.save_tracker(lantz_tracker, str(sandbox_project / "tracker.json"))
    loaded = core.load_tracker(str(sandbox_project / "tracker.json"))
    assert loaded == lantz_tracker
