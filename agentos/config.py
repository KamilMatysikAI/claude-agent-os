"""Workspace discovery and `agentos.toml` loading.

Rules:
- Missing keys fall back to DEFAULTS, so an old config keeps working after an upgrade.
- Invalid values degrade to the SAFE choice (unknown profile -> "safe"), never to a wider one.
- Secrets never live in agentos.toml; they come from the environment or `<workspace>/.env`.
"""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

CONFIG_NAME = "agentos.toml"
PROFILES = ("safe", "developer", "full")
NOTIFY_KINDS = ("none", "file", "telegram")

DEFAULTS: dict = {
    "owner_name": "Owner",
    "language": "en",
    "timezone": "",
    "queue": {
        "enabled": False,
        "profile": "safe",
        "interval_minutes": 30,
        "timeout_minutes": 45,
        "max_tasks_per_run": 1,
        "claude_bin": "claude",
        "model": "",
        "cooldown_minutes": 0,
    },
    "projects": {
        "wip_limit": 5,
        "human_task_max_minutes": 15,
    },
    "notify": {
        "kind": "none",
        "digest_hours": [8, 15, 21],
    },
    "panel": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8777,
    },
    "updates": {
        "check": True,
    },
}


class WorkspaceNotFound(RuntimeError):
    pass


def find_workspace(start: str | os.PathLike | None = None) -> Path:
    """Walk up from `start` (default: cwd) to the first directory holding agentos.toml."""
    here = Path(start or os.getcwd()).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    raise WorkspaceNotFound(
        f"No {CONFIG_NAME} found in {here} or any parent directory. "
        "Run the installer or pass --workspace PATH."
    )


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _as_int(value, default: int, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= minimum else default


def normalize(cfg: dict) -> dict:
    """Coerce types and clamp to safe values. Never raises."""
    d = DEFAULTS
    q = cfg["queue"]
    q["enabled"] = bool(q.get("enabled"))
    if str(q.get("profile", "")).lower() not in PROFILES:
        q["profile"] = "safe"
    q["profile"] = str(q["profile"]).lower()
    for key in ("interval_minutes", "timeout_minutes", "max_tasks_per_run"):
        q[key] = _as_int(q.get(key), d["queue"][key], minimum=1)
    q["cooldown_minutes"] = _as_int(q.get("cooldown_minutes"), 0)
    q["claude_bin"] = str(q.get("claude_bin") or "claude")
    q["model"] = str(q.get("model") or "")
    p = cfg["projects"]
    p["wip_limit"] = _as_int(p.get("wip_limit"), 5, minimum=1)
    p["human_task_max_minutes"] = _as_int(p.get("human_task_max_minutes"), 15, minimum=1)
    n = cfg["notify"]
    if str(n.get("kind", "")).lower() not in NOTIFY_KINDS:
        n["kind"] = "none"
    n["kind"] = str(n["kind"]).lower()
    hours = n.get("digest_hours")
    if not isinstance(hours, list):
        hours = d["notify"]["digest_hours"]
    n["digest_hours"] = sorted({h for h in (_as_int(x, -1) for x in hours) if 0 <= h <= 23})
    pn = cfg["panel"]
    pn["port"] = _as_int(pn.get("port"), 8777, minimum=1)
    pn["host"] = str(pn.get("host") or "127.0.0.1")
    pn["enabled"] = bool(pn.get("enabled"))
    up = cfg.get("updates")
    if not isinstance(up, dict):
        up = cfg["updates"] = {"check": True}
    up["check"] = bool(up.get("check", True))
    return cfg


def load_config(workspace: str | os.PathLike | None = None) -> dict:
    """Return the merged config. A broken or missing TOML gives defaults (logged by caller
    via the `_error` key) instead of crashing a scheduled run."""
    ws = Path(workspace) if workspace else find_workspace()
    cfg = copy.deepcopy(DEFAULTS)
    path = ws / CONFIG_NAME
    try:
        with open(path, "rb") as fh:
            cfg = _merge(cfg, tomllib.load(fh))
    except FileNotFoundError:
        cfg["_error"] = f"{CONFIG_NAME} not found in {ws}"
    except (tomllib.TOMLDecodeError, OSError) as exc:
        cfg = copy.deepcopy(DEFAULTS)
        cfg["_error"] = f"{CONFIG_NAME} unreadable: {exc}"
    cfg = normalize(cfg)
    cfg["_workspace"] = str(ws)
    return cfg


def load_env(workspace: str | os.PathLike | None) -> dict[str, str]:
    """Process environment overlaid on `<workspace>/.env` (process env wins).

    Minimal KEY=VALUE parser: comments, blank lines, optional `export `, optional quotes.
    The file is read only; os.environ is never modified.
    """
    values: dict[str, str] = {}
    if workspace:
        env_path = Path(workspace) / ".env"
        try:
            for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
        except (OSError, UnicodeDecodeError):
            pass
    values.update({k: v for k, v in os.environ.items()})
    return values
