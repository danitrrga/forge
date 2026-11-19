#!/usr/bin/env python3
"""How the owner learns forge's commands (4.4 U3c): the "examples" of each --help, the suggestion for a misspelled name, and
`forge completion fish|zsh|bash`, which completes live by calling `forge`.

Cases:
  a  every `forge ...` line of every "examples:" section in `forge SUB --help` goes through the real parser (cli.build_parser), without
     running anything, and is accepted; `config`, `list`, `switch`, `new`, `start` and `run` must have such a section. The checker is
     seen rejecting a line with a flag that does not exist: `example rejected: <line>`.
  b  an unknown project, profile, skill and server each exit 2 and name the closest one and the list (forge/suggest.py), through
     list, config, start and run; a message with no suggestion is `no suggestion in: <message>`.
  c  per shell, a fake `forge` on a PATH that holds only the fake directory, the printed script is loaded and asked for candidates
     after `forge config `, `forge switch @` and `claude @` (and a few more): fish with `complete -C`, bash by calling the function
     `complete -p` registered with COMP_WORDS, zsh by calling the function `compdef` was given with `words`, CURRENT and a `compadd`
     that records. Zero candidates is a failure, `no candidates for: forge config `; the fake logs its argv, so a script that
     hard-codes names instead of asking `forge` is a failure too. The real `claude`'s own completion is stood in for by a fake and
     must still answer for anything that does not start with `@`.
  d  `forge config --names` (the values of --on and --off: TYPE:NAME, one per line) lists skills, sets, servers and options and
     writes nothing.

A shell that is not installed prints `NOT RUN, NOT ARMED: <shell> not found`; the test then exits 77, as test_shim.py does, and this
test runs itself with an empty search path to prove the line (its control).

Written first, run against fe9246a (no `completion`, no `build_parser`, no `config --names`): see the commit message for the FAILs.
"""
import argparse
import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SHELLS = ("fish", "zsh", "bash")
REQUIRED = ("config", "list", "switch", "new", "start", "run")
failures = []
not_run = []


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, detail))


# ------------------------------------------------------------------------------------------------------------ a: the examples

def examples_of(help_text):
    """The `forge ...` command lines of the "examples:" section of a help text; None when it has no such section. A redirection, a
    pipe and a trailing comment end the command."""
    lines = help_text.splitlines()
    if "examples:" not in lines:
        return None
    out = []
    for line in lines[lines.index("examples:") + 1:]:
        if not line.startswith(" "):
            break
        if line.strip().startswith("forge "):
            words = shlex.split(line, comments=True)
            for i, w in enumerate(words):
                if w[:1] in ("<", ">", "|"):
                    words = words[:i]
                    break
            out.append(words)
    return out


def rejected(parser, commands):
    """`example rejected: <line>` for each command the parser does not accept (argparse exits 2 on a flag it does not know)."""
    bad = []
    for words in commands:
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(words[1:])
            except SystemExit:
                bad.append("example rejected: %s" % " ".join(words))
    return bad


def subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def case_a(w):
    from forge import cli
    parser = cli.build_parser()
    subs = subparsers(parser)
    check("a: the parser has subcommands to look at", len(subs) > 10, "found %d" % len(subs))
    seen = 0
    for name, sub in subs.items():
        found = examples_of(sub.format_help())
        if name in REQUIRED:
            check("a: forge %s --help has an examples section" % name, bool(found), "no `examples:` section with forge lines")
        for line in rejected(parser, found or []):
            check("a: %s" % line, False, "in the help of forge %s" % name)
        seen += len(found or [])
    check("a: the examples that were looked at are not zero", seen >= 12, "looked at %d" % seen)
    # the real `--help`, run as the owner runs it, says the same
    code, out, err = w.forge_cmd(["config", "--help"])
    check("a: forge config --help prints its examples", code == 0 and "forge config" in "".join(
        " ".join(x) for x in examples_of(out) or []), (code, out[-300:], err))
    # control: a line with a flag that does not exist is rejected, and its message is the one the brief names
    bad = rejected(parser, [["forge", "config", "myapp", "--offf", "skill:x"]])
    check("a: control: an example with a flag that does not exist is rejected", bad == ["example rejected: forge config myapp --offf skill:x"], bad)
    check("a: control: a good line is accepted", rejected(parser, [["forge", "config", "myapp", "--off", "skill:x"]]) == [], "rejected")


# ------------------------------------------------------------------------------------------------------------ b: suggestions

