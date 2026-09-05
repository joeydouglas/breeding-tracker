---
id:
  type: string
  default: null
  description: "Plant identifier, e.g. HBH01 / Ltz07 / PK03. Always a string, even when it looks numeric."
cross:
  type: string
  default: null
  description: "Human-readable cross name this plant belongs to."
status:
  type: string
  default: "active"
  description: "Lifecycle status: active, culled, keeper, etc. Set by Discord status-keyword detection."
sex:
  type: string
  default: null
  description: "male / female / unknown."
germ_date:
  type: string
  default: null
  description: "ISO-8601 date the seed was germinated."
veg_start:
  type: string
  default: null
  description: "ISO-8601 date vegetative growth started."
flower_flip:
  type: string
  default: null
  description: "ISO-8601 date the light cycle was flipped to flower."
harvest_date:
  type: string
  default: null
  description: "ISO-8601 date the plant was harvested."
vigor:
  type: integer
  default: null
  description: "0-10 rating from Discord observation parsing."
structure:
  type: string
  default: null
  description: "Free-text structure/morphology notes."
terpene_notes:
  type: string
  default: null
  description: "Free-text terpene/aroma notes."
issues:
  type: string
  default: null
  description: "Free-text pest/deficiency/problem notes."
selection_notes:
  type: string
  default: null
  description: "Free-text keeper/cull reasoning."
photos:
  type: list
  default: []
  description: "List of {drive_id, drive_url, filename, embed_url} photo reference objects."
photo_count:
  type: integer
  default: 0
  description: "Number of photos attached to this plant."
photos_drive_url:
  type: string
  default: null
  description: "Google Drive folder URL holding this plant's photos."
original_notes:
  type: string
  default: null
  description: "Verbatim notes imported from the original Google Doc tab, preserved unmodified."
corrected_reading:
  type: string
  default: null
  description: "Note recording a corrected transcription/OCR reading of an observation, with who confirmed it and when. Found on Lantz Ltz01 during the Task 3.0 field inventory."
observation_log:
  type: body
  default: ""
  description: "Append-only observation log. Stored as the markdown BODY of the file, never in frontmatter, so hand-written formatting survives byte-for-byte."
---

<!--
This is the canonical plant template. Each frontmatter key above is a SCHEMA
DESCRIPTOR object ({type, default, description}) - not example data. A real
plant file (plants/<ID>.md) carries plain scalar values for these same keys,
and its markdown body holds the observation_log.
-->
