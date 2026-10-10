"""Shared helpers for engine tests: build a tiny workspace in tmp_path."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO = ROOT / "demo"

CONFIG = """owner_name = "Alex"
language = "en"

[queue]
enabled = true
profile = "{profile}"
timeout_minutes = 5
max_tasks_per_run = 1
claude_bin = "claude"
cooldown_minutes = 0

[projects]
wip_limit = {wip}

[notify]
kind = "file"
digest_hours = [8, 15, 21]
"""


def make_ws(tmp_path: Path, profile: str = "safe", wip: int = 5) -> Path:
    ws = tmp_path / "ws"
    (ws / "projects" / "shop" / "tasks").mkdir(parents=True)
    (ws / "inbox").mkdir()
    (ws / "agentos.toml").write_text(CONFIG.format(profile=profile, wip=wip), encoding="utf-8")
    (ws / "projects" / "shop" / "PROJECT.md").write_text(
        "---\nslug: shop\nname: Test shop\nstatus: active\nowner_human: Alex\n"
        "wip_limit:\ncreated: 2026-10-01\n---\n\n## Goal\n\nSell things.\n", encoding="utf-8")
    return ws


def write_task(ws: Path, task_id: str, project: str = "shop", body: str = "", **meta) -> Path:
    fields = {
        "id": task_id, "project": project, "title": f"Task {task_id}",
        "owner": "human" if task_id.startswith("H-") else "copy", "type": "task",
        "status": "todo", "priority": "normal", "due": "", "created": "2026-10-01",
        "closed": "", "size": "small", "autonomy": "full", "source": "local", "profile": "",
        "blocked_by": "[]", "unblocked_by": "", "decision": "", "evidence": "", "lock": "",
    }
    fields.update({k: v for k, v in meta.items()})
    lines = ["---"] + [f"{k}: {v}".rstrip() for k, v in fields.items()] + ["---", ""]
    text = "\n".join(lines) + (body or f"\n## Goal\n\nDo {task_id}.\n\n## Progress log\n\n")
    folder = ws / "projects" / project / "tasks" if project else ws / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{task_id}-task.md"
    path.write_text(text, encoding="utf-8")
    return path
