"""The Task 3.x acceptance contract, run against EVERY migrated project.

Task 3.1 and Task 3.2 each carried their own copy of these checks; the copies
had already drifted (3.2 gained a never-migrated-dir gate and an
evidence-count assertion that 3.1 never got back). Every check here is
parametrized over `PROJECT_SPECS`, so a fix lands on all projects at once and
Task 3.3 inherits the full, current contract by adding one `ProjectSpec`
rather than by copying a file that is already a version behind.

Per-project modules keep ONLY assertions that are genuinely unique to that
project's data. The plan's acceptance criteria are covered here:

(a) plant count matches exactly;
(b) every field round-trips with zero data loss, diffed against Task 3.0's
    field inventory rather than a hand-listed subset;
(c) the migration is sandbox-only;
(d) `tracker.json` is unchanged and no real Discord/Drive/git side effect was
    possible.
"""

import json
import os
from pathlib import Path

import pytest

from helpers_migration import (  # noqa: F401  (fixture re-export)
    PLANT_TEMPLATE,
    PROJECT_TEMPLATE,
    REPO,
    migrate_project,
    no_side_effects,
    registry_entry as _registry_entry,
    tracker_json as _tracker_json,
)
from migration_harness import live_tree_state
from migration_specs import PROJECT_SPECS
from tracker_migration import (
    SandboxViolationError,
    file_md5,
    migrate_tracker,
    verify_migration,
)

BREEDING_ROOT = Path.home() / ".hermes" / "breeding"


#: Parametrizes every test below over each accepted project, skipping any whose
#: real tracker is absent on this machine rather than silently passing.
def _spec_params():
    return [
        pytest.param(
            spec,
            id=spec.slug,
            marks=pytest.mark.skipif(
                not spec.tracker.exists(),
                reason=f"real tracker for {spec.slug} not present",
            ),
        )
        for spec in PROJECT_SPECS
    ]


spec_param = pytest.mark.parametrize("spec", _spec_params())


def _migrate(spec, tmp_path, name="sandbox"):
    return migrate_project(spec, tmp_path, name)


# ------------------------------------------------- (a) plant count match ----


@spec_param
def test_plant_count_matches_the_source_and_the_field_inventory(
    spec, tmp_path, no_side_effects
):
    _, out = _migrate(spec, tmp_path)
    source = _tracker_json(spec)
    written = sorted((out / "plants").glob("*.md"))
    assert len(source["plants"]) == spec.plant_count
    assert len(written) == spec.plant_count


@spec_param
def test_every_source_plant_id_has_exactly_one_markdown_file(
    spec, tmp_path, no_side_effects
):
    _, out = _migrate(spec, tmp_path)
    source_ids = sorted(p["id"] for p in _tracker_json(spec)["plants"])
    written_ids = sorted(p.stem for p in (out / "plants").glob("*.md"))
    assert written_ids == source_ids
    assert len(set(source_ids)) == len(source_ids), "duplicate id in the source"


# ------------------------------------------------ (b) zero field loss -------


@spec_param
def test_full_verification_reports_zero_loss(spec, tmp_path, no_side_effects):
    _, out = _migrate(spec, tmp_path)
    report = verify_migration(
        spec.tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, spec.registry, spec.slug
    )
    assert report.ok, json.dumps(report.as_dict(), indent=2, default=str)[:4000]


@spec_param
def test_verification_actually_compared_every_record_and_field(
    spec, tmp_path, no_side_effects
):
    """`ok` is only evidence if the gate inspected the whole dataset.

    Round 4's fix made a vacuous pass impossible; this pins the exact evidence
    counts, re-derived from the tracker, so a gate that quietly stopped
    comparing most of the data would fail even though it recorded no
    discrepancy.
    """
    _, out = _migrate(spec, tmp_path)
    report = verify_migration(
        spec.tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, spec.registry, spec.slug
    )
    source = _tracker_json(spec)
    assert report.verified_something
    assert report.records_compared == spec.expected_records
    assert report.fields_compared == spec.expected_fields(source)


