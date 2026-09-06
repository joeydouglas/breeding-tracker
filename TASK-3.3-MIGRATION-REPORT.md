# Task 3.3 — `kibungan-pheno-hunt` tracker.json → Markdown migration

**Phase:** 3 (data migration), Task 3.x instance #3 of 6
**Scope:** `/home/joey/.hermes/breeding/kibungan-pheno-hunt/tracker.json`
**Mode:** **SANDBOX ONLY** — no real repo written, no commit/push to any project
repo, no Discord, no Drive.
**Verdict:** **PASS** — 13/13 plants, 234 plant field values + 11 project field
values + 2 registry-sourced routing fields round-tripped with zero loss,
`tracker.json` md5 `c1bb1e3bc31ec2f3ae0c0601e5a59647` unchanged.

---

## 1. What was used, and what the harness cost

This is the first task to run entirely on the shared harness extracted after
Task 3.2. Registering the project was **one `ProjectSpec`** in
`src/migration_specs.py`; the 27-check shared acceptance contract picked it up
automatically and the spec-driven verifier accepted `kibungan-pheno-hunt` as a
slug with no new script. No production migration code was written or changed —
`git diff src/tracker_migration.py src/plant_markdown.py src/project_markdown.py`
is empty for this commit, which is the point: three projects with materially
different data now share one implementation.

| file | change |
|---|---|
| `src/migration_specs.py` | +1 `ProjectSpec` (`KIBUNGAN`), appended to `PROJECT_SPECS` |
| `tests/test_kibungan_migration.py` | 12 tests for what is genuinely unique to this project's data |
| `tools/verify_migration.py` | +1 tamper case the earlier projects' data could not express (§3b) |

For contrast, Task 3.2 added ~700 lines of duplicated acceptance module plus a
~450-line verifier copy. Task 3.3 added 40 lines of spec and no verifier copy.

## 2. Acceptance criterion (a) — plant count matches exactly

| measure | value |
|---|---|
| plants in `tracker.json` | **13** |
| `plants/*.md` files written | **13** |
| plant IDs, sorted, source vs written | **identical** |

The roster is asserted as an exact list, not a count:
`PK01, PK03, PK04, PK07, PK09, PK10, PK11, PK12, PK14, PK19, PL05, PL06, PL15`
— non-contiguous in **both** families (PK skips eight numbers; PL is 05/06/15),
so a dropped or renumbered record fails on identity.

## 3. Acceptance criterion (b) — zero data loss

- **234** plant field values (13 plants × 18 keys) → **0 lost, 0 altered**
- **11** project field values → **0 lost, 0 altered**
- **2** registry-sourced routing fields → correct (§3a, §3b)
- `verify_migration` reports **14 records / 247 field values compared**, and
  both the tests and the verifier assert those exact counts against
  independently re-derived totals, so `ok=True` from a gate that inspected
  nothing is not accepted as evidence.
- Whole-object checks: the `plants` array and the project dict, rebuilt from
  markdown and compared with `json.dumps(..., sort_keys=True)`, are **equal**
  to the source.
- `corrected_reading` is the **only** defaulted plant field, on all 13 records;
  no project field was defaulted at all (`defaulted_fields["project"] == []`),
  the first project where that set is empty.

### 3a. The multi-prefix case — what this project proves that the first two could not

`registry.json` gives this project **two** plant-ID prefixes, `PK` and `PL`, for
one landrace population (the tracker's own `flagged_ambiguities` explains why:
likely two seed packs of the same landrace, not two crosses). Every project
migrated before this one had exactly one prefix, so a migration that read
`plant_id_prefixes[0]`, or flattened the list to a single mapping, would have
passed Tasks 3.1 and 3.2 unnoticed and then silently stopped routing every `PL`
note in production — three of thirteen plants here.

The tests do not stop at string equality. The patterns are compiled **out of
the migrated markdown** and executed:

| check | result |
|---|---|
| `PK` pattern matches | exactly the 10 PK IDs |
| `PL` pattern matches | exactly the 3 PL IDs |
| cross-family (`PK` vs `PL05`, `PL` vs `PK01`) | no match |
| lowercase free text `checked pk-7 today` | matches, group = `7` |
| `PK #12 stretching` | matches, group = `12` |
| lookbehind negative `SPK12` | no match |

