#!/usr/bin/env python3
"""Part 1.1 (consent window), unit U4: the `consent` row of `forge doctor` (forge/cli.py consent_row).

Off: a SKIP that says NOT RUN, NOT ARMED. On: the first problem found is a FAIL that names its fix, in this order:
gateway.json, adapter, built-in adapter's tools, no project with `production`, the `--consent` entry of
~/.claude/settings.json (missing, onFailure not "block"), timeout_s not below the entry's timeout, then the smoke
test: the entry's exact command, run with shell=True under the hook's own cap, on `git status` (must exit 0) and on an
unattended push to a production branch (must exit 2 with CONSENT_UNATTENDED:). The PASS says what it looked at.

A toy world per case: a toy forge root (a copy of the guard, gateway.json, projects, scripts/consent/), a toy HOME with
a settings.json, a PATH holding only a fake directory (python3 linked in, `gum` and the Omarchy launcher stubs), and
fake guards written here for the smoke test. The real guard of this branch still answers a match with `CONSENT_ERROR:
not wired yet` (U1c builds the window flow), so the smoke test is driven against fakes that honour the contract
(`CONSENT_UNATTENDED:`, exit 2). The one assertion that only holds end to end once U1c has landed: the real
hooks/guard_tool_use.py --consent, run through this row on the unattended push, exits 2 with CONSENT_UNATTENDED:
(not asserted here; checked by hand in the report).

Seen failing, against forge/cli.py of the base (no consent_row; INTEGRATION_NEEDS without "consent"): every case
raised AttributeError: module 'forge.cli' has no attribute 'consent_row', and the `integrations` row with consent on
raised KeyError: 'consent'. Then, against the finished row with one check removed at a time (a copy of the checkout
with the mutation applied, this file run against it), each case below went red alone:
  gateway check removed (consent_config not called)            -> gateway missing / invalid: "FAIL, got PASS"
  adapter check removed                                        -> adapter not there / not executable: got PASS
  gum / launcher check removed                                 -> built-in without gum / launcher: got PASS
  production check removed (`declared` never empty)            -> no project declares production: got PASS
  entry check removed / onFailure check removed                -> no entry, onFailure absent / "allow": got PASS
  timeout comparison `limit >= cap` weakened to `limit > cap`  -> timeout_s == cap (the boundary): got PASS
  smoke test removed (consent_probe returns None, the same as the `entry exists` control below)
                                                               -> missing .py, always-0 guard, CONSENT_ERROR guard, hang: got PASS
The control inside this file: with consent_probe replaced by `lambda *a, **k: None` (a row that only checks that the
entry exists) the entry pointing at a missing .py is a PASS, so the smoke test is the check that makes it a FAIL."""
import json
import os
import shutil
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

REPO = sandbox.FORGE
TOY = sandbox.mkdtemp("consent-doctor-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "FORGE_CONSENT"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, REPO)
from forge import lib  # noqa: E402

lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import cli, hooks  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
hooks.USER_SETTINGS = SETTINGS
REAL_PATH = os.environ.get("PATH", "")
REAL_ROOT = lib.ROOT

failures, n_cases = [], [0]
_n = [0]


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:500]))


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)


EXE = stat.S_IRWXU

# Fake guards. `record` appends what the hook was given: the payload, FORGE_CONSENT, XDG_STATE_HOME.
RECORD = '''import json, os, sys
raw = sys.stdin.read()
rec = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record.jsonl")
payload = json.loads(raw)
open(rec, "a").write(json.dumps({"payload": payload, "consent": os.environ.get("FORGE_CONSENT"),
    "state": os.environ.get("XDG_STATE_HOME"), "cwd": os.getcwd(), "project": os.environ.get("CLAUDE_PROJECT_DIR")}) + "\\n")
cmd = payload["tool_input"]["command"]
'''
GUARDS = {
    # the contract: nothing for a harmless call; an unattended match is refused with CONSENT_UNATTENDED:
    "good": RECORD + '''match = cmd.startswith(("git push", "vercel"))
if match and os.environ.get("FORGE_CONSENT") == "unattended":
    sys.stderr.write("CONSENT_UNATTENDED: nobody to ask; do not retry\\n")
    sys.exit(2)
if match:
    sys.exit(5)  # would have opened a window
sys.exit(0)
''',
    "exit2-other": RECORD + '''if cmd.startswith("git push"):
    sys.stderr.write("CONSENT_ERROR: not wired yet: the call matches the rule push-production\\n")
    sys.exit(2)
sys.exit(0)
''',
    "always0": "import sys\nsys.stdin.read()\nsys.exit(0)\n",
    "always2": "import sys\nsys.stdin.read()\nsys.stderr.write('CONSENT_UNATTENDED: nope\\n')\nsys.exit(2)\n",
    "hang": "import sys, time\nsys.stdin.read()\ntime.sleep(60)\n",
}

