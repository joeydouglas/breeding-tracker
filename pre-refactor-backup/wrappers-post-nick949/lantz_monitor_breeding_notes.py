#!/usr/bin/env python3
"""
Monitor Discord #breeding thread for plant observations (Lantz).

Thin config wrapper -- all real logic lives in the shared module
(NICK-592, see breeding_core.py's module docstring for why). Add new
parsing/status/pipeline behavior there, not here.
"""

import sys
from pathlib import Path
import os

BREEDING_DIR = Path(os.environ.get('BREEDING_DIR') or (Path.home() / '.hermes' / 'breeding' / 'lantz'))
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
GITHUB_REPO = os.environ.get('BREEDING_GITHUB_REPO', 'joeydouglas/lantz-breeding')

# Plant ID pattern - tolerant of voice-transcription artifacts and now
# (NICK-924) 3-digit IDs, '#' separators, and leading zeros -- widened
# to match the gateway's routing decision, see the pattern's own
# comment below for why.
# NICK-924: widened to match the gateway's live, more permissive
# PLANT_ID_REGISTRY pattern (breeding-ingest/breeding_tracker/
# discord_ingest.py) -- handles '#' separator, leading zeros, and
# 3-digit IDs that the old narrower pattern silently dropped even
# though the gateway had already routed the message here (found
# investigating NICK-924's routing-equivalence acceptance criterion).
# Case-insensitivity is applied by the caller (extract_plant_ids_single
# always passes re.IGNORECASE), matching the gateway's own (?i).
PLANT_ID_PATTERN = r'(?i)(?<![A-Z0-9])Ltz\s*[-#]?\s*0*(\d{1,3})(?!\d)'
PLANT_ID_PREFIX = 'LTZ'

CONFIG = {
    'BREEDING_DIR': BREEDING_DIR,
    'TRACKER_FILE': TRACKER_FILE,
    'GITHUB_REPO': GITHUB_REPO,
    'DISABLE_GITHUB_PUSH': DISABLE_GITHUB_PUSH,
    'CROSS_NAME': 'Lantz',
    'AUTO_CREATE': True,  # NICK-1058: auto-create enabled for all projects
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
        print("Usage: python3 monitor_breeding_notes.py 'Ltz15 looking fire, vigor 9'")
