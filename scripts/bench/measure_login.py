"""The login of a measurement session (scripts/bench/auto_mode.py, scripts/bench/skill_bench.py).

A session runs on the long-lived token of `claude setup-token`, kept in the secret store under FORGE_MEASURE_OAUTH_TOKEN and handed to
the child as CLAUDE_CODE_OAUTH_TOKEN. It never shares the machine's `.credentials.json`: Claude Code rewrites that file by temp file plus
rename, which replaces a symlink with a regular file, so a refresh in the throwaway config dir left the rotated refresh token there and
logged the real login out for every session on the machine. The token is static: nothing rotates, nothing is written.

Lives next to its two callers, so each reaches it as a sibling import with no path setup and no new dependency. The store is
`config/secrets.json` of the checkout, the file every generator resolves its `${VAR}` from; FORGE_SECRETS_FILE names another file (a
toy store in tests) and a run says so on stderr. It is read here, not with forge's `lib.read_json`, because that reader turns every
failure into an empty store and the error must say which one it was.

What the harness does with the value. It never prints it, logs it, writes it to a result file of its own (run.json, result.json,
cells.tsv) or puts it on a command line, and the text it stores from a session (stream, stderr, hook log, transcripts) is written as a new
file through `redact_text` / `write_redacted`, the value replaced by PLACEHOLDER; it never opens, rewrites or decompresses a file the
agent produced. The limit: the measured agent runs with the token in its environment, so a file it writes into its work directory can
hold it, and the run keeps those files as they are. Treat a run directory as private and do not share one without checking it.
"""
import json
import os
import stat
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEY = "FORGE_MEASURE_OAUTH_TOKEN"
STORE_ENV = "FORGE_SECRETS_FILE"
PLACEHOLDER = "[REDACTED: measurement token]"
MIN_LEN, MAX_LEN = 20, 4096
# Removed from the child's environment, the token variable last set from the store. Each group changes which credential or endpoint the
# session would use, or exposes a login that is not the measurement one.
DROPPED = (
    # the parent's own credentials: the first two outrank the token in Claude Code's authentication precedence, the third is replaced
    # by the store's value
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    # cloud-provider credentials rank first "when CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_VERTEX, or CLAUDE_CODE_USE_FOUNDRY is set":
    # one of them in the owner's shell would turn a token run into a provider run; MANTLE and ANTHROPIC_AWS are provider switches of the
    # same env-vars page (whether they outrank the token is not documented, they change the endpoint)
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    # an endpoint of the owner's shell would receive the token
    "ANTHROPIC_BASE_URL",
    # CLAUDE_CODE_SIMPLE is bare mode without the flag: "OAuth tokens and keychain credentials are not read" (env-vars page)
    "CLAUDE_CODE_SIMPLE",
    # the owner's refresh token and its scopes: not part of the session's authentication, but the agent's own shell would see them, and a
    # spent refresh token is the failure this module exists to avoid
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES",
)


class LoginError(Exception):
    """Why no session may start; the message is one line and is what the script exits with."""


def store_path():
    return os.environ.get(STORE_ENV) or os.path.join(ROOT, "config", "secrets.json")


def _fail(why, path):
    raise LoginError("no measurement login: %s (secret store %s). Run `claude setup-token` in a terminal and store the token under the key "
                     "%s in that store. No session was started." % (why, path, KEY))


def token(secrets_file=None):
    """The measurement token from the store; LoginError, with the cause and the store path, when there is no usable one. Says on stderr
    when FORGE_SECRETS_FILE redirected the store."""
    redirected = secrets_file is None and os.environ.get(STORE_ENV)
    path = secrets_file or store_path()
    if redirected:
        print("measure_login: the secret store is redirected by %s to %s" % (STORE_ENV, path), file=sys.stderr)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        _fail("the store file does not exist", path)
    except IsADirectoryError:
        _fail("the store path is a directory", path)
    except OSError as e:
        _fail("the store cannot be read (%s)" % (e.strerror or type(e).__name__), path)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):   # the last: a document nested deeper than the parser allows
        _fail("the store is not valid JSON", path)
    if not isinstance(doc, dict):
        _fail("the store is JSON but not an object", path)
    if KEY not in doc:
        _fail("the key %s is not in the store" % KEY, path)
    val = doc[KEY]
    if not isinstance(val, str):
        _fail("the value of %s is not a string" % KEY, path)
    val = val.strip()
    if not val:
        _fail("the value of %s is empty" % KEY, path)
    # a plausible shape and no more (no vendor prefix): too short a value would also match inside the run's own files, too long a one
    # cannot be passed on a command's environment
    if not (MIN_LEN <= len(val) <= MAX_LEN and val.isascii() and all(33 <= ord(ch) <= 126 for ch in val)):
        _fail("the value of %s is not a plausible token (printable ASCII without spaces, %d to %d characters, this one has %d)"
              % (KEY, MIN_LEN, MAX_LEN, len(val)), path)
    return val


