# Decisions — monitor-core (Phase 2, markdown-backed persistence)

Companion to `breeding-markdown/DECISIONS.md`, which records Phase 1's
decisions for the shared markdown library. This file follows the same
convention: one section per task / review round, written at the time the
decision was made. Where a decision here depends on one made there, it is
cross-linked rather than restated.

## Task 2.1 — `plants/<ID>.md` collision, and the policies settled fixing it

Task 2.1 swapped `breeding_core`'s persistence backend (`tracker.json` ->
`project.md` + `plants/<ID>.md`) under the contract *"same parsing and
status-detection logic, only persistence calls change"*.

### The collision itself: `update_markdown` was destroying the plant record

`plants/<ID>.md` became the authoritative record, written by `save_tracker`
via Phase 1's `plant_markdown.write_plant`. But the JSON-era
`update_markdown()` still wrote its own **derived view** — a lossy 3-key
projection — to that same path, and `update_plant()` called it immediately
after `save_tracker()`. One `process_message()` call shrank a real 19-field
Lantz plant to 4 keys and renamed `id` to `plant_id`, so the *next*
observation raised `KeyError('id')`.

Fixed by treating the derived view as fully redundant with the record:
`update_plant()` no longer calls `update_markdown()` at all (the file was
already written), and `update_markdown(plant, breeding_dir)` keeps its
signature — all six wrappers expose it — but now persists the plant RECORD
via a new `markdown_backend.save_plant()`, a non-destructive merge over the
file on disk, so a standalone wrapper call is safe and idempotent.

`observation_log` is documented and regression-tested as the one deliberate
exception to exact key-set preservation: Phase 1's `read_plant` always
returns the body, and all real plants already have it.

### POLICY: fail loud on a corrupt plant file (review round 1)

One unparseable `plants/<ID>.md` makes the **whole** project load raise;
there is no per-plant isolation. This was kept deliberately, not softened to
skip-and-warn, because `plants/<ID>.md` is now the record of truth: a skipped
plant would be absent from the returned roster, and `save_tracker`'s
whole-roster rewrite semantics would DELETE its file on the very next Discord
observation — turning one recoverable parse error into permanent data loss.

`migration.py`'s per-repo isolation is explicitly **not** a precedent here:
each repo there is an independent, retryable unit with no cross-repo delete
semantics. Documented in both `markdown_backend.load_tracker` and
`breeding_core.load_tracker` docstrings, and pinned by a regression test.

### `save_tracker` atomicity: staged render, not a narrowed comment

The pre-existing comment promised *"a bad id halfway through must not leave a
half-written project on disk"*, but the pre-pass only validated ids and
duplicates. Reproduced empirically: an unserialisable value on plant #3 of 4
left plants #1–#2 rewritten AND `project.md` rewritten with the new
`plant_order`.

Fixed with a render pass — `project.md` and every plant are rendered in full
into a scratch dir inside the project dir before any real path is touched —
so every failure this code can raise now happens before the first real byte is
written. Chosen over narrowing the comment because the diff is small and it
closes the actual gap. Chose to **re-render** rather than move the staged
files into place: moving would bypass Phase 1's existing-file-mode
preservation and silently downgrade git-tracked files to `0600`.

The docstring states the residual limit honestly: per-file writes are atomic
(`mkstemp` + `os.replace`), but the roster is not one filesystem transaction,
so a mid-sequence ENOSPC or crash can still leave some files updated.

### `p.get('id')` hardening

`update_plant`'s roster scan used a bare `p['id']`, raising an opaque
`KeyError('id')` for an id-less plant *before* `save_tracker`'s clean
`ValueError("plant record has a missing or non-string id")` could surface.
Now `p.get('id')`, so the informative error wins.

### `_ALWAYS_PRESENT_PLANT_KEYS`: defense in depth over deletion

The constant was defined and documented as the mechanism exempting
`observation_log` from the restrict-to-present filter, but
`_restrict_to_present` never read it — the behaviour came for free from
Phase 1's `read_plant` contract, making this module silently dependent on an
implementation detail of another repo. `_restrict_to_present` now takes an
`always_keep` set and both plant call sites pass the constant. Cost is one
parameter; the alternative (delete the constant, document the dependency)
leaves a cross-repo coupling that fails silently by dropping every plant's
observation log.

## Task 2.2 — vigor `int` -> `str` is an ACCEPTED, USER-APPROVED deviation

Task 2.2 pinned NICK-592's parsing / status detection behind a committed,
versioned fixture and asserted every case differentially against the JSON-era
implementation. Exactly **one** genuine deviation surfaced.

**What it is.** `vigor` round-trips as a string (`'9'`) under markdown where
JSON kept an int (`9`).

**Scope: persistence only.** `parse_observation()` still returns an `int` and
`update_plant()` still assigns that `int` to `plant['vigor']` in memory —
byte-identical logic to the JSON era, and both facts are asserted against the
baseline module. The type changes only on the round-trip through
`plants/<ID>.md`.

**Cause.** Phase 1's canonical, Joey-approved `plant-template.md` declares
`vigor` as a free-text **string** (`'strong'`/`'weak'`/`'average'`), not an
integer. See `breeding-markdown/DECISIONS.md` -> *"Task 1.1 spec-compliance
review findings (2026-09-05)"*, whose first bullet records that an
unapproved integer `vigor` (0–10 rating) was explicitly **reverted to
canonical string**. The schema-typed read therefore coerces `9` -> `'9'`.

