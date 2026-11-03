#!/usr/bin/env python3
"""Part 1.1 (consent window), unit U3: the engine's wiring. The window itself is hooks/guard_tool_use.py --consent
(U1a-U1c); this suite covers only what forge/lib.py and forge/hooks.py do for it:

- `consent` is an integration (lib.INTEGRATIONS); absent counts as off.
- the user-scope hook row (PreToolUse, matcher `Bash|mcp__.*`, `guard_tool_use.py --consent`, timeout 300,
  `"onFailure": "block"`) is written only with `integrations.consent` true, for Claude Code only. With it off the
  row is not written and an entry holding exactly its command is taken out (by command, never by marker).
- reconcile compares and writes `onFailure` too: an entry that is right except for it is repaired, not kept.
- the profile field `production` has a row in lib.PROFILE_FIELDS and lib.profile_error asks the guard's single
  production_error (imported by importlib: hooks/ is not edited from here).
- rollback (I8): with consent on, the row written and config/gateway.json broken, `consent: false` and
  `forge sync --apply` exits 0 and removes the entry, because forge sync never reads gateway.json.
- toy-world dry-run with consent true differs from consent false only by the new row's note, and consent absent is
  byte-identical to consent false.
- examples/forge.json has `"consent": false`; examples/gateway.json is accepted by the guard's consent_config;
  README.md has the integration row.

Everything runs against a toy HOME and toy forge.json (in-process, lib.may_write stubbed to allow: this checkout may
be a linked worktree) or in a copy of the engine in a toy world (subprocess, `forge sync`). Nothing real is read or
written.

Seen failing on 10182c3 (U1a: the guard validates, the engine does not wire; this file run against that commit's
forge/lib.py and forge/hooks.py, README.md and examples/ with the new files absent), 42 of 79 checks red:
  on: exactly one entry for the row is written -- []  (line: "appended SessionStart forge session-start ...", no
    PreToolUse row), and with it the event, matcher, command, timeout, onFailure and entry-type checks (None / {})
  on, codex harness on: the Claude file has the row -- []
  off / absent: the entry holding exactly the row's command is taken out -- the seeded entry was still there; the
    note says it was dropped -- the line was "appended SessionStart forge session-start ..." (the row is unknown to
    reconcile, so nothing takes its entry out)
  repair, onFailure missing / wrong: it now says "block" -- the entry stayed as seeded (no onFailure / "allow"), and
    the note says repaired -- it said nothing of the sort
  PROFILE_FIELDS has a row for production -- None; profile_error rejects production 'main' / None / [] /
    {"branches": "main"} / {"branches": [""]} / ... (got None), and says the guard's own words -- forge: None
  examples/forge.json has "consent": false -- {'codex': False, 'gsd': False, 'hindsight': False}; its _doc names
    consent; examples/gateway.json exists / has the plan's rules / passes consent_config -- missing; README row --
    []
  dry-run: with consent true the output holds the new row's note -- absent
  rollback: the entry is written, with onFailure block -- []
The checks that pass there on purpose (controls): the toy world's other row is written, a foreign entry stays, the
`--project` guard entry stays, a valid production is accepted, an entry that is right is left byte-for-byte,
consent absent is byte-identical to consent false in the dry-run, and the rollback's last four checks (the entry is
gone, sync exits 0, ...), which hold vacuously until the row exists: the rollback is red at its first check.
Negative controls on the finished code, each mutation put back from a copy of the file (checks red):
  onFailure left out of the comparison in reconcile (4: both repair cases, "it now says block" and "repaired")
  onFailure not written into a fresh entry (8: "onFailure is block", the second run not current, both repairs)
  row not listed in ROW_INTEGRATION (8: the off and absent rows are written, the entry is not taken out)
  profile_error not asking the guard (12: every object-shaped bad production is accepted)
  production not in PROFILE_FIELDS (1)
  write_user_settings reading config/gateway.json when consent is on (2: the rollback's exit 0 and its entry
    written; this is the check that a broken gateway.json cannot stop the rollback)
The rollback also carries its own control: the same broken gateway.json makes `guard_tool_use.py --consent` exit 2
with CONSENT_ERROR, so the break is real."""
import importlib
import importlib.util
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("consent-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402

lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import hooks  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CODEX = os.path.join(HOME, ".codex", "hooks.json")

failures, n_cases = [], [0]
MARKER = "guard_tool_use.py --consent"
CMD = "python3 %s/hooks/guard_tool_use.py --consent" % lib.ROOT
MATCHER = "Bash|mcp__.*"
PROJECT_CMD = "python3 %s/hooks/guard_tool_use.py --project toy" % lib.ROOT
FOREIGN_CMD = "python3 /elsewhere/other_guard.py"
_n = [0]


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:600]))


