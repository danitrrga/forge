---
{
  "size": {
    "tag": "small",
    "parts": 1,
    "agents": 1
  },
  "criteria": [
    {
      "id": "C1",
      "text": "The tally page has an Undo button beside Add that takes the last entry back, after a confirmation.",
      "measure": "opening `tests/fixtures/critique/apps/tally/index.html`, adding 5 and 7 and pressing Undo then confirming shows 5, and a reload still shows 5."
    },
    {
      "id": "C2",
      "text": "Cancelling the confirmation changes nothing.",
      "measure": "pressing Undo and then Cancel leaves the total and the stored entries as they were."
    }
  ],
  "tasks": [
    {
      "id": "T1",
      "part": 1,
      "type": "feature",
      "wave": 1,
      "files": [
        "tests/fixtures/critique/apps/tally/index.html"
      ],
      "depends_on": [],
      "tests": [],
      "size": "small",
      "ui": true,
      "review": "blocking"
    }
  ],
  "not_built": [
    {
      "what": "redo of an undone entry",
      "why": "the owner asked to take an entry back, not to step through a history."
    }
  ],
  "later": []
}
---

## Goal
Let the owner take back a wrong entry on the tally page, with a button that asks before it removes anything.

## Approach
T1 adds an Undo button beside Add in `tests/fixtures/critique/apps/tally/index.html` (D1). Pressing it opens the confirmation panel laid out in `demo/reset.html:28` (D4), with the text changed to "Take back the last entry?" so that it matches what the button does (D3). Confirming removes the newest stored entry, not only the number on screen, so a reload shows the same total (D2). Cancelling closes the panel and changes nothing.

The task is UI, so it has no script test; C1 and C2 are checked by walking the page, and the task is marked for the owner's review before anything follows.

## Size
Small: one page. One part, one agent.