These patterns are also the first to carry `(?i)` and a `(?<![A-Z0-9])`
lookbehind — `[`, `]`, `(`, `)`, `?`, `<`, `!`, `#`, `*` and backslashes in one
YAML scalar, versus the plain `\bXX[\s\-]?(\d{1,2})\b` of the earlier projects.
They survive byte-exact:

```
(?i)(?<![A-Z0-9])PK\s*[-#]?\s*0*(\d{1,3})(?!\d)
(?i)(?<![A-Z0-9])PL\s*[-#]?\s*0*(\d{1,3})(?!\d)
```

Mutation-checked to confirm the behavioural assertions are not decorative:
stripping `(?i)` from the migrated file leaves the ID list routing perfectly
while `checked pk-7` stops matching — caught only by the free-text test, not by
the ID test.

### 3b. A tamper the earlier projects' data could not express

The shared gate already blanks `plant_id_prefixes` to `[]` and requires
rejection. On a single-prefix project that is the only expressible tamper, and
it is coarse: it cannot distinguish a gate that compares the list's *contents*
from one that merely checks it is non-empty.

With two prefixes the realistic regression is **losing one entry** — the list
stays non-empty and stays correct for ten of thirteen plants. That case is now
in both the per-project tests and `tools/verify_migration.py`, which adds it
automatically for any project with more than one prefix and prints a `[NOTE]`
for the projects that cannot express it rather than passing silently. Verified:
the dropped-entry tamper is rejected (`ok=False`, `plant_id_prefixes` flagged),
and `project.md` is restored and re-verified clean afterwards.

### 3c. Other data shapes new to this project

* **`google_sheet_url` is `''` while `google_sheet_id` is `null`.** The first
  project where the empty string and null appear side by side, so a reader that
  normalised one into the other round-trips cleanly on mule-fuel and
  honey-badger and corrupts this project. Both survive distinctly, and the
  serialised form is asserted to be `google_sheet_url: ''`.
* **`notes_meta` with real content** — non-null `source_doc` and a one-item
  `flagged_ambiguities` (empty on both earlier projects). It is the human
  record of *why* two prefixes share one project; it survives JSON-equal.
* **Three plants carry a "Review and confirm." selection note** whose text
  disagrees with the recorded status (e.g. PK19 reads as a cull but is
  `active`). Migration preserves both verbatim — resolving a pending human
  decision during a data move would be data loss.
* All 13 plants share the one project-level photos folder with `photo_count: 1`;
  a migration that de-duplicated repeated values or hoisted them to the project
  record would be caught.

## 4. Acceptance criteria (c) and (d) — sandbox-only, no real side effects

Inherited whole from the shared contract, with nothing weakened:

- `tracker.json` md5 **`c1bb1e3bc31ec2f3ae0c0601e5a59647`** before and after,
  hashed by the system `md5sum` binary, not the module under test.
- `registry.json` md5 unchanged.
- The **entire** live project dir unchanged — 41 data paths plus the nested
  `dashboard/` repo's HEAD and porcelain status.
- The other five project trackers unchanged.
- Every write observed through an `os.open` spy landed inside the sandbox.
- `migrate_tracker` raises `SandboxViolationError` for the live dir, including
  with `allow_git_repo=True`, and leaves no directory behind.
- A simulated `OSError` on plant 6 of 13 leaves no half-written tree.
- `subprocess.run/Popen/call/check_call/check_output`, `socket.socket`,
  `socket.create_connection`, `urllib.request.urlopen` and `os.system` are all
  booby-trapped during every migration in the suite; none fired.
- Static proof: `tracker_migration.py` contains no subprocess/socket/urllib/
  http/requests/smtplib import and no `os.system`/`os.popen`.
- Both git repos (`breeding-markdown`, `breeding-meta`) show no unexpected
  change against a full HEAD + porcelain + per-path sha256 baseline.
- The migration is byte-identical across two runs (14 files compared).

## 5. Evidence

| gate | result |
|---|---|
| `pytest` (whole suite) | **527 passed**, 0 warnings (`filterwarnings = error`) — was 488 |
| new tests | +39 (27 shared contract cases now parametrized over this project, +12 project-specific) |
| `tools/verify_migration.py kibungan-pheno-hunt` | **39/39 checks passed** |
| `tools/verify_migration.py --all` | **113/113 checks passed** across all three projects |

The final acceptance run was made on a clean tree, without
`--allow-dirty-baseline`, so the pre-run cleanliness claim is made in full.
