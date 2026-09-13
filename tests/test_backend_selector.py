"""NICK-949 -- TDD: per-project storage-backend selector (markdown vs JSON).

WHY THIS EXISTS (and why it was not there from the start): Task 2.1 flipped
``load_tracker``/``save_tracker`` to the markdown backend GLOBALLY -- one
unconditional ``markdown_backend`` call shared by all six wrappers, with no
per-project override (commit f2bbca5). That was fine as a migration step but
it left Phase 2's rollback story unimplementable: Task 7.2's rollback
rehearsal has to "switch that project's config to the new backend" and then
"flip config back to JSON" for ONE project, without touching the other five.
There was no config key to flip. This suite pins the selector that makes
that possible.

Contract pinned here:

1. ``CONFIG['BACKEND']`` selects storage per project: ``'markdown'`` or
   ``'json'``.
2. **Absent key defaults to markdown** -- backward compatibility, so a config
   built before this task (or by ``config_for_project`` from a registry entry
   with no backend field) behaves exactly as it does today.
3. Flipping ``BACKEND`` on an existing config and re-calling load/save
   actually switches which storage is read and written -- the literal
   mechanism the rollback rehearsal drives.
4. An unknown backend name fails LOUD, matching this codebase's standing call
   on ambiguous persistence config (see ``_validate_registry``): silently
   falling back would write a project's observations to the wrong store.

Sandbox-only: every write lands in pytest ``tmp_path``; real project dirs are
never written.
"""

import json
import re
from pathlib import Path

import pytest

from breeding_tracker import breeding_core as core


# ------------------------------------------------------------- helpers ----


def _config(project_dir, backend=None):
    """A minimal per-project config of the shape the six wrappers build."""
    config = {
        'BREEDING_DIR': project_dir,
        'TRACKER_FILE': project_dir / 'tracker.json',
        'CROSS_NAME': 'Sandbox Cross',
        'AUTO_CREATE': False,
        'GITHUB_REPO': 'sandbox/none',
        'DISABLE_GITHUB_PUSH': True,
    }
    if backend is not None:
        config['BACKEND'] = backend
    return config


@pytest.fixture
def small_tracker():
    return {
        'cross_name': 'Sandbox Cross',
        'plants': [
            # vigor is a STRING: the markdown backend stores scalars as text
            # (see test_tracker_persistence's no-YAML-retyping tests), so an
            # int would not survive a markdown round trip and would make these
            # tests about the backend's typing rather than about routing.
            {'id': 'SB01', 'status': 'active', 'vigor': '8', 'observation_log': '\n### t\nnote\n'},
            {'id': 'SB02', 'status': 'keeper', 'vigor': '9', 'observation_log': ''},
        ],
    }


# --------------------------------------------------- selector surface ----


def test_default_backend_is_markdown():
    assert core.DEFAULT_BACKEND == 'markdown'


def test_both_backends_are_registered():
    assert set(core.STORAGE_BACKENDS) == {'markdown', 'json'}


def test_json_backend_module_is_importable_and_has_the_two_functions():
    backend = core.STORAGE_BACKENDS['json']
    assert callable(backend.load_tracker)
    assert callable(backend.save_tracker)


def test_backend_name_defaults_to_markdown_when_config_has_no_backend_key(tmp_path):
    assert core.backend_name(_config(tmp_path)) == 'markdown'


def test_backend_name_reads_an_explicit_key(tmp_path):
    assert core.backend_name(_config(tmp_path, 'json')) == 'json'
    assert core.backend_name(_config(tmp_path, 'markdown')) == 'markdown'


def test_backend_name_defaults_for_a_none_config():
    assert core.backend_name(None) == 'markdown'


def test_unknown_backend_fails_loud(tmp_path):
    with pytest.raises(ValueError) as exc:
        core.backend_name(_config(tmp_path, 'sqlite'))
    assert 'sqlite' in str(exc.value)


def test_unknown_backend_error_names_the_project(tmp_path):
    """NICK-949 stage-2 review I2: an unqualified 'unknown backend' error
    across six near-identical wrappers leaves the reader to go find which
    project it was about. The message must name it -- and this must be a
    real `match=` assertion, not just 'a ValueError was raised', or a future
    edit can silently drop the project name again (as happened once already:
    the CROSS_NAME wiring was added without a test, and a downstream config
    builder that didn't set CROSS_NAME went unnoticed)."""
    with pytest.raises(ValueError, match=r"Sandbox Cross"):
        core.backend_name(_config(tmp_path, 'sqlite'))


