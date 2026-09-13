"""Round-2 code-quality review regression tests (Phase 2 / Task 2.5).

Each test here pins one finding from the FINAL Phase 2 code-quality review of
the ``registry.json`` routing mechanism. All three were empirically reproduced
by the reviewer against the shipped code; each test below was written BEFORE
its fix and watched failing.

1. Prefix uniqueness was case-SENSITIVE, so ``sp`` and ``SP`` in two different
   projects both validated and a message routed to BOTH crosses. Not
   hypothetical: ``spaced-paste`` really does declare a lowercase ``sp``.
2. ``_compile_prefixes`` compiled multi-prefix patterns with NO flags while
   ``extract_plant_ids_single`` passed ``re.IGNORECASE`` -- so matching was
   case-sensitive for multi-prefix projects only. Invisible today solely
   because Kibungan happens to embed ``(?i)`` inline in both its patterns.
3. ``breeding_dir`` was checked for presence but not containment, so
   ``~/.hermes/../../../tmp/pwned`` or ``/etc`` loaded clean and would let a
   later write land outside the breeding tree.

SANDBOX-ONLY, like the rest of this suite: real project dirs are read-only
inputs, every write lands in a pytest ``tmp_path``, and no Discord, Drive,
network or git-push side effect is performed.
"""

import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))

import breeding_core as core  # noqa: E402
from test_registry_routing import (  # noqa: E402,F401
    _project_entry,
    _write_registry,
    meta_repo,
)


# ------------------------------------ #1 case-insensitive prefix uniqueness

def test_prefix_uniqueness_is_case_insensitive(meta_repo, tmp_path):
    """``sp`` and ``SP`` are the SAME prefix for routing purposes.

    Matching is case-insensitive on both the single- and multi-prefix paths,
    so a registry declaring both spellings would route one message to two
    different crosses. The README promises a duplicate is rejected at load
    time; that promise has to hold under case folding too.
    """
    _write_registry(meta_repo, [
        _project_entry("a", tmp_path / "a",
                       [{"prefix": "sp", "pattern": r"\bsp[\s\-]?(\d{1,2})\b"}]),
        _project_entry("b", tmp_path / "b",
                       [{"prefix": "SP", "pattern": r"\bSP[\s\-]?(\d{1,2})\b"}]),
    ])

    with pytest.raises(ValueError) as exc:
        core.load_registry()

    message = str(exc.value)
    # BOTH original spellings must appear -- a human debugging this needs to
    # see exactly which two entries collided, not just the winning one.
    assert "'sp'" in message
    assert "'SP'" in message
    assert "'a'" in message and "'b'" in message


def test_case_variant_prefixes_would_have_routed_to_two_projects(tmp_path):
    """The bug this guards, demonstrated without the load-time guard.

    Fed straight to ``route_message`` as an in-memory registry (bypassing
    ``load_registry``'s validation), a 'sp'/'SP' pair matches the same text
    twice. That is the ambiguity the uniqueness check exists to prevent.
    """
    registry = {"schema_version": 1, "projects": [
        _project_entry("a", tmp_path / "a",
                       [{"prefix": "sp", "pattern": r"\bsp[\s\-]?(\d{1,2})\b"}]),
        _project_entry("b", tmp_path / "b",
                       [{"prefix": "SP", "pattern": r"\bSP[\s\-]?(\d{1,2})\b"}]),
    ]}
    routed = core.route_message("SP05 fire", pull=False, registry=registry)
    assert [r["slug"] for r in routed] == ["a", "b"], (
        "precondition for the uniqueness guard: case variants really do "
        "double-route"
    )


# ------------------------------ #2 IGNORECASE symmetry, single vs multi

def test_multi_prefix_patterns_match_case_insensitively(tmp_path):
    """Multi-prefix routing must be as case-insensitive as single-prefix.

    ``extract_plant_ids_single`` passes ``re.IGNORECASE``; ``_compile_prefixes``
    passed no flags. A two-prefix project whose patterns lack an inline
    ``(?i)`` therefore silently failed to match lowercase input while a
    one-prefix project matched it fine.
    """
    registry = {"schema_version": 1, "projects": [
        _project_entry("multi", tmp_path / "multi", [
            {"prefix": "XA", "pattern": r"\bXA(\d{1,2})\b"},
            {"prefix": "XB", "pattern": r"\bXB(\d{1,2})\b"},
        ]),
    ]}
    routed = core.route_message("xa05 looking fire", pull=False, registry=registry)
    assert [r["slug"] for r in routed] == ["multi"]
    assert routed[0]["plant_ids"] == ["XA05"]


