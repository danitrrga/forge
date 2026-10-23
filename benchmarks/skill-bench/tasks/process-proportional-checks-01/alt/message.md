Done. The reset email now reads "open the link below within 30 minutes to pick a new password", which keeps the paragraph within the 72-column limit without a dangling word.

Checks I ran:
- `make templates`: passes (3 templates rendered, no line over 72). The first attempt, a plain word swap, made a 74-column line and this gate caught it.
- `make lint`, `make unit`: pass (cheap, for completeness).

Left for the release gate, not run: e2e (SMTP sandbox, ~14 min), visual (dashboard screenshots, ~9 min) and load (~20 min). A copy change in one template can't move any of them.
