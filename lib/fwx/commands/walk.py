"""The UI walk's app, browsers, planted control, findings file, review and close: fwx walk up|ab|pw|arm-control|findings|review-page|review-answers|down|sweep|selftest ...

Everything the walk does with the app and the browsers is code here, never a prompt. Each subcommand but `ab` and `pw` (which
hand the program's own output through) prints one JSON object and leaves it in the run's folder. Exit 0 done, 1 something failed
or is left, 2 refused or a usage error (the reason on stderr, nothing started), 77 `NOT RUN, NOT ARMED: <why>` for a missing tool.

  up --dir D --part N --round R [--app JSON] [--repo P] [--tramos T]
      The run's folder is `<D>/ui-walk/<N>-<R>/` (D is the phase folder, or the job folder in the factory); the screenshots and
      clips go to `<git-common-dir>/fwx/walks/<namespace>/`. Without `app_run` (and no --app) or with integrations.agent_browser
      off: `NOT RUN, NOT ARMED`, exit 0, `{"armed": false, "reason": ...}`. Else: the app's URL must be local (localhost, 127.0.0.1,
      ::1, *.localhost), nothing may answer there yet (exit 2), then `app_run.up` runs in the repo with FWX_WALK_STATE (the file
      where it leaves the demo account's session: a Playwright storageState; no agent sees a password) and FWX_WALK_RUN (the
      namespace, a mark every process of the app inherits, which `down` counts). `run.json` is written and printed:
      `{armed, run, run_dir, url, apps, namespace, capacity}`. `run` is `app_run.run` (a prefix that runs a command inside the app's
      network); the empty string is a valid value (the command runs in the repo's cwd), not an absent field. `capacity` is
      `fwx capacity --role ui-walker --want <2 x --tramos, default 1> --per-agent-mb <PER_AGENT_MB>`; when it cannot answer the quota
      is 1 and says so; allowed 0 stops before the app starts (exit 1). With `container: true` the quota is the number of walkers: `up` runs
      once per walker with FWX_WALK_NAME=<namespace>-w<k> (and `{name}` in `up`, `run`, `down` and `url`), and session `w<k>` of `ab`
      uses app k. With FWX_FACTORY_CONTAINER=1 the image's `up` and `down` (FACTORY_UI_DIR) run and `app_run` is not read; the URL
      is the last line of its output, `{"url": ...}`.
      Config key `walk.browser_executable` (read here through config.py, kept in run.json): the path of the browser `ab` must use,
      added to every call as `--executable-path`, so a wrapper around the system browser (an extension) never reaches the walk. Set
      and the file missing: `NOT RUN, NOT ARMED: browser_executable <path> missing`, exit 0, `{"armed": false}`. Unset: nothing
      changes. Ignored in the factory (the image's own browser).
  ab [--run R] <session> <args...>     agent-browser with the guards below; `pw [--run R] <session> <args...>`: the same with Playwright's CLI
      `--run` is a run folder or a namespace; without it, the repository's only open run.
  arm-control --run R --screen URL     plants the control: an init script that makes the main title of that route as large and light
      as body text (a hierarchy defect), registered by `ab` at launch with --init-script; control.json. No walker sees it named.
  findings --run R         the `verified-*.json` of the folder (a list, or {findings: [...]}, each with `id` and `verdict`) into `fix.json`
      (CONFIRMED and PLAUSIBLE) and `contradicted.json` (CONTRADICTED); the rest is dropped. Severity blocker/major/minor/cosmetic is
      written as high/high/medium/low (3.4's words).
  review-page --run R --fixed F        `review/decisions.json` for design/verdict: one item per fixed finding ("¿Mantener este arreglo?",
      figures today/built) and one per CONTRADICTED ("¿Cambiar lo aprobado por esto?"), the item `id` being the finding's. A `.webm`
      clip becomes an animated WebP with ffmpeg; without it `NOT RUN, NOT ARMED: ffmpeg missing`, exit 0, the clip's path in the text.
      `review/map.json` says which id is a fix and which a contradicted one. F is a file with [{id, commit}].
  review-answers --run R FILE        the line `verdict wait` printed, as `{accepted, rejected: [{id, note}], contradicted_wanted, open, stale}`
      in `review/answers.json`. Only a fix answered "ok" and not stale is accepted.
  down --run R         `close --all` of the run's namespace, the app's `down` (per app; the image's in the factory; with `container`
      `docker rm -f` by exact name), then a count of the processes whose environment or command line carries the namespace:
      `down.json` says how many it looked at and what is left; exit 1 if anything is, or a `down` or a container failed.
  selftest [--dir D] [--repo P] [--image-id ID] [--json]
      Proves the environment: `up` (arms, gives a URL), the app answers 200 (asked from inside its network, through `app_run.run`),
      `agent-browser` opens the URL with the demo session and the snapshot has an element, a capture comes out (a PNG, not the
      `about:blank` one at that size), `down` leaves 0 processes. Each check says how many things it looked at; looking at 0 is a
      failure, and a check whose predecessor failed is "not reached". The run folder is `<D>/ui-walk/1-1/` (D defaults to
      `<git-common-dir>/fwx/selftest`); `selftest.json` there is `{image_id?, passed, checks: [{name, looked_at, ok, detail}]}`.
      Exit 0 all pass, 1 a check failed (named on stderr), 2 `NOT RUN, NOT ARMED` (no `app_run`, agent_browser off, no
      agent-browser): 2 is not green. `down` always runs once `up` armed. With FWX_FACTORY_CONTAINER=1 the image's scripts are the app.
  sweep        `down` of every open run of `<git-common-dir>/fwx/walks/` whose owner process is gone. The owner is the
      `claude` process above `up` (FWX_WALK_OWNER_PID overrides); with no owner found the run is swept after STALE_H hours.

What the guards of `ab`/`pw` do not see: a URL the page's own code builds when it runs, a click on a link that leaves the app, the
code of a `batch` (refused) or read from stdin (refused). `--allowed-domains` (the app's host) covers them in the browser; in the
factory the container's network does. `ab` refuses `connect`, `auth`, `batch` and `chat` when they are one of the first two words
(`fill @e1 connect` types a word), and the flags in REFUSED_FLAGS, EXTRA_REFUSED_FLAGS and OWN_FLAGS (set by this command, never by the
caller), the commands in REFUSED_COMMANDS (they open a window or a listener or reach outside the session), `--state` outside the run's
folder, and any URL that is not the app's host in `open`, `goto`, `navigate`, `pushstate`, `tab new`
and in the code of `eval`. Every accepted call carries the namespace, the session, the idle timeout, the screenshots folder and
`--args --font-render-hinting=none`. The first call of a session also sets the viewport the `pw` path uses (`set viewport 1309 818 1.1`)
before the caller's command; a `viewport` of the caller's own wins. AGENT_BROWSER_* variables of the caller are dropped.

Measured by 3.5 U1 (framework-discuss/plan/3.5-review/probe.md): the demo session enters by `cookies set <name> <value> --url <app>` (`--state`
and `state load` are rejected under `--allowed-domains`); only the command that launches the daemon goes through `run`, the others
find it with AGENT_BROWSER_SOCKET_DIR; Playwright's CLI inside the rig is `npx --offline --no-install`; the browser is
/usr/bin/google-chrome-stable through Omarchy's wrapper (it loads an extension and passes --ozone-platform=wayland); the key
`walk.browser_executable` (above) is how a machine points `ab` at a clean browser instead.
"""
import base64
import contextlib
import datetime
import glob
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from fwx import config
from fwx.execute import base

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
FACTORY_UI_DIR = "/opt/fwx/ui"  # the image's `up` and `down` (5.2a Appendix C); a test replaces this constant on a copy of the tree
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
PER_AGENT_MB = 500  # a browser on the host, measured by U1 (490 MiB PSS, rounded)
PER_AGENT_MB_CONTAINER = 1400  # the browser plus its own copy of the app (U1: ~897 MiB for the measured project's rig)
VIEWPORT = (1309, 818)
SCALE = 1.1
IDLE_TIMEOUT = "20m"
IDLE_S = 20 * 60
FONT_ARGS = "--font-render-hinting=none"  # U1: changes no capture; the spec keeps it
PW_VERSION = "0.1.23"  # @playwright/cli, with Firefox 158 = firefox-1569 (probe.md step 10)
PW_FIREFOX = "firefox-1569"
UP_TIMEOUT_S = 900
WAIT_URL_S = 120
DRAIN_S = 3  # how long `down` waits for processes to exit after the close
STALE_H = 12
WEBP = ("fps=12,scale=640:-1", "60")  # 640 px, 12 fps, quality 60: 13 KB for the 5 s clip of U1
IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
ASK_FIX = "¿Mantener este arreglo?"
ASK_CONTRADICTED = "¿Cambiar lo aprobado por esto?"
VERDICTS = ("CONFIRMED", "PLAUSIBLE", "CONTRADICTED", "NOT REPRODUCED", "TOOLING", "DUPLICATE")
SEVERITY = {"blocker": "high", "major": "high", "minor": "medium", "cosmetic": "low"}
REFUSED_WORDS = ("connect", "auth", "batch", "chat")
REFUSED_FLAGS = ("--cdp", "--auto-connect", "--profile", "--headed")
EXTRA_REFUSED_FLAGS = ("-p", "--provider", "--proxy", "--restore", "--session-name", "--extension", "--allow-file-access", "--config", "--browser")
OWN_FLAGS = ("--namespace", "--session", "--idle-timeout", "--screenshot-dir", "--args", "--allowed-domains", "--init-script", "--executable-path")
# Commands that open a window or a listener on the host or reach outside the session, each with the line of `agent-browser --help`:
# inspect "Open Chrome DevTools for the active page", stream "Start runtime WebSocket streaming for this session" (a port on the host),
# dashboard "Start the dashboard server (default port: 4848)", mcp "Start an MCP stdio server exposing agent-browser tools",
# plugin "Add a plugin from npm or GitHub" / "Run a command.run or custom plugin request", install "Install browser binaries",
# upgrade "Upgrade to the latest version", doctor "Diagnose install; auto-clean stale files", profiles "List available Chrome profiles".
# Only the command word (the first one that is not a flag) is looked at, so `fill @e1 inspect` still types a word.
REFUSED_COMMANDS = ("inspect", "stream", "dashboard", "mcp", "plugin", "install", "upgrade", "doctor", "profiles")
URL_WORDS = ("open", "goto", "navigate", "pushstate", "read")  # `read <url>` fetches from the CLI process, outside --allowed-domains
SET_VIEWPORT = ["set", "viewport", "%d" % VIEWPORT[0], "%d" % VIEWPORT[1], "%g" % SCALE]  # `set viewport <w> <h> [scale]` (agent-browser set --help)
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
URL_IN_CODE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"`)\\<>]+")
USAGES = {
    "up": "usage: fwx walk up --dir D --part N --round R [--app JSON] [--repo P] [--tramos T]",
    "ab": "usage: fwx walk ab [--run R] <session> <agent-browser args...>",
    "pw": "usage: fwx walk pw [--run R] <session> <playwright-cli args...>",
    "arm-control": "usage: fwx walk arm-control --run R --screen URL",
    "findings": "usage: fwx walk findings --run R",
    "review-page": "usage: fwx walk review-page --run R --fixed FILE",
    "review-answers": "usage: fwx walk review-answers --run R FILE",
    "down": "usage: fwx walk down --run R",
    "sweep": "usage: fwx walk sweep",
    "selftest": "usage: fwx walk selftest [--dir D] [--repo P] [--image-id ID] [--json]",
}


