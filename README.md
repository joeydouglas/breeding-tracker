# breeding-tracker

A reusable, generic plant-breeding tracking library. Consolidates what were
previously four scattered codebases (`monitor-core`, `breeding-markdown`,
`breeding-ingest`, `master-dashboard`) into one pip-installable package.

## What it does

- **Observation pipeline** (`breeding_tracker.breeding_core`): parses
  free-text plant observations (Discord messages, voice transcripts) into
  structured updates — status, vigor, smells, stretch, notes — and persists
  them via a pluggable storage backend.
- **Plant-ID registry & Discord ingestion**
  (`breeding_tracker.discord_ingest`, `breeding_tracker.hermes_gateway`):
  durable SQLite ingestion of a shared #breeding channel, with a per-cross
  plant-ID prefix registry (`MG04`, `HBH12`, …) that routes each message to
  the right project.
- **Markdown record of truth** (`breeding_tracker.plant_markdown`,
  `project_markdown`, `markdown_backend`): schema-driven
  `project.md` + `plants/*.md` files with YAML frontmatter; templates ship
  as package data (`breeding_tracker/templates/`).
- **Legacy JSON backend** (`breeding_tracker.json_backend`): the historical
  `tracker.json` persistence, kept for per-project rollback.
- **Migrations** (`tracker_migration`, `reverse_migration`, `migration`,
  `migration_harness`, `migration_specs`, `scaffolding`): tracker.json ↔
  markdown migration, template application, and verification harnesses.
- **Master dashboard** (`breeding_tracker.master_dashboard`): read-only
  aggregation of every registered project into one overview page, driven by
  a `manifest.json` registry (see `config/manifest.json.example`; the live
  manifest location is configured via `MASTER_DASHBOARD_DIR`).

## Install

```bash
pip install git+https://github.com/joeydouglas/breeding-tracker.git
```

## Usage in a project

Each breeding project keeps its own repo (project.md, plants/, dashboards)
and a thin `monitor_breeding_notes.py` wrapper that supplies a `CONFIG`
dict (breeding dir, plant-ID pattern, cross name, backend) and delegates
everything to `breeding_tracker.breeding_core`:

```python
from breeding_tracker import breeding_core as core

CONFIG = {
    "BREEDING_DIR": ...,
    "TRACKER_FILE": ...,
    "GITHUB_REPO": "you/your-cross",
    "CROSS_NAME": "Your Cross",
    "BACKEND": "markdown",
    ...
}
result = core.process_message(text, attachments, CONFIG, ...)
```

## Environment overrides

- `BREEDING_MARKDOWN_DIR` — use an alternate checkout's `templates/`
  instead of the packaged templates.
- `MASTER_DASHBOARD_DIR` — where the live master-dashboard `manifest.json`
  and output live.
- `BREEDING_ROOT` — root directory containing per-project breeding dirs.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/python -m pytest
```

Historical design records are under `docs/` (DECISIONS files and task
reports carried over from the source repos, with their full git history
merged into this repo).
