"""The per-project migration specs for Phase 3.

Task 3.3 and the three projects after it add an entry here instead of copying
a ~700-line acceptance module and a ~450-line verifier script. Everything that
is genuinely the same across projects lives in `migration_harness` and
`tests/test_project_migration_contract.py`; this file is the delta.

Adding a project:

1. Add a `ProjectSpec` below, sourced from Task 3.0's field inventory.
2. Run the contract suite -- it picks the new spec up automatically.
3. Add a per-project test module for anything genuinely unique to that
   project's data (a numbering gap, a record missing fields, a field that
   exists nowhere else). Do NOT re-add the shared checks.
"""

from migration_harness import ProjectSpec

#: The 18 keys carried by every complete plant record, per Task 3.0 §2.
#: `corrected_reading` is NOT here: it is declared in the plant template and
#: real on exactly one lantz plant, so it is a legitimate materialised default
#: everywhere else and is tracked via `expected_plant_defaults`.
_COMMON_PLANT_KEYS = frozenset(
    {
        "cross",
        "flower_flip",
        "germ_date",
        "harvest_date",
        "id",
        "issues",
        "observation_log",
        "original_notes",
        "photo_count",
        "photos",
        "photos_drive_url",
        "selection_notes",
        "sex",
        "status",
        "structure",
        "terpene_notes",
        "veg_start",
        "vigor",
    }
)

MULE_FUEL = ProjectSpec(
    slug="mule-fuel-x-nana-glue",
    plant_count=45,
    project_keys=frozenset(
        {
            "created",
            "cross_name",
            "drive_folders",
            "github_pages_url",
            "github_repo",
            "google_sheet_id",
            "google_sheet_url",
            "last_updated",
            "plants",
        }
    ),
    plant_keys=_COMMON_PLANT_KEYS,
    expected_project_defaults=frozenset(
        {"genetics", "breeder_lineage", "notes_meta"}
    ),
    incomplete_plants=frozenset({"MG07"}),
    notes=(
        "Registry auto_create is false, which EQUALS the template default, so "
        "this project's data cannot distinguish a registry read from a silent "
        "template default. Its routing-field assertions are true but not "
        "discriminating; honey-badger-haze provides the discriminating case. "
        "Plant IDs skip MG09. MG07 alone lacks photo_count/photos_drive_url."
    ),
)

HONEY_BADGER_HAZE = ProjectSpec(
    slug="honey-badger-haze-pheno-hunt",
    plant_count=23,
    project_keys=frozenset(
        {
            "breeder_lineage",
            "created",
            "cross_name",
            "drive_folders",
            "genetics",
            "github_pages_url",
            "github_repo",
            "google_sheet_id",
            "google_sheet_url",
            "last_updated",
            "notes_meta",
            "plants",
        }
    ),
    plant_keys=_COMMON_PLANT_KEYS,
    notes=(
        "Registry auto_create is TRUE while the template default is false, so "
        "this is the first project whose data can prove Task 3.0 §8's "
        "highest-risk finding was handled. notes_meta is present. Every plant "
        "carries all 18 keys, so corrected_reading must be the ONLY defaulted "
        "plant field. IDs are the contiguous HBH01..HBH23 run. Its "
        "notes_meta.migration_note is stale in the SOURCE (claims plants[] is "
        "empty while 23 exist) and is migrated verbatim rather than corrected."
    ),
)

KIBUNGAN = ProjectSpec(
    slug="kibungan-pheno-hunt",
    plant_count=13,
    project_keys=frozenset(
        {
            "breeder_lineage",
            "created",
            "cross_name",
            "drive_folders",
            "genetics",
            "github_pages_url",
            "github_repo",
            "google_sheet_id",
            "google_sheet_url",
            "last_updated",
            "notes_meta",
            "plants",
        }
    ),
    plant_keys=_COMMON_PLANT_KEYS,
    notes=(
        "The FIRST project with more than one plant-ID prefix: registry "
        "`plant_id_prefixes` carries both PK and PL for one landrace "
        "population, so a migration that took only the first entry, or that "
        "flattened the list, breaks ID routing for a third of this project's "
        "plants. Its two patterns are also the first to use `(?i)` and a "
        "`(?<!...)` lookbehind, so they exercise YAML escaping harder than the "
        "single `\\b...\\b` patterns of the first two projects. Registry "
        "auto_create is TRUE while the template default is false, so this is a "
        "second discriminating case for Task 3.0 §8. `google_sheet_url` is the "
        "EMPTY STRING while `google_sheet_id` is null -- the first project "
        "where those two differ, so a reader coercing '' to None (or None to "
        "'') is caught. notes_meta is present with a non-null `source_doc` and "
        "a non-empty `flagged_ambiguities` list (empty on both earlier "
        "projects). Every plant carries all 18 keys, so corrected_reading must "
        "be the ONLY defaulted plant field. IDs are non-contiguous within both "
        "families (PK01..PK19 skipping 8 numbers, PL05/PL06/PL15)."
    ),
)

