# Task 3.2 — `honey-badger-haze-pheno-hunt` tracker.json → Markdown migration

**Phase:** 3 (data migration), Task 3.x instance #2 of 6
**Scope:** `/home/joey/.hermes/breeding/honey-badger-haze-pheno-hunt/tracker.json`
**Mode:** **SANDBOX ONLY** — no real repo written, no commit/push to any project
repo, no Discord, no Drive.
**Verdict:** **PASS** — 23/23 plants, 414 plant field values + 11 project field
values + 2 registry-sourced routing fields round-tripped with zero loss,
`tracker.json` md5 `eb23369faf136231e3a801eb5f99612a` unchanged.

---

## 1. What was used

No production code was written or changed for this task. Task 3.1's
`src/tracker_migration.py` was reused **as-is** (`git diff src/` is empty for
this commit), which is the point: the tooling was hardened across four review
rounds on mule-fuel, and Task 3.2 is evidence it generalises to a second
project rather than being fitted to the first.

New files are test/verification/documentation only:

| file | purpose |
|---|---|
| `tests/test_honey_badger_haze_migration.py` | 37 acceptance tests against the **real** tracker |
| `tools/verify_honey_badger_haze_migration.py` | out-of-band verifier re-deriving every claim independently of the test suite |

## 2. Acceptance criterion (a) — plant count matches exactly

| measure | value |
|---|---|
| plants in `tracker.json` | **23** |
| `plants/*.md` files written | **23** |
| plant IDs, sorted, source vs written | **identical** |

`HBH01`–`HBH23`, a contiguous run with no numbering gap (unlike mule-fuel,
which skips `MG09`). Asserted as the exact expected ID list, so a dropped or
renumbered record fails rather than merely changing a count.

Cross-checked against Task 3.0's inventory (23 for this project, part of the
95-plant total).

## 3. Acceptance criterion (b) — zero data loss

Every key/value in the source is compared, not a hand-picked subset:

- **414** plant field values (23 plants × 18 keys) → **0 lost, 0 altered**
- **11** project field values → **0 lost, 0 altered**
- **2** registry-sourced routing fields → correct (see §3a)
- `verify_migration` reports **24 records / 427 field values compared**, and
  the test asserts those exact counts — `ok=True` from a gate that silently
  inspected nothing is not accepted as evidence.
- Whole-object checks: the `plants` array and the project dict, reconstructed
  from markdown and compared with `json.dumps(..., sort_keys=True)`, are
  **equal** to the source.

### 3a. `auto_create` — the discriminating case mule-fuel could not provide

Task 3.0 §8's highest-risk finding is that `auto_create` and
`plant_id_prefixes` exist only in `registry.json`; sourcing them from the
tracker silently yields the template defaults (`false` / `[]`) and breaks ID
routing.

On mule-fuel the registry value of `auto_create` is `false` — **identical to
the template default**. A migration that ignored `registry.json` entirely
would have produced a byte-identical `project.md` there and passed every
Task 3.1 assertion. That project's data could not distinguish the two.

This project's registry value is **`true`**, so it can:

| source | `auto_create` |
|---|---|
| `registry.json` entry | `true` |
| `project-template.md` default | `false` |
| `tracker.json` | *field does not exist* |
| migrated `project.md` | **`true`** |

