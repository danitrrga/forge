#!/usr/bin/env python3
"""guard_tool_use.py — PreToolUse security guard, the core every guarded project shares
(docs/command-guard-design.md). Blocks dangerous shell commands, prints of credential
stores, Bash writes to the harness, git hook bypasses, and Read/Write/Edit/Grep of
protected files. Exit 2 + stderr message blocks the tool call.

Reads the PreToolUse payload (tool_name, tool_input) on stdin.
Copied from a downstream project's .claude/hooks/guard_tool_use.py at d923f2ce, which
began as a copy of this file at forge d5000cd. Left out of the copy: the
Portal-only rule (the Stop hook's pause file) and the deleted ones (an MCP allowlist
and GUARD_BYPASS). Setting LEFTHOOK_BIN is refused like LEFTHOOK=0 (hook_bypass): lefthook's
generated git hooks run whatever it names. PROJECT is CLAUDE_PROJECT_DIR, which Claude
Code sets for hooks; alerts land in forge's logs/, where security_audit.py reads them.
(Ported from guard_tool_use.ps1 for Linux. Handles both Claude tool names —
Bash/Write/Edit/Read — and the Gemini equivalents.)

This is the EXTRA layer. The primary control for secret files is native: the
`permissions.deny` Read rules forge writes (forge/hooks.py SECRET_DENY), which Claude Code
applies to Read, Grep, Glob and the Bash file commands it recognises (cat, head, sed, ...).
What those rules cannot see, `grep -r`, an interpreter, a redirect into a loop, is why this
file exists. A pattern check never closes every shape (the downstream project's independent review of
harness-security.md M1); the test suite next to this file pins the ones it
does close, and the ones it does not are listed there too.

Every check always ENFORCES. There is no off switch inside a tool call: the project turns
the guard off, and a command it refuses that the user wants run, the user runs himself.
"""
import datetime
import glob
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

# forge: this file lives in <forge>/hooks/, and its alert log in <forge>/logs/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORGE = os.path.realpath(ROOT)
# The repository this guard protects: CLAUDE_PROJECT_DIR, which Claude Code sets for hooks,
# else the directory the hook was started in. Never this file's location, which is forge.
PROJECT = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
HOME = os.path.realpath(os.path.expanduser("~"))
# The directory the tool call runs in; set from the payload in main().
CWD = [PROJECT]

# Dangerous shell patterns (case-insensitive). Each entry: (regex, reason).
# Each reason says what to do instead (the suite checks it): the agent reads only that line.
DANGEROUS_SHELL = [
    (r"base64\s+(-d|--decode)", "base64 decode into a shell or interpreter. Instead, decode into "
     "a file, read it, and run it as its own step"),
    # Anywhere, not only after `>`: `bash -i >& /dev/tcp/...` and `exec 3<>/dev/tcp/...`
    # both reach it without a bare `> ` in front (harness-security.md m3).
    (r"/dev/(?:tcp|udp)/", "bash /dev/tcp exfiltration. Instead, use curl against a named host"),
    (r"(\||;)\s*nc\s+", "netcat piping detected. Instead, use curl, or run the nc probe as a call of its own"),
    (r"(\||;)\s*ncat\s+", "netcat piping detected. Instead, use curl, or run the nc probe as a call of its own"),
    (r"find\s+[^|]*\s-name\s+['\"]?\*\.env", "mass .env harvesting. Instead, ls the one directory "
     "whose env file you need (ls apps/web/.env*), or git ls-files"),
    (r"find\s+[^|]*\s-name\s+['\"]?id_", "SSH key harvesting pattern. Instead, ls ~/.ssh"),
    (r"powershell.*\s-e(nc|ncodedcommand)\b", "powershell -EncodedCommand (obfuscation). Instead, pass the "
     "script as plain text"),
]
# base64 decode is only dangerous when its output reaches a shell or an interpreter: a pipe
# into one, a substitution that runs it, or a shell named anywhere. The downstream project's bare `\|`
# matched any pipe, so `gh api ... --jq .content | base64 -d | head` was refused (29 of
# a downstream project's 36 base64 refusals in the replay of its recorded commands).
PIPE_TO_SHELL = re.compile(
    r"(\|\s*(?:sudo\s+)?(?:zsh|dash|ksh|fish|python[\d.]*|perl|ruby|node|php|deno|bun|source|eval|xargs)\b"
    r"|\|\s*\.(?=\s|$)|\$\(|`|<\(|\bsh\b|\bbash\b|(?<![\w-])iex(?![\w-])|invoke-expression)", re.I)
OOB_DOMAINS = [
    r"\.interact\.sh", r"\.oast\.(pro|live|site|fun|me)", r"\.burpcollaborator\.net",
    r"\.requestbin\.", r"\.pipedream\.net", r"webhook\.site", r"\.ngrok\.io",
    r"\.ngrok-free\.app", r"\.trycloudflare\.com",
]
# The last suffix of a tracked env template, which carries placeholder names only:
# `.env.example`, and in forge also `.env.sample` (that project's, which its block-env-write.sh
# allows; 64 of its 200 credential-store refusals in the replay were reads of it),
# `.env.template` and `.env.dist`, after any other suffix (`.env.tunnel.sample`). Only the
# last one counts: `.env.sample.local` is a secret, and the downstream project's `\b` let through
# `.env.example.local`.
ENV_TEMPLATE = r"(?:example|sample|template|dist)"
# forge's credentials/ (addition 4), the real home of every token forge hands out, whose files
# are not all named secrets.*. Matched by the checkout's own name, so `~/...`, `$HOME/...` and a
# relative `forge/credentials` are seen as well as the absolute path. Lowercase, like the text
# it is matched against.
_FORGE_BASE = os.path.basename(FORGE).lower()
_FORGE_NAME = re.escape(_FORGE_BASE)
# ~/.hindsight/'s top level as forge/hooks.py SECRET_DENY names it (`*.json*`, `*.token`, `*.env`,
# `profiles/*.env*`); its subdirectories stay readable, so `[^/]*` and not `.*`. The guard knew only
# coding-agent.json and control.token until Codex read `session.json`.
HINDSIGHT_STORE = r"/\.hindsight/(?:profiles/[^/\s'\"]*\.env|[^/\s'\"]*\.(?:json|token|env))"
FORGE_CREDENTIALS_PATH = r"/" + _FORGE_NAME + r"/credentials(?:/|$)"
FORGE_CREDENTIALS = r"(?:^|[\s/'\"=])" + _FORGE_NAME + r"/credentials\b"
# forge's config/secrets*, which SECRET_DENY names with a `*`: secrets.json is a symlink into
# credentials/, but a `secrets.yaml` or a `secrets.json.bak` beside it is the same kind of file.
FORGE_CONFIG_SECRETS_PATH = r"/" + _FORGE_NAME + r"/config/secrets"
FORGE_CONFIG_SECRETS = r"(?:^|[\s/'\"=])" + _FORGE_NAME + r"/config/secrets"
# Paths the Read/Write/Edit tools may not touch. An env template is not protected: editing
# it is how a new variable is added.
PROTECTED_FILES = [
    r"/\.mcp\.json", r"/\.gemini/settings\.json",
    r"/\.bashrc", r"/\.bash_profile", r"/\.profile", r"/\.zshrc", r"/profile\.ps1",
    r"\.ssh/", r"\.env(?:\.(?!(?:[^/]*\.)?" + ENV_TEMPLATE + r"$)|$)", r"\.envrc\b", r"credentials\.json",
    # `.env_prod`, `.env2`, `.env-prod`: an env file with another separator, where the name starts.
    r"(?:^|/)\.env(?:[_-](?!(?:[^/]*[._-])?" + ENV_TEMPLATE + r"$)|\d)",
    r"id_rsa", r"id_ed25519", r"\.pem\b", r"\.key\b", r"/\.codex/",
    r"google/chrome/user data", r"mozilla/", r"microsoft/edge/user data",
    # The stores SECRET_FILES blocks for Bash. Until a later fix the Read and Grep tools
    # could open every one of them (break-it round on PR #23, U17 and U72). None ends in `$`, as
    # SECRET_FILES does not: a renamed copy (`claude-code.json.disabled-20260917`, `.npmrc.bak`)
    # holds the same bearer (round 9). `\b` where the Bash rule has it, so `.npmrc` is not `.npmrcx`.
    r"ovcli\.conf", r"/claude-code\.json", r"gate\.token", r"secrets\.(?:json|env)",
    r"/\.secrets\b", r"/\.config/gh/hosts\.yml\b", r"/\.npmrc\b", r"com\.vercel\.cli/auth\.json\b",
    r"/\.git-credentials\b", r"/\.supabase/access-token\b", r"/\.vercel/auth\.json\b",
    r"supabase/\.temp/", r"/\.aws/credentials\b", r"/\.kube/config\b", r"/\.docker/config\.json\b",
    # Hindsight's live client config (its `apiToken`) and its local control panel's token,
    # unguarded until they were added here. A `.bak` copy sits beside coding-agent.json.
    r"/coding-agent\.json", r"/control\.token",
    # A login kept for a test run (`.dev-credentials.local` held the Playwright demo user's
    # email and password, and `cat` of it passed every layer until this entry).
    r"credentials[^/]*\.local\b", r"/\.dev-credentials[^/]*$",
    # Stores forge/hooks.py SECRET_DENY denies to Read that the downstream project's lists lack (addition 4):
    # ~/.claude.json carries every MCP server's resolved secrets, and its backups beside it.
    r"/\.claude\.json", r"/\.aws/config\b", r"/id_ecdsa", r"/id_dsa", FORGE_CREDENTIALS_PATH,
    HINDSIGHT_STORE, FORGE_CONFIG_SECRETS_PATH,
]

# Credential stores whose CONTENT must never reach a transcript. Matched against the
# shell command string, because that is the hole the PROTECTED_FILES check below
# cannot see: that check only reads `file_path`, so it covers Read/Write/Edit and
# never looks at Bash. Once the memory store's API key leaked through
# `cat ~/.openviking/ovcli.conf | sed 's/.../<REDACTED>/'` -- a redaction that did not
# match -- and from the transcript it reached a MEMORY, which recall then re-injected
# into every later session until the key was rotated. The lesson is not "redact more
# carefully": a redaction that silently fails looks exactly like one that worked.
# id_ecdsa and id_dsa are forge's (addition 4), anchored so `valid_dsa.py` is not a key.
SSH_KEYS = (r"id_rsa\b", r"id_ed25519\b", r"(?<!\w)id_ecdsa\b", r"(?<!\w)id_dsa\b")
SECRET_FILES = [
    # ovcli.conf was OpenViking's client config; claude-code.json and the two files under
    # /etc/hindsight are its Hindsight successors, and they carry the same kind of bearer.
    r"ovcli\.conf", r"claude-code\.json", r"gate\.token", r"cp\.env", r"api\.env",
    r"secrets\.json", r"secrets\.env",
    # Hindsight's client config after claude-code.json (its `apiToken`), and the token of
    # its local control panel. Recorded commands in forge sessions read both.
    r"coding-agent\.json", r"control\.token",
    # `process.env` and `import.meta.env` are JavaScript, not files, and searching source
    # for them is ordinary work. An env template carries placeholder names only and is
    # tracked (harness-security.md m7: blocking `.env.example` was the defect).
    # A backslash before it is the regex's escape (`process\.env\.X` in a sed or grep pattern).
    r"(?<!process)(?<!process\\)(?<!meta)(?<!meta\\)\.env(?!(?:\.[\w-]+)*?\." + ENV_TEMPLATE + r"(?![\w.-]))\b",
    # `.env_prod`, `.env2`: the `\b` above lets a `_` or a digit after `env` pass, which keeps
    # `.environment` readable. Only where a name starts, so `cfg.env_file` in code is not one;
    # `.env_example` is a template (`_` as the separator), `.env_example.local` is not.
    r"(?:^|[\s/'\"=])\.env(?=[_\d])(?!(?:[\w-]*[._])?" + ENV_TEMPLATE + r"(?![\w.-]))",
    r"\.envrc\b", r"\.secrets\b",
    r"credentials\.json", *SSH_KEYS, r"\.pem\b",
    # .mcp.json and .codex/config.toml carry live tokens (this repo's .gitignore says
    # so), and three user-level stores exist on this machine (harness-security.md M1c/d).
    r"\.mcp\.json", r"\.codex[\\/]config\.toml",
    r"\.config/gh/hosts\.yml", r"\.npmrc\b", r"com\.vercel\.cli/auth\.json",
    r"\.git-credentials\b", r"\.supabase/access-token\b", r"\.vercel/auth\.json",
    r"supabase/\.temp/",
    # Stores that are not on this machine today but are where these tools keep a login.
    r"\.aws/credentials\b", r"\.kube/config\b", r"\.docker/config\.json\b",
    # A test login in a gitignored file, `.dev-credentials.local` or `e2e-credentials.local`.
    # Anchored on the prefix or the suffix, so `grep -rn credentials docs` is not a read.
    r"credentials[^/\s'\"]*\.local\b", r"\.dev-credentials\b",
    # A glob the shell expands at run time: `.en*`, `.en?`, `.[e]nv`.
    r"\.en[*?\[]", r"\.\[e\]", r"\.e\{",
    # A secret name built from pieces: `f=apps/web/.en; cat ${f}v.local`. The fragment
    # is a path segment that is exactly `.e` or `.en`, which no ordinary path has.
    r"(?:^|[\s=/'\"])\.en?(?=$|[\s;&|'\"}]|\$)",
    # Addition 4, as in PROTECTED_FILES. `.claude.json` starts a path segment: forge's projects
    # are named `<project>.claude.json`. A quote before it does not count: forge's project code
    # quotes the suffix (`.replace('.claude.json', '')`, the replay of one project's commands), and the store is
    # in $HOME, so a quoted relative name is a store only after a `cd ~` (cd_resolved follows it).
    r"(?:^|[\s/=])\.claude\.json", r"\.aws/config\b", FORGE_CREDENTIALS, HINDSIGHT_STORE,
    FORGE_CONFIG_SECRETS,
]
# Where to look instead, for the store that project reached for most: 8 of its 45 refusals left after
# the friction fixes, in the replay of its recorded commands, read ~/.claude.json
# for MCP server definitions.
HINTS = {p: " For MCP server definitions, read forge's config/mcp-registry.json and "
            "config/projects/<project>.claude.json, which hold ${VAR} placeholders, not values."
         for p in SECRET_FILES if p.endswith(r"\.claude\.json")}
# Commands that put a file's bytes on stdout. Used by inert_segment to tell a search
# that prints names or counts from one that prints lines.
DUMP_COMMANDS = (
    r"(?:^|[|;&]|\$\(|['\"]|--\s|-c\s)\s*"
    r"(?:(?:do|then|else)\s+)?"
    r"(?:sudo\s+)?"
    r"(?:cat|bat|head|tail|less|more|nl|strings|xxd|od|hexdump|base64"
    r"|grep(?!\s+(?:-[a-z]*[lcq][a-z]*\s))|rg(?!\s+(?:-[a-z]*[lc][a-z]*\s))"
    r"|awk|sed|jq|tee|printenv|env)\b"
)

# The secret store that is NOT a file, and therefore matched nothing above. Once a
# freshly minted Supabase token was printed into the transcript by `secret-tool search service
# "Supabase CLI"`, which dumps `secret = <value>` along with the metadata.
# Blocked unless the output is redirected to a file, which is how a secret is legitimately
# moved into a rotation tool without ever reaching stdout.
KEYRING_DUMP = re.compile(
    r"""(?:^|[|;&]|\$\(|['"]|--\s|-c\s)\s*(?:sudo\s+)?"""
    r"(?:secret-tool\s+(?:search|lookup)|kwallet-query|keyctl\s+print"
    r"|pass\s+show|security\s+find-generic-password)\b", re.I)
# A redirect into a path. `> /dev/stdout` and `>&1` are not files and do not count.
REDIRECT_TO_FILE = re.compile(r">\s*(?!&)(?!/dev/(?:stdout|stderr|fd))[\w./$\"'{}-]+")

