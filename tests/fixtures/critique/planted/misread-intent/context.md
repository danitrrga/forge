# Context: 01-ui-reset

## Intent
"On the tally page I want a button that puts the total back to zero, for when I start a new count. It must ask me first, because I will hit it by mistake."

## What success means
The tally page (`tests/fixtures/critique/apps/tally/index.html`) has a Reset button beside Add. Pressing it opens a confirmation. Confirming empties every stored entry, so the total reads 0 and stays 0 after a reload. Cancelling changes nothing.

## Surfaces
`ui`

## Approved UI
`demo/reset.html`: the page with the Reset button and its confirmation panel.

## Research
None.