def test_unknown_backend_error_falls_back_to_tracker_file_without_cross_name():
    """A config with no CROSS_NAME at all (not the shape wrappers build, but
    not disallowed either) must still name *something* locatable -- the
    tracker path -- rather than silently omitting project identification."""
    config = {'BACKEND': 'sqlite', 'TRACKER_FILE': Path('/tmp/nope/tracker.json')}
    with pytest.raises(ValueError, match=r"nope/tracker\.json"):
        core.backend_name(config)


def test_empty_string_backend_fails_loud_not_defaults(tmp_path):
    """NICK-949 stage-2 review round 4 (M1): backend_name() used to treat
    BACKEND: '' the same as an absent key (falsy-or fallback), silently
    defaulting to markdown -- while _validate_registry() already rejected an
    empty backend as an explicit invalid value. The two checks disagreeing
    on the same input is exactly the class of gap this module exists to
    close; an empty string is a half-finished edit, not an intentional
    'use the default' signal, same reasoning as any other typo'd name."""
    with pytest.raises(ValueError, match=r"unknown storage backend ''"):
        core.backend_name(_config(tmp_path, ''))


def test_none_and_missing_backend_key_still_default_to_markdown(tmp_path):
    """The empty-string fix (above) must not regress the genuinely-absent
    cases: no config, no BACKEND key, and an explicit BACKEND: None must all
    still mean 'use the default', since that's the whole point of every
    existing wrapper/registry entry that predates NICK-949."""
    assert core.backend_name(None) == core.DEFAULT_BACKEND
    assert core.backend_name({}) == core.DEFAULT_BACKEND
    assert core.backend_name({'BACKEND': None}) == core.DEFAULT_BACKEND


def test_unknown_backend_fails_loud_on_load_and_save(tmp_path, small_tracker):
    config = _config(tmp_path, 'postgres')
    with pytest.raises(ValueError):
        core.load_tracker_for(config)
    with pytest.raises(ValueError):
        core.save_tracker_for(small_tracker, config)


def test_backend_name_is_not_silently_case_or_whitespace_normalised(tmp_path):
    """A config saying ``'JSON'`` is a typo, not a backend -- routing on a
    guess is exactly what ``_validate_registry`` refuses to do."""
    with pytest.raises(ValueError):
        core.backend_name(_config(tmp_path, 'JSON'))
    with pytest.raises(ValueError):
        core.backend_name(_config(tmp_path, ' json '))


# ------------------------------------------------- markdown path (default) -


def test_markdown_backend_writes_markdown_not_tracker_json(tmp_path, small_tracker):
    config = _config(tmp_path, 'markdown')
    core.save_tracker_for(small_tracker, config)

    assert (tmp_path / 'project.md').is_file()
    assert not (tmp_path / 'tracker.json').exists()
    assert sorted(p.stem for p in (tmp_path / 'plants').glob('*.md')) == ['SB01', 'SB02']


def test_absent_backend_key_behaves_exactly_like_markdown(tmp_path, small_tracker):
    """Backward compatibility: the pre-NICK-949 config shape, unchanged."""
    config = _config(tmp_path)  # no BACKEND key at all
    core.save_tracker_for(small_tracker, config)

    assert (tmp_path / 'project.md').is_file()
    assert not (tmp_path / 'tracker.json').exists()
    assert core.load_tracker_for(config) == small_tracker


def test_markdown_round_trip_via_the_selector(tmp_path, small_tracker):
    config = _config(tmp_path, 'markdown')
    core.save_tracker_for(small_tracker, config)
    assert core.load_tracker_for(config) == small_tracker


# ----------------------------------------------------------- json path ----


def test_json_backend_writes_tracker_json_and_no_markdown(tmp_path, small_tracker):
    config = _config(tmp_path, 'json')
    core.save_tracker_for(small_tracker, config)

    tracker_file = tmp_path / 'tracker.json'
    assert tracker_file.is_file()
    assert json.loads(tracker_file.read_text(encoding='utf-8')) == small_tracker
    assert not (tmp_path / 'project.md').exists()
    assert not (tmp_path / 'plants').exists()


def test_json_round_trip_via_the_selector(tmp_path, small_tracker):
    config = _config(tmp_path, 'json')
    core.save_tracker_for(small_tracker, config)
    assert core.load_tracker_for(config) == small_tracker


