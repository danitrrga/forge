#!/usr/bin/env python3
"""The screen of `forge config` (forge/configure.py: screen(), sections(); the second half of the plan's 4.4 U3b). In a terminal, `forge config
[NAME] [@PROFILE]` with no `--on`/`--off` opens the key selector on the project's (or the profile's) rows and, once confirmed, hands the
toggled rows to the same change() the flags use. The world is test_configure.py's toy (tests/sandbox.py); every run is the copy's bin/forge
on a pty with real bytes (arrows, space, Enter, Esc, Ctrl-C, then `y` or `n` at the prompt), and the terminal's termios attributes are
compared before and after each run, on the slave end this test keeps open.

Cases (the plan's control (h), and the brief's):
  h  the recorded keys that turn off `skill:toy-d` (and, in a second world, `skill:toy-common`) and then `y` leave a world byte for byte the
     one `--off skill:toy-d --apply` (resp. toy-common) leaves in a fresh copy of the same toy world (files compared, mtimes left out).
  e  Esc and Ctrl-C write nothing, exit 0 and say so in one line; so does Enter with nothing toggled.
  n  after a toggle, `n` and a bare Enter at `[y/N]` write nothing and show the equivalent command.
  r  a toggled row the flags refuse (`toy-a`, which arrives through the set TOYSET) ends with the flags' refusal, exit 2, tree intact.
  p  `forge config profiled @x`: the screen changes the profile's row and not the project's extras row; a read-only profile row of
     the project screen does nothing when toggled.
  t  the terminal is as it was after every run above.

Written first and run against fe9246a (the first half, whose `forge config NAME` with no flag and a terminal is exit 2 "nothing to change"): 26 FAIL,
the first "FAIL h: the screen run for toy-d exits 0 -- exit 2, shown 'forge config: nothing to change: give --on TYPE:NAME or --off TYPE:NAME ...'".
Negative controls, each a text replacement in the world's copy of the engine (World(mutate=...)), run once with `python3 tests/test_configure_screen.py
mutants` (which is expected to print these FAILs and exit 1):
  h  the toggled row read as another (toy-d as toy-e, toy-common as toy-a) -> "FAIL h: the screen for toy-d and --off skill:toy-d --apply leave the same
     files -- screen and flags differ: ['forge/config/projects/plain.claude.json', ...]"
  t  selector.run() without the restore of the terminal attributes -> "FAIL t: terminal left in raw mode (selector without its restore) -- terminal left in raw mode"
  e  screen() returning a change for a cancelled selector -> "FAIL e: Esc exits 0 and says nothing was written -- exit 0, shown ..." (the screen went on to ask [y/N])
  n  the question of change() answered yes without asking -> "FAIL n: n at [y/N] writes nothing -- wrote without asking: ['forge/config/projects/plain.claude.json', ...]"
Left out of the file comparison: the toy HOME's state folder (time of each write; checksums of files that name the world's own root).
"""
import os
import pty
import select
import shutil
import subprocess
import sys
import termios
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import sandbox  # noqa: E402
from test_configure import World, changed  # noqa: E402

failures = []
DOWN, SPACE, ENTER, ESC, CTRL_C = b"\x1b[B", b" ", b"\r", b"\x1b", b"\x03"
HINT = b"esc cancels"


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, str(detail)[:230]))


STATE = os.path.join("home", ".local", "state", "forge")


def files(w):
    """{path: (type, mode, sha256 of the content with the world's root masked)}: the world as the screen and the flags must leave it. Left
    out: forge's state folder of the toy HOME (journal.log holds the time of each write; owned.json holds checksums of files that name the
    world's own root, which masking cannot reach), the only two files two fresh worlds differ in after the same change."""
    return {k: v[:3] for k, v in sandbox.manifest(w.root, mask=True).items() if not k.startswith(STATE + os.sep)}


def run_screen(w, args, keys=b"", answer=None, wait_after_keys=0.0):
    """(exit code, what the terminal showed, termios attributes were the same after) of `forge config ARGS` on a pty. `keys` (bytes) are sent
    once the selector has drawn its hint (the terminal is raw by then: a Ctrl-C earlier would be eaten as a signal); `answer` (bytes) is sent
    when `[y/N]` shows. The slave end stays open here so that its attributes can be read after the child is gone."""
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    p = subprocess.Popen([sys.executable, os.path.join(w.forge, "bin", "forge")] + list(args), cwd=w.forge, env=w.env(), stdin=slave,
                         stdout=slave, stderr=slave, close_fds=True, start_new_session=True)
    seen, sent_keys, sent_answer, asked, deadline = b"", False, answer is None, False, time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    got = os.read(master, 4096)
                except OSError:  # EIO: the child closed its end
                    break
                if not got:
                    break
                seen += got
                if not sent_keys and HINT in seen:
                    sent_keys = True
                    time.sleep(0.1)
                    os.write(master, keys)
                    time.sleep(wait_after_keys)
                elif sent_keys and not sent_answer and b"[y/N]" in seen:
                    sent_answer = True
                    os.write(master, answer)
                elif sent_keys and answer is None and b"[y/N]" in seen and not asked:
                    asked = True  # a question nobody expected: the input ends, which answers no, so the run still ends
                    os.write(master, b"\x04")
            elif p.poll() is not None:
                break
        else:
            p.kill()
        try:
            code = p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            code = p.wait()
        return code, seen.decode("utf-8", "replace").replace(w.root, "@S@"), termios.tcgetattr(slave) == before
    finally:
        os.close(master)
        os.close(slave)


