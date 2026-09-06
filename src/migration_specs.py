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

#: Every project whose migration has been accepted. Task 3.3 appends here.
PROJECT_SPECS = [MULE_FUEL, HONEY_BADGER_HAZE]

SPECS_BY_SLUG = {spec.slug: spec for spec in PROJECT_SPECS}