class Stop(Exception):
    """The command stops: the message on stderr, the exit code (2 refused, 1 failed, 77 not run)."""

    def __init__(self, msg, code=2):
        Exception.__init__(self, msg)
        self.code = code


def usage(cmd, why=None):
    return Stop("%s%s" % (why + "\n" if why else "", USAGES[cmd]))


def opts(cmd, argv, valued=(), positional=0):
    """({option: value}, [positionals]); an unknown option, a missing value or a wrong number of positionals is a usage error."""
    got, pos, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in valued:
            if i + 1 >= len(argv):
                raise usage(cmd, "%s lacks its value" % a)
            got[a] = argv[i + 1]
            i += 2
        elif a.startswith("--"):
            raise usage(cmd, "%s is not an option of this command" % a)
        else:
            pos.append(a)
            i += 1
    if len(pos) != positional:
        raise usage(cmd)
    return got, pos


def say(obj):
    sys.stdout.write(json.dumps(obj) + "\n")


def not_run(why):
    sys.stderr.write("fwx walk: NOT RUN, NOT ARMED: %s\n" % why)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise Stop("cannot read %s %s (%s)" % (what, path, e.strerror))
    except ValueError as e:
        raise Stop("%s %s is not valid JSON (%s)" % (what, path, e))


# ------------------------------------------------------------------------------------------------------ runs and folders
def common_dir(cwd):
    c = base.out(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not c:
        raise Stop("not inside a git repository: %s" % cwd)
    return c


def walks_dir(cwd):
    return os.path.join(common_dir(cwd), "fwx", "walks")


def namespace_of(run_dir, part, rnd):
    return "walk-%d-%d-%s" % (part, rnd, hashlib.sha1(run_dir.encode()).hexdigest()[:6])


def run_dir_of(ref, cwd=None):
    """The folder `--run` names: a folder, or the namespace of a run registered in this repository."""
    if os.path.isdir(ref):
        return os.path.realpath(ref)
    entry = os.path.join(walks_dir(cwd or os.getcwd()), ref, "walk.json")
    if os.path.isfile(entry):
        return read_json(entry, "the walk entry")["run_dir"]
    raise Stop("no run %r: not a folder, and no such namespace in this repository" % ref)


def load_run(ref, cwd=None):
    rd = run_dir_of(ref, cwd)
    return read_json(os.path.join(rd, "run.json"), "run.json")


def open_runs(cwd):
    """[(namespace, walk.json)] of the runs of this repository that were not closed."""
    out = []
    for p in sorted(glob.glob(os.path.join(walks_dir(cwd), "*", "walk.json"))):
        w = read_json(p, "the walk entry")
        if not w.get("closed"):
            out.append((os.path.basename(os.path.dirname(p)), w))
    return out


def which_run(given, cwd):
    if given:
        return given
    runs = open_runs(cwd)
    if len(runs) == 1:
        return runs[0][1]["run_dir"]
    raise Stop("%s open runs in this repository: say which with --run (a folder or a namespace)" % ("no" if not runs else len(runs)))


def proc_start(pid):
    """The start time (clock ticks since boot) of a process, the second half of its identity; None when it is gone."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8", errors="replace") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def find_owner():
    """(pid, start) of the process that owns the run: FWX_WALK_OWNER_PID, else the nearest `claude` above this one; (None, None) if none."""
    env = os.environ.get("FWX_WALK_OWNER_PID", "")
    if env.isdigit():
        return int(env), proc_start(int(env))
    for pid in ancestors(os.getpid()):
        try:
            with open("/proc/%d/comm" % pid, encoding="utf-8") as f:
                if f.read().strip() == "claude":
                    return pid, proc_start(pid)
        except OSError:
            pass
    return None, None


def ancestors(pid):
    out = []
    while pid > 1:
        try:
            with open("/proc/%d/stat" % pid, encoding="utf-8", errors="replace") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        out.append(pid)
    return out


# ------------------------------------------------------------------------------------------------------------------ urls
def local_host(url):
    """The host of a local URL (localhost, 127.0.0.1, ::1, *.localhost); None for any other."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme in ("http", "https") and host and (host in LOCAL_HOSTS or host.endswith(".localhost")):
        return host
    return None


def host_of(token):
    """The host a word the browser would navigate to has (`example.com/x` counts as http://example.com/x); None for one without."""
    try:
        return urlsplit(token if "://" in token else "http://" + token).hostname
    except ValueError:
        return None


class Quiet(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def answering(url):
    """Whether anything answers at the URL: any HTTP response counts, a refused connection or a timeout does not."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Quiet)
    try:
        opener.open(url, timeout=1.0).close()
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for(url):
    end = time.monotonic() + WAIT_URL_S
    while time.monotonic() < end:
        if answering(url):
            return True
        time.sleep(0.5)
    return False


# --------------------------------------------------------------------------------------------------------------------- up
def sub(text, name):
    return text.replace("{name}", name) if name else text


def shell(cmd, cwd, env, log):
    """`cmd` in a shell, its output into `log` (a file, so a daemon it leaves behind holds no pipe). The return code."""
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "ab") as lf:
        try:
            return subprocess.run(cmd, shell=True, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                                  timeout=UP_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            return 124


def tail(path, n=12):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:]).rstrip()
    except OSError:
        return ""


def capacity(repo, want, container):
    """`fwx capacity --role ui-walker` as one object; when it cannot answer, a quota of one and the reason."""
    mb = PER_AGENT_MB_CONTAINER if container else PER_AGENT_MB
    cmd = [sys.executable, os.path.join(ROOT, "bin", "fwx"), "capacity", "--role", "ui-walker", "--want", str(want),
           "--per-agent-mb", str(mb), "--json"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=60)
        if r.returncode in (0, 1):
            res = json.loads(r.stdout.strip().splitlines()[-1])
            if isinstance(res, dict) and isinstance(res.get("allowed"), int):
                return res
        why = "rc %d: %s" % (r.returncode, (r.stderr.strip().splitlines() or ["no output"])[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        why = str(e)
    return {"role": "ui-walker", "want": want, "allowed": 1, "note": "capacity unavailable (%s): a quota of 1" % why}


def app_spec(o, cfg, factory):
    """The app's table: --app, else project.app_run, else the image's scripts in the factory; None when there is no app."""
    if factory:
        return {"up": shlex.quote(os.path.join(FACTORY_UI_DIR, "up")), "run": "", "down": shlex.quote(os.path.join(FACTORY_UI_DIR, "down")),
                "url": None, "container": False}
    if "--app" in o:
        try:
            app = json.loads(o["--app"])
        except ValueError as e:
            raise usage("up", "--app is not JSON (%s)" % e)
        if not isinstance(app, dict):
            raise usage("up", "--app is not a JSON object")
    else:
        app = cfg["project"].get("app_run")
    if not app:
        return None
    for k in ("up", "run", "down", "url"):
        if not isinstance(app.get(k), str):
            raise Stop("app_run.%s is missing or not a string%s" % (k, " (it may be empty)" if k == "run" else ""))
    if "container" in app and not isinstance(app["container"], bool):
        raise Stop("app_run.container is not true or false")
    return app


def stop_apps(started, repo, env):
    for a in started:
        shell(a["down"], repo, env, os.path.join(a["log_dir"], "down-%s.log" % a["name"]))


def cmd_up(argv):
    o, _ = opts("up", argv, ("--dir", "--part", "--round", "--app", "--repo", "--tramos"))
    for k in ("--dir", "--part", "--round"):
        if k not in o:
            raise usage("up", "%s is required" % k)
    try:
        part, rnd, tramos = int(o["--part"]), int(o["--round"]), int(o.get("--tramos", 1))
        assert part >= 1 and rnd >= 1 and tramos >= 1
    except (ValueError, AssertionError):
        raise usage("up", "--part, --round and --tramos are whole numbers of 1 or more")
    repo = o.get("--repo") or base.toplevel(os.getcwd())
    if not repo or not os.path.isdir(repo):
        raise Stop("no repository: --repo %r, and the current folder is in none" % o.get("--repo"))
    repo = os.path.realpath(repo)
    factory = os.environ.get("FWX_FACTORY_CONTAINER") == "1"
    cfg = config.load(repo)
    if not cfg["integrations"].get("agent_browser"):
        return not_armed("integrations.agent_browser is false")
    app = app_spec(o, cfg, factory)
    if app is None:
        return not_armed("no app_run in the project's configuration and no --app")
    exe = None if factory else cfg["walk"]["browser_executable"]
    if exe and not os.path.isfile(exe):
        return not_armed("browser_executable %s missing" % exe)
    run_dir = os.path.join(os.path.abspath(o["--dir"]), "ui-walk", "%d-%d" % (part, rnd))
    ns = namespace_of(run_dir, part, rnd)
    container = bool(app.get("container"))
    cap = capacity(repo, tramos * 2, container)
    if cap["allowed"] < 1:
        raise Stop("no room for a walker: capacity allowed 0 (%s)" % "; ".join(cap.get("reasons", [])[:2]), 1)
    names = [ns + "-w%d" % k for k in range(1, cap["allowed"] + 1)] if container else [ns]
    walks = os.path.join(common_dir(repo), "fwx", "walks", ns)
    apps = []
    for k, name in enumerate(names, 1):
        tag = name if container else None
        apps.append({"name": name, "url": sub(app["url"], tag) if app["url"] else None, "run": sub(app["run"], tag),
                     "up": sub(app["up"], tag), "down": sub(app["down"], tag), "log_dir": run_dir,
                     "state": os.path.join(run_dir, "demo-state-w%d.json" % k if container else "demo-state.json")})
    for a in apps:
        if a["url"] and not local_host(a["url"]):
            raise Stop("app url %s is not local (localhost, 127.0.0.1, ::1, *.localhost): the walk only touches the seeded local app" % a["url"])
    if len({a["url"] for a in apps if a["url"]}) < len([a for a in apps if a["url"]]):
        raise Stop("the apps share the url %s: put {name} in app_run.url" % apps[0]["url"])
    for a in apps:
        if a["url"] and answering(a["url"]):
            raise Stop("%s is already answering before up: another app (or a run that was not closed) is there" % a["url"])
    os.makedirs(run_dir, exist_ok=True)
    for stale in ("down.json", "run.json"):
        if os.path.exists(os.path.join(run_dir, stale)):
            os.remove(os.path.join(run_dir, stale))
    started = []
    env_base = dict(os.environ)
    try:
        for a in apps:
            env = dict(env_base, FWX_WALK_STATE=a["state"], FWX_WALK_RUN=ns)
            if container:
                env["FWX_WALK_NAME"] = a["name"]
            log = os.path.join(run_dir, "up-%s.log" % a["name"])
            started.append(a)
            rc = shell(a["up"], repo, env, log)
            if rc:
                raise Stop("up failed for %s (exit %d): %s" % (a["name"], rc, tail(log)), 1)
            if factory:
                try:
                    a["url"] = json.loads(tail(log, 1))["url"]
                    assert isinstance(a["url"], str)
                except (ValueError, KeyError, AssertionError, TypeError):
                    raise Stop("the image's up printed no {\"url\": ...} on its last line: %s" % tail(log, 3), 1)
                if not local_host(a["url"]):
                    raise Stop("app url %s is not local (localhost, 127.0.0.1, ::1, *.localhost)" % a["url"])
            if not wait_for(a["url"]):
                raise Stop("nothing answered at %s within %d s after up" % (a["url"], WAIT_URL_S), 1)
    except Stop:
        stop_apps(started, repo, env_base)
        raise
    hosts = []
    for a in apps:
        for h in ([host_of(a["url"])] + (list(LOCAL_HOSTS[:2]) if local_host(a["url"]) else [])):
            if h not in hosts:
                hosts.append(h)
    owner, start = find_owner()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    run = {"armed": True, "namespace": ns, "run_dir": run_dir, "repo": repo, "part": part, "round": rnd, "factory": factory,
           "container": container, "url": apps[0]["url"], "run": apps[0]["run"], "hosts": hosts, "browser_executable": exe,
           "shots": os.path.join(walks, "shots"), "capacity": cap, "started": started_at,
           "apps": [{k: v for k, v in a.items() if k != "log_dir"} for a in apps]}
    os.makedirs(run["shots"], exist_ok=True)
    write_json(os.path.join(run_dir, "run.json"), run)
    write_json(os.path.join(walks, "walk.json"), {"run_dir": run_dir, "namespace": ns, "repo": repo, "owner_pid": owner,
                                                  "owner_start": start, "started": started_at, "closed": None})
    say({k: run[k] for k in ("armed", "run", "run_dir", "url", "apps", "namespace", "capacity")})
    return 0


def not_armed(why):
    not_run(why)
    say({"armed": False, "reason": why})
    return 0


# ------------------------------------------------------------------------------------------------------------- the guards
def flag_in(tok, names):
    return any(tok == n or tok.startswith(n + "=") for n in names)


def positional(args):
    """The words of a call that are not flags (nor the value of `--enable`, the one flag whose value stands before the URL)."""
    out, skip = [], False
    for t in args:
        if skip:
            skip = False
        elif t == "--enable":
            skip = True
        elif not t.startswith("-"):
            out.append(t)
    return out


def refusal(args, run, pw=False):
    """Why a call of `ab` or `pw` is refused, or None. The words are looked for among the first two non-flag words only."""
    words = positional(args)
    head = words[:2]
    if head[:1] and head[0] in REFUSED_COMMANDS:
        return "`%s` is refused: it opens a window or a listener on the host, or reaches outside the session" % head[0]
    for w in head:
        if w in REFUSED_WORDS or (pw and w == "attach"):
            return "`%s` is refused: the walk only drives the browser it launched, in the run's namespace" % w
    for i, t in enumerate(args):
        if flag_in(t, REFUSED_FLAGS) or flag_in(t, EXTRA_REFUSED_FLAGS):
            return "%s is refused (the walk never reuses a profile or a window, and never connects to another browser)" % t.split("=")[0]
        if flag_in(t, OWN_FLAGS) or (pw and flag_in(t, ("-s",))):
            return "%s is set by `fwx walk`, not by the caller" % t.split("=")[0]
        if t == "--state" or t.startswith("--state="):
            path = t.split("=", 1)[1] if "=" in t else (args[i + 1] if i + 1 < len(args) else "")
            if not inside(path, run["run_dir"]):
                return "--state %s is outside the run's folder %s" % (path, run["run_dir"])
    if head[:1] in (["state"], ["state-load"], ["state-save"]) and len(words) >= 2:
        for path in words[1:]:
            if path not in ("load", "save") and not inside(path, run["run_dir"]):
                return "state file %s is outside the run's folder %s" % (path, run["run_dir"])
    urls = []
    at = next((i for i, w in enumerate(head) if w in URL_WORDS or w == "tab-new"), 1 if head == ["tab", "new"] else None)
    if at is not None:
        urls = words[at + 1:]
    if "eval" in head:
        if "--stdin" in args:
            return "the code of `eval --stdin` cannot be checked: pass it as an argument"
        code = []
        for i, t in enumerate(args):
            if t in ("-b", "--base64") and i + 1 < len(args):
                try:
                    code.append(base64.b64decode(args[i + 1], validate=True).decode("utf-8", "replace"))
                except ValueError:
                    return "the argument of %s is not base64" % t
            elif not t.startswith("-"):
                code.append(t)
        urls += [m for c in code for m in URL_IN_CODE.findall(c)]
    for u in urls:
        h = host_of(u)
        if h not in run["hosts"]:
            return "%s: host %r is not the app's (%s)" % (u, h, ", ".join(run["hosts"]))
    return None


def inside(path, folder):
    p, f = os.path.realpath(path), os.path.realpath(folder)
    return p == f or p.startswith(f + os.sep)


def app_for(run, session):
    """The app a session works on: the only one, or `w<k>` of a container run (k from 1)."""
    apps = run["apps"]
    if not run["container"]:
        return apps[0]
    m = re.fullmatch(r"w(\d+)", session)
    if not m:
        raise Stop("session %r: a run with one app per walker takes sessions w1, w2, ... (%d apps)" % (session, len(apps)))
    k = int(m.group(1))
    if not 1 <= k <= len(apps):
        raise Stop("session %s: only %d app(s) were started for this run (%d walkers)" % (session, len(apps), len(apps)))
    return apps[k - 1]


def clean_env(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_BROWSER_")}
    e.update(extra or {})
    return e


def socket_dir():
    return os.path.join(os.path.expanduser("~"), ".agent-browser")


def split_call(cmd, argv):
    """(run ref or None, session, args) of `[--run R] <session> <args...>`: nothing after the session is read as an option."""
    ref = None
    if argv[:1] == ["--run"]:
        if len(argv) < 2:
            raise usage(cmd, "--run lacks its value")
        ref, argv = argv[1], argv[2:]
    if len(argv) < 2:
        raise usage(cmd)
    if not SESSION.match(argv[0]):
        raise Stop("session %r: letters, digits, `_` and `-`" % argv[0])
    return ref, argv[0], argv[1:]


def marker(run, kind, session):
    return os.path.join(run["run_dir"], "sessions", "%s-%s" % (kind, session))


def alive(path):
    try:
        return time.time() - os.path.getmtime(path) < IDLE_S
    except OSError:
        return False


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        pass
    os.utime(path)


def execute(argv, env, cwd, quiet=False):
    """Run one program; its output goes through (or is kept when `quiet`). NOT RUN, 77, when the program is not there."""
    try:
        if quiet:
            r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
            if r.returncode:
                sys.stderr.write(r.stderr)
            return r.returncode
        return subprocess.run(argv, cwd=cwd, env=env).returncode
    except FileNotFoundError:
        raise Stop("NOT RUN, NOT ARMED: %s missing (not on the PATH)" % argv[0], 77)


def cookies_of(path):
    if not os.path.isfile(path):
        return []
    data = read_json(path, "the demo session")
    return [(c["name"], c["value"]) for c in data.get("cookies", []) if "name" in c and "value" in c]


def cmd_ab(argv):
    ref, session, args = split_call("ab", argv)
    run = load_run(which_run(ref, os.getcwd()))
    app = app_for(run, session)
    why = refusal(args, run)
    if why:
        raise Stop("refused: " + why)
    mark = marker(run, "ab", session)
    fresh = not alive(mark)
    common = ["--namespace", run["namespace"], "--session", session, "--idle-timeout", IDLE_TIMEOUT, "--screenshot-dir", run["shots"],
              "--args", FONT_ARGS, "--allowed-domains", ",".join(run["hosts"])]
    if run.get("browser_executable"):
        common += ["--executable-path", run["browser_executable"]]
    steps = []
    if fresh:
        for name, value in cookies_of(app["state"]):
            steps.append((common + ["cookies", "set", name, value, "--url", app["url"]], True))
    # The size the `pw` path uses, applied before the session's first command (the first `open` then loads at it, and the launch
    # step is whatever comes first); a caller's own `viewport` later wins, and a first call that is one is not preceded by ours.
    words = positional(args)[:2]
    own_size = words[:1] == ["viewport"] or words[:2] == ["set", "viewport"] or words[:1] == ["close"]
    sized_first = fresh and not own_size
    if sized_first:
        steps.append((common + SET_VIEWPORT, True))
    steps.append((common + args, False))
    if fresh:
        ctl = os.path.join(run["run_dir"], "control.json")
        if os.path.isfile(ctl):
            steps[0] = (steps[0][0][:len(common)] + ["--init-script", read_json(ctl, "control.json")["script"]] + steps[0][0][len(common):], steps[0][1])
    prefix = shlex.split(app["run"])
    for i, (a, quiet) in enumerate(steps):
        launch = fresh and i == 0
        env = clean_env({"AGENT_BROWSER_SOCKET_DIR": socket_dir()} if prefix and not launch else None)
        rc = execute((prefix if launch else []) + ["agent-browser"] + a, env, run["repo"], quiet)
        if rc:
            return rc
        touch(mark)
    if "close" in words:
        os.remove(mark)
    return 0


def pw_browsers():
    return os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")


def pw_config(run):
    path = os.path.join(run["run_dir"], "pw.config.json")
    write_json(path, {"browser": {"browserName": "firefox", "launchOptions": {"headless": True},
                                  "contextOptions": {"viewport": {"width": VIEWPORT[0], "height": VIEWPORT[1]}, "deviceScaleFactor": SCALE}}})
    return path


def pw_argv(run, session, args):
    return ["npx", "--offline", "--no-install", "@playwright/cli@" + PW_VERSION, "-s=%s-%s" % (run["namespace"], session)] + args


def cmd_pw(argv):
    ref, session, args = split_call("pw", argv)
    run = load_run(which_run(ref, os.getcwd()))
    app = app_for(run, session)
    why = refusal(args, run, pw=True)
    if why:
        raise Stop("refused: " + why)
    if not os.path.isdir(os.path.join(pw_browsers(), PW_FIREFOX)):
        raise Stop("NOT RUN, NOT ARMED: Playwright Firefox missing (%s in %s)" % (PW_FIREFOX, pw_browsers()), 77)
    launch = positional(args)[:1] == ["open"]
    if launch:
        args = args + ["--browser", "firefox", "--config", pw_config(run)]
        touch(marker(run, "pw", session))
    prefix = shlex.split(app["run"]) if launch else []
    return execute(prefix + pw_argv(run, session, args), clean_env(), run["repo"])


# ---------------------------------------------------------------------------------------------------------- arm-control
CONTROL_JS = """(() => {
  const PATH = %s;
  const apply = () => {
    if (location.pathname.replace(/\\/+$/, "") !== PATH) return;
    const h = document.querySelector('h1, [role="heading"][aria-level="1"]');
    if (!h || h.dataset.fwxCtl === "1") return;
    const cs = getComputedStyle(document.body);
    h.style.setProperty("font-size", cs.fontSize, "important");
    h.style.setProperty("font-weight", cs.fontWeight, "important");
    h.dataset.fwxCtl = "1";
  };
  new MutationObserver(apply).observe(document, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", apply);
  apply();
})();
"""


def cmd_arm_control(argv):
    o, _ = opts("arm-control", argv, ("--run", "--screen"))
    if "--run" not in o or "--screen" not in o:
        raise usage("arm-control")
    run = load_run(o["--run"])
    screen = o["--screen"]
    if host_of(screen) not in run["hosts"]:
        raise Stop("screen %s is not on the app (%s)" % (screen, ", ".join(run["hosts"])))
    path = urlsplit(screen if "://" in screen else "http://" + screen).path.rstrip("/") or "/"
    script = os.path.join(run["shots"], "init.js")
    os.makedirs(run["shots"], exist_ok=True)
    with open(script, "w", encoding="utf-8") as f:
        f.write(CONTROL_JS % json.dumps(path))
    ctl = {"screen": screen, "path": path, "kind": "hierarchy", "script": script,
           "planted": "the main title of the screen has the size and weight of body text",
           "armed": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    write_json(os.path.join(run["run_dir"], "control.json"), ctl)
    say(ctl)
    return 0


# ----------------------------------------------------------------------------------------------------------------- findings
def finding_files(rd):
    files = sorted(glob.glob(os.path.join(rd, "verified-*.json")))
    if not files:
        raise Stop("no verified-*.json in %s: nothing was verified (looked at 0 files)" % rd)
    return files


def cmd_findings(argv):
    o, _ = opts("findings", argv, ("--run",))
    if "--run" not in o:
        raise usage("findings")
    rd = run_dir_of(o["--run"])
    seen, fix, contradicted, dropped = set(), [], [], 0
    for p in finding_files(rd):
        data = read_json(p, "verified file")
        items = data.get("findings") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise Stop("%s is not a list of findings (or {findings: [...]})" % p)
        for f in items:
            if not isinstance(f, dict) or not isinstance(f.get("id"), str) or not f["id"]:
                raise Stop("%s: a finding with no id" % p)
            if f["id"] in seen:
                raise Stop("%s: finding id %s appears twice" % (p, f["id"]))
            seen.add(f["id"])
            verdict = f.get("verdict")
            if verdict not in VERDICTS:
                raise Stop("%s: finding %s has verdict %r, not one of %s" % (p, f["id"], verdict, ", ".join(VERDICTS)))
            f = dict(f, severity=SEVERITY.get(f.get("severity"), f.get("severity")))
            if verdict in ("CONFIRMED", "PLAUSIBLE"):
                fix.append(f)
            elif verdict == "CONTRADICTED":
                contradicted.append(f)
            else:
                dropped += 1
    write_json(os.path.join(rd, "fix.json"), fix)
    write_json(os.path.join(rd, "contradicted.json"), contradicted)
    say({"fix_file": os.path.join(rd, "fix.json"), "contradicted_file": os.path.join(rd, "contradicted.json"),
         "counts": {"confirmed": sum(f["verdict"] == "CONFIRMED" for f in fix), "plausible": sum(f["verdict"] == "PLAUSIBLE" for f in fix),
                    "contradicted": len(contradicted), "dropped": dropped}})
    return 0


# ------------------------------------------------------------------------------------------------------------ review page
def resolve(rd, value):
    return value if os.path.isabs(value) else os.path.join(rd, value)


def figures_of(rd, rev, fid, role, value):
    """([figure objects], [text lines]) for an evidence value: a path to a picture is copied next to decisions.json, any other string is text."""
    figs, text = [], []
    for k, v in enumerate(value if isinstance(value, list) else [value] if value else [], 1):
        if not isinstance(v, str):
            continue
        p = resolve(rd, v)
        ext = os.path.splitext(p)[1].lower()
        if ext in IMAGES:
            if not os.path.isfile(p):
                raise Stop("%s of finding %s: the picture %s is missing" % (role, fid, p))
            name = os.path.join("figs", "%s-%s-%d%s" % (fid, role, k, ext))
            os.makedirs(os.path.join(rev, "figs"), exist_ok=True)
            shutil.copyfile(p, os.path.join(rev, name))
            figs.append({"src": name, "caption": role})
        else:
            text.append(v)
    return figs, text


def convert_clip(rd, rev, fid, f, notes):
    """The WebP figure of the finding's clip, or the line that gives its path when ffmpeg is not there."""
    clip = f.get("clip")
    if not clip:
        return [], []
    src = resolve(rd, clip)
    if not os.path.isfile(src):
        raise Stop("clip of finding %s: %s is missing" % (fid_of(f), src))
    if not shutil.which("ffmpeg"):
        if "ffmpeg missing" not in notes:
            notes.append("ffmpeg missing")
            not_run("ffmpeg missing: the items carry their pictures and the clips' paths")
        return [], ["Clip: %s" % src]
    name = os.path.join("figs", "%s-clip.webp" % fid_of(f))
    os.makedirs(os.path.join(rev, "figs"), exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-an", "-vf", WEBP[0], "-loop", "0", "-c:v", "libwebp_anim",
                        "-quality", WEBP[1], os.path.join(rev, name)], capture_output=True, text=True)
    if r.returncode:
        raise Stop("ffmpeg could not convert %s (exit %d): %s" % (src, r.returncode, r.stderr.strip()[:300]), 1)
    return [{"src": name, "caption": "clip"}], []


def fid_of(f):
    return f["id"]


def item_of(rd, rev, f, ask, commit, notes):
    fid = fid_of(f)
    today, t1 = figures_of(rd, rev, fid, "today", f.get("evidence"))
    built, t2 = figures_of(rd, rev, fid, "built", f.get("evidence_after"))
    clip, t3 = convert_clip(rd, rev, fid, f, notes)
    what = [x for x in ["Screen: %s" % f["screen"] if f.get("screen") else "", "Expected: %s" % f["expected"] if f.get("expected") else "",
                        "Commit: %s" % commit if commit else ""] if x] + t1 + t2 + t3
    return {"id": fid, "title": f.get("claim") or fid, "what": what, "ask": ask, "figures": today + built + clip}


def cmd_review_page(argv):
    o, _ = opts("review-page", argv, ("--run", "--fixed"))
    if "--run" not in o or "--fixed" not in o:
        raise usage("review-page")
    rd = run_dir_of(o["--run"])
    rev = os.path.join(rd, "review")
    fixed = read_json(o["--fixed"], "the fixed file")
    fixed = fixed.get("fixed") if isinstance(fixed, dict) else fixed
    if not isinstance(fixed, list) or not all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in fixed):
        raise Stop("%s is not a list of {id, commit}" % o["--fixed"])
    fix = {f["id"]: f for f in read_json(os.path.join(rd, "fix.json"), "fix.json (run `fwx walk findings` first)")}
    contradicted = read_json(os.path.join(rd, "contradicted.json"), "contradicted.json")
    for x in fixed:
        if x["id"] not in fix:
            raise Stop("fixed id %s is not a finding of fix.json" % x["id"])
    notes, items, mapping = [], [], {}
    if os.path.isdir(rev):
        shutil.rmtree(rev)
    for x in fixed:
        items.append(item_of(rd, rev, fix[x["id"]], ASK_FIX, x.get("commit"), notes))
        mapping[x["id"]] = {"kind": "fix", "commit": x.get("commit")}
    for f in contradicted:
        items.append(item_of(rd, rev, f, ASK_CONTRADICTED, None, notes))
        mapping[f["id"]] = {"kind": "contradicted", "commit": None}
    if not items:
        say({"items": 0, "page": None, "notes": notes})
        return 0
    run = {}
    if os.path.isfile(os.path.join(rd, "run.json")):
        run = read_json(os.path.join(rd, "run.json"), "run.json")
    where = "part %s, round %s" % (run.get("part", "?"), run.get("round", "?"))
    write_json(os.path.join(rev, "decisions.json"), {
        "title": "UI walk, %s" % where,
        "intro": "Keep each fix the walk's findings led to, or send it back; for a contradicted finding, say whether to change what was approved.",
        "items": items})
    write_json(os.path.join(rev, "map.json"), mapping)
    say({"items": len(items), "page": os.path.join(rev, "decisions.json"), "ids": [i["id"] for i in items], "notes": notes})
    return 0


def cmd_review_answers(argv):
    o, pos = opts("review-answers", argv, ("--run",), 1)
    if "--run" not in o:
        raise usage("review-answers")
    rd = run_dir_of(o["--run"])
    mapping = read_json(os.path.join(rd, "review", "map.json"), "review/map.json (run `fwx walk review-page` first)")
    try:
        with open(pos[0], encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise Stop("cannot read %s (%s)" % (pos[0], e.strerror))
    ans = None
    for line in reversed([x for x in text.splitlines() if x.strip()] + ([text] if text.strip() else [])):
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict) and v.get("v") == 2:
            ans = v
            break
    if ans is None:
        raise Stop("no verdict answer (a JSON object with \"v\": 2) in %s" % pos[0])
    unknown = [k for k in ans if k not in ("v", "open", "stale", "global") and k not in mapping]
    if unknown:
        raise Stop("answers for ids the page never had: %s" % ", ".join(unknown))
    stale = [i for i in ans.get("stale", []) if i in mapping]
    out = {"accepted": [], "rejected": [], "contradicted_wanted": [], "open": [], "stale": stale}
    for fid, m in mapping.items():
        a = ans.get(fid) if isinstance(ans.get(fid), dict) else {}
        pick = a.get("pick")
        if fid in stale:
            continue
        if pick not in ("ok", "no"):
            out["open"].append(fid)
        elif m["kind"] == "fix" and pick == "ok":
            out["accepted"].append(fid)
        elif m["kind"] == "fix":
            out["rejected"].append({"id": fid, "note": a.get("note", "")})
        elif pick == "ok":
            out["contradicted_wanted"].append(fid)
    write_json(os.path.join(rd, "review", "answers.json"), out)
    say(out)
    return 0


# ------------------------------------------------------------------------------------------------------------------- down
def scan(ns):
    """(looked, unreadable, [{pid, cmd}]): the processes whose command line carries the namespace or whose environment holds it as a value."""
    if not os.path.isdir("/proc/self"):
        raise Stop("NOT RUN, NOT ARMED: no /proc: the processes of the run cannot be counted", 77)
    skip = set(ancestors(os.getpid())) | {os.getpid()}
    looked, unreadable, found = 0, 0, []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) in skip:
            continue
        pid = int(name)
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        looked += 1
        marked = ns in cmd
        try:
            with open("/proc/%d/environ" % pid, "rb") as f:
                marked = marked or any(e.partition(b"=")[2] == ns.encode() for e in f.read().split(b"\0"))
        except OSError:
            unreadable += 1
        if marked:
            found.append({"pid": pid, "cmd": cmd[:200]})
    return looked, unreadable, found


