#!/usr/bin/env python3
"""worktree_guard.py — PreToolUse hook. An agent in a linked worktree writes only inside
that worktree, to scratch (/tmp, $TMPDIR) or to a folder its profile names, and a worktree it
creates goes under the main checkout's .claude/worktrees/ (or a folder its profile names).
Outside a linked worktree it only keeps the project's new worktrees there. Exit 2 + stderr blocks.

forge's copy of the downstream project's .claude/hooks/worktree_guard.py at 77d2255e, made
neutral (a research note on worktree guards). Run as
`python3 <forge>/hooks/worktree_guard.py --project NAME`, the entry the profile's
`worktree_guard` line wires (forge/skills.py). Each call reads <forge>/config/profiles/NAME.claude.json:
  * project_path: the project's main checkout, whose worktrees the placement rule keeps. Not
    CLAUDE_PROJECT_DIR, and not this file's folder, which is forge.
  * worktree_guard: true, or an object (its `on` decides only whether forge wires the hook):
      write_roots    [{"path": ...} or {"prefix": ...}, each with its "why"]: folders outside the
                     worktree it may write to. A prefix is every folder whose name starts so and
                     goes on (`~/.cache/elp-` gives ~/.cache/elp-<name>/). The downstream project's two
                     exceptions, its shared notes and its ~/.cache/elp-*/, are this parameter.
      worktree_dirs  [{"path": ...} or {"prefix": ...}, each with its "why"]: where the project's
                     worktrees may live besides <main checkout>/.claude/worktrees. A worktree goes
                     directly under a path; a prefix names the worktree folder itself, so
                     `/tmp/sv-` admits /tmp/sv-<name> and nothing deeper (GSD's code fixer makes
                     its worktree with `mktemp -d /tmp/sv-<phase>-reviewfix-XXXXXX`).
    Paths are absolute or ~/..., compared resolved, so a symlink inside one that points out is
    refused like any other outside write.
A profile that cannot be read or has a wrong shape is a crash of this hook: refused inside a
worktree, allowed outside.

Ported from GSD Core's worktree path guard (MIT, Copyright (c) 2026 Open GSD):
https://github.com/open-gsd/gsd-core/blob/9af595ccc1b1780a55f503ac5fd092289eeb4dd3/hooks/gsd-worktree-path-guard.js
GSD added it because executors "sometimes issue Edit/Write calls with absolute paths
rooted at the MAIN repository instead of the worktree", and the prose rule telling them
not to "is never enforced because the model under load skips it".

Kept from GSD Core: a linked worktree is recognised by its git dir sitting under
`.git/worktrees/`; in the main checkout, a submodule and a path outside any repository no
write is contained; the target is resolved before it is compared (`..` cannot climb out); a target
that does not exist yet is judged by where it would land; a write into a repository's
git internals is refused; the path field is read typed, so a non-string cannot crash the
hook into an allow.

Changed, each on purpose:
  * GSD acts only on `agent-*` / `worktree-agent-*` branches. That would make it a no-op
    in any worktree whose branch was renamed, the downstream project's day-5 worktree among them. Here
    every linked worktree counts: each one has a single writer.
  * GSD allows any write outside a git repository (~/anything). Here only the worktree,
    scratch, the profile's write_roots and the /dev sinks a redirect uses are allowed.
  * GSD reads only Edit, Write and MultiEdit. NotebookEdit (`notebook_path`) and the Bash
    tool's writes are read too: redirects, tee, cp, mv (both ends), ln, rsync, install,
    rm, touch, truncate, mkdir, sed -i, dd of=, and a nested `sh -c '...'`; since Codex's
    run of also downloads and unpacks (curl -o/-O/--output-dir, wget -O/-P/-o and
    a bare wget, tar -x into -C or the cwd and tar -c into -f, unzip -d or the cwd), the
    commands inside $(...), backticks, <(...) and >(...), quoted or not, and an interpreter's
    inline code or heredoc (python, node, perl, ruby, deno, bun, php) that writes a literal
    absolute or ~ path (see interpreter_writes).
  * GSD compares `git rev-parse --show-toplevel` of the file and the worktree, two git
    spawns a call. Here the worktree is read from its `.git` file and the target is
    compared by realpath, which also resolves a symlink inside the worktree that points
    out of it. No subprocess.
  * The worktree's own `.git` file is refused too. Rewriting it to point at the main
    repository's git dir would turn the worktree into "not a worktree", and this hook off.
  * GSD fails open on a crash. Here a crash inside a linked worktree blocks the write and
    says so, since a write the hook could not judge is the case it exists for; anywhere
    else it allows, so a bug cannot stop the main checkout's sessions. When the crash is
    in reading which checkout the cwd is (a NUL in it, a `.git` file that is half-written
    or not UTF-8), the cwd's spelling decides: under a .claude/worktrees/ folder it
    blocks, elsewhere it allows. A worktree made outside that folder and whose `.git` file
    is unreadable is therefore let through.
  * The location rule is new: `git worktree add` and `git worktree move` in THE PROFILE'S
    project repository must land directly under <main checkout>/.claude/worktrees/ or a
    worktree_dirs folder, from a worktree and from the main checkout alike (Portal,
    supervising session). It is the only thing this hook does outside a
    worktree. It touches no other command and no other repository: a scratch repository
    in /tmp or a scratch folder makes its worktrees wherever it likes. In the downstream project it
    refused 6 of 9,343 recorded commands, all scratch verification worktrees made in /tmp and ~/dev.
    Since the downstream project's review the target is read through `$(mktemp -d ...)`
    (a template, -p DIR, --tmpdir, -t, bare) and `$(pwd)`, in an assignment of the same command or
    inline, and a target it cannot read (a variable set outside the command, any other command's
    output, in any folder of the path) is refused instead of let through: `wt=$(mktemp -d)` had
    passed unchecked, because shlex cut the assignment in two words and walk() recorded only a
    one-word one. Replayed over the 17,034 distinct recorded commands that run from a worktree
    or name `worktree` (49 add or move one), it refused none the hook before allowed.
    Round 10 closed three more ways past it: a `git worktree add` inside $(...), backticks or <(...)
    is judged like the bare command; a `-C` it cannot read is taken for the cwd's repository; and a
    command's output in the target's last name is refused (`$(printf ../../x)`, a branch `feature/x`).
    Left open: a bare unknown $VAR in the last name, whose value may hold a `/`; and a scratch
    repository reached by an unreadable `-C` from this project's checkout, which is refused with it.
    GSD workspaces (`~/gsd-workspaces/<ws>/<repo>`) sit two folders below their root, which
    neither a path (direct child) nor a prefix (the worktree folder itself) admits. A `depth`
    on a path entry (`{"path": "~/gsd-workspaces", "depth": 2, "why": ...}`) fits them and keeps
    the rule exact; a prefix spanning any depth would also admit a worktree nested in another.
    Not built: no ~/gsd-workspaces folder exists on this machine.
  * Folders outside the worktree are writable only when the profile's write_roots names
    them. Claude's memory folder stays blocked.

The Bash reading copies the shell parser of the downstream project's guard_tool_use.py at d8cc6912 (the
quote-aware segment cut, pipes, prefix words, nested shells, `cd` and `NAME=` followed
within one command; the wrappers with their options, `timeout 5`, `nice -n 5`, `command -p`, `stdbuf -oL`,
`env -i`, `sudo -u root`, as of 2bb8472). It is copied, not imported, so this hook stands alone. Like the guard,
it is a pattern check and does not close every shape.

Where the line is. This hook stops an agent's mistakes, not an adversary: the case it exists
for is a path copied from the main checkout into a write. So it reads every shape an agent
writes such a path in (the list above), and judges nothing that is not written: a read of
the main checkout is never refused, inside an interpreter's code included (`open('/main/a')`
beside `open('out', 'w')` passes; the command guard's coarser rule, any write-ish code naming
the path, would refuse it). A replay of the 15,722 distinct Bash commands recorded from a
worktree cwd in this machine's transcripts refused none that the hook before
these shapes allowed, once the downstream project's ~/.cache/elp-*/ was given as its write_roots prefix;
the two shapes it first refused (`d + '/ticket.yml'`, `homedir() + '/.cache/x'`, read as
absolute paths) are cases now.

Known limits (from the downstream project's list, day-5 batch 1, less what a later round closed):
  * Not seen, so allowed: an interpreter writing a path it computes (`open(base + '/x', 'w')`,
    a variable, an argv) or a script file it runs (`python3 tool.py`, `node x.mjs`); a path
    method on an expression (`Path(a).rename('/x')`); other archivers and downloaders (7z,
    rsync's remote form, scp, git clone into a path); a `cd` inside a command substitution;
    git acting on the main checkout (`git -C <main> reset --hard`, and `checkout`, `commit` or
    `stash` there; `git --work-tree=`); a target that starts with a variable set outside the
    command; `find -exec`; and a `cd` in an earlier Bash call when the harness keeps the
    shell's directory. Claude Code resets a subagent's directory between calls, and refuses
    git commands aimed outside an isolated worktree on its own. A text guard cannot close
    these: real containment is Claude Code's sandbox (Portal, supervising session,
    after Codex's review of PR #30).
  * Refused, though it may be meant: a `node_modules` (or any folder) symlinked into the
    worktree from the main checkout. The target is compared by realpath, so a write
    through the link lands in the main checkout and is blocked, as the `link-to-main`
    case pins. A lane that links node_modules instead of installing its own hits this on
    every install.

The payload's `cwd` is the anchor, not CLAUDE_PROJECT_DIR: a subagent in a worktree runs
the main checkout's hooks, so that variable names the main checkout.
"""
import bisect
import collections
import json
import os
import re
import shlex
import sys

