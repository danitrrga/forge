#!/usr/bin/env python3
"""The session skill's review text: the verdict page is never waited on, a rejection stops for a question, and the commands it names exist.

Plain Python, no network: it reads skills/session/ of the checkout it sits in (`python3 tests/test_session_text.py [ROOT]` reads another
tree) and runs that tree's `bin/fwx --help` for the command list. Commands that only exist on another branch (`walk` on the UI-walk
branch, `open` on master) are SKIPped with their reason printed, never silently; the rest must exist.

Seen red on the untouched branch (text before this change; the six FAIL lines, 22 checks looked at):
  FAIL: no 'verdict wait' in skills/session -> references/ui-review.md
  FAIL: no '--serve' in skills/session -> references/ui-review.md
  FAIL: no 'xdg-open' in skills/session -> SKILL.md, references/ui-review.md
  FAIL: ui-review.md names 'redo' -> missing
  FAIL: ui-review.md names 'not_defect' -> missing
  FAIL: ui-review.md asks before the revert -> no 'revert it?' before the first '--revert'
Each check also has a control on a toy text (the "control:" checks): a text with 'verdict wait' must fail the removed-string check, and a text
that reverts before it asks must fail the ask-first check.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.realpath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SESSION = os.path.join(ROOT, "skills", "session")
fails, skips, looked = [], [], [0]

# Commands that only exist on a branch this one does not contain yet; each is SKIPped with its reason.
ELSEWHERE = {
    "walk": "the UI-walk branch (feat/3.5-ui-walk)",
    "open": "master once `fwx open` lands",
}


def check(name, ok, detail=""):
    looked[0] += 1
    if not ok:
        fails.append("FAIL: %s -> %s" % (name, detail))


def read(rel):
    with open(os.path.join(SESSION, rel), encoding="utf-8") as f:
        return f.read()


def files_naming(needle, texts):
    return [rel for rel, text in texts.items() if needle in text]


def asks_before_revert(text):
    ask, flag = text.find("revert it?"), text.find("--revert")
    return ask != -1 and (flag == -1 or ask < flag)


def fwx_commands(text):
    """Top-level `fwx <name>` words; `fwx:execute` (a workflow) has a colon and is not one."""
    return set(re.findall(r"\bfwx ([a-z][a-z-]*)\b", text))


def main():
    texts = {rel: read(rel) for rel in ("SKILL.md", os.path.join("references", "ui-review.md"))}
    review = texts[os.path.join("references", "ui-review.md")]

    # The session never waits on the page and hands the owner files through `fwx open`.
    for gone in ("verdict wait", "--serve", "xdg-open"):
        named = files_naming(gone, texts)
        check("no '%s' in skills/session" % gone, not named, ", ".join(named))

    # What the review text must say.
    for word in ("review-answers", "redo", "not_defect"):
        check("ui-review.md names '%s'" % word, word in review, "missing")
    check("ui-review.md asks before the revert", asks_before_revert(review), "no 'revert it?' before the first '--revert'")

    # Every command the two files name exists, or is skipped with its reason.
    out = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "--help"], capture_output=True, text=True)
    check("fwx --help ran", out.returncode == 0, out.stderr.strip())
    known = {m.group(1) for m in re.finditer(r"^  ([a-z][a-z-]*)\s", out.stdout, re.M)}
    check("fwx --help lists commands", len(known) > 5, "listed %d" % len(known))
    named = set()
    for text in texts.values():
        named |= fwx_commands(text)
    check("the files name some fwx commands", len(named) > 5, "named %d" % len(named))
    for cmd in sorted(named):
        if cmd in known:
            check("fwx %s exists" % cmd, True)
        elif cmd in ELSEWHERE:
            skips.append("SKIP: fwx %s not checked: it lives on %s" % (cmd, ELSEWHERE[cmd]))
        else:
            check("fwx %s exists" % cmd, False, "not in `fwx --help`")

    # control: the checks above can fail.
    check("control: 'verdict wait' is caught", files_naming("verdict wait", {"x.md": "run verdict wait in the background"}) == ["x.md"])
    check("control: revert before the question fails", not asks_before_revert("run wave prepare --revert 1, then ask: revert it?"))
    check("control: question before the revert passes", asks_before_revert("ask: revert it? Then wave prepare --revert 1"))
    check("control: a command that does not exist is not known", "frobnicate" not in known and "frobnicate" in fwx_commands("run fwx frobnicate now"))


main()
for line in skips:
    print(line)
for line in fails:
    print(line)
print("%d checks looked at, %d failed, %d skipped" % (looked[0], len(fails), len(skips)))
sys.exit(1 if fails else 0)
