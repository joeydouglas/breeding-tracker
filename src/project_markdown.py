"""Read and write project markdown files (frontmatter + freeform body).

The markdown file is the sole source of truth for a project. Layout:

    ---
    cross_name: Lantz
    auto_create: true
    ---
    ## Notes
    Freeform project narrative.

Frontmatter holds scalar/array/object fields; the markdown BODY holds
freeform project notes verbatim under the fixed ``body`` key, so hand-written
formatting survives byte-for-byte.

Design rules this module enforces (mirrors ``plant_markdown.py``, Task 1.1):

* **Declared types win over PyYAML's guessing.** A hand-edited
  ``cross_name: 07`` stays the string ``"07"``; ``auto_create: yes`` becomes
  the declared boolean. Coercion is driven by the template schema, never by
  YAML's implicit resolver.
* **Untrusted input.** Files arrive via ``git pull`` from repos humans
  hand-edit, so parsing rejects anchors/aliases, custom tags, duplicate keys,
  oversized input, and excessive nesting rather than trusting them.
* **Round-trip fidelity.** ``read_project(write_project(x)) == x``, and
  rewriting an unmodified file is byte-stable.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import yaml

__all__ = [
    "ProjectMarkdownError",
    "MalformedFrontmatterError",
    "DuplicateKeyError",
    "SchemaTypeError",
    "UnsafeYamlError",
    "load_schema",
    "read_project",
    "write_project",
]

DELIMITER = "---"
BODY_FIELD = "body"

MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_NESTING_DEPTH = 20
_SCHEMA_KEYS = frozenset({"type", "default", "description"})
_KNOWN_SCHEMA_TYPES = frozenset(
    {"string", "integer", "boolean", "list", "array", "object", "body"}
)


# --------------------------------------------------------------- errors ----


class ProjectMarkdownError(Exception):
    """Base class for every error this module raises."""


class MalformedFrontmatterError(ProjectMarkdownError):
    """Frontmatter delimiters are missing/unterminated, or YAML is invalid."""


class DuplicateKeyError(ProjectMarkdownError):
    """The same key appears twice in one YAML mapping."""


class SchemaTypeError(ProjectMarkdownError):
    """A value cannot be represented as its schema-declared type."""


class UnsafeYamlError(ProjectMarkdownError):
    """Input exceeds a safety limit (size, nesting) or uses anchors/aliases."""


# ---------------------------------------------------------- YAML loader ----


class _Scalar:
    """A plain YAML scalar carrying BOTH its literal text and resolved value.

    PyYAML's implicit resolver is lossy for our purposes: ``07`` becomes the
    int ``7`` and ``1:30`` becomes the int ``90``, destroying the literal text
    before a schema ever gets to say "this field is a string". Capturing both
    lets :func:`_coerce` honour the declared type without re-guessing.
    """

    __slots__ = ("raw", "value")

    def __init__(self, raw: str, value: Any):
        self.raw = raw
        self.value = value


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and anchors/aliases.

    Anchors are refused outright: legitimate project files never need them,
    and allowing them invites billion-laughs-style expansion from a
    hand-edited file that lands on ``main``.
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
    if node.style in ('"', "'", "|", ">"):
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
        try:
            duplicate = key in mapping
        except TypeError as exc:
            # A YAML complex/collection key (e.g. `? [a, b]`) is unhashable.
            # Nothing in this schema ever needs non-scalar keys, so reject it
            # as malformed input rather than let a bare TypeError escape the
            # module's documented "everything raises ProjectMarkdownError"
            # contract to callers (e.g. the webhook's git-pull handler).
            raise MalformedFrontmatterError(
                f"unsupported (unhashable) YAML key: {key!r}"
            ) from exc
        if duplicate:
            raise DuplicateKeyError(f"duplicate key in frontmatter: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


def _no_anchors(loader: _StrictLoader) -> None:
    raise UnsafeYamlError("YAML anchors/aliases are not allowed in project files")


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


def _reject_unknown_tag(loader: _StrictLoader, node: yaml.Node) -> Any:
    """Fallback for any tag not explicitly recognised.

    Plain (untagged) scalars never reach this: PyYAML's implicit resolver
    always assigns them one of the standard tags registered below before
    construction runs. Only an EXPLICITLY tagged node (custom local tags like
    ``!whatever``, or dangerous ones like ``!!python/name:...``) lands here,
    so unconditional rejection is correct and safe.
    """
    raise MalformedFrontmatterError(f"unsupported YAML tag: {node.tag}")


def _reject_collection_tag(loader: _StrictLoader, node: yaml.Node) -> Any:
    """Reject YAML's non-scalar/mapping/sequence collection types.

    ``!!set``, ``!!omap``, ``!!pairs`` and ``!!binary`` are all "safe" as far
    as PyYAML's SafeLoader is concerned (they never construct arbitrary
    Python objects), but our schema only ever needs plain scalars, lists and
    mappings. Letting these through would silently hand back non-JSON-
    serialisable values (``set``, ``bytes``) that ``write_project`` can't
    round-trip either.
    """
    raise MalformedFrontmatterError(f"unsupported YAML tag: {node.tag}")


_StrictLoader.add_constructor(None, _reject_unknown_tag)
for _tag in (
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:str",
):
    _StrictLoader.add_constructor(_tag, _plain_scalar)
for _tag in (
    "tag:yaml.org,2002:set",
    "tag:yaml.org,2002:omap",
    "tag:yaml.org,2002:pairs",
    "tag:yaml.org,2002:binary",
):
    _StrictLoader.add_constructor(_tag, _reject_collection_tag)


def _compose_node_reject_anchors(
    self: _StrictLoader, parent: yaml.Node, index: Any
) -> yaml.Node:
    """Reject any node carrying an anchor, whether or not it's ever aliased.

    The previous implementation only fired on an *alias reference*
    (``AliasEvent``), so a bare, never-referenced anchor definition like
    ``cross_name: &a big`` parsed fine — contradicting the module's own
    documented "anchors are refused outright" contract. Every composable
    event (scalar, sequence-start, mapping-start, alias) carries an
    ``.anchor`` attribute; checking it before composing catches definitions
    and references alike.
    """
    event = self.peek_event()
    if getattr(event, "anchor", None) is not None:
        _no_anchors(self)
    return yaml.composer.Composer.compose_node(self, parent, index)


_StrictLoader.compose_node = _compose_node_reject_anchors  # type: ignore[method-assign]


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
    except RecursionError as exc:
        # PyYAML's composer can hit Python's own recursion limit while
        # building nodes for a deeply-nested flow collection, raising a bare
        # RecursionError BEFORE our post-parse _check_depth ever runs. That
        # would otherwise escape every ProjectMarkdownError-catching caller
        # (e.g. the webhook's git-pull handler) as an unrelated exception.
        raise UnsafeYamlError(
            f"structure nested deeper than {MAX_NESTING_DEPTH} levels "
            "(hit Python's recursion limit while parsing)"
        ) from exc
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
    """Return ``(yaml_text, body)``; the body is returned verbatim.

    The delimiter lines themselves may end in ``\\n`` or ``\\r\\n`` (a file
    hand-edited on Windows, or checked out with ``core.autocrlf=true``, uses
    CRLF throughout, including on the ``---`` lines) -- only the BODY's own
    line endings need to be preserved byte-for-byte, so the delimiter search
    tolerates either.
    """
    if text.startswith(DELIMITER + "\r\n"):
        rest = text[len(DELIMITER) + 2 :]
    elif text.startswith(DELIMITER + "\n"):
        rest = text[len(DELIMITER) + 1 :]
    else:
        raise MalformedFrontmatterError(
            "file must begin with a '---' frontmatter delimiter on line 1"
        )
    # Empty frontmatter: write_project emits "---\n---\nbody" when there are
    # zero fields, so the closing delimiter sits at position 0 of `rest` with
    # no preceding blank line -- the general "\n---\n"/"\r\n---\r\n" marker
    # below requires a newline BEFORE the closing delimiter, which doesn't
    # exist here. Handle it before falling into that search, so the writer
    # never produces a file its own reader rejects.
    for lead in (DELIMITER + "\r\n", DELIMITER + "\n"):
        if rest.startswith(lead):
            return "", rest[len(lead) :]
    if rest == DELIMITER:
        return "", ""
    for marker in ("\r\n" + DELIMITER + "\r\n", "\n" + DELIMITER + "\n"):
        end = rest.find(marker)
        if end != -1:
            return rest[:end], rest[end + len(marker) :]
    for tail in ("\r\n" + DELIMITER, "\n" + DELIMITER):
        if rest.endswith(tail):
            return rest[: -len(tail)], ""
    raise MalformedFrontmatterError("unterminated frontmatter: no closing '---'")


def _get_umask() -> int:
    """Read the process umask ONCE at import time, without permanently
    changing it.

    ``os.umask()`` is the only stdlib way to read the current umask, and it
    always has the side effect of setting a new one -- calling this on every
    ``write_project`` invocation would be racy. Caching the value once at
    import time avoids the runtime race entirely.
    """
    current = os.umask(0)
    os.umask(current)
    return current


_CACHED_UMASK = _get_umask()


# ------------------------------------------------------------- coercion ----


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _coerce(field: str, value: Any, declared: str) -> Any:
    """Coerce ``value`` to the schema-declared type, or raise SchemaTypeError.

    When the file gave a plain scalar, the LITERAL text is used for string
    fields, so a hand-edited ``cross_name: 07`` stays ``"07"`` rather than
    becoming the int ``7`` that YAML's implicit resolver would have produced.
    """
    raw = value.raw if isinstance(value, _Scalar) else None
    value = _unwrap(value)

    if declared in ("string", "body"):
        if raw is not None:
            # A plain scalar that resolves to null (bare `null`, `~`, or an
            # empty value) is a genuine null. Every other plain scalar keeps
            # its LITERAL text, so `07` / `true` / `1:30` survive as written.
            # Quote the value in the file to force the strings "null"/"~".
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

    if declared == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "yes", "on", "1"):
                return True
            if lowered in ("false", "no", "off", "0"):
                return False
            raise SchemaTypeError(
                f"{field}: expected a boolean, got {value!r}"
            )
        raise SchemaTypeError(f"{field}: expected a boolean, got {value!r}")

    if declared == "array":
        if isinstance(value, list):
            return value
        raise SchemaTypeError(
            f"{field}: expected an array, got {type(value).__name__}"
        )

    if declared == "object":
        if isinstance(value, dict):
            return value
        raise SchemaTypeError(
            f"{field}: expected an object, got {type(value).__name__}"
        )

    return value


class _RawStr(str):
    """Marks a string that must be emitted quoted, preserving its literal text."""


def _quote_raw(dumper: yaml.Dumper, data: _RawStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="'")


class _ProjectDumper(yaml.SafeDumper):
    pass


_ProjectDumper.add_representer(_RawStr, _quote_raw)


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

    Each returned default is a fresh object, so callers mutating one
    project's default list/dict can never corrupt another's.
    """
    text = Path(path).read_text(encoding="utf-8", newline="")
    yaml_text, _ = _split_frontmatter(text)
    raw = _parse_yaml_plain(yaml_text)

    schema: dict[str, dict] = {}
    for field, spec in raw.items():
        if not isinstance(spec, dict) or not _SCHEMA_KEYS.issubset(spec):
            raise MalformedFrontmatterError(
                f"{field}: template fields must be {{type, default, description}} "
                "descriptor objects, not example values"
            )
        if spec["type"] not in _KNOWN_SCHEMA_TYPES:
            raise MalformedFrontmatterError(
                f"{field}: unknown schema type {spec['type']!r}, expected one "
                f"of {sorted(_KNOWN_SCHEMA_TYPES)}"
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


def read_project(
    path: str | os.PathLike, schema: Mapping[str, Mapping] | None = None
) -> dict:
    """Parse a project markdown file into a plain JSON-compatible dict.

    The markdown body is returned verbatim under ``body``. When a ``schema``
    is given, every field is coerced to its declared type and any field
    absent from the file is filled with the schema default.
    """
    file_path = Path(path)
    size = file_path.stat().st_size  # raises FileNotFoundError, as tests expect
    if size > MAX_FILE_BYTES:
        raise UnsafeYamlError(
            f"file is {size} bytes, exceeding the {MAX_FILE_BYTES}-byte limit"
        )

    # newline="" disables universal-newline translation: a hand-edited or
    # Windows-checked-out (autocrlf=true) file's CRLF line endings in the
    # BODY must survive read_project(write_project(x)) == x byte-for-byte,
    # not get silently rewritten to LF.
    #
    # Read with an explicit cap rather than trusting `stat().st_size`: a
    # git-committed symlink (e.g. to /dev/zero) reports a tiny/zero apparent
    # size from stat() while the actual read can be unbounded, defeating the
    # size check above entirely. Files arrive via `git pull` from repos
    # humans hand-edit, and git tracks symlinks, so this is in-scope for the
    # "untrusted input" threat model this module documents.
    with open(file_path, "r", encoding="utf-8", newline="") as handle:
        text = handle.read(MAX_FILE_BYTES + 1)
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise UnsafeYamlError(
            f"file exceeds the {MAX_FILE_BYTES}-byte limit (apparent size "
            "from stat() may have been misleading, e.g. a symlink)"
        )
    yaml_text, body = _split_frontmatter(text)
    data = _parse_yaml(yaml_text)
    if BODY_FIELD in data:
        # `body` belongs in the markdown BODY, never in frontmatter --
        # silently discarding a hand-entered frontmatter value here would
        # lose real data. Reject instead so a hand-edit mistake is caught
        # immediately rather than a project's notes vanishing without a
        # trace.
        raise MalformedFrontmatterError(
            f"{BODY_FIELD!r} must not appear in frontmatter -- it belongs "
            "in the markdown body below the closing '---'"
        )

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
        result[BODY_FIELD] = body
        return result

    data = _unwrap(data)
    data[BODY_FIELD] = body
    return data


def write_project(
    path: str | os.PathLike,
    data: Mapping[str, Any],
    schema: Mapping[str, Mapping] | None = None,
) -> None:
    """Write a project dict to ``path`` atomically.

    ``body`` becomes the markdown body; everything else becomes frontmatter,
    ordered by the schema so diffs stay minimal. The caller's dict is never
    mutated.
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
        Dumper=_ProjectDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10**9,
    )
    if ordered and not yaml_text.endswith("\n"):
        yaml_text += "\n"
    if not ordered:
        yaml_text = ""

    content_newline = (
        "\r\n"
        if "\r\n" in body and "\n" not in body.replace("\r\n", "")
        else "\n"
    )
    # The write-side counterpart to read_project's newline="" fix: if the
    # BODY is CRLF-terminated (a Windows-authored or autocrlf=true-checked-
    # out file), match the frontmatter delimiters/YAML block to the same
    # line ending, rather than grafting hardcoded LF delimiters onto a CRLF
    # body -- which would otherwise produce a mixed-newline file and a
    # spurious whole-header diff on every single touch of such a file.
    if content_newline == "\r\n":
        yaml_text_out = yaml_text.replace("\n", "\r\n") if yaml_text else ""
        content = f"{DELIMITER}\r\n{yaml_text_out}{DELIMITER}\r\n{body}"
    else:
        content = f"{DELIMITER}\n{yaml_text}{DELIMITER}\n{body}"

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # tempfile.mkstemp always creates its file mode 0600, and os.replace
    # preserves whatever mode the source (temp) file had -- so rewriting an
    # existing, normally-permissioned file (e.g. 0644, the usual mode for a
    # git-tracked file) would silently downgrade it to 0600 on every write.
    # Match the target's existing mode when rewriting, or fall back to a
    # permissive default (respecting umask) for a brand-new file.
    if target.exists():
        desired_mode = target.stat().st_mode & 0o777
    else:
        desired_mode = 0o666 & ~_CACHED_UMASK
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        os.chmod(tmp_name, desired_mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