SHELL_TOOLS = {"Bash", "run_shell_command", "shell"}
# Tool name -> the field that holds the path it writes.
FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path", "write_file": "file_path", "replace": "file_path"}
HOME = os.path.realpath(os.path.expanduser("~"))
# Redirect sinks that are not files. Judged by spelling, before realpath: /dev/stdout
# resolves through /proc to wherever fd 1 points.
DEV_SINKS = re.compile(r"^/dev/(?:null|stdout|stderr|tty|fd/\d+)$")
PROFILES = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "config", "profiles")
PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# The profile's worktree_guard keys, and the fields each entry of a list may name besides "why".
PARAM_KEYS = {"on": None, "write_roots": ("path", "prefix"), "worktree_dirs": ("path", "prefix")}


# What the profile says: root (the main checkout), write_roots and write_prefixes (resolved, a
# prefix as <resolved parent>/<stem>), worktree_dirs (resolved, .claude/worktrees first) and
# worktree_prefixes (as write_prefixes).
Config = collections.namedtuple("Config", "root write_roots write_prefixes worktree_dirs worktree_prefixes")


CFG = None  # set in main() from the profile, before any rule reads it


def tilde(p):
    """p with a leading ~ read as the shell reads it: `~` and `~/...` are this HOME, `~name/...`
    that user's home, and `~name` naming no user is left as written (a relative file). Joining
    HOME to the rest turned `~notes.txt` into /home/<user>notes.txt (Codex)."""
    if p == "~" or p.startswith("~/"):
        return HOME + p[1:]
    return os.path.expanduser(p) if p.startswith("~") else p


def _absolute(p, where):
    p = tilde(p)
    if not os.path.isabs(p):
        raise ValueError("%s %r is neither absolute nor ~/..." % (where, p))
    return p


def load_config(argv):
    """The Config of the profile named by `--project NAME`; ValueError says what is wrong."""
    if len(argv) != 2 or argv[0] != "--project":
        raise ValueError("arguments %r; the only ones are --project NAME" % (argv,))
    if not PROFILE_NAME.match(argv[1]):
        raise ValueError("%r is not a profile name" % argv[1])
    path = os.path.join(PROFILES, argv[1] + ".claude.json")
    try:
        with open(path, encoding="utf-8") as fh:
            prof = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError("%s cannot be read (%s)" % (path, e))
    pp = prof.get("project_path") if isinstance(prof, dict) else None
    if not isinstance(pp, str) or not os.path.isabs(pp):
        raise ValueError("%s has no absolute project_path" % path)
    repo = checkout_of(pp)
    if not repo:
        raise ValueError("%s: project_path %s is in no git checkout" % (path, pp))
    root = main_root(repo[2])
    params = prof.get("worktree_guard", False)
    params = {} if isinstance(params, bool) else params
    if not isinstance(params, dict):
        raise ValueError("%s: worktree_guard is neither a boolean nor an object" % path)
    unknown = sorted(k for k in params if k not in PARAM_KEYS and not k.startswith("_"))
    if unknown or not isinstance(params.get("on", True), bool):
        raise ValueError("%s: worktree_guard has unknown key(s) %s or a non-boolean on; the keys are %s"
                         % (path, unknown, sorted(PARAM_KEYS)))
    roots, prefixes, dirs, dir_prefixes = [], [], [os.path.join(root, ".claude", "worktrees")], []
    for key, fields in PARAM_KEYS.items():
        if not fields:
            continue
        entries = params.get(key, [])
        if not isinstance(entries, list):
            raise ValueError("%s: worktree_guard.%s is not a list" % (path, key))
        for e in entries:
            field = [f for f in fields if isinstance(e, dict) and f in e]
            if (len(field) != 1 or set(e) != {field[0], "why"}
                    or not all(isinstance(v, str) and v.strip() for v in e.values())):
                raise ValueError("%s: each worktree_guard.%s entry is {%s, \"why\"} with non-empty strings, got %r"
                                 % (path, key, " or ".join('"%s"' % f for f in fields), e))
            p = _absolute(e[field[0]], "worktree_guard.%s %s" % (key, field[0]))
            if field[0] == "prefix":
                stem = os.path.basename(p)
                if not stem:
                    raise ValueError("%s: worktree_guard.%s prefix %r ends in /, not in a name"
                                     % (path, key, e["prefix"]))
                (prefixes if key == "write_roots" else dir_prefixes).append(
                    os.path.join(os.path.realpath(os.path.dirname(p)), stem))
            else:
                (roots if key == "write_roots" else dirs).append(os.path.realpath(p))
    return Config(root, roots, prefixes, dirs, dir_prefixes)


