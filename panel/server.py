"""Local web panel for an agentos workspace.

    python -m panel --workspace PATH [--host 127.0.0.1] [--port 8777]

SECURITY: the panel has NO authentication by design. It binds to 127.0.0.1 by default
and must never be exposed to the public internet. For phone access use a private
network you control (for example a VPN or a tailnet) and add that hostname to
`[panel] allowed_hosts` in agentos.toml. Requests with any other Host header are refused,
which also blocks DNS-rebinding attacks from web pages you visit. Writes accept only
`application/json` from the same origin, so a foreign page cannot post a form to it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import socketserver
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

if __package__ in (None, ""):  # `python panel/server.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import core, updates  # noqa: E402

from panel import actions, data  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/tree.js": ("tree.js", "text/javascript; charset=utf-8"),
    "/i18n.en.json": ("i18n.en.json", "application/json; charset=utf-8"),
    "/i18n.pl.json": ("i18n.pl.json", "application/json; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
GZIP_MIN = 16 * 1024
MAX_BODY = 512 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


class PanelState:
    def __init__(self, workspace: Path, cfg: dict, undo_seconds: float = actions.UNDO_SECONDS,
                 spawn=None):
        self.ws = data.Workspace(workspace, cfg)
        self.pending = actions.Pending(self.ws, delay=undo_seconds)
        self.spawn = spawn
        panel_cfg = cfg.get("panel", {}) if isinstance(cfg.get("panel"), dict) else {}
        extra = panel_cfg.get("allowed_hosts", [])
        self.allowed_hosts = {h.lower() for h in LOOPBACK}
        self.allowed_hosts.add(str(panel_cfg.get("host", "127.0.0.1")).lower())
        if isinstance(extra, list):
            self.allowed_hosts.update(str(h).lower() for h in extra)


class Handler(BaseHTTPRequestHandler):
    server_version = "agentos-panel"
    protocol_version = "HTTP/1.1"
    state: PanelState  # set on the subclass by make_server

    def log_message(self, fmt, *args):  # quiet console; errors go to .agentos/logs
        pass

    # ── responses ─────────────────────────────────────────────────────────────
    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store"):
        gz = (len(body) > GZIP_MIN
              and "gzip" in (self.headers.get("Accept-Encoding") or "").lower())
        if gz:
            body = gzip.compress(body, compresslevel=6)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                             "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str, code: str = "", params: dict | None = None):
        # `code` + `params` let the panel translate the message (keys `srv.<code>`)
        self._json({"ok": False, "error": message, "code": code, "params": params or {}}, status)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        if host.startswith("["):
            name = host.split("]")[0] + "]"
        else:
            name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return name in self.state.allowed_hosts

    # ── routing ───────────────────────────────────────────────────────────────
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Unknown host. Add it to [panel] allowed_hosts.")
        try:
            parts = urlsplit(self.path)
            path = parts.path
            qs = parse_qs(parts.query)
            if path in STATIC_FILES:
                return self._static(path)
            if not path.startswith("/api/"):
                return self._error(HTTPStatus.NOT_FOUND, "Not found.")
            return self._api_get(path[len("/api/"):], qs)
        except Exception as exc:  # noqa: BLE001
            core.log(self.state.ws.root, "panel", f"GET {self.path} failed: {exc!r}")
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                               "The panel hit an error. See .agentos/logs/panel.log.", "server_error")

    def _static(self, path: str):
        name, ctype = STATIC_FILES[path]
        try:
            body = (STATIC_DIR / name).read_bytes()
        except OSError:
            return self._error(HTTPStatus.NOT_FOUND, "Missing static file.")
        self._send(200, body, ctype, cache="no-cache")

    def _api_get(self, route: str, qs: dict):
        ws = self.state.ws
        one = lambda name, default="": (qs.get(name) or [default])[0]  # noqa: E731
        if route == "meta":
            updates.refresh_async(ws.root, ws.cfg)   # at most one anonymous request a day, off in agentos.toml
            return self._json(data.meta_payload(ws))
        if route == "today":
            return self._json(data.today_payload(ws))
        if route == "decisions":
            return self._json(data.decisions_payload(ws))
        if route == "projects":
            return self._json(data.projects_payload(ws))
        if route == "tree":
            return self._json(data.tree_payload(ws))
        if route == "orgtree":
            return self._json(data.org_tree_payload(ws))
        if route.startswith("project/"):
            slug = unquote(route[len("project/"):])
            payload = data.project_payload(ws, slug)
            if payload is None:
                return self._error(HTTPStatus.NOT_FOUND, "Unknown project.", "unknown_project")
            return self._json(payload)
        if route == "activity":
            since = actions.parse_since(one("since"))
            return self._json(data.activity_payload(ws, since, archive=one("archive") == "1"))
        if route == "tasks":
            scope = one("scope", "open")
            if scope not in ("open", "recent", "all"):
                return self._error(HTTPStatus.BAD_REQUEST, "scope must be open, recent or all.")
            return self._json(data.tasks_payload(ws, scope))
        if route.startswith("task/"):
            key = unquote(route[len("task/"):])
            if not data.valid_key(key):
                return self._error(HTTPStatus.NOT_FOUND, "Unknown task.", "unknown_task")
            entry = ws.find(key)
            if entry is None:
                return self._error(HTTPStatus.NOT_FOUND, "Unknown task.", "unknown_task")
            return self._json(data.task_payload(ws, entry))
        if route.startswith("pending/"):
            item = self.state.pending.get(route[len("pending/"):])
            if item is None:
                return self._error(HTTPStatus.NOT_FOUND, "Unknown action.")
            return self._json(item)
        return self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Unknown host. Add it to [panel] allowed_hosts.")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
        origin = self.headers.get("Origin")
        if origin:
            o = urlsplit(origin)
            if (o.netloc or "").lower() != (self.headers.get("Host") or "").lower():
                return self._error(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, "Invalid JSON.")
        if not isinstance(payload, dict):
            return self._error(HTTPStatus.BAD_REQUEST, "Send a JSON object.")
        route = urlsplit(self.path).path
        try:
            if route == "/api/actions":
                return self._action(payload)
            if route == "/api/undo":
                item = self.state.pending.undo(str(payload.get("id") or ""))
                return self._json({"ok": True, **item, "message": "Undone."})
            if route == "/api/create":
                result = actions.create(self.state.ws, payload)
                return self._json({"ok": True, **result}, HTTPStatus.CREATED)
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")
        except actions.ActionError as exc:
            return self._error(exc.status, exc.message, exc.code, exc.params)
        except core.LockBusy as exc:
            return self._error(HTTPStatus.CONFLICT, f"The file is busy, try again: {exc}", "file_busy")
        except OSError as exc:
            core.log(self.state.ws.root, "panel", f"POST {route} failed: {exc!r}")
            return self._error(HTTPStatus.CONFLICT,
                               f"Could not save: {exc.strerror or exc}. Another program may hold the file; try again.",
                               "save_locked", {"detail": str(exc.strerror or exc)})
        except Exception as exc:  # noqa: BLE001
            core.log(self.state.ws.root, "panel", f"POST {route} failed: {exc!r}")
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                               "The panel hit an error. See .agentos/logs/panel.log.", "server_error")

    def _action(self, payload: dict):
        action = str(payload.get("action") or "")
        key = payload.get("key")
        entry, params = actions.validate(self.state.ws, action, key, payload)
        if action in actions.DELAYED:
            item = self.state.pending.schedule(action, entry.key, params)
            return self._json({"ok": True, "pending": item,
                               "undo_seconds": self.state.pending.delay}, HTTPStatus.ACCEPTED)
        result = actions.apply_immediate(self.state.ws, action, entry, params,
                                         spawn=self.state.spawn)
        return self._json({"ok": True, **result})


class PanelServer(ThreadingHTTPServer):
    """HTTPServer.server_bind() calls socket.getfqdn(), a reverse DNS lookup that can take many
    seconds on some machines (seen on macOS). The panel never needs its own host name."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def make_server(workspace: Path, host: str | None = None, port: int | None = None,
                undo_seconds: float = actions.UNDO_SECONDS, spawn=None):
    cfg = core.load_config(workspace)
    state = PanelState(Path(workspace), cfg, undo_seconds=undo_seconds, spawn=spawn)
    handler = type("BoundHandler", (Handler,), {"state": state})
    pcfg = cfg.get("panel", {})
    bind_host = host or pcfg.get("host", "127.0.0.1")
    bind_port = pcfg.get("port", 8777) if port is None else port
    state.allowed_hosts.add(str(bind_host).lower())
    httpd = PanelServer((bind_host, bind_port), handler)
    httpd.daemon_threads = True
    httpd.panel_state = state  # type: ignore[attr-defined]
    return httpd


def serve(workspace: Path, host: str | None = None, port: int | None = None) -> int:
    httpd = make_server(workspace, host, port)
    h, p = httpd.server_address[:2]
    if h not in ("127.0.0.1", "::1", "localhost"):
        print(f"WARNING: the panel has no login and is listening on {h}. "
              "Never expose it to the public internet.", file=sys.stderr)
    print(f"Panel: http://{'127.0.0.1' if h in ('0.0.0.0', '') else h}:{p}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.panel_state.pending.flush()  # type: ignore[attr-defined]
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="panel", description="Local web panel for agentos.")
    parser.add_argument("--workspace", help="workspace folder (default: search up from cwd)")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    try:
        ws = core.find_workspace(args.workspace) if args.workspace is None else \
            Path(args.workspace).resolve()
    except Exception as exc:  # noqa: BLE001
        print(exc, file=sys.stderr)
        return 2
    return serve(ws, args.host, args.port)


def run_in_thread(httpd) -> threading.Thread:
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    raise SystemExit(main())
