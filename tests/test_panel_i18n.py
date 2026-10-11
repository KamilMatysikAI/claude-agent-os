"""Panel language: both dictionaries complete and consistent, every key the front end uses
exists, Polish plurals and server message codes covered."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import data  # noqa: E402

STATIC = ROOT / "panel" / "static"
LANGS = ("en", "pl")
PLURAL_FORMS = {"en": {"one", "other"}, "pl": {"one", "few", "many", "other"}}
NAMESPACES = ("a11y", "nav", "lang", "theme", "common", "date", "due", "status", "prio", "decision",
              "role", "hdr", "search", "new", "keys", "err", "toast", "row", "today", "dec", "proj",
              "deps", "act", "tasks", "drawer", "tree", "srv")
# keys built at run time from a fixed list of values
DYNAMIC = {
    "status": ("todo", "in_progress", "blocked", "done", "cancelled"),
    "prio": ("high", "normal", "low"),
    "decision": ("accepted", "rejected"),
    "role": ("ceo", "soft", "web", "copy", "marketing", "research", "you", "unassigned"),
    "theme": ("auto", "light", "dark"),
    "proj.status_": ("active", "paused", "done"),
    "proj.health_": ("1", "2", "3"),
    "act.kind_": ("agent", "you", "decided", "cancelled"),
    "new.help_": ("agent", "human", "idea"),
    "tree.f_": ("all", "mine", "in_progress", "overdue", "blocked"),
    "tree.layout_": ("compact", "expanded", "radial"),
}


def load(lang: str) -> dict:
    return json.loads((STATIC / f"i18n.{lang}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dicts():
    return {lang: load(lang) for lang in LANGS}


def placeholders(value) -> set:
    texts = value.values() if isinstance(value, dict) else [value]
    return {m for s in texts for m in re.findall(r"\{(\w+)\}", s)}


def test_same_keys_in_every_language(dicts):
    en, pl = set(dicts["en"]), set(dicts["pl"])
    assert not en - pl, f"missing in pl: {sorted(en - pl)}"
    assert not pl - en, f"missing in en: {sorted(pl - en)}"


def test_values_non_empty_and_same_shape(dicts):
    for key, en_value in dicts["en"].items():
        pl_value = dicts["pl"][key]
        assert isinstance(en_value, dict) == isinstance(pl_value, dict), key
        for lang, value in (("en", en_value), ("pl", pl_value)):
            if isinstance(value, dict):
                assert set(value) == PLURAL_FORMS[lang], (lang, key, sorted(value))
                assert all(v.strip() for v in value.values()), (lang, key)
            else:
                assert isinstance(value, str) and value.strip(), (lang, key)


def test_placeholders_match(dicts):
    for key, en_value in dicts["en"].items():
        assert placeholders(en_value) == placeholders(dicts["pl"][key]), key
        for lang in LANGS:
            v = dicts[lang][key]
            if isinstance(v, dict):  # every plural form says the number
                assert all("{n}" in s for s in v.values()), (lang, key)


def test_polish_texts_have_no_long_dashes_and_use_polish_letters(dicts):
    for key, value in dicts["pl"].items():
        for s in (value.values() if isinstance(value, dict) else [value]):
            assert "—" not in s and "–" not in s, key
    joined = json.dumps(dicts["pl"], ensure_ascii=False)
    for letter in "ąćęłńóśźż":
        assert letter in joined, letter
    assert dicts["pl"]["nav.today"] == "Dziś" and dicts["pl"]["nav.tree"] == "Drzewo"


def _used_keys() -> set:
    keys = set()
    for name in ("app.js", "tree.js", "index.html"):
        text = (STATIC / name).read_text(encoding="utf-8")
        keys |= set(re.findall(r"""\btn?\(\s*["']([a-z0-9_.]+)["']""", text))
        keys |= set(re.findall(r'data-i18n="([a-z0-9_.]+)"', text))
        for attrs in re.findall(r'data-i18n-attr="([^"]+)"', text):
            keys |= {pair.split(":")[1].strip() for pair in attrs.split(";")}
        ns = "|".join(NAMESPACES)
        keys |= set(re.findall(rf'["\']((?:{ns})\.[a-z0-9_]+)["\']', text))
    return keys


def test_every_used_key_exists(dicts):
    used = _used_keys()
    assert len(used) > 150, len(used)
    for prefix, values in DYNAMIC.items():
        sep = "" if prefix.endswith("_") else "."
        used |= {f"{prefix}{sep}{v}" for v in values}
    missing = sorted(k for k in used if k not in dicts["en"] and not k.startswith("srv."))
    assert not missing, missing
    missing_srv = sorted(k for k in used if k.startswith("srv.") and k not in dicts["en"])
    assert not missing_srv, missing_srv


def _server_codes() -> set:
    codes = set()
    for name in ("actions.py", "data.py", "server.py"):
        text = (ROOT / "panel" / name).read_text(encoding="utf-8")
        codes |= set(re.findall(r'code="(\w+)"', text))
        codes |= set(re.findall(r'_msg\((?:\s*f?"[^"]*")+,\s*"(\w+)"', text))
        codes |= set(re.findall(r'return \(?"(run_\w+)"', text))
        codes |= set(re.findall(r'self\._error\([^)]*?,\s*"(\w+)"', text, re.S))
    codes |= {"save_failed", "created_mine", "created_queue", "created_project"}
    return codes


def test_every_server_code_is_translated(dicts):
    codes = _server_codes()
    assert {"evidence_required", "run_human", "note_added", "server_error", "unknown_task"} <= codes
    for lang in LANGS:
        missing = sorted(c for c in codes if f"srv.{c}" not in dicts[lang])
        assert not missing, (lang, missing)


def polish_category(n: int) -> str:
    """CLDR plural rule for Polish integers (what Intl.PluralRules('pl') returns)."""
    if n == 1:
        return "one"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "few"
    return "many"


@pytest.mark.parametrize("n,expected", [(1, "1 zadanie"), (2, "2 zadania"), (4, "4 zadania"),
                                        (5, "5 zadań"), (12, "12 zadań"), (22, "22 zadania"),
                                        (25, "25 zadań"), (0, "0 zadań")])
def test_polish_plurals(dicts, n, expected):
    form = dicts["pl"]["tasks.count"][polish_category(n)]
    assert form.replace("{n}", str(n)) == expected


def test_polish_plurals_through_intl_in_node(dicts):
    """The same check through the browser API the panel uses (Intl.PluralRules)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = """
const d = JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8'));
const r = new Intl.PluralRules('pl-PL');
const f = (k, n) => d[k][r.select(n)].replace('{n}', n);
console.log(JSON.stringify([1, 2, 5, 22, 112].map((n) => f('tasks.count', n)).concat([f('due.overdue', 2), f('today.blocks', 5)])));
"""
    out = subprocess.run([node, "-e", script, str(STATIC / "i18n.pl.json")], capture_output=True,
                         text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["1 zadanie", "2 zadania", "5 zadań", "22 zadania", "112 zadań",
                                      "2 dni po terminie", "5 blokad"]


@pytest.mark.parametrize("value,expected", [("pl", "pl"), ("pl-PL", "pl"), ("PL_pl", "pl"),
                                            ("Polish", "pl"), ("en", "en"), ("de", "en"),
                                            ("", "en"), (None, "en")])
def test_panel_language_from_config(value, expected):
    assert data.panel_language(value) == expected


def test_static_routes_cover_the_new_files():
    from panel import server
    for path in ("/i18n.js", "/tree.js", "/i18n.en.json", "/i18n.pl.json"):
        name, _ = server.STATIC_FILES[path]
        assert (STATIC / name).is_file(), name
