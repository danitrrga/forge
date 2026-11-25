"""Every call `fwx wave run` makes to Orca, and what a worker's worktree holds before Orca starts a session in it (09.6 T66).

This is the one module that starts a worker, the seam 01-factory adds `claude -p` beside. What it does that a caller cannot forget:
  - every `orca` call loses ORCA_AGENT_SESSION_ID, ORCA_AGENT_SESSION_SPAWN_TOKEN and ORCA_STRUCTURED_SESSION, else Orca binds the launching
    session's run and sends every completion into the orchestrator's chat;
  - `worker-start` is always `--worktree path:<an existing worktree>` with no creation flag (`--name`, `--repo`, `--base-branch`,
    `--display-name`, `--comment`, `--setup`): Orca refuses them together, and fwx made the worktree so that it could prepare it;
  - a worker is released only once it is settled: a dispatch that ended its turn without `worker_done` stays `ready` and idle, and Orca
    refuses its `worker-release` (`dispatch_inactive`) until `worker-stop` ran (research/orca-boundary.md): the caller stops it first;
  - `run-create` is sent from a terminal fwx made for the run (`terminal_create`, closed when the run ends), because with those variables gone
    Orca has no sender for it; the workers' `worker_done` go to the run's inbox, not to any chat;
  - `repo` is added once, and not at all when `orca repo list` already shows the checkout.

`prepare_worker` is the part of a start that is fwx's: the worktree holds a copy of the main checkout's `.claude/settings.local.json` with
`env.FORCE_PROMPT_CACHING_5M` `1` merged in (a worker is a top-level session and writes its cache at one hour without it; `worker-start`
takes no `--env`, and the settings' `env` was seen to work), its `fwx-worker.json` marker (role, run, unit) in its git dir, and the settings
file in `<git-common-dir>/info/exclude` (git reads a linked worktree's excludes from the common dir only), so that `git status` there stays
clean. Imports the standard library and execute.base.
"""
import json
import os
import re
import subprocess

from fwx.execute.base import WaveError, git, out

PLUGIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
SESSION_VARS = ("ORCA_AGENT_SESSION_ID", "ORCA_AGENT_SESSION_SPAWN_TOKEN", "ORCA_STRUCTURED_SESSION")
SETTLED = ("succeeded", "failed", "stopped")
SETTINGS = os.path.join(".claude", "settings.local.json")
MARKER = "fwx-worker.json"
REPLY_LINE = re.compile(
    r"(?:(?:done|wrong-base|question|failed) \S+/\.fwx-agent/\S+/report\.json commits=\d+"
    r"|reviewed \S+/\.fwx-agent/\S+/report\.json looked_at=\d+ findings=\d+ criteria_no=\d+ criteria_unproven=\d+"
    r"|verdicts \S+/\.fwx-agent/\S+/report\.json)\Z"
)


class OrcaError(WaveError):
    """A call to Orca failed or answered something unreadable."""


def _env():
    return {k: v for k, v in os.environ.items() if k not in SESSION_VARS}


