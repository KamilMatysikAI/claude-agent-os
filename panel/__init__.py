"""Optional local web panel for agentos (stdlib only, no build step).

Start it with `python -m panel --workspace PATH` or `python -m agentos panel`.
It has no login: keep it on 127.0.0.1 (see SECURITY note in server.py).
"""

from .server import main, make_server, serve  # noqa: F401
