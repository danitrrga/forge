#!/usr/bin/env python3
"""The agent-config generator: forge/sync.py's agent_config(), run from the path forge/cli.py,
rotate_secret.py, register_project.py and every doc name. Dry-run by default; --apply writes."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from forge import sync  # noqa: E402
sys.exit(sync.agent_config(sys.argv[1:]))
