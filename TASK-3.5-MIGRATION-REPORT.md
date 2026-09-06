# Task 3.5 — `spaced-paste` tracker.json → Markdown migration

**Phase:** 3 (data migration), Task 3.x instance #5 of 6
**Scope:** `/home/joey/.hermes/breeding/spaced-paste/tracker.json`
**Mode:** **SANDBOX ONLY** — no real repo written, no commit/push to any project
repo, no Discord, no Drive.
**Verdict:** **PASS** — 5/5 plants, 90 plant field values + 9 project field
values + 2 registry-sourced routing fields round-tripped with zero loss,
`tracker.json` md5 `dee45e00a1ae55cfa71463f2a45ac358` unchanged.

---

## 1. What was used

Registering the project was **one `ProjectSpec`** in `src/migration_specs.py`.
The shared acceptance contract picked it up automatically and the spec-driven
verifier accepted `spaced-paste` as a slug with no new script — the third
consecutive task to cost no per-project harness. **No production migration code
was written or changed**, and no shared harness or contract check was changed
either: this is the first Task 3.x instance whose entire diff is one spec plus
one per-project test module.

| file | change |
|---|---|
| `src/migration_specs.py` | +1 `ProjectSpec` (`SPACED_PASTE`), appended to `PROJECT_SPECS` |
| `tests/test_spaced_paste_migration.py` | 18 tests for what is genuinely unique to this project's data |

`git diff src/tracker_migration.py src/plant_markdown.py src/project_markdown.py
src/migration_harness.py tools/verify_migration.py
tests/test_project_migration_contract.py` is empty for this commit.

## 2. Acceptance criterion (a) — plant count matches exactly

| measure | value |
|---|---|
| plants in `tracker.json` | **5** |
| `plants/*.md` files written | **5** |
| plant IDs, sorted, source vs written | **identical** |

The roster is asserted as an exact list: `sp01, sp02, sp03, sp05, sp06`.
`sp04` never existed, so a migration that regenerated IDs from a loop index
would emit a plausible `sp01..sp05` and pass any count-only check.

## 3. Acceptance criterion (b) — zero data loss

- **90** plant field values (5 plants × 18 keys) → **0 lost, 0 altered**
- **9** project field values → **0 lost, 0 altered**
- **2** registry-sourced routing fields → correct
- `verify_migration` reports **6 records / 101 field values compared**, and both
  the tests and the verifier assert those exact counts against independently
  re-derived totals, so `ok=True` from a gate that inspected nothing is not
  accepted as evidence.
- Whole-object checks: the `plants` array and the project dict, rebuilt from
  markdown and compared with `json.dumps(..., sort_keys=True)`, are **equal**
  to the source.
- `corrected_reading` is the **only** defaulted plant field, on all 5 records.
  `genetics` and `breeder_lineage` are the only defaulted project fields — both
  genuinely absent from the source — while `notes_meta` is real data and is not
  defaulted. That combination exists on no earlier project (mule-fuel defaults
  all three; the other three default none), so the spec pins it.

### 3a. The lowercase-ID case — what this project proves first

This is the **first project with a lowercase plant-ID family**: the registry
prefix is `sp` and the IDs are `sp01`..`sp06`. MG, HBH, PK/PL, PC and Ltz are
all uppercase-initial, so until now nothing in the corpus could tell an
ID-normalising migration from a correct one. Case is load-bearing in three
places here:

1. **The filename.** Every shared field check locates a record by building
   `plants/<id>.md`. On a case-insensitive filesystem `SP01.md` answers to
   `sp01.md`, so a migration that upper-cased IDs while writing passes the
   entire shared field-diff and produces a roster that no longer matches the
   source on a case-sensitive one. `test_plant_filenames_preserve_id_case_
   exactly` compares against the real directory listing instead.
2. **The `id` field inside the record**, asserted both through the schema
   reader and against the raw frontmatter, since a YAML dump that re-quoted or
   re-cased the value is invisible to the reader.
3. **The routing pattern.** Production compiles with `re.IGNORECASE` and the
   canonical spelling here is the *lower*-case one, so `SP01`/`Sp 3` — what
   people actually type — must route to the same plant with the same captured
   number.

### 3b. The two-character prefix — the boundary is doing real work

`sp` is the **shortest prefix in the corpus and the only one that is a common
English bigram**. The shared routing check proves the pattern rejects one
synthetic leading character (`Xsp01`); this is the only project where the
negative case is real English. `wasp01 looks great`, `crisp 01 leaves`,
`esp 5 was fine` and `gasp-01` are asserted not to match, compiled with
production's flags out of the **migrated** markdown. The check is confirmed
discriminating: with `\b` stripped from the same pattern, `wasp01` does match.

### 3c. The unsorted source array — positional pairing made visible

`tracker.json` stores its plants as **`sp06, sp01, sp02, sp03, sp05`** — the
first project where array order and sorted-ID order differ. Every earlier
tracker is stored in sorted order, so a migration that paired payloads
positionally against a sorted roster produced byte-identical output on all four
and passed. Here it writes sp06's payload into `sp01.md`.

