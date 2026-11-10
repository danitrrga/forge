"""lib/fwx/lint_models.py: every agent() call in a workflow names its model; no agents/*.md declares one.

Reads the fixtures in tests/fixtures/lint/ and small toy trees. The red seen first, then the controls.

Red before the module existed (python3 tests/test_model_lint.py):
  ImportError: cannot import name 'lint_models' from 'fwx'

Controls, each run on a copy of lib/fwx/lint_models.py changed in one place (red seen, copy discarded; 46 checks each):
  - a rule that accepts any second argument (the model is not looked for):
      FAIL: no_model.js: reported at line 3: got [], want [3]
      FAIL: var_opts.js: opts passed as a variable is refused: got [], want [2]
      FAIL: model only in a string value: got (1, []), want (1, ['model'])
  - a reader that does not skip `//` comments (it finds the `agent(` written in them):
      FAIL: good.js: agent() calls looked at (the nested one included, the comment and the string not): got 6, want 4
      FAIL: no_model.js: reported at line 3: got [1, 3], want [3]
      FAIL: cli: the good fixture exits 0: got 1, want 0
  - a rule that stops seeing the shorthand `{ model }`:
      FAIL: shorthand: {model} counts as naming the model: got (1, ['model']), want (1, [])
      FAIL: cli: the good fixture exits 0: got 1, want 0
  - a frontmatter reader that never reports `model:`:
      FAIL: agent_with_model.md: reported at line 4: got [], want [4]
      FAIL: md quoted key: got [], want [3]
  - a CLI that does not fault an explicit path with nothing to look at (zero files is not a pass):
      FAIL: cli: explicit path with no workflow or agent file exits 1: got 0, want 1
      FAIL: cli: explicit path that does not exist exits 1: got 0, want 1
  - a call finder that finds no call (zero calls is not a pass):
      FAIL: good.js: agent() calls looked at (the nested one included, the comment and the string not): got 0, want 4
      FAIL: no_model.js: calls looked at: got 0, want 1

2.5 U6 (agentType and fork). Red before the change, on the old lint: `python3 lib/fwx/lint_models.py
tests/fixtures/lint/no_agent_type.js` and `.../fork.md` both printed `0 fault(s)` and exited 0; the suite stopped at
  AttributeError: module 'fwx.lint_models' has no attribute 'lint_text'
Controls (80 checks, each on a copy changed in one place, red seen, copy discarded):
  - agentType never reported:
      FAIL: no_agent_type.js: the call without agentType is reported at line 3: got [], want [3]
      FAIL: agentType missing: got (1, []), want (1, ['agentType'])
  - fork never matched (script keys and text pattern):
      FAIL: fork.md: the fork launch is reported at line 3 only: got [], want [3]
      FAIL: text: quoted value: got [], want [2]
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import lint_models as lm  # noqa: E402

FIX = os.path.join(helpers.ROOT, "tests", "fixtures", "lint")
s = helpers.Suite()


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def lines(problems, kind="model"):
    return [p[1] for p in problems if p[2] == kind]


# fixtures: good passes, each bad one fails at its line
calls, probs = lm.lint_js(fixture("good.js"))
s.eq("good.js: no problem", probs, [])
s.eq("good.js: agent() calls looked at (the nested one included, the comment and the string not)", calls, 4)

calls, probs = lm.lint_js(fixture("no_model.js"))
s.eq("no_model.js: calls looked at", calls, 1)
s.eq("no_model.js: reported at line 3", lines(probs), [3])

calls, probs = lm.lint_js(fixture("var_opts.js"))
s.eq("var_opts.js: calls looked at", calls, 1)
s.eq("var_opts.js: opts passed as a variable is refused", lines(probs), [2])

calls, probs = lm.lint_js(fixture("no_agent_type.js"))
s.eq("no_agent_type.js: calls looked at", calls, 2)
s.eq("no_agent_type.js: no model fault, the model is named", lines(probs), [])
s.eq("no_agent_type.js: the call without agentType is reported at line 3", lines(probs, "agentType"), [3])
s.eq("no_agent_type.js: says it would be workflow-subagent", [p[3] for p in probs],
     ["agent() without agentType: it would be workflow-subagent"])
s.eq("fork.md: the fork launch is reported at line 3 only", lines(lm.lint_text(fixture("fork.md")), "fork"), [3])

s.eq("agent_with_model.md: reported at line 4", lines(lm.lint_md(fixture("agent_with_model.md"))), [4])

# toy sources: one behaviour each
def one(src):
    calls, probs = lm.lint_js(src)
    return calls, [p[2] for p in probs if p[2] != "agentType"]


def agt(src):
    calls, probs = lm.lint_js(src)
    return calls, [p[2] for p in probs if p[2] == "agentType"]


s.eq("no second argument", one("agent('p')"), (1, ["model"]))
s.eq("shorthand: {model} counts as naming the model", one("agent('p', { label: 'a', model })"), (1, []))
s.eq("quoted key", one("agent('p', { 'model': 'x' })"), (1, []))
s.eq("model inside a nested object is not the call's model", one("agent('p', { cfg: { model: 'x' } })"), (1, ["model"]))
s.eq("model only in a string value", one("agent('p', { label: 'model: x' })"), (1, ["model"]))
s.eq("spread alone hides the model", one("agent('p', { ...opts })"), (1, ["model"]))
s.eq("ternary of two literals is not a literal", one("agent('p', c ? { model: 'a' } : { model: 'b' })"), (1, ["model"]))
s.eq("a literal followed by more is not the literal", one("agent('p', { model: 'a' }.x)"), (1, ["model"]))
s.eq("model: undefined is not explicit", one("agent('p', { model: undefined })"), (1, ["model"]))
s.eq("model with no value", one("agent('p', { model: })"), (1, ["model"]))
s.eq("trailing comma after the options", one("agent('p', { model: 'a' },)"), (1, []))
s.eq("a call across lines with a template argument holding braces and commas",
     one("agent(`a ${f({ x: 1 }, [2, 3])}, b`,\n  { label: `l:${k}`,\n    model: 'opus' })"), (1, []))
s.eq("skipped text: a call in a comment, a string and a regex is not counted",
     one("// agent('c')\n/* agent('d', { model: 'x' }) */\nconst a = 'agent(1)'\nconst b = /agent\\(/g\nagent('p', { model: 'm' })\nagent('q')"),
     (2, ["model"]))
s.eq("a regex with a slash in a class and a division are told apart",
     one("const r = /[/]agent(/.test(x)\nconst d = a / b / c\nagent('p', { model: 'm' })"), (1, []))
s.eq("a function declaration and a method named agent are not calls",
     one("function agent(a, b) { return 1 }\nconst o = { agent(a) { return 2 } }"), (0, []))
s.eq("a member call is looked at", one("ctx.agent('p', { label: 'a' })"), (1, ["model"]))
s.eq("an identifier that only contains the word is not a call", one("subagent('p')\nagents('p')\nagent_x('p')"), (0, []))

# agentType: the same reading as model
s.eq("agentType named", agt("agent('p', { model: 'm', agentType: 'fwx:reviewer' })"), (1, []))
s.eq("agentType missing", agt("agent('p', { model: 'm' })"), (1, ["agentType"]))
s.eq("agentType shorthand", agt("agent('p', { model: 'm', agentType })"), (1, []))
s.eq("agentType quoted key", agt("agent('p', { model: 'm', 'agentType': 'x' })"), (1, []))
s.eq("agentType: undefined is not named", agt("agent('p', { model: 'm', agentType: undefined })"), (1, ["agentType"]))
s.eq("agentType in a nested object is not the call's", agt("agent('p', { model: 'm', cfg: { agentType: 'x' } })"), (1, ["agentType"]))
s.eq("agentType only in a string value", agt("agent('p', { model: 'm', label: 'agentType: x' })"), (1, ["agentType"]))
s.eq("a model fault does not hide a missing agentType", agt("agent('p', { label: 'a' })"), (1, ["agentType"]))
s.eq("opts as a variable: the model fault says it, agentType is not reported twice", agt("agent('p', opts)"), (1, []))
s.eq("a declaration is not a call, so no agentType fault", agt("function agent(a, b) { return 1 }"), (0, []))

# fork: a launch of subagent_type fork, in scripts and in text
fk = lambda src: [p[1] for p in lm.lint_js(src)[1] if p[2] == "fork"]
s.eq("js: agentType 'fork'", fk("agent('p', { model: 'm', agentType: 'fork' })"), [1])
s.eq("js: quoted key", fk("agent('p', {\n 'agentType': 'fork', model: 'm' })"), [2])
s.eq("js: subagent_type", fk("const o = { subagent_type: \"fork\" }"), [1])
s.eq("js: a longer name is not fork", fk("agent('p', { model: 'm', agentType: 'fork-reviewer' })"), [])
s.eq("js: the word in a comment or a label is not a launch", fk("// agentType: 'fork'\nagent('p', { label: 'fork', model: 'm', agentType: 'x' })"), [])
tx = lambda src: lines(lm.lint_text(src), "fork")
s.eq("text: quoted value", tx("a\nsubagent_type: \"fork\"\n"), [2])
s.eq("text: JSON form", tx("{\"subagent_type\": \"fork\", \"prompt\": 1}"), [1])
s.eq("text: equals form and agentType", tx("subagent_type='fork'\nagentType = fork"), [1, 2])
s.eq("text: unquoted", tx("use subagent_type: fork here"), [1])
s.eq("text: other types and the bare word are not a launch", tx("subagent_type: forked\nsubagent_type: \"general-purpose\"\nfork it"), [])

# a script that cannot be read is an error, not a pass
for label, src in (("unterminated string", "const a = 'x\nagent('p')"), ("unterminated template", "const a = `x ${y"),
                   ("unterminated comment", "/* x"), ("unbalanced bracket", "agent('p', { model: 'a' )"),
                   ("stray closer", "agent('p', { model: 'a' }))")):
    calls, probs = lm.lint_js(src)
    s.ok("%s: a parse error" % label, any(p[2] == "parse" for p in probs), repr(probs))

# frontmatter
md = lambda t: lines(lm.lint_md(t))
s.eq("md without model", md("---\nname: a\n---\nmodel: x in the body\n"), [])
s.eq("md quoted key", md("---\nname: a\n\"model\": 'x'\n---\n"), [3])
s.eq("md nested model is not the agent's", md("---\nname: a\nmetadata:\n  model: x\n---\n"), [])
s.eq("md with no frontmatter", md("model: sonnet\n"), [])

# the whole thing through a directory and through the command line
def run(*args):
    return subprocess.run([sys.executable, os.path.join(helpers.ROOT, "lib", "fwx", "lint_models.py")] + list(args),
                          env=helpers.clean_env(), capture_output=True, text=True)


tree = helpers.mkdtemp("fwx-lint-")
helpers.write(tree, "workflows/ok.js", "agent('p', { model: 'sonnet', agentType: 'fwx:reviewer' })\n")
helpers.write(tree, "workflows/skip.txt", "agent('p')\n")
helpers.write(tree, "agents/reviewer.md", "---\nname: reviewer\n---\nbody\n")
helpers.write(tree, "tests/fixtures/bad.js", "agent('p')\n")
rep = lm.lint_root(tree)
s.eq("lint_root: workflows/*.js and agents/*.md only", (rep.js, rep.md, rep.calls, rep.problems), (1, 1, 1, []))
s.eq("lint_root: no other text file in this tree", rep.text, 0)
r = run("--root", tree)
s.eq("cli: a clean tree exits 0", r.returncode, 0)
s.ok("cli: says how much it looked at", "1 workflow file(s), 1 agent file(s), 1 agent() call(s)" in r.stdout, r.stdout)

helpers.write(tree, "workflows/bad.js", "const a = 1\nawait agent('p', { label: 'x' })\n")
r = run("--root", tree)
s.eq("cli: a missing model exits 1", r.returncode, 1)
s.ok("cli: names file:line", os.path.join(tree, "workflows", "bad.js") + ":2:" in r.stdout, r.stdout)

empty = helpers.mkdtemp("fwx-lint-empty-")
r = run("--root", empty)
s.eq("cli: a repo with no workflow and no agent is not a failure (phase 2)", r.returncode, 0)
s.ok("cli: it says it looked at 0", "0 workflow file(s), 0 agent file(s), 0 agent() call(s)" in r.stdout, r.stdout)
r = run(os.path.join(empty, "workflows"))
s.eq("cli: explicit path with no workflow or agent file exits 1", r.returncode, 1)
r = run(os.path.join(empty, "nothing.js"))
s.eq("cli: explicit path that does not exist exits 1", r.returncode, 1)
r = run(os.path.join(FIX, "no_model.js"), os.path.join(FIX, "var_opts.js"), os.path.join(FIX, "agent_with_model.md"))
s.eq("cli: the three bad fixtures exit 1", r.returncode, 1)
s.ok("cli: one line per fault", all(x in r.stdout for x in ("no_model.js:3:", "var_opts.js:2:", "agent_with_model.md:4:")), r.stdout)
r = run(os.path.join(FIX, "good.js"))
s.eq("cli: the good fixture exits 0", r.returncode, 0)
r = run(os.path.join(FIX, "no_agent_type.js"))
s.eq("cli: the fixture without agentType exits 1", r.returncode, 1)
s.ok("cli: names file:line and the message", os.path.join(FIX, "no_agent_type.js") + ":3: agent() without agentType: it would be workflow-subagent" in r.stdout, r.stdout)
r = run(os.path.join(FIX, "fork.md"))
s.eq("cli: the fork fixture exits 1", r.returncode, 1)
s.ok("cli: names file:line and says why", os.path.join(FIX, "fork.md") + ":3:" in r.stdout and "fork" in r.stdout, r.stdout)

# fork is looked for in workflows/, skills/, agents/ and playbooks/; skills and playbooks are walked
ftree = helpers.mkdtemp("fwx-lint-fork-")
helpers.write(ftree, "playbooks/deep/p.md", "# p\n\nsubagent_type: fork\n")
helpers.write(ftree, "skills/s/SKILL.md", "subagent_type: \"fork\"\n")
helpers.write(ftree, "agents/a.md", "---\nname: a\n---\nsubagent_type: fork\n")
helpers.write(ftree, "workflows/w.md", "subagent_type: fork\n")
helpers.write(ftree, "workflows/w.js", "agent('p', { model: 'm', agentType: 'fork' })\n")
helpers.write(ftree, "templates/t.md", "subagent_type: fork\n")
rep = lm.lint_root(ftree)
s.eq("lint_root: a fork in each of the five places, none in templates/",
     sorted(os.path.relpath(p[0], ftree) for p in rep.problems if p[2] == "fork"),
     ["agents/a.md", "playbooks/deep/p.md", "skills/s/SKILL.md", "workflows/w.js", "workflows/w.md"])
s.eq("lint_root: counts the text files it read", (rep.js, rep.md, rep.text), (1, 1, 3))
r = run("--root", ftree)
s.eq("cli: forks exit 1", r.returncode, 1)
s.ok("cli: says how many text files", "3 other text file(s)" in r.stdout, r.stdout)

# the framework repo itself: in phase 2 it may hold no workflow, and says so
rep = lm.lint_root(helpers.ROOT)
s.eq("this repo: no problem", rep.problems, [])
print("this repo: %d workflow file(s), %d agent file(s), %d agent() call(s)" % (rep.js, rep.md, rep.calls))

# a real-world read: the host project's own workflows must parse (they may still lack a model)
forge = os.environ.get("FORGE_ROOT")
wf = os.path.join(forge, ".claude", "workflows") if forge else ""
if os.path.isdir(wf):
    names = sorted(n for n in os.listdir(wf) if n.endswith(".js"))
    rep = lm.lint_paths([os.path.join(wf, n) for n in names])
    s.ok("FORGE_ROOT workflows: some were read", rep.js > 0 and rep.calls > 0, "%d files, %d calls" % (rep.js, rep.calls))
    s.eq("FORGE_ROOT workflows: no parse error", [p for p in rep.problems if p[2] == "parse"], [])
    print("FORGE_ROOT workflows: %d file(s), %d agent() call(s), %d without a visible model" % (rep.js, rep.calls, len(rep.problems)))
else:
    print("FORGE_ROOT workflows: not armed (FORGE_ROOT unset or without .claude/workflows)")
s.done()
