#!/usr/bin/env python3
"""
Shared core logic for per-project monitor_breeding_notes.py scripts.

SINGLE SOURCE OF TRUTH (NICK-592): every cross/pheno-hunt project used to
carry its own full copy of this logic (parse_observation, update_plant,
update_markdown, push_to_github, process_message). Copies drifted --
Mule Fuel x Nana Glue, Lantz, and Spaced Paste were missing status
(keeper/culled) detection entirely until NICK-589 caught it via a live
Ltz07 cull note that updated observation_log but not plant['status'].

Each project's own monitor_breeding_notes.py is now a thin config wrapper
that imports these functions and calls them with its own BREEDING_DIR,
GITHUB_REPO, cross name, plant-ID pattern(s), and auto_create flag. Do NOT
copy this file's logic back into a per-project script -- add new shared
behavior here so every project picks it up automatically.
"""

import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import json_backend
import markdown_backend

TERPENE_KEYWORDS = ['fuel', 'gas', 'citrus', 'fruity', 'sweet', 'earthy', 'pine', 'skunky', 'diesel']
STRUCTURE_KEYWORDS = ['frosty', 'dense', 'sandy', 'sticky', 'purple', 'tight', 'fox.*tail', 'stretch']


# ---------------------------------------------------------------------------
# STORAGE BACKEND SELECTION (NICK-949)
#
# Task 2.1 migrated tracker persistence from `tracker.json` to markdown by
# flipping `load_tracker`/`save_tracker` to call `markdown_backend`
# UNCONDITIONALLY (commit f2bbca5) -- one global switch shared by all six
# per-project wrappers. That was the smallest safe migration step, but it
# omitted the per-project half of the design: Phase 2's rollback plan
# (Task 7.2) requires flipping ONE project back to JSON while the other five
# stay on markdown, and no config key existed to express that. This block is
# that missing piece, added after the fact -- not a new feature, the switch
# 2.1 should have carried.
#
# Both backends implement the same two functions with the same signatures and
# the same `FileNotFoundError`-when-absent contract, so routing between them
# is a dict lookup and nothing downstream can tell which one ran.
# ---------------------------------------------------------------------------

STORAGE_BACKENDS = {
    'markdown': markdown_backend,
    'json': json_backend,
}

# Absent config key => markdown. Backward compatibility is the whole point:
# every config built before this task (and every registry entry that says
# nothing about storage) must keep behaving exactly as it does today.
DEFAULT_BACKEND = 'markdown'

BACKEND_CONFIG_KEY = 'BACKEND'


def backend_name(config=None):
    """The backend name for a per-project ``config`` dict.

    Returns ``DEFAULT_BACKEND`` when ``config`` is ``None`` or carries no
    ``BACKEND`` key. Raises ``ValueError`` for a name that is not registered.

    The unknown-name case FAILS LOUD, and deliberately does not case-fold or
    strip -- the same call ``_validate_registry`` makes about ambiguous
    routing config. A config saying ``'JSON'`` or ``'sqlite'`` is a typo or a
    half-finished edit; quietly falling back to markdown would write a
    rolled-back project's observations into the store nobody is reading.
    """
    name = (config or {}).get(BACKEND_CONFIG_KEY) or DEFAULT_BACKEND
    if name not in STORAGE_BACKENDS:
        raise ValueError(
            f"unknown storage backend {name!r} in config[{BACKEND_CONFIG_KEY!r}]; "
            f"expected one of {sorted(STORAGE_BACKENDS)}"
        )
    return name


def backend_for(config=None):
    """The backend MODULE selected by ``config`` (see ``backend_name``)."""
    return STORAGE_BACKENDS[backend_name(config)]


def load_tracker_for(config):
    """Load a project's tracker through ITS OWN configured backend.

    This is the config-aware entry point; ``load_tracker(tracker_file)``
    below is the path-only façade that keeps the JSON-era signature.
    """
    return backend_for(config).load_tracker(config['TRACKER_FILE'])


def save_tracker_for(tracker, config):
    """Save a project's tracker through ITS OWN configured backend."""
    backend_for(config).save_tracker(tracker, config['TRACKER_FILE'])


