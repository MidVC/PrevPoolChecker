# PrevPoolChecker

Check whether an osu! beatmap was pooled in a previous tournament.

Given a beatmap (URL or numeric difficulty id), the checker reports:

- **EXACT MAP** — the same difficulty was pooled before, and
- **SAME SET** — a *different* difficulty from the same beatmap set was pooled,

with the tournament, round, slot and mod for each hit.

## Requirements

- Python 3 (uses the standard library only — no `pip install` needed).
- Internet is needed only the first time you look up a beatmap whose set isn't
  already known; results are cached. Everything already in the dataset resolves
  offline.

## Setup

```
git clone <your repo>
cd PrevPoolChecker
python check.py          # ready to use; the dataset is committed
```

osu! API credentials are **optional** — only `ingest.py` can use them (to add
`beatmapset_id` faster when you add a tournament), and it falls back to a
credential-free method without them. The checker itself never needs credentials.
See [Credentials](#credentials).

## Usage

Run it and type beatmap ids or osu! URLs at the prompt (blank line or `q` quits):

```
python check.py
beatmap> 4064517
beatmap> https://osu.ppy.sh/beatmapsets/1234#osu/4064517
```

Example output:

```
=== 9999999  (beatmap id: 9999999, set: 1601852) ===
  EXACT MAP - not pooled in any stored tournament
  SAME SET (other difficulties) - 1 slot(s):
    - WOC 22 / Week 1 / NM1 (NM)  [diff 3271290]
        rejection - Aimai Attitude (feat. Nakamura Sanso) [Girlish Extra ft. Regou]
```

To find the query's set, the checker reads the `/b/{id}` redirect (no osu!
credentials needed) and caches the result in `sets_cache.json`. It needs
internet only for ids it hasn't seen before; ids already in the dataset / cache
resolve instantly and offline.

## Layout

```
PrevPoolChecker/
  check.py                  # the interactive checker
  ingest.py                 # builds a tournament JSON from a Google-Sheets cell dump
  osu_sets.py               # shared beatmap_id -> set_id resolver (API or redirect)
  tournaments/              # one JSON file per tournament (the dataset)
    woc-22.json
    woc-21.json
    ...
  credentials.example.json  # template for optional osu! API credentials
  credentials.json          # your real credentials (optional; gitignored; you create this)
  sets_cache.json           # beatmap_id -> set_id cache (gitignored, regenerable)
  .gitignore
```

## Dataset format

Each file in `tournaments/` is one tournament:

```json
{
  "key": "WOC 22",
  "name": "WOC 22",
  "ruleset": "osu",
  "sheet_url": "https://docs.google.com/spreadsheets/d/.../",
  "pools": [
    {
      "round": "Finals",
      "maps": [
        {
          "slot": "NM1",
          "mod": "NM",
          "beatmap_id": 2547849,
          "beatmapset_id": 1186612,
          "title": "Artist - Title [Diff]"
        }
      ]
    }
  ]
}
```

`beatmap_id` is the **difficulty** id (the key for exact pool membership);
`beatmapset_id` enables set-level matching and is filled in by `ingest.py`
(absent for a handful of deleted maps). The checker indexes every map across
every file, so a map reused across tournaments or rounds shows up as multiple
hits.

## Credentials (optional)

Nothing here is required to *use* the checker. `ingest.py` will use osu! API v2
credentials **if available** to resolve `beatmapset_id` quickly (50 ids/request);
without them it falls back to the credential-free `/b/{id}` redirect.

To set them up:

1. Log in at <https://osu.ppy.sh> → Settings → OAuth
   (<https://osu.ppy.sh/home/account/edit#oauth>) → **New OAuth Application**.
   Any name; the callback URL is unused for this flow, so `http://localhost` is
   fine. Register it.
2. Copy the template and fill in your Client ID / Secret:

   ```
   cp credentials.example.json credentials.json   # then edit credentials.json
   ```

   `credentials.json` is gitignored, so your secret stays local. (You can also
   skip the file and set `OSU_CLIENT_ID` / `OSU_CLIENT_SECRET` as environment
   variables — `osu_sets.py` checks those first.)

Never commit `credentials.json`. If a secret ever leaks, regenerate it in the
osu! OAuth settings.

## Adding a tournament

Mappools come from per-tournament Google Sheets. The sheets vary in tab name and
column layout, so ingestion is:

1. Read the mappool tab **anchored at column A** (e.g. range `<Tab>!A1:Z500`) and
   save the raw cell dump to a file.
2. Run the parser, eyeballing the rounds before committing:

   ```
   python ingest.py dump.json --key "<Tournament Name>" --url "<sheet url>" --dry-run
   python ingest.py dump.json --key "<Tournament Name>" --url "<sheet url>" --out tournaments/<name>.json
   ```

`--key` is whatever name you want shown in results (it need not be "WOC ..."),
and `<name>.json` is any filename. When writing (with `--out`), `ingest.py`
resolves and adds `beatmapset_id` for the maps automatically, caching results in
`sets_cache.json`.

`ingest.py` auto-detects the title / beatmap-id / mod columns and the round
headers, processes each tab separately, and prefixes round names per tab when a
sheet has several (e.g. `T1`/`T2`). Useful flags when a sheet is irregular:

- `--include "Round A,Round B"` / `--exclude "Test"` — keep/drop rounds by name
- `--min-row N` / `--max-row N` — restrict to one section of a multi-section tab

## Notes on the WOC sheets ingested so far

- **WOC 22** — tab `Mappool`. Week 1–3 + Semi-Finals + Finals (120 maps). Skipped
  empty Qualifiers/Group Stage/Grand Finals, a `Test` scratch pool, and a
  duplicate (draft) week set.
- **WOC 21** — tab `MAPPOOLS`. Grand Finals → Swiss Stage 1 (7 rounds, 146 maps).
- **WOC 20** — tab `Mappools`. The tab has two parallel layouts; ingested the
  compact section (9 rounds, 127 maps). Round-name detection is imperfect there
  (one block is labelled `row 2`) and the Qualifiers/Round-of-64 blocks look
  incomplete — worth a manual pass.
- **WOC 19** — tabs `Tournament Pool` (one 100-map pool) + `Team Pools` (8 teams
  × 5 maps; rounds are labelled by team name). 140 maps total. One team name
  came through as `row 2`.
- **WOC 18** — tab `MAPPOOLS`. Swiss 1–5 only in this tab (95 maps); no bracket
  pools found.
- **WOC 17** — tabs `Mappool T1` + `Mappool T2`; rounds prefixed `T1`/`T2`
  (13 rounds, 221 maps).
- **WOC 16** — tab `Mappools`. Grand Finals → Qualifiers (6 rounds, 108 maps).
- **WOC 15** — tabs `Mappools T1` + `Mappools T2`; rounds prefixed `T1`/`T2`
  (10 rounds, 166 maps).
