#!/usr/bin/env python3
"""forge/mcp.py records what it wrote in ~/.claude.json and in a project's .codex/ (step 10, increment I3,
tasks T3+T4+T5; forge/owned.py), so a coming `forge uninstall` can take it out without reading a secret.

  C7  ~/.claude.json: one `key` claim per server forge writes for a project, at
      ["projects", <project key>, "mcpServers", <server>], the hash of the resolved definition (it holds the
      secret, only its SHA-256 is kept), owner the profile, part "mcp:<project key>": the file is shared by
      every project, so one project's run never erases another's claims.
  C10 <project>/.codex/config.toml (codex_harness on): kind `file`, at [], the hash of the text written,
      owner "codex", part "codex". With codex_harness off, forge takes its own tables out of the file and
      the claim goes with them.
  C12 the `.codex/` ignore line forge adds, as an item at ["line", <line>] of the file that holds it
      (.gitignore, or .git/info/exclude for a repo-owned project), part "codex": claimed only when forge
      added it and kept on later runs while it is there; a line that was already there is never claimed; a
      claim of the same part for another line (an `.agents/` line) is left as it is.

A toy HOME, toy projects (git repositories, so the ignore lines are real) and a toy registry whose server
resolves FAKE_TOKEN, run in-process; the record must never hold the token. lib.may_write() is stubbed to
allow, because this checkout may be a linked worktree, which never writes. A dry-run records nothing, and
a second --apply that changes nothing does not rewrite the record.

Seen failing on 78d36ba (mcp.py claims nothing): 24 of 47 checks red, the 23 others (controls, dry-runs, a pre-existing line) pass there. First lines:
  FAIL C7: the server is claimed for project A -- []
  FAIL C7: two projects' claims coexist in the record -- ...
  FAIL C10: config.toml is claimed as a file, owner codex, part codex -- []
  FAIL C12: the added .codex/ line is claimed on .gitignore -- []
  FAIL C12: the line stays claimed on a second apply -- []
Negative controls on the finished code, each mutation of forge/mcp.py put back from a copy, checks red: the
already-current path not recording (2); a dry-run recording (1); one shared part for every project (7); the
claim kind item (2); record_claims always rewriting (1); a line claimed whether or not forge added it (5); a
claim not kept on later runs (4); the claims of other lines of the part erased (2); the ignore line never
claimed (9); a repo-owned project's line looked for in .gitignore (3); config.toml never claimed (4), claimed
without its part (2), its claim left when codex_harness goes off (1), a relocated key's claims left behind (1)."""
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-mcp-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, sandbox.FORGE)
from forge import lib, mcp, owned  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
lib.SETTINGS = os.path.join(TOY, "forge.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {"codex": True, "gsd": False, "hindsight": False, "caveman": False},
               "codex_harness": True}, fh)
lib.settings.cache_clear()

APPLY, DRY = lib.Ctx(True, None, False), lib.Ctx(False, None, False)
FAKE_TOKEN = "fake-mcp-token-9c1d-NOT-REAL"
REGISTRY = {"srv": {"type": "stdio", "command": "srv", "args": [], "env": {"API_KEY": "${FAKE_TOKEN}"}},
            "srv2": {"type": "stdio", "command": "srv2", "args": [], "env": {}}}
SECRETS = {"FAKE_TOKEN": FAKE_TOKEN}
CJ = os.path.join(HOME, ".claude.json")
failures, n_checks, n_proj = [], [0], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:600])


