#!/usr/bin/env python3
"""Parse a Google-Sheets cell dump (from the gdrive MCP `gsheets_read` tool)
into a PrevPoolChecker tournament JSON file.

The dump must be produced by reading the mappool tab anchored at column A
(e.g. range `<Tab>!A1:Z400`) so the cell `location` values are absolute.

Usage:
    python ingest.py <dump.json> --key "WOC 21" --url "<sheet url>" \
        --out tournaments/woc-21.json [--include "Round A,Round B"] \
        [--exclude "Test"] [--dry-run]

With --dry-run (or no --out) it just prints the rounds + map counts it found,
so you can eyeball the structure before committing a file.
"""
import argparse
import json
import re
import sys
from collections import Counter

import osu_sets

LOC_RE = re.compile(r"!([A-Z]+)(\d+)$")
TITLE_RE = re.compile(r"^.+ - .+\[.+\]$")
MOD_RE = re.compile(r"^(NM|HD|HR|DT|FM|EZ|RX|TB|WI|FL|HT|SD|PF|CL)\d*$", re.I)
ID_LABELS = {"map id", "beatmap id", "beatmapid", "map link", "mapid"}
KNOWN_HEADERS = {
    "", "sr", "bpm", "length", "cs", "ar", "od", "hp", "mapper", "map id",
    "beatmap id", "mod#", "mod", "mods", "comment", "comments", "banner",
    "artist - title [diff.]", "artist - title [diff]", "map", "#", "stars",
    "drain", "link", "stats", "slot", "pick", "beatmap", "artist", "title",
    "identifier",
}