**Decision: accept as intentional, do not "fix".** Making vigor survive as an
int would require editing an approved schema Task 2.2 is forbidden to touch,
and would re-introduce the exact change Phase 1's review reverted. Joey was
shown the deviation and explicitly approved accepting it rather than
silently absorbing it. Real-world impact is nil: vigor is null on all 95 real
plants and has never been populated in production. The contract this task
exists to protect is unaffected — `plant['status']` is identical under both
backends for all three status keywords.

Recorded in three places so it cannot be lost: the fixture's
`known_deviation_from_json_era` block, a dedicated pinning test
(`test_vigor_is_stored_as_a_string_by_the_markdown_backend`), and a
per-case `vigor_type_deviation` flag whose test asserts the affected cases
differ from their JSON-era expectation in **exactly** one way — `str(vigor)`
— so any drift beyond the coercion fails loudly.

### Pre-existing JSON-era quirks: PINNED, not endorsed

The following are **not** decisions made by Phase 2. They are JSON-era
behaviours the fixture pins so that a silent change fails the suite. Pinning
them is not an endorsement, and changing any of them is a product decision
rather than a refactor:

- **`structure` is parsed but never persisted.** `parse_observation` fills
  `observation['structure']` and `update_plant` puts it in the Discord reply
  summary, but it is never written to `plant['structure']`, which stays
  `None`. Pinned by `test_structure_is_reported_but_never_persisted`.
- **`vigor 0` parses but is never persisted.** `update_plant`'s field-merge
  guard is a plain truthiness check, so a parsed vigor of `0` is falsy and
  silently dropped.
- **Structure keywords are prefix-matched and record the raw regex source**
  (`'fox.*tail'` is stored literally, and the wildcard spans a space), while
  terpenes are whole-word matched (`'fueled'` does not match `'fuel'`).

Also known and deliberately **out of scope** for this pass: latent
status-keyword parsing bugs surfaced as a side-effect of the review
(hyphen / double-space degradation, and false-positive `'non-keeper'` /
`'do not cull'` matches). These are pre-existing JSON-era behaviour. Fixing
them means changing the actual parser, which needs a product decision Joey
has not yet made — so they are recorded here and left untouched.

## Task 2.2 code-quality review round 1 (2026-09-05)

Round 1 APPROVED Task 2.2 (zero Critical, zero production-code risk); the two
Important findings below were code-quality issues in the test suite itself.

### Important #1: the baseline loader failed open

`test_nick592_parsing_spec.py`'s `_json_era_module()` obtained the JSON-era
source by shelling out to `git show 2dd0537:breeding_core.py` and calling
`pytest.skip()` when that failed. The reviewer proved empirically that
repointing `BASELINE_COMMIT` at a dead SHA made the suite **exit 0 with 28
silent skips** — the entire differential guarantee evaporating without
failing CI. Nothing pinned commit `2dd0537`: no tag, no branch, no remote.

Fixed by committing a frozen, byte-for-byte copy of the baseline source as
`tests/fixtures/baseline_breeding_core_2dd0537.py` and `exec()`-ing that.
This removes the subprocess and the live-history dependency entirely, and
makes the suite runnable from a tarball or any non-git export. Chosen over
the alternatives (tag the commit; make the skip loud) because a tag is still
a mutable, deletable pointer into history the repo does not control, whereas
a committed file travels with the tests that depend on it.

**There is deliberately no skip path left in the loader.** A missing snapshot
is a hard failure, and `test_baseline_loading_never_silently_skips` parses
the loader's own AST to assert it contains no `pytest.skip`, no `subprocess`,
and no `git` — so the fail-open shape cannot be reintroduced quietly.

The git cross-check is kept, demoted to **optional**:
`test_frozen_baseline_matches_git_history` compares the frozen copy against
`git show` when history happens to be available, catching drift where it can,
and skips (loudly, with a reason stating the differential tests all still
ran) where it cannot. That skip is safe precisely because nothing else in the
file depends on git.

Verified: with the `git` binary removed from `PATH`, all 28 previously-
skipping differential tests now pass; with the snapshot deleted, the suite
fails hard rather than skipping.

### Important #2: this file did not exist

`monitor-core` had no `DECISIONS.md`, though `breeding-markdown` established
the convention firmly across Phase 1. The user-approved vigor coercion
decision existed only in a commit message, a JSON fixture block, and a test
docstring — none of which a reader looking for "what did we decide and why"
would find. This file is that record, backfilled for Tasks 2.1 and 2.2 from
the commit messages and review comments in this repo.

### Minor: keyword coverage was asymmetric

`test_fixture_covers_every_required_behavior` asserted that every
`TERPENE_KEYWORDS` entry appears in some case's text, but made no equivalent
assertion for `STRUCTURE_KEYWORDS` — independently confirmed, not taken on
the reviewer's word. A literal text check cannot work for
`STRUCTURE_KEYWORDS` because `'fox.*tail'` is a regex whose source never
appears verbatim in an observation. The check is therefore made against the
recorded **parse results** instead, which is both correct and stricter: the
parser records the regex source, so `'fox.*tail'` must actually have been
matched by some case rather than merely mentioned.
