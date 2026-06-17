#!/usr/bin/env python3
"""Pool checker for osu! tournaments.

Given a beatmap (URL or numeric id), report every stored tournament mappool
that contains it -- both the exact difficulty and other difficulties from the
same beatmap set.

Run it and type a beatmap id (or osu! URL) at the prompt:
    python check.py
    beatmap> 4064517
    beatmap> https://osu.ppy.sh/beatmapsets/1234#osu/4064517

Enter a blank line or "q" to quit.
"""
import json
import sys
import re
import glob
import os

import osu_sets

# When frozen by PyInstaller the bundled data lives under sys._MEIPASS.
if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "tournaments")


# ---- parsing -------------------------------------------------------------

def extract_id(s):
    """Pull a beatmap (difficulty) id out of a raw id or an osu! URL."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    m = re.search(r"/beatmapsets/\d+#\w+/(\d+)", s)  # /beatmapsets/<set>#<mode>/<diff>
    if m:
        return int(m.group(1))
    m = re.search(r"/b(?:eatmaps)?/(\d+)", s)  # /beatmaps/<diff> or /b/<diff>
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*$", s)  # trailing number
    if m:
        return int(m.group(1))
    return None


def extract_set_from_url(s):
    """If the input URL already names the set, read it straight off (no network)."""
    m = re.search(r"/beatmapsets/(\d+)", s)
    return int(m.group(1)) if m else None


# ---- dataset index -------------------------------------------------------

def load_indexes():
    """Return (by_beatmap_id, by_set_id) over every tournament file."""
    by_id, by_set = {}, {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            t = json.load(fh)
        for pool in t.get("pools", []):
            for mp in pool.get("maps", []):
                entry = {
                    "tournament": t.get("name", t.get("key", "?")),
                    "round": pool.get("round", "?"),
                    "slot": mp.get("slot"),
                    "mod": mp.get("mod"),
                    "title": mp.get("title"),
                    "beatmap_id": mp.get("beatmap_id"),
                    "beatmapset_id": mp.get("beatmapset_id"),
                }
                by_id.setdefault(mp["beatmap_id"], []).append(entry)
                if mp.get("beatmapset_id"):
                    by_set.setdefault(mp["beatmapset_id"], []).append(entry)
    return by_id, by_set


# ---- reporting -----------------------------------------------------------

def _line(h, extra=""):
    return f"    - {h['tournament']} / {h['round']} / {h['slot']} ({h['mod']}){extra}"


def report(raw, by_id, by_set, cache):
    bid = extract_id(raw)
    if bid is None:
        print(f"\n=== {raw} ===\n  could not parse a beatmap id from this input")
        return

    # resolve the query's set: prefer the id off a beatmapsets URL, else look it
    # up; fall back to whatever the dataset already knows about this exact map.
    sid = extract_set_from_url(raw)
    online_ok = True
    if sid is None and bid in by_id:  # the dataset already knows pooled maps' sets
        sid = by_id[bid][0].get("beatmapset_id")
    if sid is None:  # otherwise resolve via the credential-free /b/{id} redirect
        sid, online_ok = osu_sets.resolve_one(bid, cache)

    print(f"\n=== {raw}  (beatmap id: {bid}, set: {sid if sid else '?'}) ===")

    exact = by_id.get(bid, [])
    if exact:
        print(f"  EXACT MAP - pooled in {len(exact)} slot(s):")
        for h in exact:
            print(_line(h))
            if h["title"]:
                print(f"        {h['title']}")
    else:
        print("  EXACT MAP - not pooled in any stored tournament")

    if sid:
        same_set = [h for h in by_set.get(sid, []) if h["beatmap_id"] != bid]
        if same_set:
            print(f"  SAME SET (other difficulties) - {len(same_set)} slot(s):")
            for h in same_set:
                print(_line(h, f"  [diff {h['beatmap_id']}]"))
                if h["title"]:
                    print(f"        {h['title']}")
        elif exact:
            print("  SAME SET - no other difficulties from this set were pooled")
    elif not online_ok:
        print("  SAME SET - could not resolve set id (offline or map deleted)")


def main():
    by_id, by_set = load_indexes()
    if not by_id:
        print(f"No tournament data found in {DATA_DIR}")
        return 1
    cache = osu_sets.load_cache()

    print("osu! pool checker - enter a beatmap id or URL (blank or 'q' to quit)")
    while True:
        try:
            raw = input("\nbeatmap> ").strip().lstrip("﻿")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if raw == "" or raw.lower() == "q":
            break
        report(raw, by_id, by_set, cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())