DEFAULT_PROD = {"branches": ["main"], "commands": ["vercel deploy --prod"]}


def world(consent=True, gateway="ok", adapter="omarchy", timeout_s=120, projects="prod", guard="good", entry="ok",
          cap=300, on_failure="block", tools=("gum", "omarchy-launch-floating-terminal-with-presentation"),
          adapter_mode=EXE, prod=DEFAULT_PROD):
    """A toy forge root, HOME and PATH for one case; returns the fake guard's directory. `gateway`: "ok", "missing",
    "broken" or a path for the adapter; `projects`: "prod", "none" or "invalid"; `entry`: "ok", "missing",
    "nofile" (the command names a .py that is not there), "no-settings" (no settings.json at all)."""
    _n[0] += 1
    top = os.path.join(TOY, "case-%d" % _n[0])
    root = os.path.join(top, "forge")
    for sub in ("hooks", "config/projects", "scripts/consent"):
        os.makedirs(os.path.join(root, sub))
    shutil.copy(os.path.join(REPO, "hooks", "guard_tool_use.py"), os.path.join(root, "hooks", "guard_tool_use.py"))
    write(os.path.join(root, "scripts", "consent", "omarchy"), "#!/bin/sh\nexit 0\n", adapter_mode)
    write(os.path.join(root, "scripts", "consent", "custom"), "#!/bin/sh\nexit 0\n", adapter_mode)
    if adapter == "not-there":
        adapter = "scripts/consent/absent"
    doc = json.load(open(os.path.join(REPO, "examples", "gateway.json"), encoding="utf-8"))
    doc["consent"]["adapter"] = adapter
    doc["consent"]["timeout_s"] = timeout_s
    gpath = os.path.join(root, "config", "gateway.json")
    if gateway == "ok":
        write(gpath, json.dumps(doc))
    elif gateway == "broken":
        write(gpath, "{ not json")
    elif gateway == "forbidden":  # /usr/bin/true: outside scripts/consent
        doc["consent"]["adapter"] = "/usr/bin/true"
        write(gpath, json.dumps(doc))
    project = os.path.join(top, "app")
    os.makedirs(project)
    if projects == "prod":
        write(os.path.join(root, "config", "projects", "app.claude.json"),
              json.dumps({"project": "app", "project_path": project, "production": prod}))
    elif projects == "none":
        write(os.path.join(root, "config", "projects", "app.claude.json"), json.dumps({"project": "app", "project_path": project}))
    elif projects == "invalid":
        write(os.path.join(root, "config", "projects", "app.claude.json"),
              json.dumps({"project": "app", "project_path": project, "production": {"branches": "main"}}))
    gdir = os.path.join(top, "guards")
    os.makedirs(gdir)
    write(os.path.join(gdir, "guard_tool_use.py"), GUARDS[guard])
    command = "python3 %s --consent" % os.path.join(gdir, "guard_tool_use.py" if entry != "nofile" else "gone/guard_tool_use.py")
    hook = {"type": "command", "command": command, "timeout": cap}
    if on_failure is not None:
        hook["onFailure"] = on_failure
    groups = {"PreToolUse": [{"matcher": "Bash|mcp__.*", "hooks": [hook]}]}
    if entry == "missing":
        groups = {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 /elsewhere/other.py", "timeout": 10}]}]}
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)
    if entry != "no-settings":
        write(SETTINGS, json.dumps({"hooks": groups}))
    bindir = os.path.join(top, "bin")
    os.makedirs(bindir)
    os.symlink(sys.executable, os.path.join(bindir, "python3"))
    for tool in tools:
        write(os.path.join(bindir, tool), "#!/bin/sh\nexit 0\n", EXE)
    os.environ["PATH"] = bindir  # only the fake directory (standing order 10): no real gum or launcher behind it
    lib.ROOT = root
    lib.SETTINGS = os.path.join(top, "forge.json")
    integrations = {k: False for k in lib.INTEGRATIONS}
    if consent is not None:
        integrations["consent"] = consent
    write(lib.SETTINGS, json.dumps({"integrations": integrations, "user_settings": {}, "user_hooks": []}))
    lib.settings.cache_clear()
    return gdir


