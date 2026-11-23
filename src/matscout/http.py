"""Rate-limited, retrying, cached JSON GET. Stdlib only (urllib).

API etiquette: per-host minimum intervals, exponential backoff on 429/5xx,
24h SQLite response cache. Read-only GETs; no external write operations.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "MatScout/0.1 (materials novelty-check tool; contact: set MATSCOUT_CONTACT)"
MIN_INTERVAL = {"api.openalex.org": 0.35, "api.crossref.org": 1.0}
RETRY_STATUS = {429, 500, 502, 503, 504}

_last_call: dict[str, float] = {}
_lock = threading.Lock()


class HttpError(Exception):
    def __init__(self, url: str, status: int | None, message: str):
        self.url = url
        self.status = status
        super().__init__(f"HTTP {status} for {url}: {message}")


def build_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v is not None}
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)


def _throttle(host: str) -> None:
    with _lock:
        interval = MIN_INTERVAL.get(host, 0.5)
        wait = _last_call.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def get_json(url, params=None, *, conn: sqlite3.Connection | None = None,
             ttl: float = 86400.0, retries: int = 3, timeout: float = 20.0,
             fetch=None) -> dict:
    """GET JSON with throttle/retry/cache. `fetch` injectable for offline tests."""
    full = build_url(url, params)
    if conn is not None:
        row = conn.execute("SELECT response_json, fetched_at FROM http_cache WHERE key=?", (full,)).fetchone()
        if row and (time.time() - row["fetched_at"]) < ttl:
            return json.loads(row["response_json"])
    host = urllib.parse.urlparse(full).hostname or ""
    last_status = None
    last_msg = "unknown error"
    for attempt in range(max(1, retries)):
        _throttle(host)
        try:
            if fetch is not None:
                data = fetch(full)
            else:
                headers = {"User-Agent": UA, "Accept": "application/json"}
                req = urllib.request.Request(full, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            if conn is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO http_cache(key,url,response_json,fetched_at) VALUES(?,?,?,?)",
                    (full, full, json.dumps(data, ensure_ascii=False), time.time()),
                )
                conn.commit()
            return data
        except urllib.error.HTTPError as e:
            last_status, last_msg = e.code, str(e)
            if e.code in RETRY_STATUS and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_status, last_msg = None, str(e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            break
    raise HttpError(full, last_status, last_msg)