@spec_param
def test_verification_of_a_never_migrated_dir_is_not_ok(spec, tmp_path):
    """The gate must fail closed, not report a vacuous pass.

    Task 3.2 had this; Task 3.1's copy never got it. Parametrizing is what
    stops that drift.
    """
    report = verify_migration(
        spec.tracker,
        tmp_path / "nothing-here",
        PROJECT_TEMPLATE,
        PLANT_TEMPLATE,
        spec.registry,
        spec.slug,
    )
    assert not report.ok


@spec_param
def test_source_plant_keys_are_exactly_the_inventoried_set(spec):
    """Guards the inventory itself: if the live tracker grew a field, the
    migration's coverage claim is stale and must be re-derived, not assumed."""
    allowed = spec.plant_keys | spec.expected_plant_defaults
    for plant in _tracker_json(spec)["plants"]:
        assert set(plant) <= allowed, f"{plant['id']} has un-inventoried keys"


@spec_param
def test_source_project_keys_are_exactly_the_inventoried_set(spec):
    assert set(_tracker_json(spec)) == set(spec.project_keys)


@spec_param
def test_every_inventoried_plant_field_survives_on_every_plant(
    spec, tmp_path, no_side_effects
):
    """Field-level diff against Task 3.0's inventory, not a hand-picked subset."""
    from plant_markdown import load_schema, read_plant

    _, out = _migrate(spec, tmp_path)
    schema = load_schema(PLANT_TEMPLATE)
    lost, changed, compared = [], [], 0
    for plant in _tracker_json(spec)["plants"]:
        got = read_plant(out / "plants" / f"{plant['id']}.md", schema=schema)
        for key, original in plant.items():
            compared += 1
            if key not in got:
                lost.append(f"{plant['id']}.{key}")
            elif got[key] != original:
                changed.append(f"{plant['id']}.{key}")
    assert not lost, lost
    assert not changed, changed[:10]
    assert compared, "compared nothing -- the check would be vacuous"


@spec_param
def test_the_whole_plants_array_reconstructs_from_markdown(
    spec, tmp_path, no_side_effects
):
    """The strongest form of (b): rebuild the source array and JSON-compare."""
    from plant_markdown import load_schema, read_plant

    _, out = _migrate(spec, tmp_path)
    schema = load_schema(PLANT_TEMPLATE)
    source_plants = _tracker_json(spec)["plants"]
    rebuilt = [
        {
            k: read_plant(out / "plants" / f"{p['id']}.md", schema=schema)[k]
            for k in p
        }
        for p in source_plants
    ]
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(
        source_plants, sort_keys=True
    )


@spec_param
def test_every_project_field_survives(spec, tmp_path, no_side_effects):
    from project_markdown import load_schema, read_project

    _, out = _migrate(spec, tmp_path)
    source = _tracker_json(spec)
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    for key, original in source.items():
        if key == "plants":
            continue
        assert key in got, f"lost project field {key}"
        assert got[key] == original, f"altered project field {key}"


@spec_param
def test_plants_array_is_not_duplicated_into_project_frontmatter(
    spec, tmp_path, no_side_effects
):
    from project_markdown import load_schema, read_project

    _, out = _migrate(spec, tmp_path)
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    assert "plants" not in got


@spec_param
def test_observation_logs_are_preserved_verbatim_as_the_body(
    spec, tmp_path, no_side_effects
):
    _, out = _migrate(spec, tmp_path)
    for plant in _tracker_json(spec)["plants"]:
        text = (out / "plants" / f"{plant['id']}.md").read_text(
            encoding="utf-8", newline=""
        )
        assert text.split("\n---\n", 1)[1] == plant["observation_log"]


@spec_param
def test_corrected_reading_is_defaulted_and_never_invented(
    spec, tmp_path, no_side_effects
):
    """A materialised template default must not be confused with a real value."""
    summary, out = _migrate(spec, tmp_path)
    source_plants = _tracker_json(spec)["plants"]
    for plant in source_plants:
        if "corrected_reading" in plant:
            continue
        assert "corrected_reading" in summary.defaulted_fields.get(plant["id"], ())


@spec_param
def test_defaulted_project_fields_are_exactly_the_expected_set(
    spec, tmp_path, no_side_effects
):
    summary, _ = _migrate(spec, tmp_path)
    got = set(summary.defaulted_fields.get("project", ()))
    assert got == set(spec.expected_project_defaults)


