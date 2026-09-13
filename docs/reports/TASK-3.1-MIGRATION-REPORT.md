# Task 3.1 — `mule-fuel-x-nana-glue` tracker.json → Markdown migration

**Phase:** 3 (data migration), Task 3.x instance #1 of 6
**Scope:** `/home/joey/.hermes/breeding/mule-fuel-x-nana-glue/tracker.json`
**Mode:** **SANDBOX ONLY** — no real repo written, no commit/push to any project
repo, no Discord, no Drive.
**Verdict:** **PASS** — 45/45 plants, 808 plant field values + 8 project field
values round-tripped with zero loss, `tracker.json` md5 unchanged.

---

## 1. What was built

| file | purpose |
|---|---|
| `src/tracker_migration.py` | the migration itself: `migrate_tracker()`, `verify_migration()`, sandbox guard |
| `tests/test_tracker_migration.py` | 41 unit tests (synthetic fixtures, guards, failure modes) |
| `tests/test_mule_fuel_migration.py` | 19 acceptance tests against the **real** tracker |
| `tools/verify_mule_fuel_migration.py` | out-of-band verifier that re-derives every claim independently of the test suite |

`migrate_tracker()` writes `<out>/project.md` + `<out>/plants/<ID>.md` using
Phase 1's `write_project`/`write_plant`. It performs **no** git, network,
Discord or Drive operation — that is enforced, not just intended (§4).

## 2. Acceptance criterion (a) — plant count matches exactly

| measure | value |
|---|---|
| plants in `tracker.json` | **45** |
| `plants/*.md` files written | **45** |
| plant IDs, sorted, source vs written | **identical** |

`MG01`–`MG08`, `MG10`–`MG46` (`MG09` does not exist in the source; the
migration reproduces the gap rather than renumbering).

Cross-checked against Task 3.0's inventory, which recorded 45 for this project
as part of its 95-plant total.

## 3. Acceptance criterion (b) — zero data loss, diffed against Task 3.0

Not a spot check of "the fields Revision 1 happened to list" — every key/value
in the source JSON is compared:

- **808** plant field values compared → **0 lost, 0 altered**
- **8** project field values compared → **0 lost, 0 altered**
- Reconstructing the whole `plants` array from the 45 markdown files and
  `json.dumps(..., sort_keys=True)`-comparing it to the source array: **equal**
- Same whole-object comparison for the project record: **equal**

Guard tests also assert the source's key sets still *equal* Task 3.0's
inventoried sets (18 plant keys, 9 top-level keys), so the migration fails
loudly if the tracker drifts rather than silently migrating unknown fields.

### 3a. Specific inventory hazards, each explicitly covered

| Task 3.0 finding | handling | test |
|---|---|---|
| §8 `auto_create`/`plant_id_prefixes` exist only in `registry.json` | sourced from the registry entry, which **overrides** any tracker value; a missing entry or missing key **aborts** rather than silently taking the template default | `test_registry_sourced_routing_fields_are_correct`, `test_missing_registry_entry_aborts_instead_of_defaulting` |
| §9.2 `plants` is an array | indexed as a list (dict form also accepted) | `test_plants_as_a_dict_is_accepted` |
| §9.3 `MG07` lacks `photo_count`/`photos_drive_url` | template defaults `0` / `""` materialised; verified **MG07 is the only** plant needing them | `test_mg07_...`, `test_only_mg07_needed_photo_count_and_drive_url_defaults` |
| §9.4 `corrected_reading` (1/95, lantz only) | declared field materialised as `null` on all 45 plants, never dropped, never fabricated | `test_corrected_reading_is_defaulted_on_every_plant_and_never_invented` |
| §9.5 10 always-null fields | declared template types govern; no type inferred from observed data | full-value diff |
| §9.6 `notes_meta` absent on this project | materialised as the template default `{}`, reported in `defaulted_fields` | `test_project_missing_notes_meta_gets_the_template_default` |
| §7a `MG07` photos carry extra `uploaded`/`context` sub-keys | `photos` passes through opaquely; sub-keys survive | `test_mg07_...` |
| §4 `reports`/`reports_url` unique to this project | `drive_folders` compared whole | `test_drive_folders_reports_subkeys_unique_to_this_project_survive` |

