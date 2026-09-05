"""RED-phase tests for project_markdown.py (Task 1.2).

Same acceptance-criteria shape as Task 1.1 (test_plant_markdown.py), adapted
for project.md's schema (no per-field "body" mapping - the freeform section
after frontmatter is project-level notes, always carried under the fixed
"body" key):

  (a) round-trip test passes
  (b) missing optional fields, unicode, empty body, empty containers
  (c) explicit YAML type-coercion tests (string/array/boolean/object) +
      malformed frontmatter, duplicate keys, oversized/recursive YAML
      rejection
  (d) markdown BODY round-trip is byte-exact, including hand-written
      formatting
  (e) tests watched failing first
  (f) pytest -q green with zero warnings
"""

import copy
from pathlib import Path

import pytest

from project_markdown import (
    DuplicateKeyError,
    MalformedFrontmatterError,
    ProjectMarkdownError,
    SchemaTypeError,
    UnsafeYamlError,
    load_schema,
    read_project,
    write_project,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "project-template.md"


@pytest.fixture()
def schema():
    return load_schema(TEMPLATE)


@pytest.fixture()
def full_project():
    return {
        "cross_name": "Lantz",
        "genetics": "Unknown x Unknown",
        "breeder_lineage": "Found in a mixed pack",
        "plant_id_prefixes": ["Ltz"],
        "auto_create": True,
        "github_repo": "https://github.com/example/lantz-data",
        "github_pages_url": "https://example.github.io/lantz",
        "google_sheet_id": None,
        "google_sheet_url": "https://docs.google.com/spreadsheets/d/abc123",
        "drive_folders": {"photos": "https://drive.google.com/drive/folders/abc"},
        "notes_meta": {"last_message_id": "123456789", "channel": "lantz-notes"},
        "created": "2026-01-01T00:00:00Z",
        "last_updated": "2026-08-30T12:00:00Z",
        "body": "## Lantz\n\nFreeform project notes.\n",
    }


# ---------------------------------------------------------------- schema ----


class TestLoadSchema:
    def test_loads_descriptor_objects_not_example_data(self, schema):
        assert schema["auto_create"]["type"] == "boolean"
        assert schema["auto_create"]["default"] is False

    def test_cross_name_is_declared_string(self, schema):
        assert schema["cross_name"]["type"] == "string"

    def test_plant_id_prefixes_is_declared_array(self, schema):
        assert schema["plant_id_prefixes"]["type"] == "array"
        assert schema["plant_id_prefixes"]["default"] == []

    def test_drive_folders_is_declared_object(self, schema):
        assert schema["drive_folders"]["type"] == "object"
        assert schema["drive_folders"]["default"] == {}

    def test_every_field_has_type_default_description(self, schema):
        for name, spec in schema.items():
            assert set(spec) == {"type", "default", "description"}, name
            assert isinstance(spec["description"], str) and spec["description"]

    def test_default_containers_are_not_shared_mutable_state(self, schema):
        a = schema["drive_folders"]["default"]
        assert a == {}
        a2 = load_schema(TEMPLATE)["drive_folders"]["default"]
        a["mutated"] = True
        assert a2 == {}, "schema defaults must not be shared mutable state"

        b = schema["plant_id_prefixes"]["default"]
        b.append("mutated")
        b2 = load_schema(TEMPLATE)["plant_id_prefixes"]["default"]
        assert b2 == []


# ------------------------------------------------------------ round-trip ----


class TestRoundTrip:
    def test_full_project_round_trips_exactly(self, tmp_path, full_project, schema):
        p = tmp_path / "project.md"
        write_project(p, full_project, schema=schema)
        assert read_project(p, schema=schema) == full_project

    def test_round_trip_is_byte_stable_on_rewrite(self, tmp_path, full_project, schema):
        p = tmp_path / "project.md"
        write_project(p, full_project, schema=schema)
        first = p.read_bytes()
        write_project(p, read_project(p, schema=schema), schema=schema)
        assert p.read_bytes() == first

    def test_write_does_not_mutate_caller_dict(self, tmp_path, full_project, schema):
        p = tmp_path / "project.md"
        before = copy.deepcopy(full_project)
        write_project(p, full_project, schema=schema)
        assert full_project == before

    def test_file_starts_with_frontmatter_delimiter(self, tmp_path, full_project, schema):
        p = tmp_path / "project.md"
        write_project(p, full_project, schema=schema)
        assert p.read_text(encoding="utf-8").startswith("---\n")

    def test_frontmatter_key_order_follows_schema(self, tmp_path, full_project, schema):
        p = tmp_path / "project.md"
        write_project(p, full_project, schema=schema)
        text = p.read_text(encoding="utf-8")
        fm = text.split("\n---\n")[0][len("---\n") :]
        seen = [
            ln.split(":")[0]
            for ln in fm.splitlines()
            if ln and not ln[0].isspace() and not ln.startswith("-")
        ]
        expected = [k for k in schema if k != "body" and k in full_project]
        assert seen == expected


# ------------------------------------------------------- optional / edge ----


class TestOptionalAndEdgeCases:
    def test_missing_optional_fields_filled_with_schema_defaults(self, tmp_path, schema):
        p = tmp_path / "project.md"
        write_project(p, {"cross_name": "Lantz"}, schema=schema)
        got = read_project(p, schema=schema)
        assert got["genetics"] is None
        assert got["plant_id_prefixes"] == []
        assert got["auto_create"] is False
        assert got["drive_folders"] == {}
        assert got["notes_meta"] == {}
        assert got["body"] == ""

    def test_empty_body(self, tmp_path, full_project, schema):
        full_project["body"] = ""
        p = tmp_path / "e.md"
        write_project(p, full_project, schema=schema)
        assert read_project(p, schema=schema)["body"] == ""

    def test_empty_containers(self, tmp_path, full_project, schema):
        full_project["plant_id_prefixes"] = []
        full_project["drive_folders"] = {}
        full_project["notes_meta"] = {}
        p = tmp_path / "c.md"
        write_project(p, full_project, schema=schema)
        got = read_project(p, schema=schema)
        assert got["plant_id_prefixes"] == []
        assert got["drive_folders"] == {}
        assert got["notes_meta"] == {}

    def test_unicode_in_body_survives(self, tmp_path, full_project, schema):
        full_project["body"] = (
            "## \u5170\u5179\n\nsmells like peaches \u2014 \U0001f33f\n"
        )
        full_project["genetics"] = "p\u00eache \u00d7 caf\u00e9"
        p = tmp_path / "u.md"
        write_project(p, full_project, schema=schema)
        got = read_project(p, schema=schema)
        assert got["body"] == full_project["body"]
        assert got["genetics"] == full_project["genetics"]

    def test_unicode_written_raw_not_escaped(self, tmp_path, full_project, schema):
        full_project["genetics"] = "p\u00eache"
        p = tmp_path / "u2.md"
        write_project(p, full_project, schema=schema)
        assert "p\u00eache" in p.read_text(encoding="utf-8")

    def test_null_false_zero_empty_defaults_preserved(self, tmp_path, schema):
        p = tmp_path / "n.md"
        data = {
            "cross_name": "X",
            "auto_create": False,
            "genetics": "",
            "google_sheet_id": None,
        }
        write_project(p, data, schema=schema)
        got = read_project(p, schema=schema)
        assert got["auto_create"] is False
        assert got["genetics"] == ""
        assert got["google_sheet_id"] is None

    def test_unknown_extra_field_is_preserved(self, tmp_path, schema):
        p = tmp_path / "x.md"
        write_project(p, {"cross_name": "X", "future_field": "keep me"}, schema=schema)
        assert read_project(p, schema=schema)["future_field"] == "keep me"

    def test_read_missing_file_raises(self, tmp_path, schema):
        with pytest.raises(FileNotFoundError):
            read_project(tmp_path / "nope.md", schema=schema)


# ------------------------------------------------------------- the BODY ----


class TestBodyRoundTrip:
    """Criterion (d): the markdown body must survive byte-for-byte."""

    HAND_EDITED = (
        "## Notes\n"
        "\n"
        "- 2026-04-01 :: kickoff\n"
        "-   2026-04-09 ::   ragged indentation kept   \n"
        "\n"
        "```\n"
        "  raw code fence --- with delimiter-ish text\n"
        "```\n"
        "\n"
        "| week | note |\n"
        "|------|------|\n"
        "| 1    | ok   |\n"
        "\n"
        "\n"
        "trailing blank lines above are intentional\n"
    )

    def test_hand_written_formatting_survives_exactly(self, tmp_path, schema):
        p = tmp_path / "b.md"
        write_project(p, {"cross_name": "X", "body": self.HAND_EDITED}, schema=schema)
        assert read_project(p, schema=schema)["body"] == self.HAND_EDITED

    def test_body_containing_frontmatter_delimiter_survives(self, tmp_path, schema):
        body = "before\n---\nafter a bare delimiter line\n"
        p = tmp_path / "d.md"
        write_project(p, {"cross_name": "X", "body": body}, schema=schema)
        assert read_project(p, schema=schema)["body"] == body

    def test_body_with_crlf_and_tabs_survives(self, tmp_path, schema):
        body = "line one\twith tab\nline two  \n"
        p = tmp_path / "t.md"
        write_project(p, {"cross_name": "X", "body": body}, schema=schema)
        assert read_project(p, schema=schema)["body"] == body

    def test_manually_authored_file_body_read_verbatim(self, tmp_path, schema):
        p = tmp_path / "m.md"
        p.write_text(
            "---\ncross_name: X\n---\n" + self.HAND_EDITED, encoding="utf-8"
        )
        assert read_project(p, schema=schema)["body"] == self.HAND_EDITED

    def test_body_is_not_yaml_parsed(self, tmp_path, schema):
        body = "cross_name: fake\nauto_create: true\n"
        p = tmp_path / "y.md"
        write_project(
            p, {"cross_name": "X", "auto_create": False, "body": body}, schema=schema
        )
        got = read_project(p, schema=schema)
        assert got["auto_create"] is False
        assert got["body"] == body

    def test_no_frontmatter_fields_still_has_body_key(self, tmp_path, schema):
        p = tmp_path / "z.md"
        write_project(p, {"cross_name": "X"}, schema=schema)
        got = read_project(p, schema=schema)
        assert got["body"] == ""


# ------------------------------------------------------ type  coercion ----


class TestYamlTypeCoercion:
    """Criterion (c): declared type wins over PyYAML's automatic guessing."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("07", "07"),
            ("007", "007"),
            ("true", "true"),
            ("False", "False"),
            ("no", "no"),
            ("1.20", "1.20"),
            ("0x1A", "0x1A"),
            ("2026-03-01", "2026-03-01"),
        ],
    )
    def test_string_field_never_silently_coerced(self, tmp_path, schema, raw, expected):
        p = tmp_path / "c.md"
        p.write_text(f"---\ncross_name: {raw}\n---\n", encoding="utf-8")
        assert read_project(p, schema=schema)["cross_name"] == expected

    @pytest.mark.parametrize("raw", ["null", "~", ""])
    def test_bare_null_scalars_are_none_not_the_literal_text(self, tmp_path, schema, raw):
        p = tmp_path / "cn.md"
        p.write_text(
            f"---\ncross_name: X\ngenetics: {raw}\n---\n", encoding="utf-8"
        )
        assert read_project(p, schema=schema)["genetics"] is None

    @pytest.mark.parametrize("raw", ["null", "~", "true", "07"])
    def test_quoted_scalars_always_stay_strings(self, tmp_path, schema, raw):
        p = tmp_path / "cq.md"
        p.write_text(
            f'---\ncross_name: X\ngenetics: "{raw}"\n---\n', encoding="utf-8"
        )
        assert read_project(p, schema=schema)["genetics"] == raw

    def test_boolean_field_stays_bool(self, tmp_path, schema):
        p = tmp_path / "i.md"
        p.write_text("---\ncross_name: X\nauto_create: true\n---\n", encoding="utf-8")
        got = read_project(p, schema=schema)
        assert got["auto_create"] is True
        assert isinstance(got["auto_create"], bool)

    def test_boolean_field_given_string_is_coerced(self, tmp_path, schema):
        p = tmp_path / "i2.md"
        p.write_text(
            '---\ncross_name: X\nauto_create: "true"\n---\n', encoding="utf-8"
        )
        assert read_project(p, schema=schema)["auto_create"] is True

    def test_boolean_field_given_non_boolean_raises(self, tmp_path, schema):
        p = tmp_path / "i3.md"
        p.write_text(
            "---\ncross_name: X\nauto_create: maybe\n---\n", encoding="utf-8"
        )
        with pytest.raises(SchemaTypeError):
            read_project(p, schema=schema)

    def test_array_field_given_scalar_raises(self, tmp_path, schema):
        p = tmp_path / "l.md"
        p.write_text(
            "---\ncross_name: X\nplant_id_prefixes: nope\n---\n", encoding="utf-8"
        )
        with pytest.raises(SchemaTypeError):
            read_project(p, schema=schema)

    def test_object_field_given_scalar_raises(self, tmp_path, schema):
        p = tmp_path / "o.md"
        p.write_text(
            "---\ncross_name: X\ndrive_folders: nope\n---\n", encoding="utf-8"
        )
        with pytest.raises(SchemaTypeError):
            read_project(p, schema=schema)

    def test_object_field_given_list_raises(self, tmp_path, schema):
        p = tmp_path / "o2.md"
        p.write_text(
            "---\ncross_name: X\ndrive_folders:\n  - a\n  - b\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(SchemaTypeError):
            read_project(p, schema=schema)

    def test_string_field_given_mapping_raises(self, tmp_path, schema):
        p = tmp_path / "s.md"
        p.write_text("---\ncross_name:\n  a: 1\n---\n", encoding="utf-8")
        with pytest.raises(SchemaTypeError):
            read_project(p, schema=schema)

    def test_readback_types_are_json_compatible(self, tmp_path, full_project, schema):
        import json

        p = tmp_path / "j.md"
        write_project(p, full_project, schema=schema)
        got = read_project(p, schema=schema)
        assert json.loads(json.dumps(got)) == got

    def test_no_schema_still_reads_without_coercion_errors(self, tmp_path):
        p = tmp_path / "ns.md"
        p.write_text(
            "---\ncross_name: X\nauto_create: true\n---\nbody\n", encoding="utf-8"
        )
        got = read_project(p)
        assert got["auto_create"] is True


# -------------------------------------------------------------- rejects ----


class TestMalformedInput:
    def test_no_frontmatter_at_all_rejected(self, tmp_path, schema):
        p = tmp_path / "bad.md"
        p.write_text("just a body, no frontmatter\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_unterminated_frontmatter_rejected(self, tmp_path, schema):
        p = tmp_path / "bad2.md"
        p.write_text("---\ncross_name: X\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_leading_blank_line_before_delimiter_rejected(self, tmp_path, schema):
        p = tmp_path / "bad3.md"
        p.write_text("\n---\ncross_name: X\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_empty_file_rejected(self, tmp_path, schema):
        p = tmp_path / "bad4.md"
        p.write_text("", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_frontmatter_that_is_not_a_mapping_rejected(self, tmp_path, schema):
        p = tmp_path / "bad5.md"
        p.write_text("---\n- a\n- b\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_invalid_yaml_rejected(self, tmp_path, schema):
        p = tmp_path / "bad6.md"
        p.write_text("---\ncross_name: [unclosed\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_duplicate_keys_rejected(self, tmp_path, schema):
        p = tmp_path / "dup.md"
        p.write_text(
            "---\ncross_name: X\ngenetics: A\ngenetics: B\n---\n", encoding="utf-8"
        )
        with pytest.raises(DuplicateKeyError):
            read_project(p, schema=schema)

    def test_duplicate_keys_in_nested_mapping_rejected(self, tmp_path, schema):
        p = tmp_path / "dup2.md"
        p.write_text(
            "---\ncross_name: X\ndrive_folders:\n  a: 1\n  a: 2\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(DuplicateKeyError):
            read_project(p, schema=schema)

    def test_yaml_anchors_and_aliases_rejected(self, tmp_path, schema):
        p = tmp_path / "anchor.md"
        p.write_text(
            "---\ncross_name: X\ngenetics: &a big\nbreeder_lineage: *a\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(UnsafeYamlError):
            read_project(p, schema=schema)

    def test_billion_laughs_style_expansion_rejected(self, tmp_path, schema):
        p = tmp_path / "boom.md"
        p.write_text(
            "---\n"
            "cross_name: X\n"
            "a: &a [x,x,x,x,x,x,x,x,x]\n"
            "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
            "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
            "d: [*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
            "---\n",
            encoding="utf-8",
        )
        with pytest.raises(UnsafeYamlError):
            read_project(p, schema=schema)

    def test_python_object_tag_rejected(self, tmp_path, schema):
        p = tmp_path / "tag.md"
        p.write_text(
            "---\ncross_name: X\ngenetics: !!python/object/apply:os.system ['echo pwned']\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(ProjectMarkdownError):
            read_project(p, schema=schema)

    def test_oversized_file_rejected(self, tmp_path, schema):
        p = tmp_path / "big.md"
        p.write_text(
            "---\ncross_name: X\ngenetics: " + ("x" * (3 * 1024 * 1024)) + "\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(UnsafeYamlError):
            read_project(p, schema=schema)

    def test_deeply_nested_structure_rejected(self, tmp_path, schema):
        p = tmp_path / "deep.md"
        p.write_text(
            "---\ncross_name: X\ndrive_folders: " + "[" * 200 + "]" * 200 + "\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(UnsafeYamlError):
            read_project(p, schema=schema)

    def test_all_errors_subclass_project_markdown_error(self):
        for exc in (
            MalformedFrontmatterError,
            DuplicateKeyError,
            SchemaTypeError,
            UnsafeYamlError,
        ):
            assert issubclass(exc, ProjectMarkdownError)


class TestWriteValidation:
    def test_write_rejects_non_mapping(self, tmp_path, schema):
        with pytest.raises(TypeError):
            write_project(tmp_path / "w.md", ["not", "a", "dict"], schema=schema)

    def test_write_rejects_non_string_keys(self, tmp_path, schema):
        with pytest.raises(TypeError):
            write_project(tmp_path / "w.md", {1: "x"}, schema=schema)

    def test_write_creates_parent_directories(self, tmp_path, schema):
        p = tmp_path / "nested" / "deeper" / "project.md"
        write_project(p, {"cross_name": "X"}, schema=schema)
        assert read_project(p, schema=schema)["cross_name"] == "X"

    def test_write_is_atomic_leaves_no_temp_files(self, tmp_path, schema):
        p = tmp_path / "a.md"
        write_project(p, {"cross_name": "X"}, schema=schema)
        assert [f.name for f in tmp_path.iterdir()] == ["a.md"]

    def test_write_ends_with_single_trailing_newline(self, tmp_path, schema):
        p = tmp_path / "nl.md"
        write_project(p, {"cross_name": "X", "body": "note\n"}, schema=schema)
        text = p.read_text(encoding="utf-8")
        assert text.endswith("note\n") and not text.endswith("\n\n")


# ------------------------------------------------- spec-compliance review ----
# The following classes cover gaps found by porting plant_markdown.py's
# (Task 1.1's) hardened behavior across to project_markdown.py (Task 1.2),
# which had drifted behind it.


class TestCrlfPreservation:
    """Task 1.1 parity: read_project used Path.read_text() WITHOUT
    newline="", so universal-newline translation silently rewrote a
    Windows-authored (or autocrlf=true-checked-out) CRLF body to LF; and
    write_project hardcoded LF delimiters even for a CRLF body, producing a
    mixed-newline file and a spurious whole-header diff on every touch."""

    def test_crlf_body_survives_exactly(self, tmp_path, schema):
        p = tmp_path / "crlf.md"
        body = "line one\r\nline two\r\n"
        write_project(p, {"cross_name": "C1", "body": body}, schema=schema)
        assert read_project(p, schema=schema)["body"] == body

    def test_manually_authored_crlf_file_read_verbatim(self, tmp_path, schema):
        p = tmp_path / "crlf_hand.md"
        with open(p, "wb") as fh:
            fh.write(b"---\r\ncross_name: C3\r\n---\r\nnote one\r\nnote two\r\n")
        assert (
            read_project(p, schema=schema)["body"] == "note one\r\nnote two\r\n"
        )

    def test_crlf_rewrite_is_line_ending_consistent(self, tmp_path, schema):
        p = tmp_path / "crlf_rw.md"
        with open(p, "wb") as fh:
            fh.write(b"---\r\ncross_name: C4\r\n---\r\nnote one\r\nnote two\r\n")
        got = read_project(p, schema=schema)
        write_project(p, got, schema=schema)
        rewritten = p.read_bytes()
        assert b"\r\n" in rewritten
        # No bare LF anywhere that isn't part of a CRLF pair.
        assert b"\n" not in rewritten.replace(b"\r\n", b"")
        canonical = rewritten
        write_project(p, read_project(p, schema=schema), schema=schema)
        assert p.read_bytes() == canonical

    def test_mixed_crlf_and_lf_body_survives_exactly(self, tmp_path, schema):
        p = tmp_path / "mixed.md"
        body = "unix line\nwindows line\r\nunix again\n"
        write_project(p, {"cross_name": "C2", "body": body}, schema=schema)
        assert read_project(p, schema=schema)["body"] == body


class TestEmptyFrontmatterRoundTrip:
    """Task 1.1 parity: write_project with zero frontmatter fields emits
    '---\\n---\\nbody', which _split_frontmatter then rejected as
    'unterminated frontmatter' -- the writer produced a file its own reader
    could not read back."""

    def test_write_with_no_fields_round_trips(self, tmp_path):
        p = tmp_path / "empty.md"
        write_project(p, {"body": "hello\n"}, schema=None)
        assert read_project(p, schema=None)["body"] == "hello\n"

    def test_write_with_no_fields_and_no_body_round_trips(self, tmp_path):
        p = tmp_path / "empty2.md"
        write_project(p, {}, schema=None)
        assert read_project(p, schema=None)["body"] == ""

    def test_write_with_no_fields_round_trips_with_schema(self, tmp_path, schema):
        p = tmp_path / "empty3.md"
        write_project(p, {}, schema=schema)
        got = read_project(p, schema=schema)
        assert got["body"] == ""
        assert got["cross_name"] is None


class TestHostileYamlRecursionGuard:
    """Task 1.1 parity: PyYAML's composer hits Python's own recursion limit
    while building nodes for a deeply-nested flow collection, raising a bare
    RecursionError BEFORE the post-parse _check_depth runs -- escaping every
    ProjectMarkdownError-catching caller."""

    def test_extremely_deep_nesting_raises_project_markdown_error(
        self, tmp_path, schema
    ):
        depth = 2000
        p = tmp_path / "deep.md"
        p.write_text(
            "---\ncross_name: A1\nplant_id_prefixes: "
            + "[" * depth
            + "]" * depth
            + "\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(ProjectMarkdownError):
            read_project(p, schema=schema)


class TestUnknownSchemaTypeRejected:
    """Task 1.1 parity: load_schema never validated the `type` vocabulary --
    a typo'd `type: banana` silently disabled coercion for that field."""

    def test_load_schema_rejects_unknown_type(self, tmp_path):
        bad_template = tmp_path / "bad-template.md"
        bad_template.write_text(
            "---\ncross_name:\n  type: string\n  default: null\n  description: x\n"
            "auto_create:\n  type: banana\n  default: null\n  description: y\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(MalformedFrontmatterError):
            load_schema(bad_template)

    def test_load_schema_accepts_every_type_the_real_template_uses(self, schema):
        assert {spec["type"] for spec in schema.values()} <= {
            "string",
            "integer",
            "boolean",
            "array",
            "list",
            "object",
            "body",
        }


class TestUnhashableKeyRejected:
    """Task 1.1 parity: a YAML complex/collection key (`? [a, b]`) is
    unhashable, so _no_duplicates' `key in mapping` raised a bare TypeError
    that escaped the documented ProjectMarkdownError contract."""

    def test_complex_key_rejected_as_malformed(self, tmp_path, schema):
        p = tmp_path / "complexkey.md"
        p.write_text("---\n? [a, b]\n: v\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)


class TestSymlinkSizeLimitNotBypassable:
    """Task 1.1 parity: read_project used Path.stat() (which follows
    symlinks) for the MAX_FILE_BYTES guard, then read the file
    unconditionally -- a git-committed symlink to /dev/zero reports a tiny
    apparent size while the actual read is unbounded."""

    def test_oversized_content_rejected_even_via_capped_read(self, tmp_path, schema):
        import project_markdown

        p = tmp_path / "big.md"
        big_body = "x" * (project_markdown.MAX_FILE_BYTES + 100)
        p.write_text(f"---\ncross_name: A1\n---\n{big_body}", encoding="utf-8")
        with pytest.raises(UnsafeYamlError):
            read_project(p, schema=schema)

    def test_symlink_to_unbounded_device_does_not_exhaust_memory(self, tmp_path):
        """The real scenario: a git-committed symlink to /dev/zero. stat()
        follows it and reports size 0, so the pre-read guard passes, and an
        uncapped read then consumes memory without bound (this test OOMs the
        interpreter against the unfixed code). Run in a child process under
        a hard address-space limit so a regression fails fast and loudly
        instead of taking the whole test session down with it."""
        import os
        import subprocess
        import sys

        if not os.path.exists("/dev/zero"):
            pytest.skip("/dev/zero unavailable on this platform")
        link = tmp_path / "link.md"
        os.symlink("/dev/zero", link)

        program = (
            "import resource, sys\n"
            "resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)\n"
            "sys.path.insert(0, %r)\n"
            "import project_markdown\n"
            "try:\n"
            "    project_markdown.read_project(%r)\n"
            "except project_markdown.ProjectMarkdownError:\n"
            "    print('OK')\n"
            % (str(Path(__file__).resolve().parents[1] / "src"), str(link))
        )
        proc = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.stdout.strip() == "OK", (
            f"expected ProjectMarkdownError, got rc={proc.returncode} "
            f"stderr={proc.stderr[-500:]!r}"
        )


class TestWritePermissionsPreserved:
    """Task 1.1 parity: tempfile.mkstemp always creates 0600 and os.replace
    preserves the temp file's mode, so rewriting an existing 0644
    (the normal git-tracked mode) project.md silently downgraded it."""

    def test_rewriting_existing_file_preserves_its_mode(self, tmp_path, schema):
        import os

        p = tmp_path / "perm.md"
        write_project(p, {"cross_name": "A1"}, schema=schema)
        os.chmod(p, 0o644)
        write_project(p, {"cross_name": "A1", "auto_create": True}, schema=schema)
        assert (p.stat().st_mode & 0o777) == 0o644

    def test_new_file_gets_permissive_default_mode(self, tmp_path, schema):
        p = tmp_path / "newperm.md"
        write_project(p, {"cross_name": "A1"}, schema=schema)
        mode = p.stat().st_mode & 0o777
        assert mode != 0o600, "new project files must not be created world-unreadable"


class TestBodyKeyInFrontmatterRejected:
    """Task 1.1 parity: 'body' belongs in the markdown BODY, never in
    frontmatter. read_project SILENTLY DISCARDED a hand-entered frontmatter
    'body:' key, losing real data; plant_markdown rejects the analogous
    observation_log case outright."""

    def test_body_in_frontmatter_is_rejected_not_discarded(self, tmp_path, schema):
        p = tmp_path / "bodykey.md"
        p.write_text(
            "---\ncross_name: A1\nbody: oops hand-entered\n---\nreal body\n",
            encoding="utf-8",
        )
        with pytest.raises(MalformedFrontmatterError):
            read_project(p, schema=schema)

    def test_body_in_frontmatter_rejected_without_schema(self, tmp_path):
        p = tmp_path / "bodykey2.md"
        p.write_text(
            "---\ncross_name: A1\nbody: oops\n---\nreal body\n", encoding="utf-8"
        )
        with pytest.raises(MalformedFrontmatterError):
            read_project(p)
