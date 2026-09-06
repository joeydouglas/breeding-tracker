# Task 3.0 — Real Tracker Field Inventory & Template Coverage Verification

**Phase:** 3 (data migration), Task 3.0 — READ-ONLY investigative task
**Scope:** all 6 real `tracker.json` files under `/home/joey/.hermes/breeding/`
**Verdict:** **PASS** — no field in real data lacks a declared template field.
**Plants inventoried:** 95 across 6 projects.

> Satisfies the I13/Codex finding that Revision 1 asserted a field list without
> checking it against real data. Every claim below is derived programmatically
> from the actual files, not from the plan draft.

---

## 1. TOP-LEVEL TRACKER KEYS (union across 6 projects)

| key | types observed | present in N/6 | missing from |
|---|---|---|---|
| `breeder_lineage` | string | 3 | lantz, mule-fuel-x-nana-glue, spaced-paste |
| `created` | string | 6 | - |
| `cross_name` | string | 6 | - |
| `drive_folders` | object | 6 | - |
| `genetics` | string | 3 | lantz, mule-fuel-x-nana-glue, spaced-paste |
| `github_pages_url` | string | 6 | - |
| `github_repo` | string | 6 | - |
| `google_sheet_id` | null, string | 6 | - |
| `google_sheet_url` | null, string | 6 | - |
| `last_updated` | string | 6 | - |
| `notes_meta` | object | 5 | mule-fuel-x-nana-glue |
| `plants` | array | 6 | - |

## 2. PLANT RECORD KEYS (union across all 95 plants)

| key | types observed | occurrences | present in projects |
|---|---|---|---|
| `corrected_reading` | string | 1/95 | 1/6 |
| `cross` | string | 95/95 | 6/6 |
| `flower_flip` | null | 95/95 | 6/6 |
| `germ_date` | null | 95/95 | 6/6 |
| `harvest_date` | null | 95/95 | 6/6 |
| `id` | string | 95/95 | 6/6 |
| `issues` | null | 95/95 | 6/6 |
| `observation_log` | string | 95/95 | 6/6 |
| `original_notes` | string | 95/95 | 6/6 |
| `photo_count` | int | 94/95 | 6/6 |
| `photos` | array | 95/95 | 6/6 |
| `photos_drive_url` | string | 94/95 | 6/6 |
| `selection_notes` | null, string | 95/95 | 6/6 |
| `sex` | null | 95/95 | 6/6 |
| `status` | string | 95/95 | 6/6 |
| `structure` | null | 95/95 | 6/6 |
| `terpene_notes` | null, string | 95/95 | 6/6 |
| `veg_start` | null | 95/95 | 6/6 |
| `vigor` | null | 95/95 | 6/6 |

### 2b. Per-project plant-key breakdown

- **mule-fuel-x-nana-glue**: 18 keys; missing vs union: corrected_reading
- **honey-badger-haze-pheno-hunt**: 18 keys; missing vs union: corrected_reading
- **kibungan-pheno-hunt**: 18 keys; missing vs union: corrected_reading
- **spaced-paste**: 18 keys; missing vs union: corrected_reading
- **paloma-coma**: 18 keys; missing vs union: corrected_reading
- **lantz**: 19 keys; missing vs union: (none)

## 3. TYPE-VARIANCE FLAGS

- nullable: top-level.google_sheet_id -> ['null', 'string']
- nullable: top-level.google_sheet_url -> ['null', 'string']
- ALWAYS-NULL: plant.flower_flip
- ALWAYS-NULL: plant.germ_date
- ALWAYS-NULL: plant.harvest_date
- ALWAYS-NULL: plant.issues
- nullable: plant.selection_notes -> ['null', 'string']
- ALWAYS-NULL: plant.sex
- ALWAYS-NULL: plant.structure
- nullable: plant.terpene_notes -> ['null', 'string']
- ALWAYS-NULL: plant.veg_start
- ALWAYS-NULL: plant.vigor

## 4. NESTED / NON-SCALAR SUB-SCHEMAS

### top-level `drive_folders`  (n=6 instances)

| sub-key | types | in projects |
|---|---|---|
| `dashboard` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, mule-fuel-x-nana-glue, paloma-coma |
| `dashboard_url` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, mule-fuel-x-nana-glue, paloma-coma |
| `notes` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, mule-fuel-x-nana-glue, paloma-coma, spaced-paste |
| `notes_url` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, mule-fuel-x-nana-glue, paloma-coma, spaced-paste |
| `photos` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, mule-fuel-x-nana-glue, paloma-coma, spaced-paste |
| `photos_url` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, mule-fuel-x-nana-glue, paloma-coma, spaced-paste |
| `reports` | string | mule-fuel-x-nana-glue |
| `reports_url` | string | mule-fuel-x-nana-glue |
| `root` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, mule-fuel-x-nana-glue, paloma-coma, spaced-paste |
| `root_url` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, mule-fuel-x-nana-glue, paloma-coma, spaced-paste |

### top-level `notes_meta`  (n=5 instances)

