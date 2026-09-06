#!/usr/bin/env python3
"""Independent, out-of-band proof of the honey-badger-haze-pheno-hunt migration.

Deliberately does NOT use the test suite or its assertions: it re-derives
every acceptance claim from scratch so a bug shared between the migration
code and its tests cannot hide.

Run:  .venv/bin/python tools/verify_honey_badger_haze_migration.py
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SLUG = "honey-badger-haze-pheno-hunt"
LIVE = Path.home() / ".hermes" / "breeding" / SLUG
TRACKER = LIVE / "tracker.json"
REGISTRY = (
    Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
)
PROJECT_TEMPLATE = REPO / "templates" / "project-template.md"
PLANT_TEMPLATE = REPO / "templates" / "plant-template.md"

EXPECTED_PLANTS = 23

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def md5sum_via_system(path):
    """Hash with the system binary, not the module under test."""
    out = subprocess.run(
        ["md5sum", str(path)], capture_output=True, text=True, check=True
    )
    return out.stdout.split()[0]


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.lstat().st_size, p.lstat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
    }


def main():
    import plant_markdown
    import project_markdown
    from tracker_migration import migrate_tracker, verify_migration

    print(f"tracker : {TRACKER}")
    print(f"registry: {REGISTRY}\n")

    tracker_md5_before = md5sum_via_system(TRACKER)
    registry_md5_before = md5sum_via_system(REGISTRY)
    live_before = snapshot(LIVE)
    # Baselines for the sibling projects must be captured BEFORE the migration
    # runs, or the post-run comparison has nothing to detect a change against.
    breeding_root = Path.home() / ".hermes" / "breeding"
    sibling_dirs = [
        d
        for d in sorted(breeding_root.iterdir())
        if d.is_dir() and d.name != SLUG and (d / "tracker.json").exists()
    ]
    siblings_before = {
        d.name: md5sum_via_system(d / "tracker.json") for d in sibling_dirs
    }
    print(f"tracker.json md5 BEFORE (system md5sum): {tracker_md5_before}\n")

    source = json.loads(TRACKER.read_text(encoding="utf-8"))
    source_plants = source["plants"]
    entry = next(
        e
        for e in json.loads(REGISTRY.read_text(encoding="utf-8"))["projects"]
        if e["slug"] == SLUG
    )

    with tempfile.TemporaryDirectory(prefix="honey-badger-sandbox-") as tmp:
        out = Path(tmp) / SLUG
        summary = migrate_tracker(
            TRACKER, REGISTRY, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
        print(f"sandbox : {out}\n")

        # --- (a) plant count ------------------------------------------------
        written = sorted((out / "plants").glob("*.md"))
        check(
            "plant count matches (source == files written == 23)",
            len(source_plants) == len(written) == EXPECTED_PLANTS,
            f"source={len(source_plants)} files={len(written)}",
        )
        check(
            "plant IDs match exactly",
            sorted(p["id"] for p in source_plants) == sorted(p.stem for p in written),
        )
        check(
            "plant IDs are the contiguous HBH01..HBH23 run (no gap, no renumber)",
            sorted(p.stem for p in written)
            == [f"HBH{n:02d}" for n in range(1, EXPECTED_PLANTS + 1)],
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
            "zero plant fields lost",
            not lost,
            f"{fields_checked} field values compared",
        )
        check("zero plant field values altered", not changed, str(changed[:5]))
        check(
            "every plant carried all 18 inventoried keys",
            all(len(p) == 18 for p in source_plants),
            f"key counts={sorted({len(p) for p in source_plants})}",
        )

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

        # --- project-specific shapes ----------------------------------------
        check(
            "notes_meta present in source and preserved verbatim (not defaulted to {})",
            "notes_meta" in source
            and got_project["notes_meta"] == source["notes_meta"]
            and got_project["notes_meta"] != {},
        )
        check(
            "drive_folders round-trips whole, without mule-fuel's reports subkeys",
            got_project["drive_folders"] == source["drive_folders"]
            and "reports" not in got_project["drive_folders"],
            f"{len(got_project['drive_folders'])} subkeys",
        )
        check(
            "no project-level field needed a template default",
            summary.defaulted_fields.get("project") is None,
            str(summary.defaulted_fields.get("project")),
        )
        plant_defaults = {
            tuple(v) for k, v in summary.defaulted_fields.items() if k != "project"
        }
        check(
            "corrected_reading is the ONLY defaulted plant field, on all 23 plants",
            plant_defaults == {("corrected_reading",)}
            and len(
                [k for k in summary.defaulted_fields if k != "project"]
            )
            == EXPECTED_PLANTS,
            str(plant_defaults),
        )
        check(
            "no plant needed a photo_count/photos_drive_url default (MG07 hazard "
            "is mule-fuel-specific)",
            not any(
                "photo_count" in f or "photos_drive_url" in f
                for f in summary.defaulted_fields.values()
            ),
        )

        # --- registry-sourced routing fields (Task 3.0 §8) -------------------
        check(
            "auto_create sourced from registry.json",
            got_project["auto_create"] == entry["auto_create"],
            f"value={got_project['auto_create']}",
        )
        check(
            "auto_create (true) DIFFERS from the template default (false), so the "
            "registry was demonstrably read -- the discriminating case mule-fuel "
            "could not provide",
            entry["auto_create"] is True
            and project_schema["auto_create"]["default"] is False
            and got_project["auto_create"] is True
            and "auto_create" not in source,
        )
        check(
            "plant_id_prefixes sourced from registry.json",
            got_project["plant_id_prefixes"] == entry["plant_id_prefixes"],
        )
        check(
            "the HBH ID-routing regex survives backslash-intact",
            got_project["plant_id_prefixes"][0]["pattern"]
            == r"\bHBH[\s\-]?(\d{1,2})\b",
            got_project["plant_id_prefixes"][0]["pattern"],
        )

        # --- observation_log verbatim ---------------------------------------
        bad_body = []
        for plant in source_plants:
            text = (out / "plants" / f"{plant['id']}.md").read_text(
                encoding="utf-8", newline=""
            )
            body = text.split("\n---\n", 1)[1]
            if body != plant["observation_log"]:
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
        report = verify_migration(
            TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
        )
        expected_records = 1 + len(source_plants)
        expected_fields = (
            fields_checked + len([k for k in source if k != "plants"]) + 2
        )
        check(
            "verification report is not vacuous",
            report.ok and report.verified_something,
            f"records={report.records_compared} fields={report.fields_compared}",
        )
        check(
            "verification compared every record and field value",
            report.records_compared == expected_records
            and report.fields_compared == expected_fields,
            f"expected records={expected_records} fields={expected_fields}",
        )
        check(
            "verification of a never-migrated dir is reported as NOT ok",
            not verify_migration(
                TRACKER,
                Path(tmp) / "never-migrated",
                PROJECT_TEMPLATE,
                PLANT_TEMPLATE,
                REGISTRY,
                SLUG,
            ).ok,
        )

        # --- the gate must see the registry-sourced routing fields -----------
        project_md = out / "project.md"
        pristine = project_md.read_text(encoding="utf-8")
        tampers = {
            "auto_create": pristine.replace(
                f"auto_create: {str(entry['auto_create']).lower()}",
                f"auto_create: {str(not entry['auto_create']).lower()}",
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
                    check(f"tamper fixture actually modified {field}", False)
                    continue
                project_md.write_text(broken, encoding="utf-8")
                tampered = verify_migration(
                    TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
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
                TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE, REGISTRY, SLUG
            ).ok,
        )

        try:
            verify_migration(TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE)
            registry_required = False
        except TypeError:
            registry_required = True
        check(
            "verify_migration cannot be called without the registry", registry_required
        )

        # --- determinism -----------------------------------------------------
        second = Path(tmp) / "second-run"
        migrate_tracker(
            TRACKER, REGISTRY, SLUG, second, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
        rels = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
        identical = all(
            (out / r).read_bytes() == (second / r).read_bytes() for r in rels
        )
        check(
            "a second migration of the same source is byte-identical",
            identical and rels == sorted(
                p.relative_to(second) for p in second.rglob("*") if p.is_file()
            ),
            f"{len(rels)} files compared",
        )

        # --- a mid-write failure must leave nothing behind -------------------
        rollback_out = Path(tmp) / "rollback-probe"
        real_write_plant = plant_markdown.write_plant
        seen = {"n": 0}

        def fail_midway(path, record, **kwargs):
            seen["n"] += 1
            if seen["n"] == 12:
                raise OSError("simulated ENOSPC partway through the plant writes")
            return real_write_plant(path, record, **kwargs)

        plant_markdown.write_plant = fail_midway
        try:
            migrate_tracker(
                TRACKER,
                REGISTRY,
                SLUG,
                rollback_out,
                PROJECT_TEMPLATE,
                PLANT_TEMPLATE,
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
            "a failed write partway through 23 plants leaves no half-written tree",
            rolled_back,
            detail,
        )

        # --- the guard protects the live dir ---------------------------------
        from tracker_migration import SandboxViolationError

        for label, kwargs in (
            ("", {}),
            (" even with allow_git_repo=True", {"allow_git_repo": True}),
        ):
            try:
                migrate_tracker(
                    TRACKER,
                    REGISTRY,
                    SLUG,
                    LIVE / "markdown",
                    PROJECT_TEMPLATE,
                    PLANT_TEMPLATE,
                    **kwargs,
                )
                refused = False
            except SandboxViolationError:
                refused = True
            check(
                f"migration refuses to write into the live project dir{label}",
                refused and not (LIVE / "markdown").exists(),
            )

    check("sandbox directory removed after the run", not out.exists())

    tracker_md5_after = md5sum_via_system(TRACKER)
    print(f"\ntracker.json md5 AFTER  (system md5sum): {tracker_md5_after}")
    check(
        "tracker.json md5 unchanged",
        tracker_md5_after == tracker_md5_before,
        tracker_md5_after,
    )
    check(
        "registry.json md5 unchanged",
        md5sum_via_system(REGISTRY) == registry_md5_before,
    )
    check(
        "entire live project dir unchanged (size+mtime of every file)",
        snapshot(LIVE) == live_before,
        f"{len(live_before)} paths fingerprinted",
    )
    check("summary reports tracker unchanged", summary.tracker_unchanged)

    # --- the other five projects are untouched -----------------------------
    siblings_after = {
        d.name: md5sum_via_system(d / "tracker.json") for d in sibling_dirs
    }
    check(
        "the other 5 project trackers are unchanged (this task migrates one)",
        len(sibling_dirs) == 5 and siblings_after == siblings_before,
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
    allowed_suffixes = (
        "src/tracker_migration.py",
        "tests/test_tracker_migration.py",
        "tests/test_mule_fuel_migration.py",
        "tests/test_honey_badger_haze_migration.py",
        "tools/verify_mule_fuel_migration.py",
        "tools/verify_honey_badger_haze_migration.py",
        "DECISIONS.md",
        "TASK-3.1-MIGRATION-REPORT.md",
        "TASK-3.2-MIGRATION-REPORT.md",
    )
    for repo in (REPO, REGISTRY.parent):
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        unexpected = [
            line for line in status.splitlines() if not line.endswith(allowed_suffixes)
        ]
        check(
            f"no unexpected git changes in {repo.name}", not unexpected, str(unexpected)
        )

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} checks failed): {failures}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