def child_env(parent=None, secrets_file=None):
    """A copy of `parent` (default os.environ) for a measurement session: CLAUDE_CODE_OAUTH_TOKEN from the store, everything in DROPPED
    removed first, nothing else changed. LoginError when the store has no token (fail closed)."""
    tok = token(secrets_file)
    src = os.environ if parent is None else parent
    gone = sorted(k for k in DROPPED if k in src)
    if gone:   # names only: an owner whose setup needs one of them must not get a run on the default endpoint without a word
        print("measure_login: not passed to the session (set in this environment): %s" % ", ".join(gone), file=sys.stderr)
    env = {k: v for k, v in src.items() if k not in DROPPED}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    return env


def refuse_bare(cmd):
    """`--bare` does not read CLAUDE_CODE_OAUTH_TOKEN, so a bare session would run without a login: refused in front of any session."""
    if "--bare" in cmd:
        raise LoginError("--bare is refused: bare mode does not read CLAUDE_CODE_OAUTH_TOKEN, so the measurement login would not apply.")


def clean_config_dir(d):
    """Removes a `.credentials.json` (link or file) an earlier run left in the throwaway dir; a link's target is never touched. A stale
    one there can shadow the token or be refreshed by a daemon the session spawns. LoginError when it cannot be removed (a directory,
    no permission): no session starts over a login file that is still there."""
    p = os.path.join(d, ".credentials.json")
    try:
        os.remove(p)
    except FileNotFoundError:   # none there, or another worker of the same run removed it first
        pass
    except OSError as e:
        raise LoginError("cannot remove %s (%s): a login file is left in the throwaway config dir. No session was started."
                         % (p, e.strerror or type(e).__name__))


def _forms(tok):
    """The byte strings that stand for the token in text: as it is, and as JSON writes it when that differs (a `"` or `\\` in the value)."""
    out = [tok.encode("utf-8")]
    esc = json.dumps(tok)[1:-1].encode("utf-8")
    return out + ([esc] if esc != out[0] else [])


def redact_bytes(data, tok):
    """`data` with every occurrence of the token replaced by PLACEHOLDER. A no-op without a token."""
    for f in (_forms(tok) if tok else ()):
        data = data.replace(f, PLACEHOLDER.encode("utf-8"))
    return data


def redact_text(text, tok):
    """`text` with the token replaced by PLACEHOLDER (None comes back as ""). A no-op without a token."""
    return redact_bytes((text or "").encode("utf-8", "surrogateescape"), tok).decode("utf-8", "surrogateescape")


def write_atomic(path, data):
    """Writes `data` (bytes) as a new file: to a temp name in the same directory, then renamed over `path`. Never an in-place edit; if
    anything fails, or the process dies before the rename, nothing is under `path` that was not there before, and the temp file is
    removed when the process lives to do it."""
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_redacted(path, text, tok):
    """Stores `text` (what a session printed) at `path`, the token replaced, as a new file (write_atomic)."""
    write_atomic(path, redact_text(text, tok).encode("utf-8", "surrogateescape"))


def copy_redacted(src, dst, tok):
    """Stores the regular file `src` (text the harness keeps: a transcript, the hook log) at `dst` as a new file with the token replaced.
    A link or a special file is not opened: LoginError. A file that cannot be copied leaves nothing under `dst`."""
    try:
        if not stat.S_ISREG(os.lstat(src).st_mode):
            raise LoginError("cannot store %s: not a regular file" % src)
        with open(src, "rb") as fh:
            data = fh.read()
        write_atomic(dst, redact_bytes(data, tok))
    except OSError as e:
        raise LoginError("cannot store %s as %s: %s" % (src, dst, e.strerror or type(e).__name__))
