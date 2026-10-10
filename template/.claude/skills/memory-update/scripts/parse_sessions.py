#!/usr/bin/env python3
"""Extract a clean dialogue (user + assistant text) from Claude Code session logs.

Claude Code stores one JSONL file per session under
    <config dir>/projects/<encoded workspace path>/<session id>.jsonl
where <config dir> is $CLAUDE_CONFIG_DIR or ~/.claude, and the encoded path is
the absolute workspace path with every non-alphanumeric character replaced by "-".

Sessions started from a subdirectory of the workspace get their own encoded
directory; all directories whose name starts with the workspace's encoded path
are scanned. Worktree sessions (".../<repo>-wt-..." or "...-worktrees-...") are
skipped by default because they are short-lived agent runs.

Noise filtered out: tool calls and results, very short messages, slash commands,
skill bodies loaded into the context.

Usage:
    python parse_sessions.py [--since "YYYY-MM-DD HH:MM"] [--days N]
                             [--workspace PATH] [--out FILE] [--stats-json FILE]
                             [--include-worktrees]

Output: the dialogue to stdout (or --out FILE), a one-line summary to stderr.
Read-only: it never modifies or deletes session files. Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

MIN_USER_LENGTH = 10        # shorter user messages are noise ("ok", "yes")
MIN_ASSISTANT_LENGTH = 20
MAX_ASSISTANT_LENGTH = 2000  # long answers are truncated
MAX_USER_MESSAGES = 500      # hard cap across all sessions

BUILTIN_COMMANDS = {
    "/clear", "/help", "/compact", "/cost", "/doctor", "/init", "/login",
    "/logout", "/config", "/mcp", "/memory", "/review", "/status", "/vim",
    "/model", "/permissions", "/terminal-setup", "/fast", "/resume",
}

WORKTREE_MARKERS = ("-worktrees-", "-wt-")


def configure_stdio() -> None:
    """Force UTF-8 output so non-ASCII text survives on any console."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_workspace(start: Path) -> Path:
    """Walk up to the directory containing agentos.toml; fall back to start."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "agentos.toml").is_file():
            return candidate
    return current


def encode_path(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def config_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def session_dirs(workspace: Path, include_worktrees: bool) -> list[Path]:
    base = config_dir() / "projects"
    if not base.is_dir():
        raise FileNotFoundError(f"Claude Code projects directory not found: {base}")
    prefix = encode_path(workspace)
    found = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        rest = entry.name[len(prefix):]
        if not include_worktrees and any(marker in rest for marker in WORKTREE_MARKERS):
            continue
        found.append(entry)
    if not found:
        raise FileNotFoundError(f"No session directories for {workspace} (looked for {prefix}* in {base})")
    return found


def cutoff_time(since: str | None, days: int) -> dt.datetime:
    if since:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(since, fmt)
            except ValueError:
                continue
        raise ValueError(f"invalid --since value: {since!r} (expected YYYY-MM-DD or YYYY-MM-DD HH:MM)")
    return dt.datetime.now() - dt.timedelta(days=days)


def session_files(dirs: list[Path], cutoff: dt.datetime) -> list[tuple[dt.datetime, Path]]:
    seen: set[str] = set()
    result = []
    for directory in dirs:
        for path in directory.glob("*.jsonl"):
            if path.name in seen:
                continue
            seen.add(path.name)
            mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
            if mtime >= cutoff:
                result.append((mtime, path))
    result.sort()
    return result


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def is_command(text: str) -> bool:
    first = text.strip().split("\n", 1)[0].strip().lower()
    return any(first == cmd or first.startswith(cmd + " ") for cmd in BUILTIN_COMMANDS)


def is_skill_body(text: str) -> bool:
    stripped = text.strip()
    return "Base directory for this skill:" in stripped or stripped.startswith("---\nname:")


def parse_session(path: Path) -> list[tuple[str, str]]:
    dialogue: list[tuple[str, str]] = []
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"skipped {path.name}: {exc}", file=sys.stderr)
        return dialogue
    with handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # one broken line never stops the file
            kind = entry.get("type")
            message = entry.get("message", {})
            if kind == "user" and entry.get("userType") == "external":
                content = message.get("content", "") if isinstance(message, dict) else message
                text = text_of(content).strip()
                if len(text) < MIN_USER_LENGTH or is_command(text) or is_skill_body(text):
                    continue
                dialogue.append(("USER", text))
            elif kind == "assistant" and isinstance(message, dict):
                text = text_of(message.get("content", "")).strip()
                if len(text) < MIN_ASSISTANT_LENGTH:
                    continue
                if len(text) > MAX_ASSISTANT_LENGTH:
                    text = text[:MAX_ASSISTANT_LENGTH] + "\n[...truncated]"
                dialogue.append(("ASSISTANT", text))
    return dialogue


def build_output(files: list[tuple[dt.datetime, Path]]) -> tuple[list[str], dict]:
    lines: list[str] = []
    sessions = 0
    user_messages = 0
    for mtime, path in files:
        dialogue = parse_session(path)
        if not dialogue:
            continue
        sessions += 1
        count = sum(1 for role, _ in dialogue if role == "USER")
        user_messages += count
        lines.append("\n" + "=" * 60)
        lines.append(f"SESSION: {mtime:%Y-%m-%d %H:%M} | {count} user messages")
        lines.append("=" * 60 + "\n")
        for role, text in dialogue:
            lines.append(f"[{role}]: {text}\n")
        if user_messages >= MAX_USER_MESSAGES:
            lines.append(f"\n[...limit of {MAX_USER_MESSAGES} user messages reached, later sessions skipped]")
            break
    stats = {"sessions": sessions, "user_messages": user_messages}
    return lines, stats


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Extract dialogue from Claude Code session logs.")
    parser.add_argument("--since", help="sessions modified since YYYY-MM-DD or 'YYYY-MM-DD HH:MM'")
    parser.add_argument("--days", type=int, default=1, help="sessions from the last N days (ignored with --since)")
    parser.add_argument("--workspace", help="workspace root (default: walk up to agentos.toml)")
    parser.add_argument("--out", help="write the dialogue to this file instead of stdout")
    parser.add_argument("--stats-json", help="also write summary stats as JSON to this file")
    parser.add_argument("--include-worktrees", action="store_true", help="include worktree sessions")
    args = parser.parse_args(argv)

    try:
        cutoff = cutoff_time(args.since, args.days)
        workspace = Path(args.workspace).resolve() if args.workspace else find_workspace(Path.cwd())
        dirs = session_dirs(workspace, args.include_worktrees)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    files = session_files(dirs, cutoff)
    if not files:
        print(f"No sessions since {cutoff:%Y-%m-%d %H:%M}", file=sys.stderr)
        return 0

    lines, stats = build_output(files)
    stats.update({
        "cutoff": f"{cutoff:%Y-%m-%d %H:%M}",
        "earliest": f"{files[0][0]:%Y-%m-%d %H:%M}",
        "latest": f"{files[-1][0]:%Y-%m-%d %H:%M}",
    })
    print(
        f"Sessions: {stats['sessions']} | User messages: {stats['user_messages']} | "
        f"Range: {stats['cutoff']} to now",
        file=sys.stderr,
    )

    text = "\n".join(lines)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.stats_json:
        Path(args.stats_json).write_text(json.dumps(stats), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
