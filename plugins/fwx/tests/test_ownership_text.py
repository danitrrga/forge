#!/usr/bin/env python3
"""The ownership rule in the texts of agents (principles.md rule 12): one place states it, the rest point to it, and no text still narrows
an agent's scope to its brief.

What this can check is the words, and only the words that carry the owner's rule or that code reads: that rule 12 exists with the owner's
quotes and an enforcer, that no agent text says "leave it" or "report what the diff breaks, not everything wrong in the files it touches",
that each agent file points at the rule, and that the agents which report a defect outside their task name the `outside` item that
`fwx wave report` validates (a report without its shape is rejected there). What happens to an item is checked in code
(test_wave_report.py). Wording beyond that (the words of the escalation, the rubric's dimensions, the hedge on chained commands) is not
pinned here: 09.3 T33 removed those checks with their red logs.

Seen red on copies of the real texts (a copy of plugins/fwx with the pinned words changed; the FAIL line printed):
  playbooks/principles.md with "Enforced by" changed to "Checked by":
    FAIL: principles.md: rule 12 states the ownership rule and its source: got ['principles.md: rule 12 names no enforcer (a rule with none is a guideline, rule 1)'], want []
  agents/executor.md with "You own the result, not only your task" changed to "The bigger picture narrows your scope":
    FAIL: a text still narrows an agent's scope to its brief (state the rule once, in principles.md rule 12, and point at it): got ['agents/executor.md: "narrows your scope"'], want []
  agents/reviewer.md with "rule 12" changed to "rule 11":
    FAIL: each agent file points at rule 12 and the agents that report a defect outside their task name `outside`: got ['agents/reviewer.md does not point at principles.md rule 12'], want []
  agents/reviewer.md with "`outside`" changed to "item":
    FAIL: each agent file points at rule 12 and the agents that report a defect outside their task name `outside`: got ['agents/reviewer.md does not say `outside`'], want []
Controls (each check run on a text with its subject put back, and it must say so): see the `control:` checks.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
RULE = "principles.md rule 12"
# What narrows an agent to its brief. The message of a hit says what to write instead.
NARROWING = [
    ("narrows your scope", "an agent owns the result, not the brief: point at " + RULE),
    ("Report what you saw outside your task and leave it", "a defect seen outside the task is fixed when small, else an `outside` item with its fix"),
    ("no fixes outside", "a small defect outside the task is fixed in its own commit: " + RULE),
    ("not everything wrong in the files it touches", "a reviewer reads the connected code and reports a defect nearby as `outside`"),
    ("scope the brief already forbids", "there is no forbidden scope, only the coordination limits"),
]
TEXT_DIRS = ("agents", "skills", "playbooks", "workflows", "data", "templates")
# The files that point at the rule. The agents that report a defect outside their task also carry the word `outside`: it is the key of the
# item that `fwx wave report` validates, and a report without it is rejected there.
POINTERS = ["agents/executor.md", "agents/reviewer.md", "agents/security-reviewer.md", "agents/review-verifier.md", "agents/planner.md",
            "agents/pre-mortem.md", "skills/session/SKILL.md", "data/executor-brief.md"]
REPORTS_OUTSIDE = ("agents/executor.md", "agents/reviewer.md", "agents/security-reviewer.md", "data/executor-brief.md")


def read(rel, root=ROOT):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def texts(root=ROOT):
    found = {}
    for d in TEXT_DIRS:
        for base, _, files in os.walk(os.path.join(root, d)):
            for name in files:
                if name.endswith((".md", ".js", ".tsv")):
                    p = os.path.join(base, name)
                    found[os.path.relpath(p, root)] = open(p, encoding="utf-8").read()
    return found


def narrowing(found):
    return ["%s: \"%s\"" % (rel, phrase) for rel, text in sorted(found.items()) for phrase, _ in NARROWING if phrase in text]


def rule_problems(principles):
    m = re.search(r"^12\. \*\*(.+?)\*\*(.*?)(?=^\d+\. \*\*|\Z)", principles, re.M | re.S)
    if not m:
        return ["principles.md: rule 12 states the ownership rule: not found"]
    body = m.group(0)
    found = []
    for quote in ("Agents have full responsibility on the code that they're working in and the entire code base",
                  "you're responsible of everything that software it's supposed to be", "We have to move fast"):
        if quote not in body and quote not in principles:
            found.append("principles.md: the owner's words are not quoted: %s" % quote)
    if "Enforced by" not in body:
        found.append("principles.md: rule 12 names no enforcer (a rule with none is a guideline, rule 1)")
    return found


def pointer_problems(read_text):
    found = []
    for rel in POINTERS:
        text = read_text(rel)
        if not re.search(r"principles\.md`? rule 12", text):
            found.append("%s does not point at %s" % (rel, RULE))
        if rel in REPORTS_OUTSIDE and "`outside`" not in text:
            found.append("%s does not say `outside`" % rel)
    return found


s.eq("principles.md: rule 12 states the ownership rule and its source", rule_problems(read("playbooks/principles.md")), [])
s.eq("a text still narrows an agent's scope to its brief (state the rule once, in " + RULE + ", and point at it)", narrowing(texts()), [])
s.eq("each agent file points at rule 12 and the agents that report a defect outside their task name `outside`", pointer_problems(read), [])
looked = texts()
s.ok("the narrowing check looked at the agent, skill, playbook and workflow texts (looking at nothing is a failure)",
     len(looked) > 30 and "agents/executor.md" in looked and "workflows/ui-walk.js" in looked, str(len(looked)))

# controls: each check, shown on a text that has the fault
s.ok("control: the narrowing check finds the old executor sentence",
     narrowing({"agents/executor.md": "The bigger picture narrows your scope; it never widens it."}) != [])
s.ok("control: ... and the old reviewer sentence", narrowing({"agents/reviewer.md": "not everything wrong in the files it touches"}) != [])
s.ok("control: ... and the old FORBIDDEN line", narrowing({"workflows/ui-walk.js": "FORBIDDEN: no rebase, no fixes outside this work"}) != [])
s.ok("control: a rule 12 with no enforcer is found", rule_problems("12. **Agents own the result.** Source: the owner.\n") != [])
s.ok("control: a missing rule 12 is found", rule_problems("11. **x.** y\n") != [])
s.ok("control: an executor that does not point at the rule is found",
     any("executor.md does not point" in p for p in pointer_problems(lambda rel: "" if rel == "agents/executor.md" else read(rel))))
s.ok("control: a reviewer that does not say a defect nearby is an `outside` item is found",
     any("reviewer.md does not say `outside`" in p for p in pointer_problems(lambda rel: read(rel).replace("`outside`", "") if rel == "agents/reviewer.md" else read(rel))))
s.done()
