# Task 3.4 — `paloma-coma` tracker.json → Markdown migration

**Phase:** 3 (data migration), Task 3.x instance #4 of 6
**Scope:** `/home/joey/.hermes/breeding/paloma-coma/tracker.json`
**Mode:** **SANDBOX ONLY** — no real repo written, no commit/push to any project
repo, no Discord, no Drive.
**Verdict:** **PASS** — 5/5 plants, 90 plant field values + 11 project field
values + 2 registry-sourced routing fields round-tripped with zero loss,
`tracker.json` md5 `4e59e7b1896f885767824bbacbcef437` unchanged.

---

## 1. What was used

Registering the project was **one `ProjectSpec`** in `src/migration_specs.py`.
The shared acceptance contract picked it up automatically and the spec-driven
verifier accepted `paloma-coma` as a slug with no new script — the second
consecutive task to cost no per-project harness. No production migration code
was written or changed: `git diff src/tracker_migration.py
src/plant_markdown.py src/project_markdown.py` is empty for this commit.

| file | change |
|---|---|
| `src/migration_specs.py` | +1 `ProjectSpec` (`PALOMA_COMA`), appended to `PROJECT_SPECS` |
| `tests/test_project_migration_contract.py` | +2 shared checks: behavioural ID routing, lifted out of Task 3.3's kibungan-only module (§4) |
| `tests/test_kibungan_migration.py` | the generic half of its routing tests removed, now inherited from the contract; only the `(?i)`/`[-#]`/lookbehind specifics remain |
| `tests/test_paloma_coma_migration.py` | 9 tests for what is genuinely unique to this project's data |
| `tools/verify_migration.py` | the same behavioural routing check, out-of-band, for every project |

## 2. Acceptance criterion (a) — plant count matches exactly

| measure | value |
|---|---|
| plants in `tracker.json` | **5** |
| `plants/*.md` files written | **5** |
| plant IDs, sorted, source vs written | **identical** |

The roster is asserted as an exact list: `PC01, PC04, PC05, PC06, PC07`. The
gap is at the **front** — `PC02` and `PC03` never existed — so a migration that
regenerated IDs from a loop index would emit a plausible `PC01..PC05` and pass
any count-only check. Cross-checked against Task 3.0's inventory.

## 3. Acceptance criterion (b) — zero data loss

- **90** plant field values (5 plants × 18 keys) → **0 lost, 0 altered**
- **11** project field values → **0 lost, 0 altered**
- **2** registry-sourced routing fields → correct
- `verify_migration` reports **6 records / 103 field values compared**, and both
  the tests and the verifier assert those exact counts against independently
  re-derived totals, so `ok=True` from a gate that inspected nothing is not
  accepted as evidence.
- Whole-object checks: the `plants` array and the project dict, rebuilt from
  markdown and compared with `json.dumps(..., sort_keys=True)`, are **equal**
  to the source.
- `corrected_reading` is the **only** defaulted plant field, on all 5 records;
  no project field was defaulted at all.

### 3a. The all-nullable-fields-empty case — what this project proves

**All ten** nullable plant columns — `sex`, `germ_date`, `veg_start`,
`flower_flip`, `harvest_date`, `vigor`, `structure`, `terpene_notes`, `issues`
and `selection_notes` — are `null` on **every** plant. That combination exists
in no earlier project: mule-fuel's `terpene_notes` is populated, and
honey-badger and kibungan both carry `selection_notes` on at least one plant.
50 of this project's 90 plant field values are null. Only
`id`/`cross`/`status`/`photos`/`photo_count`/`photos_drive_url`/notes carry
data.

That makes it the first data able to catch a writer that skipped an
entirely-null column, or a reader that only materialised keys it had seen carry
a value. Both round-trip every earlier project cleanly and lose ten fields per
plant here.

Two layers, deliberately:

| layer | check |
|---|---|
| reader | every one of the ten keys is present and **`is None`** on all 5 plants — `None` explicitly, since `''`, `[]` and `0` are all falsy and all wrong |
| bytes | the frontmatter literally contains `field: null` for each |