# A segment that names a secret is dangerous unless it is provably inert. There is no
# list of dump verbs to satisfy first: that gate is why 44 of 80 probed leak shapes
# passed (sort, cut, dd, interpreters, redirects, curl file://, vim -es; review M1).
#
# Segments split on ; && || & and newlines, never on a pipe, so `cat .env | sed`
# stays one segment. Inert means:
#   * metadata only: ls, stat, test, [, chmod, chown, du, wc, file, rm, and git
#     check-ignore / ls-files / status / rm; cd, pushd and mkdir with no substitution in
#     them (a relative read after a cd is seen through cd_resolved, which rewrites it first);
#   * find without -exec, -execdir, -ok or -okdir;
#   * grep or rg in the name-only or count-only form, or with the secret's name only in
#     the search pattern;
#   * a move, copy or link whose destination keeps a secret name, so any later
#     dump of the destination still matches here (forge: a move INTO ~/.secrets/ is how a
#     secret is put away);
#   * awk reading stdin with a program that can open nothing (forge);
#   * ssh whose one quoted remote command is itself inert (forge).
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|(?<![>&])&(?![>&])|\n")
INERT_COMMANDS = {"ls", "stat", "test", "[", "chmod", "chown", "du", "wc", "file", "rm", "tree"}
INERT_GIT = {"check-ignore", "ls-files", "status", "rm"}
RELOCATE_COMMANDS = {"mv", "cp", "ln", "rsync", "install"}
NO_SUBSTITUTION = {"cd", "pushd", "mkdir"}
SUBSTITUTES = re.compile(r"\$\(|`|<\(")
# awk's program, in the single quotes the shell leaves alone: its $6 is a field, not an
# argument (that replay: `ls -l ~/.claude.json | awk '{print $6}'` was refused).
AWK_PROGRAM = re.compile(r"(\b[gmn]?awk\s+(?:-\S+\s+)*)('[^']*')")
# What lets an awk program open a file or run a command, lowercased.
AWK_OPENS = re.compile(r"getline|system|argv|@|[|<>]")
# A read of the previous command's argument or of a file descriptor is not tied to any
# path this guard can see: `ls .env; cat $_`. It only counts when the same command
# names a secret somewhere. Counting it on its own blocked every `awk '{print $1}'`
# and every script with `"$1"` (found live on an uncommitted draft).
INDIRECT_READ = re.compile(r"\$_(?!\w)|\$\{?[0-9@*]|<&|<<<")
# Commands whose quoted argument is prose (a message, a title, a body) to be
# written, not a nested command to execute.
PROSE_BEARING = {
    ("git", "commit"), ("git", "tag"), ("git", "notes"),
    ("gh", "pr"), ("gh", "issue"), ("gh", "release"),
}
SUBSTITUTION = re.compile(r"\$\([^()]*\)|`[^`]*`")
# A one-word message is prose too (`git commit -m .env` was refused; Codex), but
# only where the word is surely -m's value: a plain `git commit` with value-less flags before
# it, and a word the shell neither expands nor ends early. `git commit -- -m .env`, `--author
# -m .env` and `> -m .env` make .env a pathspec, and `-m .env*` a glob, so they stay checked.
_WORD = r"[^\s'\"`$()<>*?\[\]{}\\;&|]+"
ONE_WORD_MESSAGE = re.compile(
    r"^(\s*git\s+commit(?:\s+(?:-[aqsv]+|--(?:amend|no-edit|all|quiet|signoff|allow-empty|verbose)))*"
    r"\s+(?:-m|--message)\s+)(?:%s|'%s'|\"%s\")(?=\s|$)" % (_WORD, _WORD, _WORD))
# A heredoc body is prose only when the whole line that opens it is one of three idioms,
# with nothing else on the line: a commit or PR message through `"$(cat <<'EOF'` or
# `-F - <<'EOF'` (in forge also with a pathspec after the `-`), or a notes file written with
# `cat > notes.md <<'EOF'`. A heredoc fed to anything else (`git commit -am x && python3 -
# <<'EOF'`) is code and stays checked, and so does one written to a script (`cat > run.sh
# <<'EOF'`), which the next command may run. forge adds two, from the replay of one project's commands:
# text fed to grep or rg, and a file of any other kind that nothing later in
# the same call runs, reads back or names in a glob (runs_later).
# Commands before the idiom stay in the checked text; only the body is blanked. They may
# not contain a `<` (another heredoc whose body would be swallowed) and must end in && or ;.
_LEAD = r"^(?P<lead>(?:[^<\n]*?(?:&&|;))?)\s*"
# gh release is left out: its positional arguments are files to upload.
_VERB = r"(?:git\s+(?:commit|tag|notes)|gh\s+(?:pr|issue)\s+(?:create|edit|comment|review|close))\b"
_PLAIN = r"[^;&|<>`$()\n]*?"
_DELIM = r"<<-?\s*(?P<q>['\"]?)(?P<d>\w+)(?P=q)\s*$"
PROSE_HEREDOC = [
    re.compile(_LEAD + _VERB + _PLAIN + r"\"\$\(cat\s*" + _DELIM),
    re.compile(_LEAD + _VERB + _PLAIN + r"(?:-F|--file)\s*-(?=\s|<)" + _PLAIN + _DELIM),
    re.compile(_LEAD + r"cat\s*>>?\s*[^\s;&|<>`()]+\.(?:md|txt|rst)\s*" + _DELIM),
    re.compile(_LEAD + r"(?:grep|rg)\b" + _PLAIN + _DELIM),
    re.compile(_LEAD + r"cat\s*>>?\s*(?P<t>[^\s;&|<>`()]+)\s*" + _DELIM),
]
# What a later command may do to a file a heredoc wrote without running or reading it.
LEAVES_FILE = {"chmod", "ls", "stat", "ln", "wc", "file"}
# Files a shell runs by itself in every later call, so writing one is running it.
SHELL_STARTUP = {".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zshenv",
                 ".zprofile", ".zlogin", "config.fish", ".envrc"}


def runs_later(target, rest):
    """True when a command after the heredoc may run or read the file it wrote: it names the
    file, or holds a glob that might, and is not chmod, ls, stat, ln, wc, file or git add."""
    name = os.path.basename(target.strip("'\""))
    if name in SHELL_STARTUP:
        return True
    for seg in SEGMENT_SPLIT.split("\n".join(rest)):
        words = strip_prefix(split_words(seg) or [])
        if words and (words[0] in LEAVES_FILE or (words[0] == "git" and git_subcommand(words[1:])[1][:1] == ["add"])):
            continue
        if not name or name in seg or GLOB.search(seg):
            return True
    return False
PROSE_SEP = re.compile(r"&&|\|\||[;&|\n]")


def _prose_heredocs(cmd):
    lines, out, i = cmd.split("\n"), [], 0
    # Each idiom line re-parses everything before it, so thousands of them take seconds
    # (break-it round, U63). Past 20 the text is kept whole: stricter, never looser.
    if sum(1 for ln in lines if any(r.match(ln) for r in PROSE_HEREDOC)) > 20:
        return cmd
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = next(filter(None, (r.match(line) for r in PROSE_HEREDOC)), None)
        if not m:
            continue
        # The line must start a command: nothing before it may leave a quote open or
        # continue onto it with a backslash.
        before = "\n".join(lines[:i - 1] + [m.group("lead")])
        if before.endswith("\\") or split_words(before) is None:
            continue
        quoted, delim = m.group("q"), m.group("d")
        end = next((j for j in range(i, len(lines))
                    if lines[j].strip() == delim or lines[j].strip().startswith(delim + ")")), None)
        if end is None:
            continue
        if m.groupdict().get("t") and runs_later(m.group("t"), lines[end + 1:]):
            continue
        for body in lines[i:end]:
            # An unquoted delimiter still expands $(...) and backticks in the body.
            if not quoted and ("$(" in body or "`" in body):
                out.append(body)
        i = end
    return "\n".join(out)


# A Python script fed through a quoted heredoc, the way a session edits a markdown file
# outside the repo. Its multi-word string literals are the prose it writes, and a mention
# of `.env.local` in that prose was blocked as a read. A bare
# literal such as `open('.env.local')` has no space in it and stays checked. So does the
# whole script when it can start a process: then a string may be a shell command.
PY_HEREDOC = re.compile(r"(?:^|[\s;&|(])python3?\b[^\n]*?<<-?\s*(?:(['\"])(\w+)\1|\\(\w+))[^\n]*\n")
# `compile` is left out: it only builds code, and `re.compile` is in most editing scripts.
SPAWNS = {"subprocess", "system", "popen", "Popen", "eval", "pty", "__import__",
          "importlib", "getattr", "runpy", "ctypes", "startfile", "sh", "plumbum"}


def _python_prose(text):
    out, pos = [], 0
    for m in PY_HEREDOC.finditer(text):
        if m.start() < pos:
            continue
        delim = m.group(2) or m.group(3)
        end = re.compile(r"^\t*" + delim + r"[ \t]*$", re.M).search(text, m.end())
        if not end:
            break
        body = text[m.end():end.start()]
        out.append(text[pos:m.end()] + _blank_py_strings(body))
        pos = end.start()
    return "".join(out) + text[pos:]


def _blank_py_strings(body):
    import tokenize  # here, not at the top: ~0.6 ms on every call that never needs it
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(body).readline))
    except Exception:  # not Python, or not finished: keep all of it
        return body
    if any(t.type == tokenize.NAME and (t.string in SPAWNS or t.string.startswith(("exec", "spawn", "posix_spawn")))
           for t in toks):
        return body
    starts = [0]
    for ln in body.splitlines(True):
        starts.append(starts[-1] + len(ln))
    for t in reversed(toks):
        prefix = re.match(r"[A-Za-z]*", t.string).group().lower()
        words = t.string[len(prefix):].strip("'\"")
        # An f-string's braces are code; a literal with one word is a path or a key.
        if t.type == tokenize.STRING and not set("ft") & set(prefix) and re.search(r"\S\s+\S", words):
            a = starts[t.start[0] - 1] + t.start[1]
            b = starts[t.end[0] - 1] + t.end[1]
            body = body[:a] + '"PROSE"' + body[b:]
    return body


def _quoted_spans(seg):
    """(start, end) of each quoted string in seg that is not inside another one."""
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


def strip_prose(cmd):
    """Blank out what is prose, not a command: the heredoc bodies above, and the
    multi-word quoted arguments of PROSE_BEARING commands (`-m "fix the .env loader"`).
    A replay of 8,741 recorded commands showed commit messages that merely mention
    `.env.local`, `--no-verify` or a hooks path being blocked as if they ran them. A
    substitution in a message still runs, so it is kept; the text is edited in place,
    so redirects and operators stay exactly where they were."""
    text = _python_prose(_prose_heredocs(cmd))
    parts = PROSE_SEP.split(text)
    seps = PROSE_SEP.findall(text)
    out = []
    for k, seg in enumerate(parts):
        seg = ONE_WORD_MESSAGE.sub(r"\1PROSE", seg)
        words = split_words(seg)
        if words and tuple(strip_prefix(words)[:2]) in PROSE_BEARING:
            for a0, b0 in reversed(_quoted_spans(seg)):
                body = seg[a0 + 1:b0 - 1]
                if not re.search(r"\s", body) or "`" in body:
                    continue
                subs = SUBSTITUTION.findall(body)
                if body.count("$(") != len(subs):
                    continue
                seg = seg[:a0] + (" ".join(subs) or "PROSE") + seg[b0:]
        out.append(seg)
        if k < len(seps):
            out.append(seps[k])
    return "".join(out)


