"""breeding-tracker: reusable plant-breeding tracking library.

Consolidates the former monitor-core, breeding-markdown, breeding-ingest
and master-dashboard modules into one pip-installable package.

Submodules
----------
breeding_core       -- observation pipeline: parse Discord text, update plants
plant_record        -- canonical plant-ID helpers
json_backend        -- legacy tracker.json persistence
markdown_backend    -- markdown (project.md / plants/*.md) persistence
plant_markdown      -- plant markdown file format (read/write/schema)
project_markdown    -- project markdown file format (read/write/schema)
tracker_migration   -- tracker.json -> markdown migration
reverse_migration   -- markdown -> tracker.json reverse migration
migration           -- template application across repos
migration_harness   -- migration verification harness
migration_specs     -- per-project migration specs
scaffolding         -- scaffold new plant/project markdown files
discord_ingest      -- Discord #breeding channel ingestion + plant-ID registry
hermes_gateway      -- Hermes gateway hook factory for silent ingestion
master_dashboard    -- master overview dashboard generator
"""

__version__ = "1.0.0"
