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

## Task 2.3 — `push_to_github()` now publishes the data repo, and keeps publishing the dashboard

Task 2.3 rewrote `push_to_github()` for the markdown backend. The JSON-era
function was pure `git`, not the GitHub REST API — `git add .` / `git commit`
in `breeding_dir/'dashboard'`, then `git push https://$TOKEN@github.com/<repo>.git main`.
So there was never an API surface to sandbox; the whole function is testable
against a throwaway local bare repo, and the entire Task 2.3 suite pushes only
to `git init --bare` targets under `tmp_path`.

### The bug Task 2.1 left behind: this function was still pointed at the dashboard

Tasks 2.1/2.2 changed *what an observation writes* (`project.md` +
`plants/<ID>.md`) but not *what gets published*. `push_to_github()` still
committed only `dashboard/`, so after 2.1 an observation mutated the markdown
record of truth and pushed **none of it** — the data repo never received a
single commit. Verified, not assumed: the pre-change function's paths do not
mention `project.md` or `plants/` anywhere.

### POLICY: the dashboard push STAYS, transitionally

The obvious fix — repoint the function at `breeding_dir` — would have been a
silent production outage. Checked against the real filesystem: today all six
projects have a git repo at `dashboard/` (each with a live GitHub Pages
`origin`) and **none** of the six project dirs is a git repo at all. A
markdown-only push would therefore have frozen all six live dashboards for the
entire Phase 3–7 window while pushing nothing anywhere.

So the function pushes **both** repos, each fully independently via a shared
`_push_repo()` helper that no-ops on a missing `.git`. That makes every
lifecycle shape work with no code change: dashboard-only (today), both
(mid-cutover), data-repo-only (after Task 7.3 removes `dashboard/`). **Task
7.3 should delete the second `_push_repo` call** — that is the intended
removal point, recorded here so it is not left behind as mystery code.

### Staging is path-limited for the data repo, `.` for the dashboard

`git add .` is correct for `dashboard/` (generated HTML only) but wrong for a
project dir, which also holds `tracker.json`, `cache/`, `photo_staging/`,
`__pycache__/` and `save_tracker`'s own `.save_tracker-staging-*` scratch
dirs — a blanket add would publish staged photos and legacy JSON into a
private data repo. The data repo therefore stages exactly
`git add --all -- project.md plants`.

`--all` rather than a plain path-limited add is load-bearing: `save_tracker`'s
whole-roster semantics *unlink* a dropped plant's file, and without `--all`
that deletion is never staged, so the plant would live on the remote forever
while being gone locally. Pinned by its own test.

### Empty-commit suppression, and Phase 1's push-stranding lesson

The JSON-era code ran `git commit` unconditionally and only pushed *if a token
was set*. Both are now fixed: a commit is skipped when nothing is staged (no
more one-commit-per-Discord-message churn), and the push is attempted whenever
an `origin` exists — even when this call staged nothing — because a previous
run may have committed while the remote was unreachable. That is exactly the
push-stranding failure `breeding-markdown/DECISIONS.md` records from Task 1.3,
applied here rather than re-learned. Likewise `HEAD:refs/heads/<branch>` with
an explicit detached-HEAD refusal, from the same source: the JSON era
hardcoded `main`.

### The token no longer goes in a URL — and no longer goes in the argv either

`https://$TOKEN@github.com/...` writes the credential into anything that logs
the argv or the remote. The token is now supplied as an `http.extraHeader`, so
it never reaches `.git/config` or `git remote -v` — asserted by a test.
`github_repo` is consequently unused for URL construction; it is kept in the
signature because all six wrappers pass it, and each push targets that repo's
own `origin`.