def test_json_backend_is_the_restored_pre_task_2_1_implementation(tmp_path, small_tracker):
    """Byte-for-byte the JSON era's writer (``json.dump(..., indent=2)``),
    restored from commit 2dd0537 rather than rewritten -- a rollback that
    produced a differently-formatted file would emit a whole-file git diff
    for every project it touched."""
    config = _config(tmp_path, 'json')
    core.save_tracker_for(small_tracker, config)

    expected = json.dumps(small_tracker, indent=2)
    assert (tmp_path / 'tracker.json').read_text() == expected


def test_json_backend_load_raises_file_not_found_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        core.load_tracker_for(_config(tmp_path, 'json'))


# ------------------------------------------- THE ROLLBACK MECHANISM -------


def test_flipping_backend_switches_which_store_is_written(tmp_path, small_tracker):
    """Task 7.2 rollback rehearsal, in miniature: one project's config flips
    markdown -> json and the very next save lands in the other store."""
    config = _config(tmp_path, 'markdown')
    core.save_tracker_for(small_tracker, config)
    assert (tmp_path / 'project.md').is_file()
    assert not (tmp_path / 'tracker.json').exists()

    config['BACKEND'] = 'json'          # <- the literal rollback flip
    core.save_tracker_for(small_tracker, config)

    assert (tmp_path / 'tracker.json').is_file()
    assert core.load_tracker_for(config) == small_tracker


def test_flipping_backend_switches_which_store_is_read(tmp_path, small_tracker):
    """Two DIFFERENT payloads in the two stores; the config key alone decides
    which one comes back."""
    md_config = _config(tmp_path, 'markdown')
    core.save_tracker_for(small_tracker, md_config)

    json_payload = dict(small_tracker)
    json_payload['cross_name'] = 'FROM-JSON-STORE'
    core.save_tracker_for(json_payload, _config(tmp_path, 'json'))

    assert core.load_tracker_for(_config(tmp_path, 'markdown'))['cross_name'] == 'Sandbox Cross'
    assert core.load_tracker_for(_config(tmp_path, 'json'))['cross_name'] == 'FROM-JSON-STORE'

    # ...and the round trip is lossless in both directions.
    assert core.load_tracker_for(_config(tmp_path, 'json')) == json_payload


def test_round_trip_markdown_to_json_and_back_preserves_the_tracker(tmp_path, small_tracker):
    """Rollback and roll-forward: the rehearsal flips to the new backend and
    then flips back, and no data may be lost either way."""
    config = _config(tmp_path, 'json')
    core.save_tracker_for(small_tracker, config)

    config['BACKEND'] = 'markdown'
    core.save_tracker_for(core.load_tracker_for(_config(tmp_path, 'json')), config)
    assert core.load_tracker_for(config) == small_tracker

    config['BACKEND'] = 'json'
    core.save_tracker_for(core.load_tracker_for(_config(tmp_path, 'markdown')), config)
    assert core.load_tracker_for(config) == small_tracker


def test_one_projects_flip_does_not_affect_another_project(tmp_path, small_tracker):
    """The whole point of PER-PROJECT: rehearsing rollback on one cross must
    leave the other five on markdown."""
    a = tmp_path / 'project-a'
    b = tmp_path / 'project-b'
    a.mkdir()
    b.mkdir()

    core.save_tracker_for(small_tracker, _config(a, 'json'))
    core.save_tracker_for(small_tracker, _config(b, 'markdown'))

    assert (a / 'tracker.json').is_file() and not (a / 'project.md').exists()
    assert (b / 'project.md').is_file() and not (b / 'tracker.json').exists()


# -------------------------------------------- integration: update_plant ---


def _observation(text='vigor 7 fuel'):
    return core.parse_observation(text)


def test_update_plant_honours_the_json_backend(tmp_path, small_tracker, monkeypatch):
    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **k: None)
    monkeypatch.setattr(core, 'push_to_github', lambda *a, **k: None)

    config = _config(tmp_path, 'json')
    config['PLANT_ID_PATTERN'] = r'\bSB(\d{1,2})\b'
    config['PLANT_ID_PREFIX'] = 'SB'
    core.save_tracker_for(small_tracker, config)

    result = core.update_plant('SB01', _observation(), config)

    assert 'SB01' in result
    stored = json.loads((tmp_path / 'tracker.json').read_text(encoding='utf-8'))
    plant = next(p for p in stored['plants'] if p['id'] == 'SB01')
    assert plant['vigor'] == 7  # JSON backend keeps the int verbatim
    assert not (tmp_path / 'project.md').exists()


