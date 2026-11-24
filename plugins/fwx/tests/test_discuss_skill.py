#!/usr/bin/env python3
"""The discuss skill's text: no model name, a model on every agent launch, a recommendation on every question, and no `decisions` agent.

Plain Python, no network: it reads skills/discuss/ and agents/demo.md of the checkout it sits in (`python3 tests/test_discuss_skill.py [ROOT]`
reads another tree). The question lines the format check looks at are the round format of rounds.md (from `**Q1**` to the first `---`).

08-steering D9 and D29 reversed the old rule "never recommend an option unasked": every question ends with `Recommended: <letter>, because ...`,
and no discuss text says never recommend. D17: the orchestrator records decisions itself with `fwx decision new`, so the discuss launches no
`decisions` agent. D14: step 3 offers a route (direct change, focused fix or full process) the owner confirms. D23: reentry.md's split is
the wayfinder mode, a milestone as the map and one phase per decision ticket.
Seen red on the 6e4e54c texts (rc=1, 43 checks; the first FAIL of each check):
  FAIL: rounds.md's question format ends with a Recommended: line -> last line of the format: 'b. <option>: <what it implies>'
  FAIL: no discuss text says never recommend -> SKILL.md:6 <!-- referent: ... the owner decides without recommendations; ...  (also SKILL.md:8, :22, rounds.md:1 and :33)
  FAIL: the discuss launches no `decisions` agent -> SKILL.md:24 5. **Record.** With decisions in the turn, launch `decisions` (`models.decisions.small`) ...  (also SKILL.md:30)
  FAIL: step 3 offers a route, direct change, focused fix or full process, that the owner confirms -> step 3: '3. **What does the owner ask?** Unsure: ask in round one. ...
  FAIL: step 5 records with fwx decision new, launches nothing, and names Pocock's three criteria -> step 5: '5. **Record.** With decisions in the turn, launch `decisions` ...
  FAIL: reentry.md's split is the wayfinder mode: a map and a decision ticket per phase -> reentry.md lacks one of: wayfinder, Destination, ...
Each check has a control on a toy: the good toy passes, then one change makes its check fail.
Held from before (seen red on planted copies): no model name (planted "Use sonnet." in SKILL.md: FAIL: no model name -> SKILL.md names 'sonnet'), and every launch names its
model (`models.researcher.small` taken out of a launch: FAIL: every launch names its model -> Then `fwx phase new <slug> [--subproject S]` and launch two or three `researcher`:).
No verdict page is waited on or served, and no opener is named: no .md under skills/, agents/ and playbooks/ names `verdict wait`,
`--serve` or `xdg-open` (how a page is opened for the owner is in his own instructions).
Seen red on master before the texts changed (first match per file; 18 .md files looked at):
  FAIL: no verdict wait, serve or opener in the discuss and the agents -> agents/demo.md names '--serve'
  FAIL: no verdict wait, serve or opener in the discuss and the agents -> skills/discuss/SKILL.md names 'xdg-open'
Widened to every skill and playbook, red before the session texts changed (32 .md files looked at):
  FAIL: ... -> playbooks/session.md names 'xdg-open'
  FAIL: ... -> skills/session/SKILL.md names 'xdg-open'
  FAIL: ... -> skills/session/references/ui-review.md names 'xdg-open'
The verdict keys reach the demo (16 checks); red on the texts before the fix (rc=1, 32 .md files looked at):
  FAIL: step 7 names verdict_tool and verdict_command in the sentence that launches demo -> step 7 launch clause: ' (`models.demo.normal`)'
  FAIL: demo.md tells the agent to read verdict_tool and verdict_command from fwx discuss --json when its prompt lacks them -> agents/demo.md has no line with 'fwx discuss --json' and both keys
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
    for block in re.findall(r"```json\n(.*?)```", demo_text, flags=re.S):
        if re.search(r'"(recommend|pick)"\s*:', block):
            out.append(("demo example has no recommend key", block[:60]))
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

check("the texts are looked at", len(files["SKILL.md"].split()) > 300 and "```json" in demo)

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


def route_line(step3):
    return all(w in step3 for w in ("direct change", "focused fix", "full process", "confirm"))


def records_itself(step5):
    return ("fwx decision new" in step5 and "launch" not in step5.lower()
            and all(w in step5 for w in ("hard to reverse", "surprising without context", "trade-off")))


def wayfinder(text):
    return all(w in text for w in ("wayfinder", "Destination", "Decisions so far", "Not yet specified", "Out of scope", "decision ticket"))


check("step 3 offers a route, direct change, focused fix or full process, that the owner confirms", route_line(step(files["SKILL.md"], 3)),
      "step 3: %r" % step(files["SKILL.md"], 3)[:90])
check("step 5 records with fwx decision new, launches nothing, and names Pocock's three criteria", records_itself(step(files["SKILL.md"], 5)),
      "step 5: %r" % step(files["SKILL.md"], 5)[:90])
check("reentry.md's split is the wayfinder mode: a map and a decision ticket per phase", wayfinder(files["reentry.md"]),
      "reentry.md lacks one of: wayfinder, Destination, Decisions so far, Not yet specified, Out of scope, decision ticket")

# the verdict keys reach the demo: the launch sentence of step 7 names both, and the demo gets them itself when its prompt lacks them
step7 = [l for l in files["SKILL.md"].splitlines() if l.startswith("7. ")]
launch7 = step7[0].split("launch `demo`", 1)[-1].split(";", 1)[0] if step7 and "launch `demo`" in step7[0] else ""
check("step 7 names verdict_tool and verdict_command in the sentence that launches demo",
      "`verdict_tool`" in launch7 and "`verdict_command`" in launch7, "step 7 launch clause: %r" % launch7[:90])
# the turn that builds the verdict page ends with where it is (the rehearsal's owner message named the page earlier in the turn, not last)
# Seen red on the old step 7 (it said "open the page ... say in one line it is ready and end the turn"):
#   FAIL: step 7 makes the last line of the turn name the page, its path or the orca tab -> step 7: "waiting on it. His pasted answer's pick and note go into `Approved UI` of `context.md`. ..."
def last_line_names_page(step):
    return re.search(r"last line[^.;]*\bnames? the page\b", step) is not None and "path" in step and "orca tab" in step
check("step 7 makes the last line of the turn name the page, its path or the orca tab",
      bool(step7) and last_line_names_page(step7[0]), "step 7: %r" % (step7[0][-200:] if step7 else ""))
check("control: the old step 7 does not pass the last-line check",
      not last_line_names_page("open the page for the owner the way the user's instructions say, say in one line it is ready and end the turn"))
gets = [l for l in demo.splitlines() if "fwx discuss --json" in l and "`verdict_tool`" in l and "`verdict_command`" in l]
check("demo.md tells the agent to read verdict_tool and verdict_command from fwx discuss --json when its prompt lacks them",
      len(gets) == 1, "agents/demo.md has no line with 'fwx discuss --json' and both keys")
for name, detail in problems(files, demo):
    check(name, False, detail)

# controls: the good toy passes first, then each change makes its own check fail
good = {"SKILL.md": "launch `researcher` (`models.researcher.small`): the map.\n", "rounds.md": "**Q1** - x\na. one: it implies y\n"}
check("control: the good toy passes", problems(good, "```json\n{\"options\": [\"a\"]}\n```") == [])
for label, files2, demo2, want in [
    ("a model name", dict(good, **{"SKILL.md": good["SKILL.md"] + "Use sonnet.\n"}), "", "no model name"),
    ("a launch without models.", dict(good, **{"SKILL.md": "launch `demo` for the figure.\n"}), "", "every launch names its model"),
    ("a recommend key", good, "```json\n{\"recommend\": 1}\n```", "demo example has no recommend key"),
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
GOOD3 = "3. **What?** Route: direct change, focused fix or full process; the owner confirms.\n"
check("control: the good step 3 passes", route_line(step(GOOD3 + "4. x\n", 3)))
check("control: a step 3 with no route fails", not route_line(step("3. **What?** Trivial: plain Claude.\n4. x\n", 3)))
GOOD5 = "5. **Record.** `fwx decision new`: hard to reverse, surprising without context and a real trade-off.\n6. x\n"
check("control: the good step 5 passes", records_itself(step(GOOD5, 5)))
check("control: a step 5 that launches an agent fails", not records_itself(step(GOOD5.replace("5. **Record.**", "5. **Record.** Launch an agent;"), 5)))
check("control: a step 5 with no criteria fails", not records_itself(step("5. **Record.** `fwx decision new`.\n6. x\n", 5)))
check("control: the wayfinder text passes", wayfinder("wayfinder: Destination, Decisions so far, Not yet specified, Out of scope, one decision ticket per phase"))
check("control: the old split fails", not wayfinder("make the other phases with `fwx phase new`"))

check("control: a text with no wait passes", waiting({"a.md": "show the page."}) == [])
for bad in ("verdict wait <dir>", "verdict <dir> --serve", "end with its `xdg-open` line"):
    check("control: %r fails" % bad, len(waiting({"a.md": "x " + bad})) == 1)

print("looked at %d checks" % looked[0])
for f in fails:
    print(f)
sys.exit(1 if fails else 0)
