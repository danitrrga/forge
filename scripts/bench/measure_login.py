"""The login of a measurement session (scripts/bench/auto_mode.py, scripts/bench/skill_bench.py).

A session runs on the long-lived token of `claude setup-token`, kept in the secret store under FORGE_MEASURE_OAUTH_TOKEN and handed to
the child as CLAUDE_CODE_OAUTH_TOKEN. It never shares the machine's `.credentials.json`: Claude Code rewrites that file by temp file plus
rename, which replaces a symlink with a regular file, so a refresh in the throwaway config dir left the rotated refresh token there
and killed the real login for every session on the machine (Linear DTC-43). The token is static: nothing rotates, nothing is written.

Lives next to its two callers, so each reaches it as a sibling import with no path setup and no new dependency. The store is read with
forge's own reader (`lib.read_json`) from `config/secrets.json`, the file every generator resolves its `${VAR}` from; FORGE_SECRETS_FILE
names another file (the tests' toy store). The value is never printed, logged, written to a run file or put on a command line.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from forge import lib  # noqa: E402

KEY = "FORGE_MEASURE_OAUTH_TOKEN"
STORE_ENV = "FORGE_SECRETS_FILE"
DROPPED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


class LoginError(Exception):
    """Why no session may start; the message is one line and is what the script exits with."""


def store_path():
    return os.environ.get(STORE_ENV) or os.path.join(lib.ROOT, "config", "secrets.json")


def token(secrets_file=None):
    """The measurement token from the store; LoginError when the store has no usable value for KEY."""
    doc = lib.read_json(secrets_file or store_path(), quiet=True)
    val = doc.get(KEY) if isinstance(doc, dict) else None
    val = val.strip() if isinstance(val, str) else ""
    if not val:
        raise LoginError("no measurement login: %s is missing or empty in the secret store. Run `claude setup-token` in a terminal "
                         "and store the token under that key. No session was started." % KEY)
    return val


def child_env(parent=None, secrets_file=None):
    """A copy of `parent` (default os.environ) for a measurement session: CLAUDE_CODE_OAUTH_TOKEN from the store, the parent's three auth
    variables dropped first, nothing else changed. LoginError when the store has no token (fail closed)."""
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
    one there can shadow the token or be refreshed by a daemon the session spawns (anthropics/claude-code#105047)."""
    try:
        os.remove(os.path.join(d, ".credentials.json"))
    except FileNotFoundError:   # none there, or another worker of the same run removed it first (skill_bench makes the dir per job)
        pass