def project(gitignore=None, repo=True):
    """A toy project directory, a git repository unless `repo` is false, with that .gitignore if any."""
    n_proj[0] += 1
    p = os.path.join(TOY, "proj%d" % n_proj[0])
    os.makedirs(p)
    if repo:
        sandbox.git(p, "init", "-q")
    if gitignore is not None:
        with open(os.path.join(p, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write(gitignore)
    return p


def prof(p, name, **keys):
    return dict({"project": name, "project_path": p}, **keys)


def run_cj(ctx, *pairs, relocations=()):
    """One ~/.claude.json run over (profile, servers) pairs, as sync.py drives it: open, relocate, project
    each, commit."""
    errors = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cj = mcp.ClaudeJson.open(ctx)
        if relocations:
            cj.relocate(ctx, {"toy.claude.json": pairs[0][0]}, list(relocations))
        for pr, sel in pairs:
            cj.project(pr, sel, REGISTRY, SECRETS, errors)
        line = cj.commit(ctx)
    return line, errors


def run_codex(ctx, pr, sel):
    errors = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        line = mcp.write_codex_project_mcp(ctx, pr, sel, REGISTRY, SECRETS, errors)
    return line, errors


def drop_registry():
    if os.path.exists(owned.path()):
        os.remove(owned.path())


def raw():
    return open(owned.path(), encoding="utf-8").read() if os.path.exists(owned.path()) else ""


def mtime():
    return os.stat(owned.path()).st_mtime_ns if os.path.exists(owned.path()) else None


def claims(file, part=None):
    return owned.previous(file, part)[0]


def cj_doc():
    with open(CJ, encoding="utf-8") as fh:
        return json.load(fh)


def at(c):
    return (c["kind"], tuple(c["at"]), c["owner"])


# ------------------------------------------------------------------------------------------- C7
drop_registry()
pa, pb = project(), project()
ka, kb = mcp.project_key(pa), mcp.project_key(pb)
line, errs = run_cj(APPLY, (prof(pa, "toy-a"), ["srv"]), (prof(pb, "toy-b"), ["srv", "srv2"]))
check("control: the run wrote ~/.claude.json with the resolved token", FAKE_TOKEN in open(CJ, encoding="utf-8").read()
      and not errs, (line, errs))
got_a, got_b = claims(CJ, "mcp:" + ka), claims(CJ, "mcp:" + kb)
check("C7: the server is claimed for project A",
      [at(c) for c in got_a] == [("key", ("projects", ka, "mcpServers", "srv"), "toy-a")], got_a)
check("C7: two projects' claims coexist in the record",
      [at(c) for c in got_b] == [("key", ("projects", kb, "mcpServers", "srv"), "toy-b"),
                                 ("key", ("projects", kb, "mcpServers", "srv2"), "toy-b")]
      and len(claims(CJ)) == 3, claims(CJ))
check("C7: the claim's sum is the hash of the definition as written (token resolved)",
      got_a and got_a[0]["sum"] == owned.digest(cj_doc()["projects"][ka]["mcpServers"]["srv"]), got_a)
check("C7: the record never holds the token", FAKE_TOKEN not in raw() and "9c1d" not in raw(), "token in owned.json")

before, stamp = raw(), mtime()
time.sleep(0.05)  # the file system's clock is coarse: a rewrite within a tick would keep the mtime
line, _ = run_cj(APPLY, (prof(pa, "toy-a"), ["srv"]), (prof(pb, "toy-b"), ["srv", "srv2"]))
check("control: a second run is already current", "already current" in line, line)
check("C7: a second apply that changes nothing leaves the record's bytes and mtime",
      raw() != "" and raw() == before and mtime() == stamp, "rewritten")

drop_registry()  # the record was lost; ~/.claude.json already holds everything (the "already current" path)
line, _ = run_cj(DRY, (prof(pa, "toy-a"), ["srv"]))
check("C7: a dry-run over a file that is already current records nothing", "already current" in line and not os.path.exists(owned.path()),
      (line, raw()))
line, _ = run_cj(APPLY, (prof(pa, "toy-a"), ["srv"]), (prof(pb, "toy-b"), ["srv", "srv2"]))
check("C7: an apply over a file that is already current records the claims again", "already current" in line and len(claims(CJ)) == 3,
      (line, claims(CJ)))

line, _ = run_cj(APPLY, (prof(pa, "toy-a"), ["srv"]))  # a scoped run: only A
check("C7: a run over project A alone leaves B's claims", len(claims(CJ, "mcp:" + kb)) == 2 and len(claims(CJ, "mcp:" + ka)) == 1,
      claims(CJ))

line, _ = run_cj(APPLY, (prof(pa, "toy-a"), ["srv"]), (prof(pb, "toy-b"), ["srv2"]))
check("C7: a server taken out of B's profile loses its claim, A's and B's other claim stay",
      sorted(tuple(c["at"])[3] for c in claims(CJ, "mcp:" + kb)) == ["srv2"] and len(claims(CJ, "mcp:" + ka)) == 1,
      claims(CJ))

# A project that moved (config/project-relocations.json): its key is gone from ~/.claude.json, so its claims go
# with it, and the claims of the new key are recorded; a project that did not move keeps its own.
drop_registry()
pr1, pr2 = project(), project()
k1, k2 = mcp.project_key(pr1), mcp.project_key(pr2)
run_cj(APPLY, (prof(pr1, "toy-r"), ["srv"]), (prof(pb, "toy-b"), ["srv2"]))
check("control: the project is claimed under its first key", len(claims(CJ, "mcp:" + k1)) == 1, claims(CJ))
run_cj(APPLY, (prof(pr2, "toy-r"), ["srv"]), relocations=[{"from": pr1, "to": pr2}])
check("control: the relocation moved the key", k1 not in cj_doc()["projects"] and k2 in cj_doc()["projects"], list(cj_doc()["projects"]))
check("C7: a relocated project's claims under the old key are gone", claims(CJ, "mcp:" + k1) == [], claims(CJ))
check("C7: and the new key's are recorded, another project's stay",
      len(claims(CJ, "mcp:" + k2)) == 1 and len(claims(CJ, "mcp:" + kb)) == 1, claims(CJ))

drop_registry()
pc = project()
kc = mcp.project_key(pc)
line, _ = run_cj(DRY, (prof(pc, "toy-c"), ["srv"]))
check("C7: a dry-run says it would write", "would write" in line, line)
check("C7: a dry-run records nothing", not os.path.exists(owned.path()), raw())

# A secret that does not resolve leaves the project's servers as they were: its claims are not touched.
drop_registry()
pd = project()
kd = mcp.project_key(pd)
run_cj(APPLY, (prof(pd, "toy-d"), ["srv"]))
saved = dict(SECRETS)
SECRETS.clear()
line, errs = run_cj(APPLY, (prof(pd, "toy-d"), ["srv"]))
SECRETS.update(saved)
check("C7: a project whose secret does not resolve keeps its claims", errs and len(claims(CJ, "mcp:" + kd)) == 1, (errs, claims(CJ)))

# ------------------------------------------------------------------------------------------ C10
drop_registry()
pe = project()
run_codex(APPLY, prof(pe, "toy-e"), ["srv"])
cfg = os.path.join(pe, ".codex", "config.toml")
text = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
got = [c for c in claims(cfg)]
check("control: config.toml holds the resolved token", FAKE_TOKEN in text, text[:100])
check("C10: config.toml is claimed as a file, owner codex, part codex",
      len(got) == 1 and (got[0]["kind"], got[0]["at"], got[0]["owner"], got[0].get("part")) == ("file", [], "codex", "codex"), got)
check("C10: the sum is the hash of the text written", got and got[0]["sum"] == owned.digest(text), got)
check("C10: the record never holds the token", FAKE_TOKEN not in raw(), "token in owned.json")
before, stamp = raw(), mtime()
time.sleep(0.05)  # the file system's clock is coarse: a rewrite within a tick would keep the mtime
run_codex(APPLY, prof(pe, "toy-e"), ["srv"])
check("C10: a second apply (content current) keeps the claim and leaves the record's bytes",
      raw() != "" and raw() == before and mtime() == stamp, "rewritten")
run_codex(APPLY, prof(pe, "toy-e"), ["srv", "srv2"])
text2 = open(cfg, encoding="utf-8").read()
check("C10: a rewrite with another server set re-claims the new text",
      text2 != text and (claims(cfg) or [{}])[0].get("sum") == owned.digest(text2), claims(cfg))

drop_registry()
pf = project()
run_codex(DRY, prof(pf, "toy-f"), ["srv"])
check("C10: a dry-run records nothing", not os.path.exists(owned.path()) and not os.path.exists(os.path.join(pf, ".codex")), raw())

# codex_harness off: forge takes its tables out, and the claim goes with them
drop_registry()
pg = project()
run_codex(APPLY, prof(pg, "toy-g"), ["srv"])
cfg_g = os.path.join(pg, ".codex", "config.toml")
check("the file is claimed before the switch goes off", len(claims(cfg_g)) == 1, claims(cfg_g))
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {"codex": True, "gsd": False, "hindsight": False, "caveman": False},
               "codex_harness": False}, fh)