def split_words(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return None


SHELL_KEYWORDS = ("do", "then", "else", "if", "elif", "while", "until", "!")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# What runs another command after options of its own, with the short options that take a value (in
# the next word or stuck to the option) and the long ones that take it in the next word. The guard
# stopped at the first of these, so `nice tee .claude/settings.json` and `timeout 5 sh -c '...'`
# were never read (round 9b, item 1).
WRAPPER_VALUE_OPTS = {
    "sudo": "ughpCDRTU", "env": "uCS", "nice": "n", "timeout": "sk", "exec": "a", "stdbuf": "ioe",
    "xargs": "InPdLaEs", "time": "fo", "ionice": "cnpPu", "setsid": "", "command": "", "nohup": "",
}
WRAPPER_LONG_VALUE = {"--user", "--group", "--host", "--prompt", "--chdir", "--chroot", "--unset", "--adjustment",
                      "--signal", "--kill-after", "--input", "--output", "--error", "--max-args", "--max-procs",
                      "--delimiter", "--arg-file", "--eof", "--format", "--split-string"}


def command_words(words):
    """(NAME=value assignments, the command words, the wrappers passed, the directory a wrapper
    moves to) of a command: shell keywords, assignments (`LEFTHOOK=0 git ...`) and wrappers (sudo,
    env, command, nohup, time, exec, nice, timeout, stdbuf, xargs, ionice, setsid) are stepped
    over, each with its options. What env sets is the environment of the command after it, so an
    assignment among them is returned for a nested shell to read."""
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


# A pipe into something that runs its input as commands or paths turns an inert listing
# into a read: `ls <secret> | xargs cat`. The shell's `.` is a word of its own: written as
# `\.\b` it matched only a dot before a letter, so `| . /dev/stdin` passed and jq's
# `.a | .env` was blocked.
PIPE_TO_EXEC = re.compile(r"(?<!\|)\|(?!\|)\s*(?:sudo\s+)?(?:(?:xargs|sh|bash|zsh|dash|parallel|while|source)\b|\.(?=\s|$))")


# git's own options before the subcommand; these take the next word as their value.
GIT_VALUE_OPTS = ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env")


def git_subcommand(args):
    """Skips git's global options (`git -C dir -c k=v --no-pager rm x`). Returns the -C
    directory ("" when none) and the subcommand with its arguments. Reading args[0] as
    the subcommand let `git -c x=y rm lefthook.yml` past every git rule (break-it, U14)."""
    where, i = "", 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in GIT_VALUE_OPTS and i + 1 < len(args):
            if args[i] == "-C":
                where = os.path.join(where, args[i + 1])
            i += 2
        else:
            i += 1
    return where, args[i:]


PIPE = re.compile(r"(?<!\|)\|(?!\|)")


def split_unquoted_seps(text, pattern):
    """(text cut at each match of pattern that lies outside quotes, the matches it was cut at)."""
    spans, k, out, seps, last = _quoted_spans(text), 0, [], [], 0
    for m in pattern.finditer(text):
        while k < len(spans) and spans[k][1] <= m.start():
            k += 1
        if k < len(spans) and spans[k][0] <= m.start():
            continue
        out.append(text[last:m.start()])
        seps.append(m.group(0))
        last = m.end()
    return out + [text[last:]], seps


def split_unquoted(text, pattern):
    """text cut at each match of pattern that lies outside quotes."""
    return split_unquoted_seps(text, pattern)[0]


def pipeline(seg):
    """seg split at each `|` that is outside quotes and not part of `||`."""
    return split_unquoted(seg, PIPE)


def segments(text):
    """The commands of text for a rule that only adds blocks: the quote-blind cut at ; && ||
    & and newlines, plus the pieces of the cut that leaves quotes whole. The blind cut
    splits a nested `sh -c 'true; tee lefthook.yml'` into halves no parser reads, and
    those halves read as no write at all. The other cut alone is not
    enough: an apostrophe the shell never sees, in a comment or a heredoc, swallows the
    rest of the command into one quote."""
    blind = SEGMENT_SPLIT.split(text)
    seen = set(blind)
    return blind + [s for s in split_unquoted(text, SEGMENT_SPLIT) if s not in seen]


def pieces(text):
    """Each command of text: every segment of both cuts, and each later command of a pipe
    in it (the whole segment stands for the first, as it always did)."""
    return [p for s in segments(text) for p in [s] + pipeline(s)[1:]]


NESTING_SHELLS = ("bash", "sh", "zsh", "dash", "eval")


def nested_bodies(words, shells=NESTING_SHELLS):
    """The quoted command lines a nested shell runs: `bash -c 'a; b'` gives 'a; b'."""
    if words and os.path.basename(words[0]) in shells:
        return [a for a in words[1:] if re.search(r"\s", a)]
    return []


# Short flags that take no value, per command, in the lowercased text secret_dump sees.
# Uppercase flags fold onto these (-E is -e, -A is -a); the folded ones that take a value
# take a number, a type or an encoding, never a path. Any other flag before the pattern
# (-f, -g, -m, -t, a bare long option, `--`) is not understood and counts as a read.
GREP_BOOL_FLAGS = {"grep": set("abcghilnopqrstuvwxyz"), "rg": set("abchilnopqsuvwxz."),
                   "git grep": set("abcghilnopqrstuvwxyz")}


def reads_behind(seg):
    """True when seg holds a command substitution, a backtick or a `<` the shell would act on.
    Inside single quotes all three are text, and inside double quotes only the first two run, so
    `jq '... "<redacted>" ...'` and `grep '<h1>' f` read nothing behind the guard's back. Every
    caller has split the segment into words already, so its quotes are balanced."""
    rest, last = [], 0
    for a, b in _quoted_spans(seg):
        rest.append(seg[last:a])
        if seg[a] == '"':
            rest.append(" ".join(re.findall(r"\$\(|`", seg[a:b])))
        last = b
    rest.append(seg[last:])
    return bool(re.search(r"\$\(|`|<", " ".join(rest)))


def grep_operands(cmd, args):
    """(patterns, others) of a grep-family command's arguments: the pattern operand (the first
    positional, or each -e value) and every other operand or option. None when an option is not
    understood, which callers read as "could be anything"."""
    bools = GREP_BOOL_FLAGS[cmd]
    # A cluster ending in e takes the pattern next: `-e PAT`, and `-iE PAT` once lowercased,
    # which reads the same word either way. An e anywhere else is ambiguous and not accepted.
    ends_e = lambda a: re.match(r"^-[a-z.]*e$", a) and set(a[1:-1]) <= bools
    has_e = any(a == "--regexp" or a.startswith("--regexp=") or ends_e(a) for a in args)
    patterns, others, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--regexp" or ends_e(a):
            if i + 1 >= len(args):
                return None
            patterns.append(args[i + 1])
            i += 1
        elif a.startswith("--regexp="):
            patterns.append(a)
        elif a == "--" and cmd == "git grep":
            # git grep's pathspecs: every word after it is a file operand, never the pattern.
            others.extend(args[i + 1:])
            break
        elif a.startswith("--"):
            if "=" not in a:
                return None
            others.append(a)
        elif a.startswith("-") and len(a) > 1:
            # A context or count flag with its number attached (`-A3`, `-C5`, `-m5`).
            if not set(a[1:].rstrip("0123456789")) <= (bools | {"m"} if a[-1].isdigit() else bools):
                return None
        elif not has_e and not patterns:
            patterns.append(a)
        else:
            others.append(a)
        i += 1
    return patterns, others


def only_pattern_names(pat, cmd, args, seg):
    """A search FOR a secret's name, not a read of the secret: `grep -n "\\.env" notes.md`.
    True only when the pattern operand (the first positional, or each -e value) is what
    names it: no file operand, glob or option does, and nothing in the segment reads a file
    behind the guard's back (`$(`, a backtick, a `<` redirect). Break-it round, U13."""
    if reads_behind(seg):
        return False
    ops = grep_operands(cmd, args)
    if ops is None:
        return False
    patterns, others = ops
    return bool(patterns) and not any(re.search(pat, w) for w in others)


STAGE_SPLIT = re.compile(SEGMENT_SPLIT.pattern + "|" + PIPE.pattern)


def map_stages(text, fn):
    """text with each command of it (cut at ; && || & newline and every `|` outside quotes)
    replaced by fn(command); the separators stay where they were."""
    spans, k, out, last = _quoted_spans(text), 0, [], 0
    for m in STAGE_SPLIT.finditer(text):
        while k < len(spans) and spans[k][1] <= m.start():
            k += 1
        if k < len(spans) and spans[k][0] <= m.start():
            continue
        out.append(fn(text[last:m.start()]) + m.group(0))
        last = m.end()
    return "".join(out) + fn(text[last:])


def search_command(stage):
    """('grep' | 'rg' | 'git grep', its arguments) when stage runs a grep-family search, else None."""
    words = strip_prefix(split_words(stage) or [])
    if not words:
        return None
    cmd, args = os.path.basename(words[0]), words[1:]
    if cmd == "git":
        sub = git_subcommand(args)[1]
        return ("git grep", sub[1:]) if sub[:1] == ["grep"] else None
    if cmd in ("grep", "egrep", "fgrep"):
        return "grep", args
    return ("rg", args) if cmd == "rg" else None


def blank_grep_patterns(text):
    """text with the quoted pattern operand of each grep, egrep, fgrep, rg and git grep in it
    replaced by 'PATTERN': a search pattern is text, never a command or a flag, so the
    `--no-verify` of `grep -n 'a|--no-verify' PLAN.md` and the `|bash` of `grep -E 'x|bash'` are
    not read as what they would be anywhere else. A search that substitutes or redirects is left
    as written, and so is every operand that is not the pattern."""
    def blank(stage):
        found = search_command(stage)
        if not found or reads_behind(stage):
            return stage
        ops = grep_operands(*found)
        if not ops or not ops[0]:
            return stage
        for a, b in reversed(_quoted_spans(stage)):
            if split_words(stage[a:b]) in [[p] for p in ops[0]]:
                stage = stage[:a] + "'PATTERN'" + stage[b:]
        return stage
    return map_stages(text, blank)


# What keeps paths out of a command: `--exclude=GLOB` and `--exclude-dir=GLOB` of a search, an
# archive or a copy, rg's `-g '!GLOB'`, and a git pathspec `':!GLOB'`. The operand is blanked
# before the credential rule reads the line, so `grep -rn foo --exclude='.env*' .` names no store.
# `--exclude-from`, `--include` and a positive glob are not exclusions and are left alone.
_OPERAND = r"""(?:'[^']*'|"[^"$`\\]*"|[^\s'"`$();&|<>]+)"""
EXCLUDE_OPTION = re.compile(r"(?<=\s)(--exclude(?:-dir)?)(=|\s+)" + _OPERAND)
RG_EXCLUDE = re.compile(r"""(?<=\s)(--i?glob|-g)(=|\s*)(['"]?)![^\s'"`$();&|<>]*\3""")
GIT_EXCLUDE_WORD = re.compile(r"""(?<=\s)(['"]?):(?:!|\^|\(exclude\))[^\s'"`$();&|<>]*\1(?=\s|$)""")


def blank_exclusions(text):
    """text with each exclusion operand of a grep, rg, tar, rsync or git command replaced by EXCL."""
    def blank(stage):
        words = strip_prefix(split_words(stage) or [])
        name = os.path.basename(words[0]) if words else ""
        if name in ("grep", "egrep", "fgrep", "rg", "tar", "rsync"):
            stage = EXCLUDE_OPTION.sub(r"\1=EXCL", stage)
        if name == "rg":
            stage = RG_EXCLUDE.sub("--glob=EXCL", stage)
        if name == "git":
            stage = GIT_EXCLUDE_WORD.sub("EXCL", stage)
        return stage
    return map_stages(text, blank)


# jq's switches that take no value, lowercased (-C, -M, -R, -S fold onto c, m, r, s). Every
# other option either reads a file (-f, --rawfile, --slurpfile, -L) or hands the filter a
# value it can print (--arg, --args, --jsonargs), and is not understood.
JQ_BOOL_SHORT = set("acejmnrs")
JQ_BOOL_LONG = {"--raw-output", "--raw-output0", "--join-output", "--compact-output", "--slurp",
                "--null-input", "--exit-status", "--sort-keys", "--raw-input", "--ascii-output",
                "--color-output", "--monochrome-output", "--tab", "--seq", "--stream", "--unbuffered"}
JQ_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def only_jq_path_names(pat, args, seg):
    """`jq '{env:(.env|keys?)}' ~/.claude/settings.json` reads settings.json: `.env` there
    is a field of the JSON, not a file. True only when the filter
    (the first positional) is what names the secret, and only as a path: not inside a jq
    string, which jq could print for a later command to open (an `import` path is one too);
    every option is a plain switch; no file operand names the secret; and nothing in the
    segment reads a file behind the guard's back. yq stays a read: its load and load_str
    operators open whatever file the filter names."""
    if reads_behind(seg):
        return False
    positional = []
    for a in args:
        if a.startswith("--"):
            if a not in JQ_BOOL_LONG:
                return False
        elif a.startswith("-") and len(a) > 1:
            if not set(a[1:]) <= JQ_BOOL_SHORT:
                return False
        else:
            positional.append(a)
    if not positional:
        return False
    filt, files = positional[0], positional[1:]
    if any(re.search(pat, s) for s in JQ_STRING.findall(filt)):
        return False
    return not any(re.search(pat, f) for f in files)


# grep and rg print file names (-l, -L, --files-with-matches, --files-without-match), counts (-c, --count)
# or nothing (-q), and rg --files lists the files it would search: none puts a line of a file on screen.
NAME_ONLY_LONG = ("--files-with-matches", "--files-without-match", "--count", "--count-matches", "--quiet", "--files")


def lists_names_only(cmd, args):
    """True for a grep or rg whose options make it print names, counts or nothing, wherever among its
    options they are. The text is lowercased, so `-C 3` (context) reads as `-c 3`: a `-c` that holds
    a digit, or is followed by a number, is context and not a count; so is `--json`."""
    if cmd not in ("grep", "egrep", "fgrep", "rg") or "--json" in args:
        return False
    for i, a in enumerate(args):
        if a in NAME_ONLY_LONG:
            return True
        if re.match(r"^-[a-z]*[lcq][a-z]*$", a):
            if "c" in a and not set(a) & set("lq") and i + 1 < len(args) and args[i + 1].isdigit():
                continue
            return True
    return False


def inert_command(pat, part):
    """One command of a pipeline, which names the secret: does it only list or count?"""
    words = strip_prefix(split_words(part) or [])
    if not words:
        return False
    cmd, args = words[0], words[1:]
    if cmd == "git" and args:
        _, rest = git_subcommand(args)
        if not rest:
            return False
        if rest[0] in INERT_GIT:
            return True
        cmd, args = "git " + rest[0], rest[1:]
    if cmd in INERT_COMMANDS:
        return True
    if cmd in NO_SUBSTITUTION:
        return not SUBSTITUTES.search(part)
    if cmd in ("awk", "gawk", "mawk", "nawk"):
        return inert_awk(args, part)
    if cmd == "ssh":
        bodies = [a for a in args if re.search(r"\s", a)]
        return (len(bodies) == 1 and bodies[0] == args[-1]
                and not any(re.search(pat, a) for a in args[:-1]) and not secret_dump(pat, bodies[0]))
    # find prints names; only its -exec family runs a command on what it finds. The mass
    # `*.env` harvest is refused earlier, by DANGEROUS_SHELL.
    if cmd == "find":
        return not any(a in ("-exec", "-execdir", "-ok", "-okdir") for a in args)
    if cmd in ("grep", "rg"):
        # `rg --files` prints the names of the files it would search and opens none of them.
        if lists_names_only(cmd, args):
            return True
        return not re.search(DUMP_COMMANDS, part) or only_pattern_names(pat, cmd, args, part)
    if cmd == "git grep":
        return only_pattern_names(pat, cmd, args, part)
    if cmd == "jq":
        return only_jq_path_names(pat, args, part)
    if cmd in RELOCATE_COMMANDS or cmd == "git mv":
        paths = [a for a in args if not a.startswith("-")]
        return len(paths) >= 2 and bool(re.search(pat, paths[-1]))
    return False


def inert_awk(args, part):
    """awk with no file operand and a program that can open nothing reads only its stdin,
    which the rest of the pipeline already answers for."""
    if SUBSTITUTES.search(part) or "<" in part:
        return False
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i].startswith(("--", "-f", "-i", "-l", "-e")):
            return False
        i += 2 if args[i] == "-v" else 1
    return len(args) == i + 1 and not AWK_OPENS.search(args[i])


def xargs_names_only(stage):
    """True for `xargs [options] grep -l ...` (or the bare `grep -l ...`): what it runs lists names, counts
    or nothing."""
    words = command_words(split_words(stage) or [])[1]
    return bool(words) and lists_names_only(os.path.basename(words[0]), words[1:])


def inert_segment(pat, seg):
    """Every command of the pipeline that names the secret must be inert. Judging the
    pipeline by its first command let `ls | cat apps/web/.env.local` through (found in the
    fix round for PR #23)."""
    stages = pipeline(seg)
    # An xargs whose command is a name-only grep or rg puts no content on screen, so it is no executor here.
    rest = [" true " if xargs_names_only(st) else st for st in stages]
    # A search pattern is text: the `|bash` of `grep -E 'x|bash'` is no pipe into a shell.
    if PIPE_TO_EXEC.search("|".join(blank_grep_patterns(st) for st in rest)):
        return False
    parts = [p for p in stages if seg_names_secret(pat, p)]
    return bool(parts) and all(inert_command(pat, p) for p in parts)


def seg_names_secret(pat, seg):
    """True when this segment names the secret, in its raw text or in any shell word
    (the words drop quotes and backslashes: `.e''nv.local`). Prose was already blanked
    by strip_prose, so a multi-word token left here is a nested command
    (`ssh host 'cat ~/.hermes/.env'`) and is checked as one."""
    if re.search(pat, seg):
        return True
    tokens = split_words(seg)
    return tokens is not None and any(re.search(pat, t) for t in tokens)


# A for loop over names: `for f in .mcp.json AGENTS.md; do git ls-files "$f"; done` (the
# replay of one project's commands). Its header only lists names, and each use of the variable is
# checked as the name itself, so `for f in .env; do cat $f; done` is still `cat .env`. A
# header whose list holds a substitution or a variable runs or hides something and stays
# checked as it always was. Brackets, braces, a colon or a comma make it Python's
# (`for p in ['~/.claude.json']:`), whose variable no `$p` reads: a first version without
# them lost two of the replay's real catches.
FOR_HEADER = re.compile(r"^\s*for\s+([a-z_]\w*)\s+in\s+([^`$<>()[\]{}:,]*?)\s*$")
# echo and printf print their arguments, which are names, not contents: inert only when
# nothing in the whole command substitutes, redirects into a file or hands its output to an
# executor, so one command cannot write a name and read it back (`printf .env > n; xargs -a n
# cat`). `2>&1` and `>/dev/null` write no file.
LOUD = re.compile(SUBSTITUTES.pattern + r"|>(?!\s*(?:&|/dev/null\b))|" + PIPE_TO_EXEC.pattern)


def loop_names(pat, low, segs):
    """(text, segments, loop headers) with each loop variable whose list names the secret
    replaced by that name."""
    names = {}
    for seg in segs:
        m = FOR_HEADER.match(seg)
        hit = m and [w for w in (split_words(m.group(2)) or []) if re.search(pat, w)]
        if hit:
            names[m.group(1)] = hit[0]
    if not names:
        return low, segs, set()
    for var, name in names.items():
        low = re.sub(r"\$\{%s\}|\$%s(?!\w)" % (var, var), lambda _: name, low)
    segs = SEGMENT_SPLIT.split(low)
    return low, segs, {s for s in segs if (h := FOR_HEADER.match(s)) and h.group(1) in names}


def echoes(seg):
    """True when seg is one echo or printf, with no pipe. `printf -v x NAME` prints nothing:
    it assigns the name to a variable a later `cat "$x"` reads."""
    parts = pipeline(seg)
    words = strip_prefix(split_words(parts[0]) or []) if len(parts) == 1 else []
    return bool(words) and (words[0] == "echo" or (words[0] == "printf" and not any(
        w.startswith("-v") for w in words[1:])))


# A relative name that has the shape of a store wherever it sits: what `cd $UNKNOWN && cat
# secrets.yaml` or `cat hindsight-bearer.txt` reads when the guard cannot tell which directory
# the cd went to. Matched against the lowercased word.
STORE_SHAPED_NAME = re.compile(r"(?:^|/)(?:secrets[^/]*|[^/]*bearer[^/]*|[^/]*\.token|[^/]*\.pem)$")
UNREADABLE_DIR = re.compile(r"[$`*?\[{(]")
# A directory that holds stores is read by whatever walks it: `grep -r . ~/.hindsight` prints every
# store in it, and no store's name is in the command. credentials/ is refused by its own name
# (FORGE_CREDENTIALS_PATH); these are the others, each with the name of a store inside it, which
# stands for the directory in the text the patterns see. forge's config/ always counts: whether
# it holds secrets* is on the disk, and a guard that reads the disk answers differently in a
# scratch copy and in the checkout. A directory ABOVE one of them, walked recursively, counts as well
# ($HOME, `~/.hindsight/..`, the directory above the checkout; round 9b); the repository root and `.`
# there do not: a recursive grep of them is ordinary work, and test_guard_tool_use.py KNOWN_GAPS says so.
DIR_READERS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "find", "tar", "bsdtar", "cp", "rsync", "zip"}


# The store names a glob is matched against, as path components, lowercase. The last one is the
# file a glob can name; the ones before it must be in the word itself, literally. `*` is any name
# (every file of credentials/), <forge> is the checkout's own name, as FORGE_CREDENTIALS and
# FORGE_CONFIG_SECRETS take it, so `cat config/*` in another project is not a read of forge's.
# A store's backup (`.claude.json.bak`) is the same store, and a name with no directory
# (`.mcp.json`) is one wherever it sits.
_FORGE_DIR = "<forge>"
STORE_GLOB_NAMES = [n.split("/") for n in (
    ".claude.json", ".mcp.json", ".npmrc", ".git-credentials", ".secrets", ".envrc",
    "secrets.json", "secrets.env", "gate.token", "ovcli.conf", "claude-code.json", "coding-agent.json",
    "control.token", "credentials.json", "cp.env", "api.env",
    ".codex/config.toml", ".aws/credentials", ".aws/config", ".kube/config", ".docker/config.json",
    ".config/gh/hosts.yml", ".supabase/access-token", ".vercel/auth.json",
    ".ssh/id_rsa", ".ssh/id_ed25519", ".ssh/id_ecdsa", ".ssh/id_dsa",
    ".hindsight/session.json", ".hindsight/coding-agent.json", ".hindsight/claude-code.json",
    ".hindsight/control.token", ".hindsight/x.token", ".hindsight/x.env", ".hindsight/profiles/x.env",
    _FORGE_DIR + "/credentials/*", _FORGE_DIR + "/config/secrets.json", _FORGE_DIR + "/config/secrets.yaml",
    _FORGE_DIR + "/config/secrets.env",
)]
# A glob must say which store it means: the characters before its first `*` or `?`, a `[..]` as one,
# at least this many (`.cl*` and `sec*` do, `.c*`, `.*` and `*.json` do not).
GLOB_PIN = 3


def store_glob(path):
    """A store path the absolute path `path` could name, when its last component is a glob that
    can expand to a store name (matched against the names above, never against the disk); else
    None. A directory before the last component is compared literally, so one that is itself a
    glob matches nothing."""
    import fnmatch
    comps = path.lower().split("/")
    last = comps[-1]
    if not GLOB.search(last):
        return None
    pin = len(re.findall(r"\[[^\]]*\]|.", re.match(r"(?:\[[^\]]*\]|[^*?\[])*", last).group()))
    for names in STORE_GLOB_NAMES:
        dirs = [_FORGE_BASE if d == _FORGE_DIR else d for d in names[:-1]]
        name = names[-1]
        if comps[-1 - len(dirs):-1] != dirs:
            continue
        if name != "*" and not (fnmatch.fnmatchcase(name, last) or fnmatch.fnmatchcase(name + ".bak", last)):
            continue
        if not dirs and pin < GLOB_PIN:
            continue
        return "/".join(comps[:-1] + ["x" if name == "*" else name])
    return None


def store_dirs():
    """The directories that hold stores, as absolute paths."""
    return [os.path.join(HOME, ".hindsight"), os.path.join(HOME, ".hindsight", "profiles"), os.path.join(FORGE, "config")]


def store_below(path):
    """A store file in a directory below path (a store directory inside it), else None: `grep -r .` of
    $HOME reads ~/.hindsight/session.json (round 9b, item 3)."""
    low = path.lower().rstrip("/")
    for d in store_dirs():
        if d.lower().startswith(low + "/"):
            return d + "/" + store_dir_file(d)
    return None