**Round-1 correction (Important #3).** The header was originally passed as a
`-c http.extraHeader=...` *argv* flag, which is a real (if smaller) exposure:
argv is world-readable through `/proc/<pid>/cmdline` and `ps -ef` for the
lifetime of the push — this host does not mount `/proc` with `hidepid` — and
git re-exports `-c` settings to `git-remote-https` via
`GIT_CONFIG_PARAMETERS`. The credential is now passed through the
**environment** instead:

```
GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0=http.extraHeader
GIT_CONFIG_VALUE_0=Authorization: Basic <b64>
```

which git honours identically (verified: `git config --get http.extraHeader`
reads the value back through those variables).

**Residual exposure, stated plainly so the claim is not read as stronger than
it is.** This is a strictly smaller surface, not zero. `/proc/<pid>/environ` is
readable by the same uid and by root, and git still propagates the config to
its `git-remote-https` helper child. What changed is that the secret is no
longer *world*-readable to every local user via argv. An attacker already
running as this uid (or as root) can still read it — as they could read the
1Password-provisioned `GITHUB_TOKEN` in the gateway process's own environment
anyway, so the env route adds no new capability to that attacker.

`test_token_never_appears_in_any_subprocess_argv` pins this positionally: it
fails if the raw token, its base64 Basic form, or the string `extraHeader`
appears in *any* element of *any* argv (the previous test only checked
`.git/config` and `remote get-url`, and would have passed unchanged had the
token moved to a different argv position). Confirmed empirically out-of-band
by scanning `/proc/*/cmdline` during 40 real local pushes: zero hits with the
env route, and the same scanner reports LEAK against the old `-c` form.

### POLICY: best-effort and never-raising, with a stderr WARN as the operator signal

`push_to_github()` runs inside the Discord message handler. An exception here
does not just lose a push, it breaks the ingestion reply — so every git call is
best-effort and the function never raises. That is deliberate and stays.

**Round-1 correction (Important #1): never-raise had become never-tell.** Every
git failure was swallowed with no return value, no exception and no output, so
a wedged remote was indistinguishable from a healthy one. Reproduced by the
reviewer: diverging `origin` and pushing three times produced three stranded
local commits, zero stderr, zero signal.

The chosen signal is the idiom this module already uses for exactly this class
of non-fatal error in exactly this path — `update_plant`'s failed-photo-upload
warning:

```
print(f"WARN: git {action} failed in {repo}: {result.stderr.strip()}", file=sys.stderr)
```

It needs no new infrastructure, is inherited by all six wrappers, and is
captured by `hermes_gateway.py`'s logging. `add`, `commit` and `push` failures
each warn. The argv is deliberately **not** echoed in the warning — that is the
one place a credential could re-enter a log line (see Important #3 above).

**Round-1 correction (Important #2): never-raise was not actually absolute.**
`subprocess.run` can fail *before* the child process exists —
`FileNotFoundError` when git is not on `PATH`, or any other `OSError` (EACCES
on an unexecutable git, ENOMEM). The reviewer verified that with an emptied
`PATH` this propagated straight out of `push_to_github()` into the message
handler: precisely the crash-the-bot outcome the design exists to prevent.
`_git()` now catches `OSError` and returns a synthetic
`returncode=1` result, so exec failures and non-zero exits flow through one
code path and get the same WARN treatment.

### Failure paths are tested, not just asserted in prose

`tests/test_push_failure_paths.py` pins the two policies above: non-fast-forward
rejection against a diverged local bare remote (no raise, local commit survives,
remote unmoved, WARN emitted — and each of three repeated attempts warns), a
deleted/unreachable `origin`, a stale `.git/index.lock` before the add step,
an emptied `PATH`, and a monkeypatched `OSError` from `subprocess.run`. All use
local bare repos, filesystem tricks or a broken binary lookup — no network.

### Minor round-1 fixes folded in

* `_push_repo`'s local `config` was renamed `auth_env`; `config` shadowed the
  project-config dict this module uses elsewhere.
* `git diff --cached --quiet` is now tested for `returncode == 1` ("there are
  staged changes") rather than `!= 0`, so a genuinely broken repo (rc >= 128)
  is not misread as having something to commit.

### Test-suite safety

Beyond using local bare repos, `test_no_command_ever_mentions_github_com`
records every argv the function issues and fails if any names `github.com` or
any http(s) URL, and an autouse fixture strips `GITHUB_TOKEN` from the
environment for every test in the module — an ambient real token cannot leak
into a test push.

## Task 2.4 — the "NICK-592 multi-cross cycling test" was prose, not an artifact

Task 2.4's spec says to *"replay the NICK-592 multi-cross cycling test"*. **No
such runnable artifact exists** — searching this repo, `breeding-markdown`,
all six wrappers and the full git history for `NICK-592` / `multi-cross` /
`cycling` returns only prose:

* `breeding_core.py`'s module docstring — NICK-592 consolidated six drifted
  per-project copies of the pipeline after NICK-589 found Mule Fuel, Lantz and
  Spaced Paste missing keeper/culled detection entirely.
* every wrapper's comment about the gateway plugin *"cycling through crosses in
  one long-lived process via `importlib.reload()`"*. **That** is the "cycling":
  one process, one shared `breeding_core`, six crosses handled in turn, each
  with its own `BREEDING_DIR`, roster, ID pattern and `AUTO_CREATE` policy.

So the cycling test was an ad-hoc historical verification. It is now a
committed artifact: `tests/test_multicross_regression.py`. Recorded here so no
later task re-hunts for a script that never existed.

### What the committed replay does

One module-scoped pass cycles **round-robin** through sandboxed copies of all
six real projects — one observation per project per round, 25 rounds — driving
the complete pipeline (`parse_observation` -> `update_plant` -> `save_tracker`
-> `markdown_backend` -> `push_to_github`). Starting state is each project's
**real** `tracker.json`, copied in and migrated through the new backend;
observation text is Task 2.2's committed 24-case fixture, addressed to that
project's real roster IDs, plus one novel ID that exercises `AUTO_CREATE` on
the three pheno hunts and the ❌-not-found branch on the three doc-imported
rosters.

Verification is the two-armed shape Task 2.2 established:

1. **Differential.** The identical observation sequence runs against a second
   copy of the same real starting data on the FROZEN JSON-era implementation
   (`tests/fixtures/baseline_breeding_core_2dd0537.py`). Every plant of every
   project must match field for field. Both arms are fed the *same* parsed
   observation dict — `parse_observation` stamps `datetime.now()`, and parser
   equivalence is already pinned differentially by
   `test_nick592_parsing_spec.py`.
2. **Byte-for-byte against the fixture.** The auto-created plant is the one
   plant in the pass that starts from a fresh `make_blank_plant()` — exactly
   the state `plant_after` was derived against — so its fields and the Discord
   reply string must equal the fixture verbatim.

### DISCREPANCIES: exactly one, and it is the already-approved deviation

Across all six projects and every plant, the only field that ever differed
between the JSON era and the markdown era was `vigor` (`9` -> `'9'`) — the
deviation documented above under *Task 2.2*, caused by Phase 1's approved
`plant-template.md` typing `vigor` as free text. The differential tolerates it
**only** as `str(json_value)`; any other vigor drift, and any drift in any
other field, fails. No new bug surfaced, and no production code changed in this
task.

### POLICY: non-vacuity guards, because this suite is mostly conditional

Three assertions here could silently degrade into zero coverage, so each has an
explicit guard:

* `test_the_fixture_comparison_is_not_vacuous` — exactly the three pheno hunts
  must auto-create, so the byte-for-byte comparison always runs on three
  projects rather than skipping all six.
* `test_every_project_replayed_the_whole_fixture` — all 24 cases + the novel ID
  per project; a trimmed fixture or short-circuited round-robin would otherwise
  pass everything trivially.
* `test_the_vigor_deviation_is_actually_exercised` — at least one plant must
  actually show the tolerated coercion, or the differential's one tolerance is
  itself untested.

The suite was also mutation-checked: reverting `update_plant`'s status
assignment for `culled` (NICK-589's original bug, the exact defect NICK-592
existed to prevent) turns it RED in 10 tests.

### POLICY: the replay is module-scoped, and that is load-bearing

A function-scoped replay re-ran the whole six-project, two-backend pass for
each of ~40 tests: 6.5 minutes and enough small-file churn to hit `Disk quota
exceeded` on the tmpfs backing `tmp_path`. The pass is deterministic apart from
timestamps, so it runs **once** per session (~35 s) via a `scope="module"`
fixture. Consequences, both deliberate:

* `monkeypatch` is function-scoped and therefore unusable in it; `BREEDING_DIR`
  / `BREEDING_DISABLE_PUSH` are set and restored by an explicit
  `_sandbox_env()` context manager instead.
* Tests must not mutate the shared state. `test_reloading_the_markdown_is_idempotent`
  round-trips into its own `tmp_path`, not the replay's sandbox.

### Sandbox proof is taken from the pass itself, not a re-run

The `replay` fixture checksums every file under all six **real** project dirs
(and under `breeding-markdown`) immediately before and after the pass and
returns the digests, so the isolation tests assert on THIS pass rather than an
extra one. `__pycache__` is excluded: importing a wrapper legitimately rewrites
bytecode in the real dir, which is not a data change. Pushes go to a throwaway
local bare repo per project under `tmp_path`; `test_no_replay_targets_a_real_remote`
fails if any origin names `github.com`. No Discord, Drive or network call
anywhere. `generate_dashboard.py` is deliberately not copied into the sandbox,
so `update_plant`'s dashboard subprocess is a harmless, already-unchecked no-op.

## Task 2.5 — project routing became DATA, in a new local-only `breeding-meta` repo

### The plan described a `_CROSS_DIRS` dict that never existed

Task 2.5's brief was "replace the hardcoded `_CROSS_DIRS` dict in
`breeding_core.py` with a read of `registry.json`". Reading the actual file
first: there is no `_CROSS_DIRS` dict, and there never was. `breeding_core.py`
knew *nothing* about which projects exist — every one of the six
`monitor_breeding_notes.py` wrappers hand-built its own complete `CONFIG` dict
and passed it in.

So the coupling the task exists to fix is real, but it was **distributed across
the six wrappers** rather than centralized in one dict. The consequence is the
same one the plan cared about: adding a seventh cross required authoring a
seventh wrapper — a code change. We implemented the smallest mechanism that
actually removes *that* coupling rather than inventing a `_CROSS_DIRS` dict
just so we could delete it.

### `breeding-meta` is local-only, with no GitHub remote

Created at `~/.hermes/breeding/_shared/breeding-meta/` as a plain local git
repo (`git init`, one commit, **no `origin`**), matching how `monitor-core` and
`breeding-markdown` were created.

Deliberately not a real GitHub repo: creating one is an account-level action
with a blast radius outside this refactor (visibility, org placement, branch
protection, whether the ingestion credential is scoped to reach it). None of
that is needed to satisfy Task 2.5 — the acceptance criterion is about routing
coming from data instead of code, which a local clone proves exactly as well.
Adding an `origin` later is a one-line `git remote add`; `refresh_meta_repo()`
already handles both shapes with no code change, and the no-remote case is a
silent no-op rather than a warning precisely because local-only is a *valid*
configuration today, not a degraded one.

The plan's "use the existing ingestion credential, a private git clone, not an
HTTP call to the gated API" is therefore satisfied by construction: the read is
a filesystem read of a git checkout. No new auth exception is needed for a
headless script, which was the point of that clause.

### `refresh_meta_repo()` never raises — a stale registry beats a dead bot

`load_registry(pull=True)` `git pull --ff-only`s the checkout before each
ingestion run so a newly added project routes on the very next message. That
pull inherits Task 2.3's never-raise rule verbatim (`_git` + `_warn`), and the
reasoning is even stronger here than for pushes: **a stale registry still
routes every existing project correctly.** Losing a live observation because
GitHub was briefly unreachable is strictly worse than routing off a checkout
that is a few minutes old. A failed pull emits `WARN: git pull failed ...` on
stderr and ingestion proceeds on last-known-good data.

`--ff-only` is intentional: the consumer clone is read-only in practice, so a
divergence means something is wrong locally, and a merge commit created inside
a Discord handler would be worse than a warning.

Three cases are silent no-ops rather than warnings — no checkout, a non-git
directory, no `origin` — because each is a legitimate local/sandbox setup. A
non-zero `git remote` *is* warned about, since that means the git binary itself
could not run.

### Reading the registry FAILS LOUD, unlike pulling it

Asymmetric on purpose. A failed refresh is recoverable (old data still works);
a malformed `registry.json` is not — routing on a half-parsed registry sends
observations to the wrong cross or nowhere at all. So `load_registry()` raises
`FileNotFoundError` (naming `BREEDING_META_DIR`, following Task 2.1's
`BREEDING_MARKDOWN_DIR` error-message precedent) and `ValueError` on bad JSON,
an unsupported `schema_version`, a missing `slug`, a project with no prefixes,
or a **prefix claimed by two projects**. That last check is the one that earns
its keep: a duplicated prefix is silent data corruption, not an error anyone
would notice.

Same fail-loud-on-corruption call already made for plant markdown in
`load_tracker` (Task 2.1).

### What the registry stores, and what it derives — the flagged judgment call

The task flagged this as a genuine ambiguity. Resolved by reading what
`update_plant`/`process_message`/`push_to_github` actually *require* per
project and storing exactly that, minus anything derivable:

Stored: `slug`, `cross_name`, `breeding_dir`, `github_repo`, `auto_create`,
`plant_id_prefixes` (a list of `{prefix, pattern}`).

Derived, never stored:

* **`TRACKER_FILE`** — always `BREEDING_DIR / 'tracker.json'` in all six
  wrappers. Storing it invites drift with zero benefit.
* **`DISABLE_GITHUB_PUSH`** — read from `BREEDING_DISABLE_PUSH`, as every
  wrapper does. It is a per-run operational switch (and the test sandbox's
  safety catch), not a property of a project. Putting it in the registry would
  make a *data* commit able to silence pushes globally.
* **single vs multi prefix** — one prefix yields
  `PLANT_ID_PATTERN`/`PLANT_ID_PREFIX`; two or more yield `PLANT_ID_REGISTRY`
  (Kibungan's `PK` + `PL`). One uniform representation in the data, with the
  existing two-shaped config produced on demand, so `process_message` needs no
  change and nothing downstream can distinguish a registry-built config from a
  wrapper-built one.

`GITHUB_REPO` *is* stored: it is genuinely per-project and already a required
config key, even though Task 2.3 reduced it to signature-compatibility baggage
(pushes now go to each repo's own `origin`).

`test_registry_config_matches_the_wrappers_hardcoded_config` asserts the
registry-derived config equals the real wrapper's `CONFIG` field-for-field for
all six projects — the guard against `registry.json` being a plausible-looking
parallel invention that has quietly drifted from reality.

### Templates are NOT duplicated here

`breeding-markdown` owns `templates/plant-template.md` and
`templates/project-template.md` (Phase 1, approved). `breeding-meta` holds only
`registry.json` and a README. Copying the templates would create a second
canonical source and guarantee divergence.

### The six live wrappers were NOT migrated

Out of scope, and left deliberately untouched: all six are still byte-identical
(pinned by SHA-256 in both `test_wrapper_compatibility.py` and
`test_task_2_5_did_not_touch_any_real_wrapper`) and still route off their own
`CONFIG` dicts. `registry.json` describes them accurately and `route_message()`
routes them correctly, but nothing in production consumes it yet — this task
builds and *proves* the mechanism; adopting it is a later task.

The acceptance criterion is consequently proven with a fictional **seventh**
project rather than a real one, exactly as the task specified: a sandbox
authoring clone adds `zephyr-quartz` to `registry.json` and pushes it to a
throwaway local bare remote; the consumer clone (still stale — asserted) then
routes `"ZQ 12 top keeper, vigor 9"` to it, with `breeding_core.py`'s SHA-256
asserted identical before and after. A second test feeds that registry-derived
config straight into `process_message` and confirms it creates and persists
`plants/ZQ12.md` with `status: top_keeper` — proving the config is genuinely
usable, not just a lookup that returns a plausible dict.
