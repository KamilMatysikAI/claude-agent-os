"""New-version check: comparison, cache, off switch, fail-safe. No network."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentos import config, updates  # noqa: E402

ON = {"updates": {"check": True}}


def test_version_comparison():
    assert updates.is_newer("v0.2.0", "0.1.0")
    assert updates.is_newer("0.1.1", "0.1")
    assert updates.is_newer("1.0", "0.9.9")
    assert not updates.is_newer("0.1.0", "0.1.0")
    assert not updates.is_newer("v0.1", "0.1.0")
    assert not updates.is_newer("0.0.9", "0.1.0")
    for junk in ("", None, "latest", "<script>"):
        assert not updates.is_newer(junk, "0.1.0")
        assert not updates.is_newer("0.2.0", junk)


def test_status_reads_cache_only(tmp_path, monkeypatch):
    monkeypatch.delenv(updates.ENV_OFF, raising=False)
    assert updates.status(tmp_path, ON, current="0.1.0") == {
        "enabled": True, "available": False, "latest": "", "url": updates.RELEASES_URL}
    updates.refresh(tmp_path, fetch=lambda: {"version": "0.2.0", "url": updates.RELEASES_URL + "/tag/v0.2.0"},
                    now=lambda: 1000)
    s = updates.status(tmp_path, ON, current="0.1.0")
    assert s["available"] and s["latest"] == "0.2.0" and s["url"].endswith("/tag/v0.2.0")
    assert not updates.status(tmp_path, ON, current="0.2.0")["available"]


def test_foreign_url_in_cache_is_replaced(tmp_path, monkeypatch):
    monkeypatch.delenv(updates.ENV_OFF, raising=False)
    (tmp_path / ".agentos").mkdir()
    (tmp_path / ".agentos" / updates.CACHE_NAME).write_text(
        '{"checked_at": 1, "version": "9.9.9", "url": "https://example.com/x"}', encoding="utf-8")
    assert updates.status(tmp_path, ON, current="0.1.0")["url"] == updates.RELEASES_URL


def test_failed_fetch_keeps_last_version_and_moves_timestamp(tmp_path):
    updates.refresh(tmp_path, fetch=lambda: {"version": "0.2.0", "url": updates.RELEASES_URL}, now=lambda: 1000)
    data = updates.refresh(tmp_path, fetch=lambda: {}, now=lambda: 5000)
    assert data == {"checked_at": 5000, "version": "0.2.0", "url": updates.RELEASES_URL}
    assert not updates.is_stale(data, now=lambda: 5000 + updates.TTL_SECONDS - 1)
    assert updates.is_stale(data, now=lambda: 5000 + updates.TTL_SECONDS)
    assert updates.is_stale({}) and updates.is_stale({"checked_at": "x"})


def test_off_switches(tmp_path, monkeypatch):
    monkeypatch.delenv(updates.ENV_OFF, raising=False)
    off = {"updates": {"check": False}}
    assert updates.enabled(ON) and updates.enabled({}) and not updates.enabled(off)
    assert updates.status(tmp_path, off)["enabled"] is False
    assert updates.refresh_async(tmp_path, off) is False
    monkeypatch.setenv(updates.ENV_OFF, "1")
    assert not updates.enabled(ON)
    assert updates.refresh_async(tmp_path, ON) is False
    assert not (tmp_path / ".agentos" / updates.CACHE_NAME).exists()


def test_broken_cache_never_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(updates.ENV_OFF, raising=False)
    (tmp_path / ".agentos").mkdir()
    (tmp_path / ".agentos" / updates.CACHE_NAME).write_text("not json", encoding="utf-8")
    assert updates.read_cache(tmp_path) == {}
    assert updates.status(tmp_path, ON)["available"] is False


def test_config_default_and_old_config():
    cfg = config.normalize(config._merge(config.DEFAULTS, {}))
    assert cfg["updates"]["check"] is True
    cfg = config.normalize(config._merge(config.DEFAULTS, {"updates": {"check": False}}))
    assert cfg["updates"]["check"] is False
    cfg = config.normalize(config._merge(config.DEFAULTS, {"updates": "nonsense"}))
    assert cfg["updates"]["check"] is True