def world(consent, codex=False):
    """A toy forge.json with `consent` (True, False or None for the key absent), hooks reloaded over it (its rows
    are computed at import) and no file a run leaves."""
    _n[0] += 1
    integrations = {"codex": codex, "gsd": False, "hindsight": False}
    if consent is not None:
        integrations["consent"] = consent
    lib.SETTINGS = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
        json.dump({"integrations": integrations, "user_settings": {}, "user_hooks": [], "codex_harness": codex}, fh)
    lib.settings.cache_clear()
    importlib.reload(hooks)
    hooks.USER_SETTINGS, hooks.CODEX_HOOKS = SETTINGS, CODEX
    for p in (SETTINGS, SETTINGS + ".bak", CODEX, CODEX + ".bak"):
        if os.path.exists(p):
            os.remove(p)
    return hooks


def run(h, which="claude"):
    try:
        ctx = lib.Ctx(True, None, True)
        return (h.write_user_settings if which == "claude" else h.write_codex_hooks)(ctx)
    except BaseException as e:  # a crash is a red check, not a traceback (sync's sys.exit included)
        return "raised %s: %s" % (type(e).__name__, e)


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def entries(p, marker=MARKER):
    """[(event, group matcher, hook entry)] of every entry whose command holds `marker`."""
    if not os.path.exists(p):
        return []
    return [(ev, g.get("matcher"), h) for ev, groups in load(p).get("hooks", {}).items() for g in groups
            for h in g.get("hooks", []) if marker in h.get("command", "")]


