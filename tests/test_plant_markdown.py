"""RED-phase tests for plant_markdown.py (Task 1.1).

Every test in this file was written and watched failing before any
implementation existed. Acceptance criteria mapped from the plan:

  (a) round-trip test passes
  (b) missing optional fields, unicode, empty observation_log, zero photos
  (c) explicit YAML type-coercion tests + malformed frontmatter, duplicate
      keys, oversized/recursive YAML rejection
  (d) markdown BODY round-trip is byte-exact, including hand-written formatting
  (e) tests watched failing first
  (f) pytest -q green with zero warnings
"""

import copy
import os
from pathlib import Path

import pytest

from plant_markdown import (
    DuplicateKeyError,
    MalformedFrontmatterError,
    PlantMarkdownError,
    SchemaTypeError,
    UnsafeYamlError,
    load_schema,
    read_plant,
    write_plant,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "plant-template.md"


@pytest.fixture()
def schema():
    return load_schema(TEMPLATE)


@pytest.fixture()
def full_plant():
    return {
        "id": "HBH01",
        "cross": "Honey Badger Haze",
        "status": "culled",
        "sex": None,
        "germ_date": "2026-03-01",
        "veg_start": None,
        "flower_flip": None,
        "harvest_date": None,
        "vigor": "strong",
        "structure": "tall, open, above average stretch",
        "terpene_notes": "ripe peach, gassy backend",
        "issues": None,
        "selection_notes": "not worth keeping",
        "photos": [
            {
                "drive_id": "1c1WUdvlrve0NzO6CEc",
                "drive_url": "https://drive.google.com/file/d/1c1WUdvlrve0NzO6CEc/view",
                "filename": "HBH01_1.jpg",
                "embed_url": "https://lh3.googleusercontent.com/d/1c1WUdvlrve0NzO6CEc",
            }
        ],
        "photo_count": 1,
        "photos_drive_url": "https://drive.google.com/drive/folders/1nudjrmDHq9",
        "original_notes": "Really nice peachy smell.",
        "corrected_reading": None,
        "observation_log": "### Day 67\nSmells like ripe fruit.\n",
    }


# ---------------------------------------------------------------- schema ----


class TestLoadSchema:
    def test_loads_descriptor_objects_not_example_data(self, schema):
        assert schema["vigor"]["type"] == "string"
        assert schema["vigor"]["default"] is None
        assert "vigor" in schema["vigor"]["description"].lower()

    def test_id_is_declared_string(self, schema):
        assert schema["id"]["type"] == "string"

    def test_observation_log_is_body_typed(self, schema):
        assert schema["observation_log"]["type"] == "body"

    def test_every_field_has_type_default_description(self, schema):
        for name, spec in schema.items():
            assert set(spec) == {"type", "default", "description"}, name
            assert isinstance(spec["description"], str) and spec["description"]

    def test_photos_default_is_empty_list_not_shared(self, schema):
        a = schema["photos"]["default"]
        assert a == []
        a2 = load_schema(TEMPLATE)["photos"]["default"]
        a.append("mutated")
        assert a2 == [], "schema defaults must not be shared mutable state"


# ------------------------------------------------------------ round-trip ----


class TestRoundTrip:
    def test_full_plant_round_trips_exactly(self, tmp_path, full_plant, schema):
        p = tmp_path / "HBH01.md"
        write_plant(p, full_plant, schema=schema)
        assert read_plant(p, schema=schema) == full_plant

    def test_round_trip_is_byte_stable_on_rewrite(self, tmp_path, full_plant, schema):
        p = tmp_path / "HBH01.md"
        write_plant(p, full_plant, schema=schema)
        first = p.read_bytes()
        write_plant(p, read_plant(p, schema=schema), schema=schema)
        assert p.read_bytes() == first

    def test_write_does_not_mutate_caller_dict(self, tmp_path, full_plant, schema):
        p = tmp_path / "HBH01.md"
        before = copy.deepcopy(full_plant)
        write_plant(p, full_plant, schema=schema)
        assert full_plant == before

    def test_file_starts_with_frontmatter_delimiter(self, tmp_path, full_plant, schema):
        p = tmp_path / "HBH01.md"
        write_plant(p, full_plant, schema=schema)
        assert p.read_text(encoding="utf-8").startswith("---\n")

    def test_frontmatter_key_order_follows_schema(self, tmp_path, full_plant, schema):
        p = tmp_path / "HBH01.md"
        write_plant(p, full_plant, schema=schema)
        text = p.read_text(encoding="utf-8")
        fm = text.split("\n---\n")[0][len("---\n") :]
        seen = [
            ln.split(":")[0]
            for ln in fm.splitlines()
            if ln and not ln[0].isspace() and not ln.startswith("-")
        ]
        expected = [k for k in schema if k != "observation_log" and k in full_plant]
        assert seen == expected


# ------------------------------------------------------- optional / edge ----


class TestOptionalAndEdgeCases:
    def test_missing_optional_fields_filled_with_schema_defaults(
        self, tmp_path, schema
    ):
        p = tmp_path / "Ltz07.md"
        write_plant(p, {"id": "Ltz07", "cross": "Lantz"}, schema=schema)
        got = read_plant(p, schema=schema)
        assert got["vigor"] is None
        assert got["photos"] == []
        assert got["photo_count"] == 0
        assert got["status"] is None
        assert got["observation_log"] == ""

    def test_zero_photos(self, tmp_path, full_plant, schema):
        full_plant["photos"] = []
        full_plant["photo_count"] = 0
        p = tmp_path / "z.md"
        write_plant(p, full_plant, schema=schema)
        assert read_plant(p, schema=schema)["photos"] == []

    def test_empty_observation_log(self, tmp_path, full_plant, schema):
        full_plant["observation_log"] = ""
        p = tmp_path / "e.md"
        write_plant(p, full_plant, schema=schema)
        assert read_plant(p, schema=schema)["observation_log"] == ""

    def test_unicode_in_observation_notes_survives(self, tmp_path, full_plant, schema):
        full_plant["observation_log"] = (
            "### HBH 01\u2620\ufe0f\nsmells like peaches \u2014 delightful as I\u2019m "
            "trimming it \U0001f33f\n\u4e2d\u6587 \u00fcml\u00e4ut\n"
        )
        full_plant["terpene_notes"] = "p\u00eache \u2014 caf\u00e9 \U0001f351"
        p = tmp_path / "u.md"
        write_plant(p, full_plant, schema=schema)
        got = read_plant(p, schema=schema)
        assert got["observation_log"] == full_plant["observation_log"]
        assert got["terpene_notes"] == full_plant["terpene_notes"]

    def test_unicode_written_raw_not_escaped(self, tmp_path, full_plant, schema):
        full_plant["terpene_notes"] = "p\u00eache"
        p = tmp_path / "u2.md"
        write_plant(p, full_plant, schema=schema)
        assert "p\u00eache" in p.read_text(encoding="utf-8")

    def test_null_false_zero_empty_defaults_preserved(self, tmp_path, schema):
        p = tmp_path / "n.md"
        data = {"id": "X1", "photo_count": 0, "vigor": "", "selection_notes": "", "sex": None}
        write_plant(p, data, schema=schema)
        got = read_plant(p, schema=schema)
        assert got["photo_count"] == 0
        assert got["vigor"] == ""
        assert got["selection_notes"] == ""
        assert got["sex"] is None

    def test_unknown_extra_field_is_preserved(self, tmp_path, schema):
        p = tmp_path / "x.md"
        write_plant(p, {"id": "X1", "future_field": "keep me"}, schema=schema)
        assert read_plant(p, schema=schema)["future_field"] == "keep me"

    def test_read_missing_file_raises(self, tmp_path, schema):
        with pytest.raises(FileNotFoundError):
            read_plant(tmp_path / "nope.md", schema=schema)


# ------------------------------------------------------------- the BODY ----


class TestBodyRoundTrip:
    """Criterion (d): the markdown body must survive byte-for-byte."""

    HAND_EDITED = (
        "## Observations\n"
        "\n"
        "- 2026-04-01 :: vigor 8, **stinky**\n"
        "-   2026-04-09 ::   ragged indentation kept   \n"
        "\n"
        "```\n"
        "  raw code fence --- with delimiter-ish text\n"
        "```\n"
        "\n"
        "| day | note |\n"
        "|-----|------|\n"
        "| 67  | ripe |\n"
        "\n"
        "\n"
        "trailing blank lines above are intentional\n"
    )

    def test_hand_written_formatting_survives_exactly(self, tmp_path, schema):
        p = tmp_path / "b.md"
        write_plant(p, {"id": "B1", "observation_log": self.HAND_EDITED}, schema=schema)
        assert read_plant(p, schema=schema)["observation_log"] == self.HAND_EDITED

    def test_body_containing_frontmatter_delimiter_survives(self, tmp_path, schema):
        body = "before\n---\nafter a bare delimiter line\n"
        p = tmp_path / "d.md"
        write_plant(p, {"id": "D1", "observation_log": body}, schema=schema)
        assert read_plant(p, schema=schema)["observation_log"] == body

    def test_body_with_crlf_and_tabs_survives(self, tmp_path, schema):
        body = "line one\twith tab\nline two  \n"
        p = tmp_path / "t.md"
        write_plant(p, {"id": "T1", "observation_log": body}, schema=schema)
        assert read_plant(p, schema=schema)["observation_log"] == body

    def test_manually_authored_file_body_read_verbatim(self, tmp_path, schema):
        p = tmp_path / "m.md"
        p.write_text(
            "---\nid: M1\n---\n" + self.HAND_EDITED, encoding="utf-8"
        )
        assert read_plant(p, schema=schema)["observation_log"] == self.HAND_EDITED

    def test_body_is_not_yaml_parsed(self, tmp_path, schema):
        body = "vigor: 9\nstatus: keeper\n"
        p = tmp_path / "y.md"
        write_plant(p, {"id": "Y1", "vigor": "strong", "observation_log": body}, schema=schema)
        got = read_plant(p, schema=schema)
        assert got["vigor"] == "strong"
        assert got["observation_log"] == body


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
            ("1:30", "1:30"),
        ],
    )
    def test_string_field_never_silently_coerced(
        self, tmp_path, schema, raw, expected
    ):
        p = tmp_path / "c.md"
        p.write_text(f"---\nid: {raw}\n---\n", encoding="utf-8")
        assert read_plant(p, schema=schema)["id"] == expected

    @pytest.mark.parametrize("raw", ["null", "~", ""])
    def test_bare_null_scalars_are_none_not_the_literal_text(
        self, tmp_path, schema, raw
    ):
        """A bare `null`/`~`/empty value means null - that is how write_plant
        serialises None, so it must read back as None for round-tripping."""
        p = tmp_path / "cn.md"
        p.write_text(f"---\nid: A1\nsex: {raw}\n---\n", encoding="utf-8")
        assert read_plant(p, schema=schema)["sex"] is None

    @pytest.mark.parametrize("raw", ["null", "~", "true", "07"])
    def test_quoted_scalars_always_stay_strings(self, tmp_path, schema, raw):
        p = tmp_path / "cq.md"
        p.write_text(f'---\nid: A1\nsex: "{raw}"\n---\n', encoding="utf-8")
        assert read_plant(p, schema=schema)["sex"] == raw

    def test_quoted_null_stays_string_but_bare_empty_is_none(self, tmp_path, schema):
        p = tmp_path / "c2.md"
        p.write_text("---\nid: A1\nsex:\n---\n", encoding="utf-8")
        assert read_plant(p, schema=schema)["sex"] is None

    def test_integer_field_stays_int(self, tmp_path):
        int_schema = {"id": {"type": "string", "default": None, "description": "id"},
                      "count": {"type": "integer", "default": None, "description": "a synthetic integer field for coercion testing (real schema has no integer fields)"}}
        p = tmp_path / "i.md"
        p.write_text("---\nid: A1\ncount: 8\n---\n", encoding="utf-8")
        got = read_plant(p, schema=int_schema)
        assert got["count"] == 8
        assert isinstance(got["count"], int) and not isinstance(got["count"], bool)

    def test_integer_field_given_string_digits_is_coerced_to_int(
        self, tmp_path
    ):
        int_schema = {"id": {"type": "string", "default": None, "description": "id"},
                      "count": {"type": "integer", "default": None, "description": "synthetic"}}
        p = tmp_path / "i2.md"
        p.write_text('---\nid: A1\ncount: "8"\n---\n', encoding="utf-8")
        assert read_plant(p, schema=int_schema)["count"] == 8

    def test_integer_field_given_non_numeric_raises(self, tmp_path):
        int_schema = {"id": {"type": "string", "default": None, "description": "id"},
                      "count": {"type": "integer", "default": None, "description": "synthetic"}}
        p = tmp_path / "i3.md"
        p.write_text("---\nid: A1\ncount: very good\n---\n", encoding="utf-8")
        with pytest.raises(SchemaTypeError):
            read_plant(p, schema=int_schema)

    def test_list_field_given_scalar_raises(self, tmp_path, schema):
        p = tmp_path / "l.md"
        p.write_text("---\nid: A1\nphotos: nope\n---\n", encoding="utf-8")
        with pytest.raises(SchemaTypeError):
            read_plant(p, schema=schema)

    def test_string_field_given_mapping_raises(self, tmp_path, schema):
        p = tmp_path / "s.md"
        p.write_text("---\nid:\n  a: 1\n---\n", encoding="utf-8")
        with pytest.raises(SchemaTypeError):
            read_plant(p, schema=schema)

    def test_write_read_of_stringy_id_is_stable(self, tmp_path, schema):
        p = tmp_path / "w.md"
        write_plant(p, {"id": "07", "status": "true"}, schema=schema)
        got = read_plant(p, schema=schema)
        assert got["id"] == "07"
        assert got["status"] == "true"

    def test_readback_types_are_json_compatible(self, tmp_path, full_plant, schema):
        import json

        p = tmp_path / "j.md"
        write_plant(p, full_plant, schema=schema)
        got = read_plant(p, schema=schema)
        assert json.loads(json.dumps(got)) == got

    def test_no_schema_still_reads_without_coercion_errors(self, tmp_path):
        p = tmp_path / "ns.md"
        p.write_text("---\nid: A1\nvigor: strong\n---\nbody\n", encoding="utf-8")
        got = read_plant(p)
        assert got["vigor"] == "strong"