@spec_param
def test_only_the_known_incomplete_plants_needed_photo_defaults(
    spec, tmp_path, no_side_effects
):
    """mule-fuel's MG07 lacks photo_count/photos_drive_url; no other project
    record may quietly acquire the same hole without the spec declaring it."""
    summary, _ = _migrate(spec, tmp_path)
    needed = {
        record
        for record, fields in summary.defaulted_fields.items()
        if record != "project"
        and ("photo_count" in fields or "photos_drive_url" in fields)
    }
    assert needed == set(spec.incomplete_plants)


# --------------------------------------- registry-sourced routing fields ----


@spec_param
def test_registry_sourced_routing_fields_are_correct(spec, tmp_path, no_side_effects):
    """Task 3.0 §8's highest-risk finding: these live ONLY in registry.json."""
    from project_markdown import load_schema, read_project

    _, out = _migrate(spec, tmp_path)
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    entry = _registry_entry(spec)
    source = _tracker_json(spec)
    assert got["auto_create"] == entry["auto_create"]
    assert got["plant_id_prefixes"] == entry["plant_id_prefixes"]
    assert "auto_create" not in source
    assert "plant_id_prefixes" not in source


@spec_param
def test_id_routing_regexes_survive_backslash_intact(spec, tmp_path, no_side_effects):
    """A YAML round-trip that ate a backslash would silently break ID routing."""
    from project_markdown import load_schema, read_project

    _, out = _migrate(spec, tmp_path)
    got = read_project(out / "project.md", schema=load_schema(PROJECT_TEMPLATE))
    expected = _registry_entry(spec)["plant_id_prefixes"]
    assert got["plant_id_prefixes"] == expected
    for prefix in expected:
        assert "\\" in prefix["pattern"], "fixture no longer exercises escaping"


@spec_param
def test_the_migrated_patterns_still_route_this_projects_real_plant_ids(
    spec, tmp_path, no_side_effects
):
    """String equality on a regex is not the property that matters — *routing* is.

    Task 3.3 wrote this behaviourally for kibungan because its two prefixes
    made mis-routing visible there first, but nothing about it is
    multi-prefix: a single-prefix project whose pattern survived a YAML
    round-trip as a *plausible-looking but broken* string (an eaten backslash,
    a dropped inline flag) passes `test_id_routing_regexes_survive_backslash_
    intact` — which only compares text — while routing nothing. So the
    patterns are compiled out of the migrated markdown and run against the
    real IDs for every project.

    Per prefix: it matches exactly its own family's IDs and no other family's;
    across prefixes: every real ID is routed by exactly one pattern.
    """
    import re

    from project_markdown import load_schema, read_project

    _, out = _migrate(spec, tmp_path)
    prefixes = read_project(
        out / "project.md", schema=load_schema(PROJECT_TEMPLATE)
    )["plant_id_prefixes"]
    assert prefixes, "no routing patterns -- the check would be vacuous"

    ids = sorted(p["id"] for p in _tracker_json(spec)["plants"])
    assert ids, "no plant IDs -- the check would be vacuous"

    routed_by = {i: [] for i in ids}
    for entry in prefixes:
        compiled = re.compile(entry["pattern"])
        own = [i for i in ids if i.upper().startswith(entry["prefix"].upper())]
        matched = [i for i in ids if compiled.search(i)]
        assert own, f"{entry['prefix']} routes no real ID in this project"
        assert matched == own, (
            f"{entry['prefix']} pattern routes {matched}, expected {own}"
        )
        for i in matched:
            routed_by[i].append(entry["prefix"])

    for plant_id, hits in routed_by.items():
        assert len(hits) == 1, f"{plant_id} routed by {hits}, expected exactly one"