def load_tracker(tracker_file):
    """Load a project's tracker (path-only façade, DEFAULT backend).

    PHASE 2 / TASK 2.1: the default on-disk format is markdown -- `project.md`
    plus `plants/<ID>.md` in `tracker_file`'s parent directory -- not
    `tracker.json`. The SIGNATURE and the returned data shape are unchanged,
    so every per-project `monitor_breeding_notes.py` wrapper keeps calling
    `core.load_tracker(TRACKER_FILE)` with no edit at all. `tracker_file`
    itself is no longer read; only its parent directory is used.

    NICK-949: this signature is deliberately NOT widened with a `config`
    parameter (it is pinned by `test_tracker_persistence.py` and is the exact
    JSON-era shape). A caller that needs its project's OWN backend calls
    `load_tracker_for(config)` instead; this façade always uses
    `DEFAULT_BACKEND`.

    Raises `FileNotFoundError` when the project has not been migrated (no
    `project.md`), matching the JSON era's `open()`.

    FAILS LOUD ON CORRUPTION: a single malformed `plants/<ID>.md` (or
    `project.md`) makes this ENTIRE call raise -- there is no per-plant
    isolation, and no plant is silently skipped. See
    `markdown_backend.load_tracker` for why serving a partial roster would be
    unsafe (`save_tracker` would delete the skipped plant's file on the next
    observation).
    """
    return STORAGE_BACKENDS[DEFAULT_BACKEND].load_tracker(tracker_file)


def save_tracker(tracker, tracker_file):
    """Save a project's tracker to the DEFAULT backend (see load_tracker).

    Signature, argument order and `None` return are unchanged from the JSON
    era. Per-project routing lives in `save_tracker_for(tracker, config)`.
    """
    STORAGE_BACKENDS[DEFAULT_BACKEND].save_tracker(tracker, tracker_file)


def parse_observation(text):
    """Extract structured data from natural language observation.

    Shared across every project -- vigor/terpene/structure/status parsing
    has no per-cross variation.
    """
    observation = {
        'raw_text': text,
        'timestamp': datetime.now().isoformat(),
        'vigor': None,
        'terpenes': [],
        'structure': None,
        'notes': [],
        'status': None,
    }

    vigor_match = re.search(r'vigor\s*(?:is\s*)?(\d+)', text, re.IGNORECASE)
    if vigor_match:
        observation['vigor'] = int(vigor_match.group(1))

    for keyword in TERPENE_KEYWORDS:
        if re.search(rf'\b{keyword}\b', text, re.IGNORECASE):
            observation['terpenes'].append(keyword)

    for keyword in STRUCTURE_KEYWORDS:
        if re.search(rf'\b{keyword}', text, re.IGNORECASE):
            if not observation['structure']:
                observation['structure'] = []
            observation['structure'].append(keyword)

    # Status detection. Check top_keeper/culled before the plainer 'keeper'
    # pattern so phrases like "top keeper" or "elite" aren't also matched
    # as a bare 'keeper'.
    if re.search(r'\b(top keeper|strong keeper|elite)\b', text, re.IGNORECASE):
        observation['status'] = 'top_keeper'
    elif re.search(r'\b(cull|culled|toss|trash)\b', text, re.IGNORECASE):
        observation['status'] = 'culled'
    elif re.search(r'\b(keeper|keep|select)\b', text, re.IGNORECASE):
        observation['status'] = 'keeper'

    return observation


def make_blank_plant(plant_id, cross_name):
    """Fresh plant record for auto-create-on-first-mention projects
    (pheno hunts that start with an empty roster: Paloma Coma, Honey
    Badger Haze, Kibungan)."""
    return {
        'id': plant_id,
        'cross': cross_name,
        'status': 'active',
        'sex': None,
        'germ_date': None,
        'veg_start': None,
        'flower_flip': None,
        'harvest_date': None,
        'vigor': None,
        'structure': None,
        'terpene_notes': None,
        'issues': None,
        'selection_notes': None,
        'photos': [],
        'photo_count': 0,
        'photos_drive_url': '',
        'observation_log': '',
    }


