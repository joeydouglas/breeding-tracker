#!/usr/bin/env python3
"""Independent, out-of-band proof of a Task 3.x tracker migration.

Deliberately does NOT use the test suite or its assertions: it re-derives
every acceptance claim from scratch so a bug shared between the migration
code and its tests cannot hide. Hashing goes through the system `md5sum`
binary rather than Python's hashlib for the same reason.

One script for every project, driven by `migration_specs.PROJECT_SPECS`.
Task 3.1 and 3.2 each had their own ~450-line copy; the copies had already
diverged (mule-fuel's git gate carried a blanket "tools/" escape that
honey-badger's did not), which is exactly the drift a per-project copy
invites. Project-specific expectations live in the spec, not in the script.

Run:  .venv/bin/python tools/verify_migration.py <slug>
      .venv/bin/python tools/verify_migration.py --all
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from migration_harness import (  # noqa: E402  (needs the sys.path line above)
    describe_baseline_dirt,
    git_repo_state,
    live_tree_state,
    unexpected_repo_changes,
)
from migration_specs import PROJECT_SPECS, SPECS_BY_SLUG  # noqa: E402

PROJECT_TEMPLATE = REPO / "templates" / "project-template.md"
PLANT_TEMPLATE = REPO / "templates" / "plant-template.md"


class Checker:
    """Collects pass/fail results and refuses to end on zero evidence."""

    def __init__(self):
        self.failures = []
        self.passes = 0

    def __call__(self, label, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {label}" + (f" -- {detail}" if detail else ""))
        if condition:
            self.passes += 1
        else:
            self.failures.append(label)

    @property
    def total(self):
        return self.passes + len(self.failures)


def md5sum_via_system(path):
    """Hash with the system binary, not the module under test."""
    out = subprocess.run(
        ["md5sum", str(path)], capture_output=True, text=True, check=True
    )
    return out.stdout.split()[0]


def verify(spec, check, allow_dirty_baseline=False):
    """Every acceptance claim for one project, re-derived from scratch."""
    import plant_markdown
    import project_markdown
    from tracker_migration import (
        SandboxViolationError,
        migrate_tracker,
        verify_migration,
    )

    tracker, registry, slug = spec.tracker, spec.registry, spec.slug
    live = spec.live_dir

    print(f"\n{'=' * 70}\n{slug}\n{'=' * 70}")
    print(f"tracker : {tracker}")
    print(f"registry: {registry}\n")

    # Baselines captured BEFORE the migration runs, or the post-run
    # comparisons have nothing to detect a change against.
    #
    # The baseline is also asserted to be CLEAN, not merely recorded. A
    # before/after diff alone proves only "this invocation changed nothing";
    # it adopts whatever was already dirty as its own allowance, so a stray
    # artefact left by an EARLIER run -- exactly the side effect this gate
    # exists to catch -- is laundered into the baseline and never reported.
    # Cleanliness is the property the acceptance claim actually needs, so the
    # dirt is named here and the run fails on it unless a human explicitly
    # opts out with --allow-dirty-baseline (which is itself reported, so an
    # opted-out run can never be mistaken for a clean one).
    git_baseline = {repo: git_repo_state(repo) for repo in (REPO, registry.parent)}
    for repo, state in git_baseline.items():
        dirt = describe_baseline_dirt(state)
        if dirt and allow_dirty_baseline:
            print(
                f"[NOTE] {repo.name} was already dirty before this run and "
                f"--allow-dirty-baseline was given, so the pre-run cleanliness "
                f"claim is NOT being made for it: {dirt}"
            )
            continue
        check(
            f"{repo.name} working tree was already clean BEFORE the run started",
            not dirt,
            str(dirt),
        )
    tracker_md5_before = md5sum_via_system(tracker)
    registry_md5_before = md5sum_via_system(registry)
    live_before = live_tree_state(live)

    breeding_root = Path.home() / ".hermes" / "breeding"
    sibling_dirs = [
        d
        for d in sorted(breeding_root.iterdir())
        if d.is_dir() and d.name != slug and (d / "tracker.json").exists()
    ]
    siblings_before = {
        d.name: md5sum_via_system(d / "tracker.json") for d in sibling_dirs
    }
    print(f"tracker.json md5 BEFORE (system md5sum): {tracker_md5_before}\n")

    source = json.loads(tracker.read_text(encoding="utf-8"))
    source_plants = source["plants"]
    entry = next(
        e
        for e in json.loads(registry.read_text(encoding="utf-8"))["projects"]
        if e["slug"] == slug
    )

    with tempfile.TemporaryDirectory(prefix=f"{slug}-sandbox-") as tmp:
        out = Path(tmp) / slug
        summary = migrate_tracker(
            tracker, registry, slug, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
        print(f"sandbox : {out}\n")

        # --- (a) plant count ------------------------------------------------
        written = sorted((out / "plants").glob("*.md"))
        check(
            f"plant count matches (source == files written == {spec.plant_count})",
            len(source_plants) == len(written) == spec.plant_count,
            f"source={len(source_plants)} files={len(written)}",
        )
        check(
            "plant IDs match exactly",
            sorted(p["id"] for p in source_plants) == sorted(p.stem for p in written),
        )

        # --- (b) zero field loss, re-derived --------------------------------
        plant_schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        project_schema = project_markdown.load_schema(PROJECT_TEMPLATE)

        lost, changed, fields_checked = [], [], 0
        for plant in source_plants:
            got = plant_markdown.read_plant(
                out / "plants" / f"{plant['id']}.md", schema=plant_schema
            )
            for field, original in plant.items():
                fields_checked += 1
                if field not in got:
                    lost.append(f"{plant['id']}.{field}")
                elif got[field] != original:
                    changed.append(f"{plant['id']}.{field}")
        check(
            "zero plant fields lost", not lost, f"{fields_checked} field values compared"
        )
        check("zero plant field values altered", not changed, str(changed[:5]))

        got_project = project_markdown.read_project(
            out / "project.md", schema=project_schema
        )
        proj_lost = [k for k in source if k != "plants" and k not in got_project]
        proj_changed = [
            k
            for k, v in source.items()
            if k != "plants" and k in got_project and got_project[k] != v
        ]
        check("zero project fields lost", not proj_lost, str(proj_lost))
        check("zero project field values altered", not proj_changed, str(proj_changed))
        check(
            "'plants' array not duplicated into project frontmatter",
            "plants" not in got_project,
        )

        rebuilt = {k: got_project[k] for k in source if k != "plants"}
        check(
            "project dict reconstructed from markdown == source (JSON-equal)",
            json.dumps(rebuilt, sort_keys=True)
            == json.dumps(
                {k: v for k, v in source.items() if k != "plants"}, sort_keys=True
            ),
        )

        rebuilt_plants = []
        for plant in source_plants:
            got = plant_markdown.read_plant(
                out / "plants" / f"{plant['id']}.md", schema=plant_schema
            )
            rebuilt_plants.append({k: got[k] for k in plant})
        check(
            "full plants array reconstructed from markdown == source (JSON-equal)",
            json.dumps(rebuilt_plants, sort_keys=True)
            == json.dumps(source_plants, sort_keys=True),
        )

        # --- defaults are tracked separately from preservation ---------------
        check(
            "defaulted project fields are exactly the expected set",
            set(summary.defaulted_fields.get("project", ()))
            == set(spec.expected_project_defaults),
            str(sorted(summary.defaulted_fields.get("project", ()))),
        )
        incomplete = {
            record
            for record, fields in summary.defaulted_fields.items()
            if record != "project"
            and ("photo_count" in fields or "photos_drive_url" in fields)
        }
        check(
            "only the known-incomplete plants needed photo defaults",
            incomplete == set(spec.incomplete_plants),
            f"got={sorted(incomplete)} expected={sorted(spec.incomplete_plants)}",
        )

        # --- observation_log verbatim ---------------------------------------
        bad_body = []
        for plant in source_plants:
            text = (out / "plants" / f"{plant['id']}.md").read_text(
                encoding="utf-8", newline=""
            )
            if text.split("\n---\n", 1)[1] != plant["observation_log"]:
                bad_body.append(plant["id"])
        check(
            "observation_log bodies byte-identical to source",
            not bad_body,
            str(bad_body[:5]),
        )

        # --- (c)/(d) side-effect isolation -----------------------------------
        outside = [
            p for p in out.rglob("*") if not p.resolve().is_relative_to(out.resolve())
        ]
        check("all output confined to the sandbox dir", not outside)

        # --- the gate must prove it inspected something ----------------------
        # A verifier that silently degrades to a no-op reports no discrepancy
        # and is otherwise indistinguishable from a clean migration, so the
        # report's own evidence counts are checked against independently
        # re-derived totals rather than trusted.
        report = verify_migration(
            tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, slug
        )
        expected_fields = spec.expected_fields(source)
        check(
            "verification report is not vacuous",
            report.ok and report.verified_something,
            f"records={report.records_compared} fields={report.fields_compared}",
        )
        check(
            "verification compared every record and field value",
            report.records_compared == spec.expected_records
            and report.fields_compared == expected_fields,
            f"expected records={spec.expected_records} fields={expected_fields}",
        )
        check(
            "verification of a never-migrated dir is reported as NOT ok",
            not verify_migration(
                tracker,
                Path(tmp) / "never-migrated",
                PROJECT_TEMPLATE,
                PLANT_TEMPLATE,
                registry,
                slug,
            ).ok,
        )

        # --- registry-sourced routing fields (Task 3.0 §8) -------------------
        check(
            "auto_create sourced from registry.json",
            got_project["auto_create"] == entry["auto_create"],
            f"value={got_project['auto_create']}",
        )
        check(
            "plant_id_prefixes sourced from registry.json",
            got_project["plant_id_prefixes"] == entry["plant_id_prefixes"],
        )
        template_default = project_schema["auto_create"]["default"]
        if entry["auto_create"] != template_default:
            check(
                "auto_create DIFFERS from the template default, so the registry "
                "was demonstrably read (a discriminating case)",
                got_project["auto_create"] == entry["auto_create"]
                and "auto_create" not in source,
            )
        else:
            print(
                "[NOTE] auto_create equals the template default on this project, "
                "so its value cannot distinguish a registry read from a silent "
                "default. Covered by a project where they differ."
            )
        check(
            "ID-routing regexes survive backslash-intact",
            got_project["plant_id_prefixes"] == entry["plant_id_prefixes"]
            and all("\\" in p["pattern"] for p in got_project["plant_id_prefixes"]),
            str([p["pattern"] for p in got_project["plant_id_prefixes"]]),
        )

        # --- the gate must see the registry-sourced routing fields -----------
        # These have no tracker counterpart, so a verification driven by
        # tracker.json alone treats them as "not in the source" and never
        # compares them: a project.md carrying the template defaults (false /
        # []) -- which breaks ID routing in production -- would pass.
        project_md = out / "project.md"
        pristine = project_md.read_text(encoding="utf-8")
        tampers = {
            "auto_create": pristine.replace(
                f"auto_create: {str(entry['auto_create']).lower()}",
                f"auto_create: {str(template_default).lower()}",
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
                    # Reverting to a value it already holds is a no-op and
                    # cannot be a discriminating test on this project's data.
                    if field == "auto_create" and entry[field] == template_default:
                        continue
                    check(f"tamper fixture actually modified {field}", False)
                    continue
                project_md.write_text(broken, encoding="utf-8")
                tampered = verify_migration(
                    tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, slug
                )
                flagged = field in {
                    c["field"] for c in tampered.changed_fields.get("project", [])
                }
                check(
                    f"verification rejects a {field} that no longer matches "
                    "registry.json",
                    (not tampered.ok) and flagged,
                    f"ok={tampered.ok} flagged={flagged}",
                )
        finally:
            project_md.write_text(pristine, encoding="utf-8")

        check(
            "restored project.md verifies clean again",
            verify_migration(
                tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, registry, slug
            ).ok,
        )

        # The registry is not optional on the verification path: a caller that
        # omits it must get an error, never a silently tracker-only pass.
        try:
            verify_migration(tracker, out, PROJECT_TEMPLATE, PLANT_TEMPLATE)
            registry_required = False
        except TypeError:
            registry_required = True
        check(
            "verify_migration cannot be called without the registry", registry_required
        )

        # --- determinism -----------------------------------------------------
        second = Path(tmp) / "second-run"
        migrate_tracker(
            tracker, registry, slug, second, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
        rels = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
        identical = all((out / r).read_bytes() == (second / r).read_bytes() for r in rels)
        check(
            "a second migration of the same source is byte-identical",
            identical
            and rels
            == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file()),
            f"{len(rels)} files compared",
        )

        # --- a mid-write failure must leave nothing behind -------------------
        rollback_out = Path(tmp) / "rollback-probe"
        real_write_plant = plant_markdown.write_plant
        seen = {"n": 0}
        fail_at = max(2, spec.plant_count // 2)

        def fail_midway(path, record, **kwargs):
            seen["n"] += 1
            if seen["n"] == fail_at:
                raise OSError("simulated ENOSPC partway through the plant writes")
            return real_write_plant(path, record, **kwargs)

        plant_markdown.write_plant = fail_midway
        try:
            migrate_tracker(
                tracker, registry, slug, rollback_out, PROJECT_TEMPLATE, PLANT_TEMPLATE
            )
            rolled_back = False
            detail = "no exception raised"
        except OSError:
            rolled_back = not rollback_out.exists()
            detail = (
                "clean"
                if rolled_back
                else f"leftovers={sorted(p.name for p in rollback_out.rglob('*'))}"
            )
        finally:
            plant_markdown.write_plant = real_write_plant
        check(
            f"a failed write on plant {fail_at} of {spec.plant_count} leaves no "
            "half-written tree",
            rolled_back,
            detail,
        )

        # --- the guard protects the live dir ---------------------------------
        for label, kwargs in (
            ("", {}),
            (" even with allow_git_repo=True", {"allow_git_repo": True}),
        ):
            try:
                migrate_tracker(
                    tracker,
                    registry,
                    slug,
                    live / "markdown",
                    PROJECT_TEMPLATE,
                    PLANT_TEMPLATE,
                    **kwargs,
                )
                refused = False
            except SandboxViolationError:
                refused = True
            check(
                f"migration refuses to write into the live project dir{label}",
                refused and not (live / "markdown").exists(),
            )

    check("sandbox directory removed after the run", not out.exists())

    tracker_md5_after = md5sum_via_system(tracker)
    print(f"\ntracker.json md5 AFTER  (system md5sum): {tracker_md5_after}")
    check(
        "tracker.json md5 unchanged",
        tracker_md5_after == tracker_md5_before,
        tracker_md5_after,
    )
    check(
        "registry.json md5 unchanged",
        md5sum_via_system(registry) == registry_md5_before,
    )
    live_after = live_tree_state(live)
    check(
        "entire live project dir unchanged (data files + nested repo HEAD/status)",
        live_after == live_before,
        f"{len(live_before['files'])} data paths + "
        f"{len(live_before['repos'])} nested repos",
    )
    check("summary reports tracker unchanged", summary.tracker_unchanged)

    # --- the other projects are untouched -----------------------------------
    siblings_after = {
        d.name: md5sum_via_system(d / "tracker.json") for d in sibling_dirs
    }
    check(
        "the other project trackers are unchanged (this task migrates one)",
        bool(sibling_dirs) and siblings_after == siblings_before,
        f"{sorted(siblings_before)}",
    )

    # --- static proof of no side-effect capability -------------------------
    module_source = (REPO / "src" / "tracker_migration.py").read_text(encoding="utf-8")
    forbidden = [
        token
        for token in (
            "import subprocess",
            "import socket",
            "import urllib",
            "import http",
            "import requests",
            "import smtplib",
            "os.system",
            "os.popen",
        )
        if token in module_source
    ]
    check(
        "tracker_migration.py has no network/shell capability at all",
        not forbidden,
        str(forbidden),
    )

    # --- no git side effects anywhere -------------------------------------
    # Baseline-diff, not a whitelist: whatever was already dirty when this run
    # started is the allowance, so no path is ever forgiven by name and a
    # *change* to an already-dirty file is still caught.
    #
    # The comparison is over the full repo state -- HEAD sha, porcelain codes
    # AND a content digest per non-clean path -- not the porcelain codes
    # alone. A code-only diff is blind to two real side effects: appending to
    # a file that was already ' M' (or '??') leaves its code untouched, and a
    # mid-run `git commit` returns porcelain to clean, which reads exactly
    # like a run that touched nothing. Both move HEAD or the bytes, so both
    # are now reported.
    for repo in (REPO, registry.parent):
        unexpected = unexpected_repo_changes(git_baseline[repo], git_repo_state(repo))
        check(
            f"no unexpected git changes in {repo.name}", not unexpected, str(unexpected)
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", help="project slug to verify")
    parser.add_argument("--all", action="store_true", help="verify every project")
    parser.add_argument(
        "--allow-dirty-baseline",
        action="store_true",
        help=(
            "do not fail when a repo is already dirty before the run; the dirt "
            "is printed as a NOTE and the pre-run cleanliness claim is dropped "
            "for that repo. For use mid-task when the working tree legitimately "
            "carries in-flight edits -- never for a final acceptance run."
        ),
    )
    args = parser.parse_args()

    if args.all:
        specs = list(PROJECT_SPECS)
    elif args.slug:
        if args.slug not in SPECS_BY_SLUG:
            parser.error(
                f"unknown slug {args.slug!r}; known: {sorted(SPECS_BY_SLUG)}"
            )
        specs = [SPECS_BY_SLUG[args.slug]]
    else:
        parser.error("give a slug or --all")

    check = Checker()
    for spec in specs:
        if not spec.tracker.exists():
            print(f"[SKIP] {spec.slug}: tracker not present at {spec.tracker}")
            continue
        verify(spec, check, allow_dirty_baseline=args.allow_dirty_baseline)

    print()
    if not check.total:
        print("RESULT: FAIL (no checks ran -- a vacuous pass is not a pass)")
        return 1
    if check.failures:
        print(
            f"RESULT: FAIL ({len(check.failures)}/{check.total} checks failed): "
            f"{check.failures}"
        )
        return 1
    print(f"RESULT: ALL {check.total} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
