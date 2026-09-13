"""Task 2.5: project routing as DATA (``registry.json``) -- built and proven.

Project routing is encoded in CODE today, in three places, none of which is
``breeding_core.py``:

* ``_CROSS_DIRS: dict[str, Path]`` in the gateway plugin, at
  ``_shared/breeding-ingest/integrations/hermes-breeding-ingest/__init__.py``
  (~lines 55-63) -- the REAL production prefix -> project-directory router,
  whose own comment states that adding a new cross requires a line there.
* ``PLANT_ID_REGISTRY`` in ``_shared/breeding-ingest/breeding_tracker/
  discord_ingest.py`` -- the prefix -> regex table.
* each of the six ``monitor_breeding_notes.py`` wrappers, which hands
  ``breeding_core`` a fully hardcoded ``CONFIG`` dict.

The finalized plan called this task "replace the hardcoded ``_CROSS_DIRS``
dict". That dict genuinely exists and is genuinely the coupling worth
removing -- the plan simply MISFILED it, placing it in ``breeding_core.py``
rather than the gateway plugin. The premise was right; the address was wrong.
See DECISIONS.md.

Task 2.5 builds the routing table as *data*: a ``registry.json`` in a separate
``breeding-meta`` git repo that ``breeding_core.py`` reads locally and
``git pull``s before each ingestion run.

SCOPE -- what these tests do and do NOT prove. They prove the mechanism works:
the acceptance criterion below is literal and passes. They do NOT prove
adoption. Nothing in production reads ``registry.json`` yet; ``_CROSS_DIRS``,
``PLANT_ID_REGISTRY`` and the six wrappers are all untouched and still
authoritative. Migrating them onto the registry is separate future work.

The acceptance criterion from the plan is proven by
``test_acceptance_new_project_routes_with_zero_code_change`` below:

    adding a new project to registry.json and pushing, then running
    ingestion against a message using that project's prefix, correctly
    routes without any code change to breeding_core.py itself

SANDBOX-ONLY. The only git remotes used here are throwaway *local bare*
repos under ``tmp_path``. Nothing touches GitHub, a real credential, a real
project directory, or the real ``breeding-meta`` checkout's remote.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from breeding_tracker import breeding_core as core
from test_wrapper_compatibility import PROJECTS, WRAPPER_SHA256, _load_wrapper

BREEDING_ROOT = Path.home() / ".hermes" / "breeding"
MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_CORE_PY = MONITOR_CORE_DIR / "breeding_tracker" / "breeding_core.py"

# Ground truth read out of the six real wrappers at the start of Task 2.5.
# registry.json must agree with these or it is not describing reality.
EXPECTED_PREFIXES = {
    "mule-fuel-x-nana-glue": ["MG"],
    "honey-badger-haze-pheno-hunt": ["HBH"],
    "kibungan-pheno-hunt": ["PK", "PL"],
    "spaced-paste": ["SP"],
    "paloma-coma": ["PC"],
    "lantz": ["LTZ"],
    "marshmallow-og-pheno-hunt": ["MOG"],
    "pink-perfume-pheno-hunt": ["PP"],
    "ms-universe-pheno-hunt": ["MSU"],
}


def _git(args, cwd):
    """A git command in a sandbox that MUST succeed (unlike core's ``_git``)."""
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


def _write_registry(repo, projects):
    (repo / "registry.json").write_text(
        json.dumps({"schema_version": 1, "projects": projects}, indent=2) + "\n",
        encoding="utf-8",
    )


def _project_entry(slug, breeding_dir, prefixes, **kw):
    entry = {
        "slug": slug,
        "cross_name": kw.get("cross_name", slug),
        "breeding_dir": str(breeding_dir),
        "github_repo": kw.get("github_repo", f"joeydouglas/{slug}"),
        "auto_create": kw.get("auto_create", False),
        "plant_id_prefixes": prefixes,
    }
    if "backend" in kw:
        entry["backend"] = kw["backend"]
    return entry


@pytest.fixture
def meta_repo(tmp_path, monkeypatch):
    """A sandbox breeding-meta checkout wired to a throwaway local bare remote."""
    bare = tmp_path / "breeding-meta-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    # Point the bare repo's HEAD at main so a later `git clone` of it checks
    # out a working tree instead of landing on a nonexistent default branch.
    subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"],
                   cwd=str(bare), check=True)

    repo = tmp_path / "breeding-meta"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _write_registry(repo, [])
    _git(["add", "registry.json"], repo)
    _git(["commit", "-qm", "init"], repo)
    _git(["remote", "add", "origin", str(bare)], repo)
    _git(["push", "-q", "-u", "origin", "main"], repo)

    monkeypatch.setenv("BREEDING_META_DIR", str(repo))
    # Sandbox projects live under tmp_path, not ``~/.hermes/breeding``, so the
    # breeding_dir containment root (round-2 review fix #3) is pointed there
    # too. Same override precedent as BREEDING_META_DIR itself.
    monkeypatch.setenv("BREEDING_ROOT_DIR", str(tmp_path))
    return repo


