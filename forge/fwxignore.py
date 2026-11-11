"""The ignore block of the framework step: the lines that keep a project's framework documents tracked and what the
framework generates or creates out of `git status`.

The framework keeps a project's working documents (markdown and tsv) under <project>/.fwx/. They are the project's
memory and must be tracked, but a project's own `*.md` rule ignores every one of them, and nothing ignores the
worktrees the framework creates under .claude/worktrees/, so the main checkout looks dirty and the framework's own
"clean tree" checks refuse to run. For a profile with `framework: true`, forge/framework.py has this module keep ONE
block (forge/gitblock.py) at the END of the project's .gitignore, because a negation only works after the rule it
negates:

    # BEGIN FORGE-FWX (managed by forge)
    !/.fwx/**/*.md           the documents; the tsv files need no line (no rule ignores them), and the narrow form
                             keeps a project's own `/.fwx/subprojects/*/private/` ignored (`!/.fwx/**` re-exposed it)
    /.claude/<plugin>.json   generated; it used to be one claimed line of its own, which the block folds in
    /.claude/worktrees/      where the framework creates its worktrees
    # END FORGE-FWX

Where the block sits is the project's to decide about everything but its end. Lines the project added after the block
are left alone while git still answers as wanted for four sample paths (.fwx/x/y.md and .fwx/decisions.tsv not
ignored, .claude/<plugin>.json and .claude/worktrees/x ignored, by `git check-ignore -v --no-index`, asked of a
scratch repository holding the candidate file so a dry-run decides what an apply would); when a later line breaks one,
the block is moved to the end and the line says so. A project whose rules the block cannot beat (a later `.fwx/`) is
a `!` line naming the path and the rule, never a silent success.

A profile with `writes_tracked_files: false` owns its .gitignore: forge never writes it. The block goes to
.git/info/exclude (anchored to the project's place in the repository), which only this clone reads, and git ranks
a .gitignore rule above one there, so a `*.md` of the repo's .gitignore still wins over the `!` line (measured: git
check-ignore says `.gitignore:N:*.md`). The un-ignore then holds only if the repo's own .gitignore carries the block,
and the step says so with a `!` line naming the fix. When the repo's own rules already give the wanted answer, nothing
is written to the exclude file.

Markers that are not one complete pair are a `!` line naming `file:line` and nothing is written (forge/gitblock.py).
The block is a claim (forge/owned.py, item ["block", "FORGE-FWX"]), so `forge uninstall` and a profile going back to
`framework: false` take out exactly the block, while it still reads as forge wrote it: the lines of the project's own,
identical ones outside the markers included, stay."""
import collections
import contextlib
import os
import subprocess
import tempfile

from forge import gitblock, lib, owned

PART = "framework"
Out = collections.namedtuple("Out", "ok lines")  # ok: .claude/<plugin>.json is ignored once this has run
Wrong = collections.namedtuple("Wrong", "path want rule")  # a sample git answers otherwise than wanted, and the rule that decides

# The four sample paths and whether git must ignore each: a document of the framework in a nested folder, a tsv
# file, the generated file, something inside a worktree.
SAMPLES = ((".fwx/x/y.md", False), (".fwx/decisions.tsv", False), (".claude/%s.json", True), (".claude/worktrees/x", True))
_SCRATCH_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)


def _probe(cwd, plugin, env=None):
    """The samples git (run in `cwd`) answers otherwise than wanted, as Wrong rows (empty: all as wanted), or None
    when git cannot answer. `rule` is `source:line:pattern` from check-ignore -v, "no rule" when none decides."""
    wrong = []
    for sample, want in SAMPLES:
        rel = sample % plugin if "%s" in sample else sample
        try:
            r = subprocess.run(["git", "-C", cwd, "-c", "core.quotePath=false", "check-ignore", "-v", "--no-index", "--", rel],
                               capture_output=True, text=True, timeout=20, env=env)
        except Exception:
            return None
        if r.returncode not in (0, 1):
            return None
        rule = r.stdout.split("\t")[0].strip() if r.stdout.strip() else "no rule"
        # With -v, a path matched by a negation (`!pattern`) exits 0 too, but it is not ignored.
        got = r.returncode == 0 and not rule.split(":", 2)[-1].startswith("!")
        if got != want:
            wrong.append(Wrong(rel, want, rule))
    return wrong