The byte-level layer is not redundant: reading through the schema fills a
*missing* key with the template default, which is also `None`, so a reader-only
check cannot distinguish a preserved null from a silently re-invented one.
Mutation-confirmed — dropping null-valued keys in `write_plant` leaves the
reader-level check green and fails only the byte-level one.

### 3b. Other per-project facts, each asserted

| fact | why it matters |
|---|---|
| `notes_meta.migration_note` enumerates the five source tabs **by plant ID** | unlike honey-badger's note (stale in the source, preserved anyway) this one is checkable against the roster, and it records a Drive misfiling that was nearly missed — the prose is provenance |
| observation logs carry `☠️` (U+2620 U+FE0F) on PC01/PC04/PC06 and `’` (U+2019) on PC01/PC05/PC06 | non-ASCII in a markdown body under YAML frontmatter; an ASCII-escaping dump or a mis-set encoding mangles it while everything still parses |
| `original_notes` is a substring of `observation_log` on every plant | the two overlap by construction; truncating either independently breaks the relationship, which a per-field equality check alone would not notice |
| `google_sheet_id` null while `google_sheet_url` is `''` | same null/empty-string distinction kibungan introduced; covered by the shared contract |
| statuses are `culled`/`keeper` only, `photo_count == len(photos)` on every plant | the whole non-null payload |

## 4. The behavioural routing check, generalised (the shared-contract change)

Task 3.3 wrote "compile the migrated patterns and actually route the real IDs"
as a **kibungan-only** test, because two prefixes made mis-routing visible
there first. Nothing about the property is multi-prefix, and leaving it there
was the same duplication-by-omission that let Tasks 3.1 and 3.2 drift apart —
the other four single-prefix projects were being checked only for *string
equality* against `registry.json`.

Equality is the weaker property. It proves the migration copied the registry
faithfully; it says nothing about whether the result routes anything. Two
generic checks now run for **every** project, compiled out of the **migrated
markdown**:

1. **`..._still_route_this_projects_real_plant_ids`** — each pattern matches
   exactly its own family's real IDs and no other family's, and every real ID
   is routed by **exactly one** pattern (which also catches a cross-family
   collision, something no single-prefix project could previously express).
2. **`..._route_ids_embedded_in_free_text`** — the patterns exist to find IDs
   in Discord prose, so `checked <ID> today, looking good` must match *and the
   captured group must be the right number* (the monitor uses the group to pick
   the plant). The negative — `X<ID>` must **not** match — is what proves the
   boundary construct survived rather than being quietly dropped.

The same check was added to `tools/verify_migration.py`, so it is also proven
out-of-band for all four projects.

Kibungan's module keeps only what its data alone can exercise: the `(?i)`
inline flag against genuinely lowercase text (`pk-7`), the `[-#]?\s*` separator
class, and the `(?<![A-Z0-9])` lookbehind against an alphanumeric neighbour
(`SPK12`) rather than the contract's generic `X` prefix. Its dropped-second-
prefix tamper also stays, being genuinely multi-prefix.

**Mutation-confirmed on paloma-coma**, whose single `\bPC[\s\-]?(\d{1,2})\b`
was previously covered by equality alone: with the registry pattern perturbed
to a plausible-looking but broken `\bPC[\s\-]?(\d{1,2}3})\b`, the migrated
markdown still compares **equal** to the registry (equality check green) while
the pattern routes **zero** of the five real IDs — caught only by the lifted
behavioural check.

### 4a. Three gaps in the lifted check, closed after review

Reviewing the lifted check against production (`breeding_core._compile_prefixes`
and `extract_plant_ids_*`) found it asserting **less than production does** in
three places. Each was mutation-confirmed **MISSED by the check as lifted** and
**CAUGHT after the fix**:

