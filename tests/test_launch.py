#!/usr/bin/env python3
"""`forge start NAME [ARGS...]` (forge/launch.py): claude started with the environment a named launcher declares in
config/forge.json (`launchers`: {name: {"env": {VAR: value}}}), so one kind of session can carry a variable (the
keepwarm switch of an orchestrator) without every session carrying it.

The command was `forge launch` until it was renamed `forge start`; the red below is from when it was written.
Written first and run against the code that did not yet have the subcommand: 24 FAIL lines, the first "FAIL exit of a
launch (the fake exits 0): (2, \"usage: forge [-h] ... forge: error: argument cmd: invalid choice: 'launch'", then "env
reaches claude: CACHE_TAX_AUTOWARM: None, want on" and "claude not on PATH: (exit, says so): (2, False), want (127, True)"
(the cases that expect exit 2 pass by accident there, which is why each also checks the message). Negative control: with
the env merge in forge/launch.py broken (`env = dict(os.environ)`) the run fails "FAIL env reaches claude:
CACHE_TAX_AUTOWARM: None, want on" and "FAIL the other launcher: its variable: None, want x". The mutation is not kept.

The world is a toy: a forge.json under a temp dir that lib.SETTINGS points at (in the child process only), a fake
`claude` that writes its argv and two variables to a file, and a PATH that holds only the fake's directory (ORDERS 10: a
"claude missing" case behind /usr/bin would find the real one). The command runs in a child because it replaces the process.
Cases: the launcher's variable reaches claude; the caller's own variables stay; a variable of another launcher is not
added; every argument after NAME, flags included, arrives untouched and in order; no name lists the launchers (and says
so when there are none); an unknown name is exit 2 naming the known ones; a malformed `launchers` (not an object, a
launcher not an object, `env` not an object, a value that is not a string, a key forge does not know) is exit 2 naming
the key; claude not on PATH is exit 127."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures = []
CHILD = ("import sys; from forge import cli, lib; lib.SETTINGS = sys.argv[1]; sys.exit(cli.main(sys.argv[2:]))")
FAKE = "#!%s\nimport json, os, sys\njson.dump({'argv': sys.argv[1:], 'orq': os.environ.get('CACHE_TAX_AUTOWARM'), " \
       "'other': os.environ.get('OTHER_VAR'), 'kept': os.environ.get('CALLER_VAR')}, open(sys.argv[0] + '.out', 'w'))\n" % sys.executable
LAUNCHERS = {"orq": {"env": {"CACHE_TAX_AUTOWARM": "on"}}, "plain": {"env": {"OTHER_VAR": "x"}},
             "tok": {"env": {"SECRET_VAR": "hunter2"}}}


def want(label, got, expected):
    if got != expected:
        failures.append("%s: %s, want %s" % (label, got, expected))


def launch(tmp, launchers, args, with_claude=True):
    """(exit code, stdout, stderr, what the fake claude recorded or None)."""
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    fake = os.path.join(bin_dir, "claude")
    if with_claude:
        with open(fake, "w") as fh:
            fh.write(FAKE)
        os.chmod(fake, 0o755)
    doc = {"integrations": {}}
    if launchers is not None:
        doc["launchers"] = launchers
    settings = os.path.join(tmp, "forge.json")
    with open(settings, "w") as fh:
        json.dump(doc, fh)
    env = {"PATH": bin_dir, "HOME": tmp, "PYTHONDONTWRITEBYTECODE": "1", "CALLER_VAR": "mine"}
    r = subprocess.run([sys.executable, "-c", CHILD, settings] + args, cwd=sandbox.FORGE, env=env,
                       capture_output=True, text=True, timeout=60)
    out = None
    if os.path.exists(fake + ".out"):
        with open(fake + ".out") as fh:
            out = json.load(fh)
    return r.returncode, r.stdout, r.stderr, out


def main():
    with tempfile.TemporaryDirectory(prefix="forge-launch-") as tmp:
        n = [0]

        def run(*a, **k):
            n[0] += 1
            d = os.path.join(tmp, str(n[0]))
            os.makedirs(d)
            return launch(d, *a, **k)
        code, _, err, out = run(LAUNCHERS, ["start", "orq"])
        want("exit of a launch (the fake exits 0)", (code, err), (0, ""))
        want("env reaches claude: CACHE_TAX_AUTOWARM", out and out["orq"], "on")
        want("the caller's variables stay", out and out["kept"], "mine")
        want("a variable of another launcher is not added", out and out["other"], None)
        code, _, _, out = run(LAUNCHERS, ["start", "plain"])
        want("the other launcher: its variable", out and out["other"], "x")
        want("the other launcher: orq's variable is absent", out and out["orq"], None)
        argv = ["--model", "opus", "-c", "--", "-p", "two words", ""]
        code, _, _, out = run(LAUNCHERS, ["start", "orq"] + argv)
        want("args after NAME arrive untouched", out and out["argv"], argv)
        code, _, _, out = run(LAUNCHERS, ["start", "orq", "--help"])
        want("--help after NAME goes to claude", out and out["argv"], ["--help"])
        code, so, _, out = run(LAUNCHERS, ["start"])
        want("no name lists (exit, claude not run)", (code, out), (0, None))
        want("no name lists: names and env keys", ("orq" in so and "CACHE_TAX_AUTOWARM" in so and "plain" in so
                                                   and "OTHER_VAR" in so), True)
        want("no name lists: the key of a third launcher, never a value", ("SECRET_VAR" in so, "hunter2" in so), (True, False))
        for label, doc in (("none configured", None), ("empty", {})):
            code, so, _, out = run(doc, ["start"])
            want("no name, %s: (exit, says so, claude not run)" % label, (code, "no launchers" in so, out), (0, True, None))
        code, _, err, out = run(LAUNCHERS, ["start", "nope"])
        want("unknown name: (exit, claude not run)", (code, out), (2, None))
        want("unknown name: names the known ones", ("orq" in err and "plain" in err and "nope" in err), True)
        code, _, err, out = run(None, ["start", "orq"])
        want("unknown name with none configured: exit", code, 2)
        bad = (("launchers not an object", ["orq"], "launchers"),
               ("launcher not an object", {"orq": "on"}, "orq"),
               ("env not an object", {"orq": {"env": ["A"]}}, "orq"),
               ("a value that is not a string", {"orq": {"env": {"CACHE_TAX_AUTOWARM": True}}}, "CACHE_TAX_AUTOWARM"),
               ("a key with =", {"orq": {"env": {"A=B": "1"}}}, "A=B"),
               ("a key forge does not know", {"orq": {"envs": {}}}, "envs"))
        for label, launchers, key in bad:
            for args in (["start", "orq"], ["start"]):
                code, _, err, out = run(launchers, args)
                want("malformed (%s), %s: (exit, claude not run, names %r)" % (label, args, key),
                     (code, out, key in err), (2, None, True))
        code, _, err, out = run(LAUNCHERS, ["start", "orq"], with_claude=False)
        want("claude not on PATH: (exit, says so)", (code, "claude" in err and "PATH" in err), (127, True))
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print("ok: launch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