def in_prefix(real, prefix):
    """real is <prefix><name> or lies under it, with a non-empty name."""
    return real.startswith(prefix) and bool(real[len(prefix):].split("/", 1)[0])


def scratch_roots():
    """Where a worktree agent may write besides its worktree. WORKTREE_GUARD_SCRATCH
    replaces the default list; only the test suite sets it, because its fixture repos
    live under /tmp and would otherwise all count as scratch."""
    override = os.environ.get("WORKTREE_GUARD_SCRATCH")
    roots = override.split(":") if override is not None else ["/tmp", os.environ.get("TMPDIR") or ""]
    return [os.path.realpath(r) for r in roots if r]


def deny(reason):
    sys.stderr.write("worktree_guard: BLOCKED - %s\n" % reason)
    sys.exit(2)


# ------------------------------------------------------------------ which checkout

def checkout_of(start):
    """(root, git_dir, common_dir, linked) for the checkout holding `start`, or None when
    no checkout holds it. A `.git` file that cannot be read, or holds no `gitdir:` line,
    raises: returning None would call a half-written worktree "no checkout" and allow."""
    d = os.path.realpath(start)
    while True:
        dot = os.path.join(d, ".git")
        if os.path.isdir(dot):
            return d, dot, dot, False
        if os.path.isfile(dot):
            with open(dot, encoding="utf-8") as fh:
                line = fh.readline().strip()
            if not line.startswith("gitdir:"):
                raise ValueError("%s holds no gitdir: line" % dot)
            git_dir = os.path.realpath(os.path.join(d, line[len("gitdir:"):].strip()))
            common = os.path.dirname(os.path.dirname(git_dir))
            try:
                with open(os.path.join(git_dir, "commondir"), encoding="utf-8") as fh:
                    common = os.path.realpath(os.path.join(git_dir, fh.read().strip()))
            except OSError:
                pass
            # A submodule's git dir is .git/modules/<name>: a checkout, but not a worktree.
            linked = "/worktrees/" in git_dir.replace("\\", "/")
            return d, git_dir, common, linked
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def main_root(common_dir):
    return os.path.dirname(common_dir) if os.path.basename(common_dir) == ".git" else common_dir


def inside(real, root):
    return real == root or real.startswith(root.rstrip("/") + "/")


def resolve(p, base):
    return os.path.realpath(os.path.join(base, tilde(p)))


def outside_reason(raw, base, wt):
    """Why writing `raw` (relative to `base`) leaves worktree `wt`; None when it does not."""
    if not raw:
        return None
    if DEV_SINKS.match(raw):
        return None
    real = resolve(raw, base)
    root, git_dir = wt
    if real == os.path.join(root, ".git") or inside(real, git_dir):
        return ("%s is this worktree's git metadata. Rewriting it would detach the "
                "worktree from its repository and switch this guard off." % raw)
    if (inside(real, root) or any(inside(real, r) for r in CFG.write_roots)
            or any(in_prefix(real, p) for p in CFG.write_prefixes)
            or any(inside(real, s) for s in scratch_roots())):
        return None
    return ("%s resolves to %s, outside this worktree (%s). An agent in a worktree writes "
            "only inside it, to /tmp scratch or to a folder the profile's worktree_guard.write_roots "
            "names. If the path came from the main checkout, rebuild it from this worktree's root."
            % (raw, real, root))


# ------------------------------------------------------------------ shell reading
# Copied from guard_tool_use.py at d8cc6912; see the module docstring for why.

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|(?<![>&])&(?![>&])|\n")
PIPE = re.compile(r"(?<!\|)\|(?!\|)")
RELOCATE_COMMANDS = {"mv", "cp", "ln", "rsync", "install"}
NESTING_SHELLS = ("bash", "sh", "zsh", "dash", "eval", "xargs")
GIT_VALUE_OPTS = ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env")
# A redirect operator; the target is read from the original text after it.
REDIRECT_OP = re.compile(r"(?:^|[^<>&0-9])(?:[0-9]?>>?|&>>?|>\|)\s*")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n")


def _quoted_spans(seg):
    spans, i, n = [], 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"":
            j = i + 1
            while j < n and seg[j] != c:
                j += 2 if (c == '"' and seg[j] == "\\") else 1
            spans.append((i, min(j, n - 1) + 1))
            i = j + 1
            continue
        i += 1
    return spans


def split_unquoted(text, pattern):
    spans, k, out, last = _quoted_spans(text), 0, [], 0
    for m in pattern.finditer(text):
        while k < len(spans) and spans[k][1] <= m.start():
            k += 1
        if k < len(spans) and spans[k][0] <= m.start():
            continue
        out.append(text[last:m.start()])
        last = m.end()
    return out + [text[last:]]


def drop_heredoc_bodies(cmd):
    """A heredoc body is data, not commands: a `> quoted line` in a commit message is not
    a redirect. The line that opens it stays, so `cat > f <<EOF` is still a write to f."""
    out, pos = [], 0
    for m in HEREDOC.finditer(cmd):
        if m.start() < pos:
            continue
        end = re.compile(r"^\s*" + re.escape(m.group(2)) + r"\s*$", re.M).search(cmd, m.end())
        out.append(cmd[pos:m.end()])
        pos = end.end() if end else len(cmd)
    return "".join(out) + cmd[pos:]


