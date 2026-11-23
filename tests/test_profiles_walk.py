#!/usr/bin/env python3
"""The walk of an ordinary day with session profiles (plan 4.4 U11), live: a toy HOME, a real `tmux`, the real `claude` on haiku.

What a person does, typed into a shell inside tmux (the shell loads the function `forge shim --shell bash` prints, as the
person's rc file does):
  1  `forge new toy --stack generic --profiles a,b --skills @a:toy-a --skills @b:toy-c ... --apply`   (the answers are flags:
     no terminal screen is exercised here), then `cd` into the new folder
  2  `claude @b`: the session runs in profile b
  3  a word is said, `!forge switch @a` is typed in the session: the same session comes back in profile a and still has the word
  4  `forge run @b "list your skills"` returns b's skills and not a's (and `@a` the reverse, so the check can tell them apart)
  5  two windows at once, one session in a and one in b, each with its own record and its own settings file
Which profile a session is in: the record `profile-sessions/<id>.json` and, read from /proc, FORGE_PROFILE and the `--settings`
file of its claude process (there is no status bar to read). The count of typed commands is the one the plan names: steps 1 to 3,
`forge new`, `claude @b`, `!forge switch @a`, fails above MAX_COMMANDS (3). The `cd` into the project is typed too (no command
can change its parent shell's folder) and is printed apart as "navigation": with it the walk is 4 typed lines, which is one more than
today's no-skill route to a session in b (U0: `forge new`, `cd`, `claude @b`) and the plan's three does not count it.

Safety. The login of the machine is never given to the session: it runs on the measurement token (scripts/bench/measure_login.py,
FORGE_MEASURE_OAUTH_TOKEN of the secret store, or the store FORGE_SECRETS_FILE names), the toy config dir has no `.credentials.json`,
and the real `~/.claude/.credentials.json` is lstat'ed (inode, size, mtime) before and after: a difference is a FAIL. The engine is a
copy (tests/test_profiles.py World), HOME, XDG_* and the secret store are the toy's, claude is the binary linked into a PATH of our own
(the `mise` wrapper that `claude` is on a mise machine is never run). Cost: a handful of haiku turns, the two `forge run` calls report
theirs; the interactive turns are not metered here.

NOT RUN, NOT ARMED (exit 77, never a pass): no tmux, no claude binary, no measurement token, or no Linux /proc.

Controls (CONTROLS, at the end of this file; the harness is reused, each is an engine copy with one line broken, run through the same walk,
and the walk must end in the failure named there). Seen, in one run of the file:
  `forge new` ignores --profiles (forge/ask.py, `ans.profiles = flags.profiles` -> `[]`): the walk ends at step 1 with "FAIL 1: forge new
      exits 0 -- exit 2"; the pane of that run shows "! forge new: nothing written, --skills @a: that is not one of the profiles of this run
      (none: no profile is being made); --skills @b: ...". No session was started.
  a switch keeps the old FORGE_PROFILE (forge/launch.py, the line that sets it after a switch is `env = dict(env)`): the record and the flags say
      a, the restarted claude's environment says b, and the walk ends at step 3 with "FAIL walk stopped: timed out after 20s: the session to
      be in profile a". A first mutant of this control, FORGE_PROFILE fixed to 'b' in session_env, did not fail the walk (the switch sets
      the variable on its own line): "FAIL control: ... the walk ends in 'walk stopped: ...' -- failures []"; it was replaced by this one.
Not armed: no tmux, no claude executable, no measurement token, no /proc prints `NOT RUN, NOT ARMED: <what>` and exits 77 (seen for each of
the first three). A run costs a few cents on haiku (the transcript's tokens are printed) and about a minute; wherever the checkout's store holds
the measurement token, `forge test` runs it live.
"""
import atexit
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "bench"))
import sandbox  # noqa: E402
import measure_login as ml  # noqa: E402
from test_profiles import World  # noqa: E402

MAX_COMMANDS = 3
WORD = "ZEBRAMANGO"
SPELLED = "-".join(WORD)
SKILLS = ("toy-common", "toy-a", "toy-b", "toy-c")
PROMPT_WAIT, TURN_WAIT, SWITCH_WAIT = 90, 150, 90
failures = []
MODE = [""]   # "control: " while the control walk runs, so its expected FAIL lines are not read as the test's own


