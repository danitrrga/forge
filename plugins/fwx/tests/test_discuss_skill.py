#!/usr/bin/env python3
"""The discuss skill's text where code reads it or the owner set the rule: no model name and a `models.<role>.<size>` key on every agent launch
(the model comes from the configuration), a recommendation on every question, no `decisions` agent, no verdict page waited on or served, and
the verdict keys that `fwx discuss --json` prints reach the demo.

Plain Python, no network: it reads skills/discuss/ and agents/demo.md of the checkout it sits in (`python3 tests/test_discuss_skill.py [ROOT]`
reads another tree). The question lines the format check looks at are the round format of rounds.md (from `**Q1**` to the first `---`).

08-steering D9 and D29: every question ends with `Recommended: <letter>, because ...`, and no discuss text says never recommend. D17: the
orchestrator records decisions itself with `fwx decision new`, so the discuss launches no `decisions` agent. The owner opens a verdict page in
his own way: no .md under skills/, agents/ and playbooks/ names `verdict wait`, `--serve` or `xdg-open`.
09.3 T33 removed the checks that pinned wording with their red logs: step 3's route sentence, step 5's three criteria, reentry.md's wayfinder
words, the last line of step 7's turn, and the `recommend` key of the demo's example.

Seen red on copies of the real texts (a copy of plugins/fwx with the pinned words changed; the FAIL line printed):
  rounds.md, "Recommended: <letter>, because <why>" -> "Pick: <letter>":
    FAIL: rounds.md's question format ends with a Recommended: line -> last line of the format: 'Pick: <letter>'
  SKILL.md, "Record each decision" -> "Never recommend an option; record each decision":
    FAIL: no discuss text says never recommend -> SKILL.md:25 5. **Record.** Never recommend an option; record each decision of the turn yours
  SKILL.md, "`models.researcher.small`" -> "`sonnet`":
    FAIL: no model name -> SKILL.md names 'sonnet'   and   FAIL: every launch names its model -> Then `fwx phase new <slug> [--subproject S]` and launch two or three `researcher` (`sonnet
  SKILL.md step 5 changed to "Launch `decisions` to record each decision of the turn":
    FAIL: the discuss launches no `decisions` agent -> SKILL.md:25 5. **Record.** Launch `decisions` to record each decision of the turn, a row onl
    FAIL: step 5 records with fwx decision new and launches nothing -> step 5: '5. **Record.** Launch `decisions` to record each decision of the turn, a row only for a de'
  skills/discuss/SKILL.md with "xdg-open" put in step 7 ("`demo` (" -> "xdg-open `demo` ("):
    FAIL: no verdict wait, serve or opener in the skills, agents and playbooks -> skills/discuss/SKILL.md names 'xdg-open'
  agents/demo.md, "`verdict_command`" -> "`verdict_cmd`":
    FAIL: demo.md tells the agent to read verdict_tool and verdict_command from fwx discuss --json when its prompt lacks them -> agents/demo.md has no line with 'fwx discuss --json' and both keys
  lib/fwx/commands/discuss.py, '"verdict_command"' -> '"verdict_cmd"':
    FAIL: fwx discuss --json prints the keys verdict_tool and verdict_command that step 7 and demo.md name -> lib/fwx/commands/discuss.py has no such key
  agents/demo.md unchanged from before the demo loaded the design skills (no Skill in tools, step 2 "You have no Skill tool"):
    FAIL: demo.md's tools include Skill -> agents/demo.md: 'tools: Read, Grep, Glob, Bash, Write'
    FAIL: demo.md step 2 loads the design skills with the Skill tool and the Return names the ones loaded -> step 2: '... You have no Skill tool, so read their `SKILL.md`.' ; Return names loaded skills: False
Each kept check has a control on a toy: the good toy passes, then one change makes its check fail.
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
LAUNCH = re.compile(r"launch[^.]*?`(researcher|demo)`", re.I)
OPEN, CLOSE = re.compile(r"^\s*(\d+\. )?\*\*Q\d"), re.compile(r"^\s*(---\s*$|The owner answers)")
NEVER_REC = re.compile(r"never recommend|no recommendation|without recommendations?|without a recommendation|takes? no recommendation", re.I)
DECISIONS_AGENT = re.compile(r"`(?:fwx:)?decisions`")
RECOMMENDED = re.compile(r"^Recommended: <letter>, because ")


def format_ends_with_recommended(text):
    """The round format of rounds.md: from the first `**Q` line to the first `---`, its last non-blank line is the Recommended: line."""
    block, inside = [], False
    for line in text.splitlines():
        if OPEN.match(line):
            inside = True
        elif CLOSE.match(line) and inside:
            break
        if inside and line.strip():
            block.append(line.strip())
    return bool(block) and RECOMMENDED.match(block[-1]) is not None, (block[-1] if block else "no **Q1** line")


def never_recommend(files):
    return [("no discuss text says never recommend", "%s:%d %s" % (n, i, l.strip()[:80]))
            for n, t in files.items() for i, l in enumerate(t.splitlines(), 1) if NEVER_REC.search(l)]


def decisions_agent(files):
    return [("the discuss launches no `decisions` agent", "%s:%d %s" % (n, i, l.strip()[:80]))
            for n, t in files.items() for i, l in enumerate(t.splitlines(), 1) if DECISIONS_AGENT.search(l)]


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
    return out


WAITS = re.compile(r"verdict wait|--serve|xdg-open")


def waiting(texts):
    """texts: {name: text}. Returns [(check, detail)] for each file that names a verdict wait, a serve or an opener."""
    return [("no verdict wait, serve or opener in the skills, agents and playbooks", "%s names %r" % (n, m.group(0)))
            for n, t in sorted(texts.items()) for m in [WAITS.search(t)] if m]


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


files = {"SKILL.md": read("skills", "discuss", "SKILL.md")}
for f in ("rounds.md", "playback.md", "reentry.md"):
    files[f] = read("skills", "discuss", "references", f)
demo = read("agents", "demo.md")

agent_texts = {}
for sub in ("skills", "agents", "playbooks"):
    for dirpath, _, names in os.walk(os.path.join(ROOT, sub)):
        for n in names:
            if n.endswith(".md"):
                full = os.path.join(dirpath, n)
                with open(full, encoding="utf-8") as fh:
                    agent_texts[os.path.relpath(full, ROOT)] = fh.read()
print("looked at %d .md files under skills/, agents/ and playbooks/" % len(agent_texts))
check("the skill, agent and playbook texts are looked at (zero is a failure)", len(agent_texts) > 0)
for name, detail in waiting(agent_texts):
    check(name, False, detail)

check("the texts are looked at", len(files["SKILL.md"].split()) > 300 and len(demo.split()) > 50)

# D9: every question carries a recommendation, and nothing in the discuss says the opposite.
ok, last = format_ends_with_recommended(files["rounds.md"])
check("rounds.md's question format ends with a Recommended: line", ok, "last line of the format: %r" % last)
for name, detail in never_recommend(files):
    check(name, False, detail)
# D17: the orchestrator records the decision itself; no agent is launched for it
for name, detail in decisions_agent(files):
    check(name, False, detail)


def step(text, n):
    """The lines of step n of SKILL.md: from its number to the next numbered line."""
    m = re.search(r"^%d\. .*?(?=^\d+\. |\Z)" % n, text, flags=re.S | re.M)
    return m.group(0) if m else ""


def records_itself(step5):
    return "fwx decision new" in step5 and "launch" not in step5.lower()


check("step 5 records with fwx decision new and launches nothing", records_itself(step(files["SKILL.md"], 5)), "step 5: %r" % step(files["SKILL.md"], 5)[:90])

# the verdict keys reach the demo: the launch sentence of step 7 names both, and the demo gets them itself when its prompt lacks them
step7 = [l for l in files["SKILL.md"].splitlines() if l.startswith("7. ")]
launch7 = step7[0].split("launch `demo`", 1)[-1].split(";", 1)[0] if step7 and "launch `demo`" in step7[0] else ""
check("step 7 names verdict_tool and verdict_command in the sentence that launches demo",
      "`verdict_tool`" in launch7 and "`verdict_command`" in launch7, "step 7 launch clause: %r" % launch7[:90])
with open(os.path.join(ROOT, "lib", "fwx", "commands", "discuss.py"), encoding="utf-8") as fh:
    discuss_src = fh.read()
check("fwx discuss --json prints the keys verdict_tool and verdict_command that step 7 and demo.md name",
      '"verdict_tool"' in discuss_src and '"verdict_command"' in discuss_src, "lib/fwx/commands/discuss.py has no such key")
gets = [l for l in demo.splitlines() if "fwx discuss --json" in l and "`verdict_tool`" in l and "`verdict_command`" in l]
check("demo.md tells the agent to read verdict_tool and verdict_command from fwx discuss --json when its prompt lacks them",
      len(gets) == 1, "agents/demo.md has no line with 'fwx discuss --json' and both keys")
# the demo builds figures that look like the app: it loads the design skills with the Skill tool (a nameless skimming of their files left its
# prototypes generic) and says in its Return which it loaded
tools_line = next((l for l in demo.splitlines() if l.startswith("tools:")), "")
check("demo.md's tools include Skill", "Skill" in [t.strip() for t in tools_line[len("tools:"):].split(",")], "agents/demo.md: %r" % tools_line)
step2 = step(demo, 2)
check("demo.md step 2 loads the design skills with the Skill tool and the Return names the ones loaded",
      "Skill tool" in step2 and "load" in step2.lower() and "design" in step2.lower() and "no Skill tool" not in step2
      and "loaded" in demo.split("## Return", 1)[-1],
      "step 2: %r; Return names loaded skills: %s" % (step2[-120:], "loaded" in demo.split("## Return", 1)[-1]))
for name, detail in problems(files, demo):
    check(name, False, detail)

# controls: the good toy passes first, then each change makes its own check fail
good = {"SKILL.md": "launch `researcher` (`models.researcher.small`): the map.\n", "rounds.md": "**Q1** - x\na. one: it implies y\n"}
check("control: the good toy passes", problems(good, "") == [])
for label, files2, demo2, want in [
    ("a model name", dict(good, **{"SKILL.md": good["SKILL.md"] + "Use sonnet.\n"}), "", "no model name"),
    ("a launch without models.", dict(good, **{"SKILL.md": "launch `demo` for the figure.\n"}), "", "every launch names its model"),
]:
    got = [c for c, _ in problems(files2, demo2)]
    check("control: " + label, want in got, "got %s" % got)

good_round = "**Q1** - x\na. one: y\nb. two: z\nRecommended: a, because it is cheaper\n\n---\n"
GOOD_FORMAT = "**Q1** - **<title>**: <body>\n\na. <option>: <what it implies>\nb. <option>: <what it implies>\nRecommended: <letter>, because <why>\n\n---\n"
check("control: the good format passes", format_ends_with_recommended(GOOD_FORMAT)[0])
for label, text in [("no Recommended line", GOOD_FORMAT.replace("Recommended: <letter>, because <why>\n", "")),
                    ("a Recommended line before the options", "**Q1** - x\nRecommended: <letter>, because <why>\na. <option>: y\n\n---\n"),
                    ("no question at all", "Work in rounds.\n")]:
    check("control: " + label + " fails the format", not format_ends_with_recommended(text)[0])
for bad in ("Never recommend an option.", "Questions go with no recommendation.", "The owner decides without recommendations.",
            "Ask without a recommendation."):
    check("control: %r fails" % bad, len(never_recommend({"a.md": "x\n" + bad + "\n"})) == 1)
check("control: a recommendation rule passes", never_recommend({"a.md": "Every question ends with a Recommended line.\n"}) == [])
check("control: a launch of decisions fails", len(decisions_agent({"a.md": "launch `decisions` (`models.decisions.small`)"})) == 1)
check("control: the decision CLI passes", decisions_agent({"a.md": "record it with `fwx decision new`"}) == [])
GOOD5 = "5. **Record.** `fwx decision new` with the decision and its why.\n6. x\n"
check("control: the good step 5 passes", records_itself(step(GOOD5, 5)))
check("control: a step 5 that launches an agent fails", not records_itself(step(GOOD5.replace("5. **Record.**", "5. **Record.** Launch an agent;"), 5)))
check("control: a step 5 with no decision command fails", not records_itself(step("5. **Record.** Write the row by hand.\n6. x\n", 5)))

check("control: a text with no wait passes", waiting({"a.md": "show the page."}) == [])
for bad in ("verdict wait <dir>", "verdict <dir> --serve", "end with its `xdg-open` line"):
    check("control: %r fails" % bad, len(waiting({"a.md": "x " + bad})) == 1)


# 01.2 T21 (D12): `recall` is pstack's skill, owner-only, copied from cursor/plugins; what it reads from is this project's `.fwx/` documents,
# git and gh. The word-for-word part is checked against upstream by the `diff` in the task, which needs the network and is not run here.
# Seen red at 56a196a (no skills/recall/):
#   FAIL: skills/recall/SKILL.md exists -> skills/recall/SKILL.md is missing
# Controls: the good toy passes first, then each change fails its own check. Seen red on a copy with the owner-only and the fwx session
# checks switched off (`if False:`):
#   FAIL: control: no owner-only key -> got [], want 'recall is owner-only'
#   FAIL: control: fwx session named -> got [], want 'recall never runs fwx session'
RECALL_NAMES = [("project.md", "project.md"), ("adr.tsv", "adr.tsv"), ("the milestone", "milestone"), ("fwx phase list --json", "fwx phase list --json"),
                ("the phase he names", "phase he names"), ("git", "`git`"), ("gh", "`gh`")]


def recall_problems(text, notice):
    """text: skills/recall/SKILL.md; notice: NOTICE. Returns [(check, detail)]."""
    out = []
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    if "disable-model-invocation: true" not in front.splitlines():
        out.append(("recall is owner-only", "its frontmatter has no `disable-model-invocation: true`"))
    head = "\n".join(text.splitlines()[:12])
    if not re.search(r"copied-from:.*cursor/plugins.*@b7b93c36be9b", head):
        out.append(("recall carries its copied-from header", "no `copied-from: cursor/plugins ... @b7b93c36be9b` in its first lines"))
    if not any("cursor/plugins" in b and "b7b93c36be9b" in b and "skills/recall" in b for b in re.split(r"\n\s*\n", notice)):
        out.append(("NOTICE lists recall", "no entry naming cursor/plugins, b7b93c36be9b and skills/recall"))
    for label, needle in RECALL_NAMES:
        if needle not in text:
            out.append(("recall names " + label, "its text has no %r" % needle))
    if re.search(r"fwx session", text):
        out.append(("recall never runs fwx session", "its text names `fwx session`"))
    return out


recall_path = os.path.join(ROOT, "skills", "recall", "SKILL.md")
check("skills/recall/SKILL.md exists", os.path.exists(recall_path), "skills/recall/SKILL.md is missing")
if os.path.exists(recall_path):
    for name, detail in recall_problems(read("skills", "recall", "SKILL.md"), read("NOTICE")):
        check(name, False, detail)

GOOD_RECALL = ("---\nname: recall\ndisable-model-invocation: true\n---\n<!-- copied-from: cursor/plugins pstack/skills/recall/SKILL.md @b7b93c36be9b -->\n"
               "project.md adr.tsv milestone fwx phase list --json phase he names `git` `gh`\n")
GOOD_NOTICE = "cursor/plugins, commit b7b93c36be9b\n  skills/recall/SKILL.md\n"
check("control: the good recall toy passes", recall_problems(GOOD_RECALL, GOOD_NOTICE) == [])
for label, text, notice, want in [
        ("no owner-only key", GOOD_RECALL.replace("disable-model-invocation: true\n", ""), GOOD_NOTICE, "recall is owner-only"),
        ("header without the commit", GOOD_RECALL.replace("@b7b93c36be9b", "@36885ea"), GOOD_NOTICE, "recall carries its copied-from header"),
        ("NOTICE without recall", GOOD_RECALL, "cursor/plugins, commit b7b93c36be9b\n", "NOTICE lists recall"),
        ("adr.tsv not named", GOOD_RECALL.replace("adr.tsv ", ""), GOOD_NOTICE, "recall names adr.tsv"),
        ("fwx session named", GOOD_RECALL + "run `fwx session --json`\n", GOOD_NOTICE, "recall never runs fwx session")]:
    got = [c for c, _ in recall_problems(text, notice)]
    check("control: " + label, want in got, "got %s, want %r" % (got, want))

print("looked at %d checks" % looked[0])
for f in fails:
    print(f)
sys.exit(1 if fails else 0)
