#!/usr/bin/env python3
"""Reusable mutation harness for the tracker migration.

Every Task 3.x report claims its new checks "can actually fail", and every one
of those claims was produced by a throwaway script in `/tmp` that was deleted
afterwards. That makes the strongest evidence in the whole phase the one thing
nobody can re-run. This file is that script, committed, with the mutants named
and de-duplicated across tasks.

Two roles in one file, deliberately, so a mutant is defined exactly once:

* **pytest plugin.** `MUTANT=<name> pytest -p mutation_test` monkeypatches the
  migration in-process for the whole session, so the mutant is live for every
  test including the parametrized shared contract.
* **runner.** `python tools/mutation_test.py` re-runs the suite once per mutant
  in a subprocess and prints a kill table: which tests died, and — the part the
  uniqueness claims actually rest on — which *project parametrizations* of the
  shared contract died.

A mutant that kills nothing is a hole in the suite. A mutant killed on exactly
one project's parametrization is the evidence for that project's uniqueness
claim, demonstrated instead of asserted in a docstring.

Safety: mutants patch functions in memory only. Nothing here writes to any real
project directory, tracker or registry; the suite it drives is the same
sandbox-only suite, whose `no_side_effects` fixture booby-traps subprocess,
socket, urllib and `os.system` for the migration under test.

Run:
    .venv/bin/python tools/mutation_test.py              # every mutant
    .venv/bin/python tools/mutation_test.py A C D        # a subset
    .venv/bin/python tools/mutation_test.py --list
    MUTANT=A .venv/bin/python -m pytest -p mutation_test # one, interactively
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Env var the plugin half reads. Unset (or empty) means "no mutation", so
#: `-p mutation_test` is a no-op on an ordinary run and the plugin can sit in
#: `addopts` without changing the green baseline.
MUTANT_ENV = "MUTANT"

#: Emoji this corpus uses as an informal keeper/cull marker in tab headings.
#: Only referenced by mutant E, which re-derives `status` from them.
_KEEPER = "\U0001f49a"  # 💚
_CULL = "\u2620\ufe0f"  # ☠️


# ------------------------------------------------------------- mutants ------
#
# Each mutant is `apply(monkeypatch_like)`: it takes an object exposing
# `setattr(target, name, value)` so the same body works under pytest's
# `monkeypatch` and under the plugin's session-scoped patcher.


def _mutant_a(mp):
    """`corrected_reading` always materialised from the template default.

    Invisible on five of six projects: the field is absent from their sources,
    so `null` is the correct migrated value there and this writer produces
    byte-identical output. On lantz it destroys the corpus's only
    human-confirmed transcription correction.
    """
    from breeding_tracker import tracker_migration as tm

    real = tm.build_plant_record

    def mutated(plant, schema):
        record, defaulted = real(plant, schema)
        if "corrected_reading" in schema:
            record["corrected_reading"] = schema["corrected_reading"].get("default")
            if "corrected_reading" not in defaulted:
                defaulted.append("corrected_reading")
        return record, defaulted

    mp.setattr(tm, "build_plant_record", mutated)


def _mutant_b(mp):
    """The one real `corrected_reading` copied onto every record.

    The mirror of A: a writer that preserved Ltz01's value by inventing one
    everywhere passes any check that only looks at the carrier record.
    """
    from breeding_tracker import tracker_migration as tm

    real = tm.migrate_tracker

    def mutated(tracker_path, *args, **kwargs):
        import json

        source = json.loads(Path(tracker_path).read_text(encoding="utf-8"))
        seed = next(
            (
                p["corrected_reading"]
                for p in source.get("plants", [])
                if p.get("corrected_reading")
            ),
            None,
        )
        inner = tm.build_plant_record

        def spread(plant, schema):
            record, defaulted = inner(plant, schema)
            if seed is not None:
                record["corrected_reading"] = seed
                if "corrected_reading" in defaulted:
                    defaulted.remove("corrected_reading")
            return record, defaulted

        mp.setattr(tm, "build_plant_record", spread)
        try:
            return real(tracker_path, *args, **kwargs)
        finally:
            mp.setattr(tm, "build_plant_record", inner)

    mp.setattr(tm, "migrate_tracker", mutated)


def _mutant_c(mp):
    """Plant ID upper-cased in the FILENAME only, not in the record.

    Deliberately the subtle version: every field still round-trips and the
    in-file `id` is untouched, so only a check that compares the real
    directory listing can see it. Harmless on the four all-upper rosters
    (`.upper()` is identity there); caught by spaced-paste's lowercase `sp`
    and by lantz's mixed-case `Ltz`.
    """
    _patch_filename_case(mp, str.upper)


def _mutant_d(mp):
    """Plant ID lower-cased in the FILENAME only, not in the record.

    The complement of C: harmless on spaced-paste, caught by the four
    all-upper rosters and by lantz. C and D intersect on lantz alone, which
    is the mixed-case uniqueness claim demonstrated rather than asserted.
    """
    _patch_filename_case(mp, str.lower)


def _patch_filename_case(mp, transform):
    """Rewrite only the stem of the plant file each `write_plant` targets."""
    from breeding_tracker import plant_markdown as pmd

    real = pmd.write_plant

    def mutated(path, data, schema=None):
        path = Path(path)
        return real(path.with_name(transform(path.stem) + path.suffix), data, schema)

    mp.setattr(pmd, "write_plant", mutated)


def _mutant_k(mp):
    """Plant IDs upper-cased in the RECORD as well as the filename.

    The blunt version of C, kept because it is a genuinely different fault:
    it corrupts `id` in the frontmatter too, so it must die far more widely
    than C does. A suite where C and K kill the same set has a check that is
    only looking at one of the two places an ID lives.
    """
    from breeding_tracker import tracker_migration as tm

    real = tm._plant_id
    mp.setattr(tm, "_plant_id", lambda plant, index: real(plant, index).upper())


def _mutant_e(mp):
    """`status` re-inferred from the tab-heading emoji instead of stored.

    Plausible-looking and wrong: lantz's Ltz07 is 💚-tagged but `culled`, and
    paloma-coma's PC04 is ☠️-tagged but `keeper`. Both records carry the
    later decision in `status`, which must win over anything re-derivable
    from the body.
    """
    from breeding_tracker import tracker_migration as tm

    real = tm.build_plant_record

    def mutated(plant, schema):
        record, defaulted = real(plant, schema)
        body = record.get("observation_log") or ""
        if _KEEPER in body:
            record["status"] = "keeper"
        elif _CULL in body:
            record["status"] = "culled"
        return record, defaulted

    mp.setattr(tm, "build_plant_record", mutated)


def _mutant_f(mp):
    """A `defaulted_fields` entry emitted for every record, always.

    True on 94 of the corpus's 95 plant records, so only lantz's Ltz01 — the
    sole record needing no template default at all — can see it.
    """
    from breeding_tracker import tracker_migration as tm

    real = tm.build_plant_record

    def mutated(plant, schema):
        record, defaulted = real(plant, schema)
        return record, defaulted or ["corrected_reading"]

    mp.setattr(tm, "build_plant_record", mutated)


def _mutant_g(mp):
    """Null-valued keys dropped instead of written as explicit `field: null`.

    A reader that falls back to the template default for a missing key then
    reports a plausible `None`, so the loss is invisible through the reader
    and visible only in the bytes.
    """
    from breeding_tracker import plant_markdown as pmd

    real = pmd.write_plant

    def mutated(path, data, schema=None):
        return real(
            path,
            {k: v for k, v in data.items() if v is not None},
            schema=schema,
        )

    mp.setattr(pmd, "write_plant", mutated)


def _mutant_h(mp):
    """`''` coerced to `None` on write.

    kibungan's `google_sheet_url`, and `photos_drive_url` on every
    spaced-paste and lantz plant, are the empty string while a sibling field
    is genuinely null — so the two must not be conflated in either direction.
    """
    from breeding_tracker import plant_markdown as pmd

    real = pmd.write_plant

    def mutated(path, data, schema=None):
        return real(
            path,
            {k: (None if v == "" else v) for k, v in data.items()},
            schema=schema,
        )

    mp.setattr(pmd, "write_plant", mutated)


def _mutant_i(mp):
    """Routing compiled case-sensitively instead of with `re.IGNORECASE`.

    Production compiles with IGNORECASE, so a case-locked matcher still
    routes the canonical spelling and silently drops the other half of
    Discord's traffic.
    """
    from breeding_tracker import migration_harness as mh

    mp.setattr(mh, "ROUTING_FLAGS", re.NOFLAG)


def _mutant_j(mp):
    """Registry-sourced routing fields fall back to the template default.

    Task 3.0 §8's highest-risk finding: `auto_create` and `plant_id_prefixes`
    live ONLY in `registry.json`. Undetectable on the three projects whose
    registry `auto_create` happens to equal the template default.
    """
    from breeding_tracker import tracker_migration as tm

    real = tm.build_project_record

    def mutated(tracker, registry_entry, schema):
        stripped = {
            k: v for k, v in registry_entry.items() if k not in ("auto_create",)
        }
        stripped["auto_create"] = schema["auto_create"].get("default")
        return real(tracker, stripped, schema)

    mp.setattr(tm, "build_project_record", mutated)


#: name -> (one-line description, apply function). Ordered; the letters match
#: the mutant tables in the Task 3.x reports.
MUTANTS: dict[str, tuple[str, callable]] = {
    "A": ("corrected_reading always materialised from the default", _mutant_a),
    "B": ("the one real correction copied onto every record", _mutant_b),
    "C": ("plant ID upper-cased in the FILENAME only", _mutant_c),
    "D": ("plant ID lower-cased in the FILENAME only", _mutant_d),
    "E": ("status re-inferred from the tab emoji", _mutant_e),
    "F": ("a defaulted_fields entry emitted for every record", _mutant_f),
    "G": ("null-valued keys dropped instead of written as null", _mutant_g),
    "H": ("'' coerced to None on write", _mutant_h),
    "I": ("routing compiled case-sensitively (no re.IGNORECASE)", _mutant_i),
    "J": ("registry-sourced auto_create falls back to the default", _mutant_j),
    "K": ("plant IDs upper-cased in the record as well", _mutant_k),
}


def apply_mutant(name: str, mp) -> None:
    """Apply mutant `name` through a monkeypatch-like `mp`."""
    try:
        _, fn = MUTANTS[name]
    except KeyError:
        raise SystemExit(
            f"unknown mutant {name!r}; known: {', '.join(MUTANTS)}"
        ) from None
    fn(mp)


# -------------------------------------------------------- pytest plugin -----


class _SessionPatcher:
    """The sliver of `monkeypatch` the mutants need, at session scope.

    pytest's own `monkeypatch` is function-scoped, and a mutant has to be live
    for the whole session (including collection-time imports), so this keeps
    the undo stack itself.
    """

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


_PATCHER = _SessionPatcher()


def pytest_configure(config):
    name = os.environ.get(MUTANT_ENV, "").strip()
    if not name:
        return
    apply_mutant(name, _PATCHER)
    config.stash  # noqa: B018 - touch stash so pytest keeps the plugin alive
    description = MUTANTS[name][0]
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"MUTANT {name} ACTIVE: {description}", bold=True)


def pytest_unconfigure(config):
    _PATCHER.undo()


# --------------------------------------------------------------- runner -----

_FAILED = re.compile(r"^FAILED (\S+)")
_PARAM = re.compile(r"\[([^\]]+)\]$")


def _run_suite(name: str, extra: list[str]) -> tuple[list[str], str]:
    """Run the whole suite with mutant `name` live; return (failures, tail)."""
    env = {**os.environ, MUTANT_ENV: name}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "mutation_test",
            "-p",
            "no:cacheprovider",
            "-q",
            "--no-header",
            "-rf",
            *extra,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**env, "PYTHONPATH": os.pathsep.join([str(REPO), str(REPO / "tools")])},
    )
    failures = [
        m.group(1) for line in proc.stdout.splitlines() if (m := _FAILED.match(line))
    ]
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return failures, tail


def _projects_of(failures: list[str]) -> list[str]:
    """The distinct parametrization ids among failing contract instances."""
    found = set()
    for nodeid in failures:
        if "test_project_migration_contract.py" not in nodeid:
            continue
        m = _PARAM.search(nodeid)
        if m:
            found.add(m.group(1))
    return sorted(found)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mutants", nargs="*", help="mutant names (default: all)")
    parser.add_argument("--list", action="store_true", help="list mutants and exit")
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        dest="extra",
        help="extra argument passed through to pytest (repeatable)",
    )
    args = parser.parse_args(argv)

    if args.list:
        for name, (description, _) in MUTANTS.items():
            print(f"{name}  {description}")
        return 0

    names = args.mutants or list(MUTANTS)
    unknown = [n for n in names if n not in MUTANTS]
    if unknown:
        parser.error(f"unknown mutant(s): {', '.join(unknown)}")

    survivors = []
    print(f"| mutant | change | killed by | contract parametrizations |")
    print("|---|---|---|---|")
    for name in names:
        failures, tail = _run_suite(name, args.extra)
        projects = _projects_of(failures)
        if not failures:
            survivors.append(name)
            killed = "**SURVIVED**"
        else:
            killed = f"{len(failures)} tests"
        print(
            f"| {name} | {MUTANTS[name][0]} | {killed} | "
            f"{', '.join(projects) if projects else '—'} |",
            flush=True,
        )
        print(f"<!-- {name}: {tail} -->", flush=True)

    if survivors:
        print(f"\nSURVIVING MUTANTS (holes in the suite): {', '.join(survivors)}")
        return 1
    print(f"\nAll {len(names)} mutants killed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
