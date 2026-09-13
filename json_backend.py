#!/usr/bin/env python3
"""The pre-Phase-2 JSON tracker persistence, preserved as a selectable backend.

THIS IS NOT NEW CODE. ``load_tracker``/``save_tracker`` below are the exact
implementations that lived in ``breeding_core.py`` from the start of this
codebase until Task 2.1 replaced them with the markdown backend (commit
f2bbca5; the last JSON-era revision is ``2dd0537``, also snapshotted at
``tests/fixtures/baseline_breeding_core_2dd0537.py``). They are restored here
verbatim -- same ``open()`` calls, same ``indent=2`` -- rather than rewritten,
because the point of a rollback path is to reproduce the ORIGINAL behaviour
byte for byte, including the on-disk formatting. A re-implementation that
merely looked equivalent would produce a whole-file git diff on the first
save of every rolled-back project, and would be exactly the kind of subtle
divergence a rollback is supposed to avoid.

WHY IT IS SELECTABLE (NICK-949): Task 2.1 flipped the backend GLOBALLY for
all six projects at once, which left Phase 2 with no way to roll a SINGLE
project back to JSON -- the thing Task 7.2's rollback rehearsal has to do.
``breeding_core.STORAGE_BACKENDS`` now routes to this module when a project's
config says ``BACKEND: 'json'``.

Interface contract (shared with ``markdown_backend``):
  * ``load_tracker(tracker_file) -> dict`` -- raises ``FileNotFoundError``
    when the project has no store yet.
  * ``save_tracker(tracker, tracker_file) -> None``.
``tracker_file`` is the actual file read/written here (unlike the markdown
backend, which uses only its parent directory).
"""

import json


def load_tracker(tracker_file):
    """Read a project's ``tracker.json`` (restored from 2dd0537, verbatim)."""
    with open(tracker_file) as f:
        return json.load(f)


def save_tracker(tracker, tracker_file):
    """Write a project's ``tracker.json`` (restored from 2dd0537, verbatim)."""
    with open(tracker_file, 'w') as f:
        json.dump(tracker, f, indent=2)