def seed(event, cmd, matcher=None, timeout=None, extra=None):
    doc = load(SETTINGS) if os.path.exists(SETTINGS) else {}
    hook = dict({"type": "command", "command": cmd}, **({"timeout": timeout} if timeout else {}), **(extra or {}))
    g = {"hooks": [hook]}
    if matcher:
        g["matcher"] = matcher
    doc.setdefault("hooks", {}).setdefault(event, []).append(g)
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def guard_module():
    spec = importlib.util.spec_from_file_location("guard_tool_use_toy", os.path.join(REPO, "hooks", "guard_tool_use.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- the row, consent on
h = world(True)
line = run(h)
got = entries(SETTINGS)
check("on: exactly one entry for the row is written (line: %s)" % line, len(got) == 1, got)
ev, matcher, hook = got[0] if got else (None, None, {})
check("on: the event is PreToolUse", ev == "PreToolUse", ev)
check("on: the group matcher is %r" % MATCHER, matcher == MATCHER, matcher)
check("on: the command is %r" % CMD, hook.get("command") == CMD, hook.get("command"))
check("on: the timeout is 300", hook.get("timeout") == 300, hook.get("timeout"))
check('on: onFailure is "block"', hook.get("onFailure") == "block", hook)
check("on: the entry is a command hook", hook.get("type") == "command", hook)
check("on: a second run is already current", "already current" in str(run(h)), line)
check("on: the second run left one entry", len(entries(SETTINGS)) == 1, entries(SETTINGS))
check("control: the toy world's other row is written (SessionStart forge session-start)",
      bool(entries(SETTINGS, "forge session-start")), load(SETTINGS) if os.path.exists(SETTINGS) else "no settings.json")

# Claude Code only: Codex gets no row, even with codex_harness true.
h = world(True, codex=True)
run(h, "claude")
run(h, "codex")
check("on, codex harness on: the Claude file has the row", len(entries(SETTINGS)) == 1, entries(SETTINGS))
check("on, codex harness on: the Codex file has no entry for it", entries(CODEX) == [], entries(CODEX))

# ---------------------------------------------------------------- consent off, and absent
for tag, flag in (("off", False), ("absent", None)):
    h = world(flag)
    run(h)
    check("%s: the row is not written" % tag, entries(SETTINGS) == [], entries(SETTINGS))
    check("%s: control: the toy world's other row is written" % tag, bool(entries(SETTINGS, "forge session-start")), "no SessionStart row")

    h = world(flag)
    seed("PreToolUse", CMD, MATCHER, 300, {"onFailure": "block"})
    seed("PreToolUse", PROJECT_CMD, "Bash", 10)
    seed("PreToolUse", "python3 /elsewhere/hooks/guard_tool_use.py --consent", "Bash", 5)
    seed("PreToolUse", FOREIGN_CMD, "Bash", 5)
    line = run(h)
    left = [e[2]["command"] for e in entries(SETTINGS, "")]
    check("%s: the entry holding exactly the row's command is taken out (line: %s)" % (tag, line), CMD not in left, left)
    check("%s: the note says it was dropped" % tag, "dropped" in str(line) and MARKER in str(line), line)
    check("%s: the `--project` guard entry stays" % tag, PROJECT_CMD in left, left)
    check("%s: an entry that only shares the marker (another path) stays: off rows go by exact command" % tag,
          "python3 /elsewhere/hooks/guard_tool_use.py --consent" in left, left)
    check("%s: a foreign entry stays" % tag, FOREIGN_CMD in left, left)

# ---------------------------------------------------------------- repair of onFailure
for tag, extra in (("missing", None), ("wrong", {"onFailure": "allow"})):
    h = world(True)
    seed("PreToolUse", CMD, MATCHER, 300, extra)
    line = run(h)
    got = entries(SETTINGS)
    check("repair, onFailure %s: one entry is left (line: %s)" % (tag, line), len(got) == 1, got)
    check('repair, onFailure %s: it now says "block"' % tag, bool(got) and got[0][2].get("onFailure") == "block", got)
    check("repair, onFailure %s: the note says repaired" % tag, "repaired" in str(line), line)
    check("repair, onFailure %s: the next run is already current" % tag, "already current" in str(run(h)), line)

h = world(True)
run(h)
doc = load(SETTINGS)
before = json.dumps(doc, sort_keys=True)
check("control: an entry that is right is left byte-for-byte (the repair test is not just rewriting)",
      "already current" in str(run(h)) and json.dumps(load(SETTINGS), sort_keys=True) == before, "rewritten")

# ---------------------------------------------------------------- the profile field `production`
check("PROFILE_FIELDS has a row for production", lib.PROFILE_FIELDS.get("production") is dict, lib.PROFILE_FIELDS.get("production"))
guard = guard_module()
GOOD = [{"branches": ["main", "production"], "commands": ["vercel --prod", "mcp__supabase-toy__execute_sql"]},
        {"branches": ["main"]}, {"commands": ["npm publish"]}, {}]
BAD = ["main", None, [], {"branches": "main"}, {"branches": [""]}, {"branches": ["main", 3]}, {"commands": [" "]},
       {"branches": ["main"], "extra": []}, {"branch": ["main"]}]
for v in GOOD:
    check("profile_error accepts production %r" % (v,), lib.profile_error({"project": "toy", "production": v}) is None,
          lib.profile_error({"project": "toy", "production": v}))
for v in BAD:
    why = lib.profile_error({"project": "toy", "production": v})
    check("profile_error rejects production %r (got %r)" % (v, why), isinstance(why, str) and "production" in why, why)
    if isinstance(v, dict):  # a non-object is the PROFILE_FIELDS type message; an object is judged by the guard alone
        expect = guard.production_error(v)
        check("profile_error says the guard's own words for %r" % (v,), isinstance(why, str) and expect in why,
              "guard: %r, forge: %r" % (expect, why))
check("control: the guard itself rejects every BAD value (the parity above compares against something)",
      all(guard.production_error(v) is not None for v in BAD if not isinstance(v, (str, type(None), list))), "")
check("profile_error is silent about a profile without production", lib.profile_error({"project": "toy"}) is None, "")

# ---------------------------------------------------------------- the example files and the README
ex = load(os.path.join(REPO, "examples", "forge.json"))
check('examples/forge.json has "consent": false next to the other integrations',
      ex.get("integrations", {}).get("consent") is False and set(ex["integrations"]) == {"codex", "gsd", "hindsight", "consent"},
      ex.get("integrations"))
check("examples/forge.json's _doc names consent", "consent" in ex.get("_doc", ""), "")

gw_path = os.path.join(REPO, "examples", "gateway.json")
gw = load(gw_path) if os.path.exists(gw_path) else {}
check("examples/gateway.json exists with a consent section and no notify", "consent" in gw and "notify" not in gw, sorted(gw))
c = gw.get("consent", {})
check("examples/gateway.json: adapter omarchy, timeout_s 120, the two rules of the plan",
      c.get("adapter") == "omarchy" and c.get("timeout_s") == 120
      and [(r.get("id"), r.get("match")) for r in c.get("rules", [])]
      == [("push-production", "production.branches"), ("production-command", "production.commands")], c)
toy_root = os.path.join(TOY, "gwroot")
os.makedirs(os.path.join(toy_root, "config"))
os.makedirs(os.path.join(toy_root, "scripts", "consent"))
if os.path.exists(gw_path):
    with open(gw_path, encoding="utf-8") as src, open(os.path.join(toy_root, "config", "gateway.json"), "w", encoding="utf-8") as dst:
        dst.write(src.read())
try:
    cfg = guard.consent_config(toy_root)
    why = None
except ValueError as e:
    cfg, why = None, str(e)
check("examples/gateway.json passes the guard's consent_config (%s)" % why, cfg is not None and cfg["timeout_s"] == 120, why)

with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
    readme = fh.read()
rows = [l for l in readme.splitlines() if l.startswith("| `consent` |")]
check("README.md has one `consent` row in the integrations table", len(rows) == 1, rows)
row = rows[0] if rows else ""
check("README row: says it needs Omarchy and gum, that it is off by default and how to roll back",
      "Omarchy" in row and "gum" in row and "off" in row.split("|")[-2] and "integrations.consent" in row and "forge sync --apply" in row, row)

# ---------------------------------------------------------------- rollback (I8) and the dry-run, in a copy of the engine
top = sandbox.mkdtemp("consent-world-")
root, home, tmp = (os.path.join(top, n) for n in ("forge", "home", "tmp"))
proj = os.path.join(top, "projects", "toy")
for d in (home, tmp, proj):
    os.makedirs(d)
sandbox.copy_engine(root)
sandbox.seed(root)
sandbox.git(root, "init", "-q")
sandbox.git(root, "add", "-A")
sandbox.git(root, "commit", "-q", "-m", "engine")
cfg_dir = os.path.join(root, "config")
for f in os.listdir(os.path.join(cfg_dir, "profiles")):  # the fixture's profiles name /srv/toy/*, outside the world
    os.remove(os.path.join(cfg_dir, "profiles", f))
with open(os.path.join(cfg_dir, "profiles", "toy.claude.json"), "w", encoding="utf-8") as fh:
    json.dump({"project": "toy", "project_path": proj, "enableAllProjectMcpServers": True, "servers": [],
               "plugins_keep": [], "skills_keep": ["*"], "permissions": {}}, fh)
os.makedirs(os.path.join(root, "credentials"))
with open(os.path.join(root, "credentials", "secrets.json"), "w", encoding="utf-8") as fh:
    json.dump({"TOY_TOKEN": "toy"}, fh)
os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg_dir, "secrets.json"))
ENV = sandbox.bare_env(home, tmp)
W_SETTINGS = os.path.join(home, ".claude", "settings.json")
GATEWAY = os.path.join(cfg_dir, "gateway.json")


