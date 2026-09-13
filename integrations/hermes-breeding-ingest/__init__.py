"""Hermes plugin entry point for real-time breeding ingestion.

Repository root is now this project's OWN durable location
(~/.hermes/breeding/_shared/breeding-ingest), not an ephemeral Multica task
workspace. NICK-190: the previous version resolved
BREEDING_TRACKER_REPOSITORY_ROOT to a path under
~/multica_workspaces/<...>/workdir/repo, which is a per-task sandbox that
gets garbage-collected once its originating Multica task is closed. When
that happened, `breeding_tracker` module imports here started failing
(`RuntimeError: Breeding tracker repository could not be located`), and
`hermes plugins doctor breeding-channel-ingest` silently reported 0 hooks
registered -- i.e. ALL real-time #breeding ingestion (MG##/Ltz##/sp##) had
been dead with no alert since the workspace was cleaned up. Never point
this plugin at a Multica task workspace again; it must live somewhere that
outlives any single task.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# This file lives at <repo>/integrations/hermes-breeding-ingest/__init__.py,
# so the repo root is two parents up. BREEDING_TRACKER_REPOSITORY_ROOT is
# still honored as an override for local dev/testing, but the on-disk
# location relative to this file is authoritative and durable.
_REPOSITORY_ROOT = Path(
    os.environ.get("BREEDING_TRACKER_REPOSITORY_ROOT")
    or Path(__file__).resolve().parents[2]
).expanduser()
if not (_REPOSITORY_ROOT / "breeding_tracker" / "discord_ingest.py").is_file():
    raise RuntimeError(
        f"Breeding tracker repository could not be located at {_REPOSITORY_ROOT}"
    )
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from breeding_tracker.discord_ingest import IngestStore
from breeding_tracker.hermes_gateway import BREEDING_CHANNEL_ID, create_gateway_hook

# Registry of every cross sharing the #breeding channel. Each entry maps a
# plant-ID prefix (as emitted by breeding_tracker.discord_ingest.extract_plant_ids,
# which is itself the single source of truth for recognized prefixes -- see
# PLANT_ID_REGISTRY there) to that cross's own BREEDING_DIR, where its
# monitor_breeding_notes.py / tracker.json / dashboard live.
#
# Adding a new cross: (1) add its prefix+regex to PLANT_ID_REGISTRY in
# discord_ingest.py, (2) scaffold its BREEDING_DIR from an existing cross's
# monitor_breeding_notes.py the same way Lantz/Spaced Paste/Paloma Coma were
# built, (3) add one line here. No other gateway/plugin code changes needed.
_CROSS_DIRS: dict[str, Path] = {
    "MG": Path.home() / ".hermes" / "breeding" / "mule-fuel-x-nana-glue",
    "LTZ": Path.home() / ".hermes" / "breeding" / "lantz",
    "SP": Path.home() / ".hermes" / "breeding" / "spaced-paste",
    "PC": Path.home() / ".hermes" / "breeding" / "paloma-coma",
    "HBH": Path.home() / ".hermes" / "breeding" / "honey-badger-haze-pheno-hunt",
    "PK": Path.home() / ".hermes" / "breeding" / "kibungan-pheno-hunt",
    "PL": Path.home() / ".hermes" / "breeding" / "kibungan-pheno-hunt",
    "MOG": Path.home() / ".hermes" / "breeding" / "marshmallow-og-pheno-hunt",
    "PP": Path.home() / ".hermes" / "breeding" / "pink-perfume-pheno-hunt",
    "MSU": Path.home() / ".hermes" / "breeding" / "ms-universe-pheno-hunt",
}

# Short SPOKEN aliases for the NICK-979 deterministic cross-name gate below.
#
# Deliberately NOT each project's full tracker.json cross_name: two real
# projects both genuinely contain the substring "Nana Glue" --
# "Mule Fuel x Nana Glue" and "Spaced Paste (Dulce de Uva x Nana Glue)" --
# so a naive full-cross_name match would treat any mention of "Nana Glue"
# alone as matching (or ambiguously co-matching) the wrong project. Each
# alias here is the short name a person would actually SAY out loud
# ("Mule Fuel", "Spaced Paste", "Honey Badger Haze", "Kibungan", "Paloma
# Coma", "Lantz") -- distinct, unambiguous substrings of their full names.
# Keyed by _CROSS_DIRS prefix (PL intentionally omitted: Kibungan's second
# prefix for the same project as PK, already covered by "PK"'s alias).
CROSS_ALIASES: dict[str, str] = {
    "MG": "mule fuel",
    "LTZ": "lantz",
    "SP": "spaced paste",
    "PC": "paloma coma",
    "HBH": "honey badger haze",
    "PK": "kibungan",
    "MOG": "marshmallow",
    "PP": "pink perfume",
    "MSU": "ms universe",
}


def _prefix_for_plant_id(plant_id: str) -> str | None:
    """Longest-prefix match against _CROSS_DIRS keys (handles 'LTZ' vs future
    ambiguous short prefixes safely, though none currently collide)."""
    for prefix in sorted(_CROSS_DIRS, key=len, reverse=True):
        if plant_id.startswith(prefix):
            return prefix
    return None


def _load_registry_for_routing() -> dict:
    """Read ``registry.json`` fresh, for the NICK-924 routing-cutover gate.

    A thin, standalone wrapper (does NOT reuse ``breeding_core.load_registry``
    -- that function pulls the meta repo AND full-validates every project's
    backend/prefixes, both unnecessary and unsafe here: the gateway hot path
    must be cheap and must never let a validation error in an UNRELATED
    project's registry entry take down routing for every cross. Any read or
    parse failure propagates to the caller, which treats it as "not
    migrated" and falls back to the hardcoded dict -- see
    ``_resolve_breeding_dir``.
    """
    import json as _json

    meta_repo = Path.home() / ".hermes" / "breeding" / "_shared" / "breeding-meta"
    registry_path = meta_repo / "registry.json"
    return _json.loads(registry_path.read_text(encoding="utf-8"))


def _resolve_breeding_dir(prefix: str) -> Path | None:
    """The per-project breeding_dir for ``prefix``, honouring a per-project,
    independently-rollbackable cutover to registry.json-driven routing
    (NICK-924 / Task 7.2b).

    CONTRACT: registry.json's ``routing_active: true`` on a project's entry
    is the ONLY thing that makes this function prefer that project's
    registry-declared ``breeding_dir`` over the hardcoded ``_CROSS_DIRS``
    dict. Everything else -- entry absent, ``routing_active`` absent or
    false, or ANY failure reading/parsing registry.json at all -- falls back
    to ``_CROSS_DIRS`` unconditionally. That fallback is the existing, live,
    proven-correct behavior; nothing about this function can make routing
    WORSE than it already was, only opt a specific project IN.

    This directly satisfies NICK-924 acceptance criterion (b): reverting one
    project's cutover is a single ``routing_active`` edit in registry.json,
    with no code change and zero effect on any other project's routing,
    because the fallback path IS the original, untouched ``_CROSS_DIRS``
    entry for every prefix that is not explicitly opted in.
    """
    try:
        registry = _load_registry_for_routing()
    except Exception:
        logger.warning(
            "breeding-channel-ingest: could not read registry.json for "
            "routing-cutover check (prefix %r) -- falling back to the "
            "hardcoded _CROSS_DIRS path, which is always safe",
            prefix,
            exc_info=True,
        )
        return _CROSS_DIRS.get(prefix)

    for entry in registry.get("projects", []):
        if not entry.get("routing_active"):
            continue
        for spec in entry.get("plant_id_prefixes") or []:
            if spec.get("prefix") == prefix:
                breeding_dir = entry.get("breeding_dir")
                if not breeding_dir:
                    logger.warning(
                        "breeding-channel-ingest: project %r has "
                        "routing_active=true but no breeding_dir -- "
                        "falling back to _CROSS_DIRS for prefix %r",
                        entry.get("slug"),
                        prefix,
                    )
                    return _CROSS_DIRS.get(prefix)
                return Path(breeding_dir).expanduser()

    return _CROSS_DIRS.get(prefix)


def _transcribe_audio(path: str):
    from tools.transcription_tools import transcribe_audio

    return transcribe_audio(path)


def _update_master_dashboard() -> None:
    """Regenerate and push the master dashboard aggregating every project.

    Best-effort, exactly like each cross's own push_to_github(): a failure
    here must never affect the per-cross ingestion result or block the
    gateway response, since the per-cross update already succeeded and is
    the source of truth. The master dashboard is a read-only aggregation
    over every project's tracker.json (see manifest.json in the same repo
    directory) -- adding a NEW project to it later only requires one entry
    in manifest.json, not a code change here.
    """
    master_dir = Path.home() / ".hermes" / "breeding" / "_shared" / "master-dashboard"
    script = master_dir / "generate_master_dashboard.py"
    if not script.is_file():
        return
    try:
        import subprocess

        env = os.environ.copy()
        env["MASTER_DASHBOARD_DIR"] = str(master_dir)
        subprocess.run(
            ["python3", str(script)], cwd=master_dir, env=env, capture_output=True, timeout=30
        )
        dashboard_dir = master_dir / "dashboard"
        subprocess.run(["git", "add", "-A"], cwd=dashboard_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Auto-update master dashboard from breeding observation"],
            cwd=dashboard_dir,
            capture_output=True,
        )
        # GITHUB_TOKEN resolved via 1Password at gateway startup — see
        # `hermes secrets onepassword status`
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            subprocess.run(
                [
                    "git",
                    "push",
                    f"https://{token}@github.com/joeydouglas/high-priestess-breeding.git",
                    "main",
                ],
                cwd=dashboard_dir,
                capture_output=True,
            )
    except Exception:
        logger.exception(
            "breeding-channel-ingest: master dashboard update failed "
            "(per-cross update already succeeded and is unaffected)"
        )


def _make_dashboard_processor():
    """Build the processor that turns a stored observation into a dashboard
    update, by calling monitor_breeding_notes.process_message() in-process,
    once per cross touched by the message's plant IDs.

    Deterministic script call, zero LLM/provider calls per message -- this is
    the same fix pattern as the --no-agent cron conversion in NICK-11, which
    resolved a real rate-limit incident caused by spending a provider call
    per tick just to decide whether to run a deterministic script.

    Photo attachments ARE wired here (NICK-9): media_urls, as passed in by
    hermes_gateway.py's _discord_image_attachment_urls(), are real Discord
    CDN URLs (read from the raw discord.Message's .attachments, not the
    locally-cached paths in event.media_urls) -- exactly the shape
    monitor_breeding_notes.process_message()'s attachment path already
    expects from the DiscordChatExporter replay path, so no separate
    download/upload code is needed here.

    Multi-cross routing (NICK-190): a single #breeding message can only
    reasonably belong to one cross in practice (users write "PC4 ..." or
    "MG15 ..."), but a message COULD technically mention IDs from more than
    one cross's prefix set. Each matching cross's own process_message() is
    invoked independently and in isolation (own sys.path entry, own
    BREEDING_DIR env, own import) so one cross's script bug can never break
    ingestion for another cross.
    """

    def _run_for_cross(
        prefix: str, content: str, media_urls: list[str], plant_ids: list[str]
    ) -> str | None:
        # NICK-924 / Task 7.2b: per-project, independently-rollbackable cutover
        # to registry.json-driven routing. Falls back to _CROSS_DIRS for every
        # prefix not explicitly opted in (registry.json's routing_active) --
        # see _resolve_breeding_dir's own docstring for the full contract.
        breeding_dir = _resolve_breeding_dir(prefix)
        if breeding_dir is None:
            logger.error(
                "breeding-channel-ingest: no known breeding_dir for prefix "
                "%r (not in _CROSS_DIRS and no registry.json cutover active) "
                "-- observation stored but not processed",
                prefix,
            )
            return None
        if not (breeding_dir / "monitor_breeding_notes.py").is_file():
            logger.error(
                "breeding-channel-ingest: no monitor_breeding_notes.py for "
                "prefix %r at %s -- observation stored but not processed",
                prefix,
                breeding_dir,
            )
            return None
        # process_message() (in every cross's monitor_breeding_notes.py)
        # re-derives plant IDs from raw text with its OWN regex -- it has
        # no notion of plant_ids resolved upstream (regex match or the
        # spoken-ID fallback, NICK-305). Prepend the already-resolved IDs
        # as literal tokens so that regex catches them too; this is a
        # no-op when the ID was already a literal regex match (the script
        # dedupes with a set()) and is the only way a spoken-language
        # resolution (e.g. "number seven" -> PC07) actually reaches the
        # tracker instead of being silently re-dropped by process_message's
        # own independent extraction.
        prefixed_ids = [pid for pid in plant_ids if pid.startswith(prefix)]
        augmented_content = (
            " ".join(prefixed_ids) + " " + content if prefixed_ids else content
        )
        module_dir = str(breeding_dir)
        added_to_path = module_dir not in sys.path
        if added_to_path:
            sys.path.insert(0, module_dir)
        previous_breeding_dir = os.environ.get("BREEDING_DIR")
        os.environ["BREEDING_DIR"] = module_dir
        try:
            import importlib

            import monitor_breeding_notes

            # Force a fresh import bound to this cross's BREEDING_DIR: Python
            # caches modules by name, and every cross's script is literally
            # named monitor_breeding_notes.py, so a cached import from a
            # PRIOR cross in this same process would silently write into the
            # wrong tracker.json. Reload after each sys.path swap.
            monitor_breeding_notes = importlib.reload(monitor_breeding_notes)
            result = monitor_breeding_notes.process_message(
                augmented_content, attachments=media_urls or None
            )
            if result:
                logger.info("breeding-channel-ingest[%s]: %s", prefix, result)
            return result or None
        finally:
            if added_to_path:
                try:
                    sys.path.remove(module_dir)
                except ValueError:
                    pass
            if previous_breeding_dir is None:
                os.environ.pop("BREEDING_DIR", None)
            else:
                os.environ["BREEDING_DIR"] = previous_breeding_dir

    def _processor(content: str, media_urls: list[str], plant_ids: list[str]) -> list[str]:
        prefixes_seen: set[str] = set()
        for plant_id in plant_ids:
            prefix = _prefix_for_plant_id(plant_id)
            if prefix is None:
                logger.warning(
                    "breeding-channel-ingest: plant ID %r matched no known "
                    "cross prefix in _CROSS_DIRS -- observation stored but "
                    "not processed",
                    plant_id,
                )
                continue
            prefixes_seen.add(prefix)
        processing_results: list[str] = []
        for prefix in prefixes_seen:
            result = _run_for_cross(prefix, content, media_urls, plant_ids)
            if result:
                processing_results.append(result)
        if prefixes_seen:
            _update_master_dashboard()
        return processing_results

    return _processor


def _known_plant_ids() -> dict[str, tuple[str, list[str]]]:
    """Return {prefix: (cross_name, [known plant IDs])} read from each
    cross's tracker.json, so the spoken-ID resolver can only ever return an
    ID that genuinely exists -- never an invented one -- and can require
    the transcript to actually reference that cross by name."""
    import json

    result: dict[str, tuple[str, list[str]]] = {}
    for prefix, breeding_dir in _CROSS_DIRS.items():
        tracker_path = breeding_dir / "tracker.json"
        if not tracker_path.is_file():
            continue
        try:
            data = json.loads(tracker_path.read_text(encoding="utf-8"))
            plants = data.get("plants", [])
            ids = sorted({p["id"] for p in plants if isinstance(p, dict) and p.get("id")})
            cross_name = data.get("cross_name") or prefix
            if ids:
                result[prefix] = (cross_name, ids)
        except Exception:
            logger.exception(
                "breeding-channel-ingest: could not read tracker.json for "
                "prefix %r at %s -- spoken-ID resolver will skip this cross",
                prefix,
                breeding_dir,
            )
    return result


def _mentions_known_cross(text: str, known: dict[str, tuple[str, list[str]]]) -> list[str]:
    """Deterministic (LLM-free) gate for the NICK-979 spoken-ID fallback.

    Returns every prefix in ``known`` whose short spoken alias
    (``CROSS_ALIASES``, NOT the full ``tracker.json`` cross_name -- see that
    dict's docstring for why) appears in ``text`` as a case-insensitive,
    word-bounded substring. This exists to run BEFORE any LLM call: the
    resolver below only ever invokes Ollama when this returns exactly one
    prefix. Zero or 2+ matches must short-circuit to "no ID" without
    touching the model at all -- that is the actual NICK-979 fix, not a
    prompt tweak. A model asked to disambiguate is still a model that can
    hallucinate a cross with zero textual evidence for it (reproduced live:
    "Totally keeping number seven." resolved to PC07 100% of 5 runs with the
    prompt-only version of this fix); a transcript that never reaches the
    model cannot.
    """
    import re as _re

    matches = []
    for prefix in known:
        alias = CROSS_ALIASES.get(prefix)
        if not alias:
            continue
        pattern = r"(?<![A-Za-z])" + _re.escape(alias) + r"(?![A-Za-z])"
        if _re.search(pattern, text, flags=_re.IGNORECASE):
            matches.append(prefix)
    return matches


def _make_spoken_id_resolver():
    """Build the scoped local-LLM fallback (NICK-305) used ONLY when the
    deterministic regex finds zero literal plant IDs in a breeding-channel
    message. Calls the local Qwen3.8-27B IQ4 model via Ollama, using the
    two-GPU local service. It makes no network egress or metered API call and
    fires only on the rare zero-literal-ID path.

    Design note (found in local sandbox testing before this ever touched a
    real message): an EARLIER version of this prompted each cross
    independently with only that cross's own plant-number list. Since plant
    numbers like "07" exist in EVERY cross, that returned a false-positive
    match for all 5+ crosses simultaneously on ambiguous input like "number
    seven" with no cross name attached -- it would have silently written the
    same observation into every cross's tracker.json. Fixed by making this
    ONE call across all crosses at once, giving the model each cross's real
    name (e.g. "Paloma Coma") alongside its ID list, and requiring the
    transcript to explicitly name (or unambiguously imply) exactly one
    cross before any ID is accepted. Every candidate is still re-validated
    against that specific cross's real known-ID list before use.
    """
    import json as _json
    import urllib.request

    OLLAMA_URL = os.environ.get(
        "BREEDING_OLLAMA_URL", "http://127.0.0.1:11434/api/generate"
    )
    OLLAMA_MODEL = os.environ.get(
        "BREEDING_OLLAMA_MODEL", "qwen3.8-27b-64k"
    )

    def _resolve(content: str) -> list[str]:
        known = _known_plant_ids()
        if not known:
            return []

        # NICK-979 deterministic gate: only call the LLM when EXACTLY ONE
        # cross's short spoken alias appears in the transcript. Zero matches
        # means no cross was named -- safe to drop, not safe to guess.
        # Two-plus matches means genuinely ambiguous input (e.g. two crosses
        # both mentioned) -- also not safe to let the model pick one. See
        # _mentions_known_cross's docstring for the reproduced bug this
        # closes structurally rather than by prompt wording alone.
        named = _mentions_known_cross(content, known)
        if len(named) != 1:
            if len(named) > 1:
                logger.warning(
                    "breeding-channel-ingest: spoken-ID resolver skipped -- "
                    "transcript named %d crosses ambiguously (%r): %r",
                    len(named),
                    named,
                    content[:200],
                )
            return []
        named_prefix = named[0]

        crosses_block = "\n".join(
            f'- Cross name: "{cross_name}" (prefix {prefix}) -- known plant IDs: '
            f"{', '.join(ids)}"
            for prefix, (cross_name, ids) in sorted(known.items())
        )
        prompt = (
            "You are extracting a plant ID from a single breeding-log voice "
            "transcript. Multiple breeding crosses share the same Discord "
            "channel, so plant numbers repeat across crosses -- you MUST "
            "identify which cross the transcript is about before choosing "
            "an ID; never guess an ID without a confident cross match.\n\n"
            f"Known crosses:\n{crosses_block}\n\n"
            "Speakers refer to plants by spoken number (e.g. 'number seven' "
            "means the ID ending in 07) and usually say the cross name "
            "explicitly (e.g. 'Paloma Coma, number seven'). Return ONLY a "
            'JSON object like {"cross_prefix": "PC", "plant_id": "PC07"} '
            "using the prefix and one of that cross's known IDs verbatim, "
            'or {"cross_prefix": null, "plant_id": null} if the cross is '
            "not clearly and unambiguously named or implied. No other "
            f"text.\n\nTranscript: {content!r}"
        )
        body = _json.dumps(
            {
                "model": OLLAMA_MODEL,
                "stream": False,
                "prompt": prompt,
                "format": "json",
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            # 180s covers the measured cold Qwen3.8-27B load (~99s) plus
            # inference time. Failures remain safe no-ops in the gateway hook;
            # valid spoken IDs are worth waiting for on this rare path.
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = _json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.exception(
                "breeding-channel-ingest: spoken-ID resolver request to "
                "Ollama failed"
            )
            return []
        raw = payload.get("response", "")
        try:
            parsed = _json.loads(raw)
        except Exception:
            logger.warning(
                "breeding-channel-ingest: spoken-ID resolver got non-JSON "
                "response: %r",
                raw[:200],
            )
            return []
        if not isinstance(parsed, dict):
            return []
        prefix = parsed.get("cross_prefix")
        candidate = parsed.get("plant_id")
        if not isinstance(prefix, str) or not isinstance(candidate, str):
            return []
        # NICK-979 belt-and-suspenders: even though exactly one cross was
        # deterministically named, an LLM answer for a DIFFERENT cross must
        # still be rejected rather than trusted -- the gate above narrows
        # what the model is ASKED, this narrows what its ANSWER is allowed
        # to be.
        if prefix != named_prefix:
            logger.warning(
                "breeding-channel-ingest: spoken-ID resolver rejected -- "
                "transcript named cross %r but model answered %r: %r",
                named_prefix,
                prefix,
                content[:200],
            )
            return []
        cross_entry = known.get(prefix)
        if cross_entry is None or candidate not in cross_entry[1]:
            logger.warning(
                "breeding-channel-ingest: spoken-ID resolver proposed "
                "out-of-range candidate %r for prefix %r -- rejected",
                candidate,
                prefix,
            )
            return []
        return [candidate]

    return _resolve


def register(ctx):
    database_path = _REPOSITORY_ROOT / "var" / "discord-ingest.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    store = IngestStore(database_path, BREEDING_CHANNEL_ID)
    ctx.register_hook(
        "pre_gateway_dispatch",
        create_gateway_hook(
            store=store,
            transcriber=_transcribe_audio,
            processor=_make_dashboard_processor(),
            spoken_id_resolver=_make_spoken_id_resolver(),
        ),
    )