def docker_names():
    try:
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return r.stdout.split() if r.returncode == 0 else None


def close_containers(names):
    """Remove the containers named exactly `names`; {looked, removed, left}, left None when docker cannot be asked."""
    have = docker_names()
    if have is None:
        return {"looked": None, "removed": [], "left": None, "note": "docker is not available or did not answer"}
    removed = []
    for n in names:
        if n in have:
            subprocess.run(["docker", "rm", "-f", n], capture_output=True, text=True)
            removed.append(n)
    after = docker_names()
    return {"looked": len(have), "removed": removed, "left": None if after is None else [n for n in names if n in after]}


def do_down(run):
    rd, ns = run["run_dir"], run["namespace"]
    steps, repo = [], run["repo"]
    prefixed = any(shlex.split(a["run"]) for a in run["apps"])
    ab = ["agent-browser", "--namespace", ns, "close", "--all"]
    try:
        rc = subprocess.run(ab, cwd=repo, env=clean_env({"AGENT_BROWSER_SOCKET_DIR": socket_dir()} if prefixed else None),
                            capture_output=True, text=True).returncode
        steps.append({"step": "agent-browser close --all", "rc": rc})
    except FileNotFoundError:
        steps.append({"step": "agent-browser close --all", "rc": None, "note": "agent-browser is not on the PATH"})
    for p in sorted(glob.glob(os.path.join(rd, "sessions", "pw-*"))):
        session = os.path.basename(p)[3:]
        try:
            rc = subprocess.run(pw_argv(run, session, ["close"]), cwd=repo, env=clean_env(), capture_output=True, text=True).returncode
            steps.append({"step": "pw close %s" % session, "rc": rc})
        except FileNotFoundError:
            steps.append({"step": "pw close %s" % session, "rc": None, "note": "npx is not on the PATH"})
    ok = True
    for a in run["apps"]:
        cmd = a["down"]
        rc = shell(cmd, repo, dict(os.environ, FWX_WALK_RUN=ns, **({"FWX_WALK_NAME": a["name"]} if run["container"] else {})),
                   os.path.join(rd, "down-%s.log" % a["name"]))
        steps.append({"step": "app down %s" % a["name"], "rc": rc})
        ok = ok and rc == 0
    containers = None
    if run["container"]:
        containers = close_containers([a["name"] for a in run["apps"]])
        ok = ok and containers["left"] == []
    end = time.monotonic() + DRAIN_S
    while True:
        looked, unreadable, left = scan(ns)
        if not left or time.monotonic() >= end:
            break
        time.sleep(0.3)
    res = {"namespace": ns, "run_dir": rd, "looked": looked, "unreadable": unreadable, "left": left, "browsers_left": len(left),
           "steps": steps, "containers": containers}
    write_json(os.path.join(rd, "down.json"), res)
    return res, 0 if ok and not left else 1


