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

s.eq("agent_with_model.md: reported at line 4", lines(lm.lint_md(fixture("agent_with_model.md"))), [4])

# toy sources: one behaviour each
def one(src):
    calls, probs = lm.lint_js(src)
    return calls, [p[2] for p in probs]


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
helpers.write(tree, "workflows/ok.js", "agent('p', { model: 'sonnet' })\n")
helpers.write(tree, "workflows/skip.txt", "agent('p')\n")
helpers.write(tree, "agents/reviewer.md", "---\nname: reviewer\n---\nbody\n")
helpers.write(tree, "tests/fixtures/bad.js", "agent('p')\n")
rep = lm.lint_root(tree)
s.eq("lint_root: workflows/*.js and agents/*.md only", (rep.js, rep.md, rep.calls, rep.problems), (1, 1, 1, []))
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
