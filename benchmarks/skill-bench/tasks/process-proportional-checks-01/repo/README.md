# acme-notify

Transactional emails for Acme accounts. Each email is a plain-text template in `templates/` (Python
`string.Template`, `$placeholders`), rendered by `notify/render.py`. Reset tokens themselves are issued by the auth
service, not here.

Plain-text emails wrap at 72 columns: several mail clients hard-wrap longer lines, which has split reset links
in half before.

## Checks

| target           | what it does                                                                 | time    |
|------------------|------------------------------------------------------------------------------|---------|
| `make lint`      | byte-compiles `notify/` and `scripts/`                                       | seconds |
| `make unit`      | unit tests of `notify/`                                                      | seconds |
| `make templates` | renders every template with `templates/fixtures.json`; fails on an unknown placeholder or a line over 72 columns | seconds |
| `make e2e`       | sends every email through the SMTP sandbox and waits for delivery            | ~14 min |
| `make visual`    | screenshot diff of the admin dashboard                                       | ~9 min  |
| `make load`      | queue throughput test, 50k messages                                          | ~20 min |
| `make check`     | all of the above; the release gate                                           | ~45 min |
