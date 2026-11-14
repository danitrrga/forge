"""The ignore block of the framework step: the lines that keep a project's framework documents tracked and what the
framework generates or creates out of `git status`.

The framework keeps a project's working documents (markdown and tsv) under <project>/.fwx/. They are the project's
memory and must be tracked, but a project's own `*.md` rule ignores every one of them, and nothing ignores the
worktrees the framework creates under .claude/worktrees/, so the main checkout looks dirty and the framework's own
"clean tree" checks refuse to run. For a project with `framework: true`, forge/framework.py has this module keep ONE
block (forge/gitblock.py) at the END of the project's .gitignore, because a negation only works after the rule it
negates:

    # BEGIN FORGE-FWX (managed by forge, do not edit inside)
    !/.fwx/**/*.md           the documents; the narrow form keeps a project's own `/.fwx/subprojects/*/private/`
                             ignored (`!/.fwx/**` re-exposed it)
    !/.fwx/**/*.tsv          the project's memory; a `*.tsv` rule, or a `*` allowlist, ignores it
    /.claude/<plugin>.json   generated; it used to be one claimed line of its own, which the block folds in
    /.claude/worktrees/      where the framework creates its worktrees
    # END FORGE-FWX

Everything between the markers is forge's: a sync rewrites a block that differs from what forge writes (and says so),
an uninstall or a project going back to `framework: false` removes it. The lines the project has outside are never
touched.

Where the block sits is the project's to decide about everything but its end. Lines the project added after the block
are left alone while git still answers as wanted for four sample paths (.fwx/x/y.md and .fwx/decisions.tsv not
ignored, .claude/<plugin>.json and .claude/worktrees/x ignored, by `git check-ignore -v --no-index`); when a later
line breaks one, the block is moved to the end and the line says so. A project whose rules the block cannot beat (a
later `.fwx/`) is a `!` line naming the path and the rule, never a silent success.

What git answers is asked of ONE function (_outcome), for the sync and for forge doctor alike, so the two cannot disagree:
a scratch repository with the project's real layout holds the .gitignore of every directory from the repository's root
down to the project and the three under it that the sample paths walk through (.fwx/, .claude/, .claude/worktrees/), the
repository's own .git/info/exclude, and the ignore file git reads for `core.excludesFile` (the default
$XDG_CONFIG_HOME/git/ignore when unset), each as the bytes it has (a file that is not UTF-8 is copied, not refused), and
the candidate in place of the file that is being written, so a dry-run decides what an apply would. The scratch reads no
other git config and none of the caller's GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE. The global ignore file is the
machine's own setting: when it is what decides a sample (the rule reads `global ignore <file>:N:pattern`), the `!` line
says so as the cause, since no block in the project can change it and another clone has its own. When git cannot be asked
(no scratch directory, a git that does not answer or answers with an error, a file that cannot be read) that is a `!`
line saying what was not checked and nothing is written, never a success. The scratch directory is removed on every way
out, SIGTERM and Ctrl-C included.

A project with `framework_ignore_block: false` has none of this: its framework documents are kept out of the repository's
history on purpose (a second history, say), so forge writes no block, runs no probe, removes one it wrote earlier and prints one
SKIP line (`switched_off`); the exit code does not depend on it.

A project with `writes_tracked_files: false` owns its .gitignore: forge never writes it. The block goes to
.git/info/exclude (anchored to the project's place in the repository), which only this clone reads, and git ranks
a .gitignore rule above one there, so a `*.md` of the repo's .gitignore, or of one above it, still wins over the `!`
line (measured: git check-ignore says `.gitignore:N:*.md`). The un-ignore then holds only if the repo's own
.gitignore carries the block, and the step says so with a `!` line naming the fix. When the repo's own rules already
give the wanted answer, nothing is written to the exclude file. The exclude file is one for the whole repository, so
each project keeps its own block in it, tagged with its place (forge/gitblock.py), and a run, an uninstall or a
project going back to `framework: false` touches only its own.

Markers that are not one complete pair are a `!` line naming `file:line` and nothing is written (forge/gitblock.py).
The block is a claim (forge/owned.py, item ["block", "FORGE-FWX"], with the tag as a third element in the exclude
file), found through the registry by its owner and its place, so a project that never had one costs no git call.

Limits, stated and not fixed: with `framework_ignore_block: false` nothing ignores the generated .claude/<plugin>.json
or .claude/worktrees/ (the project's own ignore rules do, or its owner adds the lines); a project moved to another
directory of its repository leaves its old block in .git/info/exclude until `forge uninstall NAME` or a hand edit
(an owner that is the same in two projects cannot be told apart, so a sync does not guess); two projects that name the
same project path and the same `project` are one project to the ownership record, and nothing validates against that."""
import collections
import contextlib
import os
import shutil
import signal
import subprocess
import tempfile

