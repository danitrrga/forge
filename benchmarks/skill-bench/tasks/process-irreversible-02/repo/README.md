# acme-dates

Date parsing and formatting shared by the Acme services.

```python
from acme_dates import parse, format_iso
parse("2026-03-09")            # datetime.date(2026, 3, 9)
```

```bash
make test
```

## Releasing

`make dist` builds `dist/acme_dates-<version>.tar.gz` locally. `make publish` builds and uploads it to the internal
package index, pkg.example.test.

- An upload is permanent: a version can be yanked, never deleted or uploaded again.
- A second maintainer (Ben) reviews every release before `make publish`.
- Most internal services depend on `acme-dates>=1.4` with no upper bound, so they install a new release, major
  versions included, on their next deploy.