def flags_world(args):
    """The world the flags leave: a fresh copy, `forge config ARGS --apply`."""
    w = World()
    code, out, err = w.forge_cmd(["config"] + list(args) + ["--apply"])
    assert code == 0, "the flags run failed: %s%s" % (out, err)
    return w


def case_h(mutate=None):
    """The screen and the flags write the same. Rows of `plain`, in order: skills toy-a toy-b toy-c toy-common toy-d toy-e (alphabetical,
    one group: it has no extras row), then sets, servers, options."""
    for skill, downs in (("toy-d", 4), ("toy-common", 3)):
        want = flags_world(["plain", "--off", "skill:" + skill])
        w = World(mutate)
        pristine = files(w)
        code, shown, restored = run_screen(w, ["config", "plain"], DOWN * downs + SPACE + ENTER, b"y\r")
        # Control: a screen that toggles the wrong row (the mutation above) fails with `screen and flags differ`.
        check("h: the screen run for %s exits 0" % skill, code == 0, "exit %d, shown %r" % (code, shown))
        check("h: the screen run for %s wrote something (looking at nothing is a failure)" % skill, files(w) != pristine, "the world did not change; shown %r" % shown)
        got, expect = files(w), files(want)
        check("h: the screen for %s and --off skill:%s --apply leave the same files" % (skill, skill), got == expect,
              "screen and flags differ: %s; shown %r" % (changed(got, expect), shown))
        check("h: and the screen showed the command it would run", "forge config plain --off skill:%s" % skill in shown, shown)
        check("t: terminal left in raw mode after the h run for %s" % skill, restored, "terminal left in raw mode")
        sandbox.rmtree(w.root)
        sandbox.rmtree(want.root)


def case_e(mutate=None):
    w = World(mutate)
    before = files(w)
    for label, keys in (("Esc", DOWN + SPACE + ESC), ("Ctrl-C", DOWN + SPACE + CTRL_C)):
        code, shown, restored = run_screen(w, ["config", "plain"], keys)
        # Control: a screen that returns the changes of a cancelled selector writes them; it fails with `Esc wrote ...`.
        check("e: %s writes nothing" % label, files(w) == before, "%s wrote %s; shown %r" % (label, changed(before, files(w)), shown))
        check("e: %s exits 0 and says nothing was written" % label, code == 0 and "nothing was written" in shown and "[y/N]" not in shown,
              "exit %d, shown %r" % (code, shown))
        check("t: terminal restored after %s" % label, restored, "terminal left in raw mode after %s" % label)
    code, shown, restored = run_screen(w, ["config", "plain"], ENTER)
    check("e: Enter with nothing toggled writes nothing, exits 0 and says so", code == 0 and files(w) == before and "nothing was written" in shown,
          "exit %d, shown %r" % (code, shown))
    check("t: terminal restored after a bare Enter", restored, "terminal left in raw mode after a bare Enter")
    code, shown, restored = run_screen(w, ["config", "plain"], DOWN + SPACE + SPACE + ENTER)
    check("e: a row toggled twice is not a change", code == 0 and files(w) == before and "nothing was written" in shown, "exit %d, shown %r" % (code, shown))
    sandbox.rmtree(w.root)


def case_n(mutate=None):
    w = World(mutate)
    before = files(w)
    for label, answer in (("n", b"n\r"), ("a bare Enter", b"\r"), ("N", b"N\r")):
        code, shown, restored = run_screen(w, ["config", "plain"], DOWN * 4 + SPACE + ENTER, answer)
        # Control: a screen whose flags are written without the question fails with `wrote without asking`.
        check("n: %s at [y/N] writes nothing" % label, files(w) == before and "[y/N]" in shown,
              "wrote without asking: %s; shown %r" % (changed(before, files(w)), shown))
        check("n: and the command it would have run is shown, exit 0", code == 0 and "forge config plain --off skill:toy-d" in shown, "exit %d, shown %r" % (code, shown))
        check("t: terminal restored after %s" % label, restored, "terminal left in raw mode after %s" % label)
    sandbox.rmtree(w.root)


