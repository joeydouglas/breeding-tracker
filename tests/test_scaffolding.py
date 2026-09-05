"""RED-phase tests for scaffolding.py (Task 1.4).

Acceptance criteria (Revision 3 fix — Codex round-2 Critical #1, partial):
a freshly-scaffolded file's parsed field VALUES (not just keys) must exactly
match the current template's declared defaults, with real values (not
descriptor objects) written to the new file; null/false/0/"" defaults must
be preserved as those exact values, not dropped or coerced to a truthy
placeholder.
"""

from pathlib import Path

import pytest

import plant_markdown
import project_markdown
from scaffolding import scaffold_new_plant, scaffold_new_project

PLANT_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "plant-template.md"
)
PROJECT_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "project-template.md"
)


class TestScaffoldNewPlant:
    def test_creates_file_at_given_path(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09", "cross": "Lantz"})
        assert p.exists()

    def test_field_values_exactly_match_template_defaults(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09", "cross": "Lantz"})
        schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        got = plant_markdown.read_plant(p, schema=schema)
        for field, spec in schema.items():
            if field in ("id", "cross"):
                continue
            assert got[field] == spec["default"], field

    def test_overrides_take_precedence_over_defaults(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(
            PLANT_TEMPLATE, p, {"id": "Ltz09", "cross": "Lantz", "vigor": "strong"}
        )
        schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        got = plant_markdown.read_plant(p, schema=schema)
        assert got["vigor"] == "strong"

    def test_no_descriptor_objects_leak_into_written_values(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09", "cross": "Lantz"})
        text = p.read_text(encoding="utf-8")
        assert "description:" not in text
        assert "default:" not in text
        assert "type:" not in text

    def test_null_default_preserved_exactly(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09"})
        schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        got = plant_markdown.read_plant(p, schema=schema)
        assert got["sex"] is None
        assert got["vigor"] is None

    def test_false_and_zero_and_empty_string_defaults_preserved(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09"})
        schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        got = plant_markdown.read_plant(p, schema=schema)
        assert got["photo_count"] == 0
        assert got["observation_log"] == ""

    def test_empty_list_default_preserved_and_independent_per_call(self, tmp_path):
        p1 = tmp_path / "A.md"
        p2 = tmp_path / "B.md"
        scaffold_new_plant(PLANT_TEMPLATE, p1, {"id": "A"})
        scaffold_new_plant(PLANT_TEMPLATE, p2, {"id": "B"})
        schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        got1 = plant_markdown.read_plant(p1, schema=schema)
        got2 = plant_markdown.read_plant(p2, schema=schema)
        assert got1["photos"] == []
        assert got2["photos"] == []
        got1["photos"].append("mutated")
        assert got2["photos"] == []

    def test_raises_if_file_already_exists(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09"})
        with pytest.raises(FileExistsError):
            scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09"})


class TestScaffoldNewProject:
    def test_creates_file_at_given_path(self, tmp_path):
        p = tmp_path / "project.md"
        scaffold_new_project(PROJECT_TEMPLATE, p, {"cross_name": "Lantz"})
        assert p.exists()

    def test_field_values_exactly_match_template_defaults(self, tmp_path):
        p = tmp_path / "project.md"
        scaffold_new_project(PROJECT_TEMPLATE, p, {"cross_name": "Lantz"})
        schema = project_markdown.load_schema(PROJECT_TEMPLATE)
        got = project_markdown.read_project(p, schema=schema)
        for field, spec in schema.items():
            if field == "cross_name":
                continue
            assert got[field] == spec["default"], field

    def test_boolean_false_default_preserved(self, tmp_path):
        p = tmp_path / "project.md"
        scaffold_new_project(PROJECT_TEMPLATE, p, {"cross_name": "Lantz"})
        schema = project_markdown.load_schema(PROJECT_TEMPLATE)
        got = project_markdown.read_project(p, schema=schema)
        assert got["auto_create"] is False

    def test_empty_dict_and_list_defaults_are_independent_per_call(self, tmp_path):
        p1 = tmp_path / "p1.md"
        p2 = tmp_path / "p2.md"
        scaffold_new_project(PROJECT_TEMPLATE, p1, {"cross_name": "A"})
        scaffold_new_project(PROJECT_TEMPLATE, p2, {"cross_name": "B"})
        schema = project_markdown.load_schema(PROJECT_TEMPLATE)
        got1 = project_markdown.read_project(p1, schema=schema)
        got1["drive_folders"]["mutated"] = True
        got1["plant_id_prefixes"].append("mutated")
        got2 = project_markdown.read_project(p2, schema=schema)
        assert got2["drive_folders"] == {}
        assert got2["plant_id_prefixes"] == []

    def test_no_descriptor_objects_leak_into_written_values(self, tmp_path):
        p = tmp_path / "project.md"
        scaffold_new_project(PROJECT_TEMPLATE, p, {"cross_name": "Lantz"})
        text = p.read_text(encoding="utf-8")
        assert "description:" not in text
        assert "default:" not in text

    def test_raises_if_file_already_exists(self, tmp_path):
        p = tmp_path / "project.md"
        scaffold_new_project(PROJECT_TEMPLATE, p, {"cross_name": "Lantz"})
        with pytest.raises(FileExistsError):
            scaffold_new_project(PROJECT_TEMPLATE, p, {"cross_name": "Lantz"})


# ------------------------- code-quality review round 3 (error handling) ----
#
# scaffolding.py's suite was almost entirely happy-path: every existing test
# passes a valid template and schema-conformant overrides. These cover the
# three failure modes a caller (breeding_core's auto-create path) can
# actually hit.


class TestScaffoldingErrorPaths:
    def test_override_violating_schema_type_is_not_validated_at_scaffold_time(
        self, tmp_path
    ):
        """Pins CURRENT behaviour, deliberately not a demand for a fix.

        An override whose value can't be represented as the field's declared
        type is written out unvalidated, producing a file that `read_plant`
        with the same schema then refuses to parse back. Override validation
        is documented accepted technical debt (Minor severity: every real
        caller is `breeding_core`, which passes schema-shaped values), so
        this test exists to make the behaviour VISIBLE and to fail loudly if
        it silently changes in either direction."""
        p = tmp_path / "Ltz09.md"
        scaffold_new_plant(PLANT_TEMPLATE, p, {"id": "Ltz09", "photos": "not-a-list"})
        schema = plant_markdown.load_schema(PLANT_TEMPLATE)
        with pytest.raises(plant_markdown.SchemaTypeError):
            plant_markdown.read_plant(p, schema=schema)

    def test_project_override_violating_schema_type_is_not_validated(self, tmp_path):
        """Same accepted-debt pin for scaffold_new_project."""
        p = tmp_path / "project.md"
        scaffold_new_project(
            PROJECT_TEMPLATE, p, {"cross_name": "Lantz", "drive_folders": "nope"}
        )
        schema = project_markdown.load_schema(PROJECT_TEMPLATE)
        with pytest.raises(project_markdown.SchemaTypeError):
            project_markdown.read_project(p, schema=schema)

    def test_nonexistent_template_path_raises_filenotfound(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        with pytest.raises(FileNotFoundError):
            scaffold_new_plant(tmp_path / "no-such-template.md", p, {"id": "Ltz09"})
        assert not p.exists(), "no file may be created when the template is unusable"

    def test_project_nonexistent_template_path_raises_filenotfound(self, tmp_path):
        p = tmp_path / "project.md"
        with pytest.raises(FileNotFoundError):
            scaffold_new_project(
                tmp_path / "no-such-template.md", p, {"cross_name": "Lantz"}
            )
        assert not p.exists()

    def test_malformed_template_raises_markdown_error(self, tmp_path):
        """A template that isn't a valid frontmatter document at all (no
        delimiters) must surface the module's own error type, not a bare
        parse crash."""
        bad_template = tmp_path / "bad-template.md"
        bad_template.write_text("no frontmatter here\n", encoding="utf-8")
        p = tmp_path / "Ltz09.md"
        with pytest.raises(plant_markdown.PlantMarkdownError):
            scaffold_new_plant(bad_template, p, {"id": "Ltz09"})
        assert not p.exists()

    def test_template_of_example_values_not_descriptors_rejected(self, tmp_path):
        """A template accidentally authored as example DATA rather than
        {type, default, description} descriptors must be rejected, not
        scaffolded into a file full of garbage."""
        bad_template = tmp_path / "example-values-template.md"
        bad_template.write_text("---\nid: Ltz01\nvigor: strong\n---\n", encoding="utf-8")
        p = tmp_path / "Ltz09.md"
        with pytest.raises(plant_markdown.MalformedFrontmatterError):
            scaffold_new_plant(bad_template, p, {"id": "Ltz09"})
        assert not p.exists()

    def test_non_mapping_overrides_rejected(self, tmp_path):
        """`overrides` is documented as a Mapping. A list/None must raise
        rather than silently scaffold a defaults-only file — and crucially
        must NOT leave a partially-written file behind, since the caller's
        FileExistsError guard would then refuse to retry that plant forever.

        The exact exception type is not pinned: `dict.update` raises
        ValueError for a wrong-shaped sequence and TypeError for a
        non-iterable, and normalising that is on the accepted-debt list."""
        p = tmp_path / "Ltz09.md"
        with pytest.raises((TypeError, ValueError)):
            scaffold_new_plant(PLANT_TEMPLATE, p, ["id", "Ltz09"])
        assert not p.exists()

    def test_none_overrides_rejected(self, tmp_path):
        p = tmp_path / "Ltz09.md"
        with pytest.raises((TypeError, ValueError)):
            scaffold_new_plant(PLANT_TEMPLATE, p, None)
        assert not p.exists()

    def test_project_non_mapping_overrides_rejected(self, tmp_path):
        p = tmp_path / "project.md"
        with pytest.raises((TypeError, ValueError)):
            scaffold_new_project(PROJECT_TEMPLATE, p, ["cross_name", "Lantz"])
        assert not p.exists()