def recursive_reader(cmdname, words):
    """True when the command walks the directories it is given: ripgrep, find and tar always, grep,
    cp, rsync and zip with their recursion flag."""
    if cmdname in ("rg", "ag", "ack", "find", "tar", "bsdtar"):
        return True
    short = "".join(w[1:] for w in words if w.startswith("-") and not w.startswith("--"))
    if cmdname in ("grep", "egrep", "fgrep"):
        return bool(set("rR") & set(short)) or any(w in ("--recursive", "--dereference-recursive") for w in words)
    if cmdname == "cp":
        return bool(set("rRa") & set(short)) or any(w in ("--recursive", "--archive") for w in words)
    if cmdname == "rsync":
        return bool(set("ra") & set(short)) or any(w in ("--recursive", "--archive") for w in words)
    return cmdname == "zip" and ("r" in short or "--recurse-paths" in words)


def store_dir_file(path):
    """A store file's name when path is a directory that holds stores, else None."""
    low, home = path.lower(), HOME.lower()
    if low == home + "/.hindsight":
        return "session.json"
    if low == home + "/.hindsight/profiles":
        return "x.env"
    if low.endswith("/" + _FORGE_BASE + "/config"):
        return "secrets.json"
    return None


def cd_resolved(cmd, pats):
    """cmd with each relative word that a cd of the command points at a store replaced by its
    absolute path, so the secret check sees `cd credentials && cat x.txt` as a read of
    credentials/x.txt (Codex; until then a cd was not followed and the owner accepted
    the gap). The cwd of the event is the first directory; cd and pushd to a
    literal path move it across && ; and newlines, one after `||` adds a second place the
    command may be in. A cd to a path the guard cannot read (a variable, a substitution, a
    glob, `cd -`) leaves it unsure until an absolute cd: a relative word with the shape of a
    store (STORE_SHAPED_NAME) is then read as <forge>/credentials/<word>. Only a word whose
    absolute path names a store and whose own text does not is replaced, so a grep pattern or
    an awk program keeps the reading it had. The caller checks the original text as well."""
    segs, seps = SEGMENT_SPLIT.split(cmd), SEGMENT_SPLIT.findall(cmd)
    start_cwd = CWD[0]
    bases, unsure, env, out = [CWD[0]], False, {"HOME": HOME}, []
    groups, closing = [], []
    for i, seg in enumerate(segs):
        # A subshell `( ... )` keeps its cd and assignments to itself; a brace group's stay (as in
        # _segments_write). What a segment closes is undone before the next one is read (round 9b, item 5).
        for closer in closing:
            if groups:
                kind, saved = groups.pop()
                if kind == "(" and closer == ")":
                    bases, unsure, env = saved[0], saved[1], saved[2]
        marked, opens, closing = group_marks(seg)
        groups += [(kind, (bases, unsure, dict(env))) for kind in opens]
        words = split_words(marked)
        if not words:
            out.append(seg)
            continue
        env["PWD"] = bases[-1]
        if len(words) == 1 and re.match(r"^[A-Za-z_]\w*=", words[0]):
            k, v = words[0].split("=", 1)
            v = expand(v, env)
            if v is not None:
                env[k] = v
            out.append(seg)
            continue
        if words[0] in ("cd", "pushd"):
            args = [w for w in words[1:] if not w.startswith("-") or w == "-"]
            d = expand(args[0] if args else "~", env)
            if d is None or d == "-" or UNREADABLE_DIR.search(d):
                unsure = True
            else:
                unsure = unsure and not os.path.isabs(d)
                where = os.path.normpath(os.path.join(bases[-1], d))
                bases = bases + [where] if i and seps[i - 1] == "||" else [where]
            out.append(seg)
            continue
        first, subcommand, cmdname, stage = True, False, "", []
        for k, w in enumerate(words):
            if w == "|":
                first = True
                continue
            if subcommand:
                subcommand = False
                if not w.startswith("-"):
                    continue
            if first:
                subcommand = w == "git"
                first = (w in ("do", "then", "else", "if", "elif", "while", "until", "!", "sudo", "command",
                               "nohup", "time", "env", "exec") or bool(re.match(r"^[A-Za-z_]\w*=", w)))
                if first:
                    subcommand = False
                else:
                    cmdname = os.path.basename(w)
                    stage = words[k + 1:words.index("|", k) if "|" in words[k:] else len(words)]
                continue
            if w.startswith("-") or re.search(r"[\s{},;<>()|&`]", w):
                continue
            e = expand(w, env)
            if e is not None and GLOB.search(e) and not re.search(r"[$`]", e):
                # A glob that can expand to a store name is replaced by one the patterns see.
                hit = next(filter(None, (store_glob(os.path.normpath(os.path.join(b, e))) for b in bases)), None)
                if hit:
                    seg = re.sub(r"(?<![\w./-])" + re.escape(w) + r"(?![\w./-])", lambda _, h=hit: h, seg, count=1)
                continue
            if GLOB.search(w) or e is None or re.search(r"[$`]", e) or any(re.search(p, w.lower()) for p in pats):
                continue
            paths = [os.path.normpath(os.path.join(b, e)) for b in bases]
            if unsure and not os.path.isabs(e) and STORE_SHAPED_NAME.search(e.lower()):
                paths.append(os.path.join(FORGE, "credentials", e))
            hit = next((a for a in paths if any(re.search(p, a.lower()) for p in pats)), None)
            # A directory that holds a store, given to a command that reads what is inside it, is
            # rewritten to a store file in it. Each word is replaced in turn, so `grep -r config
            # config` rewrites the operand as well as the pattern.
            if not hit and cmdname in DIR_READERS:
                hit = next((a + "/" + f for a in paths if (f := store_dir_file(a))), None)
                # A directory above a store, walked: the repository root and `.` there stay readable. The
                # pattern word of a grep and a copy's destination are rewritten too, and stay allowed: the
                # check treats a store name in a pattern, or in the destination of a copy, as inert.
                if not hit and recursive_reader(cmdname, stage):
                    hit = next((f for a in paths if a not in (PROJECT, start_cwd) and (f := store_below(a))), None)
            if hit:
                seg = re.sub(r"(?<![\w./-])" + re.escape(w) + r"(?![\w./-])", lambda _, h=hit: h, seg, count=1)
        out.append(seg)
    return "".join(x + (seps[i] if i < len(seps) else "") for i, x in enumerate(out))


def secret_dump(pat, low):
    # Cheap pre-check on the raw text and on the text with quotes and backslashes
    # removed, so `.e''nv.local` and `.en\v.local` are seen; most commands stop here.
    flat = re.sub(r"['\"\\]", "", low)
    if not re.search(pat, low) and not re.search(pat, flat):
        return False
    # A public key is not a secret: `cat ~/.ssh/id_ed25519.pub` (break-it round, U64). Only
    # when every mention ends in .pub and nothing rebuilds a name (`${f%.pub}`) or pipes it on.
    if (pat in SSH_KEYS and not re.search(r"id_(?:rsa|ed25519|ecdsa|dsa)(?!\.pub\b)", flat)
            and not re.search(r"\$\{|\$\(|`", low) and not PIPE_TO_EXEC.search(low)):
        return False
    low = re.sub(r"\\\r?\n", " ", low)
    segs = SEGMENT_SPLIT.split(low)
    low, segs, headers = loop_names(pat, low, segs)
    quiet = not LOUD.search(low)
    for seg in segs:
        if seg in headers or (quiet and echoes(seg)):
            continue
        if seg_names_secret(pat, seg) and not inert_segment(pat, seg):
            return True
    # Reaching here means the command names the secret (the pre-check above), so a read
    # of the previous argument or a file descriptor may be reading it: `ls .env; cat $_`.
    return any(INDIRECT_READ.search(AWK_PROGRAM.sub(awk_fields, seg)) for seg in segs)


def awk_fields(m):
    """An awk program that can open nothing, blanked: its $N are fields of its input. One
    that can (`system("cat " $0)`) is kept, and its $0 still counts as a read."""
    return m.group(0) if AWK_OPENS.search(m.group(2)) else m.group(1) + "''"


# ------------------------------------------------------------------ harness self-protection
#
# Harness files an agent's Bash call may not write: the hooks, skills and agents dirs,
# settings.json, lefthook's config (and a lefthook-local.yml, which overrides it), husky's
# hooks dir (a downstream project's git hook manager; forge's addition 5), and the installed git hooks.
# The old rule looked only at the word after cp/mv/rm and needed a "/" before ".claude", so `cp /tmp/g.py .claude/hooks/guard_tool_use.py` and
# `sed -i ... .claude/hooks/guard_tool_use.py` both passed (M6).
#
# Only paths inside this repository, under ~/.claude, or in MACHINE_HARNESS count. A
# scratch copy of the repo in /tmp is not the harness, and blocking it stopped the harness
# being tested.
# The Write and Edit tools are not blocked here, so their change is a diff in the
# transcript.
HARNESS_PATH = re.compile(
    r"(?:^|/)\.(?:claude|gemini)/(?:hooks|skills|agents)(?:/|$)"
    r"|(?:^|/)\.claude/settings(?:\.local)?\.json$"
    r"|(?:^|/)\.?lefthook(?:-local)?\.ya?ml$"
    r"|(?:^|/)\.husky(?:/|$)"
    r"|(?:^|/)\.git/hooks(?:/|$)"
    # A hooksPath written straight into the repo config, without the word `core.`.
    r"|(?:^|/)\.git/config$"
)
REDIRECT_TARGET = re.compile(r"(?:^|[^<>&0-9])(?:[0-9]?>>?|&>>?|>\|)\s*['\"]?([^\s'\";&|<>()]+)")
# A `>` inside quotes is text for the command that gets it (`sed 's/ ->.*//'`, `grep -o
# '<title>.*</title>'`: the replay of one project's commands read both as a write into the glob `.*`), unless
# something in the same command runs quoted or piped text as shell, or writes from its own
# program (`echo '> x' | sh`, `awk '{print > "x"}'`): then it stays a redirect.
# An interpreter's spawn (os.system, subprocess, child_process, execSync) runs one too.
RUNS_QUOTED = re.compile(r"\b(?:(?:ba|z|da|k|fi|c|a|tc|pw)?sh|eval|su|xargs|watch|script|parallel|flock|source"
                         r"|exec\w*|spawn\w*|system|popen|subprocess|child_process|[gmn]?awk|perl|ruby)\b")
# An interpreter's own code: the argument of -c / -e / -p / --eval, or a heredoc body.
# Running a script that lives in the harness (`node .claude/hooks/test_x.mjs`) is not a
# write, so only the code text counts, never the rest of the command line.
_INTERP = r"(?:python3?|node|perl|ruby|deno|bun|php)"
INLINE_CODE = re.compile(r"(?:^|[\s;&|(/])" + _INTERP + r"\b[^\n'\"]*?\s-(?:c|e|p|pe|E|-eval)\s+(['\"])(.*?)(?<!\\)\1", re.S)
HEREDOC_CODE = re.compile(r"(?:^|[\s;&|(/])" + _INTERP + r"\b[^\n]*?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\s*(?:\n|$)", re.S)
WRITEISH = re.compile(
    r"open\([^)]*,\s*['\"][^'\"]*[wax+]|write|unlink|remove|rename|replace\(|truncate"
    r"|copy|move|symlink|rmsync|rmtree|rmdir|chmod")
# The directories that hold the harness. Removing, moving or replacing one of them takes
# every harness file inside with it: `rm -rf .claude` passed while `rm -rf .claude/hooks`
# was refused (break-it round, U47).
HARNESS_DIRS = {os.path.join(PROJECT, d) for d in (".claude", ".gemini", ".git")} | {os.path.join(HOME, ".claude")}
# The harness outside every project (docs/command-guard-design.md, addition 3). In the downstream project
# the guard sits under .claude/hooks/ and is shielded by that; in forge it does not, and an
# downstream agent could `sed -i` it. forge's live hooks/ and config/guard/ are found from this
# file's own location, so a scratch copy of forge stays writable. ~/.codex/hooks.json is
# Codex's ~/.claude/settings.json: forge writes the same user hooks into both (addition 6),
# and a Bash rewrite of it would last until the next forge session regenerated it. The consent
# window (--consent) runs in every session: config/gateway.json names the adapter it launches
# and scripts/consent/ holds the adapters, so a Bash write to either would switch the window off.
MACHINE_HARNESS = [os.path.join(FORGE, "hooks"), os.path.join(FORGE, "config", "guard"),
                   os.path.join(FORGE, "config", "gateway.json"), os.path.join(FORGE, "scripts", "consent"),
                   os.path.join(HOME, ".codex", "hooks.json")]
# The directories that hold it, counted as HARNESS_DIRS are: `rm -rf <forge>/config`.
MACHINE_DIRS = {FORGE, os.path.join(FORGE, "config"), os.path.join(HOME, ".codex")}
# A project's own harness paths, from its config file (harness_paths); set by main().
PROJECT_HARNESS = []
# Not here: gateway.json and consent. Every name added multiplies the alternatives of a glob target
# (17 names a part, 19 would make `rm -rf a/*/*/*/x` 6859 of the 5000 the budget allows), so a glob
# such as `config/gatew*` still reaches config/gateway.json unseen; a follow-up has to match globs
# against MACHINE_HARNESS without adding names.
# The names a glob in a target is matched against, without looking at the disk, so the
# suite's empty scratch repo, CI and the live checkout all give the same answer.
HARNESS_NAMES = (".claude", ".gemini", ".git", "hooks", "skills", "agents", "settings.json",
                 "settings.local.json", "config", "lefthook.yml", "lefthook.yaml",
                 ".lefthook.yml", "lefthook-local.yml", "guard", ".husky",
                 "hooks.json")
GLOB = re.compile(r"[*?\[]")
# How much a write target covers. DEST is a copy's destination directory: only a harness
# path itself counts there, so `cp notes.md .` and `cp x .claude/` pass. WRITE is a file
# written or a pathspec restored: a harness dir counts too. WHOLE is a delete, a move's
# source, or a sync of a directory's contents: the repository root counts as well.
DEST, WRITE, WHOLE = 0, 1, 2


# One call may check this many alternatives, glob or brace, over all its write targets. A glob of
# bare `*` parts stands for 17 names a part, so six of them are 24 million paths, which took over
# 40 s and ran past the 10 s a hook has (round 9, guard-crash); 5000 take about 0.1 s. Past the
# budget the command is refused: a check that gives up must not let the write through.
CANDIDATE_BUDGET = 5000
BUDGET = [CANDIDATE_BUDGET]
OVER_BUDGET = [False]
GLOB_SEEN = {}


class OverBudget(Exception):
    """The call named more alternatives than CANDIDATE_BUDGET."""


def counted(alternatives):
    """alternatives, each one spent from the call's budget; OverBudget when it runs out."""
    for alt in alternatives:
        BUDGET[0] -= 1
        if BUDGET[0] < 0:
            raise OverBudget
        yield alt


def glob_candidates(p):
    """The harness names each globbed component of p could expand to, one path at a time."""
    import fnmatch
    import itertools
    known = HARNESS_NAMES + tuple(os.path.basename(b) for b in PROJECT_HARNESS)
    # "_g_" stands for any other name, so `> .claude/hooks/*.py` is still inside hooks/.
    names = [[n for n in known if fnmatch.fnmatchcase(n, part)] + ["_g_"] if GLOB.search(part) else [part]
             for part in p.split("/")]
    return map("/".join, itertools.product(*names))


def glob_reaches_harness(p):
    """False when a glob in p cannot expand to a harness path: the literal directories before its first
    glob part lead somewhere that is neither inside the harness, nor above it, nor the harness itself,
    and no later part climbs out with `..`. Such a target needs no expansion, so `cp x build/*/*/*/*/*/*`
    is not spent from the budget (round 9b, item 6). Where it could, every alternative is still asked."""
    parts = p.split("/")
    k = next(i for i, part in enumerate(parts) if GLOB.search(part))
    if ".." in parts[k:]:
        return True
    literal = "/".join(parts[:k]) or ("/" if p.startswith("/") else "")
    low = os.path.realpath(os.path.join(CWD[0], literal)).rstrip("/")
    roots = [os.path.realpath(r) for r in list(HARNESS_DIRS) + MACHINE_HARNESS + list(MACHINE_DIRS) + PROJECT_HARNESS
             + [os.path.join(PROJECT, ".husky")]]
    return any(low == r or low.startswith(r + "/") or r.startswith(low + "/") for r in roots)


def harness_target(p, level=WRITE, from_glob=False):
    """True when p names a harness file of THIS checkout, of ~/.claude or of MACHINE_HARNESS."""
    if not p:
        return False
    p = p.strip("'\"")
    if p.startswith("~"):
        p = HOME + p[1:]
    if GLOB.search(p):
        # Asked once per target: the two cuts of _harness_write put the same one to this twice.
        key = (p, level, CWD[0])
        if key not in GLOB_SEEN:
            GLOB_SEEN[key] = glob_reaches_harness(p) and any(
                harness_target(c, level, True) for c in counted(glob_candidates(p)))
        return GLOB_SEEN[key]
    # A relative path resolves against the directory the command runs in (the payload's
    # `cwd`), so `.claude/hooks/x` inside a scratch copy is the copy, not the harness.
    real = os.path.realpath(os.path.join(CWD[0], p))
    # MACHINE_HARNESS lies outside the project, so it is checked before the scope test.
    if any(real == b or real.startswith(b + "/") for b in MACHINE_HARNESS):
        return True
    if level >= WRITE and real in MACHINE_DIRS:
        return True
    # A project's harness path, and a directory below the project root that holds one.
    for b in PROJECT_HARNESS:
        if real == b or real.startswith(b + "/"):
            return True
        if level >= WRITE and real.startswith(PROJECT + "/") and b.startswith(real + "/"):
            return True
    inside = any(real == base or real.startswith(base + "/")
                 for base in (PROJECT, os.path.join(HOME, ".claude")))
    # The hooks' bytecode cache counts too. Had anything import the guard from it, a
    # forged .pyc (its header needs only the mtime and size `stat` prints) would run in the
    # guard's place; exempting it let a plain `cp` write one.
    if not inside:
        return False
    # A name a glob might expand to counts only where the harness really is, so
    # `rm -rf apps/web/.next/*` is not taken for a lefthook.yml in .next.
    if from_glob:
        root = PROJECT if real == PROJECT or real.startswith(PROJECT + "/") else HOME
        hit = HARNESS_PATH.match(os.path.relpath(real, root))
    else:
        hit = HARNESS_PATH.search(real.replace("\\", "/").rstrip("/"))
    if hit:
        return True
    return (level >= WRITE and real in HARNESS_DIRS) or (level >= WHOLE and real == PROJECT)


