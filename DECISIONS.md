# Decisions — breeding-markdown core library

## Task 0.4 — markdown parsing/writing library: **PyYAML + hand-rolled frontmatter split**

Chosen over `python-frontmatter`. Both are actively maintained, so this was an
ergonomics call, and the deciding factor is Task 1.1's acceptance criterion (c):
the declared schema type must win over YAML's implicit resolver. Satisfying that
requires intercepting scalar construction *at the node level* to keep a scalar's
literal text alongside its resolved value — otherwise `id: 07` is already the int
`7` and `1:30` already the int `90` before any schema logic can run.
`python-frontmatter` delegates to a YAML handler and hands back finished Python
objects, so that interception point is not exposed; we would have had to reach
past its API to a custom loader anyway. Using PyYAML directly also lets us reject
anchors/aliases, duplicate keys, custom tags, and oversized/deeply-nested input
in one strict loader, and keep the markdown body as an untouched byte slice
rather than trusting a library's body handling. The frontmatter split itself is
~15 lines.

## Body vs. frontmatter for `observation_log`

`observation_log` is the markdown **body**, not a frontmatter field. It is
free-text, append-only, frequently hand-edited, and often contains the `---`
delimiter, backticks and tables. As a YAML scalar it would be re-folded and
re-quoted on every write, producing noise diffs on every ingestion run; as the
body it survives byte-for-byte. The template declares it as `type: body` so this
is explicit in the schema rather than an implicit convention.

## Null semantics for string fields

A plain (unquoted) `null`, `~`, or empty value reads back as `None`. That is
exactly how `write_plant` serialises `None`, so round-tripping requires it. Any
other plain scalar keeps its literal text (`07` stays `"07"`, `true` stays
`"true"`). To store the literal strings `"null"` or `"~"`, quote them in the
file — the writer does this automatically for any string that would otherwise
resolve to a non-string type.

## Field discovered during real-data verification

`corrected_reading` (present on Lantz `Ltz01`) was **not** in the plan's Task 0.1
field list. It was found by round-tripping all 95 real plants across all 6
projects and has been added to `plant-template.md`. This is the Task 3.0 field
inventory doing its job early — the plan's asserted field list was incomplete.

## Task 1.1 spec-compliance review findings (2026-09-05)

The spec-compliance reviewer subagent found real, undocumented drift between
this repo's local `templates/plant-template.md` and the canonical,
Joey-approved template in `breeding-meta`. All 4 unapproved schema changes
below were **reverted to canonical** rather than approved as new changes:

- `vigor`: reverted from an unapproved `integer` (0-10 rating, never seen in
  real data -- vigor is null on all 95 real plants) back to canonical
  `string` (free-text assessment).
- `status` default: reverted from an unapproved `"active"` back to canonical
  `null` (undetermined) -- every plant missing a status is now correctly
  materialised as undetermined, not silently marked active.
- `photos_drive_url` default: reverted from an unapproved `null` back to
  canonical `""`.
- `photos` type spelling: reverted from an unapproved `list` back to
  canonical `array` (the coercer now accepts both spellings so this is
  purely a schema-authoring convention, not a functional risk either way).

Tests that used `vigor` as their example field for exercising integer-type
coercion were retargeted to a synthetic ad-hoc schema fixture, since `vigor`
is not actually an integer field in the approved schema.

**5 genuine implementation bugs** were also found (via tests the reviewer
wrote but did not surface in its structured findings output -- flagged to
Joey as a process gap in subagent self-reporting) and fixed:

1. CRLF body/frontmatter content was silently translated to LF by
   `Path.read_text()`'s default universal-newline mode on the READ side (the
   WRITE side already correctly used `newline=""`). Fixed by reading with
   `newline=""` too.
2. `write_plant` with zero frontmatter fields emitted `"---\n---\nbody"`,
   which `_split_frontmatter` then rejected as "unterminated frontmatter" --
   the writer produced a file its own reader couldn't read back. Fixed by
   special-casing the empty-frontmatter delimiter shape.
3. A deeply-nested YAML flow collection could hit Python's own recursion
   limit inside PyYAML's composer, raising a bare `RecursionError` *before*
   the module's own `_check_depth` guard ever ran -- escaping every
   `PlantMarkdownError`-catching caller (e.g. the webhook's future git-pull
   handler). Fixed by catching `RecursionError` in `_parse_yaml` and
   re-raising as `UnsafeYamlError`.
4. `tempfile.mkstemp` always creates its temp file mode `0600`, and
   `os.replace` preserves that mode -- so rewriting an existing normally-
   permissioned file (e.g. `0644`, the usual mode for a git-tracked file)
   silently downgraded it to `0600` on every single write. Fixed by
   explicitly `chmod`-ing the temp file to match the target's existing mode
   before the atomic replace, or a permissive umask-respecting default for
   brand-new files.
5. `load_schema` never validated the `type` vocabulary -- a typo'd
   `type: banana` in a template silently disabled coercion for that field
   with no error at all. Fixed by validating against a known-types set.

All fixes verified: 102 tests, 100% green, zero warnings
(`pytest -W error`), independently re-run after each fix rather than
trusted from any subagent's self-report.

## Task 1.1 code-quality review findings (2026-09-05)

4 Important issues, all empirically verified by the reviewer, all fixed:

1. A YAML complex/unhashable key (`? [a, b]\n: v`) made `_no_duplicates` do
   `key in mapping` on an unhashable list, raising a bare `TypeError` that
   escaped the module's documented "every failure is PlantMarkdownError"
   contract. Fixed: `TypeError` from the membership check is now caught and
   re-raised as `MalformedFrontmatterError`.
2. The `MAX_FILE_BYTES` size guard used `Path.stat()`, which follows
   symlinks -- a git-committed symlink (e.g. to `/dev/zero`) reports a
   tiny/zero apparent size while the actual read is unbounded, defeating
   the DoS guard entirely. Files arrive via `git pull` from human-editable
   repos and git tracks symlinks, so this was in-scope for the documented
   threat model. Fixed: read with an explicit `MAX_FILE_BYTES + 1` cap and
   check the actual bytes read, rather than trusting `stat()`.
3. The earlier CRLF fix was read-side only -- `write_plant` hardcoded LF
   frontmatter delimiters even when rewriting a CRLF body, producing a
   mixed-newline file and a spurious whole-header diff on every touch of a
   Windows-authored plant. Fixed: the writer now detects a CRLF-only body
   and matches the delimiters/YAML block to the same line ending.
4. Block scalars (`|` and `>`) were run through the implicit resolver like
   any other plain scalar, so `id: >-\n  07` yielded the int `7` -- YAML
   spec says block scalars are ALWAYS strings, and this violated the
   module's own "declared types win" rule. Fixed: `_plain_scalar` now
   short-circuits on `|`/`>` styles the same way it already did for quoted
   scalars.