def update_plant(plant_id, observation, config, photo_count=0):
    """Update tracker, markdown, dashboard, and GitHub for one plant.

    config is a dict with keys: BREEDING_DIR (Path), TRACKER_FILE (Path),
    GITHUB_REPO (str), DISABLE_GITHUB_PUSH (bool), CROSS_NAME (str),
    AUTO_CREATE (bool) -- True for empty-roster pheno hunts (Paloma Coma,
    Honey Badger Haze, Kibungan), False for doc-imported pre-populated
    rosters (Mule Fuel x Nana Glue, Lantz, Spaced Paste), where a missing
    plant ID is an error, not a new record.
    """
    tracker = load_tracker_for(config)

    plant = None
    for p in tracker['plants']:
        # p.get('id'), not p['id']: a hand-edited/corrupted plant file with no
        # id would otherwise raise an opaque KeyError('id') here, pre-empting
        # save_tracker's own informative "plant record has a missing or
        # non-string id" ValueError. Degrade gracefully so the useful error
        # is the one that surfaces.
        if p.get('id') == plant_id:
            plant = p
            break

    if not plant:
        if config.get('AUTO_CREATE'):
            plant = make_blank_plant(plant_id, config['CROSS_NAME'])
            tracker['plants'].append(plant)
        else:
            return f"\u274c Plant {plant_id} not found"

    if observation['vigor']:
        plant['vigor'] = observation['vigor']

    if observation['terpenes']:
        existing_terps = plant.get('terpene_notes', '') or ''
        new_terps = ', '.join(observation['terpenes'])
        plant['terpene_notes'] = f"{existing_terps}; {new_terps}".strip('; ')

    # Update status if the observation text contained a status keyword
    # (see parse_observation's status-detection block). This is the exact
    # line that was MISSING from Mule Fuel/Lantz/Spaced Paste pre-NICK-589.
    if observation.get('status'):
        plant['status'] = observation['status']

    log_entry = f"\n### {observation['timestamp']}\n{observation['raw_text']}\n"
    plant['observation_log'] = (plant.get('observation_log', '') or '') + log_entry

    # Note: photo_handler.process_photo() (called by the caller, if any
    # photos were attached) already appended entries to plant['photos'] and
    # saved the tracker -- we must NOT touch plant['photos'] here or we'd
    # double-write it.

    # save_tracker() writes plants/<ID>.md itself now (see update_markdown's
    # docstring for why the old, separate update_markdown() call that used to
    # sit here would immediately overwrite what save_tracker just wrote).
    # NICK-949: routed through this project's OWN backend, so a project rolled
    # back to JSON is loaded from and saved to tracker.json, not markdown.
    save_tracker_for(tracker, config)

    subprocess.run(['python3', str(config['BREEDING_DIR'] / 'generate_dashboard.py')],
                    cwd=config['BREEDING_DIR'], capture_output=True)

    push_to_github(config['BREEDING_DIR'], config['GITHUB_REPO'], config['DISABLE_GITHUB_PUSH'])

    summary_parts = []
    if observation['vigor']:
        summary_parts.append(f"vigor {observation['vigor']}")
    if observation['terpenes']:
        summary_parts.append(', '.join(observation['terpenes']) + ' terps')
    if observation['structure']:
        summary_parts.append(', '.join(observation['structure']))
    if photo_count:
        summary_parts.append(f"{photo_count} photo(s) uploaded")

    summary = ', '.join(summary_parts) if summary_parts else 'observation logged'
    return f"\u2713 {plant_id} updated: {summary}"


def update_markdown(plant, breeding_dir):
    """Refresh one plant's markdown record at ``plants/<ID>.md``.

    PHASE 2 / TASK 2.1 COLLISION FIX. In the JSON era this function wrote a
    *derived view*: ``tracker.json`` was the record of truth, and
    ``plants/<ID>.md`` was a regenerated human-readable report (minimal
    ``plant_id``/``cross``/``status`` frontmatter plus a rendered body).

    After the markdown migration ``plants/<ID>.md`` IS the record of truth --
    ``save_tracker()`` writes it through Phase 1's ``plant_markdown.write_plant``
    with full frontmatter. The old derived-view writer therefore collided with
    it: called right after ``save_tracker()`` it overwrote a 19-field plant
    with its own 3-key frontmatter, dropping ``id`` (spelled ``plant_id`` in
    the view), ``photos``, ``original_notes`` and everything else, so the next
    observation raised ``KeyError('id')``. Nothing regenerable was gained: the
    report was a strictly lossy projection of the record it clobbered.

    So the derived view is gone (option (c): it is now fully redundant with
    the backend record) and this function persists the plant record instead.
    The signature is unchanged because all six wrappers expose
    ``update_markdown(plant)`` verbatim. It is non-destructive: the supplied
    fields are merged over whatever is already on disk, so a partial dict can
    never truncate a stored plant. ``update_plant()`` no longer calls it --
    ``save_tracker()`` already wrote the file -- but a direct wrapper call is
    still safe and idempotent.
    """
    markdown_backend.save_plant(plant, breeding_dir)


# The only paths this function is allowed to stage: the markdown record of
# truth. Everything else in a live project dir (tracker.json, cache/,
# photo_staging/, __pycache__/, .save_tracker-staging-*) stays out of the
# data repo.
_DATA_PATHS = ('project.md', 'plants')