def brace_group(word):
    """(start, end, parts) of the leftmost `{a,b}` group of word, else None. A group needs a comma:
    `{x}` is text, as in the shell. One pass, so a word of nothing but braces costs what it is long."""
    stack, best = [], None
    for i, c in enumerate(word):
        if c == "{":
            stack.append((i, []))
        elif c == "," and stack:
            stack[-1][1].append(i)
        elif c == "}" and stack:
            start, commas = stack.pop()
            if commas and (best is None or start < best[0]):
                best = (start, i, commas)
    if best is None:
        return None
    start, end, commas = best
    cuts = [start] + commas + [end]
    return start, end, [word[cuts[k] + 1:cuts[k + 1]] for k in range(len(cuts) - 1)]


def brace_expansions(word):
    """The words the shell makes of word by brace expansion, one at a time: `a{b,c}d` is `abd`, `acd`."""
    group = brace_group(word)
    if group is None:
        yield word
        return
    start, end, parts = group
    for part in parts:
        yield from brace_expansions(word[:start] + part + word[end + 1:])


def brace_words(word):
    """Every word word stands for, each counted against the call's budget. A word with a space or a
    quote is a program or text (awk's, a JSON body, a commit message), not a name."""
    if "{" not in word or "," not in word or re.search(r"[\s'\"]", word):
        return [word]
    if len(word) > 2000:  # each alternative rescans the word: too long to expand, too odd to allow
        raise OverBudget
    return list(counted(brace_expansions(word)))


# A brace, a comma and the shell's other characters that a quote, a backslash or `${...}` keeps from
# being a brace expansion, swapped for private-use characters while the word is expanded.
_BRACE_MASK = {"{": "\ue000", "}": "\ue001", ",": "\ue002"}
_BRACE_UNMASK = {v: k for k, v in _BRACE_MASK.items()}
WORD_END = " \t\r\n;&|()<>"


def _mask(chunk):
    return "".join(_BRACE_MASK.get(c, c) for c in chunk)


def _words_of(text):
    """text as (piece, is_word): the words the shell would cut it into at blanks and at ; & | ( ) < >,
    a quote keeping what it holds in one word, and the stretches between them."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = i
        if text[i] in WORD_END:
            while j < n and text[j] in WORD_END:
                j += 1
            out.append((text[i:j], False))
        else:
            while j < n and text[j] not in WORD_END:
                if text[j] == "\\":
                    j += 2
                elif text[j] in "'\"":
                    q, j = text[j], j + 1
                    while j < n and text[j] != q:
                        j += 2 if (q == '"' and text[j] == "\\") else 1
                    j += 1
                else:
                    j += 1
            out.append((text[i:min(j, n)], True))
        i = min(j, n)
    return out


def _masked(word):
    out, i, n = [], 0, len(word)
    while i < n:
        c = word[i]
        if c == "\\":
            out.append(_mask(word[i:i + 2]))
            i += 2
        elif c in "'\"":
            j = i + 1
            while j < n and word[j] != c:
                j += 2 if (c == '"' and word[j] == "\\") else 1
            out.append(_mask(word[i:j + 1]))
            i = j + 1
        elif word.startswith("${", i):
            j = word.find("}", i)
            j = n - 1 if j < 0 else j
            out.append(_mask(word[i:j + 1]))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def brace_text(text):
    """text with each word that is a brace expansion replaced by the words it stands for, as the shell
    makes them before the command opens anything: `cat .{mcp,x}.json` reads `.mcp.json` and `.x.json`
    (round 9b, item 2). Quotes, a backslash and `${...}` keep a brace from being one. Each alternative is
    counted against the call's budget; OverBudget when it runs out."""
    if "{" not in text or "," not in text:
        return text
    out = []
    for piece, is_word in _words_of(text):
        masked = _masked(piece) if is_word and "{" in piece and "," in piece else ""
        if "{" not in masked or "," not in masked:
            out.append(piece)
            continue
        if len(masked) > 2000:
            raise OverBudget
        out.append(" ".join("".join(_BRACE_UNMASK.get(c, c) for c in w) for w in counted(brace_expansions(masked))))
    return "".join(out)


def fuse_substitutions(seg):
    """seg with the blanks inside each command substitution outside quotes made part of its word, so
    `.claude/$(echo settings).json` is one word, as the shell has it, and not a path and a stray name."""
    spans = _quoted_spans(seg)
    return SUBSTITUTION.sub(
        lambda m: m.group(0) if any(a <= m.start() < b for a, b in spans) else re.sub(r"\s", "\x01", m.group(0)), seg)


def write_targets(seg, quoted_text=False):
    """(path, level) for each path a single shell segment writes to, as far as its text
    shows. A copy or move also writes <destination>/<name of each source>, so
    `cp -r /tmp/evil/.claude .` is a write to .claude. With quoted_text, a `>` inside
    quotes is not a redirect (RUNS_QUOTED)."""
    spans = _quoted_spans(seg) if quoted_text else []
    # A redirect into a brace word writes nothing in a shell ("ambiguous redirect"), so every word it
    # stands for is checked as if it were the one written.
    # The target stops at a `(`, so one that ends in `$` is the start of a command substitution.
    out = [(t, WRITE) for m in REDIRECT_TARGET.finditer(seg)
           for t in brace_words(m.group(1) + ("(" if m.group(1).endswith("$") and seg[m.end():m.end() + 1] == "(" else ""))
           if not any(a <= seg.find(">", m.start()) < b for a, b in spans)]
    words = [w for word in strip_prefix(split_words(fuse_substitutions(seg)) or []) for w in brace_words(word)]
    if not words:
        return out
    cmd, args = os.path.basename(words[0]), words[1:]
    paths = [a for a in args if not a.startswith("-")]
    if cmd in RELOCATE_COMMANDS:
        dest, srcs = paths[-1:], paths[:-1]
        for i, a in enumerate(args):
            # -t takes the destination, alone or at the end of a cluster (`-rt DIR`,
            # `-tDIR`, `install -Dt DIR`); rsync's -t is --times (break-it round, U46).
            m = re.match(r"^-[a-zA-Z]*t(.*)$", a) if cmd != "rsync" else None
            if (a == "--target-directory" or (m and not m.group(1))) and i + 1 < len(args):
                dest, srcs = [args[i + 1]], [p for p in paths if p != args[i + 1]]
            elif m and m.group(1):
                dest, srcs = [m.group(1)], paths
            elif a.startswith("--target-directory="):
                dest, srcs = [a.split("=", 1)[1]], paths
        for d in dest:
            out.append((d, DEST))
            for s in srcs:
                name = os.path.basename(s.rstrip("/"))
                # A trailing / or /. copies the directory's contents, whose names are unknown.
                whole = s.endswith("/") or s.endswith("/.") or not name
                out.append((d, WHOLE) if whole else (os.path.join(d, name), WRITE))
        # A move removes its sources; a link is a second name for its source, so a later
        # write through the link lands in the harness (break-it round, U73).
        if cmd == "mv":
            out += [(s, WHOLE) for s in srcs]
        elif cmd == "ln" or (cmd == "cp" and any(re.match(r"^-[a-zA-Z]*[sl]", a) or a in ("--link", "--symbolic-link") for a in args)):
            out += [(s, WRITE) for s in srcs]
    elif cmd in ("rm", "unlink", "shred"):
        out += [(p, WHOLE) for p in paths]
    elif cmd in ("truncate", "touch", "tee"):
        out += [(p, WRITE) for p in paths]
    elif cmd in ("sed", "perl") and any(re.match(r"^-[a-zA-Z]*i", a) or a.startswith("--in-place") for a in args):
        out += [(p, WRITE) for p in paths]
    elif cmd == "dd":
        out += [(a[3:], WRITE) for a in args if a.startswith("of=")]
    elif cmd == "git":
        where, sub = git_subcommand(args)
        at = lambda a: os.path.join(where, a)
        if sub and sub[0] in ("checkout", "restore"):
            out += [(at(a), WRITE) for a in sub[1:]]
        # `git rm lefthook.yml` switches the pre-commit checks off and `git rm` of the Stop
        # hook makes it exit 127; both passed this rule until it was found in review.
        elif sub and sub[0] in ("rm", "mv"):
            out += [(at(a), WHOLE) for a in sub[1:] if not a.startswith("-")]
    return out


def expand(word, env):
    """Expand ~, $VAR and ${VAR} from assignments made earlier in the same command (and $PWD,
    the directory the command runs in, which a cd of the command moves).
    Returns None when a variable is unknown, so the caller can stay conservative."""
    if word.startswith("~"):
        word = HOME + word[1:]
    unknown = []

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in env:
            return env[name]
        unknown.append(name)
        return ""
    out = re.sub(r"\$\{(\w+)\}|\$(\w+)", sub, word)
    return None if unknown else out


def substitution_in_harness(t):
    """True when a write target holds a command substitution and the directory before it is a harness
    path: `tee .claude/$(echo settings).json` writes what the guard cannot resolve, and fails closed
    only where it could be the harness (round 9b, item 8). A substitution at the start of the target
    is judged by the directory the command runs in."""
    m = re.search(r"\$\(|`", t)
    if not m:
        return False
    before = t[:m.start()]
    return harness_target(before[:before.rfind("/") + 1] or ".", WRITE)


def _harness_write(cmd):
    text = re.sub(r"\\\r?\n", " ", cmd)
    # Two cuts of the same command, as in segments(): the one that leaves quotes whole
    # keeps `sh -c 'true; tee lefthook.yml'` and `sh -c 'x | tee lefthook.yml'` in one
    # piece, and the quote-blind one runs last, so the directory the interpreter check
    # below resolves against is the one it always was. A write found by either counts.
    start = CWD[0]
    if _segments_write(split_unquoted(text, SEGMENT_SPLIT), pipeline, start):
        return True
    if _segments_write(SEGMENT_SPLIT.split(text), PIPE.split, start):
        return True
    # A pipe into a shell that runs its input, which names a harness path.
    for cut in (split_unquoted(text, SEGMENT_SPLIT), SEGMENT_SPLIT.split(text)):
        if any(names_harness(before) for seg in cut for before in piped_shell_inputs(seg)):
            return True
    # An interpreter's inline code or heredoc that names a harness path and writes.
    code = [m.group(2) for m in INLINE_CODE.finditer(cmd)] + [m.group(2) for m in HEREDOC_CODE.finditer(cmd)]
    # Only a string literal that is a bare path counts. Code that edits a document which
    # merely MENTIONS `.claude/settings.json` in prose was the main false positive when
    # 8,735 recorded commands were replayed through this rule.
    for c in code:
        if WRITEISH.search(c) and any(harness_target(t) for t in re.findall(r"['\"]([^'\"\s`]+)['\"]", c)):
            return True
    return False


def group_marks(seg):
    """(seg without the punctuation of the groups it opens and closes, the groups it opens as
    "(" and "{", what it closes as ")" and "}"). Only what starts or ends the command counts:
    `$(...)` and a parenthesis in quotes balance themselves."""
    s, opens = seg.lstrip(), []
    while True:
        if s.startswith("("):
            opens.append("(")
        elif s.startswith("{") and s[1:2].isspace():
            opens.append("{")
        else:
            break
        s = s[1:].lstrip()
    if s.strip() == "}":
        return "", opens, ["}"]
    bare = s
    for a, b in reversed(_quoted_spans(s)):
        bare = bare[:a] + " " * (b - a) + bare[b:]
    closes = [")"] * max(0, bare.count(")") - bare.count("("))
    for _ in closes:
        s = s.rstrip()
        if s.endswith(")"):
            s = s[:-1]
    return s, opens, closes


# The nested bodies already walked, so a body that both cuts of its outer command reach is judged once.
NESTED_SEEN = set()


def _nested_write(part, base, env):
    """True when a nested shell's body (`bash -c '...'`) writes the harness. The body is walked as a
    command of its own, from the directory and the variables of the command that runs it, so its cd
    moves it (round 9b, item 7) and a variable the command, or the env before it, sets reaches it
    (item 1)."""
    assigns, words, _, chdir = command_words(split_words(part) or [])
    bodies = nested_bodies(words, NESTING_SHELLS + ("xargs",))
    if not bodies:
        return False
    inner = dict(env)
    for k, v in assigns:
        v = expand(v, env)
        if v is not None:
            inner[k] = v
    saved = CWD[0]
    try:
        where = _run_dir(base, chdir, env)
        for a in bodies:
            text = re.sub(r"\\\r?\n", " ", a)
            key = (text, where, tuple(sorted(inner.items())))
            if key in NESTED_SEEN:
                continue
            NESTED_SEEN.add(key)
            if (_segments_write(split_unquoted(text, SEGMENT_SPLIT), pipeline, where, inner)
                    or _segments_write(SEGMENT_SPLIT.split(text), PIPE.split, where, inner)):
                return True
    finally:
        CWD[0] = saved
    return False


def _run_dir(base, chdir, env):
    """The directory a command runs in: base, or where `env -C` or `sudo -D` moves it."""
    if not chdir:
        return base
    d = expand(chdir, env)
    return os.path.join(base, chdir if d is None else d)


def _segments_write(segs, split_pipes, start, inherited=None):
    base, env = start, dict(inherited or {"HOME": HOME})
    env["PWD"] = start
    groups = []
    for seg in segs:
        # A subshell `( ... )` keeps its cd and assignments to itself; a brace group `{ ...; }` runs
        # in the shell that holds it, so what it changes stays changed.
        seg, opens, closes = group_marks(seg)
        groups += [(kind, base, dict(env)) for kind in opens]
        words = split_words(seg) or []
        # Follow `NAME=value` and `cd dir` within the command, so `S=/tmp/x; cd $S &&
        # cp a .claude/hooks/b` writes into the scratch copy, not the harness. An unknown
        # variable leaves the directory where it was: the conservative reading.
        if len(words) == 1 and re.match(r"^[A-Za-z_]\w*=", words[0]):
            k, v = words[0].split("=", 1)
            v = expand(v, env)
            if v is not None:
                env[k] = v
        if len(words) >= 2 and words[0] in ("cd", "pushd"):
            d = expand(words[1], env)
            if d is not None:
                base = os.path.join(base, d)
                env["PWD"] = base
        CWD[0] = base
        # A pipe starts a new command for this purpose: `echo x | tee lefthook.yml`.
        for part in split_pipes(seg):
            # `env -C DIR cmd` and `sudo -D DIR cmd` run cmd in DIR.
            CWD[0] = _run_dir(base, command_words(split_words(part) or [])[3], env)
            for t, level in write_targets(part, not RUNS_QUOTED.search(seg)):
                t2 = expand(t, env)
                if harness_target(t2 if t2 is not None else t, level) or substitution_in_harness(t2 or t):
                    return True
            CWD[0] = base
            if _nested_write(part, base, env):
                return True
        for closer in closes:
            if groups:
                kind, saved_base, saved_env = groups.pop()
                if kind == "(" and closer == ")":
                    base, env = saved_base, saved_env
    return False


def harness_write(cmd):
    orig = CWD[0]
    BUDGET[0], OVER_BUDGET[0] = CANDIDATE_BUDGET, False
    GLOB_SEEN.clear()
    NESTED_SEEN.clear()
    try:
        return _harness_write(cmd)
    except OverBudget:
        OVER_BUDGET[0] = True
        return True
    finally:
        CWD[0] = orig


# ------------------------------------------------------------------ lefthook bypasses
#
# harness-security.md M3: none of these needed special knowledge, and the guard caught
# none of them. The user keeps them for themselves, outside a tool call; CI is the net.
# A redirection, which is not a value: `2>&1`, `>/dev/null`, `> /tmp/h`, `&>x`. In quotes
# (`'>x'`) the quotes stay behind, and so does a value.
REDIRECTION = re.compile(r"(?:\d*|&)(?:>>?|<|>\|)(?:&(?:\d+|-)|\s*[^\s;&|<>()'\"]+)")


def ungroup(words):
    """words without the `(` or `{` that opens a group in front of the command, and the `)` that
    ends its last word, as in `(<command> ...)`."""
    opened = False
    while words and (words[0] == "{" or words[0].startswith("(")):
        head = words[0].lstrip("({")
        words, opened = ([head] if head else []) + words[1:], True
    if opened and words:
        last = words[-1].rstrip(")")
        words = words[:-1] + ([last] if last else [])
    return words


