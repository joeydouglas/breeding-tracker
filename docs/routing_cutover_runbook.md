# NICK-924 (Task 7.2b) — Routing-mechanism cutover runbook

This is the operational procedure for flipping a project's Discord routing
from the hardcoded `_CROSS_DIRS` dict (in
`breeding-ingest/integrations/hermes-breeding-ingest/__init__.py`) to
`registry.json`-driven routing, one project at a time. The mechanism itself
is built and tested (`tests/test_nick924_routing_cutover.py`); this document
is acceptance criterion (c) — the recovery procedure that code alone cannot
prove.

## Current state (as of this commit)

Every real project's `registry.json` entry has `routing_active` ABSENT
(falsy). Live routing behavior for all 6 projects is **unchanged**.
`test_real_registry_has_no_project_migrated_yet` fails loudly if this drifts
without a deliberate decision.

## How the mechanism works

`_resolve_breeding_dir(prefix)` in the gateway plugin checks `registry.json`
first. If that project's entry has `routing_active: true`, its
`breeding_dir` field (read fresh from `registry.json`, not a code constant)
wins. Every other prefix — entry absent, `routing_active` absent/false, or
ANY failure reading/parsing `registry.json` at all — falls back to the
original, unedited `_CROSS_DIRS` dict.

## To cut one project over

1. Confirm criterion (a) still holds for this project: its
   `registry.json` prefix pattern(s) match the gateway's own live
   `PLANT_ID_REGISTRY` pattern exactly (this was fixed for all 6 projects in
   the NICK-924 prerequisite commit — re-verify only if either side has
   since changed).
2. In `breeding-meta/registry.json`, set `"routing_active": true` on that
   project's entry. Commit and push (the gateway reads `registry.json` live
   from disk on every message — no redeploy needed, but the breeding-meta
   checkout on this machine must have the change, i.e. `git pull` if edited
   remotely).
3. Post ONE real, low-stakes test observation to that project's actual
   Discord prefix (same canary pattern as Task 7.2's backend cutover —
   Lantz is the standing low-stakes canary for a reason).
4. Verify:
   - The observation landed in the correct project's `plants/<ID>.md` (not
     some other project's).
   - `tracker.json` for that project is unchanged (still markdown-backend
     as expected, or whatever Task 7.2's backend state already was for it —
     this cutover axis is independent of the backend axis).
   - No other project's dashboard or tracker shows any trace of the
     observation.
5. Only after that single canary is confirmed clean, resume normal
   ingestion for that project under the new routing.

## Recovery: an observation misrouted to the wrong project during cutover

This is a **data-repair** procedure, not a config revert — reverting
`routing_active` does not un-write an already-committed observation.

1. **Stop.** Set `"routing_active": false` (or delete the key) for the
   affected project in `registry.json` immediately — this alone prevents
   ANY further messages from taking the bad path, with zero effect on the
   other 5 projects (proven by
   `test_reverting_routing_active_instantly_restores_hardcoded_path`).
2. **Identify exactly what was written and where.** The misrouted
   observation will be a real, timestamped block in the WRONG project's
   `plants/<ID>.md` (`### <timestamp>` header + the raw message text) or a
   git commit to the wrong project's data repo. Cross-reference the
   Discord message's real timestamp against that project's git log /
   markdown observation blocks — this is the exact same technique NICK-979's
   investigation used to find the earlier "#07 pollution" orphans (see
   `~/.hermes/backups/NICK966-20260907-123240/ORPHAN-OBSERVATIONS-PRESERVED.txt`
   for that precedent's format).
3. **Remove it from the wrong project.** Edit that `plants/<ID>.md` to
   delete the misrouted observation block, commit with a clear message
   referencing this incident, push.
4. **Re-ingest it into the RIGHT project**, either by:
   - Manually running that project's real
     `monitor_breeding_notes.process_message()` with the original message
     text (preserves the exact wording), or
   - If the observation's timing matters for the record, add it directly to
     the correct `plants/<ID>.md` with the observation's original real
     timestamp (not "now") so the historical record stays honest.
5. **Verify with NICK-967's reverse-migration tool**: run a dry-run
   rollback rehearsal against BOTH the wrongly-written and correctly-written
   projects post-repair, confirming the wrong one no longer contains the
   text and the right one now does — the same zero-loss verification
   standard as every other Task 7.2 cutover.
6. Only resume the cutover (re-enable `routing_active`) after the specific
   defect that caused the misroute is understood and fixed — not on a
   blind retry.

## Full Phase 7 completion (criterion d)

Phase 7 is not complete until all 6 projects have `routing_active: true` in
`registry.json` AND each has passed its own single-canary verification per
the procedure above. Track per-project completion as separate Multica
sub-items under NICK-924, mirroring Task 7.2's own per-project structure.