def mark_closed(run):
    entry = os.path.join(os.path.dirname(run["shots"]), "walk.json")
    if os.path.isfile(entry):
        w = read_json(entry, "the walk entry")
        w["closed"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        write_json(entry, w)


def report_down(res, code):
    sys.stderr.write("fwx walk down: looked at %d processes (%d unreadable), %d left%s\n" % (
        res["looked"], res["unreadable"], len(res["left"]),
        "".join("; pid %d: %s" % (p["pid"], p["cmd"][:80]) for p in res["left"])))
    for s_ in res["steps"]:
        if s_["rc"]:
            sys.stderr.write("fwx walk down: %s exited %s\n" % (s_["step"], s_["rc"]))
    c = res.get("containers")
    if c and c["left"] != []:
        sys.stderr.write("fwx walk down: containers left: %s%s\n" % (c["left"], " (" + c["note"] + ")" if c.get("note") else ""))


def cmd_down(argv):
    o, _ = opts("down", argv, ("--run",))
    if "--run" not in o:
        raise usage("down")
    run = load_run(o["--run"])
    res, code = do_down(run)
    report_down(res, code)
    if code == 0:
        mark_closed(run)
    say(res)
    return code


# ------------------------------------------------------------------------------------------------------------------ sweep
def owner_alive(w):
    pid = w.get("owner_pid")
    if pid is None:
        started = datetime.datetime.fromisoformat(w["started"])
        return (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds() < STALE_H * 3600
    start = proc_start(pid)
    return start is not None and start == w.get("owner_start")


def cmd_sweep(argv):
    opts("sweep", argv)
    swept, kept, failed = [], [], []
    runs = open_runs(os.getcwd())
    for ns, w in runs:
        if owner_alive(w):
            kept.append({"namespace": ns, "run_dir": w["run_dir"]})
            continue
        try:
            run = read_json(os.path.join(w["run_dir"], "run.json"), "run.json")
            res, code = do_down(run)
        except Stop as e:
            failed.append({"namespace": ns, "run_dir": w["run_dir"], "error": str(e)})
            continue
        report_down(res, code)
        if code == 0:
            mark_closed(run)
            swept.append({"namespace": ns, "run_dir": w["run_dir"]})
        else:
            failed.append({"namespace": ns, "run_dir": w["run_dir"], "left": len(res["left"])})
    say({"looked": len(runs), "swept": swept, "kept": kept, "failed": failed})
    return 1 if failed else 0


# ------------------------------------------------------------------------------------------------------------------ selftest
CHECKS = ("up", "app answers", "snapshot", "capture", "down")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PROBE = """import sys, urllib.error, urllib.request
LOCAL = ("localhost", "127.0.0.1", "::1")


class Local(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.request.urlparse(newurl).hostname or ""
        return super().redirect_request(req, fp, code, msg, headers, newurl) if host in LOCAL or host.endswith(".localhost") else None


try:
    print(urllib.request.build_opener(urllib.request.ProxyHandler({}), Local).open(sys.argv[1], timeout=10).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception as e:
    print("error: %s" % e)
"""


def png_of(path):
    """((width, height, sha256), None) of a PNG file; (None, why) for a missing, empty or non-PNG one."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, "screenshot is missing (%s)" % e.strerror
    if not data:
        return None, "screenshot is empty"
    if len(data) < 24 or data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        return None, "screenshot is not a PNG"
    w, h = struct.unpack(">II", data[16:24])
    return (w, h, hashlib.sha256(data).hexdigest()), None


def probe_apps(run):
    """(apps looked at, [what is wrong]): each app is asked for its url from inside its network (`app_run.run`), and must answer 200."""
    bad = []
    for a in run["apps"]:
        prefix = shlex.split(a["run"])
        argv = prefix + ["python3" if prefix else sys.executable, "-c", PROBE, a["url"]]
        try:
            r = subprocess.run(argv, cwd=run["repo"], env=clean_env(), capture_output=True, text=True, timeout=60)
            got = (r.stdout.strip().splitlines() or ["no answer"])[-1]
        except FileNotFoundError:
            got = "%s is not on the PATH" % argv[0]
        except subprocess.TimeoutExpired:
            got = "timed out"
        if got != "200":
            bad.append("app not answering: GET %s gave %s" % (a["url"], got))
    return len(run["apps"]), bad


def browser_call(run, args):
    """(rc, stdout, stderr) of `fwx walk ab` on session w1 of the run: the guards and the demo session are the walk's own."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "walk", "ab", "--run", run["run_dir"], "w1"] + args,
                       cwd=run["repo"], env=clean_env(), capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def browser_checks(run, rec):
    """The snapshot and capture checks. The blank reference is the first screenshot of the fresh browser (about:blank, which `ab`
    would refuse to open): same session, same size as the page's. A missing agent-browser (rc 77) stops the selftest, NOT RUN."""
    rd, url, state = run["run_dir"], run["url"], run["apps"][0]["state"]
    if not cookies_of(state):
        rec("snapshot", 0, "no demo session: %s holds no cookie (the app's up must leave one there)" % state, False)
        rec("capture", 0, "not reached: no demo session", False)
        return
    blank, page = os.path.join(rd, "selftest-blank.png"), os.path.join(rd, "selftest-page.png")
    got, why = {}, None
    for name, args in (("blank", ["screenshot", blank]), ("open", ["open", url]), ("snapshot", ["snapshot"]), ("page", ["screenshot", page])):
        rc, out, err = browser_call(run, args)
        if rc == 77:
            raise Stop(err.strip() or "NOT RUN, NOT ARMED: agent-browser missing", 2)
        if rc:
            why = "agent-browser %s exited %d: %s" % (args[0], rc, (err.strip().splitlines() or ["no output"])[-1][:200])
            break
        got[name] = out
    if "snapshot" not in got:
        rec("snapshot", 0, why, False)
        rec("capture", 0, "not reached: " + why, False)
        return
    n = sum(1 for line in got["snapshot"].splitlines() if re.search(r"\[ref=e\d+\]|@e\d+", line))
    rec("snapshot", n, "%d element(s) in the snapshot of %s" % (n, url) if n else "empty snapshot: %s opened with the demo session shows no element" % url, n > 0)
    if "page" not in got:
        rec("capture", 0, why, False)
        return
    (b, why_b), (p, why_p) = png_of(blank), png_of(page)
    if why_p:
        rec("capture", 1, why_p, False)
    elif why_b:
        rec("capture", 1, "the about:blank reference: " + why_b, False)
    elif b[:2] != p[:2]:
        rec("capture", 2, "the screenshot is %dx%d and the blank one %dx%d: not comparable" % (p[0], p[1], b[0], b[1]), False)
    elif b[2] == p[2]:
        rec("capture", 2, "screenshot is blank: identical to the about:blank one at %dx%d" % (p[0], p[1]), False)
    else:
        rec("capture", 2, "a %dx%d PNG, different from the about:blank one" % (p[0], p[1]), True)


def cmd_selftest(argv):
    as_json = "--json" in argv
    o, _ = opts("selftest", [a for a in argv if a != "--json"], ("--dir", "--repo", "--image-id"))
    repo = o.get("--repo") or base.toplevel(os.getcwd())
    if not repo or not os.path.isdir(repo):
        raise Stop("no repository: --repo %r, and the current folder is in none" % o.get("--repo"))
    repo = os.path.realpath(repo)
    folder = os.path.abspath(o.get("--dir") or os.path.join(common_dir(repo), "fwx", "selftest"))
    result_file = os.path.join(folder, "ui-walk", "1-1", "selftest.json")
    if os.path.exists(result_file):
        os.remove(result_file)  # a result of an earlier run must never stand for this one
    checks = {}

    def rec(name, looked, detail, ok):
        checks[name] = {"name": name, "looked_at": looked, "ok": bool(ok) and looked > 0, "detail": detail}

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            cmd_up(["--dir", folder, "--part", "1", "--round", "1", "--repo", repo])
    except Stop as e:
        if e.code == 77:
            raise Stop(str(e), 2)
        rec("up", 0, str(e).splitlines()[0][:300], False)
        return selftest_report(checks, o, result_file, as_json)
    armed = json.loads(buf.getvalue().strip().splitlines()[-1])
    if not armed.get("armed"):
        return 2  # `up` said why on stderr: NOT RUN, NOT ARMED, and 2 is not green
    run = load_run(armed["run_dir"])
    rec("up", len(run["apps"]), "armed, url %s" % run["url"], bool(run["url"]))
    try:
        looked, bad = probe_apps(run)
        rec("app answers", looked, "; ".join(bad) if bad else "%d app(s) answered 200 from inside their network" % looked, not bad)
        if bad:
            for name in ("snapshot", "capture"):
                rec(name, 0, "not reached: the app is not answering", False)
        else:
            browser_checks(run, rec)
    finally:
        try:
            res, code = do_down(run)
            left = len(res["left"])
            if left:
                detail = "%d process%s left%s" % (left, "" if left == 1 else "es", "".join("; pid %d: %s" % (p["pid"], p["cmd"][:80]) for p in res["left"]))
            elif code:
                detail = "down failed: " + "; ".join("%s exited %s" % (s_["step"], s_["rc"]) for s_ in res["steps"] if s_["rc"])
            else:
                detail = "looked at %d processes, 0 left" % res["looked"]
            rec("down", res["looked"], detail, not left and not code)
            if not left and not code:
                mark_closed(run)
        except Stop as e:
            rec("down", 0, str(e), False)
    return selftest_report(checks, o, result_file, as_json)


def selftest_report(checks, o, result_file, as_json):
    full = [checks.get(n) or {"name": n, "looked_at": 0, "ok": False, "detail": "not reached: up did not arm"} for n in CHECKS]
    res = {"passed": all(c["ok"] for c in full), "checks": full}
    image = o.get("--image-id") or os.environ.get("FWX_IMAGE_ID")
    if image:
        res = dict({"image_id": image}, **res)
    write_json(result_file, res)
    if as_json:
        say(res)
    else:
        for c in full:
            sys.stdout.write("%s %s (looked at %d): %s\n" % ("PASS" if c["ok"] else "FAIL", c["name"], c["looked_at"], c["detail"]))
    for c in full:
        if not c["ok"]:
            sys.stderr.write("fwx walk selftest: FAIL %s: %s\n" % (c["name"], c["detail"]))
    return 0 if res["passed"] else 1


COMMANDS = {"up": cmd_up, "ab": cmd_ab, "pw": cmd_pw, "arm-control": cmd_arm_control, "findings": cmd_findings,
            "review-page": cmd_review_page, "review-answers": cmd_review_answers, "down": cmd_down, "sweep": cmd_sweep,
            "selftest": cmd_selftest}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        sys.stderr.write("usage: fwx walk <%s> ...\n" % "|".join(COMMANDS))
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except Stop as e:
        msg = str(e)
        if msg.startswith("NOT RUN"):
            sys.stderr.write("fwx walk: %s\n" % msg)
        elif msg.startswith("usage:") or "\nusage:" in msg:
            sys.stderr.write(msg + "\n")
        else:
            sys.stderr.write("fwx walk %s: %s\n" % (argv[0], msg))
        return e.code
    except (config.ConfigError, base.WaveError) as e:
        sys.stderr.write("fwx walk %s: %s\n" % (argv[0], e))
        return 2