def row():
    try:
        return cli.consent_row()
    except BaseException as e:  # a crash is a red check, not a traceback
        return lib.Result("CRASH", "consent", "%s: %s" % (type(e).__name__, e))
    finally:
        os.environ["PATH"] = REAL_PATH
        lib.ROOT = REAL_ROOT


def fails(label, kwargs, *words):
    """A FAIL whose detail holds every word (the problem and its fix)."""
    r = None
    world(**kwargs)
    r = row()
    check("%s: FAIL" % label, r.level == "FAIL", "%s %s" % (r.level, r.detail))
    check("%s: names %s" % (label, words), r.level == "FAIL" and all(w in r.detail for w in words), r.detail)
    return r


# ---------------------------------------------------------------- SKIP
for consent in (False, None):
    world(consent=consent)
    r = row()
    check("off (%r): SKIP saying NOT RUN, NOT ARMED" % consent, r.level == "SKIP" and r.detail.startswith(cli.NOT_ARMED), r)
check("the doctor lists the row", any(c[0] == "consent" and c[1] is cli.consent_row for c in cli.CHECKS), "no consent row in CHECKS")

# ---------------------------------------------------------------- PASS, and what it looked at
gdir = world()
r = row()
check("good world: PASS", r.level == "PASS", r)
for piece in ("scripts/consent/omarchy", "timeout_s 120 below the hook's 300 s", "1 project(s) with production", "`git status` exits 0",
              "`git push origin main` exits 2 with CONSENT_UNATTENDED:", "guard_tool_use.py --consent"):
    check("PASS says %r" % piece, piece in r.detail, r.detail)
recs = [json.loads(l) for l in open(os.path.join(gdir, "record.jsonl"))] if os.path.exists(os.path.join(gdir, "record.jsonl")) else []
check("the hook was run twice, on git status then the push", [x["payload"]["tool_input"]["command"] for x in recs] == ["git status", "git push origin main"], recs)
check("both payloads were Bash payloads with the project's cwd, FORGE_CONSENT=unattended",
      all(x["payload"]["tool_name"] == "Bash" and x["payload"]["cwd"].endswith("/app") and x["consent"] == "unattended" for x in recs), recs)
check("the probe ran from the project's directory", all(x["cwd"].endswith("/app") for x in recs), recs)
check("the probe's XDG_STATE_HOME is private and gone after the run (no line in the real consent log)",
      all(x["state"] and "forge-consent-probe-" in x["state"] and not os.path.exists(x["state"]) for x in recs), recs)
check("the probe handed no CLAUDE_PROJECT_DIR to the hook", all(x["project"] is None for x in recs), recs)

# an adapter of the user's own does not need gum or the launcher
world(adapter="scripts/consent/custom", tools=())
r = row()
check("custom adapter without gum or launcher: PASS", r.level == "PASS", r)
# production with commands only: a command stands in for the push
world(prod={"commands": ["vercel deploy --prod"]})
r = row()
check("commands-only production: PASS, sending the command", r.level == "PASS" and "`vercel deploy --prod` exits 2" in r.detail, r)
world(prod={"commands": ["mcp__db__write"]})
r = row()
check("only an MCP tool name in production: FAIL (no Bash payload to send)", r.level == "FAIL" and "branch" in r.detail, r)

