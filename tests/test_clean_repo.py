"""The public repository must not contain private names, local paths, e-mails or phone numbers.

Scans every text file (and every file path) in the repo except .git, virtualenvs, caches and
the banned list itself. Banned entries live in tests/banned_words.txt (sha256 of the
normalized phrase, or plain phrases). Add a new entry with:

    python tests/test_clean_repo.py --hash "phrase to ban"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentos.doctor import find_banned, iter_text_files, load_banned, phrase_hash  # noqa: E402

BANNED_FILE = REPO / "tests" / "banned_words.txt"
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".agentos"}

# Built from pieces so this file does not trip its own rules.
PRIVATE_ROOT = re.compile(r"[A-Za-z]:[\\/]+" + "asys" + "tent", re.IGNORECASE)
USER_HOME = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!(?:you|user|username|me|alex|public|default|runneradmin|<|\{|%|\$))[A-Za-z]", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
EMAIL_ALLOWED = re.compile(r"(^|\.)(example\.(com|org|net)|example|localhost|anthropic\.com|users\.noreply\.github\.com)$", re.IGNORECASE)
PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{2,3}[ -]?)?\d{3}[ -]\d{3}[ -]\d{3}(?![\w.])"   # three groups of three digits, optional country code
    r"|(?<![\w.])\+\d{2,3}[ -]?\(?\d{2,4}\)?[ -]?\d{3}[ -]?\d{3,4}(?![\w.])"
)


def _files():
    for p in iter_text_files(REPO, skip_dirs=SKIP_DIRS):
        if p.resolve() == BANNED_FILE.resolve():
            continue
        yield p


def _scan():
    plain, hashes = load_banned(BANNED_FILE)
    problems = []
    for path in _files():
        rel = path.relative_to(REPO).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_bytes().decode("latin-1")
        if find_banned(rel, plain, hashes):
            problems.append(f"{rel}: banned word in file name")
        for lineno, line in enumerate(text.splitlines(), 1):
            # The author's public attribution is allowed only in the LICENSE copyright line.
            is_attribution = rel == "LICENSE" and line.startswith("Copyright (c)")
            if not is_attribution and find_banned(line, plain, hashes):
                problems.append(f"{rel}:{lineno}: banned word")
            if PRIVATE_ROOT.search(line):
                problems.append(f"{rel}:{lineno}: private local path")
            if USER_HOME.search(line):
                problems.append(f"{rel}:{lineno}: user home path with a real user name")
            for m in EMAIL.finditer(line):
                if not EMAIL_ALLOWED.search(m.group(1)):
                    problems.append(f"{rel}:{lineno}: e-mail address")
            if PHONE.search(line):
                problems.append(f"{rel}:{lineno}: phone number")
    return problems


def test_banned_list_exists_and_is_not_empty():
    plain, hashes = load_banned(BANNED_FILE)
    assert plain or hashes, "tests/banned_words.txt is missing or empty"


def test_matcher_is_token_based():
    plain, hashes = {"secretbrand"}, {phrase_hash("Two Words")}
    assert find_banned("we love SecretBrand!", plain, hashes)
    assert find_banned("two-words here", plain, hashes)
    assert not find_banned("notsecretbrandish", plain, hashes)  # no substring hits


def test_repo_is_clean():
    problems = _scan()
    assert not problems, "private data found:\n" + "\n".join(problems[:200])


if __name__ == "__main__":  # helper for maintainers
    if len(sys.argv) >= 3 and sys.argv[1] == "--hash":
        print(phrase_hash(" ".join(sys.argv[2:])))
    else:
        print("\n".join(_scan()) or "clean")
