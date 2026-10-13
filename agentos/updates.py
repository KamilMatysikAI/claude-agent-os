"""New-version check for the panel.

What it does: at most once a day, one anonymous GET to the public GitHub API for the latest
release of this repository. Nothing about the workspace is sent. The answer is cached in
`.agentos/update-check.json` and the panel shows a link when a newer version exists.

Rules:
- Off switch: `[updates] check = false` in agentos.toml, or AGENTOS_NO_UPDATE_CHECK=1.
- Never raises and never blocks a request: the panel reads the cache, the refresh runs in a
  background thread, and a failed check is cached too (no retry storm when offline).
- Nothing is downloaded or installed. Updating stays a manual `git pull` + `install.py`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

REPO = "KamilMatysikAI/claude-agent-os"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
CACHE_NAME = "update-check.json"
TTL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 6
ENV_OFF = "AGENTOS_NO_UPDATE_CHECK"

_refreshing = threading.Lock()


def enabled(cfg: dict, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    if str(env.get(ENV_OFF, "")).strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool((cfg.get("updates") or {}).get("check", True))


def parse_version(text) -> tuple[int, ...]:
    """"v0.2.1" -> (0, 2, 1). Anything unparsable -> () which never counts as newer."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+){0,3})", str(text or ""))
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(latest, current) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _cache_path(workspace) -> Path:
    return Path(workspace) / ".agentos" / CACHE_NAME


def read_cache(workspace) -> dict:
    try:
        data = json.loads(_cache_path(workspace).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(workspace, data: dict) -> None:
    path = _cache_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def fetch_latest() -> dict:
    """{"version": "0.2.0", "url": "..."} from GitHub, or {} when there is no release / no network."""
    req = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"claude-agent-os/{__version__}",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            body = json.loads(res.read(200_000).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    if not isinstance(body, dict):
        return {}
    version = ".".join(str(p) for p in parse_version(body.get("tag_name")))
    url = str(body.get("html_url") or "")
    if not version:
        return {}
    # Only ever link to this repository's release pages.
    if not url.startswith(RELEASES_URL):
        url = RELEASES_URL
    return {"version": version, "url": url}


def refresh(workspace, fetch=fetch_latest, now=time.time) -> dict:
    """Fetch and cache. A failed fetch keeps the last known version and only moves the timestamp."""
    old = read_cache(workspace)
    found = fetch() or {}
    data = {
        "checked_at": int(now()),
        "version": found.get("version") or old.get("version") or "",
        "url": found.get("url") or old.get("url") or "",
    }
    _write_cache(workspace, data)
    return data


def is_stale(cache: dict, now=time.time) -> bool:
    try:
        return now() - float(cache.get("checked_at") or 0) >= TTL_SECONDS
    except (TypeError, ValueError):
        return True


def refresh_async(workspace, cfg: dict) -> bool:
    """Start one background refresh when the check is on and the cache is older than a day."""
    if not enabled(cfg) or not is_stale(read_cache(workspace)):
        return False
    if not _refreshing.acquire(blocking=False):
        return False

    def work():
        try:
            refresh(workspace)
        except Exception:  # noqa: BLE001 - a version check must never take the panel down
            pass
        finally:
            _refreshing.release()

    threading.Thread(target=work, name="agentos-update-check", daemon=True).start()
    return True


def status(workspace, cfg: dict, current: str = __version__) -> dict:
    """What the panel shows. Reads the cache only."""
    if not enabled(cfg):
        return {"enabled": False, "available": False, "latest": "", "url": ""}
    cache = read_cache(workspace)
    latest = str(cache.get("version") or "")
    url = str(cache.get("url") or "")
    if not url.startswith(RELEASES_URL):
        url = RELEASES_URL
    return {"enabled": True, "available": is_newer(latest, current), "latest": latest, "url": url}