def test_update_plant_still_defaults_to_markdown_with_no_backend_key(
    tmp_path, small_tracker, monkeypatch
):
    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **k: None)
    monkeypatch.setattr(core, 'push_to_github', lambda *a, **k: None)

    config = _config(tmp_path)  # no BACKEND key
    config['PLANT_ID_PATTERN'] = r'\bSB(\d{1,2})\b'
    config['PLANT_ID_PREFIX'] = 'SB'
    core.save_tracker_for(small_tracker, config)

    core.update_plant('SB01', _observation(), config)

    assert (tmp_path / 'plants' / 'SB01.md').is_file()
    assert not (tmp_path / 'tracker.json').exists()


# ----------------------------------------- registry-built configs ---------


def test_config_for_project_defaults_to_markdown(tmp_path, monkeypatch):
    """A registry entry that says nothing about storage keeps today's
    behaviour."""
    entry = {
        'slug': 'sandbox',
        'breeding_dir': str(tmp_path),
        'cross_name': 'Sandbox',
        'plant_id_prefixes': [{'prefix': 'SB', 'pattern': r'\bSB(\d{1,2})\b'}],
    }
    monkeypatch.setattr(core, '_validated_breeding_dir', lambda *a, **k: Path(tmp_path))
    config = core.config_for_project(entry)
    assert config['BACKEND'] == 'markdown'


def test_config_for_project_carries_an_explicit_backend(tmp_path, monkeypatch):
    entry = {
        'slug': 'sandbox',
        'breeding_dir': str(tmp_path),
        'cross_name': 'Sandbox',
        'backend': 'json',
        'plant_id_prefixes': [{'prefix': 'SB', 'pattern': r'\bSB(\d{1,2})\b'}],
    }
    monkeypatch.setattr(core, '_validated_breeding_dir', lambda *a, **k: Path(tmp_path))
    config = core.config_for_project(entry)
    assert config['BACKEND'] == 'json'


# ------------------------------------- path-only façade is unchanged ------


def test_path_only_load_and_save_still_exist_and_use_the_default_backend(
    tmp_path, small_tracker
):
    """``load_tracker(tracker_file)`` / ``save_tracker(tracker, tracker_file)``
    keep their exact JSON-era signatures -- test_tracker_persistence.py pins
    them and the six wrappers' historical calls used them. They route to
    ``DEFAULT_BACKEND``."""
    core.save_tracker(small_tracker, tmp_path / 'tracker.json')
    assert (tmp_path / 'project.md').is_file()
    assert core.load_tracker(tmp_path / 'tracker.json') == small_tracker


# ------------------------------------------------- wrappers are explicit --


WRAPPERS = [
    'lantz', 'mule-fuel-x-nana-glue', 'honey-badger-haze-pheno-hunt',
    'kibungan-pheno-hunt', 'spaced-paste', 'paloma-coma',
]


@pytest.mark.parametrize('project', WRAPPERS)
def test_every_live_wrapper_declares_its_backend_explicitly(project):
    """No live project may rely on the implicit default: a future reader
    flipping a backend must be able to SEE the key that is being flipped.

    NICK-949 stage-2 review round 4 (M3, carried from round 1's M2, flagged
    twice as still open): this used to assert the literal substring
    "'BACKEND': 'markdown'", which pins the VALUE, not just the key's
    presence -- it would fail the moment Task 7.2 legitimately flips a
    project's wrapper to 'BACKEND': 'json' during its cutover/rollback
    rehearsal, for a reason that has nothing to do with what this test is
    actually meant to guard. Assert the key exists with a valid value
    instead, which is what "declares its backend explicitly" actually
    means."""
    path = Path.home() / '.hermes' / 'breeding' / project / 'monitor_breeding_notes.py'
    if not path.exists():
        pytest.skip(f'wrapper for {project} not present')
    source = path.read_text(encoding='utf-8')
    match = re.search(r"'BACKEND':\s*'(\w+)'", source)
    assert match, f"{project}'s wrapper does not declare a 'BACKEND' key at all"
    assert match.group(1) in core.STORAGE_BACKENDS, (
        f"{project}'s wrapper declares BACKEND={match.group(1)!r}, "
        f"not one of {sorted(core.STORAGE_BACKENDS)}"
    )
