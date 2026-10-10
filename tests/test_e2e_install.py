"""End to end: a clean install with the demo, then every CLI step a new user runs.

The installer creates `<ws>/.agentos/venv` and pip-installs the engine into it (a normal,
not editable install). Building the package may download setuptools; without network the
installer links the repo into the venv instead, and every command here works the same way.
The offline path is also tested on its own (pip pointed at a dead index).

No model call: `claude` is replaced by a stub on PATH that only answers `--version`, the
queue is never scheduled (`--no-schedule`), `run` is a `--dry-run`, and the panel listens on
a free loopback port (never the default one).
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PANEL_PORT = 8777


def _fake_claude(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text("@echo 0.0.0 (stub, no model call)\n", encoding="utf-8")
    else:
        stub = bin_dir / "claude"
        stub.write_text("#!/bin/sh\necho '0.0.0 (stub, no model call)'\n", encoding="utf-8")
        stub.chmod(0o755)


def _env(bin_dir: Path, **extra) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + str(Path(sys.executable).parent)
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        env["PATH"] += os.pathsep + str(Path(system_root) / "System32")
    env.pop("PYTHONPATH", None)
    env.update({"PYTHONIOENCODING": "utf-8", **extra})
    return env


def _run(args, cwd: Path, env: dict, ok: bool = True, python=None,
         timeout: int = 120) -> subprocess.CompletedProcess:
    res = subprocess.run([str(python or sys.executable), *args], cwd=str(cwd), env=env,
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout)
    if ok:
        assert res.returncode == 0, f"{args}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    return res


def _free_port() -> int:
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != DEFAULT_PANEL_PORT:
            return port
    raise RuntimeError("no free port")


def _get(port: int, path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _snapshot(ws: Path) -> dict:
    return {p.relative_to(ws).as_posix(): p.read_bytes()
            for p in ws.rglob("*.md") if ".agentos" not in p.parts}


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e")
    bin_dir, ws = root / "bin", root / "ws"
    _fake_claude(bin_dir)
    env = _env(bin_dir)
    res = _run(["install.py", "--non-interactive", "--workspace", str(ws), "--with-demo",
                "--no-schedule", "--panel"], REPO, env, timeout=600)
    sys.path.insert(0, str(REPO))
    from agentos import env as engine_env
    return {"root": root, "ws": ws, "env": env, "bin": bin_dir, "install_out": res.stdout,
            "py": engine_env.venv_python(ws)}


def test_install_report(installed):
    out, ws = installed["install_out"], installed["ws"]
    assert "conflicts: 0" in out and "Next steps:" in out
    assert installed["py"].is_file(), out
    assert "engine installed in" in out or "Linked the repo folder" in out, out
    assert "-P -m agentos panel" in out
    # the build ran on a staged copy: nothing written into the repo
    assert not (REPO / "build").exists() and not list(REPO.glob("*.egg-info"))
    claude_md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "{{engine}}" not in claude_md and ".agentos/venv/" in claude_md
    skill = (ws / ".claude/skills/project/SKILL.md").read_text(encoding="utf-8")
    assert "{{engine}}" not in skill and "-P -m agentos" in skill
    for rel in ("agentos.toml", "CLAUDE.md", "TODO.md", ".claude/agents/ceo.md",
                "ideas/.templates/idea.md", "projects/coffee-shop/PROJECT.md",
                "projects/podcast-launch/PROJECT.md", "inbox/summarise-roaster-email.md"):
        assert (ws / rel).is_file(), rel
    assert not (ws / "README.md").exists()          # demo README stays in the package
    cfg = (ws / "agentos.toml").read_text(encoding="utf-8")
    assert "[panel]\nenabled = true" in cfg and "[queue]\nenabled = false" in cfg
    assert not (ws / ".agentos" / "tick.py").exists()  # nothing scheduled


def test_venv_engine_from_the_workspace_without_pythonpath(installed):
    """The documented command: `<ws>/.agentos/venv/.../python -P -m agentos`, cwd = workspace,
    no PYTHONPATH. With a normal install the package comes from the venv, not the repo."""
    ws, env, py = installed["ws"], installed["env"], installed["py"]
    assert "PYTHONPATH" not in env
    dash = _run(["-P", "-m", "agentos", "dashboard"], ws, env, python=py)
    assert "dashboard: " in dash.stdout
    where = _run(["-P", "-c", "import agentos, panel; print(agentos.__file__)"], ws, env,
                 python=py).stdout.strip()
    if "engine installed in" in installed["install_out"]:
        assert Path(where).resolve().is_relative_to((ws / ".agentos" / "venv").resolve()), where
        files = _run(["-P", "-c", "from agentos import runner; from panel import actions as a; "
                      "import panel, pathlib; print(runner.PACKAGE_PROFILES / 'safe.json'); "
                      "print(a.PACKAGED_IDEA_TEMPLATE); print(a.IDEAS_INDEX_SCRIPT); "
                      "print(pathlib.Path(panel.__file__).parent / 'static' / 'app.js')"],
                     ws, env, python=py).stdout.splitlines()
        for f in filter(None, (x.strip() for x in files)):
            assert Path(f).is_file() and ".agentos" in Path(f).parts, f
    # a planted package in the workspace never shadows the engine (-P)
    (ws / "agentos").mkdir()
    (ws / "agentos" / "__init__.py").write_text("raise SystemExit('shadowed')\n", encoding="utf-8")
    try:
        assert "podcast-launch" in _run(["-P", "-m", "agentos", "status"], ws, env, python=py).stdout
    finally:
        (ws / "agentos" / "__init__.py").unlink()
        (ws / "agentos").rmdir()
    doctor = _run(["-P", "-m", "agentos", "doctor"], ws, env, python=py)
    assert "[FAIL]" not in doctor.stdout and "engine" in doctor.stdout


def test_cli_steps(installed):
    ws, env, py = installed["ws"], installed["env"], installed["py"]
    wsa = ["--workspace", str(ws)]
    doctor = _run(["-P", "-m", "agentos", "doctor", *wsa], ws, env, python=py)
    assert "[FAIL]" not in doctor.stdout and "stub" in doctor.stdout

    before = _snapshot(ws)
    guard = _run(["-P", "-m", "agentos", "guard", *wsa], ws, env, python=py)
    assert guard.stdout.strip() == ""                 # the shipped demo is a fixed point
    assert _snapshot(ws) == before

    dash = _run(["-P", "-m", "agentos", "dashboard", *wsa], ws, env, python=py)
    assert "dashboard: " in dash.stdout
    text = (ws / "projects" / "dashboard.md").read_text(encoding="utf-8")
    assert "## Decisions waiting for" in text and "Home-brewing podcast" in text
    assert "<!-- AGENTOS:START -->" in (ws / "TODO.md").read_text(encoding="utf-8")

    status = _run(["-P", "-m", "agentos", "status", *wsa], ws, env, python=py)
    assert "coffee-shop [active]" in status.stdout and "podcast-launch [active]" in status.stdout

    dry = _run(["-P", "-m", "agentos", "run", "--dry-run", *wsa], ws, env, python=py)
    assert "--dangerously-skip-permissions" not in dry.stdout
    assert "safe.json" in dry.stdout and '"-p"' in dry.stdout
    assert not list((ws / ".agentos" / "locks").glob("*.lock"))


def test_fallback_with_pythonpath(installed):
    """Fallback without the venv (--no-venv, or venv creation failed): system python with the
    package folder on PYTHONPATH, also with -P (cwd off sys.path)."""
    ws = installed["ws"]
    env = _env(installed["bin"], PYTHONPATH=str(REPO))
    res = _run(["-P", "-m", "agentos", "status"], ws, env)
    assert "podcast-launch" in res.stdout
    res = _run(["-P", "-m", "agentos", "panel", "--help"], ws, env)
    assert "--port" in res.stdout


def test_panel_serves_every_get_endpoint(installed):
    ws, env = installed["ws"], installed["env"]
    port = _free_port()
    proc = subprocess.Popen([str(installed["py"]), "-P", "-m", "agentos", "panel",
                             "--port", str(port)], cwd=str(ws), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 20
        while True:
            try:
                if _get(port, "/api/meta")[0] == 200:
                    break
            except OSError:
                pass
            assert proc.poll() is None, proc.stdout.read().decode("utf-8", "replace")
            assert time.time() < deadline, "panel did not start"
            time.sleep(0.2)

        for path in ("/", "/index.html", "/app.js", "/styles.css", "/favicon.svg"):
            status, body = _get(port, path)
            assert status == 200 and body, path
        payloads = {}
        for path in ("/api/meta", "/api/today", "/api/decisions", "/api/projects", "/api/tree",
                     "/api/activity", "/api/activity?since=2000-01-01&archive=1",
                     "/api/tasks?scope=open", "/api/tasks?scope=recent", "/api/tasks?scope=all"):
            status, body = _get(port, path)
            assert status == 200, path
            payloads[path] = json.loads(body)
        slugs = [p["slug"] for p in payloads["/api/projects"]["items"]]
        assert set(slugs) >= {"coffee-shop", "podcast-launch"}
        for slug in slugs:
            assert _get(port, f"/api/project/{slug}")[0] == 200, slug
        keys = [s["key"] for s in payloads["/api/tasks?scope=all"]["items"]]
        assert len(keys) >= 30
        for key in keys:
            assert _get(port, f"/api/task/{key}")[0] == 200, key
        assert _get(port, "/api/pending/0000")[0] == 404
        assert _get(port, "/api/project/does-not-exist")[0] == 404
        assert _get(port, "/api/nope")[0] == 404
        assert len(payloads["/api/decisions"]["items"]) == 4
        tree = {p["slug"]: p for p in payloads["/api/tree"]["projects"]}

        def depth(node):
            return 1 + max((depth(c) for c in node["children"]), default=0)
        assert max(depth(c) for c in tree["podcast-launch"]["chains"]) >= 3
        assert max(depth(c) for c in tree["coffee-shop"]["chains"]) >= 3
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        if proc.stdout:
            proc.stdout.close()


def test_readme_links_to_local_files_exist():
    import re
    text = (REPO / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(((?:docs|demo|template)/[^)#\s]+)\)", text)
    assert any(t.startswith("docs/screenshots/") for t in targets)
    missing = [t for t in targets if not (REPO / t).exists()]
    assert not missing, missing


def test_offline_install_links_the_repo(tmp_path):
    """pip cannot reach any index: the installer says so and links the repo into the venv;
    the documented command still works from the workspace without PYTHONPATH."""
    sys.path.insert(0, str(REPO))
    import install
    from agentos import env as engine_env

    ws = tmp_path / "ws"
    ws.mkdir()
    lines = []
    res = install.setup_engine(ws, out=lines.append, pip_args=(
        "--index-url", "http://127.0.0.1:9/simple", "--retries", "0", "--timeout", "2"))
    py = engine_env.venv_python(ws)
    assert py.is_file(), res
    if res["mode"] == "installed":
        pytest.skip("setuptools already in the venv: the offline build succeeded")
    assert res["mode"] == "linked", res
    assert "Re-run install.py when online" in res["message"]
    env = _env(tmp_path / "bin")
    where = _run(["-P", "-c", "import agentos; print(agentos.__file__)"], ws, env, python=py)
    assert Path(where.stdout.strip()).resolve().is_relative_to(REPO.resolve())
