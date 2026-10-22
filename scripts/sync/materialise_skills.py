#!/usr/bin/env python3
"""materialise_skills.py -- rebuild the online skills of config/toolchain.json into skills/ (forge/skillpins.py).
Dry-run unless --apply; the `online skills` step of `forge skills`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from forge import skillpins  # noqa: E402

if __name__ == "__main__":
    sys.exit(skillpins.main(sys.argv[1:]))