def set_consent(value):
    p = os.path.join(cfg_dir, "forge.json")
    fj = load(p)
    fj["integrations"] = {k: False for k in ("codex", "gsd", "hindsight")}
    fj["codex_harness"] = False
    if value is not None:
        fj["integrations"]["consent"] = value
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(fj, fh)


def forge(*args):
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "forge")] + list(args), cwd=root, env=ENV,
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


NOTE = "; appended PreToolUse %s [%s]" % (MARKER, MATCHER)
outs = {}
for tag, flag in (("absent", None), ("off", False), ("on", True)):
    set_consent(flag)
    code, out = forge("sync", "--all")
    outs[tag] = out
    check("dry-run, consent %s: exits 0 (%s)" % (tag, out.strip().splitlines()[-1:] or ""), code == 0, out[-400:])
check("dry-run: nothing was written by the dry-runs", not os.path.exists(W_SETTINGS), "")
check("dry-run: consent absent is byte-identical to consent false", outs["absent"] == outs["off"], "absent and off differ")
check("dry-run: the control has something to compare (the settings.json line is there)", "settings.json" in outs["off"], outs["off"][-400:])
check("dry-run: with consent true the output holds the new row's note", NOTE in outs["on"], outs["on"][-600:])
check("dry-run: with consent true the output differs from off only by that note",
      outs["on"].replace(NOTE, "") == outs["off"], "after taking the note out the outputs still differ")

