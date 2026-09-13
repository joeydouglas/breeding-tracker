#!/usr/bin/env python3
"""Generate the master High Priestess Breeding & Pheno Hunt dashboard.

Reads manifest.json (this file's own directory) for the list of registered
projects, loads each project's tracker.json from ~/.hermes/breeding/<breeding_dir>/,
and renders a single overview index.html linking out to each project's own
live GitHub Pages dashboard.

This dashboard is READ-ONLY aggregation. It never writes to any individual
project's tracker.json or dashboard -- it only reads them. Adding a new
project here means adding one entry to manifest.json; nothing about the
new project's own scaffold needs to change.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

MASTER_DIR = Path(
    os.environ.get("MASTER_DASHBOARD_DIR")
    or (Path.home() / ".hermes" / "breeding" / "_shared" / "master-dashboard")
)
MANIFEST_FILE = MASTER_DIR / "manifest.json"
BREEDING_ROOT = Path(os.environ.get("BREEDING_ROOT") or (Path.home() / ".hermes" / "breeding"))
OUTPUT_DIR = MASTER_DIR / "dashboard"

STATUS_LABELS = {
    "keeper": "Keeper",
    "top_keeper": "Top Keeper",
    "culled": "Culled",
    "active": "Active",
}
STATUS_EMOJI = {
    "keeper": "\U0001f49a",
    "top_keeper": "\U0001f49a\U0001f49a",
    "culled": "\u2620\ufe0f",
    "active": "",
}


def load_manifest() -> list[dict]:
    with open(MANIFEST_FILE) as f:
        return json.load(f)["projects"]


def load_tracker(breeding_dir: str) -> dict | None:
    path = BREEDING_ROOT / breeding_dir / "tracker.json"
    if not path.is_file():
        print(f"\u26a0\ufe0f  tracker.json missing for {breeding_dir}, skipping")
        return None
    with open(path) as f:
        return json.load(f)


def plants_list(tracker: dict) -> list[dict]:
    plants = tracker.get("plants", [])
    if isinstance(plants, dict):
        return list(plants.values())
    return plants


def project_stats(tracker: dict) -> dict:
    plants = plants_list(tracker)
    total = len(plants)
    counts = {"keeper": 0, "top_keeper": 0, "culled": 0, "active": 0}
    for p in plants:
        status = p.get("status") or "active"
        if status not in counts:
            counts[status] = 0
        counts[status] += 1
    keepers = counts.get("keeper", 0) + counts.get("top_keeper", 0)
    culled = counts.get("culled", 0)
    return {
        "total": total,
        "keepers": keepers,
        "culled": culled,
        "keeper_rate": round(100 * keepers / total, 1) if total else 0.0,
    }


def project_card_html(entry: dict, tracker: dict | None) -> str:
    icon = entry.get("icon", "\U0001f33f")
    title = entry.get("title", entry["id"])

    if tracker is None:
        return f"""
        <div class="project-card project-card-missing">
            <h2>{icon} {title}</h2>
            <p class="missing-note">tracker.json not found -- project scaffolded but not yet populated.</p>
        </div>
        """

    stats = project_stats(tracker)
    lineage = tracker.get("breeder_lineage") or tracker.get("genetics") or ""
    pages_url = tracker.get("github_pages_url", "#")
    last_updated = tracker.get("last_updated", "")
    try:
        last_updated_fmt = datetime.fromisoformat(last_updated).strftime("%B %d, %Y")
    except (ValueError, TypeError):
        last_updated_fmt = last_updated or "unknown"

    return f"""
    <a class="project-card" href="{pages_url}">
        <h2>{icon} {title}</h2>
        <p class="lineage">{lineage}</p>
        <div class="mini-stats">
            <div class="mini-stat"><span class="mini-number">{stats['total']}</span><span class="mini-label">plants</span></div>
            <div class="mini-stat keeper-color"><span class="mini-number">{stats['keepers']}</span><span class="mini-label">keeper</span></div>
            <div class="mini-stat culled-color"><span class="mini-number">{stats['culled']}</span><span class="mini-label">culled</span></div>
            <div class="mini-stat"><span class="mini-number">{stats['keeper_rate']}%</span><span class="mini-label">keep rate</span></div>
        </div>
        <p class="updated">Last updated: {last_updated_fmt}</p>
    </a>
    """


def generate_all() -> None:
    entries = load_manifest()
    trackers = {}
    for entry in entries:
        trackers[entry["id"]] = load_tracker(entry["breeding_dir"])

    total_plants = sum(project_stats(t)["total"] for t in trackers.values() if t)
    total_keepers = sum(project_stats(t)["keepers"] for t in trackers.values() if t)
    total_culled = sum(project_stats(t)["culled"] for t in trackers.values() if t)
    active_projects = sum(1 for t in trackers.values() if t)

    cards_html = "\n".join(
        project_card_html(entry, trackers[entry["id"]]) for entry in entries
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>High Priestess Breeding & Pheno Hunt Dashboard</title>
    <link rel="icon" href="favicon-32.png" sizes="32x32">
    <link rel="icon" href="favicon-192.png" sizes="192x192">
    <link rel="apple-touch-icon" href="favicon-192.png">
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <header>
            <img src="hp-logo-white.png" alt="High Priestess" class="hp-logo">
            <h1>\U0001f33f High Priestess Breeding & Pheno Hunt</h1>
            <p class="subtitle">Master Dashboard -- {active_projects} project{'s' if active_projects != 1 else ''} tracked</p>
            <p class="subtitle">Last generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
        </header>

        <div class="stats">
            <div class="stat-box">
                <div class="stat-number">{active_projects}</div>
                <div class="stat-label">Active Projects</div>
            </div>
            <div class="stat-box">
                <div class="stat-number">{total_plants}</div>
                <div class="stat-label">Total Plants</div>
            </div>
            <div class="stat-box">
                <div class="stat-number keeper">{total_keepers}</div>
                <div class="stat-label">Total Keepers</div>
            </div>
            <div class="stat-box">
                <div class="stat-number culled">{total_culled}</div>
                <div class="stat-label">Total Culled</div>
            </div>
        </div>

        <div class="project-grid">
            {cards_html}
        </div>

        <footer>
            <p>Each project card links to its own live dashboard. This page auto-aggregates from every registered project's tracker.json -- adding a new project only requires one entry in manifest.json.</p>
        </footer>
    </div>
</body>
</html>
"""

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "index.html", "w") as f:
        f.write(html)

    print(f"\u2713 Generated master dashboard in {OUTPUT_DIR}")
    print(f"  - {active_projects} of {len(entries)} projects have data")
    print(f"  - {total_plants} total plants, {total_keepers} keepers, {total_culled} culled")


if __name__ == "__main__":
    generate_all()
