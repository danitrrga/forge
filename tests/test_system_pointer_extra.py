#!/usr/bin/env python3
"""The user's own always-loaded lines inside the pointer block of sync_system_doc.py.

config/system-pointer-extra.md (user data, outside the engine's public history) holds markdown the generator places inside
the managed block of every managed project's CLAUDE.md, after the pointer text and before the END marker, so Claude
(CLAUDE.md) and Codex (the AGENTS.md link) keep a few user rules loaded. Absent or blank: the block is the plain POINTER,
byte for byte. A source that is not a readable UTF-8 file, or that holds a forge marker (a second END would make the next
sync replace up to the wrong one), stops the run with a `!` line and exit 1 before any file is touched, so the rules never
vanish silently.

A toy world (tests/sandbox.py), one project, run with --apply from a toy checkout this toy HOME names as installed.

Seen failing on 1d8b799 (the file is never read); the absent, empty and blank cases pass there, as they must, they are
today's behaviour:
  FAIL a source with rules: exit 0 and update-pointer: got (0, 'MODE: APPLY\\n...  = app  up to date\\n\\n0 change(s) applied.\\n')
  FAIL a source that holds the END marker stops the run: exit 1, a `!` line naming the file, CLAUDE.md untouched: got (0, ...)
  Review round (cases added for a broken link, a FIFO, the 8 KiB cap, a BOM with an indented first line and the user's text
  around the block), seen failing on b476470 with the script as it then was, "4 failure(s) over 21 cases":
  FAIL a source that is a broken symlink stops the run: ... got (0, 'MODE: APPLY\\n...  ~ app  update-pointer:CLAUDE.md ...')
  FAIL a source that is a FIFO stops the run: ... got (-9, 'TIMEOUT after 20 s (blocked)')
  FAIL a source that is over 8 KiB stops the run: ... got (0, ...)
  FAIL a source with a BOM and an indented first line: no BOM in the block, the indentation kept: got ...
  First round: 8 failure(s) over 13 cases, exit 1 (the rest: the block without the rules, the AGENTS.md link, the precondition, and the
  same stop-the-run failure for the BEGIN marker, a directory and non-UTF-8 sources)"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join("scripts", "sync", "sync_system_doc.py")
MODULE = os.path.join("forge", "system_doc.py")
SRC = "system-pointer-extra.md"
END = re.search(r'^END = "(.*)"$', open(os.path.join(sandbox.FORGE, MODULE), encoding="utf-8").read(), re.M).group(1)
BEGIN = re.search(r'^BEGIN = "(.*)"$', open(os.path.join(sandbox.FORGE, MODULE), encoding="utf-8").read(), re.M).group(1)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, data, mode="w"):
    with open(p, mode) as f:
        f.write(data)


def main():
    tmp = sandbox.mkdtemp("forge-sysextra-")
    root, home, app, keep = (os.path.join(tmp, d) for d in ("forge", "home", "app", "keep"))
    sandbox.mini_root(root, SCRIPT, os.path.join("forge", "mcp.py"), os.path.join("forge", "owned.py"),
                      MODULE, os.path.join("forge", "profiles.py"), os.path.join("forge", "suggest.py"))
    os.makedirs(os.path.join(root, "docs"))
    shutil.copy(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "AGENT-SYSTEM.md"),
                os.path.join(root, "docs", "AGENT-SYSTEM.md"))
    os.makedirs(os.path.join(root, "bin"))
    write(os.path.join(root, "bin", "forge"), "")  # lib.installed_root() wants it a file
    os.makedirs(os.path.join(root, "config", "projects"))
    os.makedirs(app)
    os.makedirs(keep)
    write(os.path.join(root, "config", "projects", "app.claude.json"), '{"project_path": "%s"}\n' % app)
    write(os.path.join(root, "config", "projects", "keep.claude.json"), '{"project_path": "%s"}\n' % keep)
    sandbox.installed_settings(home, root)
    env = sandbox.bare_env(home, tmp)
    source = os.path.join(root, "config", SRC)
    claude_md, agents_md = os.path.join(app, "CLAUDE.md"), os.path.join(app, "AGENTS.md")
    keep_md = os.path.join(keep, "CLAUDE.md")
    failures, ran = [], [0]

    def check(label, ok, got):
        ran[0] += 1
        if not ok:
            failures.append("%s: got %r" % (label, got if len(str(got)) < 300 else str(got)[:300] + "..."))

    def run():
        try:  # a script that opens a FIFO source blocks forever: that is a failed check, not a crashed test
            r = subprocess.run([sys.executable, os.path.join(root, SCRIPT), "--apply"], cwd=tmp, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            return -9, "TIMEOUT after 20 s (blocked)"
        return r.returncode, r.stdout

    plain = subprocess.run(
        [sys.executable, "-c", "import sys; sys.argv = ['x']; sys.path.insert(0, %r); "
         "import sync_system_doc as s; sys.stdout.write(s.POINTER)" % os.path.dirname(os.path.join(root, SCRIPT))],
        cwd=tmp, env=env, capture_output=True, text=True, timeout=60).stdout
    check("the toy checkout's POINTER can be read", plain.endswith(END), plain)
    plain_file = plain + "\n"

    before_text, after_text = "# Mine\n\nbefore the block\n\n", "\n\nafter the block\n"
    write(keep_md, before_text + plain + after_text)  # a CLAUDE.md the user wrote around forge's block
    rc, out = run()
    check("no source file: exit 0 and the block is the plain POINTER, byte for byte",
          rc == 0 and read(claude_md) == plain_file, (rc, read(claude_md)))

    rules = "- Rule one.\n- Rule two, with `code`.\n"
    for label, body in (("an empty source", ""), ("a blank source", "\n  \n\n")):
        write(source, body)
        rc, out = run()
        check(label + ": the block stays the plain POINTER", rc == 0 and read(claude_md) == plain_file, (rc, read(claude_md)))

    write(source, "\n" + rules + "\n\n")  # surrounding blank lines are not carried into the block
    want = plain[:-len(END)] + "\n" + rules + END + "\n"
    rc, out = run()
    check("a source with rules: exit 0 and update-pointer", rc == 0 and "update-pointer:CLAUDE.md" in out, (rc, out))
    check("a source with rules: the block holds them after the pointer text and before END", read(claude_md) == want, read(claude_md))
    check("a CLAUDE.md with the user's text around the block: the text is kept, the block gains the rules",
          read(keep_md) == before_text + want[:-1] + after_text, read(keep_md))
    check("the AGENTS.md link (Codex) reads the same block", os.path.islink(agents_md) and read(agents_md) == want, read(agents_md))
    rc, out = run()
    check("a second --apply changes nothing", rc == 0 and "0 change(s) applied." in out, out)

    os.remove(source)
    rc, out = run()
    check("the source removed: the block returns to the plain POINTER", rc == 0 and read(claude_md) == plain_file, (rc, read(claude_md)))

    write(source, rules)
    run()
    before = read(claude_md)
    check("the rules are in before the broken sources are tried", before is not None and rules in before, before)
    keep_before = read(keep_md)

    def clear():
        if os.path.isdir(source) and not os.path.islink(source):
            os.rmdir(source)
        elif os.path.lexists(source):
            os.remove(source)

    cases = (("holds the END marker", lambda: write(source, "x\n" + END + "\n")),
             ("holds the BEGIN marker", lambda: write(source, BEGIN + "\n")),
             ("is a directory", lambda: os.mkdir(source)),
             ("is not UTF-8", lambda: write(source, b"\xff\xfe\x00bad", "wb")),
             # A link that leads nowhere is not "absent": FileNotFoundError on open said so and the rules vanished everywhere.
             ("is a broken symlink", lambda: os.symlink("nowhere.md", source)),
             # A FIFO is not a regular file; the check comes before any open, which would block on it.
             ("is a FIFO", lambda: os.mkfifo(source)),
             ("is over 8 KiB", lambda: write(source, "x" * 8192 + "\n")))
    for label, make in cases:
        clear()
        make()
        rc, out = run()
        check("a source that %s stops the run: exit 1, a `!` line naming the file, CLAUDE.md untouched" % label,
              rc == 1 and re.search(r"^! .*%s" % re.escape(SRC), out, re.M) and read(claude_md) == before
              and read(keep_md) == keep_before, (rc, out))

    # The cap is 8 KiB, 8192 bytes, inclusive.
    clear()
    big = "x" * 8191 + "\n"
    write(source, big)
    rc, out = run()
    check("a source of exactly 8 KiB is accepted", rc == 0 and big in (read(claude_md) or ""), (rc, out))

    # A BOM is dropped and the indentation of the first line is kept (an indented first line is a code block or a nested item).
    clear()
    write(source, b"\xef\xbb\xbf\n\n    indented first line\n- rule\n\n", "wb")
    rc, out = run()
    check("a source with a BOM and an indented first line: no BOM in the block, the indentation kept",
          rc == 0 and read(claude_md) == plain[:-len(END)] + "\n    indented first line\n- rule\n" + END + "\n"
          and "﻿" not in (read(claude_md) or ""), (rc, read(claude_md)))
    check("the same source leaves the user's text around the block in the other project",
          (read(keep_md) or "").startswith(before_text) and (read(keep_md) or "").endswith(END + after_text), read(keep_md))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over %d cases" % (len(failures), ran[0]))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