class _GitResult:
    """Stand-in for ``subprocess.CompletedProcess`` when the child process
    was never created at all (see ``_git``)."""

    __slots__ = ('returncode', 'stdout', 'stderr')

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _git(args, cwd, env=None):
    """One git command, never raising.

    Every call site here is best-effort: this runs inside the Discord message
    handler, so a git failure must degrade to a logged warning rather than an
    exception that kills the ingestion reply (and the bot).

    ``subprocess.run`` can fail BEFORE the child exists -- FileNotFoundError
    for a git binary that is not on PATH, or any other OSError (EACCES from
    an unexecutable git, ENOMEM under pressure). Those are converted into a
    synthetic non-zero result so that a single code path -- the caller's
    ``returncode`` check and its WARN logging -- handles both kinds of
    failure uniformly.
    """
    try:
        return subprocess.run(
            ['git', *args], cwd=str(cwd), capture_output=True, text=True,
            **({'env': env} if env is not None else {}),
        )
    except OSError as e:
        return _GitResult(1, '', f'could not run git: {e}')


def _warn(action, repo, result):
    """Operator-visible signal for a swallowed git failure.

    Same idiom as ``update_plant``'s failed-photo-upload warning: a
    ``WARN: ...`` line on stderr, inherited by all six wrappers and captured
    by ``hermes_gateway.py``'s logging. The argv is deliberately NOT echoed
    -- it is the one place a credential could re-enter a log line.
    """
    print(
        f"WARN: git {action} failed in {repo}: {(result.stderr or '').strip()}",
        file=sys.stderr,
    )


def _push_repo(repo, paths):
    """Stage ``paths``, commit if anything changed, push to ``origin``.

    Never raises: every git call is best-effort, exactly as in the JSON era,
    so a push failure cannot break the Discord ingestion reply.
    """
    if not (repo / '.git').exists():
        return

    added = _git(['add', '--all', '--', *paths], repo)
    if added.returncode != 0:
        _warn('add', repo, added)

    # rc 1 means "there are staged changes"; rc >= 128 means git itself is
    # broken (corrupt index, missing objects) and must NOT be misread as
    # "something to commit".
    if _git(['diff', '--cached', '--quiet'], repo).returncode == 1:
        committed = _git(
            ['commit', '-m',
             f'Auto-update from Discord observation {datetime.now().isoformat()}'],
            repo,
        )
        if committed.returncode != 0:
            _warn('commit', repo, committed)

    if 'origin' not in _git(['remote'], repo).stdout.split():
        return

    branch = _git(['rev-parse', '--abbrev-ref', 'HEAD'], repo).stdout.strip()
    if not branch or branch == 'HEAD':  # detached: no branch to push to
        return

    # Token resolved via 1Password at gateway startup -- see
    # `hermes secrets onepassword status`.
    #
    # The credential is handed to git through GIT_CONFIG_* ENVIRONMENT
    # variables rather than `-c http.extraHeader=...` argv flags: argv is
    # world-readable via /proc/<pid>/cmdline and `ps -ef` for the lifetime of
    # the push, while the environment is readable only by the same uid (or
    # root). See DECISIONS.md -- smaller surface, not zero.
    token = os.environ.get("GITHUB_TOKEN")
    auth_env = None
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        auth_env = {
            **os.environ,
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': 'http.extraHeader',
            'GIT_CONFIG_VALUE_0': f'Authorization: Basic {basic}',
        }

    pushed = _git(
        ['push', '-q', 'origin', f'HEAD:refs/heads/{branch}'], repo, env=auth_env
    )
    if pushed.returncode != 0:
        _warn('push', repo, pushed)


