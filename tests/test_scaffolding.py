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
