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
