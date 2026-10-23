`templates/password_reset.txt` now says the link expires in 30 minutes instead of 24 hours.

Swapping the words in place made that line 74 columns, and `make templates` failed on it (`body line 4 is 74 columns (max 72)`). I rewrapped the paragraph so "minutes." starts the next line, and it now passes: `templates ok (3 rendered)`.

Not run: `make e2e` (~14 min), `make visual` (~9 min) and `make load` (~20 min). None of them can be affected by a wording change in one plain-text template; they stay for the release gate. `make lint` and `make unit` were not run either, since no Python changed.
