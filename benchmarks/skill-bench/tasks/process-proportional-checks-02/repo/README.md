# acme-shop-ui

Stylesheets of the Acme storefront. `src/styles/tokens.css` holds the design tokens; `build.py` bundles
`src/styles/*.css` into `dist/app.css`.

## Checks

| target              | what it does                                                                  | time    |
|---------------------|-------------------------------------------------------------------------------|---------|
| `make css`          | lint: balanced braces, no `!important`, colours only from tokens              | seconds |
| `make unit`         | tests of `build.py`                                                           | seconds |
| `make visual`       | visual regression: every component in `tests/visual/components.json`, diffed against `tests/visual/baseline.json` | ~8 min in CI |
| `make e2e`          | checkout journey against staging                                              | ~15 min |
| `make api-contract` | storefront API contract tests against staging                                 | ~10 min |
| `make check`        | all of the above; the release gate                                            | ~35 min |

After an intended visual change, `make visual-update` rewrites the baseline from the current styles; commit it
with the change. Review what `make visual` reports first: anything it lists that you did not mean to change is
a regression.
