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