def say(text):
    print(text, flush=True)


def check(name, ok, detail=""):
    if ok:
        say("%sok   %s" % (MODE[0], name))
    else:
        failures.append(name)
        say("%sFAIL %s -- %s" % (MODE[0], name, detail))


class Stop(Exception):
    """A step the rest of the walk depends on failed: the walk ends there."""


def must(name, ok, detail=""):
    check(name, ok, detail)
    if not ok:
        raise Stop(name)


def not_armed(reason):
    say("NOT RUN, NOT ARMED: " + reason)
    sys.exit(77)


# ------------------------------------------------------------------------------------------------------------ what is needed

def claude_binary():
    """The real claude executable, never the mise wrapper `claude` is on a mise machine, or None."""
    found = shutil.which("claude")
    if found and os.path.basename(os.path.realpath(found)) == "mise":
        try:
            r = subprocess.run(["mise", "which", "claude"], capture_output=True, text=True, timeout=60)
            found = r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            found = None
    return found if found and os.access(found, os.X_OK) and os.path.isfile(found) else None


def armed():
    """(claude binary, token) or exit 77 saying what is missing."""
    if sys.platform != "linux" or not os.path.isdir("/proc/self"):
        not_armed("this walk reads /proc to see a session's profile: Linux only")
    if not shutil.which("tmux"):
        not_armed("tmux is not on PATH")
    binary = claude_binary()
    if not binary:
        not_armed("no claude executable (and `mise which claude` has none)")
    try:
        tok = ml.token()
    except ml.LoginError as e:
        not_armed(str(e).split(" (secret store")[0])
    return binary, tok


REAL_LOGIN = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")


def login_stat():
    try:
        s = os.lstat(REAL_LOGIN)
    except OSError:
        return None
    return (s.st_ino, s.st_size, s.st_mtime_ns)


# ---------------------------------------------------------------------------------------------------------------------- tmux