# ---------------------------------------------------------------- real data

def test_real_registry_exists_and_declares_all_six_projects():
    registry = core.load_registry()
    slugs = [p["slug"] for p in registry["projects"]]
    assert sorted(slugs) == sorted(EXPECTED_PREFIXES), (
        "registry.json must list exactly the six real projects"
    )
    assert registry["schema_version"] == 1


def test_real_registry_prefixes_match_the_real_wrappers():
    registry = core.load_registry()
    got = {
        p["slug"]: [e["prefix"] for e in p["plant_id_prefixes"]]
        for p in registry["projects"]
    }
    assert got == EXPECTED_PREFIXES


@pytest.mark.parametrize("project", PROJECTS)
def test_registry_config_matches_the_wrappers_hardcoded_config(
    project, tmp_path, monkeypatch
):
    """The registry-derived CONFIG agrees with the wrapper's CONFIG.

    NOT a field-for-field comparison -- see the assertions below for exactly
    what is checked: CROSS_NAME, AUTO_CREATE, GITHUB_REPO, the prefix fields,
    and that TRACKER_FILE / DISABLE_GITHUB_PUSH are *derived* the same way on
    both sides. BREEDING_DIR is covered separately (it cannot be compared here
    -- the wrapper is sandbox-redirected via its env var).

    This is the guard against registry.json being a plausible-looking parallel
    invention that has quietly drifted from the six live projects.
    """
    wrapper = _load_wrapper(project, tmp_path / project, monkeypatch)
    expected = wrapper.CONFIG

    entry = core.registry_entry(project)
    got = core.config_for_project(entry)

    assert got["CROSS_NAME"] == expected["CROSS_NAME"]
    assert got["AUTO_CREATE"] == expected["AUTO_CREATE"]
    assert got["GITHUB_REPO"] == expected["GITHUB_REPO"]

    if expected.get("PLANT_ID_REGISTRY"):
        assert [p for p, _ in got["PLANT_ID_REGISTRY"]] == \
               [p for p, _ in expected["PLANT_ID_REGISTRY"]]
        assert [r.pattern for _, r in got["PLANT_ID_REGISTRY"]] == \
               [r.pattern for _, r in expected["PLANT_ID_REGISTRY"]]
        assert "PLANT_ID_PATTERN" not in got
    else:
        assert got["PLANT_ID_PATTERN"] == expected["PLANT_ID_PATTERN"]
        assert got["PLANT_ID_PREFIX"] == expected["PLANT_ID_PREFIX"]
        assert "PLANT_ID_REGISTRY" not in got

    # TRACKER_FILE is derived, never stored -- exactly as every wrapper does.
    assert got["TRACKER_FILE"] == got["BREEDING_DIR"] / "tracker.json"
    assert expected["TRACKER_FILE"] == expected["BREEDING_DIR"] / "tracker.json"

    # DISABLE_GITHUB_PUSH is likewise derived, from the same env var in both.
    # ``_load_wrapper`` sets BREEDING_DISABLE_PUSH=1 for the sandbox, so both
    # sides must read True here -- proving they share one source, not that the
    # registry happens to hardcode a matching value.
    assert got["DISABLE_GITHUB_PUSH"] == expected["DISABLE_GITHUB_PUSH"] is True

    # BREEDING_DIR is deliberately NOT compared here: ``_load_wrapper`` points
    # the wrapper at a tmp_path sandbox via the BREEDING_DIR env var, so the
    # wrapper's value in this test is the sandbox, not its real default. The
    # registry-vs-wrapper BREEDING_DIR comparison lives in
    # ``test_registry_breeding_dir_matches_the_wrappers_default`` below, which
    # reads the default out of the wrapper source without importing it.