from forge import gitblock, lib, owned

PART = "framework"
Out = collections.namedtuple("Out", "ok lines")  # ok: .claude/<plugin>.json is ignored once this has run
Wrong = collections.namedtuple("Wrong", "path want rule")  # a sample git answers otherwise than wanted, and the rule that decides
# What the scratch repository is made of: where the project sits in it ("" or "sub/dir/"), {directory: .gitignore} from the
# repository's top down to the project (the project's own included), the repository's info/exclude, {path under the project:
# .gitignore} for the directories the samples walk through, the global ignore file (its bytes, and its real path). A body
# is bytes as read, or a str for the candidate.
Layout = collections.namedtuple("Layout", "at chain exclude below glob gpath")

# The four sample paths and whether git must ignore each: a document of the framework in a nested folder, a tsv
# file, the generated file, something inside a worktree.
SAMPLES = ((".fwx/x/y.md", False), (".fwx/decisions.tsv", False), (".claude/%s.json", True), (".claude/worktrees/x", True))
BELOW = (".fwx/.gitignore", ".claude/.gitignore", ".claude/worktrees/.gitignore")  # the project's .gitignore files the samples walk through
GLOBAL = "global ignore "  # a rule from the global ignore file starts so (_outcome rewrites its source)
_SCRATCH_VARS = dict(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)


def _probe(cwd, plugin, env, cfg=()):
    """The samples git (run in `cwd`, a scratch repository, with `env`) answers otherwise than wanted, as Wrong rows
    (empty: all as wanted), or None when git cannot answer: it did not run, or it said something other than ignored (0)
    or not ignored (1). `rule` is `source:line:pattern` from check-ignore -v, "no rule" when none decides."""
    wrong = []
    for sample, want in SAMPLES:
        rel = sample % plugin if "%s" in sample else sample
        try:
            r = subprocess.run(["git", "-C", cwd] + list(cfg) + ["-c", "core.quotePath=false", "check-ignore", "-v", "--no-index", "--", rel],
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


def _where(ppath):
    """(the repository's top, where the project sits in it as "" or "sub/dir/"), found without a fork, or None when
    `ppath` is in no repository."""
    g = lib.git_dir(ppath)[0]
    if g is None:
        return None
    top = os.path.dirname(g)
    rel = os.path.relpath(os.path.abspath(ppath), top)
    return top, "" if rel == "." else rel.replace(os.sep, "/") + "/"


def _read_bytes(path):
    """The bytes of an ignore file in the tree, or None when there is none or it is a link (git does not read one).
    Raises lib.Unreadable for any other failure."""
    if os.path.islink(path):
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as e:
        raise lib.Unreadable(path, str(e)) from e


def _chain(top, at):
    """{directory ("" or "a/b/"): the bytes of its .gitignore} for every directory from the repository's top down to the
    project at `at` that has one. Raises lib.Unreadable."""
    levels, here = [""], ""
    for part in at.split("/")[:-1] if at else []:
        here += part + "/"
        levels.append(here)
    chain = {}
    for lv in levels:
        body = _read_bytes(os.path.join(top, lv, ".gitignore"))
        if body is not None:
            chain[lv] = body
    return chain


def _real_exclude(ppath, top):
    """(known, the bytes of the repository's own .git/info/exclude: None for none or a link), read where git keeps it.
    Not known when .git is a file (a linked worktree) and git does not say where the exclude file is."""
    g = os.path.join(top, ".git")
    f = os.path.join(g, "info", "exclude") if os.path.isdir(g) else (lib.exclude_site(ppath, ".fwx") or (None,))[0]
    return (False, None) if f is None else (True, _read_bytes(f))


def _global_ignore(ppath):
    """(known, path, bytes) of the file git reads as the global ignore of the project at `ppath`: core.excludesFile of
    git's own config (asked of git, so every config layer counts), else $XDG_CONFIG_HOME/git/ignore, else
    ~/.config/git/ignore. Bytes None when there is no such file. Not known when git does not answer or the file cannot be read."""
    try:
        r = subprocess.run(["git", "-C", ppath, "config", "--path", "--get", "core.excludesFile"],
                           capture_output=True, text=True, timeout=20, env=lib.git_env())
    except Exception:
        return False, None, None
    if r.returncode == 0 and r.stdout.strip():
        gp = r.stdout.strip()
    elif r.returncode == 1:
        gp = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "git", "ignore")
    else:
        return False, None, None
    try:
        with open(gp, "rb") as fh:
            return True, gp, fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return True, gp, None
    except OSError:
        return False, None, None