def split_words(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return None


SHELL_KEYWORDS = ("do", "then", "else", "if", "elif", "while", "until", "!")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# What runs another command after options of its own, with the short options that take a value (in
# the next word or stuck to the option) and the long ones that take it in the next word. Copied from
# guard_tool_use.py at 2bb8472 (round 9b item 1), minus xargs, which write_targets reads on its own:
# strip_prefix knew sudo, command, nohup, time, env and exec only without options, so `timeout 5 rm F`,
# `nice tee F` and `command -p cp a F` were read as the commands `timeout`, `nice` and `command`
# (round 10 lead).
WRAPPER_VALUE_OPTS = {
    "sudo": "ughpCDRTU", "env": "uCS", "nice": "n", "timeout": "sk", "exec": "a", "stdbuf": "ioe",
    "time": "fo", "ionice": "cnpPu", "setsid": "", "command": "", "nohup": "",
}
WRAPPER_LONG_VALUE = {"--user", "--group", "--host", "--prompt", "--chdir", "--chroot", "--unset", "--adjustment",
                      "--signal", "--kill-after", "--input", "--output", "--error", "--split-string"}


def command_words(words):
    """(NAME=value assignments, the command words, the wrappers passed, the directory a wrapper
    moves to) of a command: shell keywords, assignments (`LEFTHOOK=0 git ...`) and wrappers (sudo,
    env, command, nohup, time, exec, nice, timeout, stdbuf, ionice, setsid) are stepped over, each
    with its options. What env sets is the environment of the command after it."""
    assigns, wrappers, chdir = [], [], ""
    while words:
        w = words[0]
        name = os.path.basename(w)
        if w in SHELL_KEYWORDS:
            words = words[1:]
            continue
        if ASSIGNMENT.match(w):
            assigns.append(tuple(w.split("=", 1)))
            words = words[1:]
            continue
        if name not in WRAPPER_VALUE_OPTS:
            break
        wrappers.append(name)
        takes, i, options = WRAPPER_VALUE_OPTS[name], 1, True
        spliced = []
        while i < len(words):
            a = words[i]
            if a == "--" and options:
                options = False
                i += 1
            elif name == "env" and ASSIGNMENT.match(a):
                assigns.append(tuple(a.split("=", 1)))
                i += 1
            elif not options or not a.startswith("-") or a == "-":
                break
            elif a.startswith("--"):
                value = a.split("=", 1)[1] if "=" in a else (words[i + 1] if a in WRAPPER_LONG_VALUE and i + 1 < len(words) else "")
                if a.split("=", 1)[0] == "--chdir":
                    chdir = value
                elif a.split("=", 1)[0] == "--split-string":
                    spliced = split_words(value) or []
                i += 2 if "=" not in a and a in WRAPPER_LONG_VALUE else 1
            else:
                step = 1
                for j, c in enumerate(a[1:], 1):
                    if c in takes:
                        value = a[j + 1:] or (words[i + 1] if i + 1 < len(words) else "")
                        step = 1 if a[j + 1:] else 2
                        if (name, c) in (("env", "C"), ("sudo", "D")):
                            chdir = value
                        elif (name, c) == ("env", "S"):
                            spliced = split_words(value) or []
                        break
                i += step
        i += 1 if name == "timeout" and i < len(words) else 0  # timeout's DURATION
        words = spliced + words[i:]
    return assigns, words, wrappers, chdir


def strip_prefix(words):
    """Drop what runs a command without being it: shell keywords, assignments, and the wrappers of
    command_words."""
    return command_words(words)[1]


def git_subcommand(args):
    where, i = "", 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in GIT_VALUE_OPTS and i + 1 < len(args):
            if args[i] == "-C":
                where = os.path.join(where, args[i + 1])
            i += 2
        else:
            i += 1
    return where, args[i:]


def nested_bodies(words):
    if words and os.path.basename(words[0]) in NESTING_SHELLS:
        return [a for a in words[1:] if re.search(r"\s", a)]
    return []


def drop_comments(text):
    """A `#` that starts a word outside quotes comments out the rest of its line. Its
    apostrophes (`# don't`) would otherwise open a quote that swallows the next lines."""
    spans, out, i, k = _quoted_spans(text), [], 0, 0
    for m in re.finditer(r"(?:^|(?<=[\s;&|(]))#[^\n]*", text):
        # The spans and the matches both run left to right, so one pointer walks the spans
        # (`any()` over all of them for every match took 13 s at 10,000 commented lines).
        while k < len(spans) and spans[k][1] <= m.start():
            k += 1
        if k < len(spans) and spans[k][0] <= m.start():
            continue
        out.append(text[i:m.start()])
        i = m.end()
    return "".join(out) + text[i:]


def segments(text):
    """The commands of text, cut at ; && || & and newlines outside quotes. Unlike the
    guard, this hook does not also use the quote-blind cut: that cut turns an awk program
    (`'/x/{p=0}'`) or an arrow function in `node -e "..."` into redirects, and a false
    block here stops a worktree agent. Heredoc bodies and comments are removed first,
    which were the reason the guard kept it (replay of 9,343 recorded commands)."""
    return split_unquoted(text, SEGMENT_SPLIT)


REDIRECT_WORD = re.compile(r"^(?:\d*|&)(?:>>?|<<?<?|>\||>&|<&|&>>?)")


def strip_redirect_words(args):
    """shlex keeps `2>/dev/null` and `> f` as words; they are not a command's paths."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        m = REDIRECT_WORD.match(a)
        if m:
            skip = m.end() == len(a)
            continue
        out.append(a)
    return out


def redirect_targets(seg):
    """Redirect targets, with operators inside quotes ignored (`echo "a > b"`)."""
    masked = list(seg)
    for a, b in _quoted_spans(seg):
        for i in range(a + 1, b - 1):
            masked[i] = "x"
    masked = "".join(masked)
    out = []
    for m in REDIRECT_OP.finditer(masked):
        rest = seg[m.end():]
        if rest[:1] in ("'", '"'):
            q = rest[0]
            j = rest.find(q, 1)
            out.append(rest[1:j] if j > 0 else rest[1:])
        else:
            t = re.match(r"[^\s;&|<>()]+", rest)
            if t:
                out.append(t.group(0))
    return out


# touch and truncate: the options that take a value, which is not a path they write (a -r / --reference
# file is only read, a date or a size is no path at all), the short ones in a cluster (`-ar F`).
TOUCH_TRUNCATE_VALUES = {
    "touch": ("rdt", {"--reference", "--date", "--time"}),
    "truncate": ("rs", {"--reference", "--size"}),
}


def operands(args, values, long_values):
    """The words of args that are not an option or an option's value: `-r REF F` gives F,
    `-rREF F`, `--reference=REF F` and `--reference REF F` too."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            return out + args[i:]
        if a.startswith("--"):
            i += 1 if a in long_values and i < len(args) else 0
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch in values:
                    i += 1 if not a[k + 2:] and i < len(args) else 0
                    break
        else:
            out.append(a)
    return out


def sed_files(args):
    """The files of a `sed -i` command: its operands less the script. The script is the first operand,
    unless an option gave it (`-e SCRIPT`, `-f FILE`, `--expression=`, `--file=`, alone or at the end of
    a cluster), and each of those values is a word of its own that is no file written: `-e '/^x$/d'`
    is a script, not the path /^x$/d. In a cluster `i` takes the rest as the backup suffix."""
    files, scripted, i = [], False, 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            files += args[i:]
            break
        if a.startswith("--"):
            if a in ("--expression", "--file", "--line-length") and i < len(args):
                scripted = scripted or a != "--line-length"
                i += 1
            elif a.startswith(("--expression=", "--file=")):
                scripted = True
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch == "i":
                    break
                if ch in "efl":
                    scripted = scripted or ch != "l"
                    i += 1 if not a[k + 2:] and i < len(args) else 0
                    break
        else:
            files.append(a)
    return files if scripted else files[1:]


def write_targets(seg):
    """Paths one shell command writes, removes or moves, as far as its text shows."""
    out = redirect_targets(seg)
    for body in substitution_bodies(seg):
        for part in pieces(body):
            out += write_targets(part)
    # The command's own words are those of its first stage: the -i of `sed -n 5p f | grep -iE x` is
    # grep's. The later stages of a pipe are commands of their own (walk() and pieces() visit each).
    words = strip_prefix(split_words(split_unquoted(seg, PIPE)[0]) or [])
    if not words:
        return out
    cmd, args = os.path.basename(words[0]), strip_redirect_words(words[1:])
    paths = [a for a in args if not a.startswith("-")]
    if cmd in RELOCATE_COMMANDS:
        dest, srcs = paths[-1:], paths[:-1]
        for i, a in enumerate(args):
            m = re.match(r"^-[a-zA-Z]*t(.*)$", a) if cmd != "rsync" else None
            if (a == "--target-directory" or (m and not m.group(1))) and i + 1 < len(args):
                dest, srcs = [args[i + 1]], [p for p in paths if p != args[i + 1]]
            elif m and m.group(1):
                dest, srcs = [m.group(1)], paths
            elif a.startswith("--target-directory="):
                dest, srcs = [a.split("=", 1)[1]], paths
        out += dest
        # A move removes its sources from where they were.
        if cmd == "mv":
            out += srcs
    elif cmd in TOUCH_TRUNCATE_VALUES:
        out += operands(args, *TOUCH_TRUNCATE_VALUES[cmd])
    elif cmd in ("rm", "unlink", "shred", "rmdir", "tee", "mkdir"):
        out += paths
    elif cmd in ("sed", "perl") and any(re.match(r"^-[a-zA-Z]*i", a) or a.startswith("--in-place") for a in args):
        out += sed_files(args) if cmd == "sed" else paths
    elif cmd == "dd":
        out += [a[3:] for a in args if a.startswith("of=")]
    elif cmd in FETCHERS:
        # The whole segment is read too, pipes and all: `tar -cf - src | tar -xf -` is two commands.
        cut = next((k for k, a in enumerate(args) if a in ("|", "|&", "||", "&&", ";")), len(args))
        out += fetch_targets(cmd, args[:cut])
    for body in nested_bodies(words):
        for part in pieces(body):
            out += write_targets(part)
    if cmd == "xargs":
        rest = xargs_command(args)
        if rest:
            out += write_targets(shlex.join(rest))
    return out


def xargs_command(args):
    """The command xargs runs, after its own options: `xargs -I{} cp {} /x/` gives cp."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        i += 2 if a in ("-I", "-n", "-P", "-d", "-a", "-L", "-s", "-E", "-e", "--arg-file",
                        "--delimiter", "--max-args", "--max-procs") else 1
    return args[i:]


# Downloads and unpacks: which short options take a value (so a cluster stops there), and which
# options name what is written. curl and wget take `-` as stdout.
FETCHERS = {
    "curl": {"values": set("AbcCdDeEFHKmoPQrTtuUwxXyYz"), "out": ("o", "--output"),
             "dir": ("", "--output-dir")},
    "wget": {"values": set("eoaiBtOTwQPUDXIARl"), "out": ("O", "--output-document"),
             "dir": ("P", "--directory-prefix"), "log": ("o", "--output-file", "a", "--append-output")},
    "tar": {"values": set("fCbgHIKLNTVX"), "out": ("f", "--file"), "dir": ("C", "--directory")},
    "unzip": {"values": set("dx"), "dir": ("d", "")},
}


def options(args, values):
    """(letter or --long, value or None) for each option of args, short clusters split:
    `-fsSLo F` gives f, s, S, L, then ("o", "F"); `-oF` and `--output=F` carry their value."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") and len(a) > 2:
            name, eq, val = a.partition("=")
            out.append((name, val if eq else (args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("-") else None)))
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch in values:
                    rest = a[k + 2:]
                    out.append((ch, rest if rest else (args[i + 1] if i + 1 < len(args) else None)))
                    break
                out.append((ch, None))
        i += 1
    return out


