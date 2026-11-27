#!/usr/bin/env python3
"""The session skill's text where code reads it or the owner set the rule: the commands it names exist, the fields it reads are fields the code
has, the commit line of rule 4 does what it says in a toy repo, a rejection is asked before it is reverted, a phase worktree is removed only
once its PR is merged, nothing launches a `decisions` agent or tells the session to ask without a recommendation.

Plain Python, no network: it reads skills/session/ of the checkout it sits in (`python3 tests/test_session_text.py [ROOT]` reads another
tree) and runs that tree's `bin/fwx --help` for the command list. Commands that only exist on another branch (`walk` on the UI-walk
branch) are SKIPped with their reason printed, never silently; the rest must exist.

09.3 T33 kept the checks that a code path reads (a command, a field, a stage the table allows, the line rule 4 runs) or that guard a rule the
owner set (DTC-34 on worktrees, D9 on recommendations, D11 on the end of fwx's work at the pull request, D17 on recording decisions), and
removed the checks that pinned wording (the steps' sentences, the sub-steps of step 8, rule 9, the words of ui-review.md, the critique
skills' "another model", the shared marker `Noticed:`) together with their red logs.

Seen red on copies of the real texts (a copy of plugins/fwx with the pinned words changed; the first FAIL line printed):
  references/ui-review.md, "details.unverified" -> "details.unverfied":  FAIL: references/ui-review.md cites only fields the workflow returns -> not returned: ['unverfied']
  references/ui-review.md, "`support` `approved`" -> "`support` `approvd`":  FAIL: ui-review.md names the support of `not_defect` and `redo`, each a value `fwx decision new` accepts -> ui-review.md {'not_defect': 'approvd', 'redo': 'chosen'}, SUPPORT ('chosen', 'approved', 'unexamined', 'agent-assumption')
  references/ui-review.md, "revert it?" -> "proceed?":  FAIL: ui-review.md asks before the revert -> no 'revert it?' before the first '--revert'
  SKILL.md, "-name '*.tsv'" -> "-name '*.tsvx'" (the line of rule 4 is run in a toy repo):  FAIL: rule 4's commit line adds the documents and the demo pages -> rc 0, tracked ['.fwx/PROJECT.md', ..., '.fwx/milestones/v1/phases/01-a/research/r.md'] (no audit.tsv)
  SKILL.md, "--state merged" -> "--state open" (DTC-34):  FAIL: SKILL.md step 0 clears merged worktrees: merged PR, clean, no force -> missing: ['--state merged']
  SKILL.md, "fwx session --json" -> "fwx session --jsn":  FAIL: SKILL.md step 0 clears worktrees before the retake and the resume -> order is not sweep, retake, resume
  references/factory-return.md, "fwx decision new" -> "the `decisions` agent" (D17):  FAIL: no text launches or names the `decisions` agent, and its file is gone -> references/factory-return.md:9
  SKILL.md, "Recommended:" -> "Suggested:" (D9):  FAIL: every question to the owner carries a `Recommended:` line -> no `Recommended:` in ['SKILL.md rule 6', 'SKILL.md step 4', 'SKILL.md step 8']
09.6 T61 (the session runs `fwx wave run`; the same kind of copy, the first FAIL line printed):
  SKILL.md, the texts at a8f5904 (`fwx:execute` at :23, :46, :52):  FAIL: the session names no fwx:execute -> SKILL.md:23, :46, :52, ui-review.md:10
  references/ui-review.md, "fwx wave run ... --revert" -> "fwx wave new ... --revert":  FAIL: the session runs no `fwx wave new`: `fwx wave run` prepares the part itself -> ui-review.md:10
  references/ui-review.md, "--revert" -> "--revertt":  FAIL: every flag of a `fwx wave run` the texts give is one `wave run` takes -> named [..., '--revertt'], not taken: ['--revertt']
  SKILL.md, "with `run_in_background`" -> "and wait":  FAIL: step 5 runs `fwx wave run` in the background -> run commands [...], run_in_background False
  SKILL.md, "`result.consider`" -> "`result.considr`":  FAIL: step 5 reads the leftovers from fields the run's own files have -> cites ['file', 'considr', ...], the files have [...]
  SKILL.md, a correction's `executing` row -> a first one (`part <N> branch <branch>`):  FAIL: step 5 writes no first `executing` row for a part -> writes ['`part <N> branch <branch>`']
  references/closing.md, "gh pr ready <number>" -> "mark it ready":  FAIL: closing.md marks the gate's draft pull request ready and writes its body -> missing `gh pr ready`, `gh pr edit` or the fallback `gh pr create`
  references/closing.md, the `fwx wave list` sweep -> "remove each run":  FAIL: closing.md sweeps the runs `fwx wave list` shows with `fwx wave remove --run` -> no 'fwx wave list' ... 'fwx wave remove --run' in order
  agents/review-verifier.md, "`verdicts <report path>`" -> "`verdicts <path>`":  FAIL: the verifier replies with the line `wave findings --verdicts` reads -> no `verdicts <report path>` in agents/review-verifier.md, or review.VERDICT_LINE does not read it
  agents/reviewer.md, "names a brief file" -> "is your brief, there is no brief file":  FAIL: no agent says it has no brief file -> still says it in ['reviewer']
01.3 T32 (the orchestrator writes the report from the template; the same copy-and-change, the first FAIL line printed):
  references/closing.md, `--why "PR <url>"` -> `--why "done"`:  FAIL: closing.md writes the pull request body from the same template and the closing stage row with the PR link -> missing ['--why "PR <url>"']
Each kept check also has a control on a toy text (the "control:" checks).
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


def asks_before_revert(text):
    ask, flag = text.find("revert it?"), text.find("--revert")
    return ask != -1 and (flag == -1 or ask < flag)


def step(text, n):
    """The text of numbered step `n` of SKILL.md, after its `## Steps` heading (the fixed rules above it are numbered too), up to the
    next numbered step or the end."""
    text = text[text.find("## Steps"):] if "## Steps" in text else text
    m = re.search(r"^%d\. \*\*.*?(?=^\d+\. \*\*|\Z)" % n, text, re.S | re.M)
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
    for rel in (".fwx/project.md", ".fwx/milestones/v1/milestone.md", phase + "/context.md", phase + "/audit.tsv", phase + "/research/r.md", phase + "/demo/page.html",
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


def rule6_of(text):
    return next((ln for ln in text.split("## Steps")[0].splitlines() if ln.startswith("6. **")), "")


def in_order(text, *words):
    """True when every word is in `text` and each comes after the one before it."""
    pos = -1
    for w in words:
        i = text.find(w, pos + 1)
        if i == -1:
            return False
        pos = i
    return True


def fwx_commands(text):
    """Top-level `fwx <name>` words; `fwx:ui-walk` (a workflow) has a colon and is not one."""
    return set(re.findall(r"\bfwx ([a-z][a-z-]*)\b", text))


def mentions(texts, word):
    """{file name: [line numbers]} of the lines of each text that name `word`."""
    return {os.path.basename(n): [i for i, ln in enumerate(t.splitlines(), 1) if word in ln] for n, t in texts.items() if word in t}


def where(found):
    """`SKILL.md:23, :46, ui-review.md:10` for the result of `mentions`."""
    return ", ".join("%s:%s" % (n, ", :".join(map(str, ls))) for n, ls in sorted(found.items()))


def run_flags(text):
    """The flags of each `fwx wave run ...` command a text gives, between backticks: [{flag, ...}] one set per command."""
    return [set(re.findall(r"--[a-z-]+", c)) for c in re.findall(r"`(fwx wave run [^`]*)`", text)]


def result_fields(text):
    """The `result.<field>` words of a text: fields of what a run's own files record (`<n>-findings.json`, `<n>-report.json`)."""
    return re.findall(r"`result\.([a-z_]+)`", text)


