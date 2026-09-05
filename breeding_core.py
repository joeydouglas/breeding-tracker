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

import os
import re
import subprocess
import sys
from datetime import datetime

import markdown_backend

TERPENE_KEYWORDS = ['fuel', 'gas', 'citrus', 'fruity', 'sweet', 'earthy', 'pine', 'skunky', 'diesel']
STRUCTURE_KEYWORDS = ['frosty', 'dense', 'sandy', 'sticky', 'purple', 'tight', 'fox.*tail', 'stretch']


def load_tracker(tracker_file):
    """Load a project's tracker.

    PHASE 2 / TASK 2.1: the on-disk format is now markdown -- `project.md`
    plus `plants/<ID>.md` in `tracker_file`'s parent directory -- not
    `tracker.json`. The SIGNATURE and the returned data shape are unchanged,
    so every per-project `monitor_breeding_notes.py` wrapper keeps calling
    `core.load_tracker(TRACKER_FILE)` with no edit at all. `tracker_file`
    itself is no longer read; only its parent directory is used.
    """
    return markdown_backend.load_tracker(tracker_file)


def save_tracker(tracker, tracker_file):
    """Save a project's tracker to markdown (see load_tracker for the format).

    Signature, argument order and `None` return are unchanged from the JSON
    era; only the persistence backend differs.
    """
    markdown_backend.save_tracker(tracker, tracker_file)


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
    tracker = load_tracker(config['TRACKER_FILE'])

    plant = None
    for p in tracker['plants']:
        if p['id'] == plant_id:
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

    save_tracker(tracker, config['TRACKER_FILE'])
    update_markdown(plant, config['BREEDING_DIR'])

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
    """Write the plant's markdown file."""
    plant_id = plant['id']
    md_file = breeding_dir / 'plants' / f"{plant_id}.md"

    photo_count = len(plant.get('photos', []))
    drive_url = plant.get('photos_drive_url', '')

    content = f"""---
plant_id: {plant_id}
cross: {plant['cross']}
status: {plant['status']}
---

# {plant_id}

## Status
**{plant['status'].title()}**

## Photos
{photo_count} photos uploaded to [Google Drive]({drive_url})

## Observations

{plant.get('observation_log', '')}

## Timeline

| Date | Event |
|------|-------|
| TBD  | Observations to be added |
"""

    md_file.parent.mkdir(parents=True, exist_ok=True)
    with open(md_file, 'w') as f:
        f.write(content)


def push_to_github(breeding_dir, github_repo, disable_push):
    """Commit and push dashboard changes."""
    if disable_push:
        return
    dashboard_dir = breeding_dir / 'dashboard'

    subprocess.run(['git', 'add', '.'], cwd=dashboard_dir, capture_output=True)
    subprocess.run(['git', 'commit', '-m', f'Auto-update from Discord observation {datetime.now().isoformat()}'],
                    cwd=dashboard_dir, capture_output=True)

    # Token resolved via 1Password at gateway startup -- see
    # `hermes secrets onepassword status`.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        subprocess.run(
            ['git', 'push', f'https://{token}@github.com/{github_repo}.git', 'main'],
            cwd=dashboard_dir, capture_output=True
        )


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
