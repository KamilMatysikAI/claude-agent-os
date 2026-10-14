"""Every version in the code has its own CHANGELOG entry, so no release goes out undocumented."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agentos  # noqa: E402


def test_current_version_is_in_changelog():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## (\d+(?:\.\d+)+) - \d{4}-\d{2}-\d{2}$", text, flags=re.M)
    assert versions, "CHANGELOG.md has no '## X.Y.Z - YYYY-MM-DD' headings"
    assert versions[0] == agentos.__version__, (
        f"agentos.__version__ is {agentos.__version__}, newest CHANGELOG entry is {versions[0]}: "
        "add an entry (what changed + 'After updating: ...') before releasing")


def test_every_entry_says_what_to_do_after_updating():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.split(r"^## (?=\d)", text, flags=re.M)[1:]
    for entry in entries:
        assert "After updating:" in entry, entry.splitlines()[0]
