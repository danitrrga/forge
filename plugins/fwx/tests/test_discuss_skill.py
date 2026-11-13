#!/usr/bin/env python3
"""The discuss skill's text: no model name, a model on every agent launch, and no recommendation in a question.

Plain Python, no network: it reads skills/discuss/ and agents/demo.md of the checkout it sits in (`python3 tests/test_discuss_skill.py [ROOT]`
reads another tree). The question lines it looks at are the round format (`**Q1**`, `a. `, `- a) `); the rule sentence "no recommendation"
is not one.

Seen red on copies of the real tree with one planted change each (first FAIL line; the real tree is green, 9 checks). Planted in rounds.md
on the option lines (`a. <option>: <what it implies>` at line 13, `b.` at 14) or the question line:
  - "(recommended)": FAIL: no recommendation in a question -> rounds.md:13 a. <option>: <what it implies> (recommended)
  - "I suggest option b": FAIL: no recommendation in a question -> rounds.md:14 b. <option>: <what it implies> I suggest option b
  - "(preferred)": FAIL: no recommendation in a question -> rounds.md:13 a. <option>: <what it implies> (preferred)
  - "the best choice": FAIL: no recommendation in a question -> rounds.md:14 b. <option>: <what it implies> the best choice
  - "(default)": FAIL: no recommendation in a question -> rounds.md:13 a. <option>: <what it implies> (default)
  - "I would go with a here." under the question: FAIL: no recommendation in a question -> rounds.md:12 I would go with a here.
  - lettered option "b. drop it, suggest b" in SKILL.md: FAIL: no recommendation in a question -> SKILL.md:20 b. drop it, suggest b
  - "Use sonnet." in SKILL.md: FAIL: no model name -> SKILL.md names 'sonnet'
  - `models.researcher.small` taken out of a launch: FAIL: every launch names its model -> Then `fwx phase new <slug> [--subproject S]` and launch two or three `researcher`:
Length is not checked here: it is measured and reported, not capped. Each change also has an in-file control on a toy (the "control:" checks).
"""
import json
import os
import re
import sys

ROOT = os.path.realpath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
fails, looked = [], [0]


def check(name, ok, detail=""):
    looked[0] += 1
    if not ok:
        fails.append("FAIL: %s -> %s" % (name, detail))


MODEL = re.compile(r"\b(opus|sonnet|haiku|fable)\b", re.I)
LAUNCH = re.compile(r"launch[^.]*?`(researcher|decisions|demo)`", re.I)
QUESTION = re.compile(r"^\s*(\*\*Q\d|[a-z]\. |[-*] [a-z]\) |\d+\. \*\*Q\d)")
OPEN, CLOSE = re.compile(r"^\s*(\d+\. )?\*\*Q\d"), re.compile(r"^\s*(---\s*$|The owner answers)")
STEER = re.compile(r"recommend|suggest|prefer|\bbest\b|\bbetter\b|default|go with|\bI(?:'d| would) |my pick|ideal|safest|wiser", re.I)


def problems(files, demo_text):
    """files: {name: text} of the discuss skill; demo_text: agents/demo.md. Returns [(check, detail)]."""
    out = []
    for name, text in files.items():
        m = MODEL.search(re.sub(r"<!--.*?-->", "", text, flags=re.S))
        if m:
            out.append(("no model name", "%s names %r" % (name, m.group(0))))
    skill = files["SKILL.md"]
    for sentence in re.split(r"(?<=[.;:])\s+", skill):
        if LAUNCH.search(sentence) and "models." not in sentence:
            out.append(("every launch names its model", sentence.strip()[:90]))
    for name, text in files.items():
        inside = False
        for n, line in enumerate(text.splitlines(), 1):
            if OPEN.match(line):
                inside = True
            elif CLOSE.match(line):
                inside = False
            if (inside or QUESTION.match(line)) and STEER.search(line):
                out.append(("no recommendation in a question", "%s:%d %s" % (name, n, line.strip()[:80])))
    for block in re.findall(r"```json\n(.*?)```", demo_text, flags=re.S):
        if re.search(r'"(recommend|pick)"\s*:', block):
            out.append(("demo example has no recommend key", block[:60]))
    return out


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


files = {"SKILL.md": read("skills", "discuss", "SKILL.md")}
for f in ("rounds.md", "playback.md", "reentry.md"):
    files[f] = read("skills", "discuss", "references", f)
demo = read("agents", "demo.md")

check("the texts are looked at", len(files["SKILL.md"].split()) > 300 and "```json" in demo)
for name, detail in problems(files, demo):
    check(name, False, detail)

# controls: the good toy passes first, then each change makes its own check fail
good = {"SKILL.md": "launch `researcher` (`models.researcher.small`): the map.\n", "rounds.md": "**Q1** - x\na. one: it implies y\n"}
check("control: the good toy passes", problems(good, "```json\n{\"options\": [\"a\"]}\n```") == [])
for label, files2, demo2, want in [
    ("a model name", dict(good, **{"SKILL.md": good["SKILL.md"] + "Use sonnet.\n"}), "", "no model name"),
    ("a launch without models.", dict(good, **{"SKILL.md": "launch `demo` for the figure.\n"}), "", "every launch names its model"),
    ("a recommended option", dict(good, **{"rounds.md": "**Q1** - x\na. one: y (recommended)\n"}), "", "no recommendation in a question"),
    ("a suggested option", dict(good, **{"rounds.md": "**Q1** - x\na. one: y\nb. two: z. I suggest option b\n"}), "", "no recommendation in a question"),
    ("a preferred option", dict(good, **{"rounds.md": "**Q1** - x\na. one: y (preferred)\n"}), "", "no recommendation in a question"),
    ("a steer in the question body", dict(good, **{"rounds.md": "**Q1** - x\nI would go with a here.\n\na. one: y\n"}), "", "no recommendation in a question"),
    ("a recommend key", good, "```json\n{\"recommend\": 1}\n```", "demo example has no recommend key"),
]:
    got = [c for c, _ in problems(files2, demo2)]
    check("control: " + label, want in got, "got %s" % got)

print("looked at %d checks" % looked[0])
for f in fails:
    print(f)
sys.exit(1 if fails else 0)
