#!/usr/bin/env python3
"""sync_system_doc.py on a toy world: forge/ (lib, the script, the canonical doc, profiles), home/
and projects/ side by side, each project a git repo.

- A plain project gets the doc copy, the .gitignore line and the CLAUDE.md pointer.
- A project whose .gitignore is a symlink gets no doc: git does not read a symlinked .gitignore,
  so the copy would land un-ignored (ensure_ignored's contract: nothing under the entry when it
  answers False). Seen failing on a58e21f: "symlinked .gitignore: the doc was
  written True, the link kept True, lines ['  ~ toy  copy:AGENT-SYSTEM.md, SKIP-gitignore(a
  symlink, which git does not read):.gitignore, ...']" -- the copy ran before the ignore check.
- A frozen project gets nothing, with its repo-owned CLAUDE.md byte-identical. With
  the frozen skip disabled it gets the doc: "the frozen project was written".
- An --apply refused by lib.may_write (the toy settings.json names another checkout) writes
  nothing and says it is a dry-run.
- A malformed profile (`{broken`, `null`, a list) is named once and skipped; the good profiles'
  output is byte-identical to a world without it, and the toy still gets its doc. The dry-run and
  the apply each exit 1 for the '!' lines (the exit rule, see run()); they exited 0 before the fix.
  Seen failing before the fix, every profile json.loaded unguarded:
  "malformed profiles: exit 1, 0
  '! could not read' line(s), good output unchanged False, doc False: ... json.decoder.
  JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)".
- A CLAUDE.md that is a symlink (here to a real AGENTS.md holding the user's own rules), or a
  hard link to AGENTS.md, is not written through: the pointer and AGENTS.md steps are skipped
  with a SKIP-claude-md entry, the same in the dry-run and the apply. Seen failing on b6222aa:
  "CLAUDE.md -> AGENTS.md: AGENTS.md a link True, text None, CLAUDE.md -> 'AGENTS.md',
  dry '  ~ toy  copy:AGENT-SYSTEM.md, gitignore:.gitignore, append-pointer:CLAUDE.md,
  SKIP-agents-md(non-forge content):AGENTS.md', apply '  ~ toy  copy:AGENT-SYSTEM.md,
  gitignore:.gitignore, append-pointer:CLAUDE.md, agents-md-symlink:AGENTS.md'" -- the pointer
  landed in the real AGENTS.md, which was then replaced by a link to CLAUDE.md, a loop; and
  "hard-linked CLAUDE.md: text '# my rules\\n', one inode False, dry ... apply ..." -- the write
  split the pair, and CLAUDE.md alone got the pointer.
- A doc copy that holds the wanted text with CRLF line ends, or with a stray non-UTF-8 byte, is
  reported as `copy` and rewritten. Seen failing on a78637a, the copy compared in text
  mode: "CRLF doc copy: exit 0, rewritten False, dry '  = toy                  up to date'" and
  "non-UTF-8 doc copy: exit 0, rewritten False, dry \"  ! toy                  ERROR: 'utf-8' codec
  can't decode byte 0xff in position 0: invalid start byte -- skipped, other projects unaffected\"".
- Two profiles that name one project_path both run, and a profile is tagged and scoped by its file
  name, not its `project` field. Seen failing on a78637a, projects keyed by path with
  the field as the name: "two profiles, one project_path: exit 0, lines ['  ~ toy2 ...']: ...
  managed projects: 2 (1 repo-owned)" (the last profile won), and "profile whose project field is
  not its file name: exit 0: ... managed projects: 2 (1 repo-owned) | | | 0 change(s) would apply."
  (`--project toy` scoped the run to a project named `other`, so to nothing).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "tests"))
import sandbox  # noqa: E402
from sandbox import tail  # noqa: E402

SCRIPT = os.path.join("scripts", "sync", "sync_system_doc.py")
DOC = os.path.join(".claude", "AGENT-SYSTEM.md")
BEGIN = re.search(r'^BEGIN = "(.*)"$', open(os.path.join(sandbox.FORGE, SCRIPT), encoding="utf-8").read(), re.M).group(1)
NOTE = "IMPORTANT USER NOTE: never commit the staging database.\n"
# CLAUDE.md files whose BEGIN marker is not forge's block: quoted in prose, or an orphan on a line of its own.
STRAY = {"stray-prose": "# app\n\nforge puts its block between %s markers.\n\n" % BEGIN + NOTE,
         "stray-orphan": "# app\n\n%s\n\n" % BEGIN + NOTE}
BAD = {"broken.claude.json": "{broken", "null.claude.json": "null", "list.claude.json": "[1]"}


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def world(case):
    t = sandbox.mkdtemp("sysdoc-test-")
    WORLDS[t] = case
    root, home, projects = (os.path.join(t, d) for d in ("forge", "home", "projects"))
    sandbox.mini_root(root, SCRIPT, os.path.join("forge", "owned.py"))  # the script claims what it creates
    # The canonical doc is the fixture's, never this checkout's docs/AGENT-SYSTEM.md, which a checkout without
    # docs/ lacks: red before, on a copy_engine copy in a toy HOME (M1), "FileNotFoundError: [Errno 2] No such
    # file or directory: '.../docs/AGENT-SYSTEM.md'" from mini_root's copy. The cases compare copies of it with
    # the doc they wrote, never with its text.
    os.makedirs(os.path.join(root, "docs"))
    shutil.copy(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "AGENT-SYSTEM.md"), os.path.join(root, "docs", "AGENT-SYSTEM.md"))
    os.makedirs(home)
    for name, extra in (("toy", {}), ("portal", {"frozen": True, "writes_tracked_files": False})):
        pp = os.path.join(projects, name)
        os.makedirs(pp)
        sandbox.git(pp, "init", "-q")
        write(os.path.join(root, "config", "profiles", name + ".claude.json"),
              json.dumps(dict({"project": name, "project_path": pp}, **extra)))
    write(os.path.join(projects, "portal", "CLAUDE.md"), "# portal, owned by its repo\n")
    # Its own .gitignore covers the doc, so unfrozen it WOULD get a copy: the freeze check can fail.
    write(os.path.join(projects, "portal", ".gitignore"), ".claude/AGENT-SYSTEM.md\n")
    if case == "gitignore-symlink":
        write(os.path.join(t, "shared-gitignore"), "node_modules/\n")
        os.symlink(os.path.join(t, "shared-gitignore"), os.path.join(projects, "toy", ".gitignore"))
    elif case == "malformed":
        for name, text in BAD.items():
            write(os.path.join(root, "config", "profiles", name), text)
    elif case == "claude-symlink":
        write(os.path.join(projects, "toy", "AGENTS.md"), "# my rules\n")
        os.symlink("AGENTS.md", os.path.join(projects, "toy", "CLAUDE.md"))
    elif case == "claude-hardlink":
        write(os.path.join(projects, "toy", "AGENTS.md"), "# my rules\n")
        os.link(os.path.join(projects, "toy", "AGENTS.md"), os.path.join(projects, "toy", "CLAUDE.md"))
    elif case in STRAY:
        write(os.path.join(projects, "toy", "CLAUDE.md"), STRAY[case])
    elif case == "refused":
        write(os.path.join(t, "other", "bin", "forge"), "")
        sandbox.installed_settings(home, os.path.join(t, "other"))
    elif case == "shared-path":
        write(os.path.join(root, "config", "profiles", "toy2.claude.json"),
              json.dumps({"project": "toy2", "project_path": os.path.join(projects, "toy")}))
    elif case == "renamed":
        write(os.path.join(root, "config", "profiles", "toy.claude.json"),
              json.dumps({"project": "other", "project_path": os.path.join(projects, "toy")}))
    return t


def text(p):
    """p's content, or None when it cannot be read (a link loop raises ELOOP)."""
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def toy_line(t, out):
    """The toy project's line, the verb that differs between a dry-run and an apply left out."""
    return [l.replace(t, "<toy>") for l in out.splitlines() if l.startswith("  ~ toy ") or l.startswith("  = toy ")]


