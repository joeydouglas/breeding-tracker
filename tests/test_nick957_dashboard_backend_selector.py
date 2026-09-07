"""NICK-957 -- TDD: generate_dashboard.py must read through the storage
backend selector, not straight from ``tracker.json``.

WHY THIS EXISTS. ``generate_dashboard.py`` (one near-identical copy per
project) has always done a raw ``json.load(TRACKER_FILE)``. That predates
Task 2.1's markdown migration and was never updated. For any project cut over
to ``BACKEND='markdown'`` (all 6 live projects, as of NICK-701), the real
record of truth is ``project.md`` + ``plants/<ID>.md`` -- ``tracker.json`` is
no longer written by the live ingestion pipeline at all and is a frozen
snapshot from before cutover. The dashboard silently renders that stale
snapshot on every regeneration, which is invisible until someone diffs it
against a real observation (Joey hit exactly this on mule-fuel: NICK-981).

Reproduced live before this fix (see the NICK-957 code-review comment on
Multica): Lantz's ``tracker.json`` (``last_updated: 2026-08-25``) does not
contain either of two real observations posted through the live pipeline on
2026-09-07 ("vigor 8" and "recovering nicely"), while ``plants/Ltz01.md`` and
``plants/Ltz03.md`` do.

THE FIX. Each project's ``generate_dashboard.py`` now loads through that
SAME project's own ``monitor_breeding_notes.load_tracker()`` (which already
calls ``breeding_core.load_tracker_for(CONFIG)`` and honours
``CONFIG['BACKEND']``) instead of opening ``TRACKER_FILE`` directly. A
project rolled back to ``BACKEND='json'`` for a NICK-949 rollback rehearsal
therefore still dashboards correctly -- unlike a hardcoded
``markdown_backend`` import would have. ``plant['id']`` is replaced with
``plant_record.plant_id_of(plant)`` everywhere, matching NICK-965's
established convention (a markdown-backend plant carries ``plant_id``, not
``id``) so plant pages/cards actually render instead of raising ``KeyError``.

Every write here lands in pytest ``tmp_path``; the real project trees are
read-only inputs at most (`` real_lantz_project_dir`` fixture below), never
mutated. ``dashboard/`` output is itself already gitignored on every live
project (NICK-701's ``.gitignore`` block), so nothing this suite proves is a
live-push concern.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_ROOT = MONITOR_CORE_DIR.parents[1]
LANTZ_DIR = BREEDING_ROOT / "lantz"

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

import plant_record  # noqa: E402


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandboxed_lantz(tmp_path, monkeypatch):
    """A tmp_path copy of the REAL, live Lantz project tree.

    Copies ``project.md`` + ``plants/*.md`` (the markdown record of truth)
    and the real (stale) ``tracker.json``, so the test exercises the exact
    shape that broke live -- markdown ahead of tracker.json -- without ever
    writing to the real project dir. Skips if the real project isn't present
    (matches this suite's existing ``lantz_tracker`` fixture convention).
    """
    if not (LANTZ_DIR / "project.md").exists():
        pytest.skip("real lantz project.md not present")

    sandbox = tmp_path / "lantz"
    sandbox.mkdir()
    shutil.copy(LANTZ_DIR / "project.md", sandbox / "project.md")
    shutil.copy(LANTZ_DIR / "tracker.json", sandbox / "tracker.json")
    shutil.copytree(LANTZ_DIR / "plants", sandbox / "plants")

    monkeypatch.setenv("BREEDING_DIR", str(sandbox))
    monkeypatch.setenv("BREEDING_DISABLE_PUSH", "1")
    # Reload both wrapper modules fresh so their module-level BREEDING_DIR
    # picks up the monkeypatched env var (mirrors the gateway's own
    # importlib.reload cycle documented in monitor_breeding_notes.py).
    for name in ("monitor_breeding_notes", "generate_dashboard"):
        sys.modules.pop(name, None)

    monitor = _load_module(LANTZ_DIR / "monitor_breeding_notes.py", "monitor_breeding_notes")
    dashboard = _load_module(LANTZ_DIR / "generate_dashboard.py", "generate_dashboard")
    return sandbox, monitor, dashboard


def test_dashboard_load_tracker_sees_markdown_only_data_not_just_stale_json(sandboxed_lantz):
    """The exact NICK-957 bug: markdown has data tracker.json does not."""
    sandbox, monitor, dashboard = sandboxed_lantz

    # Plant an observation directly into the markdown record of truth (what
    # the live pipeline actually does) that is deliberately absent from the
    # copied, stale tracker.json. Mirrors markdown_backend.py's own
    # sys.path-insert of the sibling breeding-markdown checkout's src/.
    markdown_src = MONITOR_CORE_DIR.parent / "breeding-markdown" / "src"
    if str(markdown_src) not in sys.path:
        sys.path.insert(0, str(markdown_src))
    import plant_markdown

    plant_path = sandbox / "plants" / "Ltz01.md"
    schema = plant_markdown.load_schema(
        MONITOR_CORE_DIR.parent / "breeding-markdown" / "templates" / "plant-template.md"
    )
    plant = plant_markdown.read_plant(plant_path, schema=schema)
    marker = "NICK-957 regression-test observation, unique text xyzzy42"
    plant["observation_log"] = (plant.get("observation_log") or "") + f"\n### marker\n{marker}\n"
    plant_markdown.write_plant(plant_path, plant, schema=schema)

    tracker = dashboard.load_tracker()
    lt01 = next(p for p in tracker["plants"] if plant_record.plant_id_of(p) == "Ltz01")
    assert marker in (lt01.get("observation_log") or ""), (
        "generate_dashboard.load_tracker() did not see a markdown-only "
        "observation -- it is still reading stale tracker.json directly"
    )


def test_dashboard_plant_id_of_not_bracket_id_key(sandboxed_lantz):
    """A markdown-backend plant record has no 'id' key -- only 'plant_id'."""
    _, _, dashboard = sandboxed_lantz
    tracker = dashboard.load_tracker()
    plant = tracker["plants"][0]
    assert "id" not in plant
    assert plant_record.plant_id_of(plant)


def test_generate_all_runs_end_to_end_against_real_markdown_data(sandboxed_lantz):
    """Full dashboard generation must not KeyError on plant['id'] anymore."""
    sandbox, _, dashboard = sandboxed_lantz
    dashboard.generate_all()
    index_html = (sandbox / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "Ltz01" in index_html
    plant_page = sandbox / "dashboard" / "plants" / "Ltz01.html"
    assert plant_page.exists()
