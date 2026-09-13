"""Scaffold brand-new plant/project markdown files from the current templates.

Task 1.4. Unlike :func:`migration.apply_new_fields` (which patches an
EXISTING file, preserving whatever is already there), these functions create
a file that does not yet exist, materialising every schema field's declared
default as a real value (never the ``{type, default, description}``
descriptor object itself), then layering the caller's explicit overrides on
top.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from . import plant_markdown
from . import project_markdown

__all__ = ["scaffold_new_plant", "scaffold_new_project"]


def _materialize_defaults(schema: Mapping[str, Mapping[str, Any]]) -> dict:
    """Build a plain values dict from a schema, one fresh default per field.

    ``load_schema`` already deep-copies mutable defaults on each call, but a
    single schema object here backs every field in one file, so a defensive
    copy per field keeps two fields that happen to share a template-declared
    empty list/dict from ever aliasing each other.
    """
    values: dict[str, Any] = {}
    for field, spec in schema.items():
        default = spec.get("default")
        values[field] = copy.deepcopy(default) if isinstance(default, (list, dict)) else default
    return values


def scaffold_new_plant(
    template_path: str | Path, target_path: str | Path, overrides: Mapping[str, Any]
) -> dict:
    """Create a brand-new plant markdown file at ``target_path``.

    Every schema field is materialised to its template-declared default
    value first; ``overrides`` (typically at least ``id``) is then layered
    on top. Raises :class:`FileExistsError` if ``target_path`` already
    exists — scaffolding is only for genuinely new files, never for
    resetting an existing plant's data.
    """
    target = Path(target_path)
    if target.exists():
        raise FileExistsError(f"plant file already exists: {target}")

    schema = plant_markdown.load_schema(template_path)
    data = _materialize_defaults(schema)
    data.update(overrides)

    plant_markdown.write_plant(target, data, schema=schema)
    return data


def scaffold_new_project(
    template_path: str | Path, target_path: str | Path, overrides: Mapping[str, Any]
) -> dict:
    """Create a brand-new project markdown file at ``target_path``.

    Same contract as :func:`scaffold_new_plant`, for ``project.md``.
    """
    target = Path(target_path)
    if target.exists():
        raise FileExistsError(f"project file already exists: {target}")

    schema = project_markdown.load_schema(template_path)
    data = _materialize_defaults(schema)
    data.update(overrides)

    project_markdown.write_project(target, data, schema=schema)
    return data
