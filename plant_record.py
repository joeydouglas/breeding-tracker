#!/usr/bin/env python3
"""The plant record's identity field -- which key holds a plant's ID.

WHY THIS MODULE EXISTS (NICK-965). A plant's ID is spelled differently by
the two storage backends, and both spellings are real data on disk today:

* ``plant_id`` -- the CANONICAL spelling. Phase 3's migration tooling wrote
  every ``plants/<ID>.md`` frontmatter this way, so it is what 5 of the 6
  live projects use for 100% of their plants. Joey's call, recorded on
  NICK-701 (2026-09-07): ``plant_id`` is canonical going forward.
* ``id`` -- the LEGACY spelling. It is the pre-Phase-2 ``tracker.json``
  format's native key, which makes it CORRECT (not a bug) for
  ``json_backend`` -- that module is restored verbatim from commit 2dd0537
  precisely so a NICK-949 rollback reproduces the original on-disk format
  byte for byte. It also still appears in ``mule-fuel-x-nana-glue``'s 36
  plant files written by that project's own pre-migration scripts, until
  Task 7.2 step 2 re-migrates them.

The bug this module fixes: ``breeding_core`` and ``markdown_backend`` both
hard-coded ``'id'``, so against the REAL migrated corpus every plant read as
having no ID at all. On ``AUTO_CREATE: False`` projects (Lantz, Mule Fuel,
Spaced Paste) a real plant silently reported as "not found"; on
``AUTO_CREATE: True`` projects (Paloma Coma, Honey Badger Haze, Kibungan) it
fell through to auto-create and then hard-crashed inside ``save_tracker``,
having already entered the write path. 414 tests missed it because every
fixture was built THROUGH the backend, so the tests only ever read back the
spelling they themselves had written.

It lives in its own module rather than in either backend because both
``breeding_core`` and ``markdown_backend`` need it, and ``breeding_core``
imports ``markdown_backend`` -- putting it in either one would make the
dependency circular or make one backend's private detail the other's public
API. ``json_backend`` deliberately does not import it: it must stay the
verbatim 2dd0537 code.
"""

CANONICAL_ID_KEY = 'plant_id'

# Read-compatibility only. NOTHING new is ever written under this key on the
# markdown backend; it exists so records that predate the canonical decision
# keep resolving instead of reading as ID-less.
LEGACY_ID_KEY = 'id'

ID_KEYS = (CANONICAL_ID_KEY, LEGACY_ID_KEY)


def plant_id_of(plant):
    """The ID a plant record carries, under either accepted spelling.

    Returns ``None`` -- rather than raising -- when the record carries
    neither key or only empty/``None`` values. That is deliberate and
    load-bearing: the roster scan in ``update_plant`` and the validation pass
    in ``markdown_backend.save_tracker`` both need a hand-edited, ID-less
    record to reach ``_validate_plant_id``'s informative "plant record has a
    missing or non-string id" error instead of dying on an opaque
    ``KeyError``. (That hardening was added deliberately -- see
    ``DECISIONS.md``, "``p.get('id')`` hardening" -- and is preserved here.)

    Raises ``ValueError`` when BOTH keys are present and DISAGREE. Such a
    record is corrupt, and silently preferring one spelling could route an
    observation onto the wrong plant or write one plant's file under
    another's name -- a data-loss shape, not a cosmetic inconsistency. Both
    keys agreeing is fine and resolves normally.
    """
    if not isinstance(plant, dict):
        return None

    canonical = plant.get(CANONICAL_ID_KEY)
    legacy = plant.get(LEGACY_ID_KEY)

    if canonical is not None and legacy is not None and canonical != legacy:
        raise ValueError(
            "plant record has conflicting ids: "
            f"{CANONICAL_ID_KEY}={canonical!r} vs {LEGACY_ID_KEY}={legacy!r}"
        )

    return canonical if canonical is not None else legacy