def test_single_and_multi_prefix_paths_agree_on_case(tmp_path):
    """The asymmetry itself, asserted directly: same input, same answer."""
    single = {"schema_version": 1, "projects": [
        _project_entry("one", tmp_path / "one",
                       [{"prefix": "YA", "pattern": r"\bYA(\d{1,2})\b"}]),
    ]}
    multi = {"schema_version": 1, "projects": [
        _project_entry("two", tmp_path / "two", [
            {"prefix": "YA", "pattern": r"\bYA(\d{1,2})\b"},
            {"prefix": "YB", "pattern": r"\bYB(\d{1,2})\b"},
        ]),
    ]}
    got_single = core.route_message("ya05", pull=False, registry=single)
    got_multi = core.route_message("ya05", pull=False, registry=multi)

    assert [r["plant_ids"] for r in got_single] == [["YA05"]]
    assert [r["plant_ids"] for r in got_multi] == [["YA05"]]


def test_compiled_multi_prefix_patterns_carry_ignorecase(tmp_path):
    """The flag is on the compiled object, not just an accident of the data."""
    entry = _project_entry("multi", tmp_path / "multi", [
        {"prefix": "XA", "pattern": r"\bXA(\d{1,2})\b"},
        {"prefix": "XB", "pattern": r"\bXB(\d{1,2})\b"},
    ])
    for _prefix, compiled in core._compile_prefixes(entry):
        assert compiled.flags & core.re.IGNORECASE


def test_kibungan_inline_ignorecase_still_works_under_the_flag():
    """Kibungan's real patterns embed ``(?i)``; that must stay harmless.

    Redundant under ``re.IGNORECASE``, not conflicting -- this is the real
    production entry, so it is checked against the real registry.
    """
    entry = core.registry_entry("kibungan-pheno-hunt")
    compiled = dict(core._compile_prefixes(entry))
    assert set(compiled) == {"PK", "PL"}
    assert compiled["PK"].search("pk 7")
    assert compiled["PL"].search("PL-03")

    routed = core.route_message("PK7 and pl3 both fuel", pull=False)
    assert [r["slug"] for r in routed] == ["kibungan-pheno-hunt"]
    assert routed[0]["plant_ids"] == ["PK07", "PL03"]


# --------------------------------------- #3 breeding_dir path containment

def _entry_with_dir(breeding_dir):
    entry = _project_entry(
        "escapee", "placeholder",
        [{"prefix": "EE", "pattern": r"\bEE(\d{1,2})\b"}],
    )
    entry["breeding_dir"] = str(breeding_dir)
    return entry


def test_breeding_dir_traversal_escaping_the_root_is_rejected(
    meta_repo, tmp_path
):
    """``..`` segments must be collapsed and then checked, not trusted.

    ``registry.json`` is trusted local data, but a typo'd or malicious entry
    should not be able to aim ``save_tracker`` / ``markdown_backend.save_plant``
    at an arbitrary directory. The path is resolved first so ``..`` cannot
    smuggle an escape past a naive prefix check.
    """
    escaped = f"{tmp_path}/a/../../../tmp/pwned"
    _write_registry(meta_repo, [_entry_with_dir(escaped)])

    with pytest.raises(ValueError) as exc:
        core.load_registry()
    message = str(exc.value)
    assert "escapee" in message
    assert "breeding_dir" in message


def test_absolute_breeding_dir_outside_the_root_is_rejected(meta_repo):
    _write_registry(meta_repo, [_entry_with_dir("/etc")])

    with pytest.raises(ValueError) as exc:
        core.load_registry()
    message = str(exc.value)
    assert "escapee" in message
    assert "/etc" in message


