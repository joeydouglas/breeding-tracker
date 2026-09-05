"""Read and write plant markdown files (frontmatter + observation-log body).

The markdown file is the sole source of truth for a plant. Layout:

    ---
    id: HBH01
    vigor: 8
    ---
    ### Day 67
    Smells like ripe fruit.

Frontmatter holds scalar/list fields; the markdown BODY holds the
``observation_log`` verbatim, so hand-written formatting survives byte-for-byte.

Design rules this module enforces:

* **Declared types win over PyYAML's guessing.** A hand-edited ``id: 07`` stays
  the string ``"07"``; ``status: true`` stays ``"true"``. Coercion is driven by
  the template schema, never by YAML's implicit resolver.
* **Untrusted input.** Files arrive via ``git pull`` from repos humans hand-edit,
  so parsing rejects anchors/aliases, custom tags, duplicate keys, oversized
  input, and excessive nesting rather than trusting them.
* **Round-trip fidelity.** ``read_plant(write_plant(x)) == x``, and rewriting an
  unmodified file is byte-stable.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import yaml

__all__ = [
    "PlantMarkdownError",
    "MalformedFrontmatterError",
    "DuplicateKeyError",
    "SchemaTypeError",
    "UnsafeYamlError",
    "load_schema",
    "read_plant",
    "write_plant",
]

DELIMITER = "---"
BODY_FIELD = "observation_log"

MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_NESTING_DEPTH = 20
_SCHEMA_KEYS = frozenset({"type", "default", "description"})


# --------------------------------------------------------------- errors ----


class PlantMarkdownError(Exception):
    """Base class for every error this module raises."""


class MalformedFrontmatterError(PlantMarkdownError):
    """Frontmatter delimiters are missing/unterminated, or YAML is invalid."""


class DuplicateKeyError(PlantMarkdownError):
    """The same key appears twice in one YAML mapping."""


class SchemaTypeError(PlantMarkdownError):
    """A value cannot be represented as its schema-declared type."""


class UnsafeYamlError(PlantMarkdownError):
    """Input exceeds a safety limit (size, nesting) or uses anchors/aliases."""


# ---------------------------------------------------------- YAML loader ----


class _Scalar:
    """A plain YAML scalar carrying BOTH its literal text and resolved value.

    PyYAML's implicit resolver is lossy for our purposes: ``07`` becomes the int
    ``7`` and ``1:30`` becomes the int ``90``, destroying the literal text before
    a schema ever gets to say "this field is a string". Capturing both lets
    :func:`_coerce` honour the declared type without re-guessing.
    """

    __slots__ = ("raw", "value")

    def __init__(self, raw: str, value: Any):
        self.raw = raw
        self.value = value


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and anchors/aliases.

    Anchors are refused outright: legitimate plant files never need them, and
    allowing them invites billion-laughs-style expansion from a hand-edited
    file that lands on ``main``.
    """


_BASE_CONSTRUCTORS = dict(yaml.SafeLoader.yaml_constructors)


def _plain_scalar(loader: _StrictLoader, node: yaml.ScalarNode) -> Any:
    """Construct plain (unquoted) scalars as :class:`_Scalar`.

    Quoted scalars are unambiguously strings already, so they pass straight
    through and never need the literal text preserved.
    """
    if not isinstance(node, yaml.ScalarNode):
        raise MalformedFrontmatterError(
            f"unsupported YAML tag: {node.tag}"
        )
    if node.style in ('"', "'"):
        return node.value
    resolved_tag = yaml.resolver.Resolver().resolve(
        yaml.ScalarNode, node.value, (True, False)
    )
    constructor = _BASE_CONSTRUCTORS.get(resolved_tag)
    if constructor is None:
        raise MalformedFrontmatterError(f"unsupported YAML tag: {resolved_tag}")
    resolved_node = yaml.ScalarNode(resolved_tag, node.value, style=node.style)
    return _Scalar(node.value, constructor(loader, resolved_node))


