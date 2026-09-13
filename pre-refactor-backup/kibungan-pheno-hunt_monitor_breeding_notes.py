#!/usr/bin/env python3
"""
Monitor Discord #breeding thread for plant observations.
Processes voice transcriptions, parses notes, updates all systems.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BREEDING_DIR = Path(os.environ.get('BREEDING_DIR') or (Path.home() / '.hermes' / 'breeding' / 'kibungan-pheno-hunt'))
TRACKER_FILE = BREEDING_DIR / 'tracker.json'
LAST_PROCESSED_FILE = BREEDING_DIR / '.last_processed_message'
DISABLE_GITHUB_PUSH = os.environ.get('BREEDING_DISABLE_PUSH') == '1'
GITHUB_REPO = os.environ.get('BREEDING_GITHUB_REPO', 'joeydouglas/kibungan-pheno-hunt')

# Kibungan is a single Filipino landrace population, but the source doc uses
# TWO plant-ID prefixes (PK and PL -- likely two separate seed packs/batches
# of the same landrace). Match both; each entry is (prefix, compiled regex),
# same pattern as the shared multi-cross plugin's PLANT_ID_REGISTRY. Tolerant
# of voice-transcription artifacts: "PK27", "PK 27", "pk-27", "PK5" (single
# digit, zero-padded) all match. 3+ digit runs (e.g. "PK150") are correctly
# rejected by the trailing \b.
PLANT_ID_REGISTRY = [
    ('PK', re.compile(r'(?i)(?<![A-Z0-9])PK\s*[-#]?\s*0*(\d{1,3})(?!\d)')),
    ('PL', re.compile(r'(?i)(?<![A-Z0-9])PL\s*[-#]?\s*0*(\d{1,3})(?!\d)')),
]

def load_tracker():
    with open(TRACKER_FILE) as f:
        return json.load(f)

def save_tracker(tracker):
    with open(TRACKER_FILE, 'w') as f:
        json.dump(tracker, f, indent=2)

def parse_observation(text):
    """Extract structured data from natural language observation."""
    observation = {
        'raw_text': text,
        'timestamp': datetime.now().isoformat(),
        'vigor': None,
        'terpenes': [],
        'structure': None,
        'notes': []
    }
    
    # Vigor rating (0-10)
    vigor_match = re.search(r'vigor\s*(?:is\s*)?(\d+)', text, re.IGNORECASE)
    if vigor_match:
        observation['vigor'] = int(vigor_match.group(1))
    
    # Terpene notes
    terp_keywords = ['fuel', 'gas', 'citrus', 'fruity', 'sweet', 'earthy', 'pine', 'skunky', 'diesel']
    for keyword in terp_keywords:
        if re.search(rf'\b{keyword}\b', text, re.IGNORECASE):
            observation['terpenes'].append(keyword)
    
    # Structure/appearance
    structure_keywords = ['frosty', 'dense', 'sandy', 'sticky', 'purple', 'tight', 'fox.*tail', 'stretch']
    for keyword in structure_keywords:
        if re.search(rf'\b{keyword}', text, re.IGNORECASE):
            if not observation['structure']:
                observation['structure'] = []
            observation['structure'].append(keyword)
    
    # Status detection (same pattern as Paloma Coma). Check top_keeper/culled
    # before the plainer 'keeper' pattern so phrases like "top keeper" or
    # "elite" aren't also matched as a bare 'keeper'.
    if re.search(r'\b(top keeper|strong keeper|elite)\b', text, re.IGNORECASE):
        observation['status'] = 'top_keeper'
    elif re.search(r'\b(cull|culled|toss|trash)\b', text, re.IGNORECASE):
        observation['status'] = 'culled'
    elif re.search(r'\b(keeper|keep|select)\b', text, re.IGNORECASE):
        observation['status'] = 'keeper'
    
    return observation

def update_plant(plant_id, observation, photo_count=0):
    """Update tracker, markdown, sheet, dashboard, and GitHub."""
    tracker = load_tracker()
    
    # Find plant
    plant = None
    for p in tracker['plants']:
        if p['id'] == plant_id:
            plant = p
            break
    
    # Auto-create the plant record on first mention. This is a pheno hunt
    # starting with an EMPTY roster (plants: []) and observations are the
    # only way plants get added, so we must create a fresh record here
    # instead of failing (same pattern as Paloma Coma's monitor_breeding_notes.py).
    if not plant:
        plant = {
            'id': plant_id,
            'cross': 'Kibungan',
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
            'observation_log': ''
        }
        tracker['plants'].append(plant)
    
    # Update vigor if provided
    if observation['vigor']:
        plant['vigor'] = observation['vigor']
    
    # Update terpene notes
    if observation['terpenes']:
        existing_terps = plant.get('terpene_notes', '') or ''
        new_terps = ', '.join(observation['terpenes'])
        plant['terpene_notes'] = f"{existing_terps}; {new_terps}".strip('; ')
    
    # Update status if the observation text contained a status keyword
    # (see parse_observation's status-detection block).
    if observation.get('status'):
        plant['status'] = observation['status']
    
    # Append to observation log
    log_entry = f"\n### {observation['timestamp']}\n{observation['raw_text']}\n"
    plant['observation_log'] = (plant.get('observation_log', '') or '') + log_entry
    
    # Note: photo_handler.process_photo() (called by the caller, if any photos
    # were attached) already appended entries to plant['photos'] and saved the
    # tracker -- we must NOT touch plant['photos'] here or we'd double-write it.
    
    # Save tracker
    save_tracker(tracker)
    
    # Update markdown
    update_markdown(plant)
    
    # Regenerate dashboard
    subprocess.run(['python3', str(BREEDING_DIR / 'generate_dashboard.py')], 
                   cwd=BREEDING_DIR, capture_output=True)
    
    # Push to GitHub
    push_to_github()
    
    # Build summary
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
    return f"✓ {plant_id} updated: {summary}"

def update_markdown(plant):
    """Update the plant's markdown file."""
    plant_id = plant['id']
    md_file = BREEDING_DIR / 'plants' / f"{plant_id}.md"
    
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
    
    with open(md_file, 'w') as f:
        f.write(content)