def test_breeding_dir_equal_to_the_root_is_rejected(meta_repo, tmp_path):
    """The root itself is not a project directory."""
    _write_registry(meta_repo, [_entry_with_dir(tmp_path)])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "escapee" in str(exc.value)


def test_normal_project_shaped_breeding_dir_is_accepted(meta_repo, tmp_path):
    """The containment check must not break an ordinary entry."""
    _write_registry(meta_repo, [_project_entry(
        "good-project", tmp_path / "good-project",
        [{"prefix": "GP", "pattern": r"\bGP(\d{1,2})\b"}],
    )])
    registry = core.load_registry()
    assert [p["slug"] for p in registry["projects"]] == ["good-project"]


def test_real_registry_entries_all_live_under_the_default_root():
    """All six real projects sit under ``~/.hermes/breeding/`` -- the root the
    containment check is configured with. Loading the real file is itself the
    assertion, but the containment is spelled out here too."""
    root = (Path.home() / ".hermes" / "breeding").resolve()
    for entry in core.load_registry()["projects"]:
        resolved = Path(entry["breeding_dir"]).expanduser().resolve()
        assert resolved.is_relative_to(root) and resolved != root, entry["slug"]


def test_breeding_root_env_override_is_honoured(tmp_path, monkeypatch):
    """The root is configurable, same precedent as ``BREEDING_META_DIR``."""
    monkeypatch.setenv("BREEDING_ROOT_DIR", str(tmp_path / "elsewhere"))
    assert core._breeding_root() == (tmp_path / "elsewhere")
    monkeypatch.delenv("BREEDING_ROOT_DIR")
    assert core._breeding_root() == Path.home() / ".hermes" / "breeding"


# ------------------------------------------- previously untested branches

def test_non_dict_top_level_is_rejected(meta_repo):
    (meta_repo / "registry.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "JSON object" in str(exc.value)


def test_non_list_projects_is_rejected(meta_repo):
    (meta_repo / "registry.json").write_text(
        '{"schema_version": 1, "projects": {}}', encoding="utf-8"
    )
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "'projects' must be a list" in str(exc.value)


def test_unsupported_schema_version_is_rejected(meta_repo):
    (meta_repo / "registry.json").write_text(
        '{"schema_version": 99, "projects": []}', encoding="utf-8"
    )
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "schema_version" in str(exc.value)


def test_project_without_slug_is_rejected(meta_repo, tmp_path):
    entry = _project_entry("x", tmp_path / "x",
                           [{"prefix": "XX", "pattern": r"\bXX(\d{1,2})\b"}])
    del entry["slug"]
    _write_registry(meta_repo, [entry])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "no 'slug'" in str(exc.value)


def test_duplicate_slug_is_rejected(meta_repo, tmp_path):
    _write_registry(meta_repo, [
        _project_entry("dupe", tmp_path / "dupe",
                       [{"prefix": "D1", "pattern": r"\bD1(\d{1,2})\b"}]),
        _project_entry("dupe", tmp_path / "dupe2",
                       [{"prefix": "D2", "pattern": r"\bD2(\d{1,2})\b"}]),
    ])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "duplicate project slug" in str(exc.value)


def test_prefix_spec_missing_a_key_is_rejected(meta_repo, tmp_path):
    _write_registry(meta_repo, [_project_entry(
        "no-pattern", tmp_path / "no-pattern", [{"prefix": "NP"}]
    )])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "no-pattern" in str(exc.value)
    assert "pattern" in str(exc.value)


def test_invalid_regex_is_rejected(meta_repo, tmp_path):
    _write_registry(meta_repo, [_project_entry(
        "bad-regex", tmp_path / "bad-regex",
        [{"prefix": "BR", "pattern": r"\bBR(\d{1,2}"}]
    )])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "bad-regex" in str(exc.value)
    assert "invalid pattern" in str(exc.value)


def test_zero_prefix_project_is_rejected(meta_repo, tmp_path):
    _write_registry(meta_repo, [_project_entry(
        "no-prefixes", tmp_path / "no-prefixes", []
    )])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "no-prefixes" in str(exc.value)
    assert "plant_id_prefixes" in str(exc.value)
