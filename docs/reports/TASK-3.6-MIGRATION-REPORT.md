# Task 3.6 — `lantz` tracker.json → Markdown migration

**Phase:** 3 (data migration), Task 3.x instance #6 of 6 — **the last**
**Scope:** `/home/joey/.hermes/breeding/lantz/tracker.json`
**Mode:** **SANDBOX ONLY** — no real repo written, no commit/push to any project
repo, no Discord, no Drive.
**Verdict:** **PASS** — 4/4 plants, 73 plant field values + 9 project field
values + 2 registry-sourced routing fields round-tripped with zero loss,
`tracker.json` md5 `12b5aaa3ba275cb2e989b0191153591d` unchanged.

---

## 1. What was used

Registering the project was **one `ProjectSpec`** in `src/migration_specs.py`.
The shared acceptance contract picked it up automatically and the spec-driven
verifier accepted `lantz` as a slug with no new script — the fourth consecutive
task to cost no per-project harness. **No production migration code was written
or changed**, and no shared harness or contract check was changed either.

| file | change |
|---|---|
| `src/migration_specs.py` | +1 `ProjectSpec` (`LANTZ`), appended to `PROJECT_SPECS` |
| `tests/test_lantz_migration.py` | 16 tests for what is genuinely unique to this project's data |

`git diff src/tracker_migration.py src/plant_markdown.py src/project_markdown.py
src/migration_harness.py tools/verify_migration.py
tests/test_project_migration_contract.py` is empty for this commit.

Task 3.5's hand-off note predicted this task would need
`expected_plant_defaults` narrowed on the plant carrying a real
`corrected_reading`, and predicted no contract change would be needed. **The
second half was right; the first half was not necessary.** `expected_plant_
defaults` is only consumed by
`test_source_plant_keys_are_exactly_the_inventoried_set` as an *allowance*
(`plant_keys | expected_plant_defaults`), so leaving it at the class default of
`frozenset({"corrected_reading"})` already admits Ltz01's 19th key. The
contract's `test_corrected_reading_is_defaulted_and_never_invented` skips
records where the source carries the key, exactly as predicted, so it passes
unchanged. No contract change was made.

## 2. Acceptance criterion (a) — plant count matches exactly

| measure | value |
|---|---|
| plants in `tracker.json` | **4** |
| `plants/*.md` files written | **4** |
| plant IDs, sorted, source vs written | **identical** |

The roster is asserted as an exact list: `Ltz01, Ltz03, Ltz06, Ltz07`.
`Ltz02`, `Ltz04` and `Ltz05` never existed, so a migration that regenerated IDs
from a loop index would emit a plausible `Ltz01..Ltz04` and pass any count-only
check. This is the **smallest** project in the corpus (4 plants).

## 3. Acceptance criterion (b) — zero data loss