class Walk:
    """A toy world and the tmux server (own socket, own environment) the person's terminal runs in."""

    def __init__(self, binary, token, mutate=None):
        self.token, self.binary = token, binary
        self.w = World([], skills=(), mutate=mutate)
        self.root, self.home = self.w.root, self.w.home
        cfg = os.path.join(self.w.forge, "config", "forge.json")
        with open(cfg, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.projects = os.path.join(self.root, "projects")
        os.makedirs(self.projects)
        doc["projects_dir"] = self.projects
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        self.project = os.path.join(self.projects, "toy")
        self.state = os.path.join(self.home, ".local", "state", "forge")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "forge"), "w") as fh:
            fh.write('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, os.path.join(self.w.forge, "bin", "forge")))
        os.chmod(os.path.join(self.bin, "forge"), 0o755)
        os.symlink(binary, os.path.join(self.bin, "claude"))
        for s in SKILLS:
            d = os.path.join(self.home, ".claude", "skills", s)
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w") as fh:
                fh.write("---\nname: %s\ndescription: Toy skill %s, never needed for any task.\n---\nNothing.\n" % (s, s))
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as fh:
            json.dump({"model": "haiku"}, fh)
        with open(os.path.join(self.home, ".claude.json"), "w") as fh:  # onboarding and the folder's trust answered, as after a first day
            json.dump({"hasCompletedOnboarding": True, "theme": "dark", "numStartups": 9,
                       "projects": {self.project: {"hasTrustDialogAccepted": True, "allowedTools": []}}}, fh)
        ml.clean_config_dir(os.path.join(self.home, ".claude"))
        self.rc = os.path.join(self.root, "last-status")
        self.rcfile = os.path.join(self.root, "bashrc")
        with open(self.rcfile, "w") as fh:
            fh.write("PS1='WALK$ '\nPROMPT_COMMAND='echo $? > %s'\neval \"$(forge shim --shell bash)\"\n" % self.rc)
        self.env = ml.child_env(sandbox.bare_env(self.home, self.root, PATH=self.bin + ":/usr/bin:/bin", TERM="xterm-256color",
                                                 SHELL="/bin/bash", DISABLE_AUTOUPDATER="1", PYTHONDONTWRITEBYTECODE="1"))
        self.sock = os.path.join(self.root, "tmux.sock")
        self.typed = []        # (what, text): the lines typed as commands
        self.navigation = []
        atexit.register(self.stop)   # a walk that dies on an exception leaves no tmux server behind

    # tmux itself ---------------------------------------------------------------------------------------------------
    def tmux(self, *args, check_rc=True):
        r = subprocess.run(["tmux", "-S", self.sock, "-f", "/dev/null"] + list(args), capture_output=True, text=True, timeout=60,
                           env=self.env)
        if check_rc and r.returncode:
            raise Stop("tmux %s: %s" % (" ".join(args[:2]), r.stderr.strip()))
        return r.stdout

    def start(self):
        cmd = "bash --noprofile --rcfile %s -i" % self.rcfile
        subprocess.run(["env", "-i"] + ["%s=%s" % kv for kv in self.env.items()] +
                       ["tmux", "-S", self.sock, "-f", "/dev/null", "new-session", "-d", "-s", "walk", "-x", "180", "-y", "50",
                        "-c", self.root, cmd], check=True, timeout=60)
        self.wait_shell("walk:0")

    def window(self, name):
        self.tmux("new-window", "-d", "-t", "walk", "-n", name, "-c", self.root, "bash --noprofile --rcfile %s -i" % self.rcfile)
        target = "walk:" + name
        self.wait_shell(target)
        return target

    def stop(self):
        self.tmux("kill-server", check_rc=False)

    def capture(self, target):
        return ml.redact_text(self.tmux("capture-pane", "-p", "-J", "-t", target, "-S", "-300", check_rc=False), self.token)

    def screen(self, target):
        return ml.redact_text(self.tmux("capture-pane", "-p", "-t", target, check_rc=False), self.token)

    def dump(self, label, target, n=14):
        """The last `n` non-empty lines of the pane with its scrollback (claude writes the conversation there, above the input box)."""
        say("---- tmux %s (%s) ----" % (label, target))
        lines = [l.rstrip() for l in self.tmux("capture-pane", "-p", "-t", target, "-S", "-300", check_rc=False).splitlines() if l.strip()]
        say(ml.redact_text("\n".join(l[:150] for l in lines[-n:]), self.token))
        say("---- end ----")

    # waiting -------------------------------------------------------------------------------------------------------
    def until(self, what, fn, timeout, target=None):
        end = time.time() + timeout
        while time.time() < end:
            got = fn()
            if got:
                return got
            time.sleep(0.5)
        if target:
            self.dump("timeout: " + what, target)
        raise Stop("timed out after %ds: %s" % (timeout, what))

    def at_shell_prompt(self, target):
        lines = [l.rstrip() for l in self.screen(target).splitlines() if l.strip()]
        return bool(lines) and lines[-1].endswith("WALK$")

    def wait_shell(self, target, timeout=60):
        self.until("the shell prompt in %s" % target, lambda: self.at_shell_prompt(target), timeout, target)

    def claude_idle(self, target):
        """claude's input box is on screen and nothing runs: the box (a line of the frame with the prompt mark) and no 'esc to interrupt'."""
        text = self.screen(target)
        return "❯" in text and "esc to interrupt" not in text and "⏺" not in text.splitlines()[-1:][0:1].__str__()

    def settled(self, target, secs):
        """claude's input box is up and the screen (scrollback too) did not change for `secs`: a restarted claude has drawn itself, and the box
        of the one that was ended is not taken for it (the new process exists before this is asked)."""
        before = self.capture(target)
        if not self.claude_idle(target):
            return False
        time.sleep(secs)
        return self.capture(target) == before and self.claude_idle(target)

    # typing --------------------------------------------------------------------------------------------------------
    def send(self, target, text):
        self.tmux("send-keys", "-t", target, "-l", text)
        time.sleep(0.4)
        self.tmux("send-keys", "-t", target, "Enter")

    def command(self, target, text, counted=True):
        """A command typed as a person types it: `counted` ones are the steps of the walk, the others are navigation."""
        (self.typed if counted else self.navigation).append((target, text))
        self.send(target, text)

    def last_status(self):
        try:
            with open(self.rc) as fh:
                return fh.read().strip()
        except OSError:
            return None

    # which profile a session is in ----------------------------------------------------------------------------------
    def record(self, sid):
        try:
            with open(os.path.join(self.state, "profile-sessions", sid + ".json"), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def record_ids(self):
        d = os.path.join(self.state, "profile-sessions")
        return {f[:-5] for f in os.listdir(d)} if os.path.isdir(d) else set()

    def claudes(self, sid):
        """[(pid, FORGE_PROFILE, the --settings file name)] of the claude processes that carry FORGE_SESSION=sid, read from /proc."""
        out = []
        want = os.path.realpath(self.binary)
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                if os.path.realpath("/proc/%s/exe" % d) != want:
                    continue
                with open("/proc/%s/environ" % d, "rb") as fh:
                    env = dict(x.split(b"=", 1) for x in fh.read().split(b"\0") if b"=" in x)
                with open("/proc/%s/cmdline" % d, "rb") as fh:
                    argv = [x.decode("utf-8", "replace") for x in fh.read().split(b"\0")]
            except OSError:
                continue
            if env.get(b"FORGE_SESSION", b"").decode() != sid:
                continue
            settings = argv[argv.index("--settings") + 1] if "--settings" in argv and argv.index("--settings") + 1 < len(argv) else ""
            out.append((int(d), env.get(b"FORGE_PROFILE", b"").decode(), settings))
        return out

    def in_profile(self, sid, profile):
        """The session is in `profile` when its record, every claude process of it and their --settings file all say so (and one exists)."""
        rec, procs = self.record(sid), self.claudes(sid)
        suffix = os.path.join("profile-settings", "toy", profile + ".json")
        ok = bool(rec) and rec.get("profile") == profile and bool(procs) and all(
            p[1] == profile and p[2].endswith(suffix) for p in procs)
        return ok

    def describe(self, sid):
        return "record %s, claude %s" % ((self.record(sid) or {}).get("profile"), [(p[1], os.path.basename(p[2])) for p in self.claudes(sid)])

    def new_session(self, before):
        got = self.record_ids() - before
        return next(iter(got)) if len(got) == 1 else None

    def tokens(self, sid):
        """Total tokens by kind over the assistant messages of session `sid`'s transcript (the interactive turns are not metered in USD)."""
        tot = {}
        for d, _, files in os.walk(os.path.join(self.home, ".claude", "projects")):
            for n in files:
                if n == sid + ".jsonl":
                    with open(os.path.join(d, n), encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            try:
                                use = (json.loads(line).get("message") or {}).get("usage") or {}
                            except (ValueError, AttributeError):
                                continue
                            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
                                if isinstance(use.get(k), int):
                                    tot[k] = tot.get(k, 0) + use[k]
        return tot

    def say_to_claude(self, target, text):
        self.send(target, text)

    def wait_reply(self, target, needle, timeout=TURN_WAIT):
        """The reply the message asked for is on screen (needle is something the message itself does not contain) and claude is idle again."""
        self.until("a reply containing %r" % needle, lambda: needle in self.capture(target).replace("\n", "") and self.claude_idle(target),
                   timeout, target)


# ------------------------------------------------------------------------------------------------------------------- the walk

def run_forge(wk, args, cwd, timeout=240):
    r = subprocess.run([os.path.join(wk.bin, "forge")] + args, cwd=cwd, env=wk.env, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    tok = wk.token
    return r.returncode, ml.redact_text(r.stdout, tok), ml.redact_text(r.stderr, tok)


def walk(binary, token, mutate=None, switch_wait=SWITCH_WAIT):
    """Runs the walk; returns (typed commands, navigation lines). Failures are in `failures`; a Stop ends the walk at its step."""
    wk = Walk(binary, token, mutate)
    costs = []
    try:
        wk.start()
        # 1 ----------------------------------------------------------------------------------------------------------
        new = ("forge new toy --stack generic --profiles a,b --skills @a:toy-a --skills @b:toy-c --sets none --server none "
               "--memory none --yes --apply")
        wk.command("walk:0", new)
        wk.wait_shell("walk:0", 120)
        wk.dump("after forge new", "walk:0", 3)
        must("1: forge new exits 0", wk.last_status() == "0", "exit %s" % wk.last_status())
        proj = os.path.join(wk.w.forge, "config", "projects", "toy.claude.json")
        try:
            with open(proj, encoding="utf-8") as fh:
                offered = json.load(fh).get("profiles", {}).get("offered", {})
        except (OSError, ValueError):
            offered = {}
        must("1: the project file offers profiles a and b", sorted(offered) == ["a", "b"], "offered %s" % sorted(offered))
        must("1: the folder exists", os.path.isdir(wk.project))
        wk.command("walk:0", "cd %s" % wk.project, counted=False)
        wk.wait_shell("walk:0")

        # 2 ----------------------------------------------------------------------------------------------------------
        before = wk.record_ids()
        wk.command("walk:0", "claude @b")
        sid = wk.until("the session record of `claude @b`", lambda: wk.new_session(before), PROMPT_WAIT, "walk:0")
        wk.until("claude's input box", lambda: wk.claude_idle("walk:0"), PROMPT_WAIT, "walk:0")
        wk.dump("claude @b", "walk:0")
        must("2: `claude @b` runs the session in profile b", wk.in_profile(sid, "b"), wk.describe(sid))
        pid_b = wk.claudes(sid)[0][0]

        # 3 ----------------------------------------------------------------------------------------------------------
        wk.say_to_claude("walk:0", "The secret word is %s. Now reply with the digits of 1234 plus 4321 and nothing else." % WORD)
        wk.wait_reply("walk:0", "5555")
        wk.command("walk:0", "!forge switch @a")
        wk.until("the session to be in profile a", lambda: wk.in_profile(sid, "a") and wk.claudes(sid)[0][0] != pid_b, switch_wait, "walk:0")
        wk.until("the restarted claude's input box, its screen unchanged for 2 s", lambda: wk.settled("walk:0", 2), PROMPT_WAIT, "walk:0")
        wk.dump("after forge switch @a", "walk:0")
        must("3: the same session id came back in profile a", wk.in_profile(sid, "a") and wk.record_ids() >= {sid}, wk.describe(sid))
        check("3: the spelled word is on no screen before it is asked for", SPELLED not in wk.capture("walk:0").replace("\n", "").upper())
        wk.say_to_claude("walk:0", "Write the secret word I gave you with a hyphen between its letters and nothing else.")
        wk.wait_reply("walk:0", SPELLED)
        wk.dump("the word after the switch", "walk:0", 8)
        check("3: the word is kept across the switch", SPELLED in wk.capture("walk:0").replace("\n", "").upper())

        # 4 ----------------------------------------------------------------------------------------------------------
        ask = "List the names of the skills you have, one per line, and nothing else."
        found = {}
        for name in ("b", "a"):
            rc, out, err = run_forge(wk, ["run", "@" + name, ask, "--model", "haiku"], wk.project)
            say("---- forge run @%s: exit %s\n%s\n(stderr) %s" % (name, rc, out.strip(), err.strip()))
            cost = re.search(r"cost ([0-9.]+) USD", err)
            costs.append(float(cost.group(1)) if cost else None)
            found[name] = {s for s in SKILLS if re.search(r"\b%s\b" % re.escape(s), out)}
            check("4: forge run @%s exits 0" % name, rc == 0, "exit %s, stderr %r" % (rc, err[-300:]))
        check("4: forge run @b lists b's skills and not a's", "toy-c" in found["b"] and not {"toy-a", "toy-b"} & found["b"],
              "listed %s" % sorted(found["b"]))
        check("4: forge run @a lists a's skills and not b's (so the check can tell them apart)",
              "toy-a" in found["a"] and "toy-c" not in found["a"], "listed %s" % sorted(found["a"]))

        # 5 ----------------------------------------------------------------------------------------------------------
        before = wk.record_ids()
        two = wk.window("w2")
        wk.command(two, "cd %s" % wk.project, counted=False)
        wk.wait_shell(two)
        wk.command(two, "claude @b", counted=False)
        sid2 = wk.until("the second session record", lambda: wk.new_session(before), PROMPT_WAIT, two)
        wk.until("claude's input box in window 2", lambda: wk.claude_idle(two), PROMPT_WAIT, two)
        wk.dump("window 2", two)
        wk.dump("window 1 still", "walk:0")
        check("5: two sessions, two ids", sid2 != sid, "same id %s" % sid)
        check("5: window 1 is in profile a", wk.in_profile(sid, "a"), wk.describe(sid))
        check("5: window 2 is in profile b", wk.in_profile(sid2, "b"), wk.describe(sid2))
        say("---- cost: the two forge run calls reported %s USD; the interactive session's own tokens (its transcript): %s"
            % (costs, wk.tokens(sid)))
        return wk
    except Stop as e:
        failures.append("walk stopped: %s" % e)
        say("%sFAIL walk stopped: %s" % (MODE[0], e))
        return wk
    finally:
        pass


def reap(wk):
    """Ends the tmux server (its panes get HUP), then any claude of the toy world still running; returns what had to be killed."""
    wk.stop()
    time.sleep(1)
    left = [p for sid in wk.record_ids() for p in wk.claudes(sid)]
    for pid, _, _ in left:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    return left


def finish(wk):
    left = reap(wk)
    check("cleanup: no claude of the toy world was left after the tmux server ended", not left, str(left))
    check("cleanup: the toy config dir has no .credentials.json", not os.path.lexists(os.path.join(wk.home, ".claude", ".credentials.json")))


def main():
    binary, token = armed()
    before = login_stat()
    say("real login file before: %s" % (before,))
    wk = walk(binary, token)
    try:
        counted = len(wk.typed)
        say("typed commands, steps 1-3: %d %s" % (counted, [t for _, t in wk.typed]))
        say("navigation typed apart (cd, a second window): %d %s" % (len(wk.navigation), [t for _, t in wk.navigation]))
        say("typed lines in the first window with the cd: %d" % (counted + len([n for n in wk.navigation if n[0] == "walk:0"])))
        check("typed commands of steps 1-3 are at most %d" % MAX_COMMANDS, counted <= MAX_COMMANDS, "typed %d" % counted)
        check("the walk typed the three commands (looking at zero is a failure)", counted == 3, "typed %d" % counted)
        finish(wk)
    finally:
        wk.stop()
    after = login_stat()
    say("real login file after:  %s" % (after,))
    check("the machine's login file is untouched (inode, size, mtime)", before == after, "%s -> %s" % (before, after))
    # CONTROLS ---------------------------------------------------------------------------------------------------------
    control(binary, token)
    if failures:
        say("%d FAIL" % len(failures))
        sandbox.cleanup()
        sys.exit(1)
    sandbox.cleanup()
    say("ok: the walk passed")


# (what is broken, (file, the line, its replacement), the failure the walk must end in)
CONTROLS = [
    ("`forge new` ignores --profiles", ("forge/ask.py", "        ans.profiles = flags.profiles\n", "        ans.profiles = []\n"),
     "1: forge new exits 0"),
    ("a switch keeps the old FORGE_PROFILE in the restarted claude's environment, the record and the flags saying the new one",
     ("forge/launch.py", "            env = dict(env, FORGE_PROFILE=profile)\n", "            env = dict(env)\n"),
     "walk stopped: timed out after 20s: the session to be in profile a"),
]


def control(binary, token):
    """The walk against an engine copy with one line broken must end in the failure named in CONTROLS (the first of each is kept in the
    docstring of this file); steps after it must not have been reached for the first, and the claude it started must be gone."""
    for what, mutate, want in CONTROLS:
        mark = len(failures)
        MODE[0] = "(control, expected) "
        wk = walk(binary, token, mutate=mutate, switch_wait=20)
        MODE[0] = ""
        left = reap(wk)
        mine = failures[mark:]
        del failures[mark:]
        say("control message (%s): %s" % (what, mine))
        check("control: with %s the walk ends in %r" % (what, want), want in mine, "failures %s" % mine)
        check("control: nothing was left running", not left, str(left))


if __name__ == "__main__":
    main()