| sub-key | types | in projects |
|---|---|---|
| `brand_assets_in_drive` | array | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, paloma-coma, spaced-paste |
| `flagged_ambiguities` | array | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, paloma-coma, spaced-paste |
| `migration_note` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, paloma-coma, spaced-paste |
| `resolved_ambiguities` | array | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, paloma-coma, spaced-paste |
| `source_doc` | null, string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, lantz, paloma-coma, spaced-paste |

### plant.`photos[]` (list of objects)  (n=69 instances)

| sub-key | types | in projects |
|---|---|---|
| `context` | string | mule-fuel-x-nana-glue |
| `drive_id` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, mule-fuel-x-nana-glue, paloma-coma |
| `drive_url` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, mule-fuel-x-nana-glue, paloma-coma |
| `embed_url` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, mule-fuel-x-nana-glue, paloma-coma |
| `filename` | string | honey-badger-haze-pheno-hunt, kibungan-pheno-hunt, mule-fuel-x-nana-glue, paloma-coma |
| `uploaded` | string | mule-fuel-x-nana-glue |


## 5. TEMPLATE COVERAGE CROSS-REFERENCE

Approved plant-template.md fields (19): corrected_reading, cross, flower_flip, germ_date, harvest_date, id, issues, observation_log, original_notes, photo_count, photos, photos_drive_url, selection_notes, sex, status, structure, terpene_notes, veg_start, vigor

Approved project-template.md fields (14): auto_create, body, breeder_lineage, created, cross_name, drive_folders, genetics, github_pages_url, github_repo, google_sheet_id, google_sheet_url, last_updated, notes_meta, plant_id_prefixes

### Project-level fields in real data but NOT in project-template.md
- (none)

### Plant-level fields in real data but NOT in plant-template.md
- (none)

### Template fields declared but NEVER present in real data (informational)
- project-template unused: auto_create, plant_id_prefixes
- plant-template unused: (none)

## 6. VERDICT: **PASS**

- Structural note: top-level `plants` is intentionally decomposed into per-plant markdown files, so it is not expected as a project frontmatter field.
- Total plants inventoried: 95 across 6 projects.

---

## 7. Additional verification beyond static key comparison

A static key diff can still hide data loss if the writers whitelist sub-keys,
so both round-trips were executed against **real records**:

### 7a. Plant round-trip — extra `photos[]` sub-keys preserved
`mule-fuel-x-nana-glue` plant `MG07` carries two photo sub-keys absent from the
template's description (`uploaded`, `context`). Round-tripping the real record
through `write_plant()` -> `read_plant()`:

- `photos` compared equal to the original **exactly** (`True`)
- lost photo sub-keys: **none**
- lost top-level plant keys: **none**

`photos` is declared `type: array` and passed through opaquely, so undeclared
sub-keys survive. **No template change required.**

### 7b. Project round-trip — all 6 projects lossless
Each project's non-`plants` keys were round-tripped through
`write_project()` -> `read_project()`:

| project | lost keys | value-changed keys |
|---|---|---|
| mule-fuel-x-nana-glue | none | none |
| honey-badger-haze-pheno-hunt | none | none |
| kibungan-pheno-hunt | none | none |
| spaced-paste | none | none |
| paloma-coma | none | none |
| lantz | none | none |

Includes the per-project `drive_folders` variation (`reports`/`reports_url`
unique to mule-fuel) and the missing `notes_meta` on mule-fuel.

## 8. Explaining the two "unused" template fields

`auto_create` and `plant_id_prefixes` appear in `project-template.md` but in no
`tracker.json`. They are **not phantom fields** — they live in
`_shared/breeding-meta/registry.json`, whose per-project entries carry:
`auto_create`, `breeding_dir`, `cross_name`, `github_repo`, `plant_id_prefixes`,
`slug`. Migration must source these two from **registry.json**, not tracker.json,
or every migrated `project.md` will silently take the template defaults
(`auto_create: false`, `plant_id_prefixes: []`) and break ID routing / auto-create.

**This is a migration-input requirement, not a template gap.**

## 9. Notes for the migration implementer (Task 3.1+)

1. **Source `auto_create` + `plant_id_prefixes` from registry.json** (see §8). Highest-risk item found.
2. **`plants` is an array, not a dict**, in all 6 trackers — index accordingly.
3. **`MG07` lacks `photo_count` and `photos_drive_url`** (94/95 have them). Migration must apply template defaults (`0`, `""`) rather than assume presence.
4. **`corrected_reading` exists on exactly 1 plant** (lantz, 1/95). Declared in the template; do not drop it as an outlier.
5. **10 plant fields are always-null across all 95 plants** (`germ_date`, `veg_start`, `flower_flip`, `harvest_date`, `vigor`, `structure`, `issues`, `sex`, plus nullable `selection_notes`/`terpene_notes`). Migration must not infer types from observed data — the declared template types govern.
6. **`notes_meta.source_doc` is nullable**; `notes_meta` absent entirely on mule-fuel-x-nana-glue.

## 10. Acceptance criterion

> "any field found here that's missing from the templates triggers a template
> update before migration proceeds."

**No such field was found.** Zero template updates required. The already-approved
Phase 0/1 templates are confirmed complete against real data. No retroactive
escalation of a template gap is needed; the one real risk surfaced (§8) is a
migration-input issue for Task 3.1, not a schema defect.