def case_b(w):
    multi, root = w.pp("multi"), w.root
    asks = [("project", "multi", root, ["list", "multy"]), ("project", "multi", root, ["config", "multy", "--off", "skill:toy-a"]),
            ("profile", "toy-b", multi, ["list", "@toy-bb"]), ("profile", "toy-b", multi, ["config", "multi", "@toy-bb", "--off", "skill:toy-a"]),
            ("profile", "toy-b", multi, ["start", "@toy-bb", "--dry-run"]), ("profile", "toy-b", multi, ["run", "@toy-bb", "hello"]),
            ("skill", "toy-common", root, ["config", "plain", "--off", "skill:toy-comon"]),
            ("server", "toy-echo", root, ["config", "plain", "--on", "server:toy-ech"])]
    for kind, near, cwd, args in asks:
        code, out, err = w.forge_cmd(args, cwd=cwd)
        label = "b: forge %s" % " ".join(args)
        check(label + " exits 2", code == 2, "exit %d, stderr %r" % (code, err))
        # control: a message with no suggestion is `no suggestion in: <message>`
        check(label + " names the closest %s" % kind, "did you mean '%s'" % near in err or "did you mean '@%s'" % near in err,
              "no suggestion in: %s" % err.strip())
        check(label + " lists those that exist", "There are:" in err, "no list in: %s" % err.strip())


# ------------------------------------------------------------------------------------------------------------ d: the values

def case_d(w):
    before = w.tree()
    code, out, err = w.forge_cmd(["config", "--names"], cwd=w.pp("plain"))
    got = out.split()
    check("d: forge config --names is exit 0", code == 0, (code, out, err))
    for want in ("skill:toy-a", "skill:toy-common", "set:TOYSET", "server:toy-echo", "server:toy-two", "option:ui", "option:command_guard",
                 "option:enableAllProjectMcpServers"):
        check("d: forge config --names lists %s" % want, want in got, "got %s" % got)
    check("d: every line is TYPE:NAME", got and all(":" in g and g.split(":")[0] in ("skill", "set", "server", "option") for g in got), got)
    check("d: it writes nothing", w.tree() == before, "the world changed")


# ------------------------------------------------------------------------------------------------------------ c: the shells

FAKE_FORGE = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$*" in
    "list --names") printf 'alpha\\nbeta\\n' ;;
    "list @ --names") printf 'code\\nmarketing\\n' ;;
    "config --names") printf 'skill:grilling\\nskill:toy-a\\nset:TOYSET\\nserver:neon\\noption:ui\\n' ;;
    *) exit 2 ;;