def call(*args, timeout=120):
    try:
        return subprocess.run(["orca"] + list(args), capture_output=True, text=True, env=_env(), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OrcaError("orca %s: %s" % (" ".join(args[:2]), e))


def _json(r, args):
    try:
        body = json.loads(r.stdout)
    except ValueError:
        body = None
    if r.returncode != 0 or not isinstance(body, dict) or body.get("ok") is not True:
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and isinstance(err.get("code"), str) and isinstance(err.get("message"), str):
            why = err["code"] + ": " + err["message"]
        else:  # an error object with a null or missing field must stay an OrcaError: a TypeError here skipped the rest of a release
            why = (r.stderr.strip() or r.stdout.strip())[:200]
        raise OrcaError("orca %s failed (exit %d): %s" % (" ".join(args[:2]), r.returncode, why))
    return body.get("result") or {}


def result(*args):
    """The `result` of the JSON an `orca ... --json` call prints; OrcaError for any other answer."""
    return _json(call(*args, "--json"), args)


def _first(node, keys, prefix=""):
    if isinstance(node, dict):
        for k in keys:
            v = node.get(k)
            if isinstance(v, str) and v.startswith(prefix) and v:
                return v
        for v in node.values():
            found = _first(v, keys, prefix)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _first(v, keys, prefix)
            if found:
                return found
    return None


def ensure_repo(path):
    """`orca repo add --path <path>` unless Orca already lists it."""
    listed = result("repo", "list").get("repos") or []
    if any(isinstance(r, dict) and os.path.realpath(str(r.get("path"))) == os.path.realpath(path) for r in listed):
        return False
    result("repo", "add", "--path", path)
    return True


def terminal_create(path, title):
    """A terminal in the checkout `path`, titled `title`, and its handle: the sender `run-create` needs, as the session variables that would have
    named one are stripped (Orca 1.4.273: `no_active_sender_terminal`). It is created in the background, not focused."""
    got = result("terminal", "create", "--worktree", "path:" + path, "--title", title)
    handle = _first(got, ("handle",))
    if not handle:
        raise OrcaError("orca terminal create named no handle: %s" % json.dumps(got)[:200])
    return handle


def terminal_alive(handle):
    try:
        result("terminal", "show", "--terminal", handle)
    except OrcaError:
        return False
    return True


def terminal_close(handle):
    result("terminal", "close", "--terminal", handle)


def run_create(objective, sender):
    got = result("orchestration", "run-create", "--objective", objective, "--from", sender)
    run = _first(got, ("runId", "id"), "run_")
    if not run:
        raise OrcaError("orca run-create named no run: %s" % json.dumps(got)[:200])
    return run


def start(run, spec_file, model, worktree):
    got = result("orchestration", "worker-start", "--spec-file", spec_file, "--run", run, "--agent", "claude", "--model", model,
                 "--worktree", "path:" + worktree)
    dispatch = _first(got, ("dispatchId",))
    if not dispatch:
        raise OrcaError("orca worker-start named no dispatch: %s" % json.dumps(got)[:200])
    return dispatch


def show(dispatch):
    return result("orchestration", "worker-show", "--dispatch", dispatch)


def last_text(dispatch):
    """The last text the worker's assistant wrote, from its transcript (every page of it); None when there is none.
    When a later assistant turn adds closing prose after `worker_done`, the last line matching a worker reply grammar wins."""
    messages, cursor = [], None
    for _ in range(50):
        got = result("orchestration", "worker-read", "--dispatch", dispatch, "--source", "transcript", "--limit", "200",
                     *(["--cursor", cursor] if cursor else []))
        tr = got.get("transcript") or {}
        batch = tr.get("messages") or []
        messages += batch
        nxt = _first(got, ("nextCursor", "cursor"))
        if not batch or tr.get("limited") is False or not nxt or nxt == cursor:
            break
        cursor = nxt
    fallback = None
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "assistant":
            texts = [b.get("text") for b in m.get("blocks") or [] if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
            for text in reversed(texts):
                lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
                if not lines:
                    continue
                if fallback is None:
                    fallback = text
                for line in reversed(lines):
                    if REPLY_LINE.match(line):
                        return line
    return fallback


def stop(dispatch):
    result("orchestration", "worker-stop", "--dispatch", dispatch)


def release(dispatch, state):
    """Release a dispatch, stopping it first unless `state` (what Orca last said) is settled."""
    if state not in SETTLED:
        stop(dispatch)
    result("orchestration", "worker-release", "--dispatch", dispatch)


def agent_body(role):
    """The text of `agents/<role>.md` without its front matter: a worker is started with no agent type, so its spec is the agent."""
    path = os.path.join(PLUGIN, "agents", role + ".md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise WaveError("no agent file for the role %s (%s)" % (role, e))
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        text = text[end + 5:] if end >= 0 else text
    return text.strip()


def make_worktree(main, path, sha, branch=None):
    """A worktree of `main` at `sha` under `path`: on a new `branch` (an executor writes commits), detached otherwise."""
    args = ["worktree", "add", "-q", "-b", branch, path, sha] if branch else ["worktree", "add", "-q", "--detach", path, sha]
    r = git(main, *args)
    if r.returncode:
        raise WaveError("git worktree add %s failed: %s" % (path, r.stderr.strip()))


def prepare_worker(main, worktree, role, run, unit):
    """The settings copy, the marker and the exclude line a worker's worktree holds before its session starts."""
    src = os.path.join(main, SETTINGS)
    try:
        with open(src, encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError) as e:
        raise WaveError("%s cannot be read as settings (%s): a worker's settings are a copy of it" % (src, e))
    if not isinstance(settings, dict) or not isinstance(settings.get("env", {}), dict):
        raise WaveError("%s: `env` is not an object, so the 5-minute cache switch cannot be merged into it" % src)
    env = settings.setdefault("env", {})
    env["FORCE_PROMPT_CACHING_5M"] = "1"
    dest = os.path.join(worktree, SETTINGS)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    gitdir, common = (out(worktree, "rev-parse", "--path-format=absolute", x) for x in ("--absolute-git-dir", "--git-common-dir"))
    if not gitdir or not common:
        raise WaveError("%s is not a worktree" % worktree)
    try:
        # 0600: the copy holds the project's `env`, and a file made with the default mode would be readable by other users
        with open(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(settings, f, indent=1)
            f.write("\n")
        with open(os.path.join(gitdir, MARKER), "w", encoding="utf-8") as f:
            json.dump({"role": role, "run": run, "unit": unit}, f)
        exclude = os.path.join(common, "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        have = open(exclude, encoding="utf-8").read() if os.path.exists(exclude) else ""
        if SETTINGS not in have.splitlines():
            with open(exclude, "a", encoding="utf-8") as f:
                f.write(("" if not have or have.endswith("\n") else "\n") + SETTINGS + "\n")
    except OSError as e:
        raise WaveError("cannot prepare the worktree %s: %s" % (worktree, e))
