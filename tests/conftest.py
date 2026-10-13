"""Tests never talk to the network: the panel's daily new-version check is switched off."""

import os

os.environ["AGENTOS_NO_UPDATE_CHECK"] = "1"