esac
"""

DRIVE_BASH = r'''pre=$1; script=$2; cmd=$3; shift 3
[ -n "$pre" ] && . "$pre"
. "$script"
COMP_WORDS=("$@"); COMP_CWORD=$(( $# - 1 )); COMP_LINE="${COMP_WORDS[*]}"; COMP_POINT=${#COMP_LINE}
spec=$(complete -p "$cmd" 2>/dev/null) || { echo "NOT REGISTERED"; exit 3; }
fn=; prev=; for w in $spec; do [ "$prev" = -F ] && fn=$w; prev=$w; done
[ -n "$fn" ] || { echo "NOT REGISTERED"; exit 3; }
COMPREPLY=()
"$fn" "$cmd" "${COMP_WORDS[COMP_CWORD]}" "${COMP_WORDS[COMP_CWORD-1]}"
printf '%s\n' "${COMPREPLY[@]}"
'''

DRIVE_ZSH = r'''pre=$1; script=$2; cmd=$3; shift 3
compdef() { print -r -- "$@" >> "$REGISTER" }
[[ -n $pre ]] && . "$pre"
. "$script"
fn=
[[ -f $REGISTER ]] && for line in ${(f)"$(<$REGISTER)"}; do w=(${=line}); [[ $w[2] == $cmd ]] && fn=$w[1]; done
[[ -n $fn ]] || { print "NOT REGISTERED"; exit 3 }
words=("$@"); CURRENT=$#
compadd() { while (( $# )); do if [[ $1 == -- ]]; then shift; print -rl -- "$@"; return; fi; shift; done }
$fn
'''

PRE = {"fish": "complete -c claude -l model -x -d 'the real completion'\n",
       "bash": "_fake_claude() { COMPREPLY=(--model); }\ncomplete -F _fake_claude claude\n",
       "zsh": "typeset -A _comps\n_comps[claude]=_fake_claude\n_fake_claude() { compadd -- --model }\n"}


class Shells:
    """The fake forge, the drivers and one toy HOME for every shell case."""

    def __init__(self, w, found):
        self.w, self.found = w, found
        self.tmp = sandbox.mkdtemp("discover-")
        self.bin = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.bin)
        self.write(os.path.join(self.bin, "forge"), FAKE_FORGE, 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.register = os.path.join(self.tmp, "register.txt")
        self.empty = os.path.join(self.tmp, "empty")
        self.withfile = os.path.join(self.tmp, "withfile")
        os.makedirs(self.empty)
        os.makedirs(self.withfile)
        self.write(os.path.join(self.withfile, "notes.md"), "x\n")
        self.drive = {"bash": self.write(os.path.join(self.tmp, "drive.bash"), DRIVE_BASH),
                      "zsh": self.write(os.path.join(self.tmp, "drive.zsh"), DRIVE_ZSH)}
        self.pre = {s: self.write(os.path.join(self.tmp, "pre." + s), PRE[s]) for s in SHELLS}

    @staticmethod
    def write(path, text, mode=0o644):
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, mode)
        return path

    def script(self, shell):
        code, out, err = self.w.forge_cmd(["completion", shell])
        check("c: forge completion %s is exit 0 and prints a script" % shell, code == 0 and out.strip() and err == "", (code, out[:100], err[:200]))
        return self.write(os.path.join(self.tmp, "script." + shell), out)

    def candidates(self, shell, script, words, cwd=None, pre=False):
        """What `shell` offers for the command line `words` (the last one is the word being completed, "" when empty)."""
        for p in (self.log, self.register):
            if os.path.exists(p):
                os.remove(p)
        env = sandbox.bare_env(self.w.home, self.tmp, PATH=self.bin, FAKE_LOG=self.log, REGISTER=self.register)
        cmd = words[0]
        if shell == "fish":
            argv = [self.found[shell], "--no-config", "-c", "source $argv[3]; source $argv[1]; complete -C $argv[2]", script, " ".join(words),
                    self.pre[shell] if pre else os.devnull]
        else:
            flags = ["-f"] if shell == "zsh" else ["--norc", "--noprofile"]
            argv = [self.found[shell], *flags, self.drive[shell], self.pre[shell] if pre else "", script, cmd] + list(words)
        r = subprocess.run(argv, cwd=cwd or self.empty, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        got = [x.split("\t")[0] for x in r.stdout.splitlines() if x.strip() and x != "NOT REGISTERED"]
        return got, r

    def asked(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return fh.read().splitlines()


# (words, what the shell must offer, what forge must have been asked); the last word is the one being completed
CASES = [(["forge", "config", ""], {"alpha", "beta"}, ["list --names"]),
         (["forge", "switch", "@"], {"@code", "@marketing"}, ["list @ --names"]),
         (["claude", "@"], {"@code", "@marketing"}, ["list @ --names"]),
         (["forge", "list", "@m"], {"@marketing"}, ["list @ --names"]),
         (["forge", "config", "--off", ""], {"skill:grilling", "skill:toy-a", "set:TOYSET", "server:neon", "option:ui"}, ["config --names"]),
         (["forge", "config", "--on", "s"], {"skill:grilling", "skill:toy-a", "set:TOYSET", "server:neon"}, ["config --names"]),
         (["forge", "start", "@"], {"@code", "@marketing"}, ["list @ --names"]),
         (["forge", "run", "@"], {"@code", "@marketing"}, ["list @ --names"]),
         (["forge", "sync", ""], {"alpha", "beta"}, ["list --names"])]


def problems(shell, sh, script):
    """The failures of one shell with one script: a case that offers nothing is `no candidates for: <line>`."""
    bad = []
    for words, want, asked in CASES:
        if shell == "bash" and words[-2:] == ["--on", "s"]:
            continue  # bash splits the word at the colon: its case is below
        got, r = sh.candidates(shell, script, words)
        line = " ".join(words[:-1]) + " " + words[-1]
        if not got:
            bad.append("no candidates for: %s" % line)
            continue
        if set(got) != want:
            bad.append("wrong candidates for: %s -- got %s, want %s (exit %s, stderr %r)" % (line, sorted(got), sorted(want), r.returncode, r.stderr[:200]))
        if not all(a in sh.asked() for a in asked):
            bad.append("did not ask forge %s for: %s (asked %s)" % (asked, line, sh.asked()))
    return bad


def shell_cases(w, found):
    sh = Shells(w, found)
    # the commands and the flags come from the parser, not from a list in the script
    for shell in found:
        script = sh.script(shell)
        for msg in problems(shell, sh, script):
            check("%s: %s" % (shell, msg.split(" -- ")[0]), False, msg)
        got, r = sh.candidates(shell, script, ["forge", ""])
        check("%s: forge <tab> offers the commands" % shell, {"config", "list", "start", "completion"} <= set(got), "got %s" % got)
        got, r = sh.candidates(shell, script, ["forge", "config", "--"])
        check("%s: forge config -- offers its flags" % shell, {"--on", "--off", "--apply", "--json"} <= set(got), "got %s" % got)
        got, r = sh.candidates(shell, script, ["forge", "shim", "--shell", ""])
        check("%s: forge shim --shell offers its choices" % shell, set(got) == set(SHELLS), "got %s" % got)
        # the colon of TYPE:NAME: bash splits the word there, so it is given as readline gives it
        if shell == "bash":
            got, r = sh.candidates(shell, script, ["forge", "config", "--off", "skill", ":", "g"])
            check("bash: forge config --off skill:g completes what follows the colon", got == ["grilling"], "got %s" % got)
        else:
            got, r = sh.candidates(shell, script, ["forge", "config", "--off", "skill:g"])
            check("%s: forge config --off skill:g completes skill:grilling" % shell, got == ["skill:grilling"], "got %s" % got)
        # the real claude is untouched: its own completion answers for anything that is not an @, and a file is still a file
        got, r = sh.candidates(shell, script, ["claude", "--mo"], pre=True)
        check("%s: claude --mo still gets the real completion" % shell, "--model" in got and not {"@code", "alpha"} & set(got), "got %s" % got)
        got, r = sh.candidates(shell, script, ["claude", "@"], pre=True)
        check("%s: claude @ gets the profiles with the real completion beside it" % shell, {"@code", "@marketing"} <= set(got), "got %s" % got)
        if shell == "fish":
            got, r = sh.candidates(shell, script, ["claude", "no"], cwd=sh.withfile)
            check("fish: claude no still completes a file", "notes.md" in got and "alpha" not in got, "got %s" % got)
        if shell == "bash":
            spec = subprocess.run([found["bash"], "--norc", "--noprofile", "-c", '. "$1"; complete -p claude', "bash", script],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
                                  env=sandbox.bare_env(w.home, sh.tmp, PATH=sh.bin)).stdout
            check("bash: with no completion of its own, claude keeps readline's file completion (-o default)", "-o default" in spec, spec)
        # control: a script that completes nothing is `no candidates for: forge config `
        nothing = sh.write(os.path.join(sh.tmp, "nothing." + shell), "# completes nothing\n")
        bad = problems(shell, sh, nothing)
        check("%s: control: a script that completes nothing is seen failing" % shell, "no candidates for: forge config " in bad, bad[:3])
        check("%s: control: and it fails every case, not only the first" % shell, len(bad) >= len(CASES) - 1, bad)
    # control of the "asked live" check: a script that hard-codes the names offers them without asking
    if "fish" in found:
        hard = sh.write(os.path.join(sh.tmp, "hard.fish"), "complete -c forge -f -a 'alpha beta'\n")
        got, r = sh.candidates("fish", hard, ["forge", "config", ""])
        check("c: control: the fake's log is what tells a hard-coded script from a live one", set(got) == {"alpha", "beta"} and sh.asked() == [],
              (got, sh.asked()))


def completion_cli(w):
    code, out, err = w.forge_cmd(["completion", "csh"])
    check("c: forge completion csh is exit 2 and prints no script", code == 2 and out == "", (code, out[:100], err[:200]))
    from forge import cli, completion
    subs = subparsers(cli.build_parser())
    for name in completion.PROJECT_COMMANDS + completion.PROFILE_COMMANDS:
        check("c: the completion's command %s is one of the parser's" % name, name in subs, "renamed? %s" % sorted(subs))


# ------------------------------------------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-path", default=os.environ.get("PATH", os.defpath), help="where the shells are looked for (the not-run control passes an empty folder)")
    ap.add_argument("--no-world", action="store_true", help="only look for the shells (the not-run control)")
    a = ap.parse_args()
    found = {}
    for shell in SHELLS:
        p = shutil.which(shell, path=a.search_path)
        if p:
            found[shell] = p
        else:
            not_run.append(shell)
            print("NOT RUN, NOT ARMED: %s not found" % shell)
    if not a.no_world:
        from test_configure import World
        w = World()
        for fn, args in ((case_a, (w,)), (case_b, (w,)), (case_d, (w,)), (completion_cli, (w,)), (shell_cases, (w, found))):
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                check("%s ran to its end" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))
        empty = sandbox.mkdtemp("discover-empty-")
        r = subprocess.run([sys.executable, os.path.realpath(__file__), "--no-world", "--search-path", empty], capture_output=True, text=True,
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
    print("test_discover: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