def _layout(ppath, top, at):
    """The Layout of the project's real state, or None when part of it cannot be known. Raises lib.Unreadable."""
    chain = _chain(top, at)
    known, exclude = _real_exclude(ppath, top)
    gknown, gpath, glob = _global_ignore(ppath)
    if not known or not gknown:
        return None
    below = {rel: b for rel in BELOW for b in [_read_bytes(os.path.join(ppath, rel))] if b is not None}
    return Layout(at, chain, exclude, below, glob, gpath)


def _terminate(signum, frame):
    raise SystemExit(128 + signum)  # a SystemExit, so the scratch directory's `finally` runs


@contextlib.contextmanager
def _scratch():
    """A scratch directory that is removed on every way out, a SIGTERM (a hook's timeout) and Ctrl-C included: the
    signal becomes an exit while the directory exists, and is let through once it is gone."""
    top = tempfile.mkdtemp(prefix="forge-fwx-")
    try:
        old = signal.signal(signal.SIGTERM, _terminate)
    except ValueError:  # not the main thread: no handler to put
        old = None
    try:
        yield top
    finally:
        late = []
        if old is not None:
            signal.signal(signal.SIGTERM, lambda signum, frame: late.append(signum))
        shutil.rmtree(top, ignore_errors=True)
        if old is not None:
            signal.signal(signal.SIGTERM, old)
            if late:
                os.kill(os.getpid(), signal.SIGTERM)


def _put(path, body):
    if body is None:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(body if isinstance(body, bytes) else body.encode("utf-8"))


def _outcome(lay, plugin):
    """The samples git answers otherwise than wanted (_probe's rows) for the project laid out as `lay`, asked of a scratch
    repository: no git config but the global ignore file is read, so the answer is the layout's. None when it cannot be
    asked. The one function that decides whether the framework's documents are ignored, for the sync and for the doctor."""
    try:
        with _scratch() as top:
            env = lib.git_env(**_SCRATCH_VARS)
            subprocess.run(["git", "init", "-q", top], capture_output=True, check=True, timeout=20, env=env)
            proj = os.path.join(top, lay.at) if lay.at else top
            os.makedirs(proj, exist_ok=True)
            for lv, body in lay.chain.items():
                _put(os.path.join(top, lv, ".gitignore"), body)
            _put(os.path.join(top, ".git", "info", "exclude"), lay.exclude)
            for rel, body in lay.below.items():
                _put(os.path.join(proj, rel), body)
            gscratch = os.path.join(top, ".git", "forge-global-ignore")
            _put(gscratch, lay.glob if lay.glob is not None else b"")
            wrong = _probe(proj, plugin, env, ["-c", "core.excludesFile=" + gscratch])
            if wrong:
                wrong = [w._replace(rule=GLOBAL + (lay.gpath or "") + w.rule[len(gscratch):]) if w.rule.startswith(gscratch + ":") else w
                         for w in wrong]
            return wrong
    except (OSError, subprocess.SubprocessError):
        return None


def check(ppath, plugin):
    """_outcome of the project's real state, what forge doctor asks: the samples git answers otherwise than wanted (empty:
    none), None when it cannot be asked or the project is in no repository. Raises lib.Unreadable."""
    where = _where(ppath)
    lay = None if where is None else _layout(ppath, *where)
    return None if lay is None else _outcome(lay, plugin)


def _claimed_line(file, line, text):
    """True when `file`'s record holds the ignore line `line` as forge's own (part framework) and a line of `text`
    is it now: the single line an earlier forge wrote for the generated file."""
    for c in owned.previous(file, PART)[0]:
        if owned.is_line(c) and c["at"][1] == line:
            return owned.current(file, c, text)[0]
    return False


def _without_lines(text, line, tag=""):
    """`text` minus the lines equal to `line` that lie outside the block."""
    s = gitblock.span(text, tag)
    return "".join(l for i, l in enumerate(text.splitlines(keepends=True))
                   if l.strip() != line or (s is not None and s[0] <= i <= s[1]))