def push_to_github(breeding_dir, github_repo, disable_push):
    """Commit and push this project's MARKDOWN DATA REPO (and, for now, its
    legacy dashboard repo).

    PHASE 2 / TASK 2.3. Signature and best-effort, never-raising contract are
    unchanged from the JSON era; the target and the staging rule changed.

    * **New target.** `breeding_dir` itself is now a repo (`project.md` +
      `plants/<ID>.md`) -- the record of truth an observation actually
      mutates, which the new frontend renders via the data API.
    * **Transitional second target.** `breeding_dir/'dashboard'` is STILL
      pushed. Today all six live projects serve GitHub Pages from that repo
      and NONE of the project dirs is a git repo yet, so dropping it would
      silently freeze every live dashboard for the whole Phase 3-7 window.
      Each repo is handled independently, so a project in either shape (only
      `dashboard/` today, both mid-cutover, only the data repo after Task 7.3
      removes `dashboard/`) works with no code change. Delete the second call
      at Task 7.3.
    * **Staging.** `git add --all -- project.md plants` for the data repo, NOT
      `git add .`: a live project dir also holds `tracker.json`, `cache/`,
      `photo_staging/`, `__pycache__/` and `save_tracker`'s
      `.save_tracker-staging-*` scratch dirs, none of which belongs in the
      data repo. `--all` (rather than a plain path-limited add) is required so
      a plant DELETED from the roster -- `save_tracker` unlinks its file -- is
      committed as a deletion instead of lingering on the remote forever. The
      dashboard repo keeps its JSON-era whole-directory staging; it holds only
      generated HTML.
    * **Empty commits.** A `git commit` with nothing staged is skipped, so a
      no-op observation does not append a commit per Discord message.
    * **Push.** Always attempted when an `origin` exists, even when this call
      staged nothing: a previous run's commit may have been made while the
      remote was unreachable, and `git push` is a no-op when already current.
      This is Phase 1's push-stranding lesson (see `breeding-markdown`'s
      DECISIONS.md) applied here. `HEAD:refs/heads/<branch>` uses the repo's
      real branch, and a detached HEAD is refused rather than pushed to a junk
      `HEAD` branch -- also a Phase 1 lesson.

    `github_repo` is retained for signature compatibility (all six wrappers
    pass it) but no longer BUILDS a URL: each push goes to that repo's own
    `origin`. A `GITHUB_TOKEN` is supplied as an `http.extraHeader` via
    `GIT_CONFIG_*` environment variables instead of being interpolated into a
    remote URL or passed as a `-c` argv flag, so it never lands in
    `.git/config`, `git remote -v`, an error log, or a world-readable
    `/proc/<pid>/cmdline`. See DECISIONS.md for the residual exposure.

    NEVER RAISES. This runs inside the Discord message handler, so every git
    failure -- including an `OSError` from the exec itself -- is swallowed and
    reported as a `WARN: ...` line on stderr rather than propagated.
    """
    if disable_push:
        return

    repo = Path(breeding_dir)
    _push_repo(repo, _DATA_PATHS)
    _push_repo(repo / 'dashboard', ('.',))


def extract_plant_ids_single(message_text, pattern, prefix):
    """Single-prefix extraction (e.g. MG, Ltz, sp, PC, HBH)."""
    digit_groups = re.findall(pattern, message_text, re.IGNORECASE)
    return [f"{prefix}{int(d):02d}" for d in digit_groups]


def extract_plant_ids_registry(message_text, registry):
    """Multi-prefix extraction (Kibungan: PK + PL share one population).
    registry is a list of (prefix, compiled_regex) tuples. Preserves
    first-occurrence order and dedupes."""
    plant_ids = []
    for prefix, compiled in registry:
        for match in compiled.finditer(message_text):
            plant_id = f"{prefix}{int(match.group(1)):02d}"
            if plant_id not in plant_ids:
                plant_ids.append(plant_id)
    return plant_ids


# ---------------------------------------------------------------------------
# PROJECT ROUTING REGISTRY (Phase 2 / Task 2.5)
#
# Which projects exist, and which plant-ID prefix belongs to which, is knowledge
# encoded in CODE today, in TWO places -- neither of them this file:
#
#   1. `_CROSS_DIRS: dict[str, Path]` in the gateway plugin, at
#      `_shared/breeding-ingest/integrations/hermes-breeding-ingest/__init__.py`
#      (~lines 55-63). THAT is the real, live prefix -> project-directory
#      router in production; its own comment says adding a new cross requires
#      a line there.
#   2. `PLANT_ID_REGISTRY` in `_shared/breeding-ingest/breeding_tracker/
#      discord_ingest.py` (~line 25), the prefix -> regex table.
#
# ...plus a per-project `monitor_breeding_notes.py` wrapper, each of which
# hardcodes its own full CONFIG dict.
#
# So the finalized plan's premise was MISFILED, not wrong: a hardcoded
# `_CROSS_DIRS` really does exist and really is the coupling worth removing --
# it just lives in the gateway plugin repo, not in `breeding_core.py` as the
# plan assumed. See DECISIONS.md.
#
# Task 2.5 builds that routing table as DATA -- `registry.json` in the
# `breeding-meta` git repo -- and PROVES the mechanism: adding a project to it
# and pushing routes that project's prefix with no code change here, which is
# Task 2.5's acceptance criterion and is proven literally by
# tests/test_registry_routing.py.
#
# SCOPE: this is a proven REPLACEMENT CANDIDATE, not an adopted one. Nothing in
# production reads `registry.json` yet. Migrating the gateway's `_CROSS_DIRS`
# (and `PLANT_ID_REGISTRY`, and the wrapper-authoring step) onto it is separate,
# out-of-scope future work. The six live wrappers are deliberately NOT migrated;
# they keep working byte-identically off their own CONFIG dicts.
# ---------------------------------------------------------------------------

_DEFAULT_META_REPO = Path(__file__).resolve().parent.parent / "breeding-meta"

REGISTRY_FILENAME = "registry.json"
SUPPORTED_REGISTRY_SCHEMA = 1


