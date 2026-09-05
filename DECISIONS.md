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
