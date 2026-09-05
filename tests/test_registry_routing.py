"""Task 2.5: project routing is DATA (``registry.json``), not code.

Before this task, ``breeding_core.py`` knew nothing about which projects
exist -- every one of the six ``monitor_breeding_notes.py`` wrappers handed
it a fully hardcoded ``CONFIG`` dict. Adding a seventh cross therefore meant
authoring a seventh wrapper. (The finalized plan called this "replace the
hardcoded ``_CROSS_DIRS`` dict"; no such dict ever existed in this codebase
-- the hardcoding was distributed across the six wrappers instead. Same
problem, different shape. See DECISIONS.md.)

Task 2.5 adds the missing routing table as *data*: a ``registry.json`` in a
separate ``breeding-meta`` git repo that ``breeding_core.py`` clones locally
and ``git pull``s before each ingestion run.

The acceptance criterion from the plan is literal and is proven by
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
import subprocess
import sys
from pathlib import Path

import pytest

import breeding_core as core
from test_wrapper_compatibility import PROJECTS, WRAPPER_SHA256, _load_wrapper

BREEDING_ROOT = Path.home() / ".hermes" / "breeding"
MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_CORE_PY = MONITOR_CORE_DIR / "breeding_core.py"

# Ground truth read out of the six real wrappers at the start of Task 2.5.
# registry.json must agree with these or it is not describing reality.
EXPECTED_PREFIXES = {
    "mule-fuel-x-nana-glue": ["MG"],
    "honey-badger-haze-pheno-hunt": ["HBH"],
    "kibungan-pheno-hunt": ["PK", "PL"],
    "spaced-paste": ["sp"],
    "paloma-coma": ["PC"],
    "lantz": ["Ltz"],
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
    """The registry-derived CONFIG is the wrapper's CONFIG, field for field.

    This is the proof that registry.json is a faithful description of the
    six live projects rather than a plausible-looking parallel invention.
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


@pytest.mark.parametrize(
    "text,slug,ids",
    [
        ("MG15 looking fire, vigor 9", "mule-fuel-x-nana-glue", ["MG15"]),
        ("Ltz07 culled", "lantz", ["Ltz07"]),
        ("sp 5 frosty", "spaced-paste", ["sp05"]),
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


def test_registry_entry_raises_for_unknown_slug():
    with pytest.raises(KeyError):
        core.registry_entry("no-such-project")


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
    plant = next(p for p in tracker["plants"] if p["id"] == "ZQ12")
    assert plant["status"] == "top_keeper"
    assert (new_dir / "plants" / "ZQ12.md").exists()


# -------------------------------------------------- this task touched nothing

@pytest.mark.parametrize("project", PROJECTS)
def test_task_2_5_did_not_touch_any_real_wrapper(project):
    path = BREEDING_ROOT / project / "monitor_breeding_notes.py"
    if not path.exists():
        pytest.skip(f"wrapper for {project} not present")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == WRAPPER_SHA256[project]