GIT_CONFIG_UNSET = ("--unset", "--unset-all", "unset")
GIT_CONFIG_READ = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "--show-origin", "get", "list")
STDIN_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
# Interpreters that run their standard input as the program when given no program of their own:
# `... | lua -`, `... | tclsh`, `... | python3`. A pipe into one hides what runs behind a string
# no path check reads, exactly as a pipe into a shell does (Portal audit).
STDIN_INTERPRETERS = re.compile(r"^(?:python[\d.]*|perl|ruby|node|php|lua|luajit|tclsh)$")
AWKS = ("awk", "gawk", "mawk", "nawk")
AWK_SYSTEM = re.compile(r"\bsystem\s*\(")


def awk_runs_stdin(args):
    """True for an awk whose program is its input (`-f -`, `-f /dev/stdin`) or that hands each input
    line to a shell (`'{system($0)}'`). `awk '{print $1}'` and `awk -f prog.awk` read it as data.
    `print | "sh"` is the same and stays open (KNOWN_GAPS)."""
    return any(a == "-f" and args[i + 1:i + 2] in (["-"], ["/dev/stdin"]) or AWK_SYSTEM.search(a)
               for i, a in enumerate(args))


def reads_script_from_stdin(words):
    """True for a shell or interpreter that runs what is piped into it: `sh`, `bash -s`, `sh -e`, `bash -`,
    `lua -`, `python3`, `awk -f -`; not `sh -c '...'` (its body is an operand) and not `sh script.sh`,
    `python3 -m json.tool` or `perl -ne 'print'`."""
    if not words:
        return False
    name = os.path.basename(words[0])
    if name in AWKS:
        return awk_runs_stdin(words[1:])
    if name not in STDIN_SHELLS and not STDIN_INTERPRETERS.match(name):
        return False
    # Any operand is a script or a `-c` body; a shell's `-s` says to read stdin whatever the operands are.
    return (name in STDIN_SHELLS and "-s" in words[1:]) or all(a == "-" or a.startswith("-") for a in words[1:])


def piped_shell_inputs(seg):
    """The text a pipe in seg feeds to a shell or interpreter that runs it: `printf '...' | sh` gives
    `printf '...'`. A pipe into one hides what runs behind a string no path check reads (round 9b, item 9)."""
    stages = pipeline(group_marks(seg)[0])
    return ["|".join(stages[:k]) for k in range(1, len(stages))
            if reads_script_from_stdin(strip_prefix(split_words(stages[k]) or []))]


def names_harness(text):
    """True when a word of text is a harness path."""
    return any(harness_target(t) for t in re.findall(r"[^\s'\";&|<>()=]+", text))


def hookspath_set(cmd):
    """True when the command sets or unsets core.hooksPath, not when it reads it. Reading it is
    how a session checks the hooks are installed (`git config --get core.hooksPath` was
    blocked 17 times in the replay of recorded commands). Each command of a pipe is judged on
    its own, redirections dropped first: `git config core.hooksPath 2>&1 | head -1` read
    `2>&1` and then `head -1` as the value. A nested shell's body (`sh -c`, `eval`) is judged
    the same way; the old loop never looked inside one. git reads options only before the key, so
    a word after it is the value, however it starts (`-/x`, `--get`); a read mode counts only when
    it comes before the key. Under xargs a key with no value gets one from stdin."""
    low = cmd.lower()
    if re.search(r"-c\s*core\.hookspath\s*=|git_config_(?:key|parameters|count)", low):
        return True
    for seg in segments(cmd):
        if any("hookspath" in before.lower() for before in piped_shell_inputs(seg)):
            return True
        for stage in pipeline(seg):
            if "hookspath" not in stage.lower():
                continue
            words = split_words(REDIRECTION.sub(" ", stage))
            if words is None:
                return True
            _, words, wrappers, _ = command_words([w.lower() for w in ungroup(words)])
            bodies = nested_bodies(words)
            if bodies:
                if any(hookspath_set(a) for a in bodies):
                    return True
                continue
            if words and words[0] == "eval":
                words = words[1:]
            if not words or os.path.basename(words[0]) != "git" or "config" not in words:
                continue
            rest = words[words.index("config") + 1:]
            key = next((i for i, w in enumerate(rest) if w.endswith("core.hookspath")), None)
            if key is None:
                continue
            before, after = rest[:key], rest[key + 1:]
            if any(w in GIT_CONFIG_UNSET for w in before):
                return True
            if any(w in GIT_CONFIG_READ for w in before):
                continue
            if after or "xargs" in wrappers:
                return True
    return False


FIX_THE_HOOK = "Instead, fix what the hook reports, or ask the user to run it themselves"


SWITCH_OFF = re.compile(r"(?:0|false|off)\b")
ENV_DECLARERS = ("export", "declare", "typeset", "local", "readonly")
LOOSE_ASSIGNMENT = re.compile(r"\b(lefthook_bin|lefthook|husky)[\"']?\s*=\s*[\"']?(\w*)")
SUBSTITUTION_OPEN = re.compile(r"\$\(|[<>]\(|`|\)")


def command_assignments(text, depth=0):
    """(name, value) of each environment assignment the shell makes in text, lowercased: a leading
    NAME=value word of a command (before its command word, after any wrapper's own), `export`,
    `declare`, `typeset`, `local` and `readonly` with NAME=value, `env NAME=value cmd`, per command
    of a pipe or a `;`/`&&` list, and inside a nested shell, `eval` or `$(...)`. Quotes are the
    shell's: `'LEFTHOOK'=0` and `HUSKY="0"` are assignments. A word that only contains the text
    (`echo "LEFTHOOK_BIN=$LEFTHOOK_BIN"`, `grep 'HUSKY="0"' .`, `sed 's/LEFTHOOK_BIN=x/y/'`) is an
    argument, not an assignment: naming and reading stay allowed (FORGE_ALLOW 10). A command the
    shell would not parse falls back to the text, so an unbalanced quote is not a way past it."""
    found = []
    for seg in pieces(text):
        words = split_words(REDIRECTION.sub(" ", seg))
        if words is None:
            found += [(m.group(1), m.group(2)) for m in LOOSE_ASSIGNMENT.finditer(seg)]
            continue
        assigns, rest, _, _ = command_words([w.lower() for w in ungroup(words)])
        found += assigns
        if rest and os.path.basename(rest[0]) in ENV_DECLARERS:
            found += [tuple(w.split("=", 1)) for w in rest[1:] if ASSIGNMENT.match(w)]
        if depth >= 3:
            continue
        bodies = [] if not rest or os.path.basename(rest[0]) not in NESTING_SHELLS else (
            [" ".join(rest[1:])] if os.path.basename(rest[0]) == "eval"
            else [a for a in rest[1:] if not a.startswith("-")])
        bodies += [b for w in words if SUBSTITUTION_OPEN.search(w) for b in SUBSTITUTION_OPEN.split(w)[1:]]
        for body in bodies:
            found += command_assignments(body, depth + 1)
    return found


def hook_bypass(cmd):
    low = cmd.lower()
    # git accepts any unique prefix of a long option, so `--no-veri` is --no-verify
    # (break-it round, U44). `(?![\w-])` keeps `--no-verbose` and `--no-verify-signatures`.
    # A search pattern is text: `grep -n 'a|--no-verify' PLAN.md` runs no commit.
    if re.search(r"--no-v(?:e(?:r(?:i(?:f(?:y)?)?)?)?)?(?![\w-])", blank_grep_patterns(low)):
        return "--no-verify bypasses the pre-commit and pre-push gates. " + FIX_THE_HOOK
    assigns = command_assignments(low) if "lefthook" in low or "husky" in low else []
    if any(n == "lefthook" and SWITCH_OFF.match(v) for n, v in assigns):
        return "LEFTHOOK=0 disables the git hooks gate. " + FIX_THE_HOOK
    if any(n == "husky" and SWITCH_OFF.match(v) for n, v in assigns):
        return "HUSKY=0 disables the git hooks gate. " + FIX_THE_HOOK
    # lefthook's generated .git/hooks/pre-commit runs "$LEFTHOOK_BIN" when it is set, so any value skips
    # every hook (Portal audit). Setting it is refused; naming, reading and unsetting it are not.
    if any(n == "lefthook_bin" for n, v in assigns):
        return "LEFTHOOK_BIN=... replaces the program lefthook's git hooks run, so it skips the git hooks gate. " + FIX_THE_HOOK
    if "hookspath" in low and hookspath_set(cmd):
        return "overriding core.hooksPath bypasses the installed git hooks. " + FIX_THE_HOOK
    for seg in pieces(cmd):
        if commit_n(seg):
            return "git commit -n is --no-verify, it bypasses the pre-commit gate. " + FIX_THE_HOOK
    return None


def commit_n(seg):
    """True when seg runs `git commit` with -n in a flag cluster, directly or in a nested
    shell (`sh -c 'true; git commit -n'` passed until the nested-shell fix). Only the first stage of
    a pipeline is commit's own: the `-n` of `git commit -F m 2>&1 | tail -n 3` is tail's, and a
    commit later in a pipe is a piece of its own (pieces())."""
    words = strip_prefix(split_words(pipeline(seg)[0]) or [])
    bodies = nested_bodies(words)
    if bodies:
        return any(commit_n(p) for a in bodies for p in pieces(a))
    if len(words) < 2 or os.path.basename(words[0]) != "git":
        return False
    _, rest = git_subcommand(words[1:])
    if not rest or rest[0] != "commit":
        return False
    skip = False
    for a in rest[1:]:
        if skip:
            skip = False
            continue
        if a in ("-m", "-F", "-C", "-c", "-t", "--message", "--file", "--author", "--date"):
            skip = True
            continue
        if re.match(r"^-[a-zA-Z]+$", a) and "n" in a[1:]:
            return True
    return False


BACKLOG_SCRIPT = os.path.join("scripts", "backlog", "backlog.mjs")


def issue_create_refusal(pcmd):
    """A refusal when pcmd runs `gh issue create` in a project that has scripts/backlog/backlog.mjs
    (under PROJECT or the directory the call runs in): that script opens the issue and the backlog
    item together, and plain `gh issue create` leaves the two out of step. Read like commit_n: any
    wrapper prefix, `command gh`, nested shells. `-R/--repo` anywhere passes, it names another
    repository. A nudge, not a wall: `gh api` still creates an issue, and only Claude Code runs this guard."""
    if not any(os.path.isfile(os.path.join(d, BACKLOG_SCRIPT)) for d in (PROJECT, CWD[0])):
        return None
    for seg in pieces(pcmd):
        if _creates_issue(seg):
            return ("gh issue create is refused here: this project opens issues through its backlog script, "
                    "which creates the issue and the backlog item together. Instead run: "
                    'node scripts/backlog/backlog.mjs add "<title>" [--body-file FILE]')
    return None


def _creates_issue(seg):
    words = strip_prefix(split_words(pipeline(seg)[0]) or [])
    bodies = nested_bodies(words)
    if bodies:
        return any(_creates_issue(p) for a in bodies for p in pieces(a))
    if len(words) < 3 or os.path.basename(words[0]) != "gh" or words[1:3] != ["issue", "create"]:
        return False
    return not any(a in ("-R", "--repo") or a.startswith(("-R", "--repo=")) for a in words[3:])


# ------------------------------------------------------------------ per-project parameters
#
# `--project NAME` (the project's `command_guard` line) reads <forge>/config/guard/NAME.json
# on each call; a project with no file runs the core alone. secret_paths join the Bash dump
# check and the protected-file check; harness_paths join the paths a Bash call may not write
# (relative to the project root, or ~/...). Each entry carries its reason, which the next
# reader cannot derive. A file that does not parse, or carries an unknown key, refuses every
# call with its path in the message: a guard that silently drops its parameters looks
# exactly like one that applied them. docs/command-guard-design.md, "Parameters".
CONFIG_DIR = os.path.join(FORGE, "config", "guard")
CONFIG_KEYS = {"_doc", "secret_paths", "harness_paths"}
ENTRY_KEYS = {"secret_paths": ("pattern", "why"), "harness_paths": ("path", "why")}


def project_config(argv):
    """(secret patterns, harness paths) from the arguments; ValueError says what is wrong."""
    if not argv:
        return [], []
    if len(argv) != 2 or argv[0] != "--project":
        raise ValueError("unknown arguments %r; the only ones are --project NAME, or --consent alone" % argv)
    name = argv[1]
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", name):
        raise ValueError("%r is not a project name" % name)
    path = os.path.join(CONFIG_DIR, name + ".json")
    if not os.path.exists(path):
        return [], []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as e:
        raise ValueError("%s does not parse (%s)" % (path, e))
    if not isinstance(doc, dict):
        raise ValueError("%s is not a JSON object" % path)
    unknown = sorted(set(doc) - CONFIG_KEYS)
    if unknown:
        raise ValueError("%s has unknown key(s) %s; the keys are %s" % (path, unknown, sorted(CONFIG_KEYS)))
    out = {}
    for key, (field, _) in ENTRY_KEYS.items():
        entries = doc.get(key, [])
        if not isinstance(entries, list):
            raise ValueError("%s: %s is not a list" % (path, key))
        out[key] = []
        for e in entries:
            if (not isinstance(e, dict) or set(e) != set(ENTRY_KEYS[key])
                    or not all(isinstance(e[k], str) and e[k].strip() for k in e)):
                raise ValueError("%s: each %s entry is {%s} with non-empty strings, got %r"
                                 % (path, key, ", ".join('"%s"' % k for k in ENTRY_KEYS[key]), e))
            out[key].append(e[field])
    secrets = []
    for pat in out["secret_paths"]:
        # Case-insensitive: the command text and the file path are lowercased before matching.
        try:
            re.compile("(?i)" + pat)
        except re.error as e:
            raise ValueError("%s: secret_paths pattern %r is not a regex (%s)" % (path, pat, e))
        secrets.append("(?i)" + pat)
    harness = [os.path.realpath(HOME + h[1:] if h.startswith("~") else os.path.join(PROJECT, h))
               for h in out["harness_paths"]]
    return secrets, harness


# ------------------------------------------------------------------ the consent window
#
# `--consent` (the user-scope hook row, written when integrations.consent is on) runs only the consent
# rules, never the core: it loads <forge>/config/gateway.json and the `production` of the
# project the call runs in, validates both, and refuses EVERY call with CONSENT_ERROR when either is
# invalid, as `--project` does for a bad config/guard/NAME.json. It never decides to ask a human on its
# own authority from a half-read file. consent_config() and production_error() are the one definition of
# what is valid: forge's lib.project_error and `forge doctor` import them by path.
CONSENT_TOP_KEYS = ("_doc", "consent", "notify")  # notify is the notice gateway's: not looked at here
CONSENT_KEYS = ("adapter", "timeout_s", "rules")
CONSENT_RULE_KEYS = ("id", "match", "label", "risks")
CONSENT_MATCHES = ("production.branches", "production.commands")
PRODUCTION_KEYS = ("branches", "commands")


def _only_keys(where, obj, allowed):
    unknown = sorted(set(obj) - set(allowed))
    if unknown:
        raise ValueError("%s has unknown key(s) %s; the keys are %s" % (where, unknown, sorted(allowed)))


def _strings(where, items):
    if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
        raise ValueError("%s is not a list of non-empty strings" % where)


def production_error(value):
    """None when `value` is a valid project `production` ({"branches": [str], "commands": [str]}, both
    optional, only those keys, every string non-empty), else what is wrong."""
    try:
        if not isinstance(value, dict):
            raise ValueError('production is not an object {"branches": [...], "commands": [...]}')
        _only_keys("production", value, PRODUCTION_KEYS)
        for key in PRODUCTION_KEYS:
            if key in value:
                _strings("production.%s" % key, value[key])
    except ValueError as e:
        return str(e)
    return None