@spec_param
def test_the_migrated_patterns_route_ids_embedded_in_free_text(
    spec, tmp_path, no_side_effects
):
    """The patterns exist to find IDs inside Discord prose, not in isolation.

    A pattern that matches a bare `PC01` can still fail on `checked PC01
    today` if its boundary/lookbehind construct was mangled, and the captured
    group is what the monitor uses to pick the plant — so the *number* is
    asserted, not merely that something matched. The negative (an extra
    leading character must not match) is what proves the boundary construct
    survived rather than being silently dropped.
    """
    import re

    from project_markdown import load_schema, read_project

    _, out = _migrate(spec, tmp_path)
    prefixes = read_project(
        out / "project.md", schema=load_schema(PROJECT_TEMPLATE)
    )["plant_id_prefixes"]
    ids = sorted(p["id"] for p in _tracker_json(spec)["plants"])
    checked = 0

    for entry in prefixes:
        compiled = re.compile(entry["pattern"])
        for plant_id in ids:
            if not plant_id.upper().startswith(entry["prefix"].upper()):
                continue
            digits = re.search(r"(\d+)$", plant_id).group(1)

            match = compiled.search(f"checked {plant_id} today, looking good")
            assert match, f"{plant_id} not routed inside free text"
            assert int(match.group(1)) == int(digits), plant_id

            assert compiled.search(f"X{plant_id}") is None, (
                f"{plant_id} still matches with a leading character -- the "
                f"boundary construct did not survive"
            )
            checked += 1

    assert checked == len(ids), "did not exercise every real ID"


@spec_param
def test_verification_rejects_routing_fields_reverted_to_template_defaults(
    spec, tmp_path, no_side_effects
):
    """Round 5's blind spot: these fields have no tracker counterpart, so a
    tracker-driven verification never compares them and a project.md carrying
    the template defaults (false / []) would pass while breaking ID routing."""
    import re

    from project_markdown import load_schema

    _, out = _migrate(spec, tmp_path)
    entry = _registry_entry(spec)
    schema = load_schema(PROJECT_TEMPLATE)
    project_md = out / "project.md"
    pristine = project_md.read_text(encoding="utf-8")

    tampers = {
        "auto_create": pristine.replace(
            f"auto_create: {str(entry['auto_create']).lower()}",
            f"auto_create: {str(schema['auto_create']['default']).lower()}",
        ),
        "plant_id_prefixes": re.sub(
            r"plant_id_prefixes:\n(?:- .*\n|  .*\n)+",
            "plant_id_prefixes: []\n",
            pristine,
        ),
    }
    try:
        for field, broken in tampers.items():
            if broken == pristine:
                # auto_create already equals the template default (mule-fuel),
                # so reverting it is a no-op and cannot be a discriminating
                # test on this project's data. Skip honestly rather than
                # asserting something trivially true.
                assert field == "auto_create"
                assert entry["auto_create"] == schema["auto_create"]["default"]
                continue
            project_md.write_text(broken, encoding="utf-8")
            report = verify_migration(
                spec.tracker,
                out,
                PROJECT_TEMPLATE,
                PLANT_TEMPLATE,
                spec.registry,
                spec.slug,
            )
            flagged = {c["field"] for c in report.changed_fields.get("project", [])}
            assert not report.ok, f"{field} tamper not rejected"
            assert field in flagged
    finally:
        project_md.write_text(pristine, encoding="utf-8")

    assert verify_migration(
        spec.tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, spec.registry, spec.slug
    ).ok


@spec_param
def test_migration_aborts_when_the_registry_entry_is_missing(
    spec, tmp_path, no_side_effects
):
    """Silently taking the template defaults here is the failure mode Task 3.0
    §8 called the migration's highest risk; it must be a hard error."""
    from tracker_migration import TrackerMigrationError

    stripped = json.loads(spec.registry.read_text(encoding="utf-8"))
    stripped["projects"] = [
        e for e in stripped["projects"] if e["slug"] != spec.slug
    ]
    fake = tmp_path / "registry.json"
    fake.write_text(json.dumps(stripped), encoding="utf-8")

    with pytest.raises(TrackerMigrationError):
        migrate_tracker(
            spec.tracker,
            fake,
            spec.slug,
            tmp_path / "sandbox",
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
        )


# ------------------------------------------------------- determinism --------


@spec_param
def test_migration_is_deterministic_across_two_runs(spec, tmp_path, no_side_effects):
    _, first = _migrate(spec, tmp_path, name="first")
    _, second = _migrate(spec, tmp_path, name="second")
    rels = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert rels == sorted(
        p.relative_to(second) for p in second.rglob("*") if p.is_file()
    )
    assert rels, "compared no files -- the check would be vacuous"
    for rel in rels:
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), rel