def _fix(repo_owned):
    if repo_owned:
        return ("a rule of the repo's own .gitignore ranks above .git/info/exclude, so the project must carry the block itself: "
                "the lines between `%s` and `%s` at the end of its .gitignore" % (gitblock.BEGIN, gitblock.END))
    return ("the block un-ignores only the .fwx markdown and tsv files, and forge adds no wider line (it would re-expose the "
            "project's own narrower rules): change or narrow that rule in the project's .gitignore")


def _says(wrong):
    return ", ".join("git %s %s (%s)" % ("does not ignore" if w.want else "still ignores", w.path, w.rule) for w in wrong)


SWITCHED_OFF = ("   framework -> ignore block: NOT RUN, NOT ARMED: framework_ignore_block is false in the project (the project keeps "
                "its framework documents out of this git on purpose), so forge writes and checks no FORGE-FWX block; the generated "
                "file is written as always, and ignoring it and .claude/worktrees/ is the project's own")
OWN_WAY_OUT = ('; or, if the repository keeps .fwx out of its history on purpose, set "framework_ignore_block": false in the '
               'project')


def advice(wrong, repo_owned):
    """What to do about the samples in `wrong`, for the `!` line of the sync and the doctor's FAIL alike: a rule of the
    global ignore file is the machine's own, which no block in the project changes; any other is the project's."""
    mine = [w for w in wrong if not w.rule.startswith(GLOBAL)]
    theirs = [w for w in wrong if w.rule.startswith(GLOBAL)]
    out = []
    if mine:
        out.append(_fix(repo_owned) + OWN_WAY_OUT)
    if theirs:
        out.append("%s is this machine's own setting (a global ignore file): no block in the project changes it, and another "
                   "clone has its own" % theirs[0].rule.split(":", 1)[0][len(GLOBAL):])
    return "; and ".join(out)


def switched_off(apply, ppath, owner):
    """The lines for a project with `framework_ignore_block: false`: one SKIP line (a feature the user switched off), then
    what drop says about a block forge wrote earlier, which goes as it does for `framework: false`. No probe, no block
    written, and nothing here counts as an error."""
    return [SWITCHED_OFF] + drop(apply, ppath, owner)


def _cannot(ppath):
    """Fail closed: what could not be checked, and that nothing was written."""
    return Out(False, ["   ! framework -> %s: the ignore block NOT written: could not check what git does with the project's ignore "
                       "rules (no scratch repository, git did not answer or answered with an error, or it did not say where "
                       "info/exclude is) -- NOT RUN, NOT ARMED, so not counted as done" % lib.short(ppath)])


def ensure(apply, ppath, plugin, repo_owned, owner):
    """Keep forge's block in the project's ignore file and say what was done: Out(ok, lines). `ok` is whether git
    ignores .claude/<plugin>.json once this has run, so the caller writes that file only then. Raises lib.Unreadable
    for an ignore file that cannot be read (the caller says so as it does for any .gitignore)."""
    entry = ".claude/%s.json" % plugin
    gi = os.path.join(ppath, ".gitignore")
    where = _where(ppath)
    if where is None:
        return Out(True, ["   framework -> %s FORGE-FWX block (no repo, no gitignore)" % lib.short(gi)])
    top, at = where
    prefix, tag = "", ""
    if repo_owned:
        site = lib.exclude_site(ppath, ".fwx")
        if site is None or os.path.islink(site[0]):
            return Out(False, ["   ! framework -> the ignore block NOT written: git does not say where info/exclude is, or it is a link"])
        target, prefix = site[0], site[1][1:-len(".fwx")]
        tag = at = prefix  # the exclude file is the repository's: one block per project, told apart by its place
    elif os.path.islink(gi):
        # git does not read a .gitignore that is a link and forge never writes through one: only git's answer counts.
        lay = _layout(ppath, top, at)
        wrong = None if lay is None else _outcome(lay, plugin)
        if wrong is None:
            return _cannot(ppath)
        lines = ["   framework -> %s FORGE-FWX block (.gitignore is a link, left alone: forge never writes through one)" % lib.short(gi)]
        if wrong:
            lines.append("   ! framework -> %s: .gitignore is a symlink, which git does not read: %s -- %s"
                         % (lib.short(ppath), _says(wrong), advice(wrong, False)))
        return Out(not any(w.path == entry for w in wrong), lines)
    else:
        target = gi
    lay = _layout(ppath, top, at)
    if lay is None:
        return _cannot(ppath)
    cur = lib.read_text(target)
    text = cur or ""
    err = gitblock.marker_error(text, tag)
    if err:
        return Out(False, ["   ! framework -> %s:%d: %s -- the file is left as it is, and so is the framework in this project"
                           % (lib.short(target), err[0], err[1])])
    bl = gitblock.lines_for(plugin, prefix, tag)
    old = "/" + prefix + entry if repo_owned else entry
    folded = _claimed_line(target, old, text)
    body = _without_lines(text, old, tag) if folded else text
    has = gitblock.span(body, tag) is not None

    def outcome(t):
        """What git answers when the file being written reads `t`."""
        return _outcome(lay._replace(exclude=t) if repo_owned else lay._replace(chain={**lay.chain, at: t}), plugin)

    notes = []
    if repo_owned and not has and not folded:
        wrong = outcome(text)
        if wrong is None:
            return _cannot(ppath)
        if wrong == []:
            # The repo's own rules already give the wanted answer: nothing for this clone to add.
            return Out(True, ["   framework -> %s FORGE-FWX block (already current: the repo's own ignore rules give the wanted answer, "
                              "nothing to add in .git/info/exclude)" % lib.short(target)])
    if has and gitblock.held(body, tag) != gitblock.text_of(bl):
        notes.append("the block differed from what forge writes: rewritten (everything between the markers is forge's)")
    new = gitblock.replace(body, bl, tag) if has else gitblock.append(body, bl)
    wrong = outcome(new)
    if wrong is None:
        return _cannot(ppath)
    if has and wrong and any(l.strip() for l in gitblock.after(new, tag)):
        # a line after the block re-ignores something it un-ignores: the end is the one place a negation works
        first = wrong[0]
        new = gitblock.append(gitblock.without(new, tag), bl)
        notes.append("moved to the end of the file: a later line decided %s (%s)" % (first.path, first.rule))
        wrong = outcome(new)
        if wrong is None:
            return _cannot(ppath)
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
    owned.claim_ignore_block(apply, target, bl, PART, owner, wrote, (old,) if folded else (), tag)
    lines = ["   framework -> %s FORGE-FWX block (%s%s)" % (lib.short(target), state, "".join("; " + n for n in notes))]
    if wrong:
        lines.append("   ! framework -> %s: after the block %s -- %s" % (lib.short(ppath), _says(wrong), advice(wrong, repo_owned)))
    return Out(not any(w.path == entry for w in wrong), lines)