**Field additions are not data loss.** Fields materialised from a template
default because the source lacked them are reported separately on
`MigrationSummary.defaulted_fields`, never conflated with a preserved value.
For this project that is `corrected_reading` (all 45 plants),
`photo_count`+`photos_drive_url` (MG07 only), and `notes_meta` +
`genetics`/`breeder_lineage` at project level.

### 3b. `observation_log` bodies

All 45 observation logs are byte-identical to the source string, stored as the
markdown **body** below the frontmatter (never as a YAML scalar), and
`observation_log:` never appears in any frontmatter block. The migrated tree is
also byte-stable across a further read/write cycle, so later ingestion runs
will not produce noise diffs.

## 4. Acceptance criteria (c) + (d) — sandbox-only, no real side effects

Codex's I13 objection is that an md5 check alone does not prove side-effect
isolation. Five independent layers here:

1. **`tracker.json` md5 unchanged** — `f55be8df99b8e94606c19b3730b830e4` before
   and after, measured with the system `md5sum` binary, not only in-process.
   `registry.json`'s md5 is likewise unchanged, and the file's `mtime_ns` is
   asserted unchanged too.
2. **Whole live directory fingerprinted** — all **839** paths under
   `~/.hermes/breeding/mule-fuel-x-nana-glue/` (size + `mtime_ns`) are identical
   before and after. This catches a write to a dashboard file, cache entry or
   `.git` ref that a single-file hash would miss.
3. **Static proof of no side-effect capability** — a test asserts
   `tracker_migration.py` contains no `subprocess`/`socket`/`urllib`/`http`/
   `requests`/`smtplib` import and no `os.system`/`os.popen`. The module
   physically cannot push, POST or message anyone.
4. **Runtime booby-traps** — the real migration runs with `subprocess.run/Popen/
   call/check_call/check_output`, `socket.socket`, `socket.create_connection`,
   `urllib.request.urlopen` and `os.system` all monkeypatched to raise. It
   completes successfully, so none was reached.
5. **Write-path spy** — `os.open` is wrapped for the duration of a real run and
   every write-flagged path is asserted to resolve inside the sandbox
   directory. Zero writes landed outside it.

Plus a **destination guard** (`assert_sandbox_destination`) that refuses to
write into: a non-empty directory, anything inside a git work tree (unless
explicitly opted into for a future real run), or anywhere under
`~/.hermes/breeding/`. The live-data check deliberately beats the git opt-in, so
`allow_git_repo=True` can never become a blanket "write into live data" switch.
A test drives this against the real `~/.hermes/breeding/mule-fuel-x-nana-glue/`
path and confirms nothing is created.

The sandbox is a `tempfile.TemporaryDirectory` / pytest `tmp_path` and is
removed after each run.

## 5. Independent verification

`tools/verify_mule_fuel_migration.py` re-derives all of the above from scratch
without importing the test suite or reusing its assertions, so a bug shared
between the migration code and its own tests cannot hide. Result: **20/20
checks PASSED**.

## 6. Test suite

| | tests |
|---|---|
| before this task | 287 |
| `test_tracker_migration.py` (new) | +41 |
| `test_mule_fuel_migration.py` (new) | +19 |
| **after** | **347 passed, 0 failed** |

## 7. What was NOT done (deliberately)

- No real project repo was created, written to, committed to, or pushed.
- The remaining 5 projects are untouched — this is Task 3.x instance 1 of 6.
- Promoting this migration to a real repo is a separate, deliberate step
  requiring `allow_git_repo=True` and a destination outside
  `~/.hermes/breeding/`; the plan's Phase 5 cutover re-runs the migration fresh
  at that point rather than reusing this sandbox snapshot.