`test_auto_create_is_registry_true_and_not_the_template_default` asserts all
four facts together. This is the first positive proof in the project's history
that the registry is genuinely read, and it was confirmed by mutation: deleting
the registry-override block from `build_project_record` makes the suite fail
(under Task 3.1's data it would not have).

The `HBH` routing regex `\bHBH[\s\-]?(\d{1,2})\b` is asserted byte-intact —
a mangled backslash would silently break ID routing for every future note.

### 3b. Per-project shape differences from Task 3.1, each asserted

| Task 3.0 finding | this project | handling |
|---|---|---|
| §6 `notes_meta` absent on mule-fuel | **present** here | preserved verbatim, **not** overwritten with the template `{}`; asserted not in `defaulted_fields` |
| §9.3 `MG07` lacks `photo_count`/`photos_drive_url` | **no such record** — all 23 plants carry all 18 keys | asserted that *no* plant needed those defaults, so a real field loss cannot hide behind "it was defaulted" |
| §9.4 `corrected_reading` (lantz-only) | absent from all 23 | materialised as `null` and asserted to be the **only** defaulted plant field on every record |
| §4 `reports`/`reports_url` unique to mule-fuel | 8-subkey `drive_folders` | round-trips whole; asserted the sibling project's extra keys are **not** invented |
| §3/§9.5 always-null and nullable fields | `selection_notes` non-null on **HBH15 only**, `terpene_notes` null throughout | declared template types govern; a reader coercing `null`→`""` is caught |
| — | 22/23 plants have photos; one has `[]` | empty list stays `[]`, never becomes `null` |
| — | `active`/`culled`/`keeper` all present | every status preserved exactly |

**Field additions are not data loss.** `corrected_reading` (all 23 plants) is
the only field materialised from a template default; at project level,
**nothing** was defaulted.

### 3c. `observation_log` bodies

All 23 logs are byte-identical to the source string, stored as the markdown
**body** below the frontmatter, and `observation_log:` never appears in any
frontmatter block. `original_notes` (raw Discord text, frontmatter) likewise
survives verbatim on every plant.

The tree is byte-stable across a read/write cycle, and a **second migration of
the same source is byte-identical** across all 24 files — so the Phase 5
cutover cannot produce a spurious diff against this proof.

### 3d. `notes_meta.migration_note` is stale — deliberately preserved

The preserved `migration_note` claims *"plants[] is intentionally empty pending
real Discord/#breeding notes"*, while 23 plants exist. The note is factually
out of date in the **source**. Migration preserves data verbatim; silently
correcting or dropping prose would itself be data loss and would mask the
drift. Flagged here for a human, not fixed by this task.

## 4. Acceptance criteria (c) + (d) — sandbox-only, no real side effects

Six independent layers:

1. **`tracker.json` md5 unchanged** — `eb23369faf136231e3a801eb5f99612a` before
   and after, measured with the system `md5sum` binary, not only in-process.
   `registry.json`'s md5 is likewise unchanged.
2. **Whole live directory fingerprinted** — all **400** paths under
   `~/.hermes/breeding/honey-badger-haze-pheno-hunt/` (size + `mtime_ns`) are
   identical before and after, catching a dashboard/cache/`.git` write that a
   single-file hash would miss.
3. **The other 5 projects fingerprinted** — this task migrates one project;
   sibling trackers are hashed before and after and compared. (The equivalent
   check was written vacuously at first — hashing the same expression twice —
   and was fixed and then *proved to bite* with a negative control that
   perturbs a sibling and confirms the check fails.)
4. **Static proof of no side-effect capability** — `tracker_migration.py`
   contains no `subprocess`/`socket`/`urllib`/`http`/`requests`/`smtplib`
   import and no `os.system`/`os.popen`. It physically cannot push or POST.
5. **Runtime booby-traps** — the real migration runs with
   `subprocess.run/Popen/call/check_call/check_output`, `socket.socket`,
   `socket.create_connection`, `urllib.request.urlopen` and `os.system` all
   monkeypatched to raise. It completes, so none was reached.
6. **Write-path spy** — `os.open` is wrapped and every write-flagged path is
   asserted to resolve inside the sandbox. Zero writes landed outside it.

Plus the **destination guard**: refuses a non-empty directory, anything inside
a git work tree, and anywhere under `~/.hermes/breeding/`. Both the plain call
and `allow_git_repo=True` are driven against the real live path and confirmed
to raise and create nothing — the live-data check deliberately beats the git
opt-in. A mid-write failure (simulated ENOSPC on plant 12 of 23) is confirmed
to leave **no half-written tree**.

The sandbox is a `TemporaryDirectory`/pytest `tmp_path`, removed after each run.

## 5. Independent verification

`tools/verify_honey_badger_haze_migration.py` re-derives every claim without
importing the test suite, so a bug shared between the migration code and its
own tests cannot hide. Result: **42/42 checks PASSED**.

## 6. Mutation testing — the tests actually bite

`ok=True` proves nothing unless the suite fails when the migration is wrong.
Six faults were injected into `tracker_migration.py` and each was caught:

| injected fault | caught by |
|---|---|
| ignore `registry.json` (take template defaults) | `test_auto_create_is_registry_true_...` |
| strip backslashes from the ID-routing regex | `test_registry_sourced_routing_fields_are_correct` |
| coerce `null` → `""` on plant fields | `test_nullable_and_always_null_plant_fields_stay_null` |
| truncate an `observation_log` | `test_observation_logs_are_preserved_verbatim_as_the_body` |
| drop the last plant | `test_plant_count_matches_...` |
| drop `notes_meta` | `test_notes_meta_is_present_and_survives_verbatim` |

`src/tracker_migration.py` was restored after each; `git diff src/` is empty.

## 7. Test suite

| | tests |
|---|---|
| before this task | 365 |
| `test_honey_badger_haze_migration.py` (new) | +37 |
| **after** | **402 passed, 0 failed** (zero warnings, `filterwarnings = error`) |

No test is skipped: all 37 run against the real tracker on this machine.

## 8. What was NOT done (deliberately)

- No real project repo was created, written to, committed to, or pushed.
- No production code changed — Task 3.1's tooling was reused unmodified.
- The remaining 4 projects (kibungan, spaced-paste, paloma-coma, lantz) are
  untouched; this is Task 3.x instance 2 of 6.
- The stale `notes_meta.migration_note` was preserved, not corrected (§3d).
- Promoting this migration to a real repo remains a separate, deliberate step;
  Phase 5's cutover re-runs the migration fresh rather than reusing this
  sandbox snapshot.
