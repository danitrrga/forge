#!/usr/bin/env python3
"""`forge shim` (forge/shim.py): prints a shell function named `claude`, so that `claude @NAME` starts a session of that
profile (`forge start @NAME ...`) while every other `claude` stays what it is. `forge shim --check @NAME` is the probe the
function calls, only when its first argument starts with `@`: exit 0 when NAME is the default label or an offered profile of
the directory's project, 1 in every other case, and never a byte of output.

Why the function takes `@x` only when the probe says so: `claude @notes.md` is a prompt today (the binary reads `@name` as a
file mention, framework-discuss/research/profile-daily-measures.md part 2), and a plain `claude` must not pay the probe (about
33 ms, 80 % of it the import of forge/cli.py), so it never calls forge.

The world is a toy (test_profiles.World: an engine copy, a toy HOME, the projects `multi` with profiles `toy-b` and `list` and
the default label `code`, `none` without `profiles`, `frozen-p`, `bad`). The shell cases load the function that the copy's
`forge shim` prints into `fish --no-config -c`, `zsh -f -c` and `bash --norc -c`, with a fake `claude` and a fake `forge` alone
on PATH (ORDERS 10; `git` and `python3` are linked in beside them, the engine's probe needs git). The fake `forge` logs its
arguments and hands `shim` to the copy's real bin/forge, so the probe is the real one; the fake `claude` logs its arguments and
FORGE_PROFILE. Arguments reach the shell as positional parameters, never inside script text, so spaces, quotes, a leading dash,
`$HOME`, `*` and an empty argument arrive as the test wrote them.

Controls, each a mutation of the printed function, seen failing once in every shell (the message each produced is below):
  always wraps         `claude` is `forge start "$@"`          -> "wrapped a project without profiles"
  takes any @x         the probe taken out                      -> "file mention taken for a profile"
  probes on every one  the `@` guard taken out                  -> "probed without @"
  splits arguments     `forge start "$@"` without its quotes    -> "odd arguments after a profile: forge got ..."
The shell that is not installed prints `NOT RUN, NOT ARMED: <shell> not found` and the test exits 77; the test runs itself
once with an empty search path to see that (control of that line).

Written first and run against the code that had no `shim` subcommand: 65 FAIL lines, the first "FAIL cli: forge shim --shell fish
is exit 0 -- exit 2, stderr 'usage: forge [-h] {sync,skills,...} ... forge: error: argument cmd: invalid choice: 'shim'", then in
each shell "FAIL bash: the function behaves -- profile starts: forge got [], claude got [['@toy-b', '--resume', 'x']]; want
[['shim', '--check', '@toy-b'], ['start', '@toy-b', '--resume', 'x']] and []" (the plain-claude cases passed there, by reaching the
fake claude with no function at all), "FAIL bash: a profile start returns forge start's exit status -- exit 0, want 7" and "FAIL bash:
end to end, the real forge start reaches claude with the profile -- exit 0, calls [{'tool': 'claude', 'argv': ['@toy-b', '--resume',
'x'], 'profile': None}]". The NOT RUN check passed there, as it should: it does not depend on the subcommand. Its control: the same
child run with the real search path exits 0 and prints no NOT RUN line, which the parent's check would call a FAIL.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
from test_profiles import World  # noqa: E402

SHELLS = ("fish", "zsh", "bash")
failures = []
not_run = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, detail))


def locate(shell, search_path):
    """The absolute path of `shell` on `search_path`, or None."""
    return shutil.which(shell, path=search_path)


# ---------------------------------------------------------------------------------------------------- the engine, the CLI

def forge_run(w, args, cwd, env=None):
    """(exit code, stdout, stderr) of the copy's bin/forge `args` from `cwd`, with only the toy HOME's environment."""
    e = sandbox.bare_env(w.home, w.root)
    e.update(env or {})
    for k in [k for k, v in e.items() if v is None]:
        del e[k]
    r = subprocess.run([sys.executable, os.path.join(w.forge, "bin", "forge")] + list(args), cwd=cwd, env=e,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode, r.stdout, r.stderr


def cli_cases(w):
    here = w.pp("multi")
    for shell in SHELLS:
        rc, out, err = forge_run(w, ["shim", "--shell", shell], here)
        check("cli: forge shim --shell %s is exit 0" % shell, rc == 0 and err == "", "exit %s, stderr %r" % (rc, err[:200]))
        check("cli: forge shim --shell %s prints a function named claude" % shell,
              rc == 0 and "claude" in out and "forge start" in out and "command claude" in out, "stdout %r" % out[:200])
    rc, out, err = forge_run(w, ["shim", "--shell", "csh"], here)
    check("cli: --shell csh is exit 2", rc == 2 and out == "", "exit %s, stdout %r" % (rc, out[:100]))
    check("cli: --shell csh lists the three", all(s in err for s in SHELLS), "stderr %r" % err[:300])

    for shell in SHELLS:  # no --shell: from $SHELL, and it says which
        rc, out, err = forge_run(w, ["shim"], here, {"SHELL": "/usr/bin/" + shell})
        want = forge_run(w, ["shim", "--shell", shell], here)[1]
        check("cli: no --shell with SHELL=%s prints that shell's function" % shell, rc == 0 and out == want and out != "",
              "exit %s, same as --shell: %s, stderr %r" % (rc, out == want, err[:200]))
        check("cli: no --shell with SHELL=%s says which on stderr" % shell, shell in err and "$SHELL" in err, "stderr %r" % err)
    for label, env in (("SHELL=/bin/dash", {"SHELL": "/bin/dash"}), ("SHELL unset", {"SHELL": None})):
        rc, out, err = forge_run(w, ["shim"], here, env)
        check("cli: no --shell with %s is exit 2 and lists the three" % label, rc == 2 and out == "" and all(s in err for s in SHELLS),
              "exit %s, stdout %r, stderr %r" % (rc, out[:100], err[:300]))

    # the probe: exit 0 for the default label and an offered profile of the directory's project, 1 otherwise, never any output
    outside = os.path.join(w.root, "outside")
    os.makedirs(outside, exist_ok=True)
    probes = [("an offered profile", here, "@toy-b", 0), ("a profile named like a command", here, "@list", 0),
              ("the default label", here, "@code", 0), ("a name the project does not offer", here, "@notes.md", 1),
              ("a bare @", here, "@", 1), ("no @", here, "toy-b", 1), ("a name with a dash first", here, "@-x", 1),
              ("a project without profiles", w.pp("none"), "@toy-b", 1), ("a frozen project", w.pp("frozen-p"), "@list", 1),
              ("a project whose file is malformed", w.pp("bad"), "@toy-b", 1), ("a folder outside every project", outside, "@toy-b", 1)]
    for label, cwd, arg, want_rc in probes:
        rc, out, err = forge_run(w, ["shim", "--check", arg], cwd)
        check("cli: --check %s (%s) is exit %d" % (arg, label, want_rc), rc == want_rc, "exit %s, stderr %r" % (rc, err[:200]))
        check("cli: --check %s (%s) prints nothing" % (arg, label), out == "" and err == "", "stdout %r, stderr %r" % (out[:100], err[:200]))
    rc, out, err = forge_run(w, ["shim", "--check", "@toy-b", "--shell", "fish"], here)
    check("cli: --check with --shell is exit 2", rc == 2, "exit %s" % rc)
    rc, out, err = forge_run(w, ["shim", "--check"], here)
    check("cli: --check with no name is exit 2 and prints no function", rc == 2 and out == "", "exit %s, stdout %r" % (rc, out[:100]))


# ----------------------------------------------------------------------------------------------------- the shell cases

FAKE_CLAUDE = """#!%(py)s
import json, os, sys
with open(os.environ["SHIM_LOG"], "a") as fh:
    fh.write(json.dumps({"tool": "claude", "argv": sys.argv[1:], "profile": os.environ.get("FORGE_PROFILE")}) + "\\n")
