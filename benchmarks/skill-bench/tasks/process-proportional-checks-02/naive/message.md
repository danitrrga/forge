Added `border-radius: 8px` to `.btn-primary` in `src/styles/buttons.css`. Secondary buttons still inherit the 4px radius from `.btn`.

`make css` and `make unit` pass. I skipped the slow suites (visual, e2e, api-contract) since this is a one-line CSS change.
