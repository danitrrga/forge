#!/usr/bin/env python3
"""A profile `env` value of the exact form `${NAME}` is resolved from the secrets the generator
already loads (mcp.resolve_secrets) when skills.write_settings_local writes
<project>/.claude/settings.local.json; before, it arrived as literal `${NAME}` text. A NAME the
secrets lack is a `!` line (the run exits 1) and that key is not written; a file that received a
secret is mode 0600, and one that received none keeps the mode it always had. No run prints a
resolved value: the summary says `env 3 (2 from secrets)`.

Runs in-process against a toy HOME and toy config/ (a toy project per case); the values are fake and
nothing real is read or written. Seen failing on d7c2b73 (skills.py copying `env` verbatim, the new arguments accepted and ignored),
15 of 27 checks red:
  resolved: the file holds the secret -- BASELINE_TEST_EMAIL was '${BASELINE_TEST_EMAIL}'
  resolved: the file is 0600 -- mode was 0o644
  resolved, dry run / apply: the summary counts them -- the line ends ", env 3)", no "(2 from secrets)"
  already current but loose: would chmod / chmod 600 -- the file stayed 0o644 ("already current")
  missing: the key is not written -- BASELINE_TEST_PASSWORD was '${BASELINE_TEST_PASSWORD}'
  missing: one error naming the secret -- errors []
  missing: sync exits 1 with a `!` line naming the secret -- exit 0, '!' lines []
  resolved: sync wrote the secrets, 0600 -- mode 0o644; sync counts them -- not counted
Negative controls on the finished code, each put back from a copy of skills.py:
  verbatim copy again -- 8 red (the file holds the secret, the missing key written, no error, sync exit 0)
  mode not passed to write_json -- 3 red: resolved: the file is 0600; again: already current,
    byte-identical; sync wrote the secrets, 0600
  the missing-name error not appended -- 3 red: missing: one error naming the secret; an empty value
    is missing too; sync exits 1 with a `!` line
  the loose-mode correction removed -- 2 red: already current but loose, dry run; chmod 600
  summary prints the values -- 7 red: the summary counts them and no resolved value in the output (x4 runs)
"""
import contextlib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("profile-env-secrets-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from forge import lib  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "config")
lib.SETTINGS = os.path.join(FIXTURES, "forge.json")
from forge import skills, sync  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"

APPLY = lib.Ctx(True, None, False)
DRY = lib.Ctx(False, None, False)
# Fake values, distinctive enough that finding one in an output is not a coincidence.
EMAIL, PASSWORD = "fake-login-9f3a-NOT-REAL", "fake-pw-7c1d-NOT-REAL"
SECRETS = {"BASELINE_TEST_EMAIL": EMAIL, "BASELINE_TEST_PASSWORD": PASSWORD}
ENV = {"BASELINE_TEST_EMAIL": "${BASELINE_TEST_EMAIL}", "BASELINE_TEST_PASSWORD": "${BASELINE_TEST_PASSWORD}",
       "PLAIN": "kept"}

failures = []
n_cases = 0
n_proj = 0


def check(label, ok, detail=""):
    global n_cases
    n_cases += 1
    if not ok:
        failures.append("%s: %s" % (label, detail))
        print("FAIL", label, detail)


def project(mode=None, settings=None):
    """A toy project dir, with a settings.local.json of `mode` when `settings` is given."""
    global n_proj
    n_proj += 1
    p = os.path.join(TOY, "proj%d" % n_proj)
    os.makedirs(os.path.join(p, ".claude"))
    if settings is not None:
        f = slp(p)
        lib.write_json(f, settings)
        os.chmod(f, mode)
    return p


def slp(p):
    return os.path.join(p, ".claude", "settings.local.json")


def mode_of(p):
    return os.stat(slp(p)).st_mode & 0o777


def run(p, ctx=APPLY, env=ENV, secrets=SECRETS):
    """(the line, the errors, what the call printed to stdout and stderr)."""
    prof = {"project": "toy", "project_path": p, "permissions": {"allow": ["Bash(true)"]}, "env": dict(env)}
    errors, out, err = [], io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        line = skills.write_settings_local(ctx, prof, secrets, errors)
    return line, errors, out.getvalue() + err.getvalue()


def leaks(*texts):
    return [v for t in texts for v in (EMAIL, PASSWORD) if v in t]


# 1. A resolved env: values in the file, a plain one untouched, 0600, the summary a count.
p = project()
line, errors, printed = run(p, DRY)
check("resolved, dry run: the summary counts them", ", env 3 (2 from secrets)" in (line or ""), "the line was %r" % line)
check("resolved, dry run: nothing written", not os.path.exists(slp(p)), "the file exists")
check("resolved, dry run: no resolved value in the output", not leaks(line or "", printed, repr(errors)), "leaked %r" % leaks(line or "", printed))
line, errors, printed = run(p)
doc = json.load(open(slp(p)))
check("resolved: the file holds the secret", doc.get("env", {}).get("BASELINE_TEST_EMAIL") == EMAIL
      and doc["env"].get("BASELINE_TEST_PASSWORD") == PASSWORD,
      "BASELINE_TEST_EMAIL was %r" % doc.get("env", {}).get("BASELINE_TEST_EMAIL"))
check("resolved: a plain value is untouched and the order is sorted",
      doc.get("env", {}).get("PLAIN") == "kept" and list(doc.get("env", {})) == sorted(ENV), "env keys %s" % list(doc.get("env", {})))
check("resolved: no error", errors == [], "errors %r" % errors)
check("resolved: the file is 0600", mode_of(p) == 0o600, "mode was %s" % oct(mode_of(p)))
check("resolved, apply: the summary counts them", ", env 3 (2 from secrets)" in (line or ""), "the line was %r" % line)
check("resolved, apply: no resolved value in the output", not leaks(line or "", printed), "leaked %r" % leaks(line or "", printed))

# 2. Again: already current, still 0600, no change.
before = open(slp(p), "rb").read()
line, errors, printed = run(p)
check("again: already current, byte-identical", "already current" in (line or "") and open(slp(p), "rb").read() == before,
      "the line was %r" % line)

# 3. Content current but the file loose (Claude Code rewrote it, or an earlier run): corrected, not skipped.
os.chmod(slp(p), 0o644)
line, errors, printed = run(p, DRY)
check("already current but loose, dry run: says it would chmod, mode untouched",
      "would chmod 600" in (line or "") and mode_of(p) == 0o644, "line %r, mode %s" % (line, oct(mode_of(p))))
line, errors, printed = run(p)
check("already current but loose: chmod 600", mode_of(p) == 0o600, "the file stayed %s (%r)" % (oct(mode_of(p)), line))
check("already current but loose: content unchanged", open(slp(p), "rb").read() == before, "content changed")

# 4. A name the secrets lack: a `!`-able error, the key not written, the others are.
p = project()
line, errors, printed = run(p, secrets={"BASELINE_TEST_EMAIL": EMAIL})
doc = json.load(open(slp(p)))
check("missing: the key is not written", "BASELINE_TEST_PASSWORD" not in doc.get("env", {}),
      "BASELINE_TEST_PASSWORD was %r" % doc.get("env", {}).get("BASELINE_TEST_PASSWORD"))
check("missing: one error naming the secret", len(errors) == 1 and "BASELINE_TEST_PASSWORD" in errors[0], "errors %r" % errors)
check("missing: the others are written", doc.get("env", {}).get("BASELINE_TEST_EMAIL") == EMAIL
      and doc["env"].get("PLAIN") == "kept", "env %r" % sorted(doc.get("env", {})))
check("missing: an empty value is missing too", run(project(), secrets={"BASELINE_TEST_EMAIL": EMAIL, "BASELINE_TEST_PASSWORD": ""})[1] != [],
      "no error for an empty secret")

# 5. No resolved value: the file keeps the mode it has, or the umask's for a new one; the summary has no count.
p = project(0o644, {"permissions": {"allow": ["Edit"]}})
line, errors, printed = run(p, env={"PLAIN": "kept"})
check("no secret resolved: the mode is kept", mode_of(p) == 0o644, "mode was %s" % oct(mode_of(p)))
check("no secret resolved: no 'from secrets' in the line", "from secrets" not in (line or "") and ", env 1" in (line or ""),
      "the line was %r" % line)
p = project()
run(p, env={"PLAIN": "kept"})
umask = os.umask(0)
os.umask(umask)
check("no secret resolved, new file: the umask's mode, not forced to 0600", mode_of(p) == 0o666 & ~umask,
      "mode was %s, umask %s" % (oct(mode_of(p)), oct(umask)))

# 6. Through the generator: the `!` line, exit 1, the closing line; and a clean run exits 0 with nothing printed.
BANG = re.compile(r"(?m)^\s*!")


def sync_run(name, secrets_doc, apply=True):
    base = os.path.join(TOY, name)
    cfg, pdir, proj = (os.path.join(base, "config"), os.path.join(base, "config", "profiles"), os.path.join(base, "toy"))
    os.makedirs(pdir)
    os.makedirs(proj)
    with open(os.path.join(cfg, "mcp-registry.json"), "w") as f:
        f.write('{"servers": {}}')
    with open(os.path.join(base, "secrets.json"), "w") as f:
        json.dump(secrets_doc, f)
    os.symlink(os.path.join(base, "secrets.json"), os.path.join(cfg, "secrets.json"))
    with open(os.path.join(cfg, "project-relocations.json"), "w") as f:
        f.write('{"relocations": []}')
    with open(os.path.join(pdir, "toy.claude.json"), "w") as f:
        json.dump({"project": "toy", "project_path": proj, "servers": [], "env": ENV}, f)
    sync.CFG, lib.PROFILES = cfg, pdir
    if not (os.path.realpath(proj).startswith(TOY + os.sep) and lib.PROFILES.startswith(TOY + os.sep)):
        sys.exit("FENCE: the toy profile is outside the toy world -- nothing run")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sync.agent_config(["--apply"] if apply else [])
    return code, out.getvalue() + err.getvalue(), proj


# agent_config builds its Ctx with lib.context(argv); the toy world must be the whole scope, not a write to ~.
real_context = lib.context
lib.context = lambda argv: lib.Ctx(bool(argv), {"toy"}, False)
code, out, proj = sync_run("sync-missing", {"BASELINE_TEST_EMAIL": EMAIL})
check("missing: sync exits 1 with a `!` line naming the secret",
      code == 1 and any(l.lstrip().startswith("!") and "BASELINE_TEST_PASSWORD" in l for l in out.splitlines()),
      "exit %r, '!' lines %r" % (code, [l for l in out.splitlines() if l.lstrip().startswith("!")]))
check("missing: sync prints no resolved value", not leaks(out), "leaked %r" % leaks(out))
check("missing: sync did not write the key", "BASELINE_TEST_PASSWORD" not in json.load(open(slp(proj))).get("env", {}), "the key is in the file")
code, out, proj = sync_run("sync-ok", SECRETS)
check("resolved: sync exits 0, no '!' line", code == 0 and not BANG.search(out), "exit %r" % code)
check("resolved: sync wrote the secrets, 0600", json.load(open(slp(proj))).get("env", {}).get("BASELINE_TEST_PASSWORD") == PASSWORD
      and mode_of(proj) == 0o600, "env %r, mode %s" % (sorted(json.load(open(slp(proj))).get("env", {})), oct(mode_of(proj))))
check("resolved: sync prints no resolved value, and counts them", not leaks(out) and "env 3 (2 from secrets)" in out,
      "leaked %r, counted %s" % (leaks(out), "env 3 (2 from secrets)" in out))
# Codex reads the same profile `env`: its config.toml (already 0600, git-ignored, holding resolved MCP
# secrets) must hold the value, never the literal ${NAME} text, and the missing key is left out.
cx = os.path.join(proj, ".codex", "config.toml")
toml = open(cx).read() if os.path.exists(cx) else ""
check("resolved: codex config.toml holds the secrets, no literal ${NAME}",
      PASSWORD in toml and EMAIL in toml and "${" not in toml, "exists %s, literal ${ %s" % (bool(toml), "${" in toml))
code, out, proj = sync_run("sync-missing-codex", {"BASELINE_TEST_EMAIL": EMAIL})
cx = os.path.join(proj, ".codex", "config.toml")
toml = open(cx).read() if os.path.exists(cx) else ""
check("missing: codex config.toml has no literal ${NAME} and no password key",
      bool(toml) and "${" not in toml and "BASELINE_TEST_PASSWORD" not in toml, "exists %s, literal %s" % (bool(toml), "${" in toml))
check("missing: the `!` line is printed once", sum("BASELINE_TEST_PASSWORD" in l for l in out.splitlines() if l.lstrip().startswith("!")) == 1,
      "'!' lines %r" % [l for l in out.splitlines() if l.lstrip().startswith("!")])
code, out, proj = sync_run("sync-dry", SECRETS, apply=False)
check("resolved, sync dry-run: no resolved value, counted, nothing written", not leaks(out) and "env 3 (2 from secrets)" in out
      and not os.path.exists(slp(proj)), "leaked %r, file %s" % (leaks(out), os.path.exists(slp(proj))))
lib.context = real_context

sandbox.cleanup(bool(failures))
if failures:
    print("%d of %d checks failed" % (len(failures), n_cases))
    sys.exit(1)
print("ok: %d checks over %d toy projects" % (n_cases, n_proj))
