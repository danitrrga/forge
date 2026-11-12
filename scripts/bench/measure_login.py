"""The login of a measurement session (scripts/bench/auto_mode.py, scripts/bench/skill_bench.py).

A session runs on the long-lived token of `claude setup-token`, kept in the secret store under FORGE_MEASURE_OAUTH_TOKEN and handed to
the child as CLAUDE_CODE_OAUTH_TOKEN. It never shares the machine's `.credentials.json`: Claude Code rewrites that file by temp file plus
rename, which replaces a symlink with a regular file, so a refresh in the throwaway config dir left the rotated refresh token there and
logged the real login out for every session on the machine. The token is static: nothing rotates, nothing is written.

Lives next to its two callers, so each reaches it as a sibling import with no path setup and no new dependency. The store is
`config/secrets.json` of the checkout, the file every generator resolves its `${VAR}` from; FORGE_SECRETS_FILE names another file (a
toy store in tests) and a run says so on stderr. It is read here, not with forge's `lib.read_json`, because that reader turns every
failure into an empty store and the error must say which one it was.

What is guaranteed and what is not. The harness never prints the value, never logs it, never writes it to a run file of its own
(run.json, cells.tsv, result.json) and never puts it on a command line. The agent under test is another matter: the child's
environment holds the token, so an agent that runs `env` puts it into its own output. Every file a session produces that the run keeps
(the stream, the stderr file, the hook log, the session transcripts, the working copy, the config dir) is therefore scanned after the
session and at the end of the run, and the exact value is replaced by PLACEHOLDER (`redact_tree`, also inside `.gz` files; the form
escaped for JSON too). NOT covered: a file the agent writes outside the run, a compressed file other than `.gz`, git objects, and the
token sent over the network. A run directory is otherwise as private as the store: do not share one without looking.
"""
import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEY = "FORGE_MEASURE_OAUTH_TOKEN"
STORE_ENV = "FORGE_SECRETS_FILE"
PLACEHOLDER = "[REDACTED: measurement token]"
# Removed from the child's environment, the token variable last set from the store. Each group changes which credential or endpoint the
# session would use, or exposes a login that is not the measurement one.
DROPPED = (
    # the three credentials that rank above or beside the token in Claude Code's authentication precedence ("Authentication precedence")
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    # cloud-provider credentials rank first "when CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_VERTEX, or CLAUDE_CODE_USE_FOUNDRY is set":
    # one of them in the owner's shell would turn a token run into a provider run
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
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
    except (UnicodeDecodeError, ValueError):
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
    for i, ch in enumerate(val):
        if ch.isspace() or not ch.isprintable():   # a control character, a lone surrogate or an inner space cannot be in a token
            _fail("the value of %s has a character that cannot be in a token (control, space or surrogate) at position %d" % (KEY, i), path)
    return val


def child_env(parent=None, secrets_file=None):
    """A copy of `parent` (default os.environ) for a measurement session: CLAUDE_CODE_OAUTH_TOKEN from the store, everything in DROPPED
    removed first, nothing else changed. LoginError when the store has no token (fail closed)."""
    tok = token(secrets_file)
    env = {k: v for k, v in (os.environ if parent is None else parent).items() if k not in DROPPED}
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
    """The byte strings that stand for the token in a file: as it is, and as JSON writes it when that differs."""
    out = [tok.encode("utf-8")]
    esc = json.dumps(tok)[1:-1].encode("utf-8")
    return out + ([esc] if esc != out[0] else [])


def redact_text(text, tok):
    """`text` with every occurrence of the token replaced by PLACEHOLDER (None and "" come back as ""). A no-op without a token."""
    text = text or ""
    if not tok:
        return text
    for f in _forms(tok):
        text = text.replace(f.decode("utf-8"), PLACEHOLDER)
    return text


def _swap(data, tok):
    for f in _forms(tok):
        data = data.replace(f, PLACEHOLDER.encode("utf-8"))
    return data


def redact_tree(root, tok):
    """Replaces the token by PLACEHOLDER in every regular file under `root` (links not followed, `.git` skipped), `.gz` files through
    their decompressed bytes. Returns the number of files changed. A file that cannot be read is named on stderr, never skipped silently."""
    changed, unreadable = 0, []
    if not tok or not os.path.isdir(root):
        return 0
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            p = os.path.join(r, f)
            if os.path.islink(p):
                continue
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
                if f.endswith(".gz"):
                    try:
                        raw = gzip.decompress(data)
                    except (OSError, EOFError):   # not gzip after all: scanned as it is below
                        raw = None
                    if raw is not None:
                        new = _swap(raw, tok)
                        if new != raw:
                            with open(p, "r+b") as fh:
                                fh.write(gzip.compress(new))
                                fh.truncate()
                            changed += 1
                        continue
                new = _swap(data, tok)
                if new != data:
                    with open(p, "r+b") as fh:
                        fh.write(new)
                        fh.truncate()
                    changed += 1
            except OSError:
                unreadable.append(p)
    if unreadable:
        print("measure_login: %d file(s) under %s could not be scanned for the token, e.g. %s" % (len(unreadable), root, unreadable[0]),
              file=sys.stderr)
    return changed