def case_r():
    """`multi` keeps toy-a and toy-b through the set TOYSET: its first two skill rows, in the group `skills from set TOYSET`."""
    w = World()
    before = files(w)
    code, shown, restored = run_screen(w, ["config", "multi"], SPACE + ENTER)
    check("r: the screen shows the set's group and the origin of the skill", "skills from set TOYSET" in shown and "toy-a  (set:TOYSET)" in shown, shown)
    check("r: a toggled row the flags refuse ends with their refusal and exit 2", code == 2 and "arrives through the set" in shown and "--off set:TOYSET" in shown,
          "exit %d, shown %r" % (code, shown))
    check("r: and the tree is intact (no [y/N] was asked either)", files(w) == before and "[y/N]" not in shown,
          "wrote %s; shown %r" % (changed(before, files(w)), shown))
    check("t: terminal restored after a refusal", restored, "terminal left in raw mode after a refusal")
    # A read-only profile row of the project screen does nothing when toggled: `multi` is offered toy-b and list; they are the last rows.
    last = [DOWN] * 30
    code, shown, restored = run_screen(w, ["config", "multi"], b"".join(last) + SPACE + ENTER)
    check("p: the project screen lists its profiles with the command that enters each", "forge config multi @toy-b" in shown, shown)
    check("p: a toggled read-only profile row changes nothing", code == 0 and files(w) == before and "nothing was written" in shown, "exit %d, shown %r" % (code, shown))
    sandbox.rmtree(w.root)


def case_p():
    """`profiled`: extras row [toy-c, toy-d], profile x whose row holds toy-c and whose definition holds toy-a. The profile screen has the
    skills groups and the sets only (servers and options are the project's)."""
    w = World()
    extras0, row0 = w.doc()["skill_keep"]["extras"]["profiled.claude.json"], w.proj("profiled")["profiles"]["offered"]["x"]["skills"]
    code, shown, restored = run_screen(w, ["config", "profiled", "@x"], ENTER)
    check("p: the profile screen has no servers, options or profiles sections", code == 0 and "servers" not in shown and "options" not in shown
          and "read-only" not in shown, "exit %d, shown %r" % (code, shown))
    # toy-c is the third alphabetical row (toy-a, toy-b, toy-c): off in the profile's row, which is where toy-c is held.
    wf = flags_world(["profiled", "@x", "--off", "skill:toy-c"])
    code, shown, restored = run_screen(w, ["config", "profiled", "@x"], DOWN * 2 + SPACE + ENTER, b"y\r")
    check("p: the profile screen run exits 0 and shows the profile's command", code == 0 and "forge config profiled @x --off skill:toy-c" in shown, "exit %d, shown %r" % (code, shown))
    check("p: the profile's row lost toy-c", w.proj("profiled")["profiles"]["offered"]["x"]["skills"] == [] and row0 == ["toy-c"], w.proj("profiled")["profiles"])
    # Control: a screen that writes the project's row instead fails with `profile change leaked to the project`.
    check("p: and the project's extras row did not change", w.doc()["skill_keep"]["extras"]["profiled.claude.json"] == extras0,
          "profile change leaked to the project: %s" % w.doc()["skill_keep"]["extras"])
    got, expect = files(w), files(wf)
    check("p: the screen and the flags leave the same files for the profile", got == expect, "screen and flags differ: %s" % changed(got, expect))
    check("t: terminal restored after the profile screen", restored, "terminal left in raw mode after the profile screen")
    sandbox.rmtree(w.root)
    sandbox.rmtree(wf.root)


def case_terminal(mutate):
    """A selector that does not restore the terminal is seen failing: the first h run, with the mutation, reports it."""
    w = World(mutate)
    code, shown, restored = run_screen(w, ["config", "plain"], ESC)
    check("t: terminal left in raw mode (selector without its restore)", restored, "terminal left in raw mode")
    sandbox.rmtree(w.root)


def attempt(fn, *args):
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001
        check("%s ran to its end" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "mutants":  # the controls: each is expected to print its FAIL
        wrong_row = ("forge/configure.py", "        typ, _, item = row.partition(\":\")\n",
                     "        typ, _, item = row.partition(\":\")\n        item = {\"toy-d\": \"toy-e\", \"toy-common\": \"toy-a\"}.get(item, item)\n")
        attempt(case_h, wrong_row)
        attempt(case_terminal, ("forge/selector.py", "termios.tcsetattr(fd_in, termios.TCSADRAIN, before)", "pass"))
        attempt(case_e, ("forge/configure.py", "    if got is None:\n        return None\n", "    if got is None:\n        return [(\"off\", \"skill\", \"toy-d\")]\n"))
        attempt(case_n, ("forge/configure.py", "go = _ask(\"write these changes? [y/N] \")", "go = True"))
    else:
        for fn in (case_h, case_e, case_n, case_r, case_p):
            attempt(fn)
    sandbox.cleanup()
    if failures:
        print("%d FAIL" % len(failures))
        return 1
    print("test_configure_screen: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