sys.exit(int(os.environ.get("FAKE_CLAUDE_RC", "0")))
"""
# `shim` (and what FAKE_FORGE_REAL lists) is handed to the copy's real forge, so the probe is the real one; the rest is logged only.
FAKE_FORGE = """#!%(py)s
import json, os, sys
with open(os.environ["SHIM_LOG"], "a") as fh:
    fh.write(json.dumps({"tool": "forge", "argv": sys.argv[1:]}) + "\\n")
if sys.argv[1:2] and sys.argv[1] in ("shim",) + tuple(os.environ.get("FAKE_FORGE_REAL", "").split(",")):
    os.execv(%(py)r, [%(py)r, %(real)r] + sys.argv[1:])
sys.exit(int(os.environ.get("FAKE_FORGE_RC", "0")))
"""


def make_fakes(tmp, w):
    """A directory holding only the fake claude, the fake forge, and python3 and git (linked): the whole PATH of a shell case."""
    bin_dir = os.path.join(tmp, "fakebin")
    os.makedirs(bin_dir)
    for name, body in (("claude", FAKE_CLAUDE), ("forge", FAKE_FORGE)):
        p = os.path.join(bin_dir, name)
        with open(p, "w") as fh:
            fh.write(body % {"py": sys.executable, "real": os.path.join(w.forge, "bin", "forge")})
        os.chmod(p, 0o755)
    for name in ("python3", "git"):
        target = sys.executable if name == "python3" else shutil.which("git")
        os.symlink(target, os.path.join(bin_dir, name))
    return bin_dir


def argv_of(shell_path, shell, funcfile, args):
    """The command line of one case: the function file is sourced, then `claude` gets `args` as positional parameters."""
    if shell == "fish":
        return [shell_path, "--no-config", "-c", "source $argv[1]; claude $argv[2..-1]", funcfile] + list(args)
    flags = ["-f"] if shell == "zsh" else ["--norc", "--noprofile"]
    return [shell_path, *flags, "-c", '. "$1"; shift; claude "$@"', shell, funcfile] + list(args)


def run_case(w, tmp, bin_dir, shell_path, shell, funcfile, cwd, args, extra_env=None):
    """(shell exit code, [(tool, argv, profile)] the fakes logged, stderr)."""
    log = os.path.join(tmp, "calls.jsonl")
    if os.path.exists(log):
        os.remove(log)
    env = sandbox.bare_env(w.home, w.root, PATH=bin_dir, SHIM_LOG=log, **(extra_env or {}))
    r = subprocess.run(argv_of(shell_path, shell, funcfile, args), cwd=cwd, env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    calls = []
    if os.path.exists(log):
        with open(log) as fh:
            calls = [json.loads(line) for line in fh]
    return r.returncode, calls, r.stderr


def probe(arg):
    return {"tool": "forge", "argv": ["shim", "--check", arg]}


ODD = ["a b", "it's", '"q"', "-n", "--model", "x y", "$HOME", "*", "", "--", "\\n"]


def cases(w):
    """(label, kind, cwd, args, expected forge argv list, expected claude argv list, control): `kind` names the failure a
    wrong call is: a `start` where none belongs, or any forge call on a plain claude."""
    here, none = w.pp("multi"), w.pp("none")
    outside = os.path.join(w.root, "outside")
    os.makedirs(outside, exist_ok=True)
    return [
        ("profile starts", "generic", here, ["@toy-b", "--resume", "x"],
         [["shim", "--check", "@toy-b"], ["start", "@toy-b", "--resume", "x"]], [], True),
        ("the default label starts", "generic", here, ["@code"], [["shim", "--check", "@code"], ["start", "@code"]], [], False),
        ("a file mention is not a profile", "file mention taken for a profile", here, ["@notes.md", "more"],
         [["shim", "--check", "@notes.md"]], [["@notes.md", "more"]], True),
        ("a project without profiles", "wrapped a project without profiles", none, ["@toy-b"],
         [["shim", "--check", "@toy-b"]], [["@toy-b"]], True),
        ("a folder outside every project", "wrapped a project without profiles", outside, ["@toy-b"],
         [["shim", "--check", "@toy-b"]], [["@toy-b"]], False),
        ("plain claude with an option", "probed without @", here, ["--resume", "x"], [], [["--resume", "x"]], True),
        ("plain claude, no argument", "probed without @", here, [], [], [[]], False),
        ("-p before an @", "probed without @", here, ["-p", "@toy-b"], [], [["-p", "@toy-b"]], False),
        ("a bare @ is plain", "probed without @", here, ["@"], [], [["@"]], False),
        ("odd arguments after a profile", "generic", here, ["@toy-b"] + ODD,
         [["shim", "--check", "@toy-b"], ["start", "@toy-b"] + ODD], [], True),
        ("odd arguments, plain", "probed without @", here, ["a b", "-x"] + ODD, [], [["a b", "-x"] + ODD], False),
        ("odd arguments after a file mention", "file mention taken for a profile", here, ["@notes.md"] + ODD,
         [["shim", "--check", "@notes.md"]], [["@notes.md"] + ODD], False),
    ]


def judge(label, kind, calls, want_forge, want_claude):
    """The failure messages of one case: the control's own text first when the wrong call is the one it names."""
    forge = [c["argv"] for c in calls if c["tool"] == "forge"]
    claude = [c["argv"] for c in calls if c["tool"] == "claude"]
    out = []
    if kind in ("wrapped a project without profiles", "file mention taken for a profile") and any(a[:1] == ["start"] for a in forge):
        out.append("%s: %s (%s)" % (kind, label, forge))
    if kind == "probed without @" and forge:
        out.append("%s: %s (forge got %s)" % (kind, label, forge))
    if not out and (forge != want_forge or claude != want_claude):
        out.append("%s: forge got %r, claude got %r; want %r and %r" % (label, forge, claude, want_forge, want_claude))
    return out