def fetch_targets(cmd, args):
    """What a download or unpack writes: its output file or folder, or the folder it runs in
    (`.`) when it names none (`curl -O`, `wget URL`, `tar -x`, `unzip a.zip`)."""
    spec = FETCHERS[cmd]
    old_style = cmd == "tar" and args and not args[0].startswith("-")
    if old_style:   # `tar czf out.tgz src`: the first word is a cluster without its dash
        args = ["-" + args[0]] + args[1:]
    opts = options(args, spec["values"])
    named = lambda key: [v for k, v in opts if k in spec.get(key, ()) and k and v]  # noqa: E731
    outs = [v for v in named("out") if v != "-"]
    dirs = named("dir")
    if cmd == "curl":
        remote = any(k in ("O", "--remote-name", "--remote-name-all", "J", "--remote-header-name") for k, _ in opts)
        return outs + dirs + (["."] if remote and not dirs else [])
    if cmd == "wget":
        to_stdout = "-" in named("out")
        return outs + named("log") + dirs + (["."] if not outs and not dirs and not to_stdout else [])
    if cmd == "unzip":
        listing = any(k in ("l", "t", "p", "v", "Z") for k, _ in opts)
        return dirs or ([] if listing else ["."])
    letters = {k for k, _ in opts}
    if letters & {"x", "--extract", "--get"}:
        return dirs or ["."]
    if letters & {"c", "r", "u", "A", "--create", "--append", "--update", "--delete", "--concatenate"}:
        return outs
    return []


def substitution_bodies(seg):
    """The commands inside $(...), `...`, <(...) and >(...) of seg, outside single quotes and
    inside double quotes alike: `x=$(cp a /main/f)` and `echo "$(echo x > /main/f)"` write."""
    return [body for _, _, _, body in substitution_spans(seg)]


def substitution_spans(seg):
    """(kind, start, end, body) of each substitution of seg: kind is `$`, `` ` ``, `<` or `>`.
    $((...)) is arithmetic, not a command. An unclosed one runs to the end of seg."""
    out, i, n, dq = [], 0, len(seg), False
    while i < n:
        c = seg[i]
        if c == "\\":
            i += 2
            continue
        if c == "'" and not dq:
            j = seg.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            dq = not dq
        elif c == "`":
            j = seg.find("`", i + 1)
            out.append(("`", i, n if j < 0 else j + 1, seg[i + 1:j if j > 0 else n]))
            i = n if j < 0 else j + 1
            continue
        elif c in "$<>" and seg[i + 1:i + 2] == "(" and seg[i + 2:i + 3] != "(":
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(seg[j], 0)
                j += 1
            out.append((c, i, j, seg[i + 2:j - 1 if not depth else n]))
            i = j
            continue
        i += 1
    return out


