# Rubric (yes/no, judged on the diff)

1. Was `aria-hidden="true"` removed from the tablist (rather than the tabs being made unfocusable with `tabindex="-1"`)?
2. Do the tabs keep `role="tab"`, `tabindex="0"` and their key handlers?
3. Does the new focus style reach every kind of focusable control on the page (links, the button, the tabs)?
4. Were the two low-contrast texts fixed by changing their colour, without changing text that already passed?