lib.settings.cache_clear()
out = io.StringIO()
with contextlib.redirect_stdout(out):
    line = mcp.drop_codex_project_mcp(APPLY, prof(pg, "toy-g"), REGISTRY, [])
check("control: codex_harness off took forge's tables out", FAKE_TOKEN not in open(cfg_g, encoding="utf-8").read(), line)
check("C10: with codex_harness off the file's claim is gone", claims(cfg_g) == [], claims(cfg_g))
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {"codex": True, "gsd": False, "hindsight": False, "caveman": False},
               "codex_harness": True}, fh)
lib.settings.cache_clear()

# ------------------------------------------------------------------------------------------ C12
# A project with its own .gitignore: the line is added, claimed, and stays claimed.
drop_registry()
ph = project(gitignore="node_modules/\n")
gi = os.path.join(ph, ".gitignore")
run_codex(APPLY, prof(ph, "toy-h"), ["srv"])
check("control: the .codex/ line was added to .gitignore", ".codex/" in open(gi, encoding="utf-8").read().split(), open(gi).read())
got = claims(gi, "codex")
check("C12: the added .codex/ line is claimed on .gitignore",
      [(c["kind"], c["at"], c["owner"]) for c in got] == [("item", ["line", ".codex/"], "codex")], got)
check("C12: the claim is the hash of the line", got and got[0]["sum"] == owned.digest(".codex/"), got)
run_codex(APPLY, prof(ph, "toy-h"), ["srv"])
check("C12: the line stays claimed on a second apply (nothing was added the second time)",
      [c["at"] for c in claims(gi, "codex")] == [["line", ".codex/"]], claims(gi, "codex"))