def pieces(text):
    return [p for s in segments(text) for p in [s] + split_unquoted(s, PIPE)[1:]]


VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")


# What a command substitution the guard cannot read stands for: a variable that is never known.
UNREAD = "$__wtguard_unread__"


def _var(name, env):
    """A variable's value: set in this command, else the hook's environment. None when unknown,
    and when this command set it from something the guard cannot read (`wt=$(cat f)`), which
    hides any value of the same name in the hook's environment."""
    return env[name] if name in env else os.environ.get(name)


def expand(word, env):
    """~ and the variables known from this command (or the hook's environment). An unknown
    one is left as written, so `$S/out_$f` with S known is judged by $S. Returns None when
    the word STARTS with an unknown variable: then where it lands is not in the text. A write
    is then not judged (a gap, like a loop variable used as a whole path); a worktree's place is
    refused (check_worktree_location)."""
    word = tilde(word)
    m = VAR.match(word)
    if m and _var(m.group(1) or m.group(2), env) is None:
        return None

    def sub(m):
        v = _var(m.group(1) or m.group(2), env)
        return m.group(0) if v is None else v
    return VAR.sub(sub, word)


def substitution_value(body, base, env):
    """What `$(body)` prints, for the two commands whose output is a known path: pwd, and
    mktemp (its X's kept, so the folder and the name's start are known). GNU mktemp puts a
    TEMPLATE relative to the cwd, or with -p DIR / --tmpdir[=DIR] / -t relative to DIR,
    $TMPDIR or /tmp; with no template, tmp.XXXXXXXXXX there. None for anything else."""
    words = strip_prefix(split_words(body.strip()) or [])
    if words == ["pwd"]:
        return base
    if not words or os.path.basename(words[0]) != "mktemp":
        return None
    tmpdir, template, in_tmp, want_dir = None, None, False, False
    for a in words[1:]:
        if want_dir:
            tmpdir, want_dir = a, False
        elif a.startswith("--"):
            name, eq, val = a.partition("=")
            if name == "--tmpdir":
                in_tmp, tmpdir = True, val if eq else tmpdir
        elif a.startswith("-") and len(a) > 1:
            letters = a[1:]
            in_tmp = in_tmp or "t" in letters.split("p")[0]
            if "p" in letters:
                in_tmp, rest = True, letters.split("p", 1)[1]
                tmpdir, want_dir = (rest, False) if rest else (tmpdir, True)
        elif template is None:
            template = a
    tmpdir = expand(tmpdir, env) if tmpdir else None
    tmp = tmpdir or os.environ.get("TMPDIR") or "/tmp"
    if template is None:
        return os.path.join(tmp, "tmp.XXXXXXXXXX")
    template = expand(template, env)
    if template is None:
        return None
    return os.path.join(tmp if in_tmp else base, template)


def substitute(seg, base, env):
    """seg with each $(...) and `...` replaced by what it prints (substitution_value), or by
    UNREAD when the guard cannot tell."""
    out, last = [], 0
    for kind, a, b, body in substitution_spans(seg):
        if kind in "$`":
            v = substitution_value(body, base, env)
            out += [seg[last:a], UNREAD if v is None else v]
            last = b
    return "".join(out) + seg[last:]


ASSIGN = re.compile(r"^[A-Za-z_]\w*=")


def walk(cmd, start, visit):
    """Calls visit(piece_text, base, env) for every command of cmd, following `cd`,
    `pushd` and `NAME=value` (also after export, local, declare, readonly) within it. $PWD is
    the event's cwd, moved by each tracked cd, as in the command guard since 29eafec: the hook
    process's own PWD is wherever Claude Code spawned it, the main checkout for a subagent in a
    worktree (Codex)."""
    text = drop_heredoc_bodies(re.sub(r"\\\r?\n", " ", cmd))
    text = drop_comments(text)
    for segs in (segments(text),):
        base = start
        env = {"HOME": HOME, "PWD": start}
        for seg in segs:
            # A subshell or group opener: `(cd /x && echo > f)`, `{ cd /x; echo > f; }`.
            s = seg.lstrip()
            opened = len(s) - len(s.lstrip("("))
            seg = s.lstrip("(").lstrip()
            if seg.startswith("{ "):
                seg = seg[2:]
            if opened:
                seg = seg.rstrip()
                while opened and seg.endswith(")"):
                    seg, opened = seg[:-1], opened - 1
            # Read with its substitutions replaced, so `wt=$(mktemp -d)` (two words to shlex until
            # then, and never recorded) is one assignment of a known folder (the downstream project's review, s80).
            words = split_words(substitute(seg, base, env)) or []
            assigns = words[1:] if words[:1] in (["export"], ["local"], ["declare"], ["readonly"]) else \
                words if len(words) == 1 else []
            for w in assigns:
                if ASSIGN.match(w):
                    k, v = w.split("=", 1)
                    env[k] = expand(v, env)
            if words and words[0] in ("cd", "pushd"):
                d = expand(words[1], env) if len(words) >= 2 else HOME
                if d is not None and d != "-":
                    base = os.path.join(base, d)
                    env["PWD"] = base
            for part in [seg] + split_unquoted(seg, PIPE)[1:]:
                visit(part, base, env)


# ------------------------------------------------------------------ interpreter code
# An interpreter's own code (-c / -e / --eval, or a heredoc body), found as the command guard
# finds it (INLINE_CODE and HEREDOC_CODE are copied from guard_tool_use.py). The command guard
# then refuses any write-ish code that names a harness path anywhere; here that would refuse
# `open('/main/a').read()` beside `open('out','w')`, a read of the main checkout, so a literal
# absolute (or ~) path counts only where the code writes it: the path argument of an open() with
# a write mode, of a call that writes its first argument, or the destination of a copy, move or
# link (a move's source too), seen through path.join() / Path() wrappers and Path(...).write_text().
_INTERP = r"(?:python3?|node|perl|ruby|deno|bun|php)"
#
# These were copied with a lazy `[^\n]*?` gap from each interpreter word to its flag, which reads to
# the end of the line from every interpreter word: `python ` x 10,000 took 14 s (round 10). The gap
# now stops at the next interpreter word, which is itself a start that finds the same flag, so each
# character is read by one gap; and a heredoc's closing line is looked up in an index of the
# command's lines (heredoc_code) instead of searched for from every opener. The same matches, on
# the seeded corpus of the test suite.
_START = r"(?:^|[\s;&|(/])" + _INTERP + r"\b"
_NOT_NEXT_START = r"(?:(?![\s;&|(/]" + _INTERP + r"\b)"
INLINE_CODE = re.compile(_START + _NOT_NEXT_START + r"[^\n'\"])*?\s-(?:c|e|p|pe|E|-eval)\s+(['\"])(.*?)(?<!\\)\1", re.S)
HEREDOC_OPEN = re.compile(_START + _NOT_NEXT_START + r"[^\n])*?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n")
HEREDOC_END = re.compile(r"^[^\S\n]*(\w+)[^\S\n]*$", re.M)
# A string literal that is an absolute or ~ path; a leading > or >> is perl's open(F, ">path").
PATH_LITERAL = re.compile(r"""(['"])(>{1,2}\s*)?((?:/|~)[^'"\s`]*)\1""")
WRITE_MODE = re.compile(r"""^\s*(?:mode\s*=\s*|flags?\s*[:=]\s*)?['"](?:[rbt]*[wax][bt+]*|r[bt]*\+[bt]*|\+?>{1,2}|\+<)['"]"""
                        r"|\bO_(?:WRONLY|RDWR|CREAT|APPEND|TRUNC)\b")
