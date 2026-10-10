#!/usr/bin/env python3
"""Print the next free task ID for a project.

Usage:
    python .claude/skills/create-task/scripts/next_id.py <slug> A|H [--workspace PATH]

Rule (from the workspace contract): next ID = highest number found anywhere in
projects/<slug>/tasks/ (all subdirectories, archived ones included, both A- and H-
prefixes) + 1. Numbers are shared between prefixes, so A-012 and H-012 never coexist.

This is a read-only fallback for sessions where the engine CLI has no
`next-id` command. It never writes or deletes anything. Stdlib only, no side
effects at import time.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^(?:id:\s*)?([AH])-(\d{3,})\b")


def find_workspace(start: Path) -> Path | None:
    """Walk up from start until a directory containing agentos.toml is found."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "agentos.toml").is_file():
            return candidate
    return None


def highest_number(tasks_dir: Path) -> int:
    """Highest numeric part of any A-/H- ID in file names or `id:` frontmatter lines."""
    best = 0
    if not tasks_dir.is_dir():
        return best
    for path in tasks_dir.rglob("*.md"):
        match = ID_RE.match(path.name)
        if match:
            best = max(best, int(match.group(2)))
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index > 40:  # frontmatter sits at the top
                        break
                    found = ID_RE.match(line.strip())
                    if found and line.strip().startswith("id:"):
                        best = max(best, int(found.group(2)))
        except OSError:
            continue  # unreadable file: skip it, never fail the whole scan
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the next free task ID.")
    parser.add_argument("slug", help="project slug (directory name under projects/)")
    parser.add_argument("prefix", choices=["A", "H"], help="A = agent task, H = human task")
    parser.add_argument("--workspace", default=None, help="workspace root (default: walk up to agentos.toml)")
    args = parser.parse_args(argv)

    root = Path(args.workspace) if args.workspace else find_workspace(Path.cwd())
    if root is None:
        print("error: agentos.toml not found; pass --workspace", file=sys.stderr)
        return 2
    project_dir = root / "projects" / args.slug
    if not project_dir.is_dir():
        print(f"error: project not found: {project_dir}", file=sys.stderr)
        return 2

    number = highest_number(project_dir / "tasks") + 1
    print(f"{args.prefix}-{number:03d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