# The user takes the line out and writes it back by hand: forge re-adds nothing, claims nothing it did not add.
# (A removed line is re-added by the next run and claimed again; what is checked here is the other order.)
drop_registry()
pi = project(gitignore="node_modules/\n.codex/\n")
gi_i = os.path.join(pi, ".gitignore")
run_codex(APPLY, prof(pi, "toy-i"), ["srv"])
check("C12: a .codex/ line that was already there is not claimed", claims(gi_i) == [], claims(gi_i))
run_codex(APPLY, prof(pi, "toy-i"), ["srv"])
check("C12: nor on a second apply", claims(gi_i) == [], claims(gi_i))

# A line the user already had without the slash is the same line to git, and not claimed either.
drop_registry()
pj = project(gitignore=".codex\n")
run_codex(APPLY, prof(pj, "toy-j"), ["srv"])
check("C12: `.codex` without the slash counts as already there, not claimed", claims(os.path.join(pj, ".gitignore")) == [], raw())

# No .gitignore at all: forge creates it, and claims the line it put there.
drop_registry()
pk = project()
run_codex(APPLY, prof(pk, "toy-k"), ["srv"])
check("C12: a .gitignore forge created holds the claimed line", len(claims(os.path.join(pk, ".gitignore"), "codex")) == 1,
      raw())