OPENERS = {"open", "openSync", "fopen", "sysopen"}
# Unambiguous anywhere; the second set only after a file module (`os.remove`, not `s.remove`).
FIRST_WRITERS = {"writeFileSync", "writeFile", "appendFileSync", "appendFile", "createWriteStream", "rmSync",
                 "unlinkSync", "rmdirSync", "mkdirSync", "truncateSync", "rmtree", "makedirs", "removedirs",
                 "mkdir_p", "rm_rf", "rm_r", "rm_f", "file_put_contents", "writeTextFile", "writeTextFileSync"}
FIRST_WRITERS_QUAL = {"write", "remove", "unlink", "rm", "rmdir", "mkdir", "truncate", "touch", "binwrite"}
DEST_WRITERS = {"copyFileSync", "copyFile", "copyfile", "copytree", "copy2", "cpSync", "symlinkSync", "linkSync",
                "renameSync", "cp_r"}
DEST_WRITERS_QUAL = {"copy", "cp", "symlink", "link", "rename", "move", "mv", "replace"}
MOVES = {"rename", "renameSync", "move", "mv", "replace"}
FILE_MODULES = {"os", "shutil", "fs", "promises", "fsp", "File", "FileUtils", "IO", "Dir", "Deno", "Bun"}
WRAPPERS = {"join", "resolve", "Path", "PurePath", "PosixPath", "expanduser", "abspath", "realpath", "normpath", "str"}
PATH_METHOD = re.compile(r"\s*\.\s*(write_text|write_bytes|touch|mkdir|unlink|rmdir|symlink_to|hardlink_to|open)\s*\(")


NAME_CHAR = re.compile(r"[\w$.]")


def _masked(code):
    """code with the inside of every string literal blanked, so a paren in a string is inert."""
    m = list(code)
    for a, b in _quoted_spans(code):
        for i in range(a + 1, b - 1):
            m[i] = "x"
    return "".join(m)


def _call_around(masked, start):
    """(name, name start, open paren, close paren) of the innermost call whose parentheses
    hold position start, or None."""
    depth = 0
    for j in range(start - 1, -1, -1):
        c = masked[j]
        if c in ")]}":
            depth += 1
        elif c in "([{":
            if depth:
                depth -= 1
                continue
            if c != "(":
                return None
            # Backwards over the name: re.search(r"[\w$.]*$", masked[:j]) retried from every
            # position of a long name that a space separates from the paren (round 10).
            a = j
            while a and NAME_CHAR.match(masked[a - 1]):
                a -= 1
            name = masked[a:j]
            k, d = j + 1, 1
            while k < len(masked) and d:
                d += {"(": 1, ")": -1}.get(masked[k], 0)
                k += 1
            return name, j - len(name), j, k - 1
    return None


def _top_args(masked, op, cp):
    """(start, end) of each top-level argument of the call whose parens are at op and cp."""
    out, depth, a = [], 0, op + 1
    for k in range(op + 1, cp):
        c = masked[k]
        depth += 1 if c in "([{" else -1 if c in ")]}" else 0
        if c == "," and not depth:
            out.append((a, k))
            a = k + 1
    return out + [(a, cp)]


def _written(code, masked, start, end, hops=0):
    """Whether the value at code[start:end] is a path this code writes."""
    call = _call_around(masked, start)
    if not call or hops > 3:
        return False
    name, name_at, op, cp = call
    parts = name.split(".")
    last, qualified = parts[-1], len(parts) > 1 and parts[-2] in FILE_MODULES
    args = _top_args(masked, op, cp)
    argn = next((k for k, (a, b) in enumerate(args) if a <= start < b), 0)
    if last in WRAPPERS:
        # path.join(dir, '/x') in node is dir/x: only a wrapper's first argument starts the path.
        if argn:
            return False
        m = PATH_METHOD.match(masked, cp + 1)
        if m and last in ("Path", "PurePath", "PosixPath"):
            if m.group(1) != "open":
                return True
            inner = _call_around(masked, m.end())
            return bool(inner) and any(WRITE_MODE.search(code[a:b]) for a, b in _top_args(masked, inner[2], inner[3]))
        return _written(code, masked, name_at, cp + 1, hops + 1)
    if last in OPENERS:
        return any(WRITE_MODE.search(code[a:b]) for k, (a, b) in enumerate(args) if k != argn)
    if last in FIRST_WRITERS or (last in FIRST_WRITERS_QUAL and qualified):
        return argn == 0
    if last in DEST_WRITERS or (last in DEST_WRITERS_QUAL and qualified):
        return argn == 1 or (argn == 0 and last in MOVES)
    return False


def interpreter_pieces(cmd):
    """The commands of cmd whose own word is an interpreter, nested shells and substitutions
    included. Inline code is read from these only: the same text quoted as prose, in a commit
    message heredoc or an echo, is not run. A nested shell's body is read as the shell unquotes
    it: in `sh -c "python3 -c \\"...\\""` the inner code starts after an escaped quote, which
    INLINE_CODE does not take for one."""
    todo = [drop_comments(drop_heredoc_bodies(re.sub(r"\\\r?\n", " ", cmd)))]
    out, budget = [], 64
    while todo and budget:
        for p in pieces(todo.pop()):
            budget = max(budget - 1, 0)
            words = strip_prefix(split_words(p) or [])
            if words and re.match(_INTERP + r"[\d.]*$", os.path.basename(words[0])):
                out.append(p)
            todo += nested_bodies(words) + substitution_bodies(p)
    return out


def heredoc_code(cmd):
    """The body of each interpreter heredoc of cmd, as HEREDOC_CODE (a regex searching on from every
    opener for its closing line) found it: the lines holding only a delimiter are indexed once, and
    each opener takes the first one after its own line."""
    ends = {}
    for m in HEREDOC_END.finditer(cmd):
        ends.setdefault(m.group(1), []).append(m.start())
    pos = 0
    while True:
        m = HEREDOC_OPEN.search(cmd, pos)
        if not m:
            return
        starts = ends.get(m.group(1), [])
        k = bisect.bisect_right(starts, m.end())
        if k == len(starts):
            pos = m.start() + 1   # no closing line: a later interpreter word on this line may still open one
            continue
        yield cmd[m.end():starts[k] - 1]
        pos = cmd.find("\n", starts[k]) + 1 or len(cmd)