def run_cases(w, tmp, bin_dir, shell_path, shell, funcfile, only_controls=False):
    messages = []
    for label, kind, cwd, args, want_forge, want_claude, control in cases(w):
        if only_controls and not control:
            continue
        rc, calls, err = run_case(w, tmp, bin_dir, shell_path, shell, funcfile, cwd, args)
        got = judge(label, kind, calls, want_forge, want_claude)
        if not got and rc != 0:
            got = ["%s: exit %s, stderr %r" % (label, rc, err[:200])]
        messages += got
    return messages


def status_cases(w, tmp, bin_dir, shell_path, shell, funcfile):
    """The exit status of the function is the one of whatever it ran."""
    here = w.pp("multi")
    rc = run_case(w, tmp, bin_dir, shell_path, shell, funcfile, here, ["x"], {"FAKE_CLAUDE_RC": "3"})[0]
    check("%s: plain claude returns claude's exit status" % shell, rc == 3, "exit %s, want 3" % rc)
    rc = run_case(w, tmp, bin_dir, shell_path, shell, funcfile, here, ["@toy-b"], {"FAKE_FORGE_RC": "7"})[0]
    check("%s: a profile start returns forge start's exit status" % shell, rc == 7, "exit %s, want 7" % rc)
    rc = run_case(w, tmp, bin_dir, shell_path, shell, funcfile, w.pp("none"), ["@toy-b"], {"FAKE_CLAUDE_RC": "5", "FAKE_FORGE_RC": "7"})[0]
    check("%s: a file mention returns claude's exit status, not forge's" % shell, rc == 5, "exit %s, want 5" % rc)


