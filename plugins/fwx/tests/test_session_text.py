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
  (since the opener moved to the user's instructions the word checked is "the user's instructions"; with ui-review.md's
  sentence on opening the page taken out: FAIL: ui-review.md names "the user's instructions" -> missing)
  FAIL: ui-review.md names '--fix <file>' -> missing
3.2 U5 follow-up. The `state` agent returns the report as text and the session saves it (a subagent's Write of a report is refused by
Claude Code: "Subagents should return findings as text, not write report files"), and the fields the session's steps read are
fields the code has. Run against the tree of 26a9c8b (the texts before the follow-up) the new checks gave:
  FAIL: agents/state.md returns the report from its template's first heading -> no '# Report' or no 'final response' in the agent text
  FAIL: agents/state.md and step 8 share the marker 'Noticed:' -> agent False, session False
  FAIL: step 8 saves the returned report with Write, then checks it -> no 'report-<n>.md' ... 'Write' ... 'fwx report lint' in that order after the `state` launch
The rest of the follow-up checks read code that already holds, so they pass on the old tree; each has a control on a toy text (a cited
field the code does not have, a step-8 text that checks before it saves).
No static check is added for the three earlier text fixes, except where a named field is checked below: rule 8 (the line a called skill
ends with is a result, not the end of the turn) and the stop of step 8 are behaviour of a model reading prose, and a grep for the words
would only prove the words are there.

DTC-34, the owner's rule: a phase worktree is removed only once its PR is merged and nothing in it is unsaved. Run against origin/master 315324b
(closing.md step 4 removed the worktree at close, SKILL.md step 0 had no sweep), the new checks gave:
  FAIL: closing.md step 4 does not remove the phase worktree -> `git worktree remove` is in it
  FAIL: closing.md step 4 says the worktree stays until its PR is merged -> no 'stays' or no 'merged'
  FAIL: SKILL.md step 0 clears merged worktrees: merged PR, clean, no force -> missing: ['--state merged', 'status --porcelain', '.claude/worktrees/', 'no force', 'git branch -d']
  FAIL: SKILL.md step 0 clears worktrees before the retake and the resume -> order is not sweep, retake, resume
  FAIL: playbooks/session.md n_L3 clears merged worktrees (--state merged) -> missing
  FAIL: playbooks/session.md n_L10 no longer removes the phase worktree -> 'removes only the phase worktree' still in it
(the `branch -D` check passes on master; the control "a step 0 with `git branch -D` is caught" shows it can fail.)