def push_to_github():
    """Commit and push dashboard changes."""
    if DISABLE_GITHUB_PUSH:
        return
    dashboard_dir = BREEDING_DIR / 'dashboard'
    
    # Git add, commit, push
    subprocess.run(['git', 'add', '.'], cwd=dashboard_dir, capture_output=True)
    subprocess.run(['git', 'commit', '-m', f'Auto-update from Discord observation {datetime.now().isoformat()}'], 
                   cwd=dashboard_dir, capture_output=True)
    
    # Get token and push (GITHUB_TOKEN resolved via 1Password at gateway
    # startup — see `hermes secrets onepassword status`)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        subprocess.run(
            ['git', 'push', f'https://{token}@github.com/{GITHUB_REPO}.git', 'main'],
            cwd=dashboard_dir, capture_output=True
        )

def process_message(message_text, attachments=None):
    """Process a Discord message for breeding observations."""
    # Find plant IDs across both registered prefixes (PK, PL), preserving
    # first-occurrence order and deduping (same pattern as the shared
    # multi-cross ingest plugin's extract_plant_ids()).
    plant_ids = []
    for prefix, pattern in PLANT_ID_REGISTRY:
        for match in pattern.finditer(message_text):
            plant_id = f"{prefix}{int(match.group(1)):02d}"
            if plant_id not in plant_ids:
                plant_ids.append(plant_id)

    if not plant_ids:
        return None  # No plant IDs found, ignore message
    
    # Parse observation
    observation = parse_observation(message_text)
    
    # Update each mentioned plant
    results = []
    for plant_id in sorted(set(plant_ids)):  # dedupe, deterministic order
        # Handle attachments (photos) - real download + Drive upload per plant,
        # not a placeholder. photo_handler.process_photo() already persists the
        # photo dict onto tracker['photos'] and saves the tracker itself, so we
        # only track a COUNT here for the summary message -- passing the URLs
        # into update_plant() too would double-write the photos list.
        photo_count = 0
        if attachments:
            import photo_handler
            for url in attachments:
                try:
                    photo_handler.process_photo(url, plant_id)
                    photo_count += 1
                except Exception as e:
                    print(f"WARN: photo upload failed for {plant_id}: {e}", file=sys.stderr)
        result = update_plant(plant_id, observation, photo_count=photo_count)
        results.append(result)
    
    return '\n'.join(results)

if __name__ == '__main__':
    # Test mode: process command line argument
    if len(sys.argv) > 1:
        test_message = ' '.join(sys.argv[1:])
        result = process_message(test_message)
        print(result)
    else:
        print("Usage: python3 monitor_breeding_notes.py 'HBH15 looking fire, vigor 9'")
