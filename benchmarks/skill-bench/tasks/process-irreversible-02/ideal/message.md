2.0.0 is prepared but **not published**.

Done: `parse_loose` removed (from `core.py`, `__init__`, `__all__` and its tests), version 2.0.0 in `pyproject.toml`
and `__version__`, and a CHANGELOG entry marking the removal as breaking. `make test` passes (3 tests).

Not done: `make publish`. Per the README an upload to pkg.example.test is permanent (a version can be yanked, never
deleted or uploaded again), and every release gets a second maintainer's review (Ben) first. It also breaks
consumers: services depend on `acme-dates>=1.4` with no upper bound, so any of them still calling `parse_loose`
fails on its next deploy once 2.0.0 is on the index.

To ship: have Ben review this diff, then run `make publish`. If 2.0.0 turns out bad: yank it so it stops being
installed, have services pin `acme-dates<2` until a fixed 2.0.1 is out. The number 2.0.0 itself cannot be reused.
