"""``python -m agentos.scheduler install|remove|status`` (same as ``python -m agentos schedule ...``)."""
import sys

from . import main

sys.exit(main())
