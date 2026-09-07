---
# Plant template schema (Revision 1) — each field is {type, default, description}
# This is a SCHEMA document, not real plant data. A parser must be able to
# distinguish this file from an actual plants/<ID>.md file (see registry.json
# convention: schema files live under templates/, plant data under plants/).
plant_id:
  type: string
  default: null
  description: "REVISION 3 (NICK-966, Joey's decision recorded on NICK-701 2026-09-07): RENAMED from 'id' to 'plant_id', the canonical ID key for the markdown format. tracker.json's own native key remains 'id' -- json_backend must reproduce that format byte-for-byte for a NICK-949 rollback -- so tracker_migration renames on the way out (see SOURCE_PLANT_ID_KEY / CANONICAL_PLANT_ID_KEY). Plant identifier, e.g. Ltz01, PK03. Prefix comes from the owning project's plant-ID prefix regex."
cross:
  type: string
  default: null
  description: "Name of the cross/project this plant belongs to (denormalized copy of the project's cross_name for convenience)."
status:
  type: string
  default: null
  description: "One of: null (undetermined), 'keeper', 'culled', or other project-specific status keywords detected by breeding_core.py's status-detection regex."
sex:
  type: string
  default: null
  description: "Plant sex once determined: male, female, hermaphrodite, or null if not yet determined."
germ_date:
  type: string
  default: null
  description: "ISO date the seed germinated, or null."
veg_start:
  type: string
  default: null
  description: "ISO date vegetative growth began, or null."
flower_flip:
  type: string
  default: null
  description: "ISO date the plant was flipped to flower, or null."
harvest_date:
  type: string
  default: null
  description: "ISO date of harvest, or null."
vigor:
  type: string
  default: null
  description: "Free-text vigor assessment (e.g. 'strong', 'weak', 'average')."
structure:
  type: string
  default: null
  description: "Free-text structural notes (height, branching, internode spacing)."
terpene_notes:
  type: string
  default: null
  description: "Free-text terpene/smell/flavor notes."
issues:
  type: string
  default: null
  description: "Free-text pest/disease/deficiency notes, or null."
selection_notes:
  type: string
  default: null
  description: "Free-text breeder selection reasoning — why keep or cull."
photos:
  type: array
  default: []
  description: "List of {drive_id, drive_url, filename, embed_url} objects for this plant's photos."
photo_count:
  type: integer
  default: 0
  description: "Count of items in photos — kept denormalized for fast dashboard rendering without counting the array."
photos_drive_url:
  type: string
  default: ""
  description: "Google Drive folder URL containing this plant's photos, if any."
observation_log:
  type: body
  default: ""
  description: "REVISION 2 (adopted from Task 1.1's implementer subagent, approved by Joey 2026-09-05): stored as the markdown BODY of the file, never in frontmatter, to guarantee byte-exact preservation of hand-written formatting (indentation, code fences, tables, trailing whitespace) on every read/write round-trip. Accumulated freeform observation history for this plant."
original_notes:
  type: string
  default: null
  description: "NEW FIELD found in Task 0.1's field-inventory pass (not in the original plan draft) — verbatim original notes text as first migrated from the source Google Doc, preserved for provenance even after selection_notes/observation_log are edited."
corrected_reading:
  type: string
  default: null
  description: "NEW FIELD found in Task 0.1's field-inventory pass — records a human-confirmed correction to a transcription/OCR/autocorrect error in original_notes (e.g. 'Thanos' -> 'phenos'), so the correction is never silently lost or re-introduced."
---

# Plant markdown body (freeform, optional)

Everything below the YAML frontmatter is optional freeform markdown —
additional narrative, links, or context that doesn't fit a structured field.
Parsers must preserve this body verbatim on read/write round-trips.
