---
{
  "size": {"tag": "small|normal|big", "parts": 1, "agents": 1},
  "criteria": [
    {"id": "C1", "text": "<what is true when the work is done, in words>", "measure": "<the command or check that shows it, and what it returns>"},
    {"id": "C2", "text": "<a second criterion>", "measure": "<its command or check>"}
  ],
  "tasks": [
    {
      "id": "T1",
      "part": 1,
      "subphase": "<NN.M>-<slug>",
      "type": "bug|refactor|feature",
      "wave": 1,
      "files": ["<path the task writes>"],
      "depends_on": [],
      "tests": [
        {"run": "<the command that runs only this test>", "measures": "<what it measures>", "red": "<the wrong version it is seen failing against, and the failure message>"}
      ],
      "size": "small|normal|big",
      "ui": false,
      "firefox": false,
      "review": "blocking|async"
    }
  ],
  "not_built": [{"what": "<something raised and left out>", "why": "<the reason>"}],
  "later": [{"what": "<something noticed on the way>", "why": "<the reason it waits>"}]
}
---
<!-- referent: none, own text: no source has a plan as a document; the frontmatter is fixed by the plan format -->
<!-- Keep `subphase` only in a phase with subphases. Keep `firefox` only when `ui` is true and the change may behave differently in Firefox. Delete `review` to take the default. -->

## Goal
<What the work achieves, in a paragraph for the owner. Name the problem it solves, not the files it changes.>

## Approach
<How the work is split and in what order. Say which decision from `decisions.tsv` each task carries out.>

## Size
<Why this size, these parts and this many agents. Required when the plan is over the band or has grown since the pre-mortem.>
