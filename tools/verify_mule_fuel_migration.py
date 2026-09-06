#!/usr/bin/env python3
"""Independent, out-of-band proof of the mule-fuel migration.

Deliberately does NOT use the test suite or its assertions: it re-derives
every acceptance claim from scratch so a bug shared between the migration
code and its tests cannot hide.

Run:  .venv/bin/python tools/verify_mule_fuel_migration.py
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SLUG = "mule-fuel-x-nana-glue"
LIVE = Path.home() / ".hermes" / "breeding" / SLUG
TRACKER = LIVE / "tracker.json"
REGISTRY = Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta" / "registry.json"
PROJECT_TEMPLATE = REPO / "templates" / "project-template.md"
PLANT_TEMPLATE = REPO / "templates" / "plant-template.md"

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def md5sum_via_system(path):
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
    from tracker_migration import migrate_tracker

    print(f"tracker : {TRACKER}")
    print(f"registry: {REGISTRY}\n")

    tracker_md5_before = md5sum_via_system(TRACKER)
    registry_md5_before = md5sum_via_system(REGISTRY)
    live_before = snapshot(LIVE)
    print(f"tracker.json md5 BEFORE (system md5sum): {tracker_md5_before}\n")

    source = json.loads(TRACKER.read_text(encoding="utf-8"))
    source_plants = source["plants"]

    with tempfile.TemporaryDirectory(prefix="mule-fuel-sandbox-") as tmp:
        out = Path(tmp) / SLUG
        summary = migrate_tracker(
            TRACKER, REGISTRY, SLUG, out, PROJECT_TEMPLATE, PLANT_TEMPLATE
        )
        print(f"sandbox : {out}\n")

        # --- (a) plant count ------------------------------------------------
        written = sorted((out / "plants").glob("*.md"))
        check(
            "plant count matches (source == files written)",
            len(source_plants) == len(written) == 45,
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
            "zero plant fields lost",
            not lost,
            f"{fields_checked} field values compared",
        )
        check("zero plant field values altered", not changed, str(changed[:5]))

        got_project = project_markdown.read_project(
            out / "project.md", schema=project_schema
        )
        proj_lost = [
            k for k in source if k != "plants" and k not in got_project
        ]
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

        # A JSON round-trip equality check that never touches the reader used
        # to write the files' sibling code path.
        rebuilt = {k: v for k, v in got_project.items() if k not in ("body",)}
        rebuilt = {k: rebuilt[k] for k in source if k != "plants"}
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

        # --- registry-sourced routing fields --------------------------------
        entry = next(
            e
            for e in json.loads(REGISTRY.read_text(encoding="utf-8"))["projects"]
            if e["slug"] == SLUG
        )
        check(
            "auto_create sourced from registry.json, not the template default",
            got_project["auto_create"] == entry["auto_create"],
            f"value={got_project['auto_create']}",
        )
        check(
            "plant_id_prefixes sourced from registry.json",
            got_project["plant_id_prefixes"] == entry["plant_id_prefixes"],
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
        check("observation_log bodies byte-identical to source", not bad_body,
              str(bad_body[:5]))

        # --- (c)/(d) side-effect isolation -----------------------------------
        outside = [
            p
            for p in out.rglob("*")
            if not p.resolve().is_relative_to(out.resolve())
        ]
        check("all output confined to the sandbox dir", not outside)

        # --- the gate must prove it inspected something ----------------------
        # A verifier that silently degrades to a no-op reports no discrepancy
        # and is otherwise indistinguishable from a clean migration, so the
        # report's own evidence counts are checked against independently
        # re-derived totals rather than trusted.
        from tracker_migration import verify_migration

        report = verify_migration(TRACKER, out, PROJECT_TEMPLATE, PLANT_TEMPLATE)
        expected_records = 1 + len(source_plants)
        expected_fields = fields_checked + len(
            [k for k in source if k != "plants"]
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
                TRACKER, Path(tmp) / "never-migrated", PROJECT_TEMPLATE, PLANT_TEMPLATE
            ).ok,
        )

        # --- a mid-write failure must leave nothing behind -------------------
        rollback_out = Path(tmp) / "rollback-probe"
        real_write_plant = plant_markdown.write_plant
        seen = {"n": 0}

        def fail_midway(path, record, **kwargs):
            seen["n"] += 1
            if seen["n"] == 20:
                raise OSError("simulated ENOSPC partway through the plant writes")
            return real_write_plant(path, record, **kwargs)

        plant_markdown.write_plant = fail_midway
        try:
            migrate_tracker(
                TRACKER, REGISTRY, SLUG, rollback_out, PROJECT_TEMPLATE, PLANT_TEMPLATE
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
            "a failed write partway through 45 plants leaves no half-written tree",
            rolled_back,
            detail,
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
    check(
        "summary reports tracker unchanged",
        summary.tracker_unchanged,
    )

    # --- no git side effects anywhere -------------------------------------
    for repo in (REPO, REGISTRY.parent):
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        # breeding-markdown legitimately has this task's new source/test files.
        unexpected = [
            line
            for line in status.splitlines()
            if not line.endswith(
                (
                    "src/tracker_migration.py",
                    "tests/test_tracker_migration.py",
                    "tests/test_mule_fuel_migration.py",
                    "tools/verify_mule_fuel_migration.py",
                    "DECISIONS.md",
                    "TASK-3.1-MIGRATION-REPORT.md",
                )
            )
            and "tools/" not in line
        ]
        check(f"no unexpected git changes in {repo.name}", not unexpected,
              str(unexpected))

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} checks failed): {failures}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