Also fixed 2 Minor issues with real correctness implications (not just
style): `_get_umask()` was toggling the process-global umask on every
`write_plant` call for a new file, a race against any concurrently-created
file in another thread/process -- now cached once at import time instead.
And `read_plant`/`write_plant` were asymmetric for a schema that omits
`observation_log`: the writer always emitted the body but the reader only
returned it if the schema declared it, silently breaking
`read_plant(write_plant(x)) == x`. Fixed: the body is now always returned.
Also added: an explicit rejection if `observation_log` ever appears in
frontmatter (previously silently discarded, which could lose hand-entered
data), since it must live only in the body.

Remaining minor style nits (chmod-before-write ordering, no directory
fsync after os.replace, `_prepare_for_dump`'s unused `field` param,
`_check_depth`'s dict-key-counts-as-a-level nesting semantics) are real but
low severity -- documented here rather than fixed, since none risk data
loss, crashes, or incorrect behavior on the actual breeding-tracker data.

Final state after both review stages: 111 tests (test_plant_markdown.py +
test_real_data_roundtrip.py), 100% green, zero warnings.

## Task 1.2 / 1.3 spec-compliance review findings (2026-09-05)

11 empirically-verified gaps, all reproduced with probe scripts before any
fix, all fixed under strict TDD (regression test watched RED, then GREEN).

### `project_markdown.py` (Task 1.2) had drifted behind `plant_markdown.py`

Task 1.1 went through two review rounds and got hardened; Task 1.2 was
written against the pre-hardening shape of the same module and never
received those fixes. All 8 are ports of an already-approved Task 1.1 fix,
so the two modules now agree on behavior rather than diverging silently:

1. `read_project` used `Path.read_text()` WITHOUT `newline=""`, so
   universal-newline translation silently mangled a CRLF body to LF; and
   `write_project` hardcoded LF frontmatter delimiters even for a CRLF body,
   producing a mixed-newline file. Ported the newline-preserving read and
   the CRLF-matching write.
2. `write_project({'body': 'hello\n'})` emitted `---\n---\nhello\n`, which
   `read_project` then rejected as "unterminated frontmatter" -- the writer
   produced output its own reader could not read. Ported the
   empty-frontmatter special case in `_split_frontmatter`.
3. A deeply-nested YAML flow collection raised a bare `RecursionError` out
   of the module instead of the documented `ProjectMarkdownError` contract.
   Ported the `RecursionError` -> `UnsafeYamlError` catch.
4. `load_schema` never validated the `type` vocabulary -- `type: banana` was
   silently accepted, disabling coercion for that field with no error.
   Ported the known-types validation (with project's own `boolean`/`object`
   types included).
5. An unhashable YAML complex key (`? [a, b]`) leaked a bare `TypeError` out
   of `read_project`. Ported the `try/except` around the membership check.
6. `read_project` used `Path.stat()` (which follows symlinks) with no cap on
   the actual read -- a git-committed symlink to `/dev/zero` reports size 0
   and then consumes memory without bound. Ported the explicit
   `MAX_FILE_BYTES + 1` read cap that checks bytes actually read. The
   regression test drives the real `/dev/zero` symlink in a child process
   under `RLIMIT_AS`, so a regression fails loudly instead of OOM-ing the
   whole test session.
7. `write_project` never chmod'd the temp file before `os.replace`, so every
   rewrite of a normal 0644 git-tracked file silently downgraded it to 0600.
   Ported the chmod-before-replace fix (and the cached-umask helper it needs).
8. A hand-edited `body:` key in frontmatter was SILENTLY DISCARDED rather
   than rejected, losing real hand-entered data. Ported the explicit
   rejection, matching how `plant_markdown` treats `observation_log`.

### `migration.py` (Task 1.3): three real bugs the existing tests missed

1. **Push-stranding (the serious one).** With a reachable local clone but an
   unreachable remote, run 1 correctly reported `failed` -- but
   `apply_new_fields` had already applied the fields and committed locally
   before the push raised. On retry with the remote restored,
   `apply_new_fields` returned `changed=False` (the file already matched the
   template), so `_migrate_one_repo` made no git call at all, never retried
   the push, and the state file recorded `success` at the current template
   version -- while `git ls-remote` on the restored remote was still empty.
   That permanently and silently skipped a repo whose changes never left the
   local clone, and no existing test could see it because every existing
   failure case used an unreachable *local path*, never an unreachable
   *remote*. Fixed by refusing to conflate "the local file already reflects
   the template" with "this repo's committed state has been pushed":
   `_migrate_one_repo` now compares local `HEAD` against the remote branch
   tip on every run, pushes when they differ regardless of whether any field
   changed this run, and re-checks the remote afterwards, raising rather
   than reporting success if the commit isn't confirmed there.
2. `git add -A` swept every dirty/untracked file in the working tree into
   the migration commit -- a half-finished hand edit on a repo the migration
   happens to run against would be committed and pushed under a
   `chore: migrate to latest template fields` message. Now stages and
   commits only the specific markdown files this run rewrote.
3. `_save_state` ran only after the entire registry loop finished, so a
   mid-run crash persisted nothing and a restart re-migrated every repo from
   scratch, including ones that had already pushed successfully -- defeating
   the resumability the module's own docstring promises. State is now
   persisted after each repo's attempt, success or failure.

Note on scope: `src/plant_markdown.py` and `src/scaffolding.py` were read as
reference only and deliberately not modified -- Tasks 1.1 and 1.4 already
passed review.

Final state: 248 tests, 100% green, zero warnings (`pytest -W error`).

## Task 1.2 / 1.3 / 1.4 code-quality review findings (2026-09-05)

1 Critical + 7 Important issues, all empirically reproduced by the reviewer
with probe scripts before any fix, all fixed under strict TDD (regression
test watched RED, then GREEN, full suite re-run after each group).

### Critical: `migration.py` commit-stranding

Exactly the same class of bug as the push-stranding one fixed in the
previous review, one step earlier in the same function. If `git add` or
`git commit` failed AFTER `apply_new_fields` had already rewritten the
files on disk, the run was correctly reported `failed` -- but the rewritten
files stayed **uncommitted in the working tree**. On the retry,
`apply_new_fields` saw files that already matched the template
(`changed=False`), so no commit was attempted; local `HEAD` still equalled
the remote tip from before, so no push was attempted either; and the run
recorded `status=success` at the current template version. The edits then
sat as permanent uncommitted local changes while the repo was marked
migrated forever.

Fixed by refusing to conflate "the local file matches the template" with
"this repo's edits are committed", the same way the push fix refuses to
conflate it with "pushed": `_migrate_one_repo` now runs
`git status --porcelain` over the migration-managed paths
(`project.md`, `plants/*.md`) before recording success. Dirty managed paths
mean a previous run's edits were stranded, so they are committed and pushed
on this run; if they are somehow still dirty afterwards, that is a hard
failure, never a skip-as-already-done.

### `migration.py`: three more real bugs

1. **Three unhandled paths aborted the ENTIRE batch** rather than isolating
   to one repo, defeating the "one repo's failure must not abort the batch"
   contract the module's own `except` comment claims: (a) a registry entry
   missing the `name` key raised a bare `KeyError` from OUTSIDE the try
   block; (b) a corrupt/truncated state file made `_load_state`'s
   `json.loads` raise `JSONDecodeError` before the loop even started,
   bricking every future run of the migration permanently; (c) a
   `state_path` whose parent directory did not exist raised
   `FileNotFoundError` from the FIRST `_save_state` -- which only happens
   *after* a repo has already migrated and pushed, losing that record.
   Fixed: per-entry `name`/`path` validation now happens inside the loop and
   reports a per-repo failure; `_load_state` degrades to an empty state on a
   corrupt/unreadable/wrong-shaped file (re-doing idempotent work is far
   cheaper than bricking the migration); `_save_state` mkdirs its parent.
2. **Detached HEAD pushed to a garbage branch.**
   `git rev-parse --abbrev-ref HEAD` returns the literal string `HEAD` on a
   detached HEAD, which was then used as the push TARGET
   (`push origin HEAD:refs/heads/HEAD`) -- creating a junk `HEAD` branch on
   the remote, reporting success, and never reaching the repo's real branch.
   There is no correct branch to infer, so this is now a hard failure for
   that repo.
3. **No rollback on failure, and a report that discarded what it touched.**
   Every failure path left half-applied edits dirty in the working tree,
   which then collide with the next run or with a human/data-api's
   `git pull` -- and the failure report hardcoded `added_fields={}`,
   throwing away exactly the information a human needs to work out what
   state the repo was left in. Fixed: `_migrate_one_repo` now wraps the work,
   restores the migration-managed paths to `HEAD` on failure (best-effort,
   so a failing rollback never masks the original error), and raises a new
   `RepoMigrationError` carrying the paths/fields actually touched, which
   both the report and the state file now record.

### `project_markdown.py` had drifted behind `plant_markdown.py` again

The Task 1.2 spec-compliance review ported 8 fixes across; these 3 were
missed and are the exact behaviours where the two modules diverged:

1. **Arbitrary/dangerous YAML tags were accepted** (`!!set`, `!!binary`,
   `!!omap`, `!!pairs`, `!custom`, `!!python/name:os.system`) where
   `plant_markdown.py` rejects them. The `None` (fallback) constructor was
   registered as `_plain_scalar`, which re-resolved the node's VALUE through
   the implicit resolver and silently discarded the tag. Ported
   `_reject_unknown_tag` and `_reject_collection_tag`.
2. **Unaliased anchor DEFINITIONS were accepted** (`cross_name: &a big`),
   directly contradicting the module's own docstring claim that anchors are
   refused outright: the guard was still the pre-fix lambda checking only
   `AliasEvent`. Ported `_compose_node_reject_anchors`, which checks
   `event.anchor` on every composable event (scalar, sequence-start,
   mapping-start, alias), catching definitions and references alike.
3. **Block scalars were type-coerced.** `_plain_scalar` short-circuited on
   quote styles (`'`, `"`) only, not block styles (`|`, `>`), so
   `cross_name: >-\n  07` yielded the int `7` -- violating both the YAML
   spec (block scalars are ALWAYS strings) and the module's own "declared
   types win" rule. Ported the full style check.

### Test-suite drift between the two modules

`project_markdown.py`'s suite was missing ~15 tests that exist for
`plant_markdown.py` covering exactly the divergent behaviours above -- which
is *why* the drift went unnoticed twice. Added the project equivalents,
mirroring the plant suite's class/test names and adapted to project.md's
schema: YAML collection-tag rejection (4), custom/`!!python/name` tag
rejection (3), anchor rejection on scalar/mapping/sequence (3),
block-scalar type-string tests (5), unhashable-key rejection (1), and CRLF
rewrite byte-stability (1). Keeping the two suites symmetrical is the
mechanism that stops this drifting a third time.

`scaffolding.py`'s suite was almost entirely happy-path; added 9 tests for
the failure modes a real caller can hit: an override violating the declared
schema type, a nonexistent template path, a template with no frontmatter, a
template accidentally authored as example values rather than descriptors,
and a non-mapping/None `overrides` argument. The override-type test
deliberately PINS current behaviour (written out unvalidated, then
unreadable with the same schema) rather than demanding a fix, since
override validation is on the accepted-debt list below -- the test exists to
make the behaviour visible and fail loudly if it silently changes.

### Minor findings documented, deliberately not fixed

Following Task 1.1's precedent of documenting rather than fixing issues
that risk no data loss, crash, or wrong behaviour on the real
breeding-tracker data: the `type: 'list'` coercion gap in
`project_markdown.py`; `scaffolding.py` accepting unvalidated override
values and typo'd keys; the TOCTOU window on `scaffolding.py`'s
`FileExistsError` guard; `migration.py`'s filename-heuristic module
dispatch (`project.md` == project, everything else == plant);
`MigrationReport.__repr__`; unvalidated registry paths; subprocess `stderr`
not being surfaced in failure messages; `_no_anchors`'s untyped signature;
and `import copy` sitting inside `_default_for` instead of at module scope.

Final state: 284 tests, 100% green, zero warnings (`pytest -W error`),
re-run independently after each commit rather than trusted from any
subagent's self-report.

## Task 1.3 code-quality review round 4 findings (2026-09-05)

### Critical: porcelain column parsing corrupted unstaged filenames

The commit-stranding recovery path added in round 3 could never recover a
repo stranded by an UNSTAGED failure -- it failed on every retry, forever.

`_porcelain_status()` returned `result.stdout.strip()`, and the recovery
then sliced each line at the fixed column `line[3:]`. Porcelain v1 is a
fixed-width format: two status characters (XY), a space, then the path. A
staged entry is `"M  project.md"`, but an UNSTAGED entry is
`" M project.md"` -- with a leading space that is part of the format, not
padding. `.strip()` ate that space, shifting every column left by one, so
`line[3:]` sliced the first character off the filename: `project.md`
parsed as `roject.md`. The recovery then ran `git add -- roject.md`, which
fails (no such file), so the run failed; and because the failure is
deterministic, every subsequent retry failed identically. Any repo
stranded by a failing `git add`, a stale `index.lock`, or external dirt in
the migration-managed paths was permanently unrecoverable.

Fix: `_porcelain_status()` now returns the RAW stdout (documented as
deliberately unstripped; the one human-facing error message strips it at
the point of use), and path extraction moved into a new `_dirty_paths()`
helper that splits on `\n`, strips only a trailing `\r`, skips blank
lines, and takes `line[3:]` off the untouched line. It also handles the
rename shape `"R  old -> new"` by taking the new path -- the only one that
exists on disk to stage.

Why it slipped past three review rounds: the only test covering the
recovery path exercised the STAGED shape (`"M  path"`), which `.strip()`
does not corrupt, so the bug was invisible. The new
`TestPorcelainStatusParsing` covers all three shapes -- a direct unit test
of `_dirty_paths` over staged/unstaged/untracked lines, plus two
end-to-end tests that strand a real repo with unstaged edits and with an
untracked managed file and assert the retry actually commits AND pushes
the correctly-named file to the remote (not merely that the run fails).

### Dead assertion in the companion stranding test

`test_uncommitted_migration_edits_are_never_recorded_as_success` guarded
its only assertion behind `if report.repos["dirtyskip"]["status"] ==
"success"`, which never fires because the run correctly fails -- so the
test asserted nothing and would have passed against almost any
regression. It now re-strands the repo explicitly (the round-3 rollback
cleans the tree, so the scenario has to be reconstructed), then asserts
unconditionally that a run with a still-broken commit and dirty managed
paths is recorded as `failed` and that the failure names the uncommitted
paths.

Final state: 287 tests, 100% green, zero warnings (`pytest -W error`).

## Task 3.1 — mule-fuel-x-nana-glue tracker.json -> markdown (sandbox-only)

Phase 3's first of six per-project migrations. New module
`src/tracker_migration.py` plus `tools/verify_mule_fuel_migration.py`.

### Registry, not tracker, is the source for two fields

Task 3.0 §8 flagged this as the migration's highest-risk item and it is
handled as a hard failure rather than a fallback: `auto_create` and
`plant_id_prefixes` exist in NO tracker.json, only in `registry.json`.
`build_project_record` reads them from the registry entry, lets them
OVERRIDE any same-named tracker key, and raises `TrackerMigrationError` if
the registry entry (or either key on it) is missing. Silently taking the
template defaults (`false` / `[]`) would produce a project.md that looks
correct and breaks ID routing and auto-create.

### Field additions are tracked separately from field preservation

A migration that fills a missing field from a template default is doing the
right thing, but conflating that with "the value round-tripped" would let a
real loss hide behind a default. `MigrationSummary.defaulted_fields` records
every materialised field per record; `verify_migration` reports only fields
that were present in the source and are now missing or changed. For this
project the defaults are `corrected_reading` (all 45 plants -- declared in
the template, real on exactly one lantz plant), `photo_count` +
`photos_drive_url` (MG07 alone), and `genetics`/`breeder_lineage`/
`notes_meta` at project level.

### Sandbox isolation is enforced, not documented

Task 3.x's criterion (d) explicitly says an md5 check alone does not prove
side-effect isolation (Codex I13). Five layers instead:

1. `assert_sandbox_destination` refuses a non-empty destination, any path
   inside a git work tree (unless `allow_git_repo=True`), and anything under
   `~/.hermes/breeding/`. The live-data check is evaluated AFTER and
   independently of the git opt-in, so `allow_git_repo=True` can never
   become a blanket permission to write into live data.
2. A static test asserts the module imports no `subprocess`/`socket`/
   `urllib`/`http`/`requests`/`smtplib` and calls no `os.system`/`os.popen`
   -- it physically cannot push, POST or message anyone.
3. The real migration is run with all of those booby-trapped to raise.
4. An `os.open` spy asserts every write-flagged path resolves inside the
   sandbox.
5. All 839 paths under the live project dir are fingerprinted (size +
   mtime_ns) before and after; a write to a dashboard file or `.git` ref
   that a single-file md5 would miss shows up here.

Destination validation and ALL plant validation (ids, duplicates, unsafe
filenames) run before the first byte is written, so a malformed tracker
never leaves a half-written tree behind.

### Verification is independent of the test suite

`tools/verify_mule_fuel_migration.py` re-derives every acceptance claim from
scratch -- including hashing via the system `md5sum` binary rather than
Python's hashlib -- so a bug shared between the migration code and its own
tests cannot hide. 20/20 checks pass.

Result: 45/45 plants, 808 plant field values + 8 project field values with
zero loss, tracker.json md5 `f55be8df99b8e94606c19b3730b830e4` unchanged.

Final state: 347 tests (287 + 41 unit + 19 real-data), 100% green, zero
warnings (`pytest -W error`).

### Task 3.1 code-quality review round 4

Two Important findings in the migration/verification tooling.

**1. `verify_migration`'s gate was blind.** `report.ok` was True whenever
no discrepancy had been *recorded* — which is also exactly what an
inspection that compared nothing at all looks like. Point the verifier at
the wrong directory, hand it a tracker whose records have vanished, or let
a reader silently return nothing, and it reported a clean migration. That
is the one failure mode a zero-data-loss gate must not have, because it
fails toward "accept". `VerificationReport` now counts the records and
field values it actually compared, exposes `verified_something`, and `ok`
is False when that count is zero. Vacuous truth is now a failure, not a
pass. On the real tracker the gate reports 46 records / 816 field values;
`as_dict()` gained `verified_something`/`records_compared`/
`fields_compared`, and the pre-existing dict-shape test was updated to
match the widened contract.

**2. No rollback on a mid-write failure.** Round 3 established that *all
validation* runs before the first byte, so a malformed tracker can't leave
a half-written tree. That guarantee didn't cover the write loop itself:
ENOSPC, a permission change, or a writer bug on record N of M left a
partial tree on disk that is indistinguishable from a complete migration to
anything that later inspects the directory — including a human deciding the
migration is done. The writes are now wrapped, and `_rollback_partial_write`
removes everything the failed call created before the original exception
propagates unchanged. Three deliberate details: paths are registered
*before* their write (a writer failing partway still leaves a partial file
to clean up), a destination directory the caller pre-created is emptied but
kept (matching the sandbox guard, which accepts existing-but-empty), and
cleanup is best-effort with swallowed errors so a failing rollback never
masks the real failure — the same convention `migration.py::_rollback` uses.
`except BaseException` is intentional: a KeyboardInterrupt mid-migration
must not leave a half-written tree either.

Both fixes were driven test-first (9 new tests, all failing for the right
reason before the fix) and are additionally proven against the real
45-plant tracker by `tools/verify_mule_fuel_migration.py`, which grew four
checks: the report's counts are re-derived independently rather than
trusted, a never-migrated directory must be reported NOT ok, and a
simulated ENOSPC on plant 20 of 45 must leave nothing behind. 24/24 checks
pass; `tracker.json` md5 `f55be8df99b8e94606c19b3730b830e4` unchanged and
all 839 live paths unchanged.

Final state: 356 tests, 100% green, zero warnings (`pytest -W error`).

### Task 3.1 code-quality review round 5

**`verify_migration` was blind to the two fields the migration exists to get
right.** Round 4 fixed a *related* problem — the gate could pass vacuously
after comparing nothing — but left the real gap open, and the counts it added
actively disguised it: the report proudly stated "816 field values compared"
while never once looking at `auto_create` or `plant_id_prefixes`.

The mechanism: `verify_migration` diffed the migrated `project.md` against
`tracker.json` alone. But those two fields do **not exist in any tracker**
(Task 3.0 §8) — that is the entire reason `build_project_record` reads them
from `registry.json` and refuses to run without an entry. And the verifier
treats a field absent from the source as an *addition, not loss*. So the two
fields whose defining property is "unobtainable from the tracker" were exactly
the two fields the zero-data-loss gate never compared. A `project.md` carrying
the template defaults (`false` / `[]`) — which silently breaks ID routing and
auto-create in production, the precise failure `build_project_record` raises
to prevent — verified `ok=True`. The gate failed toward "accept" on the one
class of corruption it was written to catch.

The fix makes the verifier read the same two sources the writer does.
`verify_migration` now takes `registry_path` and `slug` and overlays the
registry values onto the expected project record before diffing, mirroring
`build_project_record` exactly (registry wins over any same-named tracker
key, so a stale tracker value can't satisfy the gate). `REGISTRY_SOURCED_FIELDS`
is declared once at module level and consumed by both the writer and the
verifier, so the two cannot drift about which fields the registry owns.

Three deliberate choices:

* The new parameters are **required, not optional with a default**. A default
  would re-open the identical blind spot for every caller who omits them, and
  this is a gate whose failure mode is silent acceptance. Callers must supply
  the registry; there is a test asserting the no-registry call is a `TypeError`.
* Verification **re-validates the registry entry** (missing entry, or an entry
  lacking a routing field, aborts). Falling back to a template default while
  *verifying* would be the same bug in a different function.
* `test_verification_that_compared_nothing_is_not_ok` was tightened: an empty
  tracker no longer compares zero fields, because the two routing fields are
  always checked. The genuinely blind case — nothing on disk to re-read — is
  what it now exercises.

Field counts rose by exactly 2 per project record, on synthetic (17 -> 19) and
real data (816 -> 818), which is the fix's own evidence that the previously
skipped fields are now inspected.

`tools/verify_mule_fuel_migration.py` grew five checks that revert each routing
field independently to its template default and require rejection, confirm the
restored file verifies clean again, and confirm the registry cannot be omitted:
29/29 pass against the real 45-plant tracker, md5
`f55be8df99b8e94606c19b3730b830e4` unchanged, all 839 live paths unchanged.

Final state: 365 tests, 100% green, zero warnings (`pytest -W error`).

---

## Task 3.2 — honey-badger-haze-pheno-hunt migration (sandbox-only)

Second of six Task 3.x project migrations. **No production code was written or
changed**: Task 3.1's `src/tracker_migration.py` was reused verbatim and
`git diff src/` is empty for this commit. That is the deliverable's main
claim — the tooling hardened over four review rounds on mule-fuel generalises
to a second project rather than having been fitted to the first.

Result: 23/23 plants, 414 plant field values + 11 project field values + 2
registry-sourced routing fields, zero loss; tracker md5
`eb23369faf136231e3a801eb5f99612a` unchanged; all 400 live paths unchanged;
42/42 out-of-band checks pass; suite 365 -> 402.

### The `auto_create` blind spot Task 3.1 could not have detected

Task 3.0 §8's highest-risk finding is that `auto_create`/`plant_id_prefixes`
live only in `registry.json`, and reading them from the tracker silently
yields the template defaults (`false`/`[]`), breaking ID routing.

mule-fuel's registry `auto_create` is `false` — **the same value as the
template default**. So on Task 3.1's data, a migration that never opened
`registry.json` would have produced a byte-identical `project.md` and passed
every assertion, including the ones written specifically to prove the registry
was consulted. Those assertions were true but not *discriminating*; the
project's data could not tell the two implementations apart.

This project's value is `true`, so it can. `test_auto_create_is_registry_true_
and_not_the_template_default` pins all four facts at once: registry says
`true`, template default is `false`, the tracker has no such key, and the
migrated file says `true`. Confirmed by mutation — deleting the
registry-override block from `build_project_record` fails this suite, while it
would have passed Task 3.1's.

**Lesson for the remaining four projects:** an assertion that a value came
from source A is only evidence when A and the fallback disagree. Prefer
projects/fixtures where they differ, and treat a passing check on data where
they agree as untested, not proven.

### A vacuous check caught in our own verifier

The first draft of "the other 5 projects are untouched" compared
`md5sum(f) == md5sum(f)` — the same expression twice, trivially true, and it
printed PASS. This is precisely the failure class `VerificationReport`'s
evidence counters exist to prevent, reproduced in the tool that was supposed
to independently police the migration.

Fixed by capturing sibling baselines *before* the migration runs, then
comparing after. More importantly, the fix was validated with a **negative
control**: a probe that perturbs a sibling tracker mid-run and confirms the
check flips to FAIL (it did; the sibling was then restored byte- and
mtime-identical). A green check that has never been observed to go red is not
evidence.

The same reasoning drove `test_verification_actually_compared_every_record_
and_field`, which asserts the exact 24 records / 427 field values rather than
trusting `report.ok`, and mutation-testing six injected faults against the new
suite (registry bypass, regex backslash loss, null coercion, body truncation,
dropped plant, dropped `notes_meta`) — all caught, source restored each time.

### Preserving data that is known to be wrong

This project's `notes_meta.migration_note` asserts "plants[] is intentionally
empty", while 23 plants exist. The note is stale in the **source**. It is
migrated verbatim: correcting or dropping prose during a migration is data
loss, and it would hide the drift from the human who needs to see it. Flagged
in the report, not fixed here. Migration preserves; it does not editorialise.

### Task 3.2 code-quality review — three Important findings

Fixed before Task 3.3 could replicate them. All three were in the
*verification tooling*, not the migration: `src/tracker_migration.py` is
byte-identical across this work. A gate that fails toward "accept", or that
cries wolf, is worse than no gate, because it is trusted.

**1. The git side-effect gate was a suffix whitelist.** Both verifiers decided
"no unexpected git changes" by discarding every `git status --porcelain` line
whose text ended with one of a hardcoded list of paths. Four defects in one
construct: the list grew by an entry per project; a whitelisted path was
forgiven *whatever* had happened to it (edited, staged, truncated to zero,
deleted); a file already dirty for unrelated reasons was silently excused; and
mule-fuel's copy carried a blanket `"tools/" not in line` escape forgiving
every change anywhere under `tools/` — including the verifier rewriting
itself. Replaced by `git_status_snapshot` + `unexpected_git_changes`: a
porcelain baseline is captured before the run and *any* divergence is
reported, so the allowance is data rather than a literal list of forgiven
paths. It parses `--porcelain -z`, because plain porcelain C-quotes paths
containing spaces or quotes — the exact bug `ec18b34` already fixed once in
`migration.py`, which the gate policing `migration.py` must not reintroduce.

**2. The live-directory fingerprint was flaky.** `(size, mtime_ns)` over
`LIVE_DIR.rglob("*")` swept in `__pycache__/`, `cache/`, `.pytest_cache/` and
the nested `dashboard/.git/` working repo. Those are rewritten by processes
with nothing to do with the migration — importing a module writes a `.pyc`,
the dashboard generator refreshes `cache/*.json`, a `git fetch` rewrites
`FETCH_HEAD` — so the check could go red on an entirely clean run.
`is_volatile_path` excludes exactly those (a closed list, not a heuristic),
taking honey-badger from 400 fingerprinted paths to 62 data paths. Critically,
the exclusion does not *lose* coverage: `nested_repo_state` replaces the
`.git` mtimes with a **stronger** check — HEAD sha + porcelain status — which
a `git commit`/`git push` by the migration moves and a `git gc` does not.
Directories are recorded by presence, never mtime, because a directory's mtime
bumps when a child is created and would let excluded churn leak back through
its parent.

Every exclusion is paired with a negative control, and the controls were run
against the REAL data, not just fixtures: an untracked file created mid-run
flips the git check to FAIL, and a byte appended to the live
`dashboard/index.html` flips the fingerprint to FAIL (restored byte- and
mtime-identical afterwards). A green check never observed going red is not
evidence — the lesson Task 3.2 recorded and this round applied to itself.

**3. Per-project test and verifier duplication.** Task 3.1 and 3.2 each
carried a full copy of the same acceptance module and verifier, and the copies
had **already drifted**: 3.2 gained a never-migrated-dir gate and an
evidence-count assertion that 3.1 never received, while 3.1's verifier kept
the `tools/` escape that 3.2's dropped. Four projects remained, so the drift
was about to be replicated rather than repaired.

The shared contract now lives in `tests/test_project_migration_contract.py`,
parametrized over `migration_specs.PROJECT_SPECS`; both projects run the full
current contract including the checks each was missing. `ProjectSpec` carries
the genuine per-project delta as data. `tools/verify_migration.py` takes a
slug or `--all` (898 duplicated lines to 532). Task 3.3 adds one `ProjectSpec`
instead of copying ~1200 lines that are already a version behind.

Two things generalising surfaced, both fixed test-first:

* The plant-key inventory in the first draft of the specs was *guessed* rather
  than sourced from the trackers, and the contract suite caught it
  immediately. The real 18 keys were re-derived from the live data.
* The harness's own git calls tripped the acceptance suite's `subprocess`
  booby-trap, so the strongest live-dir check could not be armed alongside the
  strongest side-effect check. `migration_harness` now binds the real `Popen`
  at import time — saving `subprocess.run` alone is insufficient, since it
  resolves `Popen` from module globals at call time. This costs no coverage:
  `tracker_migration` is statically proven to import no `subprocess`,
  `socket`, `urllib` or `http` at all, so the trap guards the code under test
  while the alias only guards the observer.

mule-fuel also gained an *executable* record of why its own routing-field
check is not discriminating (its registry `auto_create` equals the template
default), which fails if the registry ever changes — turning a comment that
can rot into an assertion that cannot. The unified verifier applies the same
reasoning at runtime: where the two agree it prints a NOTE rather than a PASS,
because a check that cannot fail is not evidence.

Mutation-tested throughout — registry override removed, a plant dropped, a
project field truncated, routing regexes stripped of backslashes, the
whitelist reinstated, directories fingerprinted by mtime, an over-broad
volatile classifier, `.git` mtimes, porcelain without `-z` — every one caught,
and the per-project mutations caught on BOTH projects.

Final state: 477 tests (was 402), 100% green, zero warnings (`pytest -W
error`); 72/72 out-of-band checks across both projects; `tracker.json` md5s
`f55be8df99b8e94606c19b3730b830e4` and `eb23369faf136231e3a801eb5f99612a`
unchanged, registry and the nested dashboard repo untouched.

## Task 3.2 review round 5: the git gate's *pre-existing dirt* blind spot

Round 4 replaced the suffix whitelist with a before/after baseline diff
(2c8869c/81c2038) and the round-4 write-up claimed the gate now catches "a
baseline-dirty path whose state merely *changes*". Review found that claim
was only half true, and that the underlying property was still not proven.

A before/after diff establishes **"this invocation changed nothing"**. The
acceptance claim the verifier actually makes is the stronger **"the migration
produced no side effects"**, and the two differ whenever the tree was already
dirty when the run began. Because the baseline is captured *inside* the run,
the gate adopts pre-existing dirt as its own allowance and never mentions it:
a stray artefact leaked by an EARLIER verifier run — precisely the side effect
this gate exists to catch — is laundered into the baseline. Reproduced against
the real repos: with `DECISIONS.md` modified and two untracked files planted
before launch, the verifier reported `ALL 35 CHECKS PASSED`.

Two further gaps shared the same root cause — the gate compared *two-character
porcelain codes* from a single invocation:

* **A porcelain code is not a content hash.** Appending to a file already at
  `' M'` (or an untracked file at `'??'`) leaves its code untouched, so the
  code diff is empty while the bytes moved. This is the case round 4 believed
  it had covered; only a code *transition* (`' M'` -> `'M '`) was ever caught.
* **A mid-run `git commit` returns porcelain to clean**, which is byte-for-byte
  indistinguishable from a run that touched nothing. HEAD is what moves, and
  `nested_repo_state` already checked HEAD for *nested* repos while the
  top-level gate did not.

`git_repo_state` now records HEAD sha + porcelain codes + a **sha256 digest per
non-clean path**, and `unexpected_repo_changes` diffs all three.
`describe_baseline_dirt` makes the allowance explicit, and the verifier asserts
pre-run cleanliness as a first-class check rather than assuming it. Untracked
*directories* are digested recursively, because porcelain collapses them to a
single `dir/` entry and a per-name digest would miss a file appearing inside.

Whether pre-existing dirt is acceptable is a caller's judgement — a task's own
in-flight edits are legitimate, a leaked sandbox file is not — so the harness
makes it visible and never decides silently. `--allow-dirty-baseline` drops
the cleanliness claim for a mid-task run and prints the dirt as a NOTE, so an
opted-out run cannot be mistaken for a clean one.

Each gap is pinned by a test that asserts the OLD code-only diff returns `[]`
for that input, so the new layer is provably what catches it rather than the
test passing for the pre-existing reason. Mutation-tested against the REAL
repos, not just fixtures: a mid-run append to a baseline-dirty file was caught
(`content changed while its porcelain code stayed ' M'`), and a mid-run commit
was caught (`HEAD: 647c7e1... -> 5275d0b...`) while porcelain read clean
throughout. Both mutations reverted, both repos restored to their committed
state.

Final state: 488 tests (was 477), 100% green, zero warnings (`pytest -W error`);
76/76 out-of-band checks across both projects on a clean tree (was 72 — the +4
are the new pre-run cleanliness claims, 2 repos x 2 projects); the reviewer's
dirty-baseline repro now FAILS with exit 1 and names every offending path.

## Task 3.3: the harness pays for itself, and multi-prefix routing

`kibungan-pheno-hunt` was registered by adding **one `ProjectSpec`** — 40 lines
of data. The 27-case shared acceptance contract parametrized over it
automatically and `tools/verify_migration.py` accepted the new slug with no
script written. No production migration code changed (`git diff` on
`tracker_migration.py`, `plant_markdown.py`, `project_markdown.py` is empty for
this commit). Task 3.2, by contrast, cost ~700 lines of duplicated acceptance
module plus a ~450-line verifier copy.

The project's value is that its data is the first to expose a real gap in what
the earlier projects could prove. `registry.json` gives it **two** plant-ID
prefixes (`PK` and `PL`) for one landrace population. Every project before it
had exactly one, so a migration reading `plant_id_prefixes[0]`, or flattening
the list, would have passed Tasks 3.1 and 3.2 unnoticed and then silently
stopped routing every `PL` Discord note — three of thirteen plants.

Two consequences, both kept in the shared layer rather than in this project's
module:

* **The gate's `plant_id_prefixes` tamper was too coarse.** It blanked the list
  to `[]`, which cannot distinguish a gate comparing the list's *contents* from
  one merely checking it is non-empty. With two prefixes the realistic
  regression is losing ONE entry: the list stays non-empty and stays correct
  for ten of thirteen plants. `verify_migration.py` now derives that tamper for
  any project with more than one prefix, and prints a `[NOTE]` for the ones
  whose data cannot express it instead of passing silently — the same
  honest-skip pattern already used for mule-fuel's non-discriminating
  `auto_create`.
* **String equality on a regex is not the property that matters.** The
  per-project tests compile the patterns *out of the migrated markdown* and run
  them against the real IDs and against realistic free text. This is not
  belt-and-braces: mutation-checked, stripping `(?i)` from the migrated file
  leaves every ID still routing correctly while `checked pk-7 today` stops
  matching, so an ID-only assertion would have called that migration clean.
  These patterns are also the first with `(?i)` and a `(?<![A-Z0-9])`
  lookbehind, which exercises YAML escaping far harder than `\bXX[\s\-]?\b`.

Two smaller firsts, both pinned: `google_sheet_url` is `''` while
`google_sheet_id` is `null` — the first project where the empty string and null
sit side by side, so a reader normalising one into the other round-trips
cleanly on both earlier projects and corrupts this one; and three plants carry
a human "Review and confirm." note whose text disagrees with the recorded
status. Migration preserves both verbatim: resolving a pending human decision
during a data move is data loss, the same reasoning that kept honey-badger's
factually stale `migration_note` intact.

Final state: 527 tests (was 488), 100% green, zero warnings (`pytest -W error`);
116/116 out-of-band checks across all three projects on a clean tree (was 76 —
the +40 are kibungan's own, including the new dropped-entry tamper);
`tracker.json` md5 `c1bb1e3bc31ec2f3ae0c0601e5a59647` unchanged, registry and
the nested dashboard repo untouched.

## Task 3.4: routing checks belong to every project, not to the one that found them

`paloma-coma` was registered with **one `ProjectSpec`**; the shared contract and
the spec-driven verifier picked it up with no per-project harness, the second
consecutive task where that held. No production migration code changed.

Its data closes a gap the earlier projects could not express: **all ten**
nullable plant columns — `sex`, `germ_date`, `veg_start`, `flower_flip`,
`harvest_date`, `vigor`, `structure`, `terpene_notes`, `issues`,
`selection_notes` — are null on every plant (50 of its 90 plant field values).
No earlier project has all ten empty at once, so it is the first data that can
catch a writer omitting an entirely-null column or a reader materialising only
keys it has seen carry a value; both round-trip mule-fuel, honey-badger and
kibungan cleanly and lose ten fields per plant here. The check is deliberately
two-layered — `is None` through the reader **and** `field: null` in the bytes —
because reading through the schema fills a *missing* key with the template
default, which is also `None`, so a reader-only assertion cannot tell a
preserved null from a re-invented one. Mutation-confirmed: dropping null-valued
keys in `write_plant` leaves the reader layer green and fails only the bytes.

The larger change is a correction to Task 3.3's own judgement. That task wrote
"compile the migrated patterns and actually route the real IDs" as a
**kibungan-only** test because two prefixes made mis-routing visible there
first. But nothing about the property is multi-prefix, and scoping it to the
project that discovered it left the other four single-prefix projects covered by
*string equality against `registry.json`* alone — which proves the migration
copied the registry faithfully and says nothing about whether the result routes
anything. That is the same duplication-by-omission that let Tasks 3.1 and 3.2
drift; the fix is the same as before, move it into the shared layer.

Two generic checks now run for every project, compiled out of the *migrated
markdown*: each pattern matches exactly its own family's real IDs with every ID
routed by exactly one pattern (which also catches a cross-family collision, not
expressible on a single-prefix project before), and each ID is found inside
`checked <ID> today` prose with the **captured group** equal to the right
number, while `X<ID>` must not match — the negative is what proves the boundary
construct survived rather than being silently dropped. The same check went into
`tools/verify_migration.py`, so it is proven out-of-band too.

Mutation-confirmed on paloma-coma, whose single `\bPC[\s\-]?(\d{1,2})\b` was
previously covered by equality alone: perturbing the registry pattern to a
plausible-looking but broken `\bPC[\s\-]?(\d{1,2}3})\b` leaves the migrated
markdown **equal** to the registry — equality check green — while it routes
zero of the five real IDs. Only the lifted behavioural check fails.

Kibungan's module keeps exactly what its data alone exercises: the `(?i)` flag
against lowercase text, the `[-#]?\s*` separator class, the `(?<![A-Z0-9])`
lookbehind against an alphanumeric neighbour, and the dropped-second-prefix
tamper. Its generic half was deleted, not left to drift alongside the contract's.

Final state: 589 tests (was 527), 100% green, zero warnings (`pytest -W error`);
171/171 out-of-band checks across all five projects on a clean tree (was 116);
`tracker.json` md5 `4e59e7b1896f885767824bbacbcef437` unchanged, registry and
every sibling project untouched.

## Task 3.4 code-quality review: two gaps in the lifted routing check

The check Task 3.4 moved into the shared harness carried two defects of its
own, both of the same shape — a condition the check *declared* it cared about
and then never exercised.

**The separator set could not express `#`.** `ROUTING_SEPARATORS` was
`("", " ", "-")` and was applied to every pattern uniformly. But kibungan's
live class is `[-#]?`: it advertises `#`, `PK#7` is a spelling people type,
and no probe ever sent a `#` through any pattern. The obvious fix — add `#` to
the universal set — is wrong: paloma-coma's `[\s\-]?` legitimately does not
route `PC#01`, so a universal demand turns a healthy project red. The set is
therefore per-pattern. `declared_separators` returns the universal three plus
every `ROUTING_OPTIONAL_SEPARATORS` entry the pattern's own character class
declares, so each pattern is held to exactly what it claims to accept.

That has a limit worth naming, because it is why the API grew a parameter: a
migration that *narrows* `[-#]?` to `[-]?` erases the evidence that `#` was
ever expected, so a self-derived probe set shrinks along with the bug and
stays green. The source registry pattern is the fixed point that does not
move, so `routing_failures` takes an explicit `separators=` map and both
callers pass the set declared by the **source**, holding the migrated pattern
to what the original advertised. Mutation-confirmed both ways: a pattern that
declares `#` and fails to route it is caught by the derived set; a class
narrowed away from `#` is caught only by the source set.

**The duplicate-prefix case was silently skipped.** The cross-project probe
opened with `if sibling_prefix.upper() in own_prefixes: continue`. That is
precisely the condition `breeding_core`'s registry validator *raises* on —
`prefix.casefold()` against `seen_prefixes`, because a message using a
prefix two projects both declare would route to two crosses. So the one
registry state production refuses to start on was the only collision this
check could never report, and it was skipped in the name of avoiding a
false positive. It is now a reported failure, compared case-insensitively the
way production compares it, with parity asserted against production's source
so the rule cannot drift into asserting something production dropped.

Both fixes are behavioural checks on scaffolding, not production code: no
migration code changed, and the registry, trackers and live project
directories are untouched.

Final state: 606 tests (was 589), 100% green, zero warnings (`pytest -W error`);
187/187 out-of-band checks across all five projects on a clean tree (was 171);
`tracker.json` md5 `4e59e7b1896f885767824bbacbcef437` unchanged.

## Task 3.5: the first migration that cost nothing but a spec

`spaced-paste` is the first Task 3.x instance whose entire diff is **one
`ProjectSpec` plus one per-project test module** — no production code, no
shared-harness change, and no new check lifted into the contract. Tasks 3.1
and 3.2 each cost ~1200 lines of duplicated test and tool; 3.3 and 3.4 each
still moved harness code. That the fifth project needed neither is the
harness's payoff, stated as an outcome rather than an intention.

**Lowercase IDs are a real gap, not a cosmetic one.** Every earlier project's
prefix is uppercase-initial (MG, HBH, PK/PL, PC, Ltz), so nothing in the corpus
could distinguish an ID-normalising migration from a correct one. `sp01`..`sp06`
makes case load-bearing in the per-plant **filename** — and that is the subtle
part: every shared field check locates a record by building
`plants/<id>.md`, so on a case-insensitive filesystem an upper-cased roster
answers to the same paths and passes the entire shared field-diff while
producing a tree that no longer matches the source on a case-sensitive one.
The check therefore compares against the real directory listing, not against a
constructed path. Mutation-confirmed: upper-casing `_plant_id` kills 11 of this
module's tests.

**Sorted source arrays were hiding a positional-pairing bug.** All four earlier
trackers store `plants` in sorted-ID order, so a migration that paired payloads
positionally against a sorted roster produced byte-identical output on every
one of them. `spaced-paste` stores `sp06, sp01, sp02, sp03, sp05`. The check
that catches it asserts on payload unique per record (`selection_notes` exists
on sp06 alone; each `observation_log` names its own source tab), because a
count or a field-set comparison cannot see a shuffle. Run against the shared
contract, this mutant fails on the `[spaced-paste]` parametrization **only** —
which is the evidence for the uniqueness claim, rather than a docstring
asserting it.

**`''` at plant level.** kibungan proved `''` and `None` are distinguishable at
*project* level (`google_sheet_url` vs `google_sheet_id`); `photos_drive_url`
is `''` on all five plants here, the first *migrated* project where that is
true of a plant field. (`lantz`, still unmigrated, has the same shape on all
four of its plants — so this is the first opportunity to catch the coercion,
not the only project that would expose it.)
Asserted in the raw frontmatter as well as through the reader, because reading
a missing key returns the template default and hides the difference — the same
reason Task 3.4 checks paloma-coma's nulls in the bytes. This project has both
at once: nine always-null columns *and* a neighbouring always-empty-string one,
so conflating them is live rather than stylistic.

**What was deliberately NOT done.** No check *unique to this project's data*
was lifted into the shared contract. Task 3.4 lifted kibungan's routing checks
because they were generic checks that happened to be discovered on one
project's data; the lowercase-ID, unsorted-array and empty-string-plant-field
checks are the opposite — each one is inexpressible on a project without those
properties, and parametrizing them over `PROJECT_SPECS` would produce four
vacuous passes per check. The premise of each is asserted separately
(`test_this_project_is_the_first_with_lowercase_plant_ids`,
`test_the_source_array_is_not_in_id_order`,
`test_photos_drive_url_is_the_empty_string_on_every_plant`) so the fixture
cannot silently stop discriminating.

**What WAS lifted afterwards (review follow-up).** The always-null-in-the-bytes
check was the exception, and it had already drifted the way Task 3.1/3.2's
copies did. paloma-coma and spaced-paste each carried their own copy of "every
column that is null on every plant must appear as `field: null` in the migrated
frontmatter", over a hand-maintained field list — while honey-badger-haze and
kibungan, whose data has the same nine always-null columns, had only a
reader-level check and never got the bytes-level one at all. The property is
generic (it is about the writer, not about any project's data); only the *field
set* is per-project, and that set is derivable from each tracker. It is now
`test_fields_null_on_every_plant_are_written_as_explicit_yaml_nulls` in the
shared contract, parametrized over `PROJECT_SPECS`, deriving the set by
intersecting keys across records first (so mule-fuel's MG07, which is *missing*
`photos_drive_url` rather than carrying a null, stays a defaulting question).
The per-project modules keep only the premise assertion that pins *which*
fields those are — ten at once for paloma-coma, nine-plus-a-neighbouring-`''`
for spaced-paste, nine-plus-a-populated-`selection_notes` for
honey-badger-haze. Mutation-verified: making `write_plant` skip `None` values
fails the new check on all five projects, and before the lift it failed on only
two.

**Routing flags are imported, never re-spelled.** spaced-paste's two routing
tests compiled the migrated patterns with a literal `re.IGNORECASE` instead of
`migration_harness.ROUTING_FLAGS`. The whole point of `ROUTING_FLAGS` is that
one constant carries production's flags and one assertion holds it to
`breeding_core._compile_prefixes`' source; a module that re-spells the literal
would keep testing the old matcher if production ever changed. Both now import
the constant, as kibungan's module and the shared contract already did.
Mutation-verified: flipping `ROUTING_FLAGS` to `re.NOFLAG` now fails
spaced-paste's case-insensitivity test, which it did not before.

Final state: 659 tests (was 656 at Task 3.5's close, 606 before it), 100%
green, zero warnings (`pytest -W error`);
232/232 out-of-band checks across all five migrated projects on a clean tree
(was 187 across four); `tracker.json` md5
`dee45e00a1ae55cfa71463f2a45ac358` unchanged.
