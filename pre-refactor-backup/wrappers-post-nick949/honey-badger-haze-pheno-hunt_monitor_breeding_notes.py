#!/usr/bin/env python3
"""
Monitor Discord #breeding thread for plant observations (Honey Badger Haze).

Thin config wrapper -- all real logic lives in the shared module
(NICK-592, see breeding_core.py's module docstring for why). Add new
parsing/status/pipeline behavior there, not here.
"""

import sys
from pathlib import Path
import os

BREEDING_DIR = Path(os.environ.get('BREEDING_DIR') or (Path.home() / '.hermes' / 'breeding' / 'honey-badger-haze'))
_SHARED_DIR = str(Path.home() / '.hermes' / 'breeding' / '_shared' / 'monitor-core')
# Guard against duplicate insertion: this module is re-imported/reloaded
# across every #breeding message (the gateway plugin cycles through crosses
# in one long-lived process via importlib.reload()). An unconditional insert
# accumulates duplicate sys.path entries across reloads, which corrupts
# reload()'s module-file resolution on later cross-switches (NICK-592 --
# caught the first refactor draft doing exactly this). Note: this script's
# OWN directory does not need adding here -- Python auto-prepends a script's
# directory when run directly, and the gateway plugin already adds/removes
# each cross's BREEDING_DIR around the call (see hermes-breeding-ingest's
# _run_for_cross()); adding it again here would double up and never be
# cleaned up, since only the plugin's own add/remove is scoped per-call.
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
import breeding_core as core

TRACKER_FILE = BREEDING_DIR / 'tracker.json'
DISABLE_GITHUB_PUSH = os.environ.get('BREEDING_DISABLE_PUSH') == '1'
GITHUB_REPO = os.environ.get('BREEDING_GITHUB_REPO', 'joeydouglas/honey-badger-haze-pheno-hunt')

# Plant ID pattern - tolerant of voice-transcription artifacts:
# "HBH27", "HBH 27", "hbh-27", "HBH5" (single digit, zero-padded) all match.
# 3+ digit runs (e.g. "HBH150") are correctly rejected by the trailing \b.
PLANT_ID_PATTERN = r'\bHBH[\s\-]?(\d{1,2})\b'
PLANT_ID_PREFIX = 'HBH'

CONFIG = {
    'BREEDING_DIR': BREEDING_DIR,
    'TRACKER_FILE': TRACKER_FILE,
    'GITHUB_REPO': GITHUB_REPO,
    'DISABLE_GITHUB_PUSH': DISABLE_GITHUB_PUSH,
    'CROSS_NAME': 'Honey Badger Haze',
    'AUTO_CREATE': True,  # pheno hunt starts with an empty roster
    # STORAGE BACKEND (NICK-949). Declared EXPLICITLY, even though
    # 'markdown' is also breeding_core's default, so that a future reader
    # can see the key that a rollback flips ('json' restores the
    # pre-Task-2.1 tracker.json persistence for THIS project only).
    'BACKEND': 'markdown',
    'PLANT_ID_PATTERN': PLANT_ID_PATTERN,
    'PLANT_ID_PREFIX': PLANT_ID_PREFIX,
}

def load_tracker():
    # NICK-949: *_for(CONFIG) honours CONFIG['BACKEND'], so flipping that key
    # actually switches this project's storage. core.load_tracker(TRACKER_FILE)
    # would always use the global default and ignore the flip.
    return core.load_tracker_for(CONFIG)

def save_tracker(tracker):
    core.save_tracker_for(tracker, CONFIG)

def parse_observation(text):
    return core.parse_observation(text)

def update_plant(plant_id, observation, photo_count=0):
    return core.update_plant(plant_id, observation, CONFIG, photo_count=photo_count)

def update_markdown(plant):
    core.update_markdown(plant, BREEDING_DIR)

def push_to_github():
    core.push_to_github(BREEDING_DIR, GITHUB_REPO, DISABLE_GITHUB_PUSH)

def process_message(message_text, attachments=None):
    return core.process_message(message_text, CONFIG, attachments=attachments)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        test_message = ' '.join(sys.argv[1:])
        result = process_message(test_message)
        print(result)
    else:
        print("Usage: python3 monitor_breeding_notes.py 'HBH15 looking fire, vigor 9'")