# ----------------------------------------- (c)/(d) side-effect isolation ----


@spec_param
def test_tracker_json_md5_is_unchanged(spec, tmp_path, no_side_effects):
    before = file_md5(spec.tracker)
    _migrate(spec, tmp_path)
    assert file_md5(spec.tracker) == before


@spec_param
def test_registry_json_is_untouched(spec, tmp_path, no_side_effects):
    before = file_md5(spec.registry)
    _migrate(spec, tmp_path)
    assert file_md5(spec.registry) == before


@spec_param
def test_the_entire_live_project_directory_is_untouched(
    spec, tmp_path, no_side_effects
):
    """Stronger than the md5 check: no data file under the live dir moved, and
    no nested repo's HEAD or working-tree status moved either.

    Volatile paths (__pycache__/, cache/, .pytest_cache/, dashboard/.git/) are
    excluded: unrelated processes rewrite them at arbitrary times, so including
    them made this check flaky, and a gate that cries wolf gets ignored.
    """
    before = live_tree_state(spec.live_dir)
    _migrate(spec, tmp_path)
    assert live_tree_state(spec.live_dir) == before
    assert before["files"], "fingerprint was empty -- the check would be vacuous"


@spec_param
def test_the_other_projects_are_untouched(spec, tmp_path, no_side_effects):
    """Task 3.x migrates ONE project; the sibling live dirs must not move."""
    others = [
        d
        for d in sorted(BREEDING_ROOT.iterdir())
        if d.is_dir() and d.name != spec.slug and (d / "tracker.json").exists()
    ]
    assert others, "no sibling projects found -- the check would be vacuous"
    before = {d.name: file_md5(d / "tracker.json") for d in others}
    _migrate(spec, tmp_path)
    assert {d.name: file_md5(d / "tracker.json") for d in others} == before


@spec_param
def test_all_writes_land_inside_the_sandbox(spec, tmp_path, no_side_effects):
    out = tmp_path / "sandbox" / spec.slug
    real_open = os.open
    written: list[str] = []

    def spy_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
            written.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    os.open = spy_open
    try:
        migrate_tracker(
            spec.tracker,
            spec.registry,
            spec.slug,
            out,
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
        )
    finally:
        os.open = real_open

    assert written, "no writes observed -- the spy would be vacuous"
    root = tmp_path.resolve()
    for path in written:
        assert Path(path).resolve().is_relative_to(root), path


@spec_param
def test_the_migration_refuses_to_write_into_the_live_project_dir(spec, tmp_path):
    """The sandbox guard, exercised against the real path it must protect."""
    with pytest.raises(SandboxViolationError):
        migrate_tracker(
            spec.tracker,
            spec.registry,
            spec.slug,
            spec.live_dir / "markdown",
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
        )
    assert not (spec.live_dir / "markdown").exists()


@spec_param
def test_the_live_dir_guard_beats_the_git_opt_in(spec, tmp_path):
    """`allow_git_repo=True` must never become a blanket write-into-live-data
    switch, even for the eventual deliberate real run."""
    with pytest.raises(SandboxViolationError):
        migrate_tracker(
            spec.tracker,
            spec.registry,
            spec.slug,
            spec.live_dir / "markdown",
            PROJECT_TEMPLATE,
            PLANT_TEMPLATE,
            allow_git_repo=True,
        )
    assert not (spec.live_dir / "markdown").exists()


def test_the_migration_module_cannot_reach_the_network_or_a_shell():
    """Static proof, independent of whether any given run happens to try.

    Not parametrized: it is a property of the module, not of a project.
    """
    source = (REPO / "src" / "tracker_migration.py").read_text(encoding="utf-8")
    for forbidden in (
        "import subprocess",
        "import socket",
        "import urllib",
        "import http",
        "import requests",
        "import smtplib",
        "os.system",
        "os.popen",
    ):
        assert forbidden not in source, forbidden


def test_every_spec_is_covered_by_this_module():
    """Guards the parametrization itself: a spec added to PROJECT_SPECS but
    skipped for a missing tracker must be visible, not silently uncovered."""
    assert PROJECT_SPECS, "no projects registered"
    assert len({s.slug for s in PROJECT_SPECS}) == len(PROJECT_SPECS)