# ``BREEDING_DIR = Path(os.environ.get('BREEDING_DIR') or (Path.home() / ...))``
_WRAPPER_DEFAULT_DIR_RE = re.compile(
    r"^BREEDING_DIR\s*=.*?Path\.home\(\)\s*(/\s*'[^']+'\s*)+", re.MULTILINE
)
_SEGMENT_RE = re.compile(r"/\s*'([^']+)'")

# KNOWN, DELIBERATE divergence -- asserted rather than silently skipped.
#
# honey-badger-haze-pheno-hunt's wrapper defaults BREEDING_DIR to
# ``~/.hermes/breeding/honey-badger-haze``, but the project directory (and so
# registry.json's breeding_dir) is ``~/.hermes/breeding/honey-badger-haze-pheno-hunt``.
#
# This is NOT an oversight in either file, and neither value is being changed:
# the wrapper's default is dead in practice. The gateway plugin
# (hermes-breeding-ingest/__init__.py::_run_for_cross) sets the BREEDING_DIR
# environment variable to the cross's real directory before importing the
# wrapper, and the wrapper reads that env var first -- so the hardcoded default
# is only ever used if someone runs the wrapper by hand from a shell. The
# registry value is the correct one. Recorded here explicitly so a future
# reader does not "fix" the registry to match a stale wrapper default, and so
# that if the wrapper's default is ever repaired this test fails loudly and
# tells them to delete this entry.
KNOWN_WRAPPER_REGISTRY_DIR_DIVERGENCE = {
    "honey-badger-haze-pheno-hunt": (
        Path.home() / ".hermes" / "breeding" / "honey-badger-haze",  # wrapper default
        Path.home() / ".hermes" / "breeding" / "honey-badger-haze-pheno-hunt",  # registry
    ),
}


def _wrapper_default_breeding_dir(project):
    """The wrapper's hardcoded BREEDING_DIR default, read from SOURCE.

    Parsed rather than imported on purpose: importing sets BREEDING_DIR from
    the environment, which is exactly the value we are trying NOT to observe.
    """
    path = BREEDING_ROOT / project / "monitor_breeding_notes.py"
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")
    match = _WRAPPER_DEFAULT_DIR_RE.search(path.read_text(encoding="utf-8"))
    assert match, f"could not parse BREEDING_DIR default out of {path}"
    return Path.home().joinpath(*_SEGMENT_RE.findall(match.group(0)))


@pytest.mark.parametrize("project", PROJECTS)
def test_registry_breeding_dir_matches_the_wrappers_default(project):
    """registry.json's ``breeding_dir`` vs the wrapper's hardcoded default.

    They agree for five of six projects. The sixth divergence is real,
    currently harmless, and asserted explicitly above rather than left to pass
    silently -- see KNOWN_WRAPPER_REGISTRY_DIR_DIVERGENCE for why it exists.
    """
    wrapper_default = _wrapper_default_breeding_dir(project)
    registry_dir = Path(
        core.registry_entry(project)["breeding_dir"]
    ).expanduser()

    if project in KNOWN_WRAPPER_REGISTRY_DIR_DIVERGENCE:
        expected_wrapper, expected_registry = \
            KNOWN_WRAPPER_REGISTRY_DIR_DIVERGENCE[project]
        assert wrapper_default == expected_wrapper, (
            f"{project}'s wrapper default changed; if it was repaired to match "
            "the registry, delete its KNOWN_WRAPPER_REGISTRY_DIR_DIVERGENCE entry"
        )
        assert registry_dir == expected_registry
        assert wrapper_default != registry_dir  # the documented divergence
    else:
        assert registry_dir == wrapper_default


