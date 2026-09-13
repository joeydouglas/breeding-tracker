---
cross_name:
  type: string
  default: null
  description: "Display name of the cross/project, e.g. 'Lantz', 'Mule Fuel x Nana Glue'."
genetics:
  type: string
  default: null
  description: "Free-text genetics description (parent strains, lineage summary). Optional - not all 6 current projects have it."
breeder_lineage:
  type: string
  default: null
  description: "Free-text breeder/lineage provenance notes. Optional - not all 6 current projects have it."
plant_id_prefixes:
  type: array
  default: []
  description: "List of plant-ID prefix regex(es) this project uses, e.g. ['Ltz'] for single-prefix projects or ['PK','PL'] for multi-prefix (Kibungan: PK/PL)."
auto_create:
  type: boolean
  default: false
  description: "Whether breeding_core.py should auto-create a new plant record the first time an unrecognized ID matching this project's prefix appears in Discord notes."
github_repo:
  type: string
  default: null
  description: "GitHub repo URL for this project's markdown data repo (post-migration) or legacy repo (pre-migration)."
github_pages_url:
  type: string
  default: null
  description: "Legacy GitHub Pages dashboard URL, preserved for the 30-day rollback/archive window even after the new frontend is live."
google_sheet_id:
  type: string
  default: null
  description: "Legacy Google Sheet ID. Confirmed dead code path (sync_to_sheet() never called by the live pipeline) but the field itself is preserved for historical reference during migration."
google_sheet_url:
  type: string
  default: null
  description: "Legacy Google Sheet URL, same status as google_sheet_id."
drive_folders:
  type: object
  default: {}
  description: "Mapping of named Google Drive folder references used by this project (structure varies per project; preserved as-is during migration, not restructured)."
notes_meta:
  type: object
  default: {}
  description: "Present on 5 of 6 current projects (all except mule-fuel-x-nana-glue); metadata about the Discord-notes ingestion process for this project. Preserved as-is."
created:
  type: string
  default: null
  description: "ISO timestamp the project was created."
last_updated:
  type: string
  default: null
  description: "ISO timestamp of the project's last update - written on every observation."
body:
  type: body
  default: ""
  description: "Freeform project-level markdown notes, stored as the file's markdown BODY (never in frontmatter) so hand-written formatting survives byte-for-byte."
---

<!--
This is the canonical project template. Each frontmatter key above is a SCHEMA
DESCRIPTOR object ({type, default, description}) - not example data. A real
project's project.md carries plain scalar/array/object values for these same
keys, and its markdown body holds freeform project notes.
-->