def end_to_end(w, tmp, bin_dir, shell_path, shell, funcfile):
    """`claude @toy-b --resume x` through the real `forge start`: the fake claude is reached with the profile's flags and FORGE_PROFILE."""
    rc, calls, err = run_case(w, tmp, bin_dir, shell_path, shell, funcfile, w.pp("multi"), ["@toy-b", "--resume", "x"],
                              {"FAKE_FORGE_REAL": "start"})
    reached = [c for c in calls if c["tool"] == "claude"]
    check("%s: end to end, the real forge start reaches claude with the profile" % shell,
          rc == 0 and len(reached) == 1 and reached[0]["profile"] == "toy-b" and reached[0]["argv"][-2:] == ["--resume", "x"]
          and "--settings" in reached[0]["argv"], "exit %s, calls %r, stderr %r" % (rc, calls, err[:300]))


def mutants(text, shell):
    """(control name, the failure it must produce, the mutated function text): each a change of the printed function, its anchor
    asserted to be there once."""
    def sub(old, new):
        assert text.count(old) == 1, "the control's anchor %r is not once in the %s function" % (old, shell)
        return text.replace(old, new)
    if shell == "fish":
        return [("always wraps", "wrapped a project without profiles", "function claude\n    forge start $argv\nend\n"),
                ("takes any @x", "file mention taken for a profile", sub('\n        and forge shim --check "$argv[1]" 2>/dev/null', "")),
                ("probes on every claude", "probed without @", sub("string match -qr -- '^@.' -- \"$argv[1]\"", "true")),
                ("joins the arguments into one", "odd arguments after a profile", sub("forge start $argv", 'forge start "$argv"'))]
    return [("always wraps", "wrapped a project without profiles", 'claude() {\n    forge start "$@"\n}\n'),
            ("takes any @x", "file mention taken for a profile", sub('forge shim --check "$1" 2>/dev/null && ', "")),
            ("probes on every claude", "probed without @", sub("@?*)", "*)")),
            ("splits the arguments again", "odd arguments after a profile", sub('forge start "$@"', "forge start $@"))]