Each check also has a control on a toy text (the "control:" checks): a text with 'verdict wait' must fail the removed-string check, and a text
that reverts before it asks must fail the ask-first check.
"""
import os
import re
import subprocess
import sys
import tempfile

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


def returned_fields(js):
    """(top, details): the keys at the first level of the object a workflow script returns (its last top-level `return {`), and the keys at the
    first level of its `details` object, found by the braces (comment lines left out, nested objects not counted)."""
    body = "\n".join(ln for ln in js[js.rindex("\nreturn {"):].splitlines() if not ln.strip().startswith("//"))
    keys, depth, i = {0: set(), 1: set()}, 0, 0
    inside = None  # the depth at which the `details` object's keys sit
    while i < len(body):
        c = body[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if inside is not None and depth < inside:
                inside = None
        else:
            m = re.match(r"([a-z][a-z_]*):", body[i:]) if (c.isalpha() and not body[i - 1].isalnum() and body[i - 1] != "_") else None
            if m:
                if depth == 1:
                    keys[0].add(m.group(1))
                    if m.group(1) == "details":
                        inside = 2
                elif inside is not None and depth == inside:
                    keys[1].add(m.group(1))
                i += len(m.group(1))
        i += 1
    return keys[0], keys[1]


def cited_missing(text, returned):
    """The `details.<field>` words of a text that the returned object's `details` has no key for (a top-level field such as `reason` is not
    one: `details.reason` is a field nobody returns)."""
    return [k for k in re.findall(r"details\.([a-z][a-z_]*)", text) if k not in returned[1]]


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


def block(playbook, node):
    """The block of `node` in a playbook: from its `### <id> ·` heading to the next heading."""
    m = re.search(r"^### %s ·.*?(?=^### |\Z)" % re.escape(node), playbook, re.S | re.M)
    return m.group(0) if m else ""


def commit_effect(line, stale=False, demo=True, twice=False):
    """Run rule 4's commit line in a toy repo holding the documents of a phase beside what the UI walk leaves, and say what it did:
    (exit code, tracked files under .fwx/, untracked ones, files of the last commit, exit code of a second run or None). `<main_checkout>` is
    the toy, `<message>` is `m`. `stale`: an older session tracked a walk's `demo-state.json` (not a document) and it has changed since;
    `demo` False: the phase has no demo page; `twice`: the line runs a second time with nothing new."""
    with tempfile.TemporaryDirectory(prefix="fwx-rule4-") as toy:
        return _commit_effect(line, toy, stale, demo, twice)


def _commit_effect(line, toy, stale, demo, twice):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_NOSYSTEM="1")
    env = {k: v for k, v in env.items() if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    phase = ".fwx/milestones/v1/phases/01-a"
    old_state = phase + "/ui-walk/0-0/demo-state.json"
    run = lambda cmd: subprocess.run(cmd, shell=True, cwd=toy, env=env, capture_output=True, text=True)
    run("git init -q -b master && echo x > README && git add -A && git commit -q -m toy")
    if stale:
        os.makedirs(os.path.dirname(os.path.join(toy, old_state)))
        with open(os.path.join(toy, old_state), "w") as f:
            f.write("old\n")
        run("git add -A && git commit -q -m older-session")
        with open(os.path.join(toy, old_state), "w") as f:
            f.write("changed\n")
    for rel in (".fwx/PROJECT.md", ".fwx/milestones/v1/MILESTONE.md", phase + "/context.md", phase + "/audit.tsv", phase + "/research/r.md", phase + "/demo/page.html",
                phase + "/demo/shot.png", phase + "/ui-walk/1-1/demo-state.json", phase + "/ui-walk/1-1/up.log", phase + "/ui-walk/1-1/shot.png"):
        if not demo and "/demo/page.html" in rel:
            continue
        os.makedirs(os.path.dirname(os.path.join(toy, rel)), exist_ok=True)
        with open(os.path.join(toy, rel), "w") as f:
            f.write("x\n")
    cmd = line.replace("<main_checkout>", toy).replace("<message>", "m")
    r = run(cmd)
    again = run(cmd).returncode if twice else None
    tracked = run("git ls-tree -r --name-only HEAD").stdout.split()
    untracked = run("git status --porcelain -uall").stdout.split("\n")
    last = run("git show --name-only --format= HEAD").stdout.split()
    return r.returncode, [f for f in tracked if f.startswith(".fwx/")], [u[3:] for u in untracked if u.startswith("?? ")], last, again


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
    for word in ("review read", "redo", "not_defect", "contradicted_wanted", "open", "stale", "the user's instructions", "--fix <file>"):
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
    check("part-report.md saves the returned report with Write, then checks it", in_order(rep_ref, "`state`", "report-<n>.md", "`Write`", "fwx report lint"),
          "no 'report-<n>.md' ... 'Write' ... 'fwx report lint' in that order after the `state` launch")
    check("step 8 sends the owner to part-report.md and does not run the check itself", "references/part-report.md" in s8 and "fwx report lint" not in s8,
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
    known = {m.group(1) for m in re.finditer(r"^  fwx ([a-z][a-z-]*)\s", out.stdout, re.M)}
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

    # The playbook and the skill say the same of a rejected fix: `fwx review read` only sorts the answers (walk.py `cmd_review_answers`
    # writes review/answers.json and no decision), and the `decisions` agent records `not_defect` with support `approved` and `redo` with
    # support `chosen`. PR 125 made the playbook say a `redo` records nothing while this skill (what the session follows) records it.
    # Seen red on 93e43d9 (the playbook said `redo` records nothing; the skill did not say that the command writes no decision):
    #   FAIL: the playbook and ui-review.md both say what the decisions agent records for each rejection -> playbook {}, ui-review.md {'not_defect': 'approved', 'redo': 'chosen'}
    #   FAIL: the playbook and ui-review.md both say `review read` writes no decision -> playbook False, ui-review.md False
    with open(os.path.join(ROOT, "playbooks", "ui-walk.md"), encoding="utf-8") as f:
        playbook = f.read()
    rej = playbook[playbook.index("### p_REJ"):]
    want = {"not_defect": "approved", "redo": "chosen"}
    check("the playbook and ui-review.md both say what the decisions agent records for each rejection",
          supports(rej) == want and supports(review) == want, "playbook %s, ui-review.md %s" % (supports(rej), supports(review)))
    check("the playbook and ui-review.md both say `review read` writes no decision", "no decision" in rej and "no decision" in review,
          "playbook %s, ui-review.md %s" % ("no decision" in rej, "no decision" in review))
    check("control: a text that records a `redo` as approved is not the wanted one", supports("`not_defect` with support `approved`, `redo` with support `approved`") != want)

    # A walk that did not finish is not "no findings": `fix_file` is null then, and step 6 once read that as nothing to fix. The session texts
    # name the fields the workflow returns (`status`, `reason`, `details.unverified`, `details.gaps`: copied from the object `workflows/ui-walk.js`
    # returns, which tests/test_ui_walk_workflow.py pins key by key), so a renamed field breaks this check.
    # Seen red on 1afad4d (no session text read them):
    #   FAIL: SKILL.md step 6 tells the owner the reason, the unverified findings and that the walk did not pass -> missing: ['reason', 'unverified', 'passed']
    #   (and the same for references/ui-review.md, playbooks/ui-walk.md and playbooks/session.md)
    with open(os.path.join(ROOT, "workflows", "ui-walk.js"), encoding="utf-8") as f:
        js = f.read()
    returned = returned_fields(js)
    # Top-level fields and `details` fields are kept apart (review of PR 125: with one merged set `details.reason` passed although `reason` is a
    # top-level field only). Seen red with the merged set: FAIL: control: `details.reason` is flagged, `reason` is a top-level field only -> got []
    top, det = returned
    check("the workflow returns the top-level fields the session texts cite", {"status", "reason", "phase_dir", "details"} <= top, "top-level %s" % sorted(top))
    check("the workflow returns the details fields the session texts cite", {"gaps", "unverified", "fix_file", "lost_slots"} <= det, "details %s" % sorted(det))
    # a walk with no `fix_file` has no `fix.json`, so `fwx review new` would stop: ui-review.md says to skip the command then (review of PR 125).
    # Seen red on a11691f: FAIL: references/ui-review.md says what to do when `details.fix_file` is null -> missing
    check("references/ui-review.md says what to do when `details.fix_file` is null", "`details.fix_file` null" in review and "do not run the command" in review, "missing")
    check("control: `details.reason` is flagged, `reason` is a top-level field only", cited_missing("read `details.reason`", returned) == ["reason"], "got %s" % cited_missing("read `details.reason`", returned))
    check("control: a details field is read as a details field", cited_missing("read `details.gaps` and `details.fix_file`", returned) == [])
    with open(os.path.join(ROOT, "playbooks", "session.md"), encoding="utf-8") as f:
        session_pb = f.read()
    for name, text in (("SKILL.md step 6", step(texts["SKILL.md"], 6)), ("references/ui-review.md", review), ("playbooks/ui-walk.md", playbook),
                       ("playbooks/session.md", session_pb)):
        absent = [w for w in ("reason", "unverified", "passed") if w not in text]
        check("%s tells the owner the reason, the unverified findings and that the walk did not pass" % name, not absent, "missing: %s" % absent)
        check("%s cites only fields the workflow returns" % name, not cited_missing(text, returned), "not returned: %s" % cited_missing(text, returned))
    check("control: a cited field the workflow does not return is caught", cited_missing("read `details.unverfied`", returned) == ["unverfied"])

    # After the owner's review of a part the walk can be repeated (the stage table allows `phase-review -> ui-walk`): step 8 says when, and the
    # playbook's block of the owner's review carries the matching exit. `fwx playbook lint` compares that exit with the table by itself.
    # Seen red on 239aa07 (step 8 and the playbook did not mention it):
    #   FAIL: step 8 says when the walk is repeated from `phase-review` -> no 'asks for the UI walk again' with 'step 6' and '`phase-review -> ui-walk`'
    # (reworded after the review of PR 129 into numbered sub-steps; the checks follow the new words)
    #   FAIL: playbooks/session.md n_L8 exits `loop n_C12` -> missing
    from fwx.core import stages  # noqa: E402
    check("the stage table allows phase-review -> ui-walk", stages.allowed("session", "phase-review", "ui-walk"), "refused")
    check("step 8 says when the walk is repeated from `phase-review`",
          all(w in s8 for w in ("The walk again", "did not count", "Step 6 again", "from `phase-review`")),
          "no 'The walk again' with 'did not count', 'Step 6 again' and 'from `phase-review`'")
    # Two wording defects of the PR 130 review (the walk again re-runs step 6, which ends in fix rounds through `execute`; and the amendment's
    # "no branch, no `executing` row" gave no reason). Seen red on 1166a3d:
    #   FAIL: step 8's 'No execute' sub-step names the fix rounds of step 6 -> sub-step 2 of 'The walk again' is: 'No execute. Then this step again.'
    #   FAIL: step 8's amendment sub-step 3 gives the reason for no branch and no `executing` row -> sub-step 3 is: '3. At step 4 give the status line and the stop for objections, but make no branch and write no `executing` row.'
    walk2 = next((ln.strip() for ln in s8.splitlines() if ln.strip().startswith("2. ") and "Then this step again" in ln), "")
    check("step 8's 'No execute' sub-step names the fix rounds of step 6",
          "execute" in walk2 and "fix rounds of step 6" in walk2, "sub-step 2 of 'The walk again' is: %r" % walk2)
    # Review of PR 130: step 6's last walk may have been a recheck (`recheck` the path of a fix.json), and `workflows/ui-walk.js` then runs only the
    # verifiers, so repeating "the args of the last walk" would walk nothing. The sub-step says `recheck` is null. The name and meaning are
    # the workflow's own (`recheck (null, or the path of a fix.json: only the verifiers run)`), pinned below against its `whenToUse`.
    # Seen red on df27f7e: FAIL: step 8's 'Step 6 again' sub-step says the repeated walk is a full one, `recheck` null -> sub-step 1 is: '1. Step 6 again (it writes its own stage `ui-walk`, which the table allows from `phase-review`), with the `args` of the part's last walk.'
    walk1 = next((ln.strip() for ln in s8.splitlines() if ln.strip().startswith("1. Step 6 again")), "")
    check("step 8's 'Step 6 again' sub-step says the repeated walk is a full one, `recheck` null",
          "`recheck` null" in walk1 and "only the verifiers" in walk1, "sub-step 1 is: %r" % walk1)
    check("the workflow has the arg `recheck` that runs only the verifiers", "recheck (null, or the path of a fix.json: only the verifiers run)" in js, "the `whenToUse` of workflows/ui-walk.js changed")
    check("control: a sub-step 1 without it is caught", "`recheck` null" not in "1. Step 6 again, with the `args` of the part's last walk.")
    amend3 = next((ln.strip() for ln in s8.splitlines() if ln.strip().startswith("3. At step 4")), "")
    check("step 8's amendment sub-step 3 gives the reason for no branch and no `executing` row",
          "no branch" in amend3 and all(w in amend3 for w in ("already exist", "git worktree add")), "sub-step 3 is: %r" % amend3)
    check("control: a sub-step 2 without the fix rounds and a sub-step 3 without a reason are caught",
          "fix rounds of step 6" not in "2. No execute. Then this step again." and "git worktree add" not in "3. At step 4 give the status line, but make no branch and write no `executing` row.")
    # Rehearsal of a whole session (F-8): on the last part of a UI phase the session did not launch `skill-proposer`, because the launch was the
    # second sentence of step 8's long first paragraph. It is now sub-step 1 of step 8, on its own line, ahead of the report.
    # Seen red on b4c52fc: FAIL: step 8's sub-step 1 launches `skill-proposer` on the last part of a UI phase and returns NONE or a block and a patch -> no line of step 8 starting '1. ' with them, first lines: '8. **Review of the part.** Stage `phase-review` with `part <N>`. On the last part of a UI phase, launch `skill-proposer` first (inputs: the part's `context.md`, `decisions.tsv`, ...'
    prop1 = next((ln.strip() for ln in s8.splitlines() if ln.strip().startswith("1. ") and "skill-proposer" in ln), "")
    check("step 8's sub-step 1 launches `skill-proposer` on the last part of a UI phase and returns NONE or a block and a patch",
          bool(prop1) and all(w in prop1 for w in ("last part of a UI phase", "`plan.md`", "base sha", "`NONE: <reason>`", "a block and a patch"))
          and "skill-proposer" not in s8.splitlines()[0],
          "no line of step 8 starting '1. ' with them, first line: %r" % s8.splitlines()[0][:160])
    check("control: the old step 8, with the launch inside its first paragraph, is caught",
          not next((ln for ln in ("8. **Review of the part.** Stage `phase-review` with `part <N>`. On the last part of a UI phase, launch `skill-proposer` first (inputs: x); it returns `NONE: <reason>` or a block and a patch.",)
                    if ln.strip().startswith("1. ") and "skill-proposer" in ln), ""))
    # Review of PR 130, second reviewer: a session cut during an amendment resumes at step 2 or 3 from its last row (`planning` or `postmortem`)
    # and runs on into step 4, which makes the branch the amendment already has. Step 0 says it in one sentence.
    # Seen red on 31ceb02: FAIL: step 0 says a `planning` or `postmortem` row after an `executing` row is an amendment with no branch at step 4 -> step 0 has no 'amendment'
    s0 = step(texts["SKILL.md"], 0)
    check("step 0 says a `planning` or `postmortem` row after an `executing` row is an amendment with no branch at step 4",
          all(w in s0 for w in ("amendment", "`planning` or `postmortem` row", "after an `executing` row", "make no branch at step 4")),
          "step 0 has %s" % ("no 'amendment'" if "amendment" not in s0 else "the sentence without one of its parts"))
    check("control: a step 0 without the sentence is caught", "amendment" not in "Go to the step of the last stage: none or `discuss` 1; `planning` 2; `postmortem` 3.")
    l8 = block(session_pb, "n_L8")
    check("playbooks/session.md n_L8 exits `loop n_C12`", "- loop n_C12:" in l8, "missing")
    # A decision of the owner's review that changes a fact the plan states sends the phase back to the planner (the table allows
    # `phase-review -> planning`); the `source` the skill tells the `decisions` agent to use is the one `plan_step.py` looks for, and the
    # playbook's block of the review and of the plan carry the matching exit and sentence.
    # Seen red on 83c37cb (step 8 and the playbook said nothing of it):
    #   FAIL: step 8 sends a post-plan decision back to the planner -> no 'planning' with 'steps 2 and 3' and 'review of part <N>'
    #   FAIL: playbooks/session.md n_L8 exits `loop n_C2` -> missing
    from fwx import plan_step  # noqa: E402
    check("the stage table allows phase-review -> planning", stages.allowed("session", "phase-review", "planning"), "refused")
    check("step 8 sends a post-plan decision back to the planner",
          all(w in s8 for w in ("A decision after the plan", "the planner and the post-mortem get the decision", "Step 2 and step 3 again", "allowed from `phase-review`")),
          "no 'A decision after the plan', 'the planner and the post-mortem get the decision', 'Step 2 and step 3 again' and 'allowed from `phase-review`'")
    # Seen red on bd44ce6 (the sentence told the session to write stage `planning` while step 2 writes it, and to judge a fact of the plan):
    #   FAIL: step 8 does not write stage `planning` itself and does not ask the session to read the plan -> a stage `planning` of its own, or no 'You do not read the plan'
    check("step 8 does not write stage `planning` itself and does not ask the session to read the plan",
          "stage `planning`" not in s8 and "You do not read the plan" in s8, "a stage `planning` of its own, or no 'You do not read the plan'")
    check("step 2 writes stage `planning` and step 3 stage `postmortem`", "Stage `planning`" in step(texts["SKILL.md"], 2) and "Stage `postmortem`" in step(texts["SKILL.md"], 3), "missing")
    check("step 8 gives the decision the source the briefs look for",
          "`source` `review of part <N>`" in s8 and bool(plan_step._REVIEWED.match("review of part 1")), "the skill and plan_step._REVIEWED disagree")
    check("playbooks/session.md n_L8 exits `loop n_C2`", "- loop n_C2:" in l8, "missing")
    check("playbooks/session.md n_C2 names the decision of the review as what a replan attends", "his review" in block(session_pb, "n_C2"), "missing")
    # Rehearsal of a whole session (F-2): the session tried to edit `.claude/fwx.json` (a `sed -i`, then `Edit`, both refused) and no rule said not
    # to. forge generates that file and rewrites it at every session start. Rule 9 says so, names the owner's way out and forbids the edit.
    # Seen red on b4c52fc: FAIL: rule 9 says `.claude/fwx.json` is generated by forge, a wrong value goes to the owner through the `forge` CLI, and the file is never edited -> no rule 9
    rule9 = next((ln for ln in texts["SKILL.md"].split("## Steps")[0].splitlines() if ln.startswith("9. **")), "")
    check("rule 9 says `.claude/fwx.json` is generated by forge, a wrong value goes to the owner through the `forge` CLI, and the file is never edited",
          all(w in rule9 for w in ("`.claude/fwx.json`", "generated by forge", "the field and the value", "`forge` CLI", "Never edit")),
          "rule 9 is: %r" % rule9[:160] if rule9 else "no rule 9")
    check("control: a rule 9 that only says the file is generated is caught",
          not all(w in "9. **Generated config.** `.claude/fwx.json` is generated by forge." for w in ("the field and the value", "`forge` CLI", "Never edit")))
    # Rule 4: the documents are always committed in the main checkout, never on the phase branch (the old exception for a default branch that
    # takes changes by pull request could not be followed: in the rehearsal nothing was committed), and only the documents: `.md` and `.tsv`
    # files and the `demo/` pages, so the walk's `demo-state.json` (demo session cookies), logs and screenshots stay untracked. The command
    # line is run here as written. A `:(glob)` pathspec per pattern was tried first: `git add` fails outright when one pattern matches nothing
    # (`fatal: pathspec ':(glob).fwx/**/demo/*.html' did not match any files`, a phase with no demo page), so the list comes from `find`.
    # Seen red on 769589c (rule 4 said `git add .fwx` and named the phase branch):
    #   FAIL: rule 4 commits in the main checkout and no longer names the phase branch as a place -> 'requires a pull request' still in rule 4
    #   FAIL: rule 4's commit line adds the documents and leaves the walk's files untracked -> no line `cd <main_checkout> && find ...`
    rule4 = next((ln for ln in texts["SKILL.md"].splitlines() if ln.startswith("4. **Commits of `.fwx/`**")), "")
    check("rule 4 found", "forge commit" in rule4, "not found")
    check("rule 4 commits in the main checkout and no longer names the phase branch as a place",
          "requires a pull request" not in rule4 and "in its worktree" not in rule4 and "never on the phase branch" in rule4,
          "'requires a pull request' or 'in its worktree' still in rule 4, or no 'never on the phase branch'")
    lines = re.findall(r"`(cd <main_checkout> && find [^`]*)`", rule4)
    check("rule 4 has one commit line built on `find`", len(lines) == 1, "found %d" % len(lines))
    if len(lines) == 1:
        rc, tracked, untracked, _, _ = commit_effect(lines[0])
        phase = ".fwx/milestones/v1/phases/01-a"
        check("rule 4's commit line adds the documents and the demo pages", rc == 0 and all(f in tracked for f in (
            ".fwx/PROJECT.md", ".fwx/milestones/v1/MILESTONE.md", phase + "/context.md", phase + "/audit.tsv", phase + "/research/r.md", phase + "/demo/page.html")),
              "rc %s, tracked %s" % (rc, tracked))
        check("rule 4's commit line leaves demo-state.json, a log and a screenshot untracked", all(any(u.endswith(n) for u in untracked) for n in (
            "demo-state.json", "up.log", "ui-walk/1-1/shot.png", "demo/shot.png")) and not [f for f in tracked if f.endswith(("demo-state.json", ".log", ".png"))],
              "untracked %s, tracked %s" % (untracked, tracked))
    # Review of PR 130: the commit took `-- .fwx`, which records the working-tree contents of every tracked file under it, so a `demo-state.json`
    # tracked by an older session and changed since went into the commit although `find` left it out of `git add`. The line is run in a toy
    # whose older session tracked such a file, in a phase with no demo page, and a second time with nothing new.
    # Seen red on fc1cd49: FAIL: rule 4's commit line leaves a changed, previously tracked walk file out of the commit -> rc 0, the commit holds [...ui-walk/0-0/demo-state.json...]
    if len(lines) == 1:
        rc, _, _, last, _ = commit_effect(lines[0], stale=True)
        check("rule 4's commit line leaves a changed, previously tracked walk file out of the commit", rc == 0 and bool(last) and not [f for f in last if f.endswith("demo-state.json")],
              "rc %s, the commit holds %s" % (rc, last))
        rc, tracked, _, last, _ = commit_effect(lines[0], demo=False)
        check("rule 4's commit line works in a phase with no demo page", rc == 0 and ".fwx/milestones/v1/phases/01-a/context.md" in last and not [f for f in tracked if "/demo/" in f],
              "rc %s, the commit holds %s" % (rc, last))
        rc, _, _, _, again = commit_effect(lines[0], twice=True)
        check("rule 4's commit line run again with nothing new exits 1 (git: nothing to commit) and makes no empty commit", rc == 0 and again == 1, "rc %s, second rc %s" % (rc, again))
    old = commit_effect("git -C <main_checkout> add .fwx && git -C <main_checkout> commit -m \"<message>\" -- .fwx")
    check("control: the old line `git add .fwx` tracks the walk's session file", any(f.endswith("demo-state.json") for f in old[1]), "tracked %s" % old[1])
    # control: the old text's own commit part (`-- .fwx`) records a tracked, changed non-document
    check("control: `commit -- .fwx` after the find-built add commits a previously tracked walk file", any(f.endswith("demo-state.json") for f in commit_effect(
        "cd <main_checkout> && find .fwx -type f ! -name '.*' \\( -name '*.md' -o -name '*.tsv' -o -path '*/demo/*.html' \\) -print0 | git add --pathspec-from-file=- --pathspec-file-nul && git commit -m \"<message>\" -- .fwx",
        stale=True)[3]), "the control line did not commit it")
    check("control: block() cuts one block", "### n_L9" not in l8 and l8.startswith("### n_L8"), l8[:40])

    # DTC-34: the worktree of a phase is removed by the next session, once its PR is merged and it is clean, never at the close.
    closing = read(os.path.join("references", "closing.md"))
    cleanup = next((ln for ln in closing.splitlines() if ln.startswith("4. **Cleanup.**")), "")
    check("closing.md step 4 found", "fwx walk stop --orphans" in cleanup, "not found")
    check("closing.md step 4 does not remove the phase worktree", "git worktree remove" not in cleanup, "`git worktree remove` is in it")
    check("closing.md step 4 says the worktree stays until its PR is merged", "stays" in cleanup and "merged" in cleanup, "no 'stays' or no 'merged'")
    s0 = step(texts["SKILL.md"], 0)
    need = ["--state merged", "status --porcelain", ".claude/worktrees/", "no force", "git branch -d"]
    check("SKILL.md step 0 clears merged worktrees: merged PR, clean, no force", all(w in s0 for w in need), "missing: %s" % [w for w in need if w not in s0])
    check("SKILL.md step 0 never uses `git branch -D`", "branch -D" not in s0, "`git branch -D` is in it")
    check("SKILL.md step 0 clears worktrees before the retake and the resume", in_order(s0, "--state merged", "retake", "fwx session --json"), "order is not sweep, retake, resume")
    check("playbooks/session.md n_L3 clears merged worktrees (--state merged)", "--state merged" in block(session_pb, "n_L3"), "missing")
    check("playbooks/session.md n_L10 no longer removes the phase worktree", "removes only the phase worktree" not in block(session_pb, "n_L10"), "'removes only the phase worktree' still in it")
    # controls: the old closing step and a step 0 without the rule fail, a step 0 with `-D` fails.
    check("control: the old closing step 4 is caught", "git worktree remove" in "4. **Cleanup.** Remove it with `git worktree remove <path>` and no force.")
    check("control: a step 0 without the rule is caught", not all(w in "0. **Where you are.** Run `fwx session --json`." for w in need))
    check("control: a step 0 with `git branch -D` is caught", "branch -D" in "then `git branch -D <branch>`")
    check("control: step 0 is cut by step()", step("## Steps\n0. **A.** x\n1. **B.** y\n", 0).startswith("0. **A.**") and "y" not in step("## Steps\n0. **A.** x\n1. **B.** y\n", 0))

    # control: the checks above can fail.
    check("control: a cited reference that is not there is caught", set(re.findall(r"references/([a-z-]+\.md)", "see references/gone.md and references/here.md")) - {"here.md"} == {"gone.md"})
    check("control: a step 8 that checks before it saves fails", not in_order("`state` returns; run fwx report lint on report-<n>.md, then `Write` it", "`state`", "report-<n>.md", "`Write`", "fwx report lint"))
    check("control: a step 8 that saves then checks passes", in_order("`state` returns; save it to report-<n>.md with `Write`, then run fwx report lint", "`state`", "report-<n>.md", "`Write`", "fwx report lint"))
    check("control: a cited field the code lacks is caught", missing_keys(["used_percentage", "usage_percentage"], '{"used_percentage": 1}') == ["usage_percentage"])
    check("control: step() cuts one numbered step", step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2).startswith("2. **B.**") and "z" not in step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2))
    check("control: 'verdict wait' is caught", files_naming("verdict wait", {"x.md": "run verdict wait in the background"}) == ["x.md"])
    check("control: revert before the question fails", not asks_before_revert("run wave new --revert 1, then ask: revert it?"))
    check("control: question before the revert passes", asks_before_revert("ask: revert it? Then wave new --revert 1"))
    check("control: a command that does not exist is not known", "frobnicate" not in known and "frobnicate" in fwx_commands("run fwx frobnicate now"))


main()
for line in skips:
    print(line)
for line in fails:
    print(line)
print("%d checks looked at, %d failed, %d skipped" % (looked[0], len(fails), len(skips)))
sys.exit(1 if fails else 0)