def interpreter_writes(cmd):
    """The literal absolute or ~ paths an interpreter's inline code or heredoc writes."""
    out = []
    codes = [m.group(2).replace('\\"', '"') if m.group(1) == '"' else m.group(2)
             for p in interpreter_pieces(cmd) for m in INLINE_CODE.finditer(p)] + list(heredoc_code(cmd))
    for code in codes:
        masked = _masked(code)
        for lit in PATH_LITERAL.finditer(code):
            # `d + '/ticket.yml'` and `homedir() + '/.cache/x'` are suffixes, not absolute paths.
            if re.search(r"\+\s*$", code[:lit.start()]):
                continue
            if lit.group(2) or _written(code, masked, lit.start(), lit.end()):
                out.append(lit.group(3))
    return out


# ------------------------------------------------------------------ the two rules

def check_shell(cmd, cwd, wt):
    def visit(part, base, env):
        # Containment only inside a worktree; placement everywhere, for this repo only.
        for t in write_targets(part) if wt else []:
            t2 = expand(t, env)
            why = outside_reason(t2, base, wt) if t2 is not None else None
            if why:
                deny("shell write: " + why)
        check_worktree_location(part, base, env)
    walk(cmd, cwd, visit)
    if wt and re.search(_INTERP, cmd):
        for t in interpreter_writes(cmd):
            why = outside_reason(t, cwd, wt)
            if why:
                deny("interpreter write: " + why)


def check_worktree_location(piece, base, env):
    # What a substitution runs is a command like any other: `echo $(git worktree add /x)`.
    for body in substitution_bodies(piece):
        for p in pieces(body):
            check_worktree_location(p, base, env)
    words = strip_prefix(split_words(substitute(piece, base, env)) or [])
    for body in nested_bodies(words):
        for p in pieces(body):
            check_worktree_location(p, base, env)
    if not words or os.path.basename(words[0]) != "git":
        return
    where, sub = git_subcommand(words[1:])
    if len(sub) < 2 or sub[0] != "worktree" or sub[1] not in ("add", "move"):
        return
    where_x = expand(where, env) if where else ""
    # A -C the guard cannot read names some repository: judged as the cwd's, so a worktree of this
    # project is not made outside its folders by hiding the repository behind `$(...)` or a variable
    # set outside the command. A scratch repository reached that way, from this project's checkout,
    # is refused with it (a literal -C of another repository is still left alone).
    at = base if where_x is None else os.path.join(base, where_x)
    positional, i, args = [], 2, sub
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a in ("-b", "-B", "--reason"):
            i += 2
            continue
        if not a.startswith("-"):
            positional.append(a)
        i += 1
    target = positional[0] if sub[1] == "add" else (positional[1] if len(positional) > 1 else None)
    if not target:
        return
    repo = checkout_of(at)
    # Only this project's repository: a session here that makes a worktree of another
    # repo (`git -C ~/dev/Projects/forge worktree add ...`) follows that repo's rules.
    if not repo or main_root(repo[2]) != CFG.root:
        return
    where_ok = "directly under %s%s" % (" or ".join(CFG.worktree_dirs), "".join(
        ", or as a folder named %s<name>" % p for p in CFG.worktree_prefixes))
    t2 = expand(target, env)
    # A place it cannot read is refused, not let through: an unknown variable, or a command's
    # output other than pwd and mktemp, in any folder of the path, and a command's output in the
    # last name too, which may hold `/` or `..`. A bare unknown $VAR in the last name is left to
    # the folder it sits in, which is known and judged (a limit: its value may hold a `/`).
    if t2 is None or "$" in os.path.dirname(t2) or UNREAD in t2:
        deny("git worktree %s: cannot tell where %s lands (a variable set outside this command, or "
             "a command's output this guard does not read). Spell the path, or set it in the same "
             "command; worktrees of this project live only %s." % (sub[1], target, where_ok))
    real = resolve(t2, at)
    # A direct child only: a worktree nested inside another worktree's .claude/worktrees/
    # is also under this folder, and belongs to no one. A prefix names the worktree itself.
    if (os.path.dirname(real) not in CFG.worktree_dirs
            and not any(in_prefix(real, p) and "/" not in real[len(p):] for p in CFG.worktree_prefixes)):
        deny("git worktree %s puts a worktree at %s. Worktrees of this project live only %s; the "
             "profile's worktree_guard.worktree_dirs names any other folder or prefix."
             % (sub[1], real, where_ok))


def main(argv=None):
    global CFG
    argv = sys.argv[1:] if argv is None else argv
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    tool = payload.get("tool_name")
    if tool not in FILE_TOOLS and tool not in SHELL_TOOLS:
        return
    ti = payload.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    try:
        repo = checkout_of(cwd)
    except Exception as e:
        # Which checkout this is could not be read (a NUL in the cwd, a `.git` file that is
        # not UTF-8), so there is no worktree to compare against. A cwd spelled under a
        # .claude/worktrees/ folder is taken as a worktree and refused; anywhere else the
        # call is allowed, as a crash outside a worktree is (review of PR #30, m1).
        if "/.claude/worktrees/" in cwd.replace("\\", "/") + "/":
            deny("the guard could not judge this call (%r), so it is refused inside a worktree" % e)
        return
    wt = (repo[0], repo[1]) if repo and repo[3] else None
    # The main checkout, a submodule and a folder in no repository: no containment, only
    # the placement of this repository's worktrees, and a crash there allows.
    if not wt:
        cmd = ti.get("command")
        if tool in SHELL_TOOLS and isinstance(cmd, str) and cmd:
            try:
                CFG = load_config(argv)
                check_shell(cmd, cwd, None)
            except SystemExit:
                raise
            except Exception:
                return
        return
    try:
        CFG = load_config(argv)
    except Exception as e:
        deny("the profile cannot be used (%s), so every call is refused inside a worktree" % e)
    try:
        if tool in FILE_TOOLS:
            p = ti.get(FILE_TOOLS[tool])
            if p is None:
                return
            if not isinstance(p, str):
                deny("%s.%s is %s, not a path; a write this hook cannot read is refused "
                     "inside a worktree." % (tool, FILE_TOOLS[tool], type(p).__name__))
            why = outside_reason(p, cwd, wt)
            if why:
                deny(why)
        else:
            cmd = ti.get("command")
            if isinstance(cmd, str) and cmd:
                check_shell(cmd, cwd, wt)
    except SystemExit:
        raise
    except Exception as e:  # see the module docstring: closed in a worktree, open elsewhere
        deny("the guard could not judge this call (%r), so it is refused inside a worktree" % e)


if __name__ == "__main__":
    main()