BROKEN = "{ this is not json"
with open(GATEWAY, "w", encoding="utf-8") as fh:
    fh.write(BROKEN)
set_consent(True)
code, out = forge("sync", "--apply", "--all")
check("rollback: sync --apply with consent on and a broken gateway.json exits 0 (forge never reads gateway.json)", code == 0, out[-600:])
got = entries(W_SETTINGS) if os.path.exists(W_SETTINGS) else []
check("rollback: the entry is written, with onFailure block", len(got) == 1 and got[0][2].get("onFailure") == "block", got)
r = subprocess.run([sys.executable, os.path.join(root, "hooks", "guard_tool_use.py"), "--consent"], cwd=root, env=ENV,
                   input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": proj}),
                   capture_output=True, text=True, timeout=60)
check("rollback: control: the broken gateway.json really breaks the hook (exit 2, CONSENT_ERROR; got %d %r)" % (r.returncode, r.stderr[:80]),
      r.returncode == 2 and "CONSENT_ERROR" in r.stderr, r.stderr)
set_consent(False)
code, out = forge("sync", "--apply", "--all")
check("rollback: consent false and sync --apply exits 0 with gateway.json still broken", code == 0, out[-600:])
check("rollback: the entry is gone", (entries(W_SETTINGS) if os.path.exists(W_SETTINGS) else None) == [], entries(W_SETTINGS))
check("rollback: the other forge rows are still there", bool(entries(W_SETTINGS, "forge session-start")), "")
with open(GATEWAY, encoding="utf-8") as fh:
    check("rollback: gateway.json was left exactly as it was (sync does not touch it)", fh.read() == BROKEN, "changed")

# ---------------------------------------------------------------- result
sandbox.cleanup(bool(failures))
if failures:
    print("FAIL: %d of %d checks" % (len(failures), n_cases[0]))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("OK: %d checks" % n_cases[0])
