"""forge launch NAME [ARGS...]: claude started with the environment a named launcher declares in config/forge.json
(`launchers`: {name: {"env": {VAR: value}}}). The process is replaced (os.execvpe), so the terminal that ran it holds
claude and nothing of forge stays behind."""
import os
import shutil
import sys

from forge import lib


def _launchers(doc):
    """The validated `launchers` table, or the message of the first thing wrong, naming its key."""
    table = doc.get("launchers", {})
    if not isinstance(table, dict):
        return None, "launchers is %s, not an object" % type(table).__name__
    for name, launcher in table.items():
        if not isinstance(launcher, dict):
            return None, "launchers.%s is %s, not an object" % (name, type(launcher).__name__)
        for key in launcher:
            if key != "env":
                return None, "launchers.%s.%s: only env is known" % (name, key)
        env = launcher.get("env", {})
        if not isinstance(env, dict):
            return None, "launchers.%s.env is %s, not an object" % (name, type(env).__name__)
        for var, value in env.items():
            if not var or "=" in var or "\0" in var:
                return None, "launchers.%s.env: %r is not a variable name" % (name, var)
            if not isinstance(value, str) or "\0" in value:
                return None, "launchers.%s.env.%s is not a string" % (name, var)
    return table, None


def cmd(a):
    table, bad = _launchers(lib.settings())
    if bad:
        print("! forge launch: %s" % bad, file=sys.stderr)
        return 2
    if not a.name:
        if not table:
            print("no launchers (add one under `launchers` in config/forge.json)")
        for name, launcher in sorted(table.items()):
            print("%s  %s" % (name, " ".join(sorted(launcher.get("env", {}))) or "(no env)"))
        return 0
    if a.name not in table:
        print("! forge launch: unknown launcher %r (known: %s)" % (a.name, ", ".join(sorted(table)) or "none"),
              file=sys.stderr)
        return 2
    env = dict(os.environ, **table[a.name].get("env", {}))
    claude = shutil.which("claude", path=env.get("PATH", os.defpath))
    if not claude:
        print("! forge launch: claude is not on PATH", file=sys.stderr)
        return 127
    sys.stdout.flush()
    os.execvpe(claude, ["claude"] + a.args, env)