@pytest.mark.parametrize(
    "text,slug,ids",
    [
        ("MG15 looking fire, vigor 9", "mule-fuel-x-nana-glue", ["MG15"]),
        ("Ltz07 culled", "lantz", ["LTZ07"]),
        ("sp 5 frosty", "spaced-paste", ["SP05"]),
        ("PC12 keeper", "paloma-coma", ["PC12"]),
        ("HBH-3 stretchy", "honey-badger-haze-pheno-hunt", ["HBH03"]),
        ("PK7 and PL3 both fuel", "kibungan-pheno-hunt", ["PK07", "PL03"]),
    ],
)
def test_real_registry_routes_each_projects_prefix(text, slug, ids):
    routed = core.route_message(text, pull=False)
    assert [r["slug"] for r in routed] == [slug]
    assert routed[0]["plant_ids"] == ids


def test_unknown_prefix_routes_nowhere():
    assert core.route_message("ZZ99 has no home", pull=False) == []


# ------------------------------------------------------------ registry read

def test_load_registry_reads_the_sandbox_clone(meta_repo, tmp_path):
    _write_registry(meta_repo, [_project_entry(
        "demo", tmp_path / "demo", [{"prefix": "DM", "pattern": r"\bDM(\d{1,2})\b"}]
    )])
    assert [p["slug"] for p in core.load_registry()["projects"]] == ["demo"]


def test_missing_registry_raises_and_names_the_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("BREEDING_META_DIR", str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError) as exc:
        core.load_registry()
    assert "BREEDING_META_DIR" in str(exc.value)