def snapshot(d):
    out = {}
    for base, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != ".git"]
        for n in files:
            p = os.path.join(base, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, d)] = hashlib.sha256(f.read()).hexdigest()
    return out


BANG = re.compile(r"(?m)^\s*!")
RULE = []  # runs that broke the exit rule, reported as failures by main()
WORLDS = {}  # toy root -> its case name


def run(t, *args):
    """The script over every profile, or over the one a --project in `args` names (it wins over --all).
    Every run is held to forge/sync.py agent_config's exit rule, which this step keeps too: a line
    whose first non-space character is '!' means exit 1, and no other line does. Red on 0ad2214,
    whose main() always returned None: "exit rule: malformed: exit 0, first '!' line
    '  ! could not read <t>/forge/config/profiles/broken.claude.json: Expecting property name
    enclosed in double quotes: line 1 column 2 (char 1)'", the same for the malformed --apply."""
    r = subprocess.run([sys.executable, os.path.join(t, "forge", SCRIPT), "--all"] + list(args), cwd=t,
                       env=sandbox.bare_env(os.path.join(t, "home"), t), capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    bang = BANG.search(out)
    if bool(bang) != (r.returncode != 0):
        RULE.append("exit rule: %s%s: exit %d, %s" % (
            WORLDS.get(t, "?"), "".join(" " + a for a in args), r.returncode,
            "first '!' line %r" % out[bang.start():].lstrip("\n").splitlines()[0].replace(t, "<t>") if bang
            else "no '!' line"))
    return r.returncode, out


def main():
    failures = []
    projects = lambda t: os.path.join(t, "projects")

    t = world("plain")
    before = snapshot(os.path.join(projects(t), "portal"))
    rc, out = run(t, "--apply")
    toy = os.path.join(projects(t), "toy")
    gi = open(os.path.join(toy, ".gitignore")).read() if os.path.exists(os.path.join(toy, ".gitignore")) else ""
    if rc or not os.path.isfile(os.path.join(toy, DOC)) or ".claude/AGENT-SYSTEM.md" not in gi.splitlines() \
            or not os.path.isfile(os.path.join(toy, "CLAUDE.md")):
        failures.append("plain project: exit %d, doc %s, .gitignore %r: %s"
                        % (rc, os.path.isfile(os.path.join(toy, DOC)), gi, tail(out)))
    if snapshot(os.path.join(projects(t), "portal")) != before:
        failures.append("the frozen project was written: %s" % tail(out))

    t = world("gitignore-symlink")
    rc, out = run(t, "--apply")
    toy = os.path.join(projects(t), "toy")
    lines = [l for l in out.splitlines() if " toy " in l]
    if os.path.exists(os.path.join(toy, DOC)) or not os.path.islink(os.path.join(toy, ".gitignore")) \
            or open(os.path.join(t, "shared-gitignore")).read() != "node_modules/\n":
        failures.append("symlinked .gitignore: the doc was written %s, the link kept %s, lines %r"
                        % (os.path.exists(os.path.join(toy, DOC)), os.path.islink(os.path.join(toy, ".gitignore")), lines))

    t = world("refused")
    before = snapshot(projects(t))
    rc, out = run(t, "--apply")
    if snapshot(projects(t)) != before or "MODE: DRY-RUN" not in out or "would apply" not in out:
        failures.append("refused apply: projects changed %s: %s" % (snapshot(projects(t)) != before, tail(out)))

    # The good profiles' output must not move: compared, with the '!' lines dropped, to a plain world's.
    plain = world("plain")
    _, plain_out = run(plain)
    t = world("malformed")
    rc, out = run(t)
    named = [l for l in out.splitlines() if l.startswith("  ! could not read ")]
    same = [l for l in out.replace(t, "@T@").splitlines() if not l.startswith("  ! could not read ")] \
        == plain_out.replace(plain, "@T@").splitlines()
    rc_apply, out_apply = run(t, "--apply")
    doc = os.path.isfile(os.path.join(projects(t), "toy", DOC))
    if (rc, rc_apply) != (1, 1) or sorted(os.path.basename(l.split(": ")[0].split()[-1]) for l in named) != sorted(BAD) \
            or not same or not doc:
        failures.append("malformed profiles: exit %d and %d, %d '! could not read' line(s), good output unchanged %s, "
                        "doc %s: %s" % (rc, rc_apply, len(named), same, doc, tail(out + out_apply)))

    # CLAUDE.md -> AGENTS.md: nothing is written through the link, and the dry-run says what the
    # apply does. The doc copy and the .gitignore line do not depend on CLAUDE.md and still happen.
    t = world("claude-symlink")
    toy = os.path.join(projects(t), "toy")
    _, dry = run(t)
    rc, out = run(t, "--apply")
    agents, claude = os.path.join(toy, "AGENTS.md"), os.path.join(toy, "CLAUDE.md")
    link = os.readlink(claude) if os.path.islink(claude) else None
    ok = (not rc and not os.path.islink(agents) and text(agents) == "# my rules\n" and link == "AGENTS.md"
          and toy_line(t, dry) == toy_line(t, out) and os.path.isfile(os.path.join(toy, DOC))
          and any("SKIP-claude-md(a symlink" in l for l in toy_line(t, out)))
    if not ok:
        failures.append("CLAUDE.md -> AGENTS.md: AGENTS.md a link %s, text %r, CLAUDE.md -> %r, dry %r, apply %r"
                        % (os.path.islink(agents), text(agents), link, " ".join(toy_line(t, dry)),
                           " ".join(toy_line(t, out))))

    # The same file under two names without a symlink: a hard link. Writing CLAUDE.md through a
    # temp file and a rename splits the pair; the SKIP keeps them one file.
    t = world("claude-hardlink")
    toy = os.path.join(projects(t), "toy")
    _, dry = run(t)
    rc, out = run(t, "--apply")
    agents, claude = os.path.join(toy, "AGENTS.md"), os.path.join(toy, "CLAUDE.md")
    one = os.path.samefile(agents, claude)
    if rc or not one or text(agents) != "# my rules\n" or toy_line(t, dry) != toy_line(t, out) \
            or not any("SKIP-claude-md(the same file as AGENTS.md)" in l for l in toy_line(t, out)):
        failures.append("hard-linked CLAUDE.md: text %r, one inode %s, dry %r, apply %r"
                        % (text(agents), one, " ".join(toy_line(t, dry)), " ".join(toy_line(t, out))))

    # A doc copy that differs from the wanted text only in its bytes is rewritten: CRLF line ends
    # (read in text mode they compared equal), and a stray non-UTF-8 byte (the read raised).
    for what, damage in (("CRLF", lambda b: b.replace(b"\n", b"\r\n")), ("non-UTF-8", lambda b: b"\xff" + b)):
        t = world("plain")
        run(t, "--apply")
        doc_path = os.path.join(projects(t), "toy", DOC)
        with open(doc_path, "rb") as f:
            good = f.read()
        with open(doc_path, "wb") as f:
            f.write(damage(good))
        _, dry = run(t)
        rc, out = run(t, "--apply")
        with open(doc_path, "rb") as f:
            now = f.read()
        if rc or not any("copy:AGENT-SYSTEM.md" in l for l in toy_line(t, dry)) or now != good:
            failures.append("%s doc copy: exit %d, rewritten %s, dry %r"
                            % (what, rc, now == good, " ".join(l for l in dry.splitlines() if " toy " in l)))

    # Two profiles naming one directory both run; one path used to key a dict and the last one won.
    t = world("shared-path")
    rc, out = run(t)
    lines = [l for l in out.splitlines() if l.startswith("  ~ toy ") or l.startswith("  ~ toy2 ")]
    if rc or len(lines) != 2 or "managed projects: 3 (1 repo-owned)" not in out:
        failures.append("two profiles, one project_path: exit %d, lines %r: %s" % (rc, lines, tail(out, 25)))

    # A profile is named by its file, as --project and the session scope name it, not by its field.
    t = world("renamed")
    rc, out = run(t, "--project", "toy")
    if rc or not any(l.startswith("  ~ toy ") for l in out.splitlines()) or " other " in out:
        failures.append("profile whose project field is not its file name: exit %d: %s" % (rc, tail(out, 25)))

    # A CLAUDE.md with a BEGIN that opens no block (quoted in prose, or an orphan) keeps every byte of the
    # user's text through two syncs, and is named on a '  ! ' line: ensure_pointer replaced from the first BEGIN
    # to the first END, so the second sync took the user's note with it. Red on 34c191b: see the commit body.
    # The control: one complete pair around the user's text is still replaced in place, the text outside kept.
    for case in sorted(STRAY):
        t = world(case)
        toy = os.path.join(projects(t), "toy", "CLAUDE.md")
        _, dry = run(t)
        run(t, "--apply")
        rc, out = run(t, "--apply")
        got = text(toy)
        named = [l for l in out.splitlines() if l.startswith("  !") and "CLAUDE.md" in l]
        dry_says = any(l.startswith("  !") and "CLAUDE.md" in l for l in dry.splitlines())
        if got != STRAY[case] or not named or not rc or not dry_says:
            failures.append("%s: file unchanged after 2 --apply %s, '  ! ' line naming CLAUDE.md %s, exit %d, "
                            "dry-run says it %s, got %r" % (case, got == STRAY[case], bool(named), rc, dry_says, got))
    t = world("plain")
    toy = os.path.join(projects(t), "toy", "CLAUDE.md")
    run(t, "--apply")
    block = text(toy)
    write(toy, "# mine\n\n" + block.replace("Shared agent-config system", "Old title") + "\n" + NOTE)
    rc, out = run(t, "--apply")
    got = text(toy)
    if rc or got != "# mine\n\n" + block + "\n" + NOTE:
        failures.append("one complete pair is replaced in place, the text around it kept: exit %d, got %r" % (rc, got))

    failures += RULE
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over 14 cases" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