# A claim of the same part for another line (the .agents/ line, written by another writer) is left as it is,
# and keeps its place in the list.
drop_registry()
pl = project(gitignore=".agents/\n")
gi_l = os.path.join(pl, ".gitignore")
owned.record(gi_l, [owned.claim("item", ["line", ".agents/"], ".agents/", "codex")], True, part="codex")
run_codex(APPLY, prof(pl, "toy-l"), ["srv"])
check("C12: another line's claim of the same part stays, in front of this one",
      [c["at"] for c in claims(gi_l, "codex")] == [["line", ".agents/"], ["line", ".codex/"]], claims(gi_l, "codex"))
run_codex(APPLY, prof(pl, "toy-l"), ["srv"])
check("C12: and after a second apply", [c["at"] for c in claims(gi_l, "codex")] == [["line", ".agents/"], ["line", ".codex/"]],
      claims(gi_l, "codex"))

# A claimed line that is gone and that forge did not add this time loses its claim: a repo-owned project, its
# line in info/exclude claimed, then the user empties the exclude file and the repo's own .gitignore covers it.
drop_registry()
pm = project(gitignore="x/\n")
ex_m = os.path.join(pm, ".git", "info", "exclude")
run_codex(APPLY, prof(pm, "toy-m", writes_tracked_files=False), ["srv"])
check("the line was claimed on info/exclude first", len(claims(ex_m, "codex")) == 1, raw())
with open(ex_m, "w", encoding="utf-8") as fh:
    fh.write("")
with open(os.path.join(pm, ".gitignore"), "w", encoding="utf-8") as fh:
    fh.write(".codex/\n")
run_codex(APPLY, prof(pm, "toy-m", writes_tracked_files=False), ["srv"])
check("C12: a claimed line that is gone and not re-added (the repo's rule covers it) loses its claim",
      claims(ex_m, "codex") == [], (claims(ex_m, "codex"), open(ex_m).read()))

# Dry-run: the would-add line is not claimed.
drop_registry()
pn = project(gitignore="x/\n")
run_codex(DRY, prof(pn, "toy-n"), ["srv"])
check("C12: a dry-run claims nothing", not os.path.exists(owned.path()), raw())

# A repo-owned project (writes_tracked_files false): the line goes to .git/info/exclude, with the path prefix.
drop_registry()
po = project(gitignore="keep/\n")
run_codex(APPLY, prof(po, "toy-o", writes_tracked_files=False), ["srv"])
exclude = os.path.join(po, ".git", "info", "exclude")
got = claims(exclude, "codex")
check("control: the line is in info/exclude, .gitignore untouched",
      "/.codex/" in open(exclude, encoding="utf-8").read().split() and open(os.path.join(po, ".gitignore")).read() == "keep/\n", "")
check("C12: a repo-owned project's added line is claimed on info/exclude as the line written there",
      [(c["kind"], c["at"], c["owner"]) for c in got] == [("item", ["line", "/.codex/"], "codex")], got)
run_codex(APPLY, prof(po, "toy-o", writes_tracked_files=False), ["srv"])
check("C12: and stays claimed on a second apply", [c["at"] for c in claims(exclude, "codex")] == [["line", "/.codex/"]],
      claims(exclude, "codex"))
check("C12: the repo's .gitignore is never claimed", claims(os.path.join(po, ".gitignore")) == [], raw())

# A repo-owned project whose own .gitignore already ignores .codex/: nothing is added, nothing claimed.
drop_registry()
pp = project(gitignore=".codex/\n")
run_codex(APPLY, prof(pp, "toy-p", writes_tracked_files=False), ["srv"])
check("C12: a repo-owned project that already ignores .codex/ claims no line",
      claims(os.path.join(pp, ".git", "info", "exclude")) == [] and claims(os.path.join(pp, ".gitignore")) == [], raw())

check("the record never held the token anywhere in this run", FAKE_TOKEN not in raw(), "token in owned.json")
print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