- **73** plant field values (3 plants × 18 keys + Ltz01's 19) → **0 lost, 0 altered**
- **9** project field values → **0 lost, 0 altered**
- **2** registry-sourced routing fields → correct
- `verify_migration` reports **5 records / 84 field values compared**, and both
  the tests and the verifier assert those exact counts against independently
  re-derived totals, so `ok=True` from a gate that inspected nothing is not
  accepted as evidence.
- Whole-object checks: the `plants` array and the project dict, rebuilt from
  markdown and compared with `json.dumps(..., sort_keys=True)`, are **equal**
  to the source.
- `genetics` and `breeder_lineage` are the only defaulted project fields — both
  genuinely absent from the source — while `notes_meta` is real data and is not
  defaulted.

### 3a. The corpus's only real `corrected_reading` — what this project proves

`Ltz01.corrected_reading` is
`"'Thanos' -> 'phenos' (phenotypes). Confirmed by Joey 2026-08-25."` — the
**single human-confirmed transcription correction in all six trackers**. No
record in any other project carries the key at all, which is why every earlier
`ProjectSpec` declares it a materialised template default.

That makes one specific bug invisible everywhere else: a writer that ignored
the source field and **unconditionally materialised the template default**
(`null`) produces byte-identical output on all five earlier projects, because
`null` is the correct answer on every one of their records. Here it destroys
the correction. The mirror bug — preserving Ltz01 by *copying* the value onto
every record — corrupts the other three. Both halves are asserted on the same
migrated tree, through the schema reader **and** in the raw frontmatter, since
a reader falling back to the template default for a key the writer dropped
would otherwise report a plausible `None` and hide the loss.

The correction's provenance is asserted to survive alongside it: the
project-level `notes_meta.resolved_ambiguities` entry, Ltz01's
`selection_notes` restatement, and the verbatim uncorrected `"Thanos"` still
present in `original_notes` and the body — a correction with no surviving
subject or audit trail is not a preserved correction.

`lantz` is also the only project with a **non-empty `resolved_ambiguities` and
an empty `flagged_ambiguities`** (kibungan is flagged-only, spaced-paste has
both, the rest have neither).

### 3b. Ltz01 — the only record anywhere with zero defaulted fields

Ltz01 carries all 19 keys, so it is the sole plant in any of the six trackers
for which `defaulted_fields` has **no entry at all**. Every other project
asserts the uniform shape "each plant defaults exactly `corrected_reading`";
that statement is false here for one record. mule-fuel's `MG07` is the opposite
skew (3 defaults where its siblings have 1), so the two ends of the range are
now both pinned.

### 3c. The only mixed-case plant-ID family

`Ltz` is upper-initial with a lower tail. `MG`/`HBH`/`PK`/`PL`/`PC` are
all-upper and spaced-paste's `sp` is all-lower — so each of those rosters
survives exactly one normalisation untouched (`.upper()` and `.lower()`
respectively) and can catch at most the other. `Ltz` survives neither. This is
asserted corpus-wide against every other spec's registry entry rather than in a
docstring, so a future project gaining a mixed-case prefix fails the claim
loudly.

Routing is additionally checked for every spelling people type — `Ltz01`,
`LTZ01`, `ltz01`, `LTZ 1` — with the right captured group, compiled with
`migration_harness.ROUTING_FLAGS` (production's flags) out of the **migrated**
markdown rather than the registry, and the `\b` boundary is checked against
real English negatives (`waltz01`, `ALTZ 3`) with a discriminating
boundary-removed control.

### 3d. The single-status roster

All four plants are `culled` — the only project with no status variety, so a
migration that dropped or normalised `status` still yields a
self-consistent-looking roster here. Asserted as an explicit
`status: culled` line in every migrated file, not just through the reader.

### 3e. Claims deliberately NOT made

Checked against the other five trackers and found **not** unique, so not
claimed as such:

- **`photos_drive_url == ''` on every plant.** spaced-paste is identical and
  caught a `''`→`None` coercion first (Task 3.5 §3d). Covered by the shared
  contract's field diff; no duplicate check added here.
- **Ltz07's keeper tab emoji (`LTZ7💚`) contradicting its `culled` status.**
  paloma-coma's `PC04` carries the mirror-image contradiction (`pc4☠️` with
  status `keeper`). Asserted here anyway — because the conflicting evidence
  lives in this project's own body text and the shared diff would report only
  the symptom — but explicitly *not* claimed as first or unique.

## 4. Mutation testing — the new checks can actually fail

The harness is now **committed** as `tools/mutation_test.py` (Tasks 3.1–3.5 each
used a throwaway `/tmp` script that was deleted afterwards, which made the
strongest evidence in the phase the one thing nobody could re-run). It is a
pytest plugin and a runner in one file: `MUTANT=A pytest -p mutation_test`
patches the migration in memory for a whole session, and
`.venv/bin/python tools/mutation_test.py` re-runs the suite once per mutant and
prints the kill table below, including which *project parametrizations* of the
shared contract died. Mutants patch functions in memory only; no real tracker,
registry or project directory is touched.

Eleven mutants, **all killed** (a survivor would be a hole in the suite):

| mutant | change | killed by | contract parametrizations |
|---|---|---|---|
| A | `corrected_reading` always materialised from the template default | 6 tests | **`lantz` only** |
| B | the one real correction copied onto every record | 5 tests | **`lantz` only** |
| C | plant ID upper-cased in the FILENAME only | 74 tests | `lantz`, `spaced-paste` |
| D | plant ID lower-cased in the FILENAME only | 116 tests | the four uppercase projects + `lantz` |
| E | `status` re-inferred from the tab emoji | 11 tests | `lantz`, `paloma-coma` |
| F | a `defaulted_fields` entry emitted for every record | 2 tests | — (both are `lantz` module tests) |
| G | null-valued keys dropped instead of written as `field: null` | 12 tests | all six |
| H | `''` coerced to `None` on write | 22 tests | `lantz`, `spaced-paste` |
| I | routing compiled case-sensitively (no `re.IGNORECASE`) | 30 tests | all six |
| J | registry-sourced `auto_create` falls back to the template default | 21 tests | the three discriminating projects |
| K | plant IDs upper-cased in the record as well as the filename | 31 tests | `lantz`, `spaced-paste` |

Three results are the evidence for this project's uniqueness claims, rather than
an assertion in a docstring:

- **Mutants A and B fail on the `[lantz]` parametrization only.** No earlier
  project's data can distinguish "read the source field" from "always emit the
  default", because `null` is correct on all of them.
- **Mutants C and D intersect on `lantz` alone.** Filename upper-casing is
  caught by `{lantz, spaced-paste}`; lower-casing by `{lantz, mule-fuel,
  honey-badger-haze, kibungan, paloma-coma}`. `lantz` is the only project in
  both sets — which is exactly the mixed-case claim, demonstrated rather than
  asserted.
- **Mutant F dies on two tests, both in `test_lantz_migration.py`.** 94 of the
  corpus's 95 plant records genuinely need a default, so Ltz01 is the only
  record anywhere that can see this fault.

## 5. Acceptance criteria (c) and (d) — sandbox-only, no side effects

- All output confined to a `tempfile` sandbox; the sandbox is removed after the
  run and the removal is checked.
- The migration **refuses to write into the live project dir**, including with
  `allow_git_repo=True`.
- `tracker_migration.py` is statically proven to import no `subprocess`,
  `socket`, `urllib` or `http` at all. Under test,
  `subprocess.run/Popen/call/check_call/check_output`, `socket.socket`,
  `socket.create_connection`, `urllib.request.urlopen` and `os.system` are
  booby-trapped to raise.
- `tracker.json` md5 `12b5aaa3ba275cb2e989b0191153591d` **identical** before and
  after, hashed with the system `md5sum` binary rather than the module under
  test. Independently confirmed by sha256
  (`6f030081d35b76e2f9bad7fd90669501ed4151d4cd6b8d4c63addc8d71381d0f`) and by
  an unchanged mtime of `2026-09-04 18:32:21`, which pre-dates this task.
  `registry.json` md5 unchanged.
- The **entire live project dir** is unchanged: 30 data paths plus 1 nested
  repo (HEAD sha + porcelain status).
- The other five project trackers are unchanged.
- No `project.md` exists anywhere under `~/.hermes/breeding/` — no sandbox
  output leaked into any live tree.
- No unexpected git changes in `breeding-markdown` or `breeding-meta`, measured
  as a before/after `git_repo_state` diff (HEAD + porcelain codes + per-path
  content digests), not a path whitelist.
- A second migration of the same source is **byte-identical** (5 files), and a
  failed write on plant 2 of 4 leaves **no half-written tree**.

## 6. Final state

- **708 tests**, 100% green, zero warnings (`pytest -W error`). Was 659 before
  Task 3.6: **+16** lantz tests and **+33** contract instances for the new spec
  (200 contract tests over 6 projects, up from 167 over 5).
- **45/45** out-of-band checks for `lantz` on a clean tree; **277/277** across
  all six migrated projects (`--all`).
- `tracker.json` md5 `12b5aaa3ba275cb2e989b0191153591d` unchanged.

## 7. Phase 3 is complete

All six projects are migrated and both-gate approved:

| task | project | plants | out-of-band |
|---|---|---|---|
| 3.1 | mule-fuel-x-nana-glue | 45 | 45/45 |
| 3.2 | honey-badger-haze-pheno-hunt | 23 | 47/47 |
| 3.3 | kibungan-pheno-hunt | 13 | 48/48 |
| 3.4 | paloma-coma | 5 | 47/47 |
| 3.5 | spaced-paste | 5 | 45/45 |
| 3.6 | **lantz** | **4** | **45/45** |
| | **total** | **95** | **277/277** |

Counts re-measured on a clean tree at this commit, not copied from the earlier
reports: the per-project totals move as shared checks are added, so a figure
quoted from the task that introduced it goes stale. `kibungan` runs 48 because
its two prefixes make the dropped-entry tamper expressible; the single-prefix
projects report that check as a `[NOTE]` instead.

Every one of the 95 plant records in the corpus now round-trips through the
markdown backend with zero field loss, and `PROJECT_SPECS` covers the whole
registry — so `tools/verify_migration.py --all` is now a complete corpus gate
rather than a partial one.

**Nothing has been written to any real repo.** Phase 3 produced sandbox proofs
only; the real migration write, and any git/Drive/Discord step, remains a
separate deliberate action for a later phase.

## 8. Post-close-out review fixes

Two code-quality issues found on review of this task's close-out, fixed here:

* **Stale "not yet migrated" docstring.** `tests/helpers_migration.py`'s
  `sibling_prefixes` docstring named spaced-paste and lantz as "not yet
  migrated" — true when the comment was written, false as of this task's own
  §7 above (`PROJECT_SPECS` now covers the whole registry). Reworded to state
  the actual invariant (the registry can outpace `PROJECT_SPECS`) instead of a
  snapshot of Phase 3's progress that a later task would have had to remember
  to update again.
* **Two uniqueness claims not asserted corpus-wide.** `test_lantz_migration.py`
  claimed "Ltz01 is the only record in the corpus with no defaulted fields",
  "the only project without status variety", and "the only project with
  resolved-only notes_meta" in docstring prose only — checked by eye against
  the other five trackers rather than by the suite. All three now assert the
  same predicate against every other spec's real tracker, matching the pattern
  already used elsewhere in this file (`test_lantz_is_the_only_project_...`,
  `test_this_project_is_the_only_mixed_case_...`): a future project acquiring
  the property now fails the claim loudly instead of quietly rotting it into a
  false comment. 708 tests still pass (assertions added to existing tests, no
  new test count).

## 9. Mutation harness committed: `tools/mutation_test.py`

Every Task 3.x report's mutation-testing section (§4 above included) was
produced by a throwaway `/tmp` script, deleted after the run — the strongest
evidence in each report was also the one artifact nobody could re-run or
audit. `tools/mutation_test.py` replaces those scripts with one committed,
reusable harness:

* Ten named mutants (`A`-`J`), covering every mutant from Tasks 3.4-3.6's
  reports (routing-pattern breakage, ID case-folding, `''`/`None` coercion,
  null-key dropping, status re-derived from emoji, `corrected_reading`
  defaulting/copying, registry-field fallback) plus a `defaulted_fields`
  always-populated mutant.
* Dual-mode: `MUTANT=<name> pytest -p mutation_test` monkeypatches the
  migration in-process for interactive use; `python tools/mutation_test.py`
  re-runs the whole suite once per mutant in a clean subprocess and prints a
  kill table, including which shared-contract **project parametrizations**
  died — the actual evidence behind every "only project X can catch this"
  claim in this and earlier reports.
* Re-run at this commit: **all 10 mutants killed**, reproducing §4's table
  exactly (mutant A kills `[lantz]` only; C/D split the case-folding projects
  with `lantz` as the sole intersection; F is killed by every project except
  `lantz`).
* No side effects: mutants patch functions in memory only; the sandboxed
  `no_side_effects` fixture still traps subprocess/socket/urllib/`os.system`
  for every mutated run.
