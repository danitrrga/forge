Primary buttons now have 8px corners: `.btn-primary` in `src/styles/buttons.css` overrides the shared `.btn` radius with `border-radius: 8px`. `.btn` and the `--radius` token are unchanged, so secondary buttons, inputs and cards keep 4px.

Ran:
- `make css`: ok.
- `make visual`: failed as expected, with exactly two differences: `button-primary` and `button-primary:hover`, `border-radius 4px -> 8px`. Nothing else moved, so I ran `make visual-update` and `make visual` again: `visual ok (5 components match the baseline)`. The updated `tests/visual/baseline.json` is part of the change.

Not run: `make e2e` (~15 min) and `make api-contract` (~10 min). Both run against staging and test behaviour and API contracts that a stylesheet can't change. `make unit` was not run either: it covers `build.py`, which I didn't touch.