# ---------------------------------------------------------------- one case per FAIL
fails("gateway.json missing", dict(gateway="missing"), "gateway.json", "cp examples/gateway.json config/gateway.json")
fails("gateway.json not JSON", dict(gateway="broken"), "gateway.json", "cannot be read")
fails("gateway.json with an adapter outside scripts/consent", dict(gateway="forbidden"), "outside scripts/consent", "gateway.json")
fails("adapter not there", dict(adapter="not-there"), "not there", "scripts/consent/absent")
fails("adapter not executable", dict(adapter_mode=0o644), "not executable", "chmod +x")
fails("built-in adapter without gum", dict(tools=("omarchy-launch-floating-terminal-with-presentation",)), "`gum`", "install gum")
fails("built-in adapter without the Omarchy launcher", dict(tools=("gum",)), "omarchy-launch-floating-terminal-with-presentation", "another adapter")
fails("no project declares production", dict(projects="none"), "no project", "production", "never open")
fails("no project at all", dict(projects="absent"), "no project", "production")
fails("a project's production is invalid", dict(projects="invalid"), "app.claude.json", "fix the project")
fails("no settings.json", dict(entry="no-settings"), "settings.json", "forge sync --apply")
fails("settings.json without the --consent entry", dict(entry="missing"), "--consent", "forge sync --apply")
fails("entry without onFailure", dict(on_failure=None), "onFailure", '"block"', "forge sync --apply")
fails("entry with onFailure allow", dict(on_failure="allow"), "onFailure", '"allow"', "forge sync --apply")
fails("timeout_s equal to the hook's timeout (the boundary)", dict(timeout_s=300), "timeout_s is 300", "300", "lower timeout_s")
fails("timeout_s above the hook's timeout", dict(timeout_s=500), "timeout_s is 500", "lower timeout_s")
world(timeout_s=299)
r = row()
check("timeout_s one below the hook's timeout: PASS", r.level == "PASS", r)

# ---------------------------------------------------------------- the smoke test
fails("entry pointing at a .py that is not there", dict(entry="nofile"), "smoke test", "`git status` exited 2, want 0", "gone/guard_tool_use.py", "forge sync --apply")
fails("a guard that always exits 0", dict(guard="always0"), "smoke test", "git push origin main", "exited 0, want 2")
fails("a guard that refuses git status too", dict(guard="always2"), "`git status` exited 2, want 0")
fails("a guard that hangs, under the entry's own cap", dict(guard="hang", cap=2, timeout_s=1), "did not answer in 2 s")
world(guard="hang", cap=2, timeout_s=1)
t0 = __import__("time").monotonic()
row()
check("the hang is bounded by the entry's timeout (2 s, took %.1f)" % (__import__("time").monotonic() - t0),
      __import__("time").monotonic() - t0 < 10, "")

# exit 2 on the push with another text: the contract word is required, not just the exit code
r = fails("a guard that answers the push with CONSENT_ERROR (the guard of this branch, before U1c)", dict(guard="exit2-other"),
          "as wanted but its stderr has no CONSENT_UNATTENDED:")

# ---------------------------------------------------------------- the first problem wins
world(gateway="broken", entry="no-settings", projects="none")
r = row()
check("gateway.json broken, no project and no settings.json: the gateway is named, once", r.level == "FAIL" and "gateway.json" in r.detail
      and "settings.json" not in r.detail.split("--")[0], r.detail)
world(projects="none", entry="no-settings")
r = row()
check("no production and no settings.json: production first", r.level == "FAIL" and "production" in r.detail, r.detail)
world(entry="nofile", timeout_s=300)
r = row()
check("timeout_s at the cap and a dead entry: the timing is named before the smoke test", "timeout_s" in r.detail, r.detail)

# ---------------------------------------------------------------- control: a row that only checks that the entry exists
world(entry="nofile")
real_probe = getattr(cli, "consent_probe", None)
cli.consent_probe = lambda *a, **k: None
try:
    r = row()
finally:
    if real_probe is not None:
        cli.consent_probe = real_probe
    else:
        del cli.consent_probe
check("control: with the smoke test removed the entry pointing at a missing .py is a PASS (the smoke test is what fails it)",
      r.level == "PASS", r)
world(entry="nofile")
r = row()
check("and with the smoke test back it is a FAIL", r.level == "FAIL", r)

# ---------------------------------------------------------------- the integrations row with consent on (the KeyError U3 left)
world(consent=True)
try:
    out = cli.integrations_row()
    got = [x for x in out if "consent is on" in x.detail]
    check("integrations row with consent on: a PASS line for consent, no KeyError", len(got) == 1 and got[0].level == "PASS", out)
except KeyError as e:
    check("integrations row with consent on: a PASS line for consent, no KeyError", False, "KeyError %s" % e)
finally:
    os.environ["PATH"] = REAL_PATH
    lib.ROOT = REAL_ROOT
world(consent=False)
out = cli.integrations_row()
check("integrations row with consent off: a SKIP line for consent",
      any(x.level == "SKIP" and "consent is off" in x.detail for x in out), out)
os.environ["PATH"] = REAL_PATH
lib.ROOT = REAL_ROOT

# ---------------------------------------------------------------- result
sandbox.cleanup(bool(failures))
if failures:
    print("FAIL: %d of %d checks" % (len(failures), n_cases[0]))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("OK: %d checks" % n_cases[0])