def consent_adapter(root, value):
    """The adapter's real path. Only "omarchy" (scripts/consent/omarchy) or a path that, once its links
    and `..` are resolved, lies inside <forge>/scripts/consent/ counts: Write and Edit do not pass through
    the Bash guard, so any other path would let `adapter: /usr/bin/true` switch the window off."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("consent.adapter is not a non-empty string")
    folder = os.path.realpath(os.path.join(root, "scripts", "consent"))
    real = os.path.realpath(os.path.join(root, "scripts", "consent", "omarchy") if value == "omarchy"
                            else os.path.join(root, value))
    if not real.startswith(folder + "/"):
        raise ValueError("consent.adapter outside scripts/consent: %r resolves to %s; use \"omarchy\" or a path "
                         "inside %s" % (value, real, folder))
    return real


def consent_config(forge_root):
    """The validated consent configuration of the forge at forge_root: {"adapter": real path, "timeout_s",
    "rules", "notify", "projects": [{"file", "project_path", "production"?}, ...]}. ValueError, with the
    file in the message, when config/gateway.json is missing, unreadable or invalid. The projects are only
    loaded: a project that does not parse is skipped, and its `production` is checked by production_error
    for the project that uses it."""
    root = os.path.realpath(forge_root)
    path = os.path.join(root, "config", "gateway.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as e:
        raise ValueError("%s cannot be read (%s)" % (path, e))
    try:
        if not isinstance(doc, dict):
            raise ValueError("it is not a JSON object")
        _only_keys("it", doc, CONSENT_TOP_KEYS)
        c = doc.get("consent")
        if not isinstance(c, dict):
            raise ValueError("\"consent\" is missing or not an object")
        _only_keys("consent", c, CONSENT_KEYS)
        missing = [k for k in CONSENT_KEYS if k not in c]
        if missing:
            raise ValueError("consent lacks %s" % missing)
        adapter = consent_adapter(root, c["adapter"])
        t = c["timeout_s"]
        if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
            raise ValueError("consent.timeout_s is not a positive integer: %r" % (t,))
        rules = c["rules"]
        if not isinstance(rules, list) or not rules:
            raise ValueError("consent.rules is not a non-empty list")
        seen = set()
        for i, r in enumerate(rules):
            where = "consent.rules[%d]" % i
            if not isinstance(r, dict):
                raise ValueError("%s is not an object" % where)
            _only_keys(where, r, CONSENT_RULE_KEYS)
            missing = [k for k in CONSENT_RULE_KEYS if k not in r]
            if missing:
                raise ValueError("%s lacks %s" % (where, missing))
            if not isinstance(r["id"], str) or not r["id"].strip() or r["id"] in seen:
                raise ValueError("%s.id is empty, not a string, or used by another rule: %r" % (where, r["id"]))
            seen.add(r["id"])
            if r["match"] not in CONSENT_MATCHES:
                raise ValueError("%s.match %r is not one of %s" % (where, r["match"], list(CONSENT_MATCHES)))
            if not isinstance(r["label"], str) or not r["label"].strip():
                raise ValueError("%s.label is not a non-empty string" % where)
            if not r["risks"]:
                raise ValueError("%s.risks is an empty list: the window must say what can go wrong" % where)
            _strings("%s.risks" % where, r["risks"])
    except ValueError as e:
        raise ValueError("%s: %s" % (path, e))
    projects = []
    for f in sorted(glob.glob(os.path.join(root, "config", "projects", "*.claude.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                prof = json.load(fh)
        except Exception:
            continue
        if isinstance(prof, dict) and isinstance(prof.get("project_path"), str) and prof["project_path"]:
            entry = {"file": f, "project_path": os.path.realpath(prof["project_path"])}
            if "production" in prof:
                entry["production"] = prof["production"]
            projects.append(entry)
    return {"adapter": adapter, "timeout_s": t, "rules": rules, "notify": doc.get("notify"), "projects": projects}


def consent_project(projects, cwd):
    """The project `cwd` is in: the one with the deepest project_path that contains it."""
    cwd = os.path.realpath(cwd)
    inside = [p for p in projects if cwd == p["project_path"] or cwd.startswith(p["project_path"].rstrip("/") + "/")]
    return max(inside, key=lambda p: len(p["project_path"])) if inside else None


# ------------------------------------------------------------------ what matches a consent rule (1.1 U1b)
#
# A Bash call matches when one of its commands is a `git push` to a production branch, or starts with an
# entry of the project's `production.commands`; an MCP call matches when the tool is named by an entry.
# The project of a command is the deepest project that holds the directory it runs in (the payload's cwd,
# moved by `cd`, `git -C`, `env -C`), or, for a worktree kept elsewhere, the project of its main checkout.
# A directory the guard cannot read (`cd $X`) is unknown, and an unknown directory fails closed: every
# project with a `production` is looked at. The commands come from the guard's own parsers (segments in
# both cuts, prefixes, nested shells); only the directory walk is new, because the write check's walk
# answers a different question. Nothing here opens a window: U1c does.
# Not read, by design or for want of a parser (each one is a way past the window; none is asserted): a git alias
# (`git config alias.p push`, then `git p origin main`: the cheap exit needs the word `push`), `--git-dir` and
# `--work-tree` (the directory is the cwd's), a script that pushes inside (name it in production.commands, 1.1
# section 8), and a Bash call whose text hides `push` behind a variable or a substitution.
CONSENT_SHELLS = ("bash", "sh", "zsh", "dash", "ksh", "su")  # shells that run the body of a `-c`
CONSENT_RUNNERS = ("bash", "sh", "zsh", "dash", "ksh", "source", ".")  # `bash X` runs X
CONSENT_DEPTH = 6  # nested shells read; a body deeper than this is refused as unreadable
CONSENT_DIRS = 16  # places a command may run in, before they are all "unknown"
UNREADABLE_REFSPEC = re.compile(r"[$`*?\[]")
GIT_CAP_S = 5
CONSENT_GIT = {"dead": False}  # a git call that timed out: the rest of this hook call do not wait for git again
CONSENT_RESOLVED = {}


def consent_git(d, *args):
    """The stdout of `git ARGS` run in d, or None when it fails, when d is unknown or missing, or when it
    takes more than GIT_CAP_S seconds. After one timeout git is not called again during this hook call."""
    if d is None or CONSENT_GIT["dead"]:
        return None
    try:
        proc = subprocess.Popen(["git"] + list(args), cwd=d, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True, start_new_session=True,
                                env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"))
    except (OSError, ValueError):
        return None
    try:
        out, _ = proc.communicate(timeout=GIT_CAP_S)
    except subprocess.TimeoutExpired:
        CONSENT_GIT["dead"] = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the group: a child of git would hold the pipe open
        except OSError:
            pass
        proc.kill()
        proc.communicate()
        return None
    return out.strip() if proc.returncode == 0 else None


def _consent_unique(dirs):
    out = list(dict.fromkeys(dirs))
    return out if len(out) <= CONSENT_DIRS else [None]


def _consent_dir(d, rel, env):
    """The directory a command is in after moving from d by rel (a cd argument, `git -C`, `env -C`);
    None when it cannot be read."""
    if not rel:
        return d
    x = expand(rel, env)
    if x is None or x == "-" or UNREADABLE_DIR.search(x):
        return None
    if os.path.isabs(x):
        return os.path.normpath(x)
    return os.path.normpath(os.path.join(d, x)) if d else None


def consent_bodies(words):
    """The command lines a shell in words runs: the argument of its `-c`, `eval`'s arguments joined, and
    the quoted lines nested_bodies finds."""
    name, out = os.path.basename(words[0]), []
    if name == "eval" and len(words) > 1:
        out.append(" ".join(words[1:]))
    if name in CONSENT_SHELLS:
        for i, a in enumerate(words[1:], 1):
            if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and i + 1 < len(words):
                out.append(words[i + 1])
                break
    return out + [b for b in nested_bodies(words) if b not in out]


def consent_commands(text, dirs, env=None, depth=0):
    """Every command `text` runs, as (its words with the prefixes stripped, the directories it may run in,
    the variables it sees); (None, dirs, env) stands for a nested body deeper than CONSENT_DEPTH. The
    directories follow `cd` as the shell does: after `cd X &&` the command is in X, and after `cd X ;` it
    may be in X or where it was, because a cd that fails changes nothing."""
    text = re.sub(r"\\\r?\n", " ", text)
    items, seen = [], set()
    blind = (SEGMENT_SPLIT.split(text), SEGMENT_SPLIT.findall(text))
    for (segs, seps), split_pipes in ((split_unquoted_seps(text, SEGMENT_SPLIT), pipeline), (blind, PIPE.split)):
        _consent_walk(segs, seps, split_pipes, dirs, env or {"HOME": HOME}, depth, items, seen)
    return items


def _consent_walk(segs, seps, split_pipes, dirs, env, depth, items, seen):
    dirs, env, groups = list(dirs), dict(env), []
    for i, seg in enumerate(segs):
        seg, opens, closes = group_marks(seg)
        groups += [(kind, list(dirs), dict(env)) for kind in opens]
        words = ungroup(split_words(seg) or [])
        prev, nxt = (seps[i - 1].strip() if i else ""), (seps[i].strip() if i < len(seps) else "")
        if len(dirs) == 1 and dirs[0]:
            env["PWD"] = dirs[0]
        else:
            env.pop("PWD", None)
        if len(words) == 1 and ASSIGNMENT.match(words[0]):
            k, v = words[0].split("=", 1)
            v = expand(v, env)
            if v is not None:
                env[k] = v
        elif words and words[0] in ("cd", "pushd"):
            args = [w for w in words[1:] if not w.startswith("-") or w == "-"]
            moved = [_consent_dir(d, args[0] if args else "~", env) for d in dirs]
            dirs = _consent_unique(moved if nxt == "&&" and prev != "||" else dirs + moved)
        else:
            for part in split_pipes(seg):
                _consent_part(part, dirs, env, depth, items, seen)
        for closer in closes:
            if groups:
                kind, saved_dirs, saved_env = groups.pop()
                if kind == "(" and closer == ")":
                    dirs, env = saved_dirs, saved_env


def _consent_part(part, dirs, env, depth, items, seen):
    assigns, words, _, chdir = command_words(ungroup(split_words(part) or []))
    if not words:
        return
    inner = dict(env)
    for k, v in assigns:
        v = expand(v, env)
        if v is not None:
            inner[k] = v
    where = _consent_unique([_consent_dir(d, chdir, inner) for d in dirs])
    key = (tuple(words), tuple(where))
    if key not in seen:
        seen.add(key)
        items.append((words, where, inner))
    for body in consent_bodies(words):
        if depth >= CONSENT_DEPTH:
            items.append((None, where, inner))
        else:
            items.extend(consent_commands(body, where, inner, depth + 1))


def _consent_entries(p):
    """The strings of a project's production.commands (a project whose production is not valid has none:
    the project that is used is checked by production_error)."""
    prod = p.get("production")
    if isinstance(prod, dict) and isinstance(prod.get("commands"), list):
        return [c for c in prod["commands"] if isinstance(c, str)]
    return []


def _consent_name(p):
    return os.path.basename(p["file"])[:-len(".claude.json")]


def _consent_resolve(cfg, d):
    """The projects with a `production` that a command run in d belongs to: the one that holds d, else the
    one of the main checkout of the worktree d is in; with d unknown, all of them. ValueError when one of
    them has an invalid production."""
    if d in CONSENT_RESOLVED:
        return CONSENT_RESOLVED[d]
    if d is None:
        found = [p for p in cfg["projects"] if "production" in p]
    else:
        p = consent_project(cfg["projects"], d)
        if p is None:
            common = consent_git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
            if common:
                p = consent_project(cfg["projects"], os.path.dirname(common.rstrip("/")))
        found = [p] if p else []
    for p in found:
        err = production_error(p["production"]) if "production" in p else None
        if err:
            raise ValueError("%s: %s" % (p["file"], err))
    CONSENT_RESOLVED[d] = [p for p in found if "production" in p]
    return CONSENT_RESOLVED[d]


def consent_push_args(args):
    """(remote or None, refspecs, flags) of the words after `git push`. The flags are the names of the
    options that change what a push does: dry-run, all (also --mirror and --branches), tags, delete, force."""
    flags, positional, i, only_positional, repo = set(), [], 0, False, None
    while i < len(args):
        a, i = args[i], i + 1
        if only_positional or not a.startswith("-") or a == "-":
            positional.append(a)
        elif a == "--":
            only_positional = True
        elif a.startswith("--"):
            name, eq, value = a.partition("=")
            if name in ("--all", "--branches", "--mirror"):
                flags.add("all")
                if name == "--mirror":
                    flags.add("mirror")
            elif name == "--tags":
                flags.add("tags")
            elif name == "--delete":
                flags.add("delete")
            elif name == "--dry-run":
                flags.add("dry-run")
            elif name == "--force" or name.startswith("--force-with-lease") or name == "--force-if-includes":
                flags.add("force")
            elif name in ("--repo", "--receive-pack", "--exec", "--push-option", "--recurse-submodules"):
                if not eq and i < len(args):
                    value, i = args[i], i + 1
                if name == "--repo":
                    repo = value
        else:
            for j, c in enumerate(a[1:], 1):
                if c == "f":
                    flags.add("force")
                elif c == "d":
                    flags.add("delete")
                elif c == "n":
                    flags.add("dry-run")
                elif c == "o":
                    i += 0 if a[j + 1:] or i >= len(args) else 1
                    break
    if repo is None and positional:
        repo, positional = positional[0], positional[1:]
    specs, k = [], 0
    while k < len(positional):
        if positional[k] == "tag" and k + 1 < len(positional):  # `tag NAME` is refs/tags/NAME
            flags.add("tags")
            k += 2
            continue
        specs.append(positional[k])
        k += 1
    return repo, specs, flags


def consent_push_line(d, remote, src, dst):
    """What pushing src to remote/dst changes: the short sha of src and the commits the remote lacks."""
    where, src = "%s/%s" % (remote, dst), (src[len("refs/heads/"):] if src.startswith("refs/heads/") else src)
    ref = src if re.match(r"^[A-Za-z0-9_][A-Za-z0-9_./@^~{}-]*$", src or "") else None
    pattern = "--remotes=%s" % remote if re.match(r"^[A-Za-z0-9_.-]+$", remote) else "--remotes"
    sha = consent_git(d, "rev-parse", "--verify", "--short", ref) if ref else None
    count = consent_git(d, "rev-list", "--count", ref, "--not", pattern) if ref else None
    if sha is None or count is None or not count.isdigit():
        return "push to %s: could not read what is pushed (git failed or took more than %d s); asking anyway" % (
            where, GIT_CAP_S)
    n = int(count)
    if n == 0:
        return "push to %s: %s (%s), nothing that %s lacks" % (where, src, sha, remote)
    subjects = (consent_git(d, "log", "--format=%s", "-n", "5", ref, "--not", pattern) or "").splitlines()
    text = "; ".join('"%s"' % s[:80] for s in subjects)
    more = " and %d more" % (n - len(subjects)) if n > len(subjects) else ""
    return "push to %s: %s (%s), %d commit(s) that %s lacks: %s%s" % (where, src, sha, n, remote, text, more)


def consent_push(args, d, branches):
    """(matches, changes) of `git push ARGS` run in directory d (None when unknown) against the production
    `branches`. Not a match: --dry-run, a push of tags only, a push to any other branch. A match that cannot
    be read to the end (a refspec with `$`, a backtick or a glob; git failing or taking more than GIT_CAP_S
    seconds) is still a match, and says so."""
    remote, specs, flags = consent_push_args(args)
    if "dry-run" in flags:
        return False, []
    if "all" in flags:
        rem = remote or "origin"
        changes = ["%s pushes every local branch to %s, production branches included (%s)" % (
            "--mirror" if "mirror" in flags else "--all", rem, ", ".join(branches))]
        if "mirror" in flags:
            changes.append("--mirror also deletes on %s every branch no local one matches, and overwrites the rest" % rem)
        for b in branches:
            if consent_git(d, "rev-parse", "--verify", "--quiet", "refs/heads/" + b) is not None:
                changes.append(consent_push_line(d, rem, b, b))
        return True, changes
    if not specs:
        if "tags" in flags:
            return False, []
        if consent_git(d, "config", "--get", "push.default") == "matching":
            return True, ["push.default is matching: every branch the remote also has is pushed, %s included" % (
                ", ".join(branches))]
        up = consent_git(d, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
        if up:
            rem = remote or (up.split("/", 1)[0] if "/" in up else "origin")
            dst = up[len(rem) + 1:] if up.startswith(rem + "/") else up.split("/", 1)[-1]
        else:
            cur = consent_git(d, "rev-parse", "--abbrev-ref", "HEAD")
            if cur is None:
                return True, ["could not read which branch a plain `git push` updates (git failed or took more "
                              "than %d s); asking anyway" % GIT_CAP_S]
            rem, dst = remote or "origin", cur
        if dst not in branches:
            return False, []
        changes = [consent_push_line(d, rem, "HEAD", dst)]
        return True, changes + (["--force: rewrites %s/%s" % (rem, dst)] if "force" in flags else [])
    changes, rem = [], remote or "origin"
    for s in specs:
        plus, body = s.startswith("+"), s.lstrip("+")
        if UNREADABLE_REFSPEC.search(body):
            changes.append("refspec %r cannot be read before it runs; treated as a push to production (%s)" % (
                s, ", ".join(branches)))
            continue
        src, _, dst = body.partition(":") if ":" in body else (body, "", body)
        if "delete" in flags and ":" not in body:
            src = ""
        dst = dst or src
        if ":" not in body and body in ("HEAD", "@") and "delete" not in flags:
            cur = consent_git(d, "rev-parse", "--abbrev-ref", "HEAD")
            if cur == "HEAD":
                continue  # detached: git refuses the push
            if cur is None:
                changes.append("could not read the current branch for %r (git failed or took more than %d s); "
                               "treated as a push to production (%s)" % (s, GIT_CAP_S, ", ".join(branches)))
                continue
            src, dst = "HEAD", cur
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        if dst not in branches:
            continue
        if "delete" in flags or not src:
            changes.append("delete %s/%s: the branch is removed from the remote" % (rem, dst))
        else:
            changes.append(consent_push_line(d, rem, src, dst))
            if plus or "force" in flags:
                changes.append("--force: rewrites %s/%s" % (rem, dst))
    return bool(changes), changes


def consent_program(words, d):
    """(the command words with `bash X`/`source X` taken as X and a leading ./ dropped, the absolute path of
    the program word when it is a path, else None) of a command run in d."""
    w = list(words)
    if os.path.basename(w[0]) in CONSENT_RUNNERS and len(w) > 1 and not w[1].startswith("-"):
        w = w[1:]
    while w[0].startswith("./"):
        w[0] = w[0][2:]
    path = w[0] if os.path.isabs(w[0]) else (os.path.join(d, w[0]) if d and "/" in w[0] else None)
    return w, (os.path.normpath(path) if path else None)


def consent_command_hit(words, d, project_path, entry):
    """True when the words of entry begin the command `words` run in d: `bash X` and `source X` count as
    X, `./X` as X, a path inside the project as the path from its root, and the path of a program
    elsewhere (/usr/bin/gh) as its name."""
    ew = split_words(entry) or entry.split()
    if not ew or not words:
        return False
    w, path = consent_program(words, d)
    names = {w[0]}
    if d and "/" not in w[0] and not os.path.isabs(w[0]):
        path = os.path.normpath(os.path.join(d, w[0]))  # `bash deploy.sh` from the directory that holds it
    if path:
        if project_path and (path == project_path or path.startswith(project_path.rstrip("/") + "/")):
            names.add(os.path.relpath(path, project_path))
        elif os.path.isabs(w[0]):
            names.add(os.path.basename(w[0]))
    efirst = ew[0]
    while efirst.startswith("./"):
        efirst = efirst[2:]
    return efirst in names and ew[1:] == w[1:len(ew)]


def consent_match(cfg, payload):
    """The consent rules a tool call matches: a list of {"rule": the rule of gateway.json, "project": the
    project's name, "kind": push | command | mcp, "changes": [what it changes, one line each]}; [] when it
    matches none. ValueError when the production of a project it needs is invalid. The cheap exit comes first:
    a Bash call with no `push` and no program of a production command in it, an MCP tool no project names."""
    tool, ti, projects = payload.get("tool_name"), payload.get("tool_input"), cfg["projects"]
    ti = ti if isinstance(ti, dict) else {}
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else PROJECT
    rule_of = {}
    for r in cfg["rules"]:
        rule_of.setdefault(r["match"], r)
    CONSENT_GIT["dead"] = False
    CONSENT_RESOLVED.clear()
    if not any("production" in p for p in projects) or not isinstance(tool, str):
        return []
    if tool.startswith("mcp__"):
        rule = rule_of.get("production.commands")
        named = [p for p in projects if tool in _consent_entries(p)]
        if not rule or not named:
            return []
        mine = consent_project(projects, cwd)
        prof = mine if mine in named else named[0]
        problem = production_error(prof["production"])
        if problem:
            raise ValueError("%s: %s" % (prof["file"], problem))
        changes = ["tool %s, project %s" % (tool, _consent_name(prof))]
        for key in ("sql", "query"):
            if isinstance(ti.get(key), str) and ti[key].strip():
                lines = ti[key].splitlines()
                changes += ["%s: %s" % (key, line) for line in lines[:10]]
                if len(lines) > 10:
                    changes.append("%s: ... and %d more lines" % (key, len(lines) - 10))
        return [{"rule": rule, "project": _consent_name(prof), "kind": "mcp", "changes": changes}]
    command = ti.get("command")
    if tool not in SHELL_TOOLS or not isinstance(command, str) or not command.strip():
        return []
    needles = ["push"]
    for p in projects:
        for e in _consent_entries(p):
            ew = [] if e.startswith("mcp__") else (split_words(e) or e.split())
            if ew:
                needles.append(os.path.basename(ew[0]))
    if not any(n in t for n in needles for t in (command, re.sub(r"['\"\\]", "", command))):
        return []
    push_rule, cmd_rule = rule_of.get("production.branches"), rule_of.get("production.commands")
    matches, seen = [], set()

    def add(rule, project, kind, changes):
        key = (kind, rule["id"], project, tuple(changes))
        if key not in seen:
            seen.add(key)
            matches.append({"rule": rule, "project": project, "kind": kind, "changes": changes})

    for words, dirs, env in consent_commands(strip_prose(command), [os.path.realpath(cwd)]):
        for d in dirs:
            profs = _consent_resolve(cfg, d)
            if words is None:
                rule = cmd_rule or push_rule
                if profs and rule:
                    add(rule, "+".join(_consent_name(p) for p in profs), "command",
                        ["the command nests shells more than %d deep, so it cannot be read; asking" % CONSENT_DEPTH])
                continue
            if os.path.basename(words[0]) == "git" and push_rule:
                args = []
                for a in words[1:]:
                    e = expand(a, env) if a.startswith("~") or "$" in a else a
                    args.append(a if e is None else e)  # a variable the guard cannot read stays `$X`: unreadable
                where, rest = git_subcommand(args)
                if rest and rest[0] == "push":
                    wd = _consent_dir(d, where, env)
                    pprofs = _consent_resolve(cfg, wd)
                    branches = sorted({b for p in pprofs for b in p["production"].get("branches", [])})
                    if branches:
                        hit, changes = consent_push(rest[1:], wd, branches)
                        if hit:
                            add(push_rule, "+".join(_consent_name(p) for p in pprofs), "push", changes)
            if cmd_rule:
                # A script named by its absolute path belongs to the project that holds it, wherever it runs from.
                script = consent_program(words, d)[1]
                holders = _consent_resolve(cfg, os.path.dirname(script)) if script else []
                for p in profs + [h for h in holders if h not in profs]:
                    for entry in _consent_entries(p):
                        if not entry.startswith("mcp__") and consent_command_hit(words, d, p["project_path"], entry):
                            add(cmd_rule, _consent_name(p), "command",
                                ["the command begins with `%s`, a production command of project %s" % (
                                    entry, _consent_name(p))])
    return matches


def consent_error(why):
    """Refuses the call: stderr starts with CONSENT_ERROR, on one line, with the way back."""
    sys.stderr.write("CONSENT_ERROR: %s. Every call is refused until it is fixed; instead of retrying or going "
                     "around it, tell the user what you wanted to run. Fix: edit that file in forge (the Edit "
                     "tool is free). To switch the window off: set integrations.consent to false in "
                     "config/forge.json and run `forge sync --apply`, which removes the hook row.\n" % why)
    sys.exit(2)


def consent_main():
    try:
        cfg = consent_config(FORGE)
    except ValueError as e:
        consent_error(str(e))
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    prof = consent_project(cfg["projects"], cwd if isinstance(cwd, str) and cwd else PROJECT)
    if prof and "production" in prof:
        err = production_error(prof["production"])
        if err:
            consent_error("%s: %s" % (prof["file"], err))
    try:
        matches = consent_match(cfg, payload) if isinstance(payload, dict) else []
    except ValueError as e:
        consent_error(str(e))
    except Exception as e:  # a parser that fails on a call must not wave it through: onFailure would block it anyway
        consent_error("the consent rules failed on this call (%s: %s)" % (type(e).__name__, e))
    if matches:
        consent_decide(cfg, payload, matches)


# ------------------------------------------------------------------ the window itself (1.1 U1c)
# A call that matches a rule is asked about: FORGE_CONSENT=unattended blocks it with no window; otherwise
# the request is written, the adapter runs with a cap of consent.timeout_s and only its exit 0 lets the call
# through. Every decision, and every failure to get one, is one line of consent.log and one stderr line that
# says not to retry or go around it. The adapter is the only thing that talks to a person.
CONSENT_COMMAND_LOG = 200  # characters of the command in the log line
CONSENT_ARGS_CAP = 2000  # characters of an MCP tool's arguments in the request
CONSENT_TELL = "Do not retry it or work around it; tell the user what you wanted to run: %s"


def _one_line(text, cap=None):
    text = re.sub(r"\s+", " ", text)
    return text if cap is None else text[:cap]


def consent_request(payload, matches):
    """The request of section 4: {project, cwd, session_id, command, what, changes, risks, requested_at}."""
    tool, ti = payload.get("tool_name"), payload.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    uniq = lambda seq: list(dict.fromkeys(seq))
    what = " + ".join(uniq(m["rule"]["label"] for m in matches))
    if tool.startswith("mcp__"):
        command = "%s %s" % (tool, json.dumps(ti, ensure_ascii=False, default=str)[:CONSENT_ARGS_CAP])
    else:
        command = ti["command"]
        if isinstance(ti.get("description"), str) and ti["description"].strip():
            what += ": " + ti["description"].strip()
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return {"project": " + ".join(uniq(m["project"] for m in matches)),
            "cwd": cwd if isinstance(cwd, str) and cwd else PROJECT,
            "session_id": sid if isinstance(sid, str) else "",
            "command": command, "what": what,
            "changes": uniq(c for m in matches for c in m["changes"]),
            "risks": uniq(r for m in matches for r in m["rule"]["risks"]),
            "requested_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def consent_log(decision, digest, request, rule_ids):
    """One TSV line: date, decision, sha256[:12] of the request, project, rule ids, command[:200]. Returns None,
    or the reason it could not be written."""
    base = os.environ.get("XDG_STATE_HOME")
    base = base if base and os.path.isabs(base) else os.path.join(HOME, ".local", "state")
    fields = [request["requested_at"], decision, digest, request["project"], rule_ids]
    line = "\t".join([_one_line(f) for f in fields] + [_one_line(request["command"], CONSENT_COMMAND_LOG)]) + "\n"
    try:
        os.makedirs(os.path.join(base, "forge"), exist_ok=True)
        fd = os.open(os.path.join(base, "forge", "consent.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        return "%s: %s" % (type(e).__name__, e)
    return None


def consent_ask(adapter, path, timeout_s, errpath):
    """Runs the adapter with the request's path as $1 and returns (answer, reason). Its exit says: 0 approved, 1
    declined, 4 timeout (nobody answered), anything else error, with the first line of its stderr (kept in
    errpath, 200 characters) as the reason. It may take no more than timeout_s: past that it and everything it
    started are killed and the answer is timeout. OSError when it cannot start."""
    with open(errpath, "wb") as errfile:
        proc = subprocess.Popen([adapter, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=errfile, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
            return "timeout", ""
    with open(errpath, "rb") as fh:
        reason = _one_line(fh.read(4096).decode("utf-8", "replace").strip().split("\n")[0], CONSENT_COMMAND_LOG)
    return {0: "approved", 1: "declined", 4: "timeout"}.get(code, "error"), (
        "the adapter exited %s: %s" % (code, reason or "it gave no reason on stderr"))


def consent_decide(cfg, payload, matches):
    request = consent_request(payload, matches)
    text = json.dumps(request, ensure_ascii=False, indent=2) + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    rule_ids = "+".join(dict.fromkeys(m["rule"]["id"] for m in matches))

    def finish(decision, prefix=None, why=""):
        failed = consent_log(decision, digest, request, rule_ids)
        if prefix:
            sys.stderr.write("%s %s. %s\n" % (prefix, why, CONSENT_TELL % _one_line(request["command"], CONSENT_COMMAND_LOG)))
        if failed:  # the answer stands: the user said it, and a full disk is not a reason to overrule them
            sys.stderr.write("consent.log could not be written (%s)\n" % failed)
        if prefix:
            sys.exit(2)

    if os.environ.get("FORGE_CONSENT") == "unattended":
        finish("unattended", "CONSENT_UNATTENDED:", "%s needs the user's approval and nobody is here to give it" % request["what"])
    adapter, runtime = cfg["adapter"], os.environ.get("XDG_RUNTIME_DIR")
    if not (os.path.isfile(adapter) and os.access(adapter, os.X_OK)):
        finish("error", "CONSENT_ERROR:", "the adapter %s does not exist or is not executable; fix consent.adapter in "
               "config/gateway.json" % adapter)
    if not runtime or not os.path.isabs(runtime) or not os.path.isdir(runtime):
        finish("error", "CONSENT_ERROR:", "XDG_RUNTIME_DIR is not set to a directory (%r), so the request has nowhere "
               "private to go" % runtime)
    folder = answer = reason = None
    try:
        folder = tempfile.mkdtemp(prefix="forge-consent-", dir=runtime)  # mode 700
        path = os.path.join(folder, "request.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        answer, reason = consent_ask(adapter, path, cfg["timeout_s"], os.path.join(folder, "stderr"))
    except OSError as e:
        finish("error", "CONSENT_ERROR:", "the window could not be opened (%s: %s)" % (type(e).__name__, e))
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
    if answer == "timeout":
        finish("timeout", "CONSENT_TIMEOUT:", "no answer within %d s to %s" % (cfg["timeout_s"], request["what"]))
    if answer == "declined":
        finish("declined", "CONSENT_DECLINED:", "the user did not approve %s" % request["what"])
    if answer == "error":
        finish("error", "CONSENT_ERROR:", "the window could not ask: %s" % reason)
    finish("approved")


SHELL_TOOLS = {"Bash", "run_shell_command", "shell"}
FILE_TOOLS = {"Write", "Edit", "Read", "MultiEdit", "write_file", "replace", "read_file"}


def deny(reason):
    sys.stderr.write("guard_tool_use: BLOCKED - %s\n" % reason)
    sys.exit(2)


def log_alert(severity, reason, detail):
    from datetime import datetime
    alert = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "severity": severity, "source": "guard", "reason": reason, "detail": detail,
    }
    # Every step of logging is inside the try: a log dir that cannot be made (an agent can
    # replace the logs dir with a plain file) raised here, the guard exited 1, and exit 1 is
    # not a block (break-it round, U11). The suite overrides the dir so its test artefacts
    # stay out of the real alert log.
    try:
        log_dir = os.environ.get("FORGE_GUARD_LOG_DIR") or os.path.join(ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "alerts.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(alert, separators=(",", ":")) + "\n")
    except Exception:
        pass


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if list(args) == ["--consent"]:
        return consent_main()
    try:
        secrets, PROJECT_HARNESS[:] = project_config(args)
    except ValueError as e:
        deny("guard config: %s. Every call is refused until it is fixed; instead of retrying, "
             "fix that file in forge or ask the user." % e)
    raw = sys.stdin.read()
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    tool = payload.get("tool_name")
    ti = payload.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    # A list or a dict raised TypeError in the set lookups below, and a crash exits 1, which
    # does not block either (Codex).
    if not tool or not isinstance(tool, str):
        return
    if isinstance(payload.get("cwd"), str) and payload["cwd"]:
        CWD[0] = payload["cwd"]

    # 1. Shell commands
    if tool in SHELL_TOOLS:
        cmd = str(ti.get("command") or "")
        if cmd:
            low = cmd.lower()
            pcmd = strip_prose(cmd)
            for pat, reason in DANGEROUS_SHELL:
                if re.search(pat, low):
                    if (reason.startswith("base64 decode") and not PIPE_TO_SHELL.search(blank_grep_patterns(low))
                            and not any(piped_shell_inputs(seg) for seg in segments(low))):
                        continue
                    deny(reason)
            for d in OOB_DOMAINS:
                if re.search(d, low):
                    deny("out-of-band exfiltration domain matched (%s). Instead, send nothing "
                         "there; ask the user if a collector is really needed" % d)
            if harness_write(pcmd):
                if OVER_BUDGET[0]:
                    deny("this command names more glob or brace alternatives than the guard can check against "
                         "the harness paths (%d), so it is refused as if it wrote one. Instead, name "
                         "the paths, or split the glob or the braces over several commands" % CANDIDATE_BUDGET)
                deny("shell write to a protected harness path (hooks, skills, agents, "
                     "settings.json, lefthook or husky config, git hooks, forge's guard and "
                     "its config, or the directories that hold them). Instead, edit harness files "
                     "with the Edit or Write tool, so the change is a reviewable diff in the "
                     "transcript. Deleting or renaming one (rm, mv, git rm, git mv) is "
                     "the user's to run: ask them.")
            reason = hook_bypass(pcmd)
            if reason:
                deny(reason)
            reason = issue_create_refusal(pcmd)
            if reason:
                deny(reason)
            if KEYRING_DUMP.search(low) and not REDIRECT_TO_FILE.search(cmd):
                log_alert("critical", "keyring_dump_blocked", "cmd=%s" % cmd[:200])
                deny(
                    "this would print a credential from the system keyring into the "
                    "transcript. The keyring is not a file, so no path check can catch it. "
                    "Instead, redirect it straight into a file the rotation tool reads "
                    "(secret-tool lookup ... > \"$T\"), and never into stdout."
                )
            # What the command keeps out (`--exclude='.env*'`, `':!.mcp.json'`) names no store it reads.
            scmd = blank_exclusions(pcmd)
            plow = scmd.lower()
            resolved = cd_resolved(scmd, SECRET_FILES + secrets).lower()
            # The command as the shell reads it after brace expansion, for the names it builds.
            BUDGET[0] = CANDIDATE_BUDGET
            try:
                braced = brace_text(scmd)
            except OverBudget:
                deny("this command names more brace alternatives than the guard can check against the "
                     "credential stores (%d), so it is refused as if it read one. Instead, name the "
                     "paths, or split the braces over several commands" % CANDIDATE_BUDGET)
            texts = [plow, resolved]
            if braced != scmd:
                texts += [braced.lower(), cd_resolved(braced, SECRET_FILES + secrets).lower()]
            texts = list(dict.fromkeys(texts))
            for pat in SECRET_FILES + secrets:
                if any(secret_dump(pat, t) for t in texts):
                    log_alert("critical", "secret_dump_blocked", "cmd=%s" % cmd[:200])
                    deny(
                        "this would print a credential store into the transcript "
                        "(matched %s). Transcripts are captured into long-term memory, "
                        "and a failed redaction is indistinguishable from a working one. "
                        "No interpreter or pipeline is an exception: a pattern check "
                        "cannot tell 'read one field' from 'print the whole file'. Instead, use "
                        "ls / stat / git check-ignore to confirm the file exists and is "
                        "ignored, or ask the user to read the value themselves.%s" % (pat, HINTS.get(pat, ""))
                    )

    # 2. Protected files. Grep takes a `path`, not a `file_path`; for Grep the native Read
    # deny rules are the primary control and this is the extra layer.
    if tool in FILE_TOOLS or tool == "Grep":
        path = str(ti.get("path" if tool == "Grep" else "file_path") or "")
        if path:
            p = path.lower().replace("\\", "/")
            for pat in PROTECTED_FILES + secrets:
                if re.search(pat, p):
                    deny("protected file or directory: %s. Instead, check it with ls or stat in "
                         "Bash, or ask the user to read or change it themselves" % path)


if __name__ == "__main__":
    main()