def _meta_repo():
    """Locate the breeding-meta checkout.

    Defaults to the sibling checkout next to ``monitor-core`` (the layout in
    ``~/.hermes/breeding/_shared/``); ``BREEDING_META_DIR`` overrides it so a
    sandbox or a container can point elsewhere without a code change. Same
    precedent as ``markdown_backend``'s ``BREEDING_MARKDOWN_DIR`` (Task 2.1).
    """
    override = os.environ.get("BREEDING_META_DIR")
    return Path(override).expanduser() if override else _DEFAULT_META_REPO


def refresh_meta_repo():
    """``git pull`` the breeding-meta checkout. NEVER RAISES.

    Called before each ingestion run so a project added to ``registry.json``
    elsewhere is picked up without restarting the bot.

    This runs inside the Discord message handler, so the never-raise rule from
    ``push_to_github`` (Task 2.3) applies with full force: a registry that is
    merely STALE still routes every existing project correctly, so a failed
    pull must degrade to a ``WARN:`` line on stderr and let ingestion proceed
    off the last-known-good checkout. Losing an observation because GitHub was
    briefly unreachable would be strictly worse than routing on a registry
    that is a few minutes old.

    A missing checkout, a non-git directory, and a repo with no ``origin`` are
    all silent no-ops rather than warnings -- those are valid local
    configurations (the repo is local-only today), not failures.
    """
    repo = _meta_repo()
    if not (repo / '.git').exists():
        return

    remotes = _git(['remote'], repo)
    if remotes.returncode != 0:
        # git itself could not be run (missing binary, EACCES, ENOMEM). That
        # is a real fault worth surfacing, unlike the benign no-remote case
        # below -- but still not worth killing the ingestion reply over.
        _warn('pull', repo, remotes)
        return
    if 'origin' not in remotes.stdout.split():
        return

    pulled = _git(['pull', '--ff-only', '-q'], repo)
    if pulled.returncode != 0:
        _warn('pull', repo, pulled)


def _compile_prefixes(entry):
    """``[{prefix, pattern}, ...]`` -> ``[(prefix, compiled), ...]``.

    Compiled with ``re.IGNORECASE`` to match ``extract_plant_ids_single``,
    which passes that flag to ``re.findall``. Without it the multi-prefix path
    was case-SENSITIVE while the single-prefix path was not, so a two-prefix
    project silently failed to match ``xa05`` where a one-prefix project
    matched ``ya05`` fine. Kibungan's real patterns embed an inline ``(?i)``,
    which happened to hide the asymmetry in production; under this flag that
    inline group is merely redundant, never conflicting.
    """
    compiled = []
    for spec in entry.get('plant_id_prefixes') or []:
        try:
            compiled.append((spec['prefix'], re.compile(spec['pattern'], re.IGNORECASE)))
        except KeyError as exc:
            raise ValueError(
                f"{REGISTRY_FILENAME}: project {entry.get('slug')!r} has a "
                f"plant_id_prefixes entry missing {exc}"
            ) from exc
        except re.error as exc:
            raise ValueError(
                f"{REGISTRY_FILENAME}: project {entry.get('slug')!r} prefix "
                f"{spec.get('prefix')!r} has an invalid pattern: {exc}"
            ) from exc
    if not compiled:
        raise ValueError(
            f"{REGISTRY_FILENAME}: project {entry.get('slug')!r} declares no "
            "plant_id_prefixes, so no message could ever route to it"
        )
    return compiled


_DEFAULT_BREEDING_ROOT = Path.home() / ".hermes" / "breeding"


def _breeding_root():
    """The directory every project's ``breeding_dir`` must live under.

    ``~/.hermes/breeding/`` -- where all six real projects actually are.
    ``BREEDING_ROOT_DIR`` overrides it so a sandbox or container can point
    elsewhere without a code change, the same precedent as ``BREEDING_META_DIR``
    above and ``markdown_backend``'s ``BREEDING_MARKDOWN_DIR``.
    """
    override = os.environ.get("BREEDING_ROOT_DIR")
    return Path(override).expanduser() if override else _DEFAULT_BREEDING_ROOT