# -------------------------------------------------------------- rejects ----


class TestMalformedInput:
    def test_no_frontmatter_at_all_rejected(self, tmp_path, schema):
        p = tmp_path / "bad.md"
        p.write_text("just a body, no frontmatter\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_unterminated_frontmatter_rejected(self, tmp_path, schema):
        p = tmp_path / "bad2.md"
        p.write_text("---\nid: A1\nstatus: active\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_leading_blank_line_before_delimiter_rejected(self, tmp_path, schema):
        p = tmp_path / "bad3.md"
        p.write_text("\n---\nid: A1\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_empty_file_rejected(self, tmp_path, schema):
        p = tmp_path / "bad4.md"
        p.write_text("", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_frontmatter_that_is_not_a_mapping_rejected(self, tmp_path, schema):
        p = tmp_path / "bad5.md"
        p.write_text("---\n- a\n- b\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_invalid_yaml_rejected(self, tmp_path, schema):
        p = tmp_path / "bad6.md"
        p.write_text("---\nid: [unclosed\n---\n", encoding="utf-8")
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_duplicate_keys_rejected(self, tmp_path, schema):
        p = tmp_path / "dup.md"
        p.write_text("---\nid: A1\nvigor: 8\nvigor: 9\n---\n", encoding="utf-8")
        with pytest.raises(DuplicateKeyError):
            read_plant(p, schema=schema)

    def test_duplicate_keys_in_nested_mapping_rejected(self, tmp_path, schema):
        p = tmp_path / "dup2.md"
        p.write_text(
            "---\nid: A1\nphotos:\n  - filename: a.jpg\n    filename: b.jpg\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(DuplicateKeyError):
            read_plant(p, schema=schema)

    def test_yaml_anchors_and_aliases_rejected(self, tmp_path, schema):
        p = tmp_path / "anchor.md"
        p.write_text(
            "---\nid: A1\nstructure: &a big\nissues: *a\n---\n", encoding="utf-8"
        )
        with pytest.raises(UnsafeYamlError):
            read_plant(p, schema=schema)

    def test_billion_laughs_style_expansion_rejected(self, tmp_path, schema):
        p = tmp_path / "boom.md"
        p.write_text(
            "---\n"
            "id: A1\n"
            "a: &a [x,x,x,x,x,x,x,x,x]\n"
            "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
            "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
            "d: [*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
            "---\n",
            encoding="utf-8",
        )
        with pytest.raises(UnsafeYamlError):
            read_plant(p, schema=schema)

    def test_python_object_tag_rejected(self, tmp_path, schema):
        p = tmp_path / "tag.md"
        p.write_text(
            "---\nid: A1\nissues: !!python/object/apply:os.system ['echo pwned']\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)

    def test_oversized_file_rejected(self, tmp_path, schema):
        p = tmp_path / "big.md"
        p.write_text(
            "---\nid: A1\nissues: " + ("x" * (3 * 1024 * 1024)) + "\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(UnsafeYamlError):
            read_plant(p, schema=schema)

    def test_deeply_nested_structure_rejected(self, tmp_path, schema):
        p = tmp_path / "deep.md"
        p.write_text("---\nid: A1\nphotos: " + "[" * 200 + "]" * 200 + "\n---\n",
                     encoding="utf-8")
        with pytest.raises(UnsafeYamlError):
            read_plant(p, schema=schema)

    def test_all_errors_subclass_plant_markdown_error(self):
        for exc in (MalformedFrontmatterError, DuplicateKeyError, SchemaTypeError,
                    UnsafeYamlError):
            assert issubclass(exc, PlantMarkdownError)


class TestCrlfPreservation:
    """Review finding: read_plant used text-mode universal-newline translation,
    silently turning \\r\\n into \\n. A Windows-edited or autocrlf=true-checked-out
    body must survive byte-for-byte, per criterion (d)."""

    def test_crlf_body_survives_exactly(self, tmp_path, schema):
        p = tmp_path / "crlf.md"
        body = "line one\r\nline two\r\n"
        write_plant(p, {"id": "C1", "observation_log": body}, schema=schema)
        assert read_plant(p, schema=schema)["observation_log"] == body

    def test_mixed_crlf_and_lf_body_survives_exactly(self, tmp_path, schema):
        p = tmp_path / "mixed.md"
        body = "unix line\nwindows line\r\nunix again\n"
        write_plant(p, {"id": "C2", "observation_log": body}, schema=schema)
        assert read_plant(p, schema=schema)["observation_log"] == body

    def test_manually_authored_crlf_file_read_verbatim(self, tmp_path, schema):
        p = tmp_path / "crlf_hand.md"
        with open(p, "wb") as fh:
            fh.write(b"---\r\nid: C3\r\n---\r\nnote one\r\nnote two\r\n")
        assert read_plant(p, schema=schema)["observation_log"] == "note one\r\nnote two\r\n"


class TestEmptyFrontmatterRoundTrip:
    """Review finding: write_plant with zero frontmatter fields emits
    '---\\n---\\nbody', which _split_frontmatter then rejected as
    'unterminated frontmatter' -- the writer produced a file its own reader
    could not read back."""

    def test_write_with_no_fields_round_trips(self, tmp_path, schema):
        p = tmp_path / "empty.md"
        write_plant(p, {"observation_log": "just a body\n"}, schema=None)
        got = read_plant(p, schema=None)
        assert got["observation_log"] == "just a body\n"

    def test_write_with_no_fields_and_no_body_round_trips(self, tmp_path):
        p = tmp_path / "empty2.md"
        write_plant(p, {}, schema=None)
        assert read_plant(p, schema=None)["observation_log"] == ""

    def test_write_with_no_fields_round_trips_with_schema(self, tmp_path, schema):
        p = tmp_path / "empty3.md"
        write_plant(p, {}, schema=schema)
        got = read_plant(p, schema=schema)
        assert got["observation_log"] == ""
        assert got["id"] is None


class TestHostileYamlRecursionGuard:
    """Review finding: PyYAML's own composer can hit Python's recursion limit
    while building nodes for a deeply-nested flow collection, raising a bare
    RecursionError *before* our post-parse _check_depth ever runs -- escaping
    every PlantMarkdownError-catching caller (e.g. the webhook's git-pull
    handler)."""

    def test_extremely_deep_nesting_raises_plant_markdown_error_not_recursionerror(
        self, tmp_path, schema
    ):
        depth = 2000
        p = tmp_path / "deep.md"
        p.write_text(
            "---\nid: A1\nphotos: " + "[" * depth + "]" * depth + "\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)


class TestCollectionTagsRejected:
    """Review finding: !!set / !!omap / !!pairs / !!binary aren't plain
    scalars/mappings/sequences our schema ever needs, but nothing rejected
    them: they were constructed by SafeLoader's own machinery and returned
    _Scalar-wrapped or native (set/bytes) objects that are neither
    JSON-serializable nor writable back out (yaml.representer.RepresenterError,
    not a PlantMarkdownError)."""

    def test_yaml_set_tag_rejected(self, tmp_path, schema):
        p = tmp_path / "set.md"
        p.write_text(
            "---\nid: A1\nissues: !!set {a: null, b: null}\n---\n", encoding="utf-8"
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)

    def test_yaml_omap_tag_rejected(self, tmp_path, schema):
        p = tmp_path / "omap.md"
        p.write_text(
            "---\nid: A1\nissues: !!omap\n  - a: 1\n---\n", encoding="utf-8"
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)

    def test_yaml_pairs_tag_rejected(self, tmp_path, schema):
        p = tmp_path / "pairs.md"
        p.write_text(
            "---\nid: A1\nissues: !!pairs\n  - a: 1\n---\n", encoding="utf-8"
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)

    def test_yaml_binary_tag_rejected(self, tmp_path, schema):
        p = tmp_path / "binary.md"
        p.write_text(
            "---\nid: A1\nissues: !!binary |\n  aGVsbG8=\n---\n", encoding="utf-8"
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)


class TestAnchorsRejectedEvenUnaliased:
    """Review finding: the module docstring claims 'Anchors are refused
    outright', but the actual guard only fired on AliasEvent -- a bare,
    never-referenced anchor (`structure: &a big`) parsed fine, contradicting
    the documented contract."""

    def test_unaliased_anchor_is_still_rejected(self, tmp_path, schema):
        p = tmp_path / "anchor_only.md"
        p.write_text(
            "---\nid: A1\nstructure: &a big\n---\n", encoding="utf-8"
        )
        with pytest.raises(UnsafeYamlError):
            read_plant(p, schema=schema)


class TestCustomScalarTagsRejected:
    """Review finding: an explicit, non-standard tag on a plain scalar
    (`!whatever hello`) fell through to the default constructor, which
    re-resolved the VALUE via the implicit resolver and silently discarded
    the tag entirely -- contradicting the 'custom tags rejected' claim,
    even though it happened to be harmless in practice."""

    def test_custom_tag_on_scalar_rejected(self, tmp_path, schema):
        p = tmp_path / "customtag.md"
        p.write_text(
            "---\nid: A1\nissues: !whatever hello\n---\n", encoding="utf-8"
        )
        with pytest.raises(MalformedFrontmatterError):
            read_plant(p, schema=schema)

    def test_python_name_tag_on_scalar_rejected(self, tmp_path, schema):
        p = tmp_path / "pyname.md"
        p.write_text(
            "---\nid: A1\nissues: !!python/name:os.system ''\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(PlantMarkdownError):
            read_plant(p, schema=schema)


class TestWritePermissionsPreserved:
    """Review finding: tempfile.mkstemp always creates 0600, and os.replace
    preserves the temp file's mode -- so rewriting an existing 0644 (the
    normal git-tracked mode) file silently downgraded it to 0600."""

    def test_rewriting_existing_file_preserves_its_mode(self, tmp_path, schema):
        p = tmp_path / "perm.md"
        write_plant(p, {"id": "A1"}, schema=schema)
        os.chmod(p, 0o644)
        write_plant(p, {"id": "A1", "vigor": 5}, schema=schema)
        assert (p.stat().st_mode & 0o777) == 0o644

    def test_new_file_gets_permissive_default_mode(self, tmp_path, schema):
        p = tmp_path / "newperm.md"
        write_plant(p, {"id": "A1"}, schema=schema)
        mode = p.stat().st_mode & 0o777
        assert mode != 0o600, "new plant files must not be created world-unreadable"


class TestUnknownSchemaTypeRejected:
    """Review finding: a typo'd `type: integr` in a template silently
    disabled coercion for that field with no error at all -- load_schema
    never validated the type vocabulary."""

    def test_load_schema_rejects_unknown_type(self, tmp_path):
        bad_template = tmp_path / "bad-template.md"
        bad_template.write_text(
            "---\nid:\n  type: string\n  default: null\n  description: x\n"
            "vigor:\n  type: banana\n  default: null\n  description: y\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(MalformedFrontmatterError):
            load_schema(bad_template)


class TestWriteValidation:
    def test_write_rejects_non_mapping(self, tmp_path, schema):
        with pytest.raises(TypeError):
            write_plant(tmp_path / "w.md", ["not", "a", "dict"], schema=schema)

    def test_write_rejects_non_string_keys(self, tmp_path, schema):
        with pytest.raises(TypeError):
            write_plant(tmp_path / "w.md", {1: "x"}, schema=schema)

    def test_write_creates_parent_directories(self, tmp_path, schema):
        p = tmp_path / "nested" / "deeper" / "P1.md"
        write_plant(p, {"id": "P1"}, schema=schema)
        assert read_plant(p, schema=schema)["id"] == "P1"

    def test_write_is_atomic_leaves_no_temp_files(self, tmp_path, schema):
        p = tmp_path / "a.md"
        write_plant(p, {"id": "A1"}, schema=schema)
        assert [f.name for f in tmp_path.iterdir()] == ["a.md"]

    def test_write_ends_with_single_trailing_newline(self, tmp_path, schema):
        p = tmp_path / "nl.md"
        write_plant(p, {"id": "A1", "observation_log": "note\n"}, schema=schema)
        text = p.read_text(encoding="utf-8")
        assert text.endswith("note\n") and not text.endswith("\n\n")