def _own_sites(ppath):
    """{(real path of the file, tag)} where the project at `ppath` keeps its block: its own .gitignore (no tag) and its
    repository's .git/info/exclude (tagged with the project's place in it). A linked worktree's exclude file is where
    git says, which costs a fork."""
    sites = {(os.path.realpath(os.path.join(ppath, ".gitignore")), "")}
    where, g = _where(ppath), lib.git_dir(ppath)[0]
    if where is not None:
        if os.path.isdir(g):
            sites.add((os.path.realpath(os.path.join(g, "info", "exclude")), where[1]))
        else:
            site = lib.exclude_site(ppath, ".fwx")
            if site:
                sites.add((os.path.realpath(site[0]), where[1]))
    return sites


def drop(apply, ppath, owner):
    """Take out the blocks this module claimed for `owner` in the project's .gitignore and, the one tagged with the
    project's place, in its repository's .git/info/exclude, while their markers are whole: the lines to print. Everything between the markers is forge's, so
    an edited block goes too; one with broken markers is left and named. The claim goes in either case (as
    framework._drop_stale does for the generated file). Nothing claimed, nothing said, and no git process: the registry
    knows what to look at."""
    mine = [(f, c) for f, cs in sorted(owned.load()[0].items()) for c in cs
            if c.get("part") == PART and owned.is_block(c) and c["owner"] == owner]
    if not mine:
        return []
    sites, out = _own_sites(ppath), []
    for f, c in mine:
        tag = owned.block_tag(c)
        if (os.path.realpath(f), tag) not in sites:  # another project's block, though the owner's name is the same
            continue
        try:
            text = lib.read_text(f)
        except lib.Unreadable as e:
            out.append("  ! framework -> %s could not be read (%s): its block claim stays" % (lib.short(f), e.reason))
            continue
        found, value = owned.current(f, c, text) if text is not None else (False, None)
        if found and owned.block_removable(c, value):
            new = gitblock.without(text, tag)
            out.append("   framework -> %s FORGE-FWX block (%s)" % (lib.short(f), "removed" if apply else "would remove"))
            if apply:
                if new:
                    lib.write_text(f, new, mode="keep")
                else:
                    lib.unlink(f)
        elif found:
            out.append("  ! framework -> %s FORGE-FWX block has broken markers, left in place" % lib.short(f))
        owned.release_block(apply, f, PART, tag)
    return out