PALOMA_COMA = ProjectSpec(
    slug="paloma-coma",
    plant_count=5,
    project_keys=frozenset(
        {
            "breeder_lineage",
            "created",
            "cross_name",
            "drive_folders",
            "genetics",
            "github_pages_url",
            "github_repo",
            "google_sheet_id",
            "google_sheet_url",
            "last_updated",
            "notes_meta",
            "plants",
        }
    ),
    plant_keys=_COMMON_PLANT_KEYS,
    notes=(
        "The SMALLEST project migrated so far (5 plants) and the first where "
        "EVERY optional phenotype field -- sex, germ_date, veg_start, "
        "flower_flip, harvest_date, vigor, structure, terpene_notes, issues "
        "AND selection_notes -- is null on every plant. All ten nullable "
        "columns are empty at once, so a writer that omitted an entirely-null "
        "field, or a reader that skipped a frontmatter key it never saw with a "
        "value, loses ten fields per plant here. No earlier project has all "
        "ten empty together: mule-fuel's terpene_notes is populated and the "
        "other two also carry selection_notes. Only id/cross/status/photos/"
        "notes carry data. "
        "Registry auto_create is TRUE while the template default is false "
        "(third discriminating case for Task 3.0 §8), with a single PC "
        "prefix. IDs are non-contiguous: PC01 then PC04..PC07 (no PC02/PC03). "
        "Its notes_meta.migration_note enumerates the five tabs by plant ID, "
        "so unlike honey-badger's stale note it can be cross-checked against "
        "the real roster."
    ),
)

SPACED_PASTE = ProjectSpec(
    slug="spaced-paste",
    plant_count=5,
    project_keys=frozenset(
        {
            "created",
            "cross_name",
            "drive_folders",
            "github_pages_url",
            "github_repo",
            "google_sheet_id",
            "google_sheet_url",
            "last_updated",
            "notes_meta",
            "plants",
        }
    ),
    plant_keys=_COMMON_PLANT_KEYS,
    expected_project_defaults=frozenset({"genetics", "breeder_lineage"}),
    notes=(
        "The FIRST project with a LOWERCASE plant-ID family: the prefix is "
        "'sp' and the IDs are 'sp01'..'sp06', where every earlier project used "
        "an uppercase prefix. Case is therefore load-bearing here in three "
        "places no earlier project could exercise: the per-plant FILENAME "
        "(sp01.md, which an ID upper-cased during migration renames while "
        "every field still round-trips), the routing pattern (production "
        "compiles with re.IGNORECASE, so a pattern that re-locked its own "
        "case still routes the canonical spelling and drops the other half of "
        "Discord's traffic), and the registry prefix itself. It is also "
        "JOINT-SHORTEST (2 chars, tied with MG/PK/PL/PC) and the only one "
        "that is a common English bigram, which makes the `\\b...\\b` "
        "boundary the sole thing stopping "
        "'sp' from firing inside ordinary prose. "
        "Second: the source `plants` array is NOT in ID order -- it is stored "
        "sp06, sp01, sp02, sp03, sp05 -- the first project where the array's "
        "order and the sorted-ID order differ, so a migration that rebuilt "
        "records from a directory glob (which sorts) silently reorders the "
        "roster while every field survives. "
        "Third: `photos_drive_url` is the EMPTY STRING on all five plants -- "
        "the first MIGRATED project where that is true of a PLANT field "
        "(kibungan had it at project level on google_sheet_url); lantz's data "
        "has the same shape but is not migrated yet, so this is the first "
        "opportunity to catch a '' -> None coercion, not the only one. "
        "Registry auto_create is false, which EQUALS the template default, so "
        "like mule-fuel this project's routing-field assertions are true but "
        "not discriminating for Task 3.0 §8. Unlike mule-fuel it DOES carry "
        "notes_meta, so `genetics` and `breeder_lineage` are the only "
        "defaulted project fields -- a combination no earlier project has. "
        "Every plant carries all 18 keys, so corrected_reading must be the "
        "ONLY defaulted plant field. IDs skip sp04. Nine of the ten nullable "
        "plant fields are null on every plant; selection_notes is populated on "
        "sp06 alone."
    ),
)

#: Every project whose migration has been accepted. Task 3.6 appends here.
PROJECT_SPECS = [MULE_FUEL, HONEY_BADGER_HAZE, KIBUNGAN, PALOMA_COMA, SPACED_PASTE]

SPECS_BY_SLUG = {spec.slug: spec for spec in PROJECT_SPECS}
