#!/usr/bin/env python3
"""The session skill's review text: the verdict page is never waited on, a rejection stops for a question, and the commands it names exist.

Plain Python, no network: it reads skills/session/ of the checkout it sits in (`python3 tests/test_session_text.py [ROOT]` reads another
tree) and runs that tree's `bin/fwx --help` for the command list. Commands that only exist on another branch (`walk` on the UI-walk
branch, `open` on master) are SKIPped with their reason printed, never silently; the rest must exist.

Seen red on the untouched branch (text before this change; the five FAIL lines, 21 checks looked at; an `xdg-open` ban was dropped in round two, because the text now names the line the tool prints, to relay it):
  FAIL: no 'verdict wait' in skills/session -> references/ui-review.md
  FAIL: no '--serve' in skills/session -> references/ui-review.md
  FAIL: ui-review.md names 'redo' -> missing
  FAIL: ui-review.md names 'not_defect' -> missing
  FAIL: ui-review.md asks before the revert -> no 'revert it?' before the first '--revert'
Round two (a review of the text found the open line not relayed and the fix round without `--fix`); run against the first version of
ui-review.md the two new checks gave:
  FAIL: ui-review.md names 'NOT OPENED' -> missing
  FAIL: ui-review.md names '--fix <file>' -> missing
3.2 U5 follow-up. The `state` agent returns the report as text and the session saves it (a subagent's Write of a report is refused by
Claude Code: "Subagents should return findings as text, not write report files"), and the fields the session's steps read are
fields the code has. Run against the tree of 26a9c8b (the texts before the follow-up) the new checks gave:
  FAIL: agents/state.md returns the report from its template's first heading -> no '# Report' or no 'final response' in the agent text
  FAIL: agents/state.md and step 8 share the marker 'Noticed:' -> agent False, session False
  FAIL: step 8 saves the returned report with Write, then checks it -> no 'report-<n>.md' ... 'Write' ... 'fwx state check report' in that order after the `state` launch
The rest of the follow-up checks read code that already holds, so they pass on the old tree; each has a control on a toy text (a cited
field the code does not have, a step-8 text that checks before it saves).
No static check is added for the three earlier text fixes, except where a named field is checked below: rule 8 (the line a called skill
ends with is a result, not the end of the turn) and the stop of step 8 are behaviour of a model reading prose, and a grep for the words
would only prove the words are there.

Each check also has a control on a toy text (the "control:" checks): a text with 'verdict wait' must fail the removed-string check, and a text
that reverts before it asks must fail the ask-first check.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.realpath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SESSION = os.path.join(ROOT, "skills", "session")
fails, skips, looked = [], [], [0]

# Commands that only exist on a branch this one does not contain yet; each is SKIPped with its reason.
ELSEWHERE = {
    "walk": "the UI-walk branch (feat/3.5-ui-walk)",
}


def check(name, ok, detail=""):
    looked[0] += 1
    if not ok:
        fails.append("FAIL: %s -> %s" % (name, detail))


def read(rel):
    with open(os.path.join(SESSION, rel), encoding="utf-8") as f:
        return f.read()


def supports(text):
    """{answer: the support the text says the decisions agent records for it}, for `not_defect` and `redo`: "`x` with support `y`" or "`x`: `support` `y`"."""
    return {w: m.group(1) for w in ("not_defect", "redo") for m in [re.search(r"`%s`(?::| with) (?:`support`|support) `(\w+)`" % w, text)] if m}


def files_naming(needle, texts):
    return [rel for rel, text in texts.items() if needle in text]


def asks_before_revert(text):
    ask, flag = text.find("revert it?"), text.find("--revert")
    return ask != -1 and (flag == -1 or ask < flag)


def step(text, n):
    """The text of numbered step `n` of SKILL.md, after its `## Steps` heading (the fixed rules above it are numbered too), up to the
    next numbered step or the end."""
    text = text[text.find("## Steps"):] if "## Steps" in text else text
    m = re.search(r"^%d\. \*\*.*?(?=^\d+\. \*\*|\Z)" % n, text, re.S | re.M)
    return m.group(0) if m else ""


def in_order(text, *words):
    """True when every word is in `text` and each comes after the one before it."""
    pos = -1
    for w in words:
        i = text.find(w, pos + 1)
        if i == -1:
            return False
        pos = i
    return True


def missing_keys(cited, source):
    """The cited keys that the source does not name as a quoted key."""
    return [k for k in cited if '"%s"' % k not in source]


def fwx_commands(text):
    """Top-level `fwx <name>` words; `fwx:execute` (a workflow) has a colon and is not one."""
    return set(re.findall(r"\bfwx ([a-z][a-z-]*)\b", text))


def main():
    texts = {rel: read(rel) for rel in ("SKILL.md", os.path.join("references", "ui-review.md"), os.path.join("references", "part-report.md"))}
    review = texts[os.path.join("references", "ui-review.md")]

    # The session never waits on the page and hands the owner files through `fwx open`.
    for gone in ("verdict wait", "--serve"):
        named = files_naming(gone, texts)
        check("no '%s' in skills/session" % gone, not named, ", ".join(named))

    # What the review text must say.
    # Round two of the text review (the nine-point contract keys, the relayed open line, the fix round's findings file).
    for word in ("review-answers", "redo", "not_defect", "contradicted_wanted", "open", "stale", "NOT OPENED", "--fix <file>"):
        check("ui-review.md names '%s'" % word, word in review, "missing")
    check("ui-review.md asks before the revert", asks_before_revert(review), "no 'revert it?' before the first '--revert'")

    # The `state` agent returns the report and the session saves it (the harness refuses a subagent's Write of a report).
    with open(os.path.join(ROOT, "agents", "state.md"), encoding="utf-8") as f:
        agent = f.read()
    with open(os.path.join(ROOT, "templates", "phase", "report.md"), encoding="utf-8") as f:
        heading = next((ln.split(" <")[0].split(":")[0] for ln in f.read().splitlines() if ln.startswith("# ")), "")
    check("report template has a first heading", bool(heading), "none")
    check("agents/state.md returns the report from its template's first heading", bool(heading) and heading in agent and "final response" in agent,
          "no '%s' or no 'final response' in the agent text" % heading)
    rep_ref = texts[os.path.join("references", "part-report.md")]
    s8 = step(texts["SKILL.md"], 8)
    check("step 8 found", "Review of the part" in s8, "not found")
    check("agents/state.md and the session's report text share the marker 'Noticed:'", "Noticed:" in agent and "Noticed:" in s8 and "Noticed:" in rep_ref,
          "agent %s, step 8 %s, part-report.md %s" % ("Noticed:" in agent, "Noticed:" in s8, "Noticed:" in rep_ref))
    check("part-report.md saves the returned report with Write, then checks it", in_order(rep_ref, "`state`", "report-<n>.md", "`Write`", "fwx state check report"),
          "no 'report-<n>.md' ... 'Write' ... 'fwx state check report' in that order after the `state` launch")
    check("step 8 sends the owner to part-report.md and does not run the check itself", "references/part-report.md" in s8 and "fwx state check report" not in s8,
          "pointer or check misplaced")
    # Every `references/<file>.md` the session skill cites exists, and every file in references/ is cited.
    cited = set(re.findall(r"references/([a-z-]+\.md)", texts["SKILL.md"]))
    present = set(os.listdir(os.path.join(SESSION, "references")))
    check("every references/ file SKILL.md cites exists", not (cited - present), "missing %s" % sorted(cited - present))
    check("every file in references/ is cited by SKILL.md", not (present - cited), "uncited %s" % sorted(present - cited))
    check("part-report.md names the two errors and the WARN of the check", all(w in rep_ref for w in ("no evidence row", "last evidence row", "WARN")), "an error or the WARN is not read")

    # The fields the steps read exist in the code that produces them (a rename would leave the text reading nothing).
    with open(os.path.join(ROOT, "lib", "fwx", "commands", "budget.py"), encoding="utf-8") as f:
        budget_src = f.read()
    cited = [k for k in ("used_percentage", "week_tight") if "`%s`" % k in texts["SKILL.md"] or ".%s" % k in texts["SKILL.md"]]
    check("SKILL.md cites both budget fields it reads", len(cited) == 2, "cites %s" % cited)
    check("fwx budget names the fields rule 7 and step 2 read", not missing_keys(cited, budget_src), "missing %s" % missing_keys(cited, budget_src))
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx import plan  # noqa: E402
    check("step 8 reads `review: blocking` and the plan accepts that value", "`review: blocking`" in s8 and "blocking" in plan.REVIEWS,
          "step 8 names it: %s; plan.REVIEWS: %s" % ("`review: blocking`" in s8, plan.REVIEWS))
    check("steps 5 and 8 read `ui: true` and plan.py has a task key `ui`", "`ui: true`" in texts["SKILL.md"] and '"ui"' in open(os.path.join(ROOT, "lib", "fwx", "plan.py"), encoding="utf-8").read(),
          "the text or the task keys lack it")
    s2 = step(texts["SKILL.md"], 2)
    check("step 2 reads the context before it writes stage `planning`", in_order(s2, "above 50", "Stage `planning`"), "the budget sentence does not come first")

    # Every command the two files name exists, or is skipped with its reason.
    out = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "--help"], capture_output=True, text=True)
    check("fwx --help ran", out.returncode == 0, out.stderr.strip())
    known = {m.group(1) for m in re.finditer(r"^  ([a-z][a-z-]*)\s", out.stdout, re.M)}
    check("fwx --help lists commands", len(known) > 5, "listed %d" % len(known))
    named = set()
    for text in texts.values():
        named |= fwx_commands(text)
    check("the files name some fwx commands", len(named) > 5, "named %d" % len(named))
    for cmd in sorted(named):
        if cmd in known:
            check("fwx %s exists" % cmd, True)
        elif cmd in ELSEWHERE:
            skips.append("SKIP: fwx %s not checked: it lives on %s" % (cmd, ELSEWHERE[cmd]))
        else:
            check("fwx %s exists" % cmd, False, "not in `fwx --help`")

    # The playbook and the skill say the same of a rejected fix: `fwx walk review-answers` only sorts the answers (walk.py `cmd_review_answers`
    # writes review/answers.json and no decision), and the `decisions` agent records `not_defect` with support `approved` and `redo` with
    # support `chosen`. PR 125 made the playbook say a `redo` records nothing while this skill (what the session follows) records it.
    # Seen red on 93e43d9 (the playbook said `redo` records nothing; the skill did not say that the command writes no decision):
    #   FAIL: the playbook and ui-review.md both say what the decisions agent records for each rejection -> playbook {}, ui-review.md {'not_defect': 'approved', 'redo': 'chosen'}
    #   FAIL: the playbook and ui-review.md both say `review-answers` writes no decision -> playbook False, ui-review.md False
    with open(os.path.join(ROOT, "playbooks", "ui-walk.md"), encoding="utf-8") as f:
        playbook = f.read()
    rej = playbook[playbook.index("### p_REJ"):]
    want = {"not_defect": "approved", "redo": "chosen"}
    check("the playbook and ui-review.md both say what the decisions agent records for each rejection",
          supports(rej) == want and supports(review) == want, "playbook %s, ui-review.md %s" % (supports(rej), supports(review)))
    check("the playbook and ui-review.md both say `review-answers` writes no decision", "no decision" in rej and "no decision" in review,
          "playbook %s, ui-review.md %s" % ("no decision" in rej, "no decision" in review))
    check("control: a text that records a `redo` as approved is not the wanted one", supports("`not_defect` with support `approved`, `redo` with support `approved`") != want)

    # control: the checks above can fail.
    check("control: a cited reference that is not there is caught", set(re.findall(r"references/([a-z-]+\.md)", "see references/gone.md and references/here.md")) - {"here.md"} == {"gone.md"})
    check("control: a step 8 that checks before it saves fails", not in_order("`state` returns; run fwx state check report on report-<n>.md, then `Write` it", "`state`", "report-<n>.md", "`Write`", "fwx state check report"))
    check("control: a step 8 that saves then checks passes", in_order("`state` returns; save it to report-<n>.md with `Write`, then run fwx state check report", "`state`", "report-<n>.md", "`Write`", "fwx state check report"))
    check("control: a cited field the code lacks is caught", missing_keys(["used_percentage", "usage_percentage"], '{"used_percentage": 1}') == ["usage_percentage"])
    check("control: step() cuts one numbered step", step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2).startswith("2. **B.**") and "z" not in step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2))
    check("control: 'verdict wait' is caught", files_naming("verdict wait", {"x.md": "run verdict wait in the background"}) == ["x.md"])
    check("control: revert before the question fails", not asks_before_revert("run wave prepare --revert 1, then ask: revert it?"))
    check("control: question before the revert passes", asks_before_revert("ask: revert it? Then wave prepare --revert 1"))
    check("control: a command that does not exist is not known", "frobnicate" not in known and "frobnicate" in fwx_commands("run fwx frobnicate now"))


main()
for line in skips:
    print(line)
for line in fails:
    print(line)
print("%d checks looked at, %d failed, %d skipped" % (looked[0], len(fails), len(skips)))
sys.exit(1 if fails else 0)