def col_to_idx(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def parse_dump(path):
    """Return {sheetName: {(row:int, col:str): value}} for non-empty cells.

    Some dumps wrap the sheet blob in a {"type":"text","text":"<json>"} envelope;
    unwrap that first.
    """
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    if isinstance(blob, list) and blob and isinstance(blob[0], dict) and blob[0].get("type") == "text":
        blob = json.loads(blob[0]["text"])
    sheets = {}
    for sheet in blob:
        name = sheet.get("sheetName", "")
        grid = sheets.setdefault(name, {})
        for row in sheet.get("data", []):
            for cell in row:
                val = (cell.get("value") or "").strip()
                if not val:
                    continue
                m = LOC_RE.search(cell.get("location", ""))
                if not m:
                    continue
                col, rownum = m.group(1), int(m.group(2))
                grid[(rownum, col)] = val
    return sheets


def tier_label(sheet_name):
    """Short tag to disambiguate rounds that come from multiple tabs."""
    m = re.search(r"\bT(\d+)\s*$", sheet_name)
    if m:
        return "T" + m.group(1)
    return sheet_name.strip()


def detect_columns(grid):
    # id-label columns / header rows
    id_label_cols = Counter()
    header_rows = set()
    for (r, c), v in grid.items():
        if v.lower() in ID_LABELS:
            id_label_cols[c] += 1
            header_rows.add(r)
    id_col = id_label_cols.most_common(1)[0][0] if id_label_cols else None

    # title & mod columns from non-header rows
    title_cols, mod_cols = Counter(), Counter()
    for (r, c), v in grid.items():
        if r in header_rows:
            continue
        if TITLE_RE.match(v):
            title_cols[c] += 1
        if MOD_RE.match(v):
            mod_cols[c] += 1
    title_col = title_cols.most_common(1)[0][0] if title_cols else None
    mod_col = mod_cols.most_common(1)[0][0] if mod_cols else None
    return id_col, title_col, mod_col, sorted(header_rows)


def with_set_id(mp, cache):
    """Return the map dict with beatmapset_id inserted after beatmap_id."""
    sid = cache.get(str(mp["beatmap_id"]))
    out = {}
    for k in ("slot", "mod", "beatmap_id"):
        if k in mp:
            out[k] = mp[k]
    if sid:
        out["beatmapset_id"] = sid
    for k, v in mp.items():
        if k not in out:
            out[k] = v
    return out


def round_name(grid, header_row):
    # round name sits on the header (label) row or up to two rows above it,
    # always in one of the leftmost columns (A-D). Ignore stat headers and any
    # mod-slot / title values that may belong to a neighbouring data row.
    for hr in (header_row, header_row - 1, header_row - 2):
        cols = sorted(
            {c for (r, c) in grid if r == hr and col_to_idx(c) <= 4},
            key=col_to_idx,
        )
        for c in cols:
            v = grid[(hr, c)]
            if v.lower() in KNOWN_HEADERS:
                continue
            if MOD_RE.match(v) or TITLE_RE.match(v):
                continue
            return v
    return f"row {header_row}"


def build_pools(grid, min_row=None, max_row=None):
    id_col, title_col, mod_col, header_rows = detect_columns(grid)
    if not (id_col and title_col):
        sys.exit(f"could not detect columns (id={id_col} title={title_col} mod={mod_col})")
    if min_row is not None:
        header_rows = [r for r in header_rows if r >= min_row]
    if max_row is not None:
        header_rows = [r for r in header_rows if r <= max_row]
    bounds = header_rows + [max(r for (r, _) in grid) + 1]
    pools = []
    for i, hr in enumerate(header_rows):
        nxt = bounds[i + 1]
        name = round_name(grid, hr)
        maps = []
        for r in range(hr + 1, nxt):
            bid = grid.get((r, id_col))
            title = grid.get((r, title_col))
            if not bid or not title or not bid.isdigit():
                continue
            slot = grid.get((r, mod_col)) if mod_col else None
            mod = re.sub(r"\d+$", "", slot) if slot else None
            entry = {"slot": slot, "mod": mod, "beatmap_id": int(bid), "title": title}
            maps.append({k: v for k, v in entry.items() if v is not None})
        if maps:
            pools.append({"round": name, "maps": maps})
    return pools, (id_col, title_col, mod_col)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--key", required=True)
    ap.add_argument("--name")
    ap.add_argument("--url", required=True)
    ap.add_argument("--out")
    ap.add_argument("--include", help="comma-separated round names to keep")
    ap.add_argument("--exclude", help="comma-separated round names to drop")
    ap.add_argument("--min-row", type=int, help="ignore pool blocks whose header is above this row")
    ap.add_argument("--max-row", type=int, help="ignore pool blocks whose header is below this row")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv[1:])

    sheets = parse_dump(args.dump)
    sheets = {n: g for n, g in sheets.items() if g}  # drop empty tabs
    multi = len(sheets) > 1

    pools = []
    for name, grid in sheets.items():
        sub, cols = build_pools(grid, min_row=args.min_row, max_row=args.max_row)
        if multi:
            tier = tier_label(name)
            for p in sub:
                p["round"] = f"{tier} {p['round']}"
        print(f"[{name}] detected columns: id={cols[0]} title={cols[1]} mod={cols[2]}")
        pools.extend(sub)

    if args.include:
        keep = {s.strip().lower() for s in args.include.split(",")}
        pools = [p for p in pools if p["round"].lower() in keep]
    if args.exclude:
        drop = {s.strip().lower() for s in args.exclude.split(",")}
        pools = [p for p in pools if p["round"].lower() not in drop]

    print("rounds:")
    for p in pools:
        print(f"  {p['round']:<22} {len(p['maps'])} maps")
    total = sum(len(p["maps"]) for p in pools)
    print(f"total: {total} maps across {len(pools)} rounds")

    if args.dry_run or not args.out:
        return 0

    ids = sorted({m["beatmap_id"] for p in pools for m in p["maps"]})
    cache = osu_sets.load_cache()
    print(f"resolving beatmapset ids for {len(ids)} maps...")
    osu_sets.resolve_many(ids, cache)
    for p in pools:
        p["maps"] = [with_set_id(m, cache) for m in p["maps"]]
    n_set = sum(1 for p in pools for m in p["maps"] if "beatmapset_id" in m)
    total = sum(len(p["maps"]) for p in pools)
    print(f"  {n_set}/{total} maps have beatmapset_id")

    doc = {
        "key": args.key,
        "name": args.name or args.key,
        "ruleset": "osu",
        "sheet_url": args.url,
        "pools": pools,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