Asserted on payload that is unique per record: `sp06` is the only plant
carrying `selection_notes`, and each plant's `observation_log` names its own
source tab (`tab: sp1`, `tab: sp2`, …), so a shuffled roster is visible
record-by-record rather than only in aggregate.

### 3d. The empty-string plant field

`photos_drive_url` is `""` on all five plants — the **first project where a
plant-level field is the empty string** rather than a URL or `None`
(kibungan's `""` was at project level, on `google_sheet_url`). `''` and `None`
are both falsy, so a reader coercing one to the other round-trips every earlier
project cleanly and corrupts all five records here. Asserted through the schema
reader *and* in the raw frontmatter (`photos_drive_url: ''`, and explicitly
**not** `: null`), because reading a missing key would return the template
default and hide the difference.

Nine of the ten nullable columns are additionally null on every plant, asserted
as explicit `field: null` in the bytes — and this is the one project where `''`
is a real, *different* value on a neighbouring field, so conflating them is a
live failure rather than a stylistic one.

### 3e. Provenance and non-ASCII

`notes_meta.migration_note` records that the original build read only the
default Doc tab and **missed four of the five plants**, and the ambiguity lists
record two facts Joey confirmed by hand (DDU = Dulce de Uva; the NG parent is
the Mule Fuel cross's Nana Glue). `sp06`'s status is `active` — the one record
whose status was *not* inferred from a tab emoji, and a flagged, still-open
ambiguity — so a migration normalising statuses to the keeper/culled pair would
erase it. The tab headings carry `☠️` (U+2620 U+FE0F) and `💚` (U+1F49A, a
**non-BMP astral** character, the first in the corpus) inside a markdown body
under YAML frontmatter; both are asserted to survive byte-for-byte.

## 4. Mutation testing — the new checks can actually fail

Every claim above was confirmed discriminating by running four mutants of the
migration against the suite (`MUTANT=… pytest -p mutate`, an out-of-tree plugin
that monkeypatches `tracker_migration`; not committed):

| mutant | change | killed by |
|---|---|---|
| A | plant IDs upper-cased while writing | 11 spaced-paste tests |
| B | filename taken from an index into a *sorted* roster (positional pairing) | 4 spaced-paste tests |
| C | `''` coerced to `None` on write | `test_the_empty_string_survives_as_an_empty_string_not_as_null` |
| E | entirely-null fields omitted from the record | `test_the_nine_always_null_fields_survive_as_explicit_nulls` |

Run against the **shared contract** instead, mutants B and C fail on the
`[spaced-paste]` parametrization **only** — no earlier project's data can see
them. That is the evidence for this project's uniqueness claims, rather than an
assertion in a docstring.

## 5. Acceptance criteria (c) and (d) — sandbox-only, no side effects

- All output confined to a `tempfile` sandbox; the sandbox is removed after the
  run and the removal is checked.
- The migration **refuses to write into the live project dir**, including with
  `allow_git_repo=True`.
- `tracker_migration.py` is statically proven to import no `subprocess`,
  `socket`, `urllib` or `http` at all. Under test, `subprocess.run/Popen/call/
  check_call/check_output`, `socket.socket`, `socket.create_connection`,
  `urllib.request.urlopen` and `os.system` are booby-trapped to raise.
- `tracker.json` md5 `dee45e00a1ae55cfa71463f2a45ac358` **identical** before and
  after, hashed with the system `md5sum` binary rather than the module under
  test. `registry.json` md5 unchanged.
- The **entire live project dir** is unchanged: 34 data paths plus 1 nested repo
  (HEAD sha + porcelain status).
- The other five project trackers are unchanged.
- No unexpected git changes in `breeding-markdown` or `breeding-meta`,
  measured as a before/after `git_repo_state` diff (HEAD + porcelain codes +
  per-path content digests), not a path whitelist.
- A second migration of the same source is **byte-identical** (6 files), and a
  failed write on plant 2 of 5 leaves **no half-written tree**.

## 6. Final state

- **656 tests**, 100% green, zero warnings (`pytest -W error`). Was 606: +18
  spaced-paste tests, +32 contract instances for the new spec.
- **45/45** out-of-band checks for `spaced-paste` on a clean tree;
  **232/232** across all five migrated projects (`--all`).
- `tracker.json` md5 `dee45e00a1ae55cfa71463f2a45ac358` unchanged.

## 7. Note for Task 3.6 (`lantz`, the last project)

`lantz` is the only project left, and it is the one holding the corpus's single
real `corrected_reading` value — the field every spec so far has declared a
materialised template default. Its `ProjectSpec` will therefore need
`expected_plant_defaults` narrowed on the plant(s) that carry a real value, and
`test_corrected_reading_is_defaulted_and_never_invented` in the shared contract
already handles that correctly (it skips plants where the key is present in the
source), so no contract change should be needed.