def test_malformed_registry_raises_rather_than_routing_on_garbage(meta_repo):
    (meta_repo / "registry.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "registry.json" in str(exc.value)


def test_duplicate_prefix_across_projects_is_rejected(meta_repo, tmp_path):
    pfx = [{"prefix": "DM", "pattern": r"\bDM(\d{1,2})\b"}]
    _write_registry(meta_repo, [
        _project_entry("a", tmp_path / "a", pfx),
        _project_entry("b", tmp_path / "b", pfx),
    ])
    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "DM" in str(exc.value)


def test_unknown_backend_in_registry_is_rejected_at_load_time(meta_repo, tmp_path):
    """NICK-949 stage-2 review, round 3 (I2): an invalid ``backend`` must
    fail loud at ``load_registry()`` time, naming the project -- the same
    guarantee every other required/validated field in this registry already
    gets (missing slug, missing breeding_dir, duplicate/ambiguous prefix).
    Previously this was only checked inside ``config_for_project`` per
    message, where the one-key config `backend_name()` was called with had
    no CROSS_NAME to report -- so the error said '<unknown project>' instead
    of naming the actual malformed entry."""
    pfx = [{"prefix": "ZZ", "pattern": r"\bZZ(\d{1,2})\b"}]
    _write_registry(meta_repo, [
        _project_entry("bad-backend-project", tmp_path / "bbp", pfx, backend="sqlite"),
    ])
    with pytest.raises(ValueError, match=r"bad-backend-project.*sqlite"):
        core.load_registry()


def test_config_for_project_names_the_project_for_an_unknown_backend(tmp_path):
    """NICK-949 stage-2 review, round 4 (I3): the fix that threads
    entry['cross_name'] through to backend_name() lives entirely inside
    ``config_for_project`` -- and nothing called ``config_for_project``
    directly with a bad backend before this test. A reviewer proved that by
    reverting just that one line and re-running the full suite: it stayed
    green. This calls ``config_for_project`` the same way
    ``registry_entry(registry=...)``-based callers do (bypassing
    ``load_registry``/``_validate_registry`` entirely), which is exactly the
    path where this fix is load-bearing, not redundant.
    """
    entry = _project_entry("cfp-bad-backend", tmp_path / "cfpbb",
                            [{"prefix": "CB", "pattern": r"\bCB(\d{1,2})\b"}],
                            backend="sqlite")
    with pytest.raises(ValueError, match=r"sqlite.*cfp-bad-backend"):
        core.config_for_project(entry)


def test_config_for_project_falls_back_to_slug_when_cross_name_absent(tmp_path):
    """Same fix, the other branch: entry.get('cross_name', entry['slug'])
    must actually fall back, not KeyError or silently drop the name, when an
    entry has no explicit 'cross_name' at all (only 'slug' is required)."""
    entry = {
        "slug": "no-cross-name-project",
        "breeding_dir": str(tmp_path / "ncnp"),
        "github_repo": "joeydouglas/no-cross-name-project",
        "auto_create": False,
        "plant_id_prefixes": [{"prefix": "NC", "pattern": r"\bNC(\d{1,2})\b"}],
        "backend": "sqlite",
    }
    assert "cross_name" not in entry
    with pytest.raises(ValueError, match=r"sqlite.*no-cross-name-project"):
        core.config_for_project(entry)


def test_config_for_project_falls_back_to_slug_when_cross_name_is_explicitly_null(tmp_path):
    """NICK-949 stage-2 review round 4 (M2): a registry entry with
    ``"cross_name": null`` (JSON explicit-null, a PRESENT key, not a missing
    one) must ALSO fall back to slug -- entry.get('cross_name', fallback)
    does not fall back for a present-but-None value, only an absent key.
    This is a stricter case than the absent-key test above: it also proves
    config['CROSS_NAME'] itself (not just the error message) is never left
    as None, since that would silently break the backend-error project-
    naming fix for exactly this input."""
    entry = {
        "slug": "null-cross-name-project",
        "cross_name": None,
        "breeding_dir": str(tmp_path / "ncnp2"),
        "github_repo": "joeydouglas/null-cross-name-project",
        "auto_create": False,
        "plant_id_prefixes": [{"prefix": "NL", "pattern": r"\bNL(\d{1,2})\b"}],
    }
    got = core.config_for_project(entry)
    assert got["CROSS_NAME"] == "null-cross-name-project"

    entry["backend"] = "sqlite"
    with pytest.raises(ValueError, match=r"sqlite.*null-cross-name-project"):
        core.config_for_project(entry)


def test_registry_entry_raises_for_unknown_slug():
    with pytest.raises(KeyError):
        core.registry_entry("no-such-project")


def test_entry_without_breeding_dir_is_rejected_at_load_time(meta_repo, tmp_path):
    """A missing ``breeding_dir`` must fail loud at load, like every other
    required field.

    Regression test. Previously ``breeding_dir`` was the one required field
    ``_validate_registry`` did NOT check: an entry missing it loaded clean and
    only blew up later, deep inside ``config_for_project``, as an opaque
    ``KeyError: 'breeding_dir'`` with no indication of which project was at
    fault. Every other required field (``slug``, ``plant_id_prefixes``) fails
    at load with the slug named; this one now does too.
    """
    entry = _project_entry(
        "no-dir", tmp_path / "x", [{"prefix": "ND", "pattern": r"\bND(\d{1,2})\b"}]
    )
    del entry["breeding_dir"]
    _write_registry(meta_repo, [entry])

    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "no-dir" in str(exc.value)
    assert "breeding_dir" in str(exc.value)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_breeding_dir_is_rejected_at_load_time(meta_repo, tmp_path, bad):
    """Present-but-empty is as broken as absent -- an empty path would resolve
    to the process CWD and scatter plant markdown wherever the bot was started.
    """
    entry = _project_entry(
        "blank-dir", tmp_path / "x", [{"prefix": "BD", "pattern": r"\bBD(\d{1,2})\b"}]
    )
    entry["breeding_dir"] = bad
    _write_registry(meta_repo, [entry])

    with pytest.raises(ValueError) as exc:
        core.load_registry()
    assert "blank-dir" in str(exc.value)
    assert "breeding_dir" in str(exc.value)


# ------------------------------------------------------- never-raise refresh

def test_refresh_never_raises_without_a_remote(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "meta"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _write_registry(repo, [])
    monkeypatch.setenv("BREEDING_META_DIR", str(repo))
    core.refresh_meta_repo()  # no origin -> silent no-op
    assert core.load_registry(pull=True)["projects"] == []


def test_refresh_warns_but_never_raises_on_a_broken_remote(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "meta"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _write_registry(repo, [])
    _git(["add", "registry.json"], repo)
    _git(["commit", "-qm", "i"], repo)
    _git(["remote", "add", "origin", str(tmp_path / "does-not-exist.git")], repo)
    monkeypatch.setenv("BREEDING_META_DIR", str(repo))

    core.refresh_meta_repo()
    assert "WARN: git pull failed" in capsys.readouterr().err
    # and ingestion still proceeds off the last-known-good checkout
    assert core.load_registry(pull=True)["projects"] == []


def test_refresh_never_raises_when_git_is_missing(meta_repo, monkeypatch, capsys):
    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(core.subprocess, "run", boom)
    core.refresh_meta_repo()
    assert "WARN: git pull failed" in capsys.readouterr().err


def test_refresh_never_raises_on_a_non_git_directory(tmp_path, monkeypatch):
    repo = tmp_path / "plain"
    repo.mkdir()
    _write_registry(repo, [])
    monkeypatch.setenv("BREEDING_META_DIR", str(repo))
    core.refresh_meta_repo()
    assert core.load_registry(pull=True)["projects"] == []


# ------------------------------------------------------------- ACCEPTANCE

def test_acceptance_new_project_routes_with_zero_code_change(
    meta_repo, tmp_path, monkeypatch
):
    """THE Task 2.5 acceptance criterion, proven literally.

    A seventh, entirely fictional project is added to registry.json and
    PUSHED to a throwaway bare remote by a separate authoring clone. The
    consumer clone that ``breeding_core`` reads has never seen it. Running
    ingestion routing against a message using the new prefix must route it
    correctly -- with breeding_core.py byte-identical throughout.
    """
    before = hashlib.sha256(BREEDING_CORE_PY.read_bytes()).hexdigest()

    bare = tmp_path / "breeding-meta-origin.git"
    consumer = meta_repo

    # Seed the remote with one existing project, and sync the consumer.
    authoring = tmp_path / "authoring"
    subprocess.run(["git", "clone", "-q", str(bare), str(authoring)], check=True)
    _write_registry(authoring, [_project_entry(
        "demo-one", tmp_path / "demo-one",
        [{"prefix": "D1", "pattern": r"\bD1[\s\-]?(\d{1,2})\b"}],
    )])
    _git(["add", "registry.json"], authoring)
    _git(["commit", "-qm", "seed"], authoring)
    _git(["push", "-q", "origin", "main"], authoring)
    core.refresh_meta_repo()

    assert [r["slug"] for r in core.route_message("D1 4 vigor 8")] == ["demo-one"]
    # The new prefix is unknown to the consumer clone right now.
    assert core.route_message("ZQ12 vigor 7") == []

    # --- a seventh project is added to registry.json and PUSHED -----------
    new_dir = tmp_path / "zephyr-quartz"
    (new_dir / "plants").mkdir(parents=True)
    _write_registry(authoring, [
        _project_entry("demo-one", tmp_path / "demo-one",
                       [{"prefix": "D1", "pattern": r"\bD1[\s\-]?(\d{1,2})\b"}]),
        _project_entry(
            "zephyr-quartz", new_dir,
            [{"prefix": "ZQ", "pattern": r"\bZQ[\s\-]?(\d{1,2})\b"}],
            cross_name="Zephyr Quartz", auto_create=True,
            github_repo="joeydouglas/zephyr-quartz",
        ),
    ])
    _git(["add", "registry.json"], authoring)
    _git(["commit", "-qm", "add zephyr-quartz"], authoring)
    _git(["push", "-q", "origin", "main"], authoring)

    # The consumer clone on disk is STILL stale -- no pull has happened yet.
    assert core.load_registry(pull=False)["projects"][0]["slug"] == "demo-one"
    assert len(core.load_registry(pull=False)["projects"]) == 1

    # Ingestion pulls before routing, so the new project routes immediately.
    routed = core.route_message("ZQ 12 top keeper, vigor 9")
    assert [r["slug"] for r in routed] == ["zephyr-quartz"]
    assert routed[0]["plant_ids"] == ["ZQ12"]

    cfg = routed[0]["config"]
    assert cfg["CROSS_NAME"] == "Zephyr Quartz"
    assert cfg["AUTO_CREATE"] is True
    assert cfg["GITHUB_REPO"] == "joeydouglas/zephyr-quartz"
    assert cfg["BREEDING_DIR"] == new_dir
    assert cfg["TRACKER_FILE"] == new_dir / "tracker.json"

    # ...and the pre-existing project still routes.
    assert [r["slug"] for r in core.route_message("D1-4 vigor 8")] == ["demo-one"]

    after = hashlib.sha256(BREEDING_CORE_PY.read_bytes()).hexdigest()
    assert before == after, "breeding_core.py was modified during the proof"


def test_acceptance_new_project_config_drives_a_real_ingestion(
    meta_repo, tmp_path, monkeypatch
):
    """Routing is not just a lookup: the config it yields actually ingests.

    The fictional project's registry entry is fed straight into
    ``process_message`` and must create and persist a plant record in the
    sandbox project dir -- with no wrapper module existing for it at all.
    """
    monkeypatch.setenv("BREEDING_DISABLE_PUSH", "1")
    new_dir = tmp_path / "zephyr-quartz"
    new_dir.mkdir()
    _write_registry(meta_repo, [_project_entry(
        "zephyr-quartz", new_dir,
        [{"prefix": "ZQ", "pattern": r"\bZQ[\s\-]?(\d{1,2})\b"}],
        cross_name="Zephyr Quartz", auto_create=True,
    )])

    routed = core.route_message("ZQ12 strong keeper, vigor 9, fuel", pull=False)
    assert len(routed) == 1
    config = routed[0]["config"]
    assert config["DISABLE_GITHUB_PUSH"] is True

    core.save_tracker({"project": {"name": "Zephyr Quartz"}, "plants": []},
                      config["TRACKER_FILE"])
    result = core.process_message("ZQ12 strong keeper, vigor 9, fuel", config)

    assert "ZQ12" in result
    tracker = core.load_tracker(config["TRACKER_FILE"])
    plant = next(
        p for p in tracker["plants"] if core.plant_id_of(p) == "ZQ12"
    )
    assert plant["status"] == "top_keeper"
    assert (new_dir / "plants" / "ZQ12.md").exists()


# -------------------------------------------------- this task touched nothing

@pytest.mark.parametrize("project", PROJECTS)
def test_task_2_5_did_not_touch_any_real_wrapper(project):
    """Re-checks the SAME WRAPPER_SHA256 pin as
    test_wrapper_compatibility.py's own drift guard (imported above). Task
    2.5 itself made no wrapper edits; NICK-949 and NICK-924 are LATER,
    deliberate edits that re-baseline WRAPPER_SHA256 (see that dict's
    comment) -- this test's job is drift detection against the CURRENT
    baseline, not a standing claim that wrappers never change."""
    path = BREEDING_ROOT / project / "monitor_breeding_notes.py"
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == WRAPPER_SHA256[project]