def _unwrap(value: Any) -> Any:
    """Recursively replace :class:`_Scalar` wrappers with their resolved values."""
    if isinstance(value, _Scalar):
        return value.value
    if isinstance(value, dict):
        return {_unwrap(k): _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    return value


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = _unwrap(loader.construct_object(key_node, deep=True))
        if key in mapping:
            raise DuplicateKeyError(f"duplicate key in frontmatter: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


def _no_anchors(self, node):  # pragma: no cover - exercised via compose
    raise UnsafeYamlError("YAML anchors/aliases are not allowed in plant files")


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)
_StrictLoader.add_constructor(None, _plain_scalar)
for _tag in (
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:str",
):
    _StrictLoader.add_constructor(_tag, _plain_scalar)
_StrictLoader.compose_node = (  # type: ignore[method-assign]
    lambda self, parent, index: (
        _no_anchors(self, None)
        if self.check_event(yaml.events.AliasEvent)
        else yaml.composer.Composer.compose_node(self, parent, index)
    )
)


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise UnsafeYamlError(
            f"structure nested deeper than {MAX_NESTING_DEPTH} levels"
        )
    if isinstance(value, dict):
        for key, val in value.items():
            _check_depth(key, depth + 1)
            _check_depth(val, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_depth(item, depth + 1)


def _parse_yaml(text: str) -> dict:
    try:
        loaded = yaml.load(text, Loader=_StrictLoader)
    except (DuplicateKeyError, UnsafeYamlError):
        raise
    except yaml.YAMLError as exc:
        raise MalformedFrontmatterError(f"invalid YAML frontmatter: {exc}") from exc

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise MalformedFrontmatterError(
            f"frontmatter must be a mapping, got {type(loaded).__name__}"
        )
    _check_depth(loaded)
    return loaded


def _parse_yaml_plain(text: str) -> dict:
    """Parse frontmatter with all scalar wrappers resolved (no schema in play)."""
    return _unwrap(_parse_yaml(text))


# --------------------------------------------------------------- splits ----


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(yaml_text, body)``; the body is returned verbatim."""
    if not text.startswith(DELIMITER + "\n"):
        raise MalformedFrontmatterError(
            "file must begin with a '---' frontmatter delimiter on line 1"
        )
    rest = text[len(DELIMITER) + 1 :]
    marker = "\n" + DELIMITER + "\n"
    end = rest.find(marker)
    if end == -1:
        if rest.endswith("\n" + DELIMITER):
            return rest[: -(len(DELIMITER) + 1)], ""
        raise MalformedFrontmatterError("unterminated frontmatter: no closing '---'")
    return rest[:end], rest[end + len(marker) :]


# ------------------------------------------------------------- coercion ----


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _coerce(field: str, value: Any, declared: str) -> Any:
    """Coerce ``value`` to the schema-declared type, or raise SchemaTypeError.

    When the file gave a plain scalar, the LITERAL text is used for string
    fields, so a hand-edited ``id: 07`` stays ``"07"`` rather than becoming the
    int ``7`` that YAML's implicit resolver would have produced.
    """
    raw = value.raw if isinstance(value, _Scalar) else None
    value = _unwrap(value)

    if declared in ("string", "body"):
        if raw is not None:
            # A plain scalar that resolves to null (bare `null`, `~`, or an
            # empty value) is a genuine null. Every other plain scalar keeps its
            # LITERAL text, so `07` / `true` / `1:30` survive as written. Quote
            # the value in the file to force the strings "null"/"~".
            return None if value is None else raw
        if isinstance(value, str):
            return value
        if value is None:
            return None
        if isinstance(value, (dict, list, tuple)):
            raise SchemaTypeError(
                f"{field}: expected a string, got {type(value).__name__}"
            )
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    if value is None:
        return None

    if declared == "integer":
        if _is_int(value):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                raise SchemaTypeError(
                    f"{field}: expected an integer, got {value!r}"
                ) from None
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise SchemaTypeError(f"{field}: expected an integer, got {value!r}")

    if declared == "list":
        if isinstance(value, list):
            return value
        raise SchemaTypeError(
            f"{field}: expected a list, got {type(value).__name__}"
        )

    return value


class _RawStr(str):
    """Marks a string that must be emitted quoted, preserving its literal text."""


def _quote_raw(dumper: yaml.Dumper, data: _RawStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="'")


class _PlantDumper(yaml.SafeDumper):
    pass


_PlantDumper.add_representer(_RawStr, _quote_raw)


def _needs_quoting(value: str) -> bool:
    """True if PyYAML would read this string back as a non-string scalar."""
    if value == "":
        return False
    resolved = yaml.resolver.Resolver().resolve(yaml.ScalarNode, value, (True, False))
    return resolved != "tag:yaml.org,2002:str"


def _prepare_for_dump(field: str, value: Any, declared: str | None) -> Any:
    if declared in ("string", "body") and isinstance(value, str) and _needs_quoting(
        value
    ):
        return _RawStr(value)
    if declared is None and isinstance(value, str) and _needs_quoting(value):
        return _RawStr(value)
    return value


# --------------------------------------------------------------- schema ----


def load_schema(path: str | os.PathLike) -> dict:
    """Load a template's frontmatter as a schema of ``{type, default, description}``.

    Each returned default is a fresh object, so callers mutating one plant's
    default list can never corrupt another's.
    """
    text = Path(path).read_text(encoding="utf-8")
    yaml_text, _ = _split_frontmatter(text)
    raw = _parse_yaml_plain(yaml_text)

    schema: dict[str, dict] = {}
    for field, spec in raw.items():
        if not isinstance(spec, dict) or not _SCHEMA_KEYS.issubset(spec):
            raise MalformedFrontmatterError(
                f"{field}: template fields must be {{type, default, description}} "
                "descriptor objects, not example values"
            )
        schema[field] = {
            "type": spec["type"],
            "default": spec["default"],
            "description": spec["description"],
        }
    return schema


def _default_for(spec: Mapping[str, Any]) -> Any:
    default = spec.get("default")
    if isinstance(default, (list, dict)):
        import copy

        return copy.deepcopy(default)
    return default


# ------------------------------------------------------------------ API ----


def read_plant(
    path: str | os.PathLike, schema: Mapping[str, Mapping] | None = None
) -> dict:
    """Parse a plant markdown file into a plain JSON-compatible dict.

    The markdown body is returned verbatim under ``observation_log``. When a
    ``schema`` is given, every field is coerced to its declared type and any
    field absent from the file is filled with the schema default.
    """
    file_path = Path(path)
    size = file_path.stat().st_size  # raises FileNotFoundError, as tests expect
    if size > MAX_FILE_BYTES:
        raise UnsafeYamlError(
            f"file is {size} bytes, exceeding the {MAX_FILE_BYTES}-byte limit"
        )

    text = file_path.read_text(encoding="utf-8")
    yaml_text, body = _split_frontmatter(text)
    data = _parse_yaml(yaml_text)

    if schema:
        result: dict[str, Any] = {}
        for field, spec in schema.items():
            if field == BODY_FIELD:
                continue
            if field in data:
                result[field] = _coerce(field, data[field], spec["type"])
            else:
                result[field] = _default_for(spec)
        for field, value in data.items():
            if field not in result and field != BODY_FIELD:
                result[field] = _unwrap(value)
        if BODY_FIELD in schema:
            result[BODY_FIELD] = body
        return result

    data = _unwrap(data)
    data[BODY_FIELD] = body
    return data


def write_plant(
    path: str | os.PathLike,
    data: Mapping[str, Any],
    schema: Mapping[str, Mapping] | None = None,
) -> None:
    """Write a plant dict to ``path`` atomically.

    ``observation_log`` becomes the markdown body; everything else becomes
    frontmatter, ordered by the schema so diffs stay minimal. The caller's dict
    is never mutated.
    """
    if not isinstance(data, Mapping):
        raise TypeError(f"data must be a mapping, got {type(data).__name__}")
    for key in data:
        if not isinstance(key, str):
            raise TypeError(f"field names must be strings, got {key!r}")

    body = data.get(BODY_FIELD, "")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise TypeError(f"{BODY_FIELD} must be a string, got {type(body).__name__}")

    ordered: MutableMapping[str, Any] = {}
    if schema:
        for field in schema:
            if field != BODY_FIELD and field in data:
                ordered[field] = _prepare_for_dump(
                    field, data[field], schema[field]["type"]
                )
    for field, value in data.items():
        if field != BODY_FIELD and field not in ordered:
            declared = schema[field]["type"] if schema and field in schema else None
            ordered[field] = _prepare_for_dump(field, value, declared)

    yaml_text = yaml.dump(
        dict(ordered),
        Dumper=_PlantDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10**9,
    )
    if ordered and not yaml_text.endswith("\n"):
        yaml_text += "\n"
    if not ordered:
        yaml_text = ""

    content = f"{DELIMITER}\n{yaml_text}{DELIMITER}\n{body}"

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