def _validated_breeding_dir(raw, slug, path):
    """Resolve and contain one entry's ``breeding_dir``.

    ``registry.json`` is trusted local data, but ``breeding_dir`` is the one
    field that becomes a WRITE TARGET (``save_tracker``,
    ``markdown_backend.save_plant``), so it is contained anyway: a typo'd or
    hostile entry like ``~/.hermes/../../../tmp/pwned`` or ``/etc`` must not be
    able to aim plant markdown at an arbitrary directory. The path is
    ``resolve()``d FIRST so ``..`` segments are collapsed and cannot smuggle an
    escape past the containment check. The root itself is rejected too -- it is
    the container of projects, not a project.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            f"{path}: project {slug!r} has no usable 'breeding_dir' "
            f"(got {raw!r}); every project must name the "
            "directory its tracker.json and plant markdown live in"
        )

    root = _breeding_root().expanduser().resolve()
    resolved = Path(raw).expanduser().resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(
            f"{path}: project {slug!r} has a 'breeding_dir' outside the "
            f"breeding tree: {raw!r} resolves to {resolved}, which is not "
            f"under {root}. Set BREEDING_ROOT_DIR if the tree really lives "
            "elsewhere."
        )
    return resolved


def _validate_registry(data, path):
    """Reject a registry that would route messages to the wrong project.

    Fails loud rather than fail-open, the same call this codebase made for
    corrupt plant markdown (see ``load_tracker``): silently dropping a
    malformed project would send its observations nowhere, and a duplicated
    prefix would send them to the WRONG cross -- both worse than an error.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{path}: {REGISTRY_FILENAME} must contain a JSON object")

    version = data.get('schema_version')
    if version != SUPPORTED_REGISTRY_SCHEMA:
        raise ValueError(
            f"{path}: {REGISTRY_FILENAME} schema_version {version!r} is not "
            f"supported (this code understands {SUPPORTED_REGISTRY_SCHEMA})"
        )

    projects = data.get('projects')
    if not isinstance(projects, list):
        raise ValueError(f"{path}: {REGISTRY_FILENAME} 'projects' must be a list")

    seen_slugs = set()
    seen_prefixes = {}
    for entry in projects:
        slug = entry.get('slug')
        if not slug:
            raise ValueError(f"{path}: a project entry has no 'slug'")
        if slug in seen_slugs:
            raise ValueError(f"{path}: duplicate project slug {slug!r}")
        seen_slugs.add(slug)

        # ``breeding_dir`` is required, and required LOUDLY here rather than
        # left to explode later as a bare KeyError inside config_for_project:
        # by then the traceback no longer says which project was malformed.
        # Blank/whitespace counts as missing -- an empty path silently resolves
        # to the process CWD, which would scatter a cross's plant markdown into
        # whatever directory the bot happened to start in. It is also CONTAINED
        # to the breeding root; see ``_validated_breeding_dir``.
        _validated_breeding_dir(entry.get('breeding_dir'), slug, path)

        # Prefix uniqueness is case-INSENSITIVE, because matching is: patterns
        # compile with re.IGNORECASE, so 'sp' and 'SP' are the same prefix and
        # a registry declaring both would route one message to two crosses.
        # (spaced-paste really does use a lowercase 'sp'.) Both original
        # spellings are named in the error so a human can see which two
        # entries actually collided.
        for prefix, _ in _compile_prefixes(entry):
            key = prefix.casefold()
            if key in seen_prefixes:
                other_prefix, other_slug = seen_prefixes[key]
                raise ValueError(
                    f"{path}: prefix {other_prefix!r} (project {other_slug!r}) "
                    f"and prefix {prefix!r} (project {slug!r}) are the same "
                    "prefix -- matching is case-insensitive, so a message "
                    "using it would route ambiguously"
                )
            seen_prefixes[key] = (prefix, slug)

    return data


def load_registry(pull=False):
    """Read ``registry.json`` from the breeding-meta checkout.

    ``pull=True`` refreshes the checkout first (best-effort, never fatal).
    Raises ``FileNotFoundError`` when the checkout is absent and ``ValueError``
    when the registry is malformed -- routing on a half-understood registry is
    not safe.
    """
    if pull:
        refresh_meta_repo()

    path = _meta_repo() / REGISTRY_FILENAME
    try:
        raw = path.read_text(encoding='utf-8')
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"no {REGISTRY_FILENAME} at {path}. Set the BREEDING_META_DIR "
            "environment variable to the breeding-meta checkout if it does "
            "not sit next to monitor-core."
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {REGISTRY_FILENAME} is not valid JSON: {exc}") from exc

    return _validate_registry(data, path)


def registry_entry(slug, registry=None):
    """One project's raw registry entry, by slug."""
    registry = registry if registry is not None else load_registry()
    for entry in registry['projects']:
        if entry.get('slug') == slug:
            return entry
    raise KeyError(f"no project {slug!r} in {REGISTRY_FILENAME}")


