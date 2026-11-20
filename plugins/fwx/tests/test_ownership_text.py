#!/usr/bin/env python3
"""The ownership rule in the texts of agents (principles.md rule 12): one place states it, the rest point to it, and no text still narrows
an agent's scope to its brief.

What this can check is the words: that rule 12 exists with its source and its enforcers named, that the texts which used to say "leave it" or
"report what the diff breaks, not everything wrong in the files it touches" are gone, and that each agent file points at the rule and
carries the shape of an `outside` item where it reports one. What happens to an item is checked in code (test_execute_workflow.py,
test_outside.py, test_decide.py).

Red on master (the executor said "The bigger picture narrows your scope; it never widens it", the reviewers "not everything wrong in
the files it touches", the principles had eleven rules); the FAIL lines:
  FAIL: principles.md: rule 12 states the ownership rule, its source and its enforcers: got ['principles.md: rule 12 states the ownership rule: not found'], want []
  FAIL: a text still narrows an agent's scope to its brief (state the rule once, in principles.md rule 12, and point at it): got ['agents/executor.md: "narrows your scope"',
    'agents/executor.md: "Report what you saw outside your task and leave it"', 'agents/reviewer.md: "not everything wrong in the files it touches"',
    'agents/security-reviewer.md: "not everything wrong in the files it touches"', 'data/executor-brief.md: "no fixes outside"',
    'playbooks/execute.md: "scope the brief already forbids"', 'workflows/execute.js: "no fixes outside"'], want []
  FAIL: each agent file points at the rule and carries what it must say: got ['agents/executor.md does not point at principles.md rule 12', ...]
Controls (each check run on a text with its subject put back, and it must say so): see `control_*` below.
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
# the files that point at the rule, and the words each must carry besides
POINTERS = {
    "agents/executor.md": ["`outside`", "its own commit", "size", "fixed"],
    "agents/reviewer.md": ["`outside`", "never dismiss"],
    "agents/security-reviewer.md": ["`outside`", "never dismiss"],
    "agents/review-verifier.md": ["not introduced"],
    "agents/planner.md": ["other software", "the people who use"],
    "agents/pre-mortem.md": ["other software", "the people who use"],
    "skills/session/SKILL.md": ["fwx outside", "route"],
    "skills/session/references/closing.md": ["fwx outside"],
    "data/executor-brief.md": ["`outside`", "fixed"],
}


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
    for enforcer in ("fwx stage", "fwx decide", "workflows/execute.js"):
        if enforcer not in body:
            found.append("principles.md: rule 12 does not name %s as an enforcer" % enforcer)
    return found


def pointer_problems(read_text):
    found = []
    for rel, words in POINTERS.items():
        text = read_text(rel)
        if RULE not in text and rel != "skills/session/references/closing.md":
            found.append("%s does not point at %s" % (rel, RULE))
        for w in words:
            if w not in text:
                found.append("%s does not say %s" % (rel, w))
    return found


s.eq("principles.md: rule 12 states the ownership rule, its source and its enforcers", rule_problems(read("playbooks/principles.md")), [])
s.eq("a text still narrows an agent's scope to its brief (state the rule once, in " + RULE + ", and point at it)", narrowing(texts()), [])
s.eq("each agent file points at the rule and carries what it must say", pointer_problems(read), [])
looked = texts()
s.ok("the narrowing check looked at the agent, skill, playbook and workflow texts (looking at nothing is a failure)",
     len(looked) > 30 and "agents/executor.md" in looked and "workflows/execute.js" in looked, str(len(looked)))

# controls: each check, shown on a text that has the fault
s.ok("control: the narrowing check finds the old executor sentence",
     narrowing({"agents/executor.md": "The bigger picture narrows your scope; it never widens it."}) != [])
s.ok("control: ... and the old reviewer sentence", narrowing({"agents/reviewer.md": "not everything wrong in the files it touches"}) != [])
s.ok("control: ... and the old FORBIDDEN line", narrowing({"workflows/execute.js": "FORBIDDEN: no rebase, no fixes outside this work"}) != [])
s.ok("control: a rule 12 with no enforcer is found", rule_problems("12. **Agents own the result.** Source: the owner.\n") != [])
s.ok("control: a missing rule 12 is found", rule_problems("11. **x.** y\n") != [])
s.ok("control: an executor that does not point at the rule is found",
     any("executor.md does not point" in p for p in pointer_problems(lambda rel: "" if rel == "agents/executor.md" else read(rel))))
s.ok("control: a reviewer that does not say a defect nearby is an `outside` item is found",
     any("reviewer.md does not say `outside`" in p for p in pointer_problems(lambda rel: read(rel).replace("`outside`", "") if rel == "agents/reviewer.md" else read(rel))))
s.done()