| # | gap | the mutation it missed |
|---|---|---|
| 1 | **no cross-project collision test** — the check only proved a project's patterns unambiguous *among themselves*, but production routes one Discord message against the **whole registry** (`breeding_core`'s registry validator rejects a duplicated prefix for exactly this reason) | a sibling pattern widened during migration, `\bPL` → `\bP[A-Z]?`, routes its own family fine and passes on **both** projects in isolation while silently stealing every `PC..` message from paloma-coma |
| 2 | **the separator class was never exercised** — every live pattern carries one (`[\s\-]?`, `\s*[-#]?\s*`) and the free-text probe only used the bare `PC01` spelling | eating the class, `\bPC[\s\-]?` → `\bPC`, keeps every assertion green while `PC 01` and `PC-01` — the spellings people actually type — stop routing |
| 3 | **wrong compile flags** — production compiles with `re.IGNORECASE`; the check compiled with none, so it tested a *stricter* matcher than the one that runs | a scoped `(?-i:\bPC)` re-locks the prefix's case: green under no flags, drops half the real traffic in production |

The logic is now **one function**, `migration_harness.routing_failures`, used
verbatim by the contract suite **and** by `tools/verify_migration.py`, so the
two copies that Task 3.4 created cannot drift again. It is unit-tested in
`tests/test_routing_checks.py` on synthetic registry entries where each failure
mode is constructed deliberately, rather than only against real data that
happens to be healthy.

Flag parity is not merely asserted as a constant: `ROUTING_FLAGS ==
re.IGNORECASE` is checked against `breeding_core.py`'s **source text** (read
statically — importing the monitor would pull in its Discord/Drive machinery,
which this sandbox-only suite must never do), so the contract cannot silently
outlive the matcher it mirrors.

Both new tampers are also asserted as **discriminating cases** in the contract
and in the verifier — a widened pattern *is* reported as a collision, a
stripped separator class *is* reported — so neither check can degrade into a
vacuous pass on data that never had the construct.

## 5. Acceptance criteria (c) + (d) — sandbox-only, no real side effects

Inherited whole from the shared contract, all now running against this project:
`tracker.json` and `registry.json` md5s unchanged; the entire live
`~/.hermes/breeding/paloma-coma/` tree fingerprinted before/after (volatile
paths excluded, nested repo HEAD+status checked instead); the other five
projects' trackers hashed before/after; static proof that
`tracker_migration.py` imports no subprocess/socket/urllib/http; runtime
booby-traps on `subprocess.*`, `socket.*`, `urllib.request.urlopen` and
`os.system`; an `os.open` write-path spy asserting every write landed inside
the sandbox; and the destination guard refusing the live dir both plainly and
with `allow_git_repo=True`. The sandbox is a pytest `tmp_path`, removed after
each run.

`tracker.json` md5 `4e59e7b1896f885767824bbacbcef437` — identical before and
after, measured with the system `md5sum` binary.

## 6. Test suite and independent verification

| | tests |
|---|---|
| before this task | 527 |
| shared contract (2 new checks × 4 projects, +8; paloma-coma inherits the existing 27 × 1, +27) | +35 |
| `tests/test_paloma_coma_migration.py` (new) | +9 |
| `tests/test_kibungan_migration.py` (generic routing check removed) | −1 |
| **after Task 3.4 as first written** | **570 passed, 0 failed** |
| §4a: `tests/test_routing_checks.py` (new unit tests for the shared check) | +15 |
| §4a: shared contract, cross-project collision check × 4 projects | +4 |
| **after** | **589 passed, 0 failed** (zero warnings, `filterwarnings = error`) |

`tools/verify_migration.py --all`: **167/167 checks PASSED** on a clean tree
(159 before §4a; the 8 new are the collision, separator and flag-parity checks
across the four projects). Per project: mule-fuel 40, honey-badger 42,
kibungan 43, paloma-coma 42.

## 7. What was NOT done (deliberately)

- No real project repo was created, written to, committed to, or pushed.
- No production migration code changed.
- The remaining 2 projects (spaced-paste, lantz) are untouched; this is Task
  3.x instance 4 of 6.
- Promoting this migration to a real repo remains a separate, deliberate step;
  Phase 5's cutover re-runs the migration fresh rather than reusing this
  sandbox snapshot.