def check(ppath, plugin):
    """_probe of the project itself, with whatever ignore sources the machine has: what forge doctor asks."""
    return _probe(ppath, plugin)


def _outcome(prefix, gitignore, exclude, plugin):
    """_probe of a scratch repository holding `gitignore` as the project's .gitignore and `exclude` as .git/info/exclude
    (either None for none), the project at `prefix` in it. No machine or user config is read, so the answer is the
    candidate's alone. The directory is removed however this ends."""
    try:
        with tempfile.TemporaryDirectory(prefix="forge-fwx-") as top:
            subprocess.run(["git", "init", "-q", top], capture_output=True, check=True, timeout=20, env=_SCRATCH_ENV)
            proj = os.path.join(top, prefix) if prefix else top
            os.makedirs(proj, exist_ok=True)
            for name, body in ((os.path.join(proj, ".gitignore"), gitignore), (os.path.join(top, ".git", "info", "exclude"), exclude)):
                if body is not None:
                    os.makedirs(os.path.dirname(name), exist_ok=True)
                    with open(name, "w", encoding="utf-8", newline="") as fh:
                        fh.write(body)
            return _probe(proj, plugin, _SCRATCH_ENV)
    except (OSError, subprocess.SubprocessError):
        return None


def _claimed_line(file, line, text):
    """True when `file`'s record holds the ignore line `line` as forge's own (part framework) and a line of `text`
    is it now: the single line an earlier forge wrote for the generated file."""
    for c in owned.previous(file, PART)[0]:
        if owned.is_line(c) and c["at"][1] == line:
            return owned.current(file, c, text)[0]
    return False


def _without_lines(text, line):
    """`text` minus the lines equal to `line` that lie outside the block."""
    s = gitblock.span(text)
    return "".join(l for i, l in enumerate(text.splitlines(keepends=True))
                   if l.strip() != line or (s is not None and s[0] <= i <= s[1]))


def _fix(repo_owned):
    if repo_owned:
        return ("a rule of the repo's own .gitignore ranks above .git/info/exclude, so the project must carry the block itself: "
                "the lines between `%s` and `%s` at the end of its .gitignore" % (gitblock.BEGIN, gitblock.END))
    return "no line from the end of the file can beat that rule: change or narrow it in the project's .gitignore"


def _says(wrong):
    return ", ".join("git %s %s (%s)" % ("does not ignore" if w.want else "still ignores", w.path, w.rule) for w in wrong)


