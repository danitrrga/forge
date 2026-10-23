Done. I added a `--radius-lg: 8px` token next to `--radius` in `tokens.css` and pointed `.btn-primary` at it, so the shared `.btn` rule and every other component stay at 4px.

Checks:
- `make visual` reported `button-primary` and `button-primary:hover` going from 4px to 8px, and nothing else. Those are the two intended changes, so I updated those two entries in `tests/visual/baseline.json`. `make visual` now passes, 5 of 5 components.
- `make css`: ok.

I didn't run e2e or api-contract. They take about 25 minutes against staging, and a corner radius can't affect a checkout flow or an API contract, so they're left for the release gate.