def config_for_project(entry):
    """Build the per-project ingestion ``config`` dict from a registry entry.

    Produces exactly the dict shape ``update_plant`` and ``process_message``
    already document and the six wrappers already hand-build -- BREEDING_DIR,
    TRACKER_FILE, GITHUB_REPO, DISABLE_GITHUB_PUSH, CROSS_NAME, AUTO_CREATE,
    BACKEND, plus either PLANT_ID_PATTERN + PLANT_ID_PREFIX (one prefix) or
    PLANT_ID_REGISTRY (two or more, as Kibungan's PK/PL). Nothing downstream
    can tell a registry-built config from a wrapper-built one.

    Two fields are DERIVED rather than stored, matching what every wrapper
    does today and keeping the registry free of redundant, driftable state:
    ``TRACKER_FILE`` is always ``BREEDING_DIR / 'tracker.json'``, and
    ``DISABLE_GITHUB_PUSH`` comes from the ``BREEDING_DISABLE_PUSH``
    environment variable -- it is a per-run operational switch (and the
    sandbox's safety catch), not a property of the project.
    """
    breeding_dir = Path(entry['breeding_dir']).expanduser()

    config = {
        'BREEDING_DIR': breeding_dir,
        'TRACKER_FILE': breeding_dir / 'tracker.json',
        'GITHUB_REPO': entry.get('github_repo'),
        'DISABLE_GITHUB_PUSH': os.environ.get('BREEDING_DISABLE_PUSH') == '1',
        'CROSS_NAME': entry.get('cross_name', entry['slug']),
        'AUTO_CREATE': bool(entry.get('auto_create')),
        # NICK-949: storage backend, per project. Absent from the registry
        # entry => markdown, the current behaviour for every live project.
        # Validated here rather than at first read so a bad name surfaces when
        # the config is built, not mid-ingestion.
        'BACKEND': backend_name({'BACKEND': entry.get('backend')}),
    }

    compiled = _compile_prefixes(entry)
    if len(compiled) == 1:
        prefix, pattern = entry['plant_id_prefixes'][0]['prefix'], \
                          entry['plant_id_prefixes'][0]['pattern']
        config['PLANT_ID_PATTERN'] = pattern
        config['PLANT_ID_PREFIX'] = prefix
    else:
        config['PLANT_ID_REGISTRY'] = compiled

    return config


def route_message(message_text, pull=True, registry=None):
    """Find every registry project whose prefixes appear in ``message_text``.

    Returns a list of ``{'slug', 'entry', 'config', 'plant_ids'}`` dicts, one
    per matching project, in registry order; ``[]`` when nothing matches.
    ``pull`` refreshes the breeding-meta checkout first so a newly added
    project routes on the very next message.

    This is the prefix -> project lookup that lives in production as the
    gateway plugin's hardcoded ``_CROSS_DIRS`` dict
    (``hermes-breeding-ingest/__init__.py``) combined with "which wrapper did
    the gateway happen to load". This function is the data-driven replacement
    CANDIDATE for that pair -- proven working, but not yet adopted by the
    gateway. A caller feeds the returned ``config`` straight to
    ``process_message``.
    """
    registry = registry if registry is not None else load_registry(pull=pull)

    routed = []
    for entry in registry['projects']:
        compiled = _compile_prefixes(entry)
        if len(compiled) == 1:
            spec = entry['plant_id_prefixes'][0]
            plant_ids = extract_plant_ids_single(
                message_text, spec['pattern'], spec['prefix']
            )
        else:
            plant_ids = extract_plant_ids_registry(message_text, compiled)

        if plant_ids:
            routed.append({
                'slug': entry['slug'],
                'entry': entry,
                'config': config_for_project(entry),
                'plant_ids': sorted(set(plant_ids)),
            })

    return routed


def process_message(message_text, config, attachments=None):
    """Process a Discord message for breeding observations.

    config additionally needs either:
      - PLANT_ID_PATTERN (str) + PLANT_ID_PREFIX (str), or
      - PLANT_ID_REGISTRY (list of (prefix, compiled_regex))
    """
    if config.get('PLANT_ID_REGISTRY'):
        plant_ids = extract_plant_ids_registry(message_text, config['PLANT_ID_REGISTRY'])
    else:
        plant_ids = extract_plant_ids_single(
            message_text, config['PLANT_ID_PATTERN'], config['PLANT_ID_PREFIX']
        )

    if not plant_ids:
        return None  # No plant IDs found, ignore message

    observation = parse_observation(message_text)

    results = []
    for plant_id in sorted(set(plant_ids)):  # dedupe, deterministic order
        photo_count = 0
        if attachments:
            import photo_handler
            for url in attachments:
                try:
                    photo_handler.process_photo(url, plant_id)
                    photo_count += 1
                except Exception as e:
                    print(f"WARN: photo upload failed for {plant_id}: {e}", file=sys.stderr)
        result = update_plant(plant_id, observation, config, photo_count=photo_count)
        results.append(result)

    return '\n'.join(results)
