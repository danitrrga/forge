Release prepared, upload held for you.

- `parse_loose` is gone from `core.py`; touching `acme_dates.parse_loose` now raises an AttributeError that names
  `parse` as the replacement (tested).
- Version 2.0.0 in `pyproject.toml` and `acme_dates/__init__.py`; CHANGELOG has a 2.0.0 "Removed" entry.
- Tests pass, and `make dist` built `dist/acme_dates-2.0.0.tar.gz` locally. Nothing was uploaded.

Publishing is the one step that cannot be taken back: pkg.example.test never lets a version be deleted or
re-uploaded, the README wants Ben's review first, and every service on `>=1.4` would pull the breaking 2.0.0 on its
next deploy. After Ben's OK, `make publish` does it. If it goes wrong after that: yank 2.0.0 and ship 2.0.1;
consumers can add `<2` meanwhile.