def shell_cases(w, found):
    tmp = sandbox.mkdtemp("shim-")
    bin_dir = make_fakes(tmp, w)
    for shell, shell_path in found.items():
        rc, text, err = forge_run(w, ["shim", "--shell", shell], w.pp("multi"))
        funcfile = os.path.join(tmp, "claude-%s.txt" % shell)
        with open(funcfile, "w") as fh:
            fh.write(text)
        for msg in run_cases(w, tmp, bin_dir, shell_path, shell, funcfile):
            check("%s: the function behaves" % shell, False, msg)
        status_cases(w, tmp, bin_dir, shell_path, shell, funcfile)
        end_to_end(w, tmp, bin_dir, shell_path, shell, funcfile)
        if not text:
            continue  # nothing to mutate: the cases above already failed
        for name, expected, mutated in mutants(text, shell):
            mfile = os.path.join(tmp, "mutant-%s.txt" % shell)
            with open(mfile, "w") as fh:
                fh.write(mutated)
            got = run_cases(w, tmp, bin_dir, shell_path, shell, mfile, only_controls=True)
            check("%s: control '%s' is seen failing with '%s'" % (shell, name, expected), any(g.startswith(expected) for g in got),
                  "it produced %r" % got[:3])
            if any(g.startswith(expected) for g in got):
                print("control %s / %s: FAIL %s" % (shell, name, next(g for g in got if g.startswith(expected))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-path", default=os.environ.get("PATH", os.defpath), help="where the shells are looked for (the not-run control passes an empty folder)")
    ap.add_argument("--no-cli", action="store_true", help="only look for the shells (the not-run control)")
    a = ap.parse_args()
    found = {}
    for shell in SHELLS:
        p = locate(shell, a.search_path)
        if p:
            found[shell] = p
        else:
            not_run.append(shell)
            print("NOT RUN, NOT ARMED: %s not found" % shell)
    if not a.no_cli:
        w = World(["multi", "none", "frozen-p", "bad"])
        before = w.files("")
        cli_cases(w)
        check("printing the function and probing write no file of the world", w.files("") == before, "the world changed")
        shell_cases(w, found)  # after the snapshot: the end-to-end case runs the real `forge start`, which writes its session files
        # control of the NOT RUN line: this test, run with an empty search path, finds no shell, says so and exits 77.
        empty = sandbox.mkdtemp("shim-empty-")
        r = subprocess.run([sys.executable, os.path.realpath(__file__), "--no-cli", "--search-path", empty], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        check("an absent shell exits 77 and says NOT RUN, NOT ARMED", r.returncode == 77 and all(
            "NOT RUN, NOT ARMED: %s not found" % s in r.stdout for s in SHELLS), "exit %s, stdout %r" % (r.returncode, r.stdout[:300]))
    sandbox.cleanup(bool(failures))
    if failures:
        print("%d FAIL" % len(failures))
        return 1
    if not_run:
        print("NOT RUN, NOT ARMED: %s (exit 77)" % ", ".join(not_run))
        return 77
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