def first_executing_rows(text):
    """The `part <N> branch <B>` rows a text has the session write: a part's first `executing` row (step 4 writes the phase's)."""
    return re.findall(r"`part <N> branch[^`]*`", text)


def main():
    texts = {rel: read(rel) for rel in ("SKILL.md", os.path.join("references", "ui-review.md"), os.path.join("references", "part-report.md"),
                                        os.path.join("references", "closing.md"), os.path.join("references", "factory-return.md"))}
    skill, review, closing = texts["SKILL.md"], texts[os.path.join("references", "ui-review.md")], texts[os.path.join("references", "closing.md")]
    rep_ref = texts[os.path.join("references", "part-report.md")]
    s8 = step(skill, 8)
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx import plan, state  # noqa: E402
    from fwx.core import stages  # noqa: E402
    from fwx.commands import wave as wave_cmd  # noqa: E402
    from fwx.execute import report as wave_report, review as wave_review  # noqa: E402

    # Every command the texts name exists, or is skipped with its reason.
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

    # Every `references/<file>.md` the session skill cites exists, and every file in references/ is cited.
    cited = set(re.findall(r"references/([a-z-]+\.md)", skill))
    present = set(os.listdir(os.path.join(SESSION, "references")))
    check("every references/ file SKILL.md cites exists", not (cited - present), "missing %s" % sorted(cited - present))
    check("every file in references/ is cited by SKILL.md", not (present - cited), "uncited %s" % sorted(present - cited))

    # 01.3 T32 (D3): the orchestrator writes the report itself, from `fwx wave --run <R> --json` and the last `evidence` row of audit.tsv, into the
    # template `templates/phase/report.md`, and pastes it to the owner; nothing is saved, so no text launches the `state` agent or names `state.md` or
    # `report-<n>.md`. The pull request body is made from the same template at the close, and the closing stage row carries the PR link. Seen red at
    # 56a196a (the texts and the template before this task):
    #   FAIL: no session text launches `state` or names `state.md` or `report-<n>.md` -> SKILL.md:18, :19, :33, :60, references/factory-return.md:8, references/part-report.md:6, :9, ...
    #   FAIL: part-report.md fills templates/phase/report.md from `fwx wave --run <R> --json` and the last evidence row, and pastes it -> missing [...]
    #   FAIL: closing.md writes the pull request body from the same template and the closing stage row with the PR link -> missing [...]
    #   FAIL: templates/phase/report.md has the six sections of the orchestrator's report in at most 40 lines -> ...
    def mirror_files(texts_by_name):
        return {n: [i for i, ln in enumerate(t.splitlines(), 1) if re.search(r"`state`|state\.md|report-<n>", ln)] for n, t in texts_by_name.items()}
    old_mirror = {n: ls for n, ls in mirror_files(texts).items() if ls}
    check("no session text launches `state` or names `state.md` or `report-<n>.md`", not old_mirror,
          ", ".join("%s:%s" % (n, ", :".join(map(str, ls))) for n, ls in sorted(old_mirror.items())))
    check("control: a text that launches `state` or names its files is caught",
          all(mirror_files({"a.md": t})["a.md"] == [1] for t in ("Launch `state` now", "writes state.md", "saves report-<n>.md")) and mirror_files({"a.md": "the stage rows"})["a.md"] == [])
    template_rel = os.path.join(ROOT, "templates", "phase", "report.md")
    with open(template_rel, encoding="utf-8") as f:
        template = f.read()
    TEMPLATE_HEADINGS = ("## Goal", "## Done", "## Assumptions taken without asking", "## Outside", "## Evidence", "## PR")

    def template_problems(text):
        heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
        out = ["heading %r" % h for h in TEMPLATE_HEADINGS if h not in heads]
        if len(text.splitlines()) > 40:
            out.append("%d lines" % len(text.splitlines()))
        return out
    check("templates/phase/report.md has the six sections of the orchestrator's report in at most 40 lines", not template_problems(template), "problems: %s" % template_problems(template))
    # CodeRabbit PR 279: the 41-line fixture also lacked five headings, so it passed with the length check removed. Each control now has one fault.
    # Seen red with the length check removed from template_problems: "FAIL: control: a template with all six sections and 41 lines is caught on length alone"
    check("control: a template with a missing section is caught on that alone", template_problems("## Goal\n") == ["heading %r" % h for h in TEMPLATE_HEADINGS[1:]])
    check("control: a template with all six sections and 41 lines is caught on length alone",
          template_problems("\n".join(TEMPLATE_HEADINGS) + "\n" * 36) == ["41 lines"], "got %s" % template_problems("\n".join(TEMPLATE_HEADINGS) + "\n" * 36))

    def fills_template(text):
        return [w for w in ("templates/phase/report.md", "fwx wave --run <R> --json", "`outside`", "`consider`", "last `evidence` row", "audit.tsv", "paste") if w not in text]
    check("part-report.md fills templates/phase/report.md from `fwx wave --run <R> --json` and the last evidence row, and pastes it", not fills_template(rep_ref),
          "missing %s" % fills_template(rep_ref))
    check("control: a part-report.md that names no template is caught", bool(fills_template("Run `fwx wave --run <R> --json` and paste the last `evidence` row of audit.tsv.")))

    # r1-F1: the keys the report texts read from `fwx wave --run <R> --json` are the keys `integrate.summary` returns: the review's facts are under
    # `findings` (`findings.consider`, `findings.outside` for the filed ones), the unfiled `outside` items at the top. `result` and `file` are not keys
    # of it (`result` belongs to `fwx wave list --json`). Seen red before the fix:
    #   FAIL: part-report.md and templates/phase/report.md read only keys `wave --run --json` returns -> cites no `findings.<key>`; names ['`result`', '`file`']
    from fwx.execute import integrate as wave_integrate  # noqa: E402
    with tempfile.TemporaryDirectory(prefix="fwx-summary-") as toy_repo:
        subprocess.run("git init -q -b master", shell=True, cwd=toy_repo, check=True)
        summary_keys = wave_integrate.summary(toy_repo, None, branch="master")[1]
    top_keys, found_keys = set(summary_keys), set(summary_keys["findings"])

    def wave_json_problems(text):
        dotted = re.findall(r"`findings\.([a-z_]+)`", text)
        bare = [w for w in ("`result`", "`file`") if w in text and w[1:-1] not in top_keys]
        return (["cites no `findings.<key>`"] if not dotted else []) + ["`findings.%s`" % k for k in dotted if k not in found_keys] + (["names %s" % bare] if bare else [])
    problems = wave_json_problems(rep_ref + "\n" + template)
    check("part-report.md and templates/phase/report.md read only keys `wave --run --json` returns", not problems and "outside" in top_keys, "; ".join(problems))
    check("control: a text that reads `result` or `findings.fil` of the run is caught",
          bool(wave_json_problems("read `result` and `findings.consider`")) and bool(wave_json_problems("read `findings.fil`")) and not wave_json_problems("`findings.consider` and `findings.outside`"))

    # 01.3 fix g3: `wave --run --json` holds no Linear keys, so the texts take the key from step 5's filing of this session, else `none filed`, and
    # step 5 no longer files "for the part report to read back from the stage rows". Seen red at a913be9:
    #   FAIL: the report texts take a Linear key from step 5's filing, else `none filed` -> part-report.md still takes Linear keys from the run's json; part-report.md has no `none filed`; template Outside does not name step 5's filing; step 5 says the report reads outside items back from stage rows
    def linear_key_problems(rep, tmpl, step5):
        return (["part-report.md still takes Linear keys from the run's json"] if "their Linear keys" in rep else []) + (
            ["part-report.md has no `none filed`"] if "none filed" not in rep else []) + (
            ["part-report.md does not name step 5's filing"] if "step 5" not in rep else []) + (
            ["template Outside does not name step 5's filing"] if "step 5" not in tmpl.split("## Outside")[-1].split("## Evidence")[0] else []) + (
            ["step 5 says the report reads outside items back from stage rows"] if "reads them back from the stage rows" in step5 else [])
    check("the report texts take a Linear key from step 5's filing, else `none filed`", not linear_key_problems(rep_ref, template, step(skill, 5)),
          "; ".join(linear_key_problems(rep_ref, template, step(skill, 5))))
    check("control: texts that read Linear keys from the run's json are caught",
          len(linear_key_problems("take their Linear keys from it", "## Outside\n## Evidence", "because the part report reads them back from the stage rows")) == 5)

    # r1-F1 (fix-1): a Linear key filed at step 5 must survive into a later session (a resume, the close's PR body), so step 5 records each as
    # `filed: <where> - <KEY>` in its stage row's `--why` and the report texts read the key from those rows. Seen red before the fix:
    #   FAIL: step 5 records filed keys in the stage row and the report reads them there -> step 5 has no `filed: <where> - <KEY>`; part-report.md does not read `filed:` from the stage rows; template Outside does not name the `filed:` entry
    def filed_key_problems(rep, tmpl, step5):
        outside_section = tmpl.split("## Outside")[-1].split("## Evidence")[0]
        return (["step 5 has no `filed: <where> - <KEY>`"] if "`filed: <where> - <KEY>`" not in step5 else []) + (
            ["part-report.md does not read `filed:` from the stage rows"] if "filed: <where> - <KEY>" not in rep else []) + (
            ["template Outside does not name the `filed:` entry"] if "`filed:`" not in outside_section else [])
    check("step 5 records filed keys in the stage row and the report reads them there", not filed_key_problems(rep_ref, template, step(skill, 5)),
          "; ".join(filed_key_problems(rep_ref, template, step(skill, 5))))
    check("control: texts with no `filed:` record are caught", len(filed_key_problems("none filed", "## Outside\n## Evidence", "unfiled go in the `--why`")) == 3)

    # 01.3 fix g11, r1-F1 and r1-SO1 (fix-2): a `--why` that carries text of a report, a finding or the app under test (`filed:`, `outside:`, the walkers'
    # findings) goes through a single-quoted heredoc, said once in rule 3; inside double quotes a `$(...)` or backtick in that text runs. Every
    # `--why "<` site in skills/session/ must be the plain stage form `--why "<text>"`, steps 5 and 6 point at the rule, and the terminator is one
    # no report line contains. Seen red at the r1-F1 commit (rule 3 had no heredoc; step 5 and 6 used the terminator `WHY`):
    #   FAIL: every `--why` that carries report, finding or app text goes through the heredoc of rule 3 -> rule 3 has no `--why "$(cat <<'WHY_END_7f3a'`; rule 3 does not say the text is never pasted inside double quotes; step 5 does not point at rule 3; step 6 has no `--why "$(cat <<'WHY_END_7f3a'`; terminator `WHY` is a line a report may contain: SKILL.md
    def why_quoting_problems(rules, step5, step6, all_texts):
        form = "--why \"$(cat <<'WHY_END_7f3a'"
        return (["rule 3 has no `%s`" % form] if form not in rules else []) + (
            ["rule 3 does not say the text is never pasted inside double quotes"] if "never pasted inside double quotes" not in rules else []) + (
            ["step 5 does not point at rule 3"] if "rule 3" not in step5 else []) + (
            ["step 6 has no `%s`" % form] if form not in step6 else []) + [
            "terminator `WHY` is a line a report may contain: %s" % rel for rel, t in all_texts.items() if "<<'WHY'" in t] + [
            "double-quoted `--why \"<%s>\"` in %s" % (w, rel) for rel, t in all_texts.items() for w in re.findall(r'--why "<([^>]*)>', t) if w != "text"]
    rules_of_skill = skill.split("## Steps")[0]
    check("every `--why` that carries report, finding or app text goes through the heredoc of rule 3",
          not why_quoting_problems(rules_of_skill, step(skill, 5), step(skill, 6), texts),
          "; ".join(why_quoting_problems(rules_of_skill, step(skill, 5), step(skill, 6), texts)))
    good = {"SKILL.md": "--why \"$(cat <<'WHY_END_7f3a'` never pasted inside double quotes, rule 3, --why \"<text>\""}
    check("control: texts with no heredoc rule, the old terminator and a double-quoted findings `--why` are caught",
          len(why_quoting_problems("a --why", "step", "wave fix --why \"<findings>\"", {"SKILL.md": "<<'WHY' --why \"<findings>\""})) == 6
          and not why_quoting_problems(good["SKILL.md"], "rule 3", good["SKILL.md"], good))

    # 01.3 fix g4: the `consider` findings print once, in the report's Done (templates/phase/report.md); step 8.2 no longer pastes them again from the
    # run's raw `<n>-findings.json`. Seen red at a913be9:
    #   FAIL: step 8.2 does not paste the consider findings a second time from `<n>-findings.json` -> names ['`result.consider`', '`consider` findings']
    def consider_twice(text):
        return [w for w in ("`result.consider`", "`consider` findings") if w in text]
    check("step 8.2 does not paste the consider findings a second time from `<n>-findings.json`", not consider_twice(s8), "names %s" % consider_twice(s8))
    check("control: a step 8.2 that pastes `result.consider` after the report is caught", bool(consider_twice("then: the `consider` findings (`result.consider` of the run")))

    # 01.3 fix g8: open `agent-assumption` rows of decisions.tsv are a source of the report's Assumptions, for a resume or the close. Seen red at a913be9:
    #   FAIL: part-report.md takes Assumptions also from the open `agent-assumption` rows of decisions.tsv -> missing `agent-assumption` or decisions.tsv
    def assumption_sources(text):
        return [w for w in ("`agent-assumption`", "decisions.tsv") if w not in text]
    check("part-report.md takes Assumptions also from the open `agent-assumption` rows of decisions.tsv", not assumption_sources(rep_ref),
          "missing %s" % ", ".join(assumption_sources(rep_ref)))
    check("control: a part-report.md that takes assumptions only from the orchestrator's own choices is caught", len(assumption_sources("from the choices you made yourself (rule 6)")) == 2)

    def closing_body(text):
        return [w for w in ("templates/phase/report.md", '--why "PR <url>"', '--why "commit <sha>"') if w not in text] + (
            [] if in_order(text, "templates/phase/report.md", "gh pr edit", "fwx stage <phase folder> closed") else ["the order template, gh pr edit, stage row"])
    check("closing.md writes the pull request body from the same template and the closing stage row with the PR link", not closing_body(closing), "missing %s" % closing_body(closing))
    check("control: a closing whose body has its own four sections is caught", bool(closing_body("`gh pr edit` with ## Why, ## What changed; `fwx stage <phase folder> closed`")))

    # 01.3 r1-F1: evidence rows are written to the part folder (execute/run.py runs `verify --dir self.part`), so a phase with subphases has none in its
    # own audit.tsv. The closing body must read them per part, fall back to the phase folder only when the plan has no subphases, and say a part
    # with no row rather than guess. Seen red at eccd269 (closing.md read "the last `evidence` row of the phase's `audit.tsv`"):
    #   FAIL: closing.md reads the evidence rows per part and says a part with none -> missing ["`evidence` row of each part's `audit.tsv`", "the phase folder's", 'no subphases', 'no evidence row']
    def closing_evidence(text):
        return [w for w in ("`evidence` row of each part's `audit.tsv`", "the phase folder's", "no subphases", "no evidence row") if w not in text]
    check("closing.md reads the evidence rows per part and says a part with none", not closing_evidence(closing), "missing %s" % closing_evidence(closing))
    check("control: a closing that reads only the phase's audit.tsv is caught",
          bool(closing_evidence("the last `evidence` row of the phase's `audit.tsv` (the commit, the command and its exit code)")))

    # 09.4 D13: the budget nag is gone, so no session text tells an agent to run `fwx budget` or to read its fields, and no check reads the
    # deleted lib/fwx/commands/budget.py. Seen red before the texts changed (rule 7, step 2 and step 5 still named it):
    #   FAIL: no session text names `fwx budget` or its fields -> SKILL.md: ['fwx budget', 'used_percentage', 'week_tight']
    nagging = {n: [w for w in ("fwx budget", "used_percentage", "week_tight") if w in tx] for n, tx in texts.items()}
    nagging = {n: ws for n, ws in nagging.items() if ws}
    check("no session text names `fwx budget` or its fields", not nagging, ", ".join("%s: %s" % kv for kv in sorted(nagging.items())))
    check("control: a text that names `fwx budget` is caught", any(w in "7. **Budget.** Run `fwx budget --json`" for w in ("fwx budget", "used_percentage")))
    # r1-F1: step 7 sent a refused `fwx:discuss` call to "rule 8" after the budget rule's removal renumbered the rules ("Generated config" became 8).
    # Seen red before the cite followed: FAIL: step 7's refused-call cite names the rule on skills and workflows -> 'rule 8 applies' is "Generated config"
    cited = re.search(r"If the call is refused, rule (\d+) applies", step(skill, 7))
    titled = re.search(r"^%s\. \*\*([^*]+?)\.\*\*" % (cited.group(1) if cited else "0"), skill, re.M)
    check("step 7's refused-call cite names the rule on skills and workflows", bool(titled) and titled.group(1) == "Skills and workflows",
          "'rule %s applies' is %s" % (cited.group(1) if cited else "?", '"%s"' % titled.group(1) if titled else "no rule"))
    check("control: a cite of a rule with another title is caught", re.search(r"^8\. \*\*([^*]+?)\.\*\*", "7. **Skills and workflows.** x\n8. **Generated config.** y", re.M).group(1) != "Skills and workflows")
    # 09.6 T61: a part runs as one `fwx wave run` (prepared in process, every agent an Orca worker), so the session launches no `fwx:execute` workflow
    # (rule 7 keeps the Workflow tool for `fwx:ui-walk`) and runs no `fwx wave new` of its own. Seen red at 3bb7ef7:
    #   FAIL: the session names no fwx:execute -> SKILL.md:23, :46, :52, ui-review.md:10
    session_texts = {n: t for n, t in texts.items()}
    old_workflow = mentions(session_texts, "fwx:execute")
    check("the session names no fwx:execute", not old_workflow, where(old_workflow))
    check("control: a text that launches fwx:execute is caught, one that launches fwx:ui-walk is not",
          bool(mentions({"a.md": "Launch `fwx:execute` now"}, "fwx:execute")) and not mentions({"a.md": "Launch `fwx:ui-walk` now"}, "fwx:execute"))
    old_prepare = mentions(session_texts, "wave new")
    check("the session runs no `fwx wave new`: `fwx wave run` prepares the part itself", not old_prepare, where(old_prepare))
    s5, s6 = step(skill, 5), step(skill, 6)
    # The owner rejected a terminal tab beside his chat in the main checkout's workspace: step 5 runs `fwx wave run` with `run_in_background` from the phase worktree,
    # with `--orchestrator`, and creates no Orca terminal at all (the run's own sender terminal lives in the phase worktree's workspace, made by the run). Progress is
    # shown by the `fwx` Orca panel, `fwx wave list` and `fwx wave list --json`. Seen red on the text before this rule (step 5 made `orca terminal create`):
    #   FAIL: step 5 runs `fwx wave run` in the background with --orchestrator and creates no Orca terminal -> run commands [...], run_in_background True, orca terminal create present True, orchestrator True
    #   FAIL: no session text tells the session to create an Orca terminal -> [('SKILL.md', 46)]
    #   FAIL: step 5 says where live progress shows -> missing ['wave list --json', 'local.fwx-session']
    def background_run(text):
        return bool(run_flags(text)) and "run_in_background" in text and any("--orchestrator" in f for f in run_flags(text)) and "orca terminal create" not in text
    check("step 5 runs `fwx wave run` in the background with --orchestrator and creates no Orca terminal", background_run(s5),
          "run commands %s, run_in_background %s, orca terminal create present %s, orchestrator %s" % (
              run_flags(s5), "run_in_background" in s5, "orca terminal create" in s5, any("--orchestrator" in f for f in run_flags(s5))))
    check("control: a step 5 that opens a terminal is caught",
          not background_run("5. Run `fwx wave run --part-dir <part> --orchestrator x` with `run_in_background`; `orca terminal create --worktree path:<main checkout> --title t`."))
    check("control: a step 5 with no background is caught",
          not background_run("5. Run `fwx wave run --part-dir <part> --orchestrator x` and wait."))
    tabs = [(os.path.basename(n), k) for n, t in texts.items() for k, l in enumerate(t.splitlines(), 1) if "orca terminal create" in l]
    check("no session text tells the session to create an Orca terminal", not tabs, "%s" % tabs)
    check("control: a line that creates one is caught", bool([1 for l in ["`orca terminal create --worktree path:x`"] if "orca terminal create" in l]))
    def progress_where(text):
        return [w for w in ("wave list --json", "local.fwx-session", "fwx wave list") if w not in text]
    check("step 5 says where live progress shows", not progress_where(s5), "missing %s" % progress_where(s5))
    check("control: a step 5 that names no progress view is caught", bool(progress_where("5. Run `fwx wave run --part-dir <part>` with `run_in_background`.")))
    stale = [(os.path.basename(n), k) for n, t in texts.items() for k, l in enumerate(t.splitlines(), 1) if "wave run" in l and "in the background" in l]
    check("no text still tells the session to run `fwx wave run` \"in the background\" (steps 5 and 6 and ui-review.md point at step 5)", not stale, "%s" % stale)
    check("control: a line that says it is caught", bool([1 for l in ["run `fwx wave run ... --fix f` in the background"] if "wave run" in l and "in the background" in l]))
    accepted = set(re.findall(r"--[a-z-]+", wave_cmd.RUN_USAGE))
    named = {f for text in texts.values() for flags in run_flags(text) for f in flags}
    check("every flag of a `fwx wave run` the texts give is one `wave run` takes", named <= accepted and len(named) >= 6, "named %s, not taken: %s" % (sorted(named), sorted(named - accepted)))
    check("control: a flag `wave run` does not take is caught", {"--part-dir", "--rounds"} - accepted == {"--rounds"})
    need = {"step 5": (s5, {"--from", "--fix", "--resume"}), "step 6": (s6, {"--fix"}), "references/ui-review.md": (review, {"--revert", "--fix"})}
    for name, (text, flags) in need.items():
        given = set().union(*run_flags(text)) if run_flags(text) else set()
        check("%s runs `fwx wave run` with %s" % (name, " and ".join(sorted(flags))), flags <= given, "its run commands carry %s" % sorted(given))
    # Orchestrator steering: the session starts every run with `--orchestrator` (its own chat) and says how a forwarded question is answered. Seen red on the text before:
    #   FAIL: step 5 starts `fwx wave run` with --orchestrator and says how a forwarded question is answered -> missing ['--orchestrator', 'orca_session_id:$ORCA_AGENT_SESSION_ID', ...]
    def steering(text):
        return [w for w in ("--orchestrator", "orca_session_id:$ORCA_AGENT_SESSION_ID", "orca orchestration send --to dispatch:<D>", "taste or direction") if w not in text]
    check("step 5 starts `fwx wave run` with --orchestrator and says how a forwarded question is answered", not steering(s5) and any("--orchestrator" in f for f in run_flags(s5)), "missing %s" % steering(s5))
    check("control: a step 5 without the flag is caught", bool(steering("5. **Execute a part.** Run `fwx wave run --part-dir <part> --plane session --branch <branch>`.")))
    fields = set(wave_review._result("done", "r1")) | set(wave_report._result("merge"))
    cited_fields = result_fields(s5)
    check("step 5 reads the leftovers from fields the run's own files have", len(cited_fields) >= 3 and set(cited_fields) <= fields, "cites %s, the files have %s" % (cited_fields, sorted(fields)))
    check("control: a `result.` field the files do not have is caught", result_fields("read `result.unverfied`") == ["unverfied"] and "unverfied" not in fields)
    # A subphase starts in `executing` (stages.start_of), so `executing -> executing` is refused: step 5 writes no first `executing` row, only a correction's.
    toy = os.path.join(os.sep, "p", ".fwx", "milestones", "v1", "phases", "01-a", "01.1-b")
    check("the table starts a subphase in `executing` and refuses `executing` after itself", stages.start_of(toy) == "executing" and not stages.allowed("session", "executing", "executing"),
          "start %s" % stages.start_of(toy))
    check("step 5 writes no first `executing` row for a part", not first_executing_rows(s5), "writes %s" % first_executing_rows(s5))
    check("control: a step 5 that writes `executing` first is caught", bool(first_executing_rows("write stage `executing` first (`part <N> branch <branch>`)")) and not first_executing_rows("stage `executing` (`part <N> corrections`)"))

    # the close: the runs `fwx wave list` shows are swept, and the gate's draft pull request is marked ready, not created again.
    check("closing.md sweeps the runs `fwx wave list` shows with `fwx wave remove --run`", in_order(closing, "fwx wave list", "fwx wave remove --run"), "no 'fwx wave list' ... 'fwx wave remove --run' in order")
    check("closing.md marks the gate's draft pull request ready and writes its body", in_order(closing, "gh pr ready", "gh pr edit") and "gh pr create" in closing, "missing `gh pr ready`, `gh pr edit` or the fallback `gh pr create`")
    check("control: a closing that only creates the pull request is caught", not in_order("`gh pr create` with a body", "gh pr ready", "gh pr edit"))

    # 09.6 T61: every worker of `fwx wave run` is given a brief file (execute/brief.py writes the executor's, the fixer's, the resolver's and each review brief), and the
    # verifier's reply is the line `wave findings --verdicts` reads (review.VERDICT_LINE), not a structured output.
    agents = {}
    for name in ("executor", "reviewer", "security-reviewer", "review-verifier"):
        with open(os.path.join(ROOT, "agents", name + ".md"), encoding="utf-8") as f:
            agents[name] = f.read()
    claims_none = [n for n, t in agents.items() if re.search(r"no brief file|their prompt is the brief", t)]
    check("no agent says it has no brief file", not claims_none, "still says it in %s" % claims_none)
    check("control: an agent text that says 'there is no brief file' is caught", bool(re.search(r"no brief file", "Your prompt is your brief, there is no brief file")))
    # The owner talks only to the orchestrator: a worker's question goes to it, never to him. Seen red on the texts before:
    #   FAIL: workers never address the owner: step 5 and executor.md say so -> missing ['SKILL.md step 5', 'executor.md']
    said = {"SKILL.md step 5": "Workers never address the owner", "executor.md": "goes to the orchestrator (the coordinator), never to the owner"}
    texts_of = {"SKILL.md step 5": s5, "executor.md": agents["executor"]}
    missing = [k for k, v in said.items() if v not in texts_of[k]]
    check("workers never address the owner: step 5 and executor.md say so", not missing, "missing %s" % missing)
    check("control: a text without the sentence is caught", "Workers never address the owner" not in "5. **Execute a part.** The worker waits for the answer.")
    unread = [n for n in ("reviewer", "security-reviewer", "review-verifier") if "names a brief file" not in agents[n]]
    check("the reviewers and the verifier read the brief file their prompt names", not unread, "no 'names a brief file' in %s" % unread)
    reply = re.search(r"`(verdicts <report path>)`", agents["review-verifier"])
    check("the verifier replies with the line `wave findings --verdicts` reads", bool(reply) and bool(wave_review.VERDICT_LINE.match(reply.group(1).replace("<report path>", "/x/report.json"))),
          "no `verdicts <report path>` in agents/review-verifier.md, or review.VERDICT_LINE does not read it")
    check("control: a verifier that answers through a structured output has no such line", re.search(r"`(verdicts <report path>)`", "you answer through the structured output, `{verdicts: [...]}`") is None)

    check("step 8 reads `review: blocking` and the plan accepts that value", "`review: blocking`" in s8 and "blocking" in plan.REVIEWS,
          "step 8 names it: %s; plan.REVIEWS: %s" % ("`review: blocking`" in s8, plan.REVIEWS))
    check("steps 5 and 8 read `ui: true` and plan.py has a task key `ui`", "`ui: true`" in skill and '"ui"' in open(os.path.join(ROOT, "lib", "fwx", "plan.py"), encoding="utf-8").read(),
          "the text or the task keys lack it")
    check("the stage table allows phase-review -> ui-walk and phase-review -> planning (step 8 sends the session there)",
          stages.allowed("session", "phase-review", "ui-walk") and stages.allowed("session", "phase-review", "planning"), "refused")
    from fwx import plan_step  # noqa: E402
    check("step 8 gives the decision the source the briefs look for",
          "`source` `review of part <N>`" in s8 and bool(plan_step._REVIEWED.match("review of part 1")), "the skill and plan_step._REVIEWED disagree")

    # What a rejected fix records: `fwx decision new --support` takes a value of state.SUPPORT.
    named_supports = supports(review)
    check("ui-review.md names the support of `not_defect` and `redo`, each a value `fwx decision new` accepts",
          set(named_supports) == {"not_defect", "redo"} and all(v in state.SUPPORT for v in named_supports.values()), "ui-review.md %s, SUPPORT %s" % (named_supports, state.SUPPORT))
    check("control: a support the code does not know is caught", "approvd" not in state.SUPPORT and supports("`not_defect` with support `approvd`") == {"not_defect": "approvd"})
    check("ui-review.md asks before the revert", asks_before_revert(review), "no 'revert it?' before the first '--revert'")

    # A walk that did not finish is not "no findings": the session texts name the fields the workflow returns (`status`, `reason`, `details.unverified`,
    # `details.gaps`: copied from the object `workflows/ui-walk.js` returns, which tests/test_ui_walk_workflow.py pins key by key), so a renamed field
    # breaks this check. Top-level fields and `details` fields are kept apart (review of PR 125).
    with open(os.path.join(ROOT, "workflows", "ui-walk.js"), encoding="utf-8") as f:
        js = f.read()
    returned = returned_fields(js)
    top, det = returned
    check("the workflow returns the top-level fields the session texts cite", {"status", "reason", "phase_dir", "details"} <= top, "top-level %s" % sorted(top))
    check("the workflow returns the details fields the session texts cite", {"gaps", "unverified", "fix_file", "lost_slots"} <= det, "details %s" % sorted(det))
    for name, text in (("SKILL.md step 6", step(skill, 6)), ("references/ui-review.md", review)):
        check("%s cites only fields the workflow returns" % name, not cited_missing(text, returned), "not returned: %s" % cited_missing(text, returned))
    # a walk with no `fix_file` has no `fix.json`, so `fwx review new` would stop: ui-review.md says to skip the command then (review of PR 125).
    check("references/ui-review.md says what to do when `details.fix_file` is null", "`details.fix_file` null" in review and "do not run the command" in review, "missing")
    check("control: `details.reason` is flagged, `reason` is a top-level field only", cited_missing("read `details.reason`", returned) == ["reason"], "got %s" % cited_missing("read `details.reason`", returned))
    check("control: a details field is read as a details field", cited_missing("read `details.gaps` and `details.fix_file`", returned) == [])
    check("control: a cited field the workflow does not return is caught", cited_missing("read `details.unverfied`", returned) == ["unverfied"])
    # the runner has its own model role (haiku in the seed): step 6 reads it from `fwx model runner small`, not from the executor's.
    # Seen red on d348f8d: FAIL: SKILL.md step 6 reads models.runner from `fwx model runner small` -> missing
    s6 = step(texts["SKILL.md"], 6)
    check("SKILL.md step 6 reads models.runner from `fwx model runner small`", "`models.runner` from `fwx model runner small`" in s6 and "models.runner` from `fwx model executor" not in s6, "missing")

    # Rule 4: the documents are committed in the main checkout, only the documents: `.md` and `.tsv` files and the `demo/` pages, so the walk's
    # `demo-state.json` (demo session cookies), logs and screenshots stay untracked. The command line is run here as written, in a toy repo. A
    # `:(glob)` pathspec per pattern was tried first: `git add` fails outright when one pattern matches nothing, so the list comes from `find`.
    rule4 = next((ln for ln in skill.splitlines() if ln.startswith("4. **Commits of `.fwx/`**")), "")
    lines = re.findall(r"`(cd <main_checkout> && find [^`]*)`", rule4)
    check("rule 4 has one commit line built on `find`", len(lines) == 1, "found %d" % len(lines))
    if len(lines) == 1:
        rc, tracked, untracked, _, _ = commit_effect(lines[0])
        phase = ".fwx/milestones/v1/phases/01-a"
        check("rule 4's commit line adds the documents and the demo pages", rc == 0 and all(f in tracked for f in (
            ".fwx/project.md", ".fwx/milestones/v1/milestone.md", phase + "/context.md", phase + "/audit.tsv", phase + "/research/r.md", phase + "/demo/page.html")),
              "rc %s, tracked %s" % (rc, tracked))
        check("rule 4's commit line leaves demo-state.json, a log and a screenshot untracked", all(any(u.endswith(n) for u in untracked) for n in (
            "demo-state.json", "up.log", "ui-walk/1-1/shot.png", "demo/shot.png")) and not [f for f in tracked if f.endswith(("demo-state.json", ".log", ".png"))],
              "untracked %s, tracked %s" % (untracked, tracked))
        # Review of PR 130: a `commit -- .fwx` records the working-tree contents of every tracked file under it, so a `demo-state.json` tracked by an
        # older session and changed since went into the commit although `find` left it out of `git add`.
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
    check("control: `commit -- .fwx` after the find-built add commits a previously tracked walk file", any(f.endswith("demo-state.json") for f in commit_effect(
        "cd <main_checkout> && find .fwx -type f ! -name '.*' \\( -name '*.md' -o -name '*.tsv' -o -path '*/demo/*.html' \\) -print0 | git add --pathspec-from-file=- --pathspec-file-nul && git commit -m \"<message>\" -- .fwx",
        stale=True)[3]), "the control line did not commit it")

    # DTC-34, the owner's rule: the worktree of a phase is removed by the next session, once its PR is merged and it is clean, never at the close.
    cleanup = next((ln for ln in closing.splitlines() if re.match(r"\d+\. \*\*Cleanup\.\*\*", ln)), "")
    check("closing.md the cleanup step found", "fwx walk stop --orphans" in cleanup, "not found")
    check("closing.md the cleanup step does not remove the phase worktree", "git worktree remove" not in cleanup, "`git worktree remove` is in it")
    s0 = step(skill, 0)
    need = ["--state merged", "status --porcelain", ".claude/worktrees/", "no force", "git branch -d"]
    check("SKILL.md step 0 clears merged worktrees: merged PR, clean, no force", all(w in s0 for w in need), "missing: %s" % [w for w in need if w not in s0])
    check("SKILL.md step 0 never uses `git branch -D`", "branch -D" not in s0, "`git branch -D` is in it")
    check("SKILL.md step 0 clears worktrees before the retake and the resume", in_order(s0, "--state merged", "retake", "fwx session --json"), "order is not sweep, retake, resume")
    check("control: the old closing step 4 is caught", "git worktree remove" in "4. **Cleanup.** Remove it with `git worktree remove <path>` and no force.")
    check("control: a step 0 without the rule is caught", not all(w in "0. **Where you are.** Run `fwx session --json`." for w in need))
    check("control: a step 0 with `git branch -D` is caught", "branch -D" in "then `git branch -D <branch>`")
    check("control: step 0 is cut by step()", step("## Steps\n0. **A.** x\n1. **B.** y\n", 0).startswith("0. **A.**") and "y" not in step("## Steps\n0. **A.** x\n1. **B.** y\n", 0))

    # D11: before `closed` the orchestrator promotes the phase's decisions to the durable record (`fwx decision new --adr`), and fwx's work ends at the
    # pull request: nothing that merges, babysits or watches follows `gh pr create`.
    promote = "fwx decision new --adr"
    check("closing.md promotes passing decisions with `fwx decision new --adr` before step 3's `fwx stage <phase folder> closed`",
          in_order(closing, promote, "fwx stage <phase folder> closed"), "'%s' is not before 'fwx stage <phase folder> closed'" % promote)
    after_pr = closing[closing.find("gh pr create"):] if "gh pr create" in closing else ""
    after_pr_steps = [ln.split("**")[1] for ln in after_pr.splitlines() if re.match(r"\d+\. \*\*", ln)]
    after_pr_bans = ("babysit", "watch", "gh pr merge", "gh pr checks", "wait for CI", "poll")
    check("closing.md has a step after `gh pr create`", bool(after_pr_steps), "no numbered step after it")
    check("closing.md adds no merge, babysit or watch to the steps after the pull request",
          not [w for w in after_pr_bans if w in after_pr.replace("fwx walk", "")] and "merge it" not in after_pr, "found: %s" % [w for w in after_pr_bans if w in after_pr])
    check("control: a closing text that promotes after `closed` fails", not in_order("fwx stage <phase folder> closed then fwx decision new --adr", promote, "fwx stage <phase folder> closed"))
    check("control: a step that babysits the pull request is caught", "babysit" in "6. **Babysit.** After `gh pr create`, babysit the PR until CI is green.".split("gh pr create")[1])

    # The owner leaving changes nothing: the session passes no `--unattended` (the factory's flag).
    leave_re = re.compile(r"\b(add|pass)\w*\s+`--unattended`")
    bad = [(n, ln.strip()[:90]) for n, ln in enumerate(skill.splitlines(), 1) if leave_re.search(ln)]
    check("no line of SKILL.md tells the session to pass --unattended", not bad, ("line %d: %r" % bad[0]) if bad else "")
    check("control: 'add `--unattended` when the owner says he is leaving' is caught", leave_re.search("(add `--unattended` when the owner says he is leaving)") is not None)
    check("control: 'you pass no `--unattended`' is not caught", leave_re.search("you pass no `--unattended` (only the factory does)") is None)

    # D9, D17: the session records decisions itself with `fwx decision new` (no `decisions` agent) and every question to the owner carries a
    # recommendation. The texts are the session skill, its references and the three critique skills.
    skill_files = {"SKILL.md": os.path.join(SESSION, "SKILL.md")}
    for ref in ("ui-review.md", "factory-return.md", "closing.md", "part-report.md"):
        skill_files["references/" + ref] = os.path.join(SESSION, "references", ref)
    for name in ("plan", "pre-mortem", "post-mortem"):
        skill_files["skills/%s/SKILL.md" % name] = os.path.join(ROOT, "skills", name, "SKILL.md")
    scanned = {}
    for name, path in skill_files.items():
        with open(path, encoding="utf-8") as f:
            scanned[name] = f.read()
    check("the texts scanned for the decisions agent and the recommendation rule are looked at", len(scanned) == 8 and all(scanned.values()), "scanned %d" % len(scanned))
    decisions_hits = ["%s:%d" % (n, i) for n, t in scanned.items() for i, ln in enumerate(t.splitlines(), 1) if re.search(r"`(fwx:)?decisions`|decisions agent", ln)]
    if os.path.exists(os.path.join(ROOT, "agents", "decisions.md")):
        decisions_hits.append("agents/decisions.md exists")
    check("no text launches or names the `decisions` agent, and its file is gone", not decisions_hits, ", ".join(decisions_hits))
    recorders = [n for n in ("SKILL.md", "references/ui-review.md", "references/factory-return.md") if "fwx decision new" not in scanned[n]]
    check("the session, the UI review and the factory return record decisions with `fwx decision new`", not recorders, "missing in %s" % recorders)
    silent = ["%s:%d" % (n, i) for n, t in scanned.items() for i, ln in enumerate(t.splitlines(), 1)
              if re.search(r"never recommend|no recommendation|without a recommendation|unasked", ln, re.I)]
    check("no text tells the session to ask without a recommendation", not silent, ", ".join(silent))
    asking = [n for n, t in (("SKILL.md rule 6", rule6_of(skill)), ("SKILL.md step 4", step(skill, 4)), ("SKILL.md step 8", s8),
                             ("references/ui-review.md", review), ("references/factory-return.md", scanned["references/factory-return.md"])) if "Recommended:" not in t]
    check("every question to the owner carries a `Recommended:` line", not asking, "no `Recommended:` in %s" % asking)
    # CodeRabbit PR 279: a worker failure after execution starts is kept in the run state (`st["result"]["why"]`, not committed); the only reason on the
    # branch is the `--why` of the stage row, and only when the factory gave one. Step 2 must say what to do when it has none. Seen red on the text at ced1761:
    #   FAIL: factory-return.md step 2 says what to do when the stage row holds no reason -> step 2: 'Read why it came back. ... (the last one says why it stopped)'
    fr_step2 = next((ln for ln in scanned["references/factory-return.md"].splitlines() if re.match(r"2\. \*\*Read why", ln)), "")
    names_no_reason = lambda s: "no reason" in s
    check("factory-return.md step 2 says what to do when the stage row holds no reason", names_no_reason(fr_step2), "step 2: %r" % fr_step2[:110])
    check("control: a step 2 that trusts the last row is caught", not names_no_reason("2. **Read why it came back.** The last `stage` rows (the last one says why it stopped)"))
    # 01.2 T23 (D2, D7): a phase holds a handful of rows (rule 6), and closing.md's step 3 carries the three tests of an ADR word for word from
    # domain-modeling, with its copied-from header. Seen red at c538909 (the texts before this task):
    #   FAIL: SKILL.md rule 6 says a phase holds a handful of rows -> rule 6 has no 'handful of rows'
    #   FAIL: closing.md step 3 quotes the three ADR tests word for word, under a copied-from header -> missing ['**Hard to reverse**: the ...', ..., 'the copied-from header']
    check("SKILL.md rule 6 says a phase holds a handful of rows", "handful of rows" in rule6_of(skill), "rule 6 has no 'handful of rows'")
    check("control: a rule 6 without the line is caught", "handful of rows" not in rule6_of("6. **Questions.** Ask the owner only what needs his taste.\n## Steps"))
    ADR_TESTS = ("**Hard to reverse**: the cost of changing your mind later is meaningful",
                 "**Surprising without context**: a future reader will wonder \"why did they do it this way?\"",
                 "**The result of a real trade-off**: there were genuine alternatives and you picked one for specific reasons")

    def adr_problems(text):
        step3 = next((ln for ln in text.splitlines() if re.match(r"3\. \*\*Record\.\*\*", ln)), "")
        head = "\n".join(text.splitlines()[:6])
        return ["%s ..." % t[:24] for t in ADR_TESTS if t not in step3] + ([] if re.search(
            r"copied-from: mattpocock/skills skills/engineering/domain-modeling/SKILL\.md @49dd158", head) else ["the copied-from header"])
    check("closing.md step 3 quotes the three ADR tests word for word, under a copied-from header", not adr_problems(closing), "missing %s" % adr_problems(closing))
    good_adr = "<!-- copied-from: mattpocock/skills skills/engineering/domain-modeling/SKILL.md @49dd158 -->\n3. **Record.** " + "; ".join(ADR_TESTS) + "\n"
    check("control: the good closing toy passes", adr_problems(good_adr) == [], "got %s" % adr_problems(good_adr))
    check("control: a paraphrased test is caught", len(adr_problems(good_adr.replace("meaningful", "high"))) == 1)
    check("control: a closing with no copied-from header is caught", adr_problems(good_adr.replace("copied-from:", "referent:")) == ["the copied-from header"])
    check("control: a decisions-agent line is caught", re.search(r"`(fwx:)?decisions`|decisions agent", "record it by the `decisions` agent") is not None)
    check("control: `decisions.tsv` is not a decisions-agent line", re.search(r"`(fwx:)?decisions`|decisions agent", "read `decisions.tsv`") is None)
    check("control: 'no recommendation unasked' is caught", re.search(r"no recommendation|unasked", "it carries no recommendation unasked", re.I) is not None)

    # Orca worker launch in pre-mortem and post-mortem skills: --spec-file (never --spec with backticks), the role's
    # agent file named in the spec because an Orca worker has no subagent_type, and end the turn instead of polling.
    # Seen red on origin/master:
    #   FAIL: skills/pre-mortem/SKILL.md Orca worker launch uses --spec-file, names agents/pre-mortem.md, and ends the turn -> worker-start does not pass --spec-file (or still passes --spec): ...; does not point the worker at ${CLAUDE_PLUGIN_ROOT}/agents/pre-mortem.md; does not tell the session to end its turn for worker_done and not poll
    #   FAIL: skills/post-mortem/SKILL.md Orca worker launch uses --spec-file, names agents/post-mortem.md, and ends the turn -> ...
    def mortem_worker_problems(text, agent_rel):
        out = []
        m = re.search(r"`orca orchestration worker-start[^`]*`", text)
        cmd = m.group(0) if m else ""
        if "--spec-file" not in cmd or re.search(r"--spec(?!-file)\b", cmd):
            out.append("worker-start does not pass --spec-file (or still passes --spec): %r" % cmd)
        agent_ref = "${CLAUDE_PLUGIN_ROOT}/" + agent_rel
        if agent_ref not in text:
            out.append("does not point the worker at %s" % agent_ref)
        if "end your turn" not in text or "do not poll" not in text:
            out.append("does not tell the session to end its turn for worker_done and not poll")
        return out

    for name in ("pre-mortem", "post-mortem"):
        agent_rel = "agents/%s.md" % name
        check("%s agent file exists on disk" % agent_rel, os.path.isfile(os.path.join(ROOT, agent_rel)))
        probs = mortem_worker_problems(scanned["skills/%s/SKILL.md" % name], agent_rel)
        check("skills/%s/SKILL.md Orca worker launch uses --spec-file, names %s, and ends the turn" % (name, agent_rel),
              not probs, "; ".join(probs))
    good_worker = ("read ${CLAUDE_PLUGIN_ROOT}/agents/post-mortem.md; "
                   "`orca orchestration worker-start --agent antigravity --spec-file <file> --json`; "
                   "end your turn and let worker_done wake you (do not poll).")
    check("control: good mortem worker text passes", mortem_worker_problems(good_worker, "agents/post-mortem.md") == [])
    check("control: worker-start with --spec is caught",
          any("--spec-file" in p for p in mortem_worker_problems(good_worker.replace("--spec-file <file>", '--spec "Run `fwx`"'), "agents/post-mortem.md")))
    check("control: missing agent file pointer is caught",
          any("agents/post-mortem.md" in p for p in mortem_worker_problems(good_worker.replace("${CLAUDE_PLUGIN_ROOT}/agents/post-mortem.md", "brief"), "agents/post-mortem.md")))
    check("control: missing end-turn / do-not-poll rule is caught",
          any("end its turn" in p for p in mortem_worker_problems(good_worker.replace("end your turn", "wait"), "agents/post-mortem.md")))

    # controls of the checks above.
    check("control: a cited reference that is not there is caught", set(re.findall(r"references/([a-z-]+\.md)", "see references/gone.md and references/here.md")) - {"here.md"} == {"gone.md"})
    check("control: step() cuts one numbered step", step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2).startswith("2. **B.**") and "z" not in step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2))
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