def ensure(apply, ppath, plugin, repo_owned, owner):
    """Keep forge's block in the project's ignore file and say what was done: Out(ok, lines). `ok` is whether git
    ignores .claude/<plugin>.json once this has run, so the caller writes that file only then. Raises lib.Unreadable
    for an ignore file that cannot be read (the caller says so as it does for any .gitignore)."""
    entry = ".claude/%s.json" % plugin
    gi = os.path.join(ppath, ".gitignore")
    if not lib.in_git_repo(ppath):
        return Out(True, ["   framework -> %s FORGE-FWX block (no repo, no gitignore)" % lib.short(gi)])
    prefix, other = "", None
    if repo_owned:
        site = lib.exclude_site(ppath, ".fwx")
        if site is None or os.path.islink(site[0]):
            return Out(False, ["   ! framework -> the ignore block NOT written: git does not say where info/exclude is, or it is a link"])
        target, prefix = site[0], site[1][1:-len(".fwx")]
        other = None if os.path.islink(gi) else lib.read_text(gi)
    elif os.path.islink(gi):
        # git does not read a .gitignore that is a link and forge never writes through one: only git's answer counts.
        wrong = _probe(ppath, plugin)
        if wrong is None or any(w.path == entry for w in wrong):
            return Out(False, ["   ! framework -> the ignore block NOT written: .gitignore is a symlink, which git does not read and "
                               "forge never writes through; it does not ignore %s" % entry])
        return Out(True, ["   framework -> %s FORGE-FWX block (.gitignore is a link, left alone: git already ignores %s)" % (lib.short(gi), entry)])
    else:
        target = gi
    cur = lib.read_text(target)
    text = cur or ""
    err = gitblock.marker_error(text)
    if err:
        return Out(False, ["   ! framework -> %s:%d: %s -- the file is left as it is, and so is the framework in this project"
                           % (lib.short(target), err[0], err[1])])
    bl = gitblock.lines_for(plugin, prefix)
    old = "/" + prefix + entry if repo_owned else entry
    folded = _claimed_line(target, old, text)
    body = _without_lines(text, old) if folded else text
    has = gitblock.span(body) is not None

    def outcome(t):
        return _outcome(prefix, other if repo_owned else t, t if repo_owned else None, plugin)

    notes, wrong = [], None
    if repo_owned and not has and not folded and outcome(text) == []:
        # The repo's own rules already give the wanted answer: nothing for this clone to add.
        return Out(True, ["   framework -> %s FORGE-FWX block (already current: the repo's own ignore rules give the wanted answer, "
                          "nothing to add in .git/info/exclude)" % lib.short(target)])
    new = gitblock.replace(body, bl) if has else gitblock.append(body, bl)
    if has and any(l.strip() for l in gitblock.after(new)):
        wrong = outcome(new)
        if wrong:  # a line after the block re-ignores something it un-ignores: the end is the one place a negation works
            first = wrong[0]
            new = gitblock.append(gitblock.without(new), bl)
            notes.append("moved to the end of the file: a later line decided %s (%s)" % (first.path, first.rule))
            wrong = outcome(new)
    elif new != text:
        wrong = outcome(new)
    if folded:
        notes.append("folded the single %s line into it" % old)
    wrote = new != text
    verb = "update" if has else "create"
    state = "already current" if not wrote else verb[:-1] + "ed" if apply else "would " + verb
    if repo_owned:
        notes.append("in .git/info/exclude: the un-ignore of .fwx/ holds only in this clone")
    if apply and wrote:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        lib.write_text(target, new, mode="keep" if cur is not None else None)
    owned.claim_ignore_block(apply, target, bl, PART, owner, wrote, (old,) if folded else ())
    lines = ["   framework -> %s FORGE-FWX block (%s%s)" % (lib.short(target), state, "".join("; " + n for n in notes))]
    if wrong:
        lines.append("   ! framework -> %s: after the block %s -- %s" % (lib.short(ppath), _says(wrong), _fix(repo_owned)))
    return Out(not any(w.path == entry for w in wrong or []), lines)


def drop(apply, ppath, owner):
    """Take out the block this module claimed in the project's .gitignore and in .git/info/exclude, while it is still what
    forge wrote: the lines to print. One edited since is the project's: it stays, and is named. The claim goes in either
    case (as framework._drop_stale does for the generated file). Nothing is claimed, nothing is said."""
    files = [os.path.join(ppath, ".gitignore")]
    site = lib.exclude_site(ppath, ".fwx") if lib.in_git_repo(ppath) else None
    if site is not None:
        files.append(site[0])
    out = []
    for f in files:
        mine = [c for c in owned.previous(f, PART)[0] if owned.is_block(c)]
        if not mine:
            continue
        try:
            text = lib.read_text(f)
        except lib.Unreadable as e:
            out.append("  ! framework -> %s could not be read (%s): its block claim stays" % (lib.short(f), e.reason))
            continue
        found, value = owned.current(f, mine[0], text) if text is not None else (False, None)
        if found and owned.removable(mine[0], value):
            new = gitblock.without(text)
            out.append("   framework -> %s FORGE-FWX block (%s)" % (lib.short(f), "removed" if apply else "would remove"))
            if apply:
                if new:
                    lib.write_text(f, new, mode="keep")
                else:
                    lib.unlink(f)
        elif found:
            out.append("  ! framework -> %s FORGE-FWX block was edited by hand, left in place" % lib.short(f))
        owned.release_block(apply, f, PART)
    return out
