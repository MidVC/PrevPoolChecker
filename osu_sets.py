#!/usr/bin/env python3
"""Resolve osu! beatmap (difficulty) ids to beatmap set ids.

Two backends, picked automatically:
  * osu! API v2 batch endpoint (50 ids/request) when valid credentials are
    available (env OSU_CLIENT_ID/OSU_CLIENT_SECRET, else credentials.json),
  * otherwise the credential-free `/b/{id}` redirect (one id/request).

Results are cached in sets_cache.json so ids are looked up at most once.
Shared by ingest.py (bulk, when building a tournament) and check.py (single
query lookups).
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(ROOT, "sets_cache.json")
CREDS_PATH = os.path.join(ROOT, "credentials.json")
TOKEN_URL = "https://osu.ppy.sh/oauth/token"
API = "https://osu.ppy.sh/api/v2"
USER_AGENT = "PrevPoolChecker/0.1"
BATCH = 50


# ---- cache ---------------------------------------------------------------

def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    return {}


def save_cache(cache):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2)
    except OSError:
        pass


# ---- credential-free redirect backend ------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # don't follow; read the Location header ourselves


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch_set_via_redirect(bid):
    """Resolve one beatmap id via the /b/{id} 302 Location header."""
    req = urllib.request.Request(
        f"https://osu.ppy.sh/b/{bid}", headers={"User-Agent": USER_AGENT}
    )
    try:
        _OPENER.open(req, timeout=15)
        return None  # a 200 with no redirect is unexpected
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            m = re.search(r"/beatmapsets/(\d+)", e.headers.get("Location", ""))
            return int(m.group(1)) if m else None
        return None
    except urllib.error.URLError:
        return None


# ---- osu! API v2 backend -------------------------------------------------

def load_credentials():
    """Return (client_id, client_secret) from env or credentials.json, or None."""
    cid = os.environ.get("OSU_CLIENT_ID")
    secret = os.environ.get("OSU_CLIENT_SECRET")
    if cid and secret:
        return cid, secret
    if not os.path.exists(CREDS_PATH):
        return None
    try:
        with open(CREDS_PATH, encoding="utf-8") as fh:
            c = json.load(fh)
    except (OSError, ValueError):
        return None
    cid, secret = c.get("client_id"), c.get("client_secret")
    if not cid or not secret or str(cid).startswith("YOUR_"):
        return None
    return cid, secret


def get_token(client_id, client_secret):
    body = json.dumps(
        {
            "client_id": int(client_id) if str(client_id).isdigit() else client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "public",
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp).get("access_token")
    except (urllib.error.URLError, ValueError):
        return None


def fetch_batch(ids, token):
    """Return {beatmap_id: beatmapset_id} for up to 50 ids."""
    qs = urllib.parse.urlencode({"ids[]": ids}, doseq=True)
    req = urllib.request.Request(
        f"{API}/beatmaps?{qs}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return {b["id"]: b["beatmapset_id"] for b in data.get("beatmaps", [])}


# ---- public resolution helpers -------------------------------------------

def resolve_one(bid, cache):
    """Set id for a single beatmap id (cache, then redirect on miss).

    Returns (set_id_or_None, online_ok); online_ok is False when a needed
    network lookup failed, so callers can tell "no set" from "offline".
    """
    key = str(bid)
    if key in cache:
        return cache[key], True
    sid = fetch_set_via_redirect(bid)
    cache[key] = sid
    save_cache(cache)
    return sid, sid is not None


def resolve_many(ids, cache, log=print):
    """Fill `cache` with set ids for `ids` not already present.

    Uses the API batch endpoint when credentials are valid, else the redirect.
    """
    todo = [i for i in ids if str(i) not in cache]
    if not todo:
        return

    creds = load_credentials()
    token = get_token(*creds) if creds else None
    if creds and not token:
        log("  osu! API auth failed; falling back to redirect lookups")

    if token:
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            try:
                found = fetch_batch(chunk, token)
            except (urllib.error.URLError, ValueError):
                found = {}
            for i in chunk:
                cache[str(i)] = found.get(i)
            save_cache(cache)
            log(f"  resolved {min(start + BATCH, len(todo))}/{len(todo)} via API")
            time.sleep(0.2)
    else:
        for n, i in enumerate(todo, 1):
            cache[str(i)] = fetch_set_via_redirect(i)
            if n % 25 == 0 or n == len(todo):
                save_cache(cache)
                log(f"  resolved {n}/{len(todo)} via redirect")
            time.sleep(0.1)
        save_cache(cache)
