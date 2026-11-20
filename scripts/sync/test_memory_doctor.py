#!/usr/bin/env python3
"""memory_doctor.py's checks, driven through main() in-process on a toy CODEX_HOME.

main() runs with every path it reads pointed into a temp dir: the Codex config and hooks.json, the
rendered hindsight config (by default one whose top-level server is a loopback stand-in answering
/health, so nothing leaves the machine), the known-empty backlog (absent) and the project list
(empty, or one toy project). Nothing under the real HOME is opened; the module is imported, never
run as a script, because the paths are module globals fixed at import time and setting HOME in a
worktree is refused by the permission classifier (round 7, S2's own evidence).

- A hooks.json that exists but does not parse (`{bad`), or parses to something that is not an
  object (`null`, `[1]`), FAILs with "hooks.json unreadable" and never says "every registered hook
  is trusted". Seen failing on b7d9773, load_json swallowed the ValueError and
  returned {}: "'{bad': exit 0, output '  PASS  codex-untrusted    every registered hook is
  trusted'", the same for `null`, and for `[1]`: "AttributeError: 'list' object has no attribute
  'get'" -- a traceback out of main().
- A missing hooks.json is no hooks, and still PASSes (the control): 0 examined.
- A manifest whose one hook carries a trust record PASSes and says 1 examined.
- A manifest with an untrusted hook WARNs, with the detail it always had.
- A manifest of the wrong shape at any depth (hooks, an event, a group, a group's hooks, a hook)
  FAILs the same way, and --hook still exits 0 with no traceback. Seen failing on 26b1cde:
  `{"hooks": ["x"]}` AttributeError: 'list' object has no attribute 'items';
  `{"hooks": {"SessionStart": ["x"]}}` AttributeError: 'str' object has no attribute 'get'; a
  string for an event's groups or a group's hooks enumerated characters.
- lib.hook_entries keeps the ORIGINAL indexes (the trust key is built from them) and counts what
  it skipped.
- A rendered hindsight config or known-empty file that is broken or not an object FAILs by name
  instead of reading as "missing" or raising; a truncated settings.local.json FAILs by name.
- The top-level server is probed too: apiUrl at a refusing port with `banks: {}` FAILs
  hindsight-server and names the bank `personal`.

Part 7.1 (MemPalace) was retired and its hub, rows and cases went with it. What of it stays is driven by backend_cases() below:
memory-one-backend (armed or not, unreadable project files, known-empty declarations) and the budget that Hindsight's probes
draw from under --hook, against `_Stall` stand-ins whose /health answers late or never.

Control record, kept when MemPalace left: each mutation below, applied to memory_doctor.py alone, was seen to turn the named case
red (and only cases that follow from the same line):
  - `== 1` to `>= 0` for the backend     "profile without a backend, hindsight on: exit 0" (11 cases)
  - unreadable project files ignored     "an unreadable project file is not a pass: exit 0"
  - zero examined passes                 "armed and looking at zero projects is a FAIL: exit 0"
  - always armed                         "not armed, a starter project without memory: NOT RUN, exit 0: exit 1" (4 cases)
  - per-call cap (HOOK_CALL_S) removed   "--hook, Hindsight server all: ends in under 4.5 s (took 5.0 s) ..." (3 cases)
  - no whole-request deadline in fetch   "--hook, Hindsight server trickle: ends in under 4.5 s (took 33.0 s) ..." (2 cases)
  - the budget loop ignored              "--hook, a Hindsight server that eats the budget: the next probe is said not run ..."
  - silence kept for every host          "--hook, a silent server does not silence another host ..."
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import sys
import socket
import threading
import time
import traceback
import urllib.request

sys.dont_write_bytecode = True
# No proxy for any request of this suite, the fixtures' and the direct control's alike: a developer's http_proxy would receive them
# (review of the pull request, finding on the stand-in servers). The opener is global, so memory_doctor's urlopen uses it too.
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tests"))
import sandbox  # noqa: E402

# memory_doctor.py is loaded from a throwaway copy of the engine seeded with the fixtures' forge.json (codex and
# hindsight on, as the cases need), not from this checkout: the module reads config/forge.json at import, and
# nothing here asserts anything about this machine's file. Red before, on a copy_engine copy in a toy HOME (M1):
# "! config/forge.json missing -- run bin/forge init" at this load; and, with a seeded all-off forge.json,
# 27 of 36 cases ("FAIL '{bad': exit 0, output ''": the doctor prints "NOT RUN, NOT ARMED: hindsight is off").
WORLD = sandbox.mkdtemp("memdoctor-world-")
sandbox.copy_engine(WORLD)
sandbox.seed(WORLD)
spec = importlib.util.spec_from_file_location("memory_doctor", os.path.join(WORLD, "scripts", "sync", "memory_doctor.py"))
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

GOOD_HOOK = {"type": "command", "command": "echo toy"}
HOOK = {"hooks": {"SessionStart": [{"hooks": [GOOD_HOOK]}]}}


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


_srv = http.server.HTTPServer(("localhost", 0), _Health)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
LIVE = "http://localhost:%d" % _srv.server_address[1]
# A port this suite owns and never listens on: connecting is refused at once, and nothing a developer runs can answer there.
_refused = socket.socket()
_refused.bind(("localhost", 0))
DEAD = "http://localhost:%d" % _refused.getsockname()[1]


def write(p, text):
    with open(p, "w") as f:
        f.write(text)


def _invoke(hook=False):
    """main() once, with its state cleared and colour off. Returns (exit code or the traceback's last line, lines)."""
    md.COLOR = {k: "" for k in md.COLOR}
    md.DIM = md.OFF = ""
    for state in (md.fails, md.warns, md.backlog, md.known_still_failing):
        state.clear()
    sys.argv = ["memory_doctor.py"] + (["--hook"] if hook else [])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            rc = md.main()
        except Exception:
            rc = traceback.format_exc().strip().splitlines()[-1]
    return rc, out.getvalue().splitlines()


def run_full(manifest, trusted=False, hind=None, known=None, hook=False, settings=None):
    """main() against a fresh toy CODEX_HOME; manifest None means no hooks.json at all.
    hind: raw text of the rendered hindsight config (default: the live stand-in as top-level
    server, bank personal, no banks), or False for no file. known: raw text of the known-empty
    file, or None for none. settings: raw text of a toy project's settings.local.json (the
    project opts in to claude-mem-lite), or None for the one default project, which is
    granted hindsight-coding-agents: memory-one-backend FAILs on a world with no project at all, so the cases that
    were about something else would otherwise all fail on it. (Red before the row was written to that rule, with
    the old zero-project harness: `memory-one-backend` FAIL "0 project(s) examined" in each of the 36 cases.)
    Returns (exit code or the traceback's last line, every output line)."""
    home = sandbox.mkdtemp("memdoctor-test-")
    hooks = os.path.join(home, "hooks.json")
    config = os.path.join(home, "config.toml")
    write(config, '[hooks.state]\n"%s:session_start:0:0" = "x"\n' % hooks if trusted else "")
    if manifest is not None:
        write(hooks, manifest)
    hindf = os.path.join(home, "hindsight.json")
    if hind is not False:
        write(hindf, hind if hind is not None
              else json.dumps({"apiUrl": LIVE, "bankId": "personal", "banks": {}}))
    knownf = os.path.join(home, "known.json")
    if known is not None:
        write(knownf, known)
    md.CODEX_HOME, md.CODEX_USER_CONFIG = home, config
    md.HINDSIGHT_RENDERED, md.KNOWN = hindf, knownf
    profs = {"base": {"project_path": os.path.join(home, "base"), "servers": ["hindsight-coding-agents"]}}
    if settings is not None:
        proj = os.path.join(home, "proj")
        os.makedirs(os.path.join(proj, ".claude"))
        write(os.path.join(proj, ".claude", "settings.local.json"), settings)
        profs = {"toy": {"project_path": proj, "plugins_keep": [md.memory.LITE_PLUGIN]}}
    md.lib.projects = lambda skipped=None: profs
    md.known_map.clear()
    return _invoke(hook)


def harness(value):
    """The toy world's config/forge.json with codex_harness set to `value` (a missing key when None)."""
    path = os.path.join(WORLD, "config", "forge.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if value is None:
        doc.pop("codex_harness", None)
    else:
        doc["codex_harness"] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    md.lib.settings.cache_clear()


def run(manifest, trusted=False):
    """Returns (exit code or the traceback's last line, the codex-untrusted lines of the output)."""
    rc, lines = run_full(manifest, trusted)
    return rc, [l for l in lines if "codex-untrusted" in l]


# ------------------------------------------------------------------------------------ memory-one-backend and the --hook budget

class _Stall(http.server.BaseHTTPRequestHandler):
    """A stand-in Hindsight server whose /health answers late or never, by `self.server.mode`: "all" accepts and never answers (the
    sleep is longer than any timeout of the doctor), "slow" answers 2.9 s late (inside a 3 s per-call timeout, so only a budget
    ends a run of them), "trickle" sends the head at once and drips the body one byte a second, "trickle-head" drips the head itself
    (urlopen never returns). The two drips never trip one socket timeout: only a deadline for the complete request ends them."""

    def do_GET(self):
        mode = self.server.mode
        if mode == "all":
            time.sleep(12)
            return
        if mode in ("trickle", "trickle-head"):
            raw = (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 40\r\n\r\n" + b"x" * 40 if mode == "trickle"
                   else b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\nx")
            cut = raw.index(b"\r\n\r\n") + 4 if mode == "trickle" else 0
            try:
                if cut:
                    self.wfile.write(raw[:cut])
                    self.wfile.flush()
                for i in range(cut, len(raw)):
                    self.wfile.write(raw[i:i + 1])
                    self.wfile.flush()
                    time.sleep(1)
            except OSError:                      # the doctor gave up and closed the socket
                pass
            return
        if mode == "slow":
            time.sleep(2.9)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def stall(mode):
    """The URL of a new stand-in server in this mode (it lives as long as the process: its threads are daemons)."""
    srv = http.server.ThreadingHTTPServer(("localhost", 0), _Stall)
    srv.mode = mode
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://localhost:%d" % srv.server_address[1]


def integration(name, value):
    """The toy world's config/forge.json with integrations.<name> set."""
    path = os.path.join(WORLD, "config", "forge.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc.setdefault("integrations", {})[name] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    md.lib.settings.cache_clear()


def mb_world(profs, skipped=()):
    """A toy world of project files: `profs` as lib.projects() returns them (a relative project_path is a directory of the toy
    world, which holds no settings.local.json: nothing outside `root` is read), and `skipped` the project files that could not be read."""
    root = sandbox.mkdtemp("memdoctor-mb-")
    return {"root": root, "skipped": list(skipped), "proj": os.path.join(root, "toy-proj"),
            "profs": {n: dict(p, project_path=os.path.join(root, p["project_path"])) if "project_path" in p else dict(p)
                      for n, p in profs.items()}}


def mb_run(w, hook=False, known=None, hind=False):
    """main() in `w`'s toy world with the hindsight integration on (over the live stand-in, or at the URL `hind` is, or with the
    config `hind` is when it is a dict) or off. Returns (rc or traceback line, lines)."""
    knownf = os.path.join(w["root"], "known.json")
    if known is not None:
        write(knownf, known)
    md.CODEX_HOME = os.path.join(w["root"], "codex")
    integration("codex", False)
    md.HINDSIGHT_RENDERED = os.path.join(w["root"], "hindsight.json")
    integration("hindsight", bool(hind))
    if hind:
        write(md.HINDSIGHT_RENDERED, json.dumps(hind if isinstance(hind, dict) else {
            "apiUrl": hind if isinstance(hind, str) else LIVE, "bankId": "personal", "banks": {}}))
    md.KNOWN, md.HOME = knownf, w["root"]

    def projects(skipped=None):
        if skipped is not None:
            skipped.extend(w["skipped"])
        return w["profs"]
    md.lib.projects = projects
    md.known_map.clear()
    return _invoke(hook)


def has(lines, level, name, text=""):
    return any(l.lstrip().startswith(level) and name in l and text in l for l in lines)


def backend_cases(failures, cases):
    real = (md.KNOWN, md.HINDSIGHT_RENDERED, md.CODEX_HOME, md.HOME, md.HOOK_BUDGET_S)

    def expect(label, ok, rc, lines, names=("memory-", "hindsight", "hook-budget", "project-path")):
        cases[0] += 1
        if not ok:
            failures.append("%s: exit %r; output %r" % (label, rc, [l for l in lines if any(n in l for n in names)]))

    try:
        # ---- memory-one-backend: also with Hindsight off and under --hook. Armed when the checkout uses memory at all (the
        # hindsight integration on, or a project that grants a backend): there, a profile without a backend says so. Mutation:
        # `== 1` to `>= 0` turns the no-backend and two-backend cases red.
        none = {"toy": {"project_path": "toy", "servers": []}}
        HS, LITE = "hindsight-coding-agents", md.memory.LITE_PLUGIN
        for label, hook in (("hindsight on", False), ("--hook, hindsight on", True)):
            rc, lines = mb_run(mb_world(none), hook=hook, hind=True)
            expect("profile without a backend, %s" % label, rc == (0 if hook else 1) and has(
                lines, "FAIL", "memory-backend", "toy has no memory backend"), rc, lines)
        rc, lines = mb_run(mb_world({"toy": {"project_path": "toy", "servers": [HS], "plugins_keep": [LITE]}}), hind=True)
        expect("profile with two backends names them", rc == 1 and has(
            lines, "FAIL", "memory-backend", "toy has 2 memory backends: hindsight-coding-agents, claude-mem-lite"), rc, lines)
        for servers, plugins, backend in (([HS], [], "hindsight-coding-agents"), ([], [LITE], "claude-mem-lite")):
            rc, lines = mb_run(mb_world({"toy": {"project_path": "toy", "servers": servers, "plugins_keep": plugins}}), hind=True)
            # (claude-mem-lite brings its own rows, which FAIL in this toy world: only the memory-backend lines are asserted.)
            expect("profile with one backend: " + backend, rc == (1 if plugins else 0)
                   and not has(lines, "FAIL", "memory-backend") and has(
                       lines, "PASS", "memory-one-backend", "1 project(s) examined, 1 with exactly one backend"), rc, lines)
        # A declaration that a project has no memory is no licence for two backends: it is stale once the project has one, and the
        # two are a FAIL that no declaration excuses.
        rc, lines = mb_run(mb_world({"toy": {"project_path": "toy", "servers": [HS], "plugins_keep": [LITE]}}), hind=True, known=json.dumps(
            {"known": {"toy/memory-backend": {"since": "long ago", "why": "no memory on purpose"}}}))
        expect("a known-empty declaration does not cover two backends", rc == 1 and has(lines, "FAIL", "memory-backend", "2 memory backends")
               and not has(lines, "KNOWN", "memory-backend") and has(lines, "STALE", "toy/memory-backend")
               and has(lines, "FAIL", "memory-one-backend", "1 failing"), rc, lines)
        # A project file that cannot be read has a backend nobody looked at: the row says so and FAILs. Mutation: ignoring `skipped`
        # turns it red. Looking at none is a FAIL too, once armed.
        w = mb_world({"toy": {"project_path": "toy", "servers": [HS]}}, skipped=[("broken.claude.json", "invalid JSON")])
        rc, lines = mb_run(w)
        expect("an unreadable project file is not a pass", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "1 project file(s) could not be read: broken.claude.json"), rc, lines)
        # With nothing switched on, a lone unreadable project file is not a fresh checkout (NOT RUN, exit 0) but a FAIL.
        w = mb_world({}, skipped=[("broken.claude.json", "invalid JSON")])
        rc, lines = mb_run(w)
        expect("an unreadable project file in a checkout with nothing switched on: a FAIL, not NOT RUN", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "1 project file(s) could not be read: broken.claude.json")
            and not any("NOT RUN, NOT ARMED: no memory integration" in l for l in lines), rc, lines)
        rc, lines = mb_run(w, hind=True)
        expect("only unreadable project files: looked at zero, FAIL", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "0 project(s) examined: a check that saw nothing is not a pass; 1 project file(s)"), rc, lines)
        w = mb_world({})
        rc, lines = mb_run(w, hind=True)
        expect("armed and looking at zero projects is a FAIL", rc == 1 and has(lines, "FAIL", "memory-one-backend", "0 project(s)"), rc, lines)
        rc, lines = mb_run(w, hind=True, hook=True)
        expect("armed and looking at zero projects, --hook: said, exit 0", rc == 0 and has(lines, "FAIL", "memory-one-backend"), rc, lines)
        # Not armed: no memory integration on and no project that grants a backend, which is a stranger's fresh checkout with its
        # one starter project. `forge init` runs this doctor on it: NOT RUN, NOT ARMED, exit 0, silent under --hook. Mutation:
        # arming always turns these red.
        NOT_RUN = "memory-one-backend -> NOT RUN, NOT ARMED: no memory integration is on"
        for label, profs in (("a starter project without memory", none), ("no project file", {})):
            w = mb_world(profs)
            rc, lines = mb_run(w)
            expect("not armed, %s: NOT RUN, exit 0" % label, rc == 0 and any(NOT_RUN in l for l in lines)
                   and not has(lines, "PASS", "memory-one-backend") and not has(lines, "FAIL", "memory"), rc, lines)
            rc, lines = mb_run(w, hook=True)
            expect("not armed, %s, --hook: silent, exit 0" % label, rc == 0 and lines == [], rc, lines)
        w = mb_world({"toy": {"project_path": "toy", "servers": []}, "other": {"project_path": "other", "servers": [HS]}})
        rc, lines = mb_run(w)
        expect("armed by another project's backend: the one without says so", rc == 1 and has(
            lines, "FAIL", "memory-backend", "toy has no memory backend") and not any(NOT_RUN in l for l in lines), rc, lines)
        # The row a reader greps must not PASS while a project it examined fails. Known-empty projects are counted apart and do not
        # fail it. Mutation: the PASS condition back to `bool(projects)` turns the first two cases red.
        mixed = {"a": {"project_path": "a", "servers": [HS]}, "b": {"project_path": "b", "servers": []},
                 "c": {"project_path": "c", "servers": [HS]}, "d": {"project_path": "d", "servers": []}}
        w = mb_world(mixed)
        rc, lines = mb_run(w, hind=True)
        expect("the row fails when a project does", rc == 1 and has(lines, "FAIL", "memory-one-backend",
               "4 project(s) examined, 2 with exactly one backend, 2 failing") and not has(lines, "PASS", "memory-one-backend"), rc, lines)
        rc, lines = mb_run(w, hind=True, hook=True)
        expect("the row fails when a project does, --hook: said, exit 0", rc == 0 and has(lines, "FAIL", "memory-one-backend", "2 failing"), rc, lines)
        rc, lines = mb_run(w, hind=True, known=json.dumps({"known": {
            "b/memory-backend": {"since": "long ago", "why": "no memory on purpose"}, "d/memory-backend": {"since": "long ago", "why": "same"}}}))
        expect("two known-empty projects are counted apart: the row passes", rc == 0 and has(
            lines, "PASS", "memory-one-backend", "4 project(s) examined, 2 with exactly one backend, 2 declared in config")
            and not has(lines, "FAIL", "memory"), rc, lines)
        rc, lines = mb_run(w, hind=True, known=json.dumps({"known": {"b/memory-backend": {"since": "long ago", "why": "x"}}}))
        expect("one known-empty and one failing project: the row fails and says both", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "2 with exactly one backend, 1 declared in config") and has(
            lines, "FAIL", "memory-one-backend", "1 failing"), rc, lines)
        w = mb_world({"b": mixed["b"]})
        rc, lines = mb_run(w, hind=True)
        expect("a project alone that has no backend: the row fails", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "1 project(s) examined, 0 with exactly one backend, 1 failing"), rc, lines)
        w = mb_world(none)
        rc, lines = mb_run(w, hind=True, known=json.dumps(
            {"known": {"toy/memory-backend": {"since": "long ago", "why": "no memory on purpose"}}}))
        expect("profile declared without memory is KNOWN", rc == 0 and has(lines, "KNOWN", "memory-backend", "no memory on purpose")
               and not has(lines, "FAIL", "memory-backend"), rc, lines)
        w = mb_world({"toy": {"project_path": "toy", "servers": [HS]}})
        rc, lines = mb_run(w, hind=True, known=json.dumps(
            {"known": {"toy/memory-backend": {"since": "long ago", "why": "no memory on purpose"}}}))
        expect("a declared-empty profile that now has a backend is reported stale", has(lines, "STALE", "toy/memory-backend"), rc, lines)
        # A project file with no project_path: one line that names it, and no settings.local.json read from the directory the doctor
        # happens to run in (here a project with a settings file of its own).
        w = mb_world({"toy": {"plugins_keep": [LITE]}})
        os.makedirs(os.path.join(w["proj"], ".claude"))
        write(os.path.join(w["proj"], ".claude", "settings.local.json"), "{}")
        here = os.getcwd()
        os.chdir(w["proj"])
        try:
            rc, lines = mb_run(w)
        finally:
            os.chdir(here)
        expect("a claude-mem-lite project without project_path: one line that names it, no settings read", rc == 1
               and has(lines, "FAIL", "project-path", "toy") and not has(lines, "", "settings-local") and not has(lines, "", "lite-"), rc, lines)

        # ---- under --hook the whole run draws from one budget (HOOK_BUDGET_S), a call is bounded as a whole request and no call is
        # made to a server that did not answer one before. Hindsight's probes are what uses it. Stand-ins that answer /health late or
        # never (_Stall): "all" and the two drips end by the per-call timeout (HOOK_CALL_S, 3 s), not by the 5 s of /health nor by the drip.
        w = mb_world({"toy": {"project_path": "toy", "servers": [HS]}})
        for mode in ("all", "trickle", "trickle-head"):
            t0 = time.time()
            rc, lines = mb_run(w, hook=True, hind=stall(mode))
            took = time.time() - t0
            expect("--hook, Hindsight server %s: ends in under 4.5 s (took %.1f s) and prints its FAIL" % (mode, took),
                   rc == 0 and took < 4.5 and has(lines, "FAIL", "hindsight-server", "does not answer /health"), rc, lines)
        # A server that eats the budget leaves the next probes one WARN line that says they were not run (the budget is cut to 3 s
        # here: the first server answers 2.9 s late and leaves 0.1 s).
        md.HOOK_BUDGET_S = 3.0
        t0 = time.time()
        rc, lines = mb_run(w, hook=True, hind={"apiUrl": stall("slow"), "bankId": "personal", "banks": {"b": {"apiUrl": stall("slow")}}})
        took = time.time() - t0
        md.HOOK_BUDGET_S = real[4]
        expect("--hook, a Hindsight server that eats the budget: the next probe is said not run (took %.1f s)" % took,
               rc == 0 and took < 6 and has(lines, "WARN", "hook-budget", "not run") and has(lines, "WARN", "hook-budget", "hindsight-server"),
               rc, lines)
        rc, lines = mb_run(w, hook=True, hind=stall("slow"))
        expect("--hook, a server that answers inside its call timeout: silent (the budget line is only for a spent budget)",
               rc == 0 and lines == [], rc, lines)
        # A silent server does not silence another host: the second probe is made and fails by itself.
        rc, lines = mb_run(w, hook=True, hind={"apiUrl": stall("all"), "bankId": "personal", "banks": {"b": {"apiUrl": DEAD}}})
        expect("--hook, a silent server does not silence another host: the probe is made and fails by itself",
               rc == 0 and has(lines, "FAIL", "hindsight-server", "does not answer /health")
               and not any("hindsight-server" in l and "not asked" in l for l in lines), rc, lines)
        # The full run keeps its long timeouts: a server that is merely slow (2.9 s) is judged healthy outside --hook.
        rc, lines = mb_run(w, hind=stall("slow"))
        expect("full run, slow server: still healthy (the long timeouts stay)", rc == 0 and has(lines, "PASS", "hindsight-server"), rc, lines)
    finally:
        md.KNOWN, md.HINDSIGHT_RENDERED, md.CODEX_HOME, md.HOME, md.HOOK_BUDGET_S = real
        for name in ("hindsight", "codex"):
            integration(name, True)

def main():
    failures = []

    for bad in ("{bad", "null", "[1]"):
        rc, lines = run(bad)
        text = " | ".join(lines)
        if (rc != 1 or "every registered hook is trusted" in text
                or not any(l.lstrip().startswith("FAIL") and "hooks.json unreadable" in l for l in lines)):
            failures.append("%r: exit %s, output %r" % (bad, rc, text))

    rc, lines = run(None)
    if rc != 0 or not any(l.lstrip().startswith("PASS") and "0 examined" in l for l in lines):
        failures.append("missing hooks.json: exit %s, output %r" % (rc, " | ".join(lines)))

    # With `codex_harness` false or absent Codex gets no hook from forge, so a config with no hook trust
    # record is the normal state, not a finding: a PASS line that says 0 examined, not a WARN. Red before:
    # "no trust records: exit 0, output ['  WARN  codex-trust        no hook trust records in <config.toml>',
    # ...]". The control is the case below: a trust record whose manifest is there still PASSes.
    for label, value in (("codex_harness false", False), ("codex_harness absent", None), ("codex_harness \"yes\"", "yes")):
        harness(value)
        rc, lines = run_full(None)
        if rc != 0 or any("codex-trust" in l and l.lstrip().startswith("WARN") for l in lines) \
                or not any("codex-trust" in l and l.lstrip().startswith("PASS") and "0 examined" in l for l in lines):
            failures.append("no trust records, %s: exit %s, output %r" % (label, rc, [l for l in lines if "codex-trust" in l]))
    # With it true forge registers Codex hooks again, and Codex runs one only once it is trusted, so no
    # trust record is a WARN again (exit 0: a warning does not fail). Red before the switch reached this
    # line: "no trust records, codex_harness true: exit 0, output ['  PASS  codex-trust        no hook trust
    # records in <config.toml> (0 examined)', ...]". Negative control: the WARN made unreachable (the
    # branch always a PASS) reproduces that failure.
    harness(True)
    rc, lines = run_full(None)
    if rc != 0 or not any("codex-trust" in l and l.lstrip().startswith("WARN") and "no hook trust records" in l for l in lines) \
            or any("codex-trust" in l and l.lstrip().startswith("PASS") for l in lines):
        failures.append("no trust records, codex_harness true: exit %s, output %r" % (rc, [l for l in lines if "codex-trust" in l]))

    rc, lines = run(json.dumps(HOOK), trusted=True)
    if rc != 0 or not any(l.lstrip().startswith("PASS") and "every registered hook is trusted (1 examined)"
                          in l for l in lines):
        failures.append("one trusted hook: exit %s, output %r" % (rc, " | ".join(lines)))

    # With `codex_harness` true a hook in the manifest with no trust record WARNs (control: it is not "never
    # warn"; set explicitly here, the case used to lean on the harness(True) left by the block above).
    harness(True)
    rc, lines = run(json.dumps(HOOK))
    want = ("1 hook(s) registered with no trust record, so they do not fire until the next "
            "Codex session approves them: SessionStart echo toy")
    if rc != 0 or not any(l.lstrip().startswith("WARN") and want in l for l in lines):
        failures.append("one untrusted hook: exit %s, output %r" % (rc, " | ".join(lines)))

    # With `codex_harness` false, absent or not a boolean forge registers no Codex hook, so a hook in the
    # manifest with no trust record is another program's: a PASS line with both counts, not a WARN. Red before:
    # "untrusted hook, codex_harness false: exit 0, output ['  WARN  codex-untrusted   1 hook(s) registered with
    # no trust record, so they do not fire until the next Codex session approves them: SessionStart echo toy']".
    # Negative control: the new condition removed (the branch always a WARN) reproduces that failure. An
    # unreadable manifest still FAILs whatever the switch says (the bad-manifest cases below, run with each value).
    for label, value in (("codex_harness false", False), ("codex_harness absent", None), ("codex_harness \"yes\"", "yes")):
        harness(value)
        rc, lines = run(json.dumps(HOOK))
        if rc != 0 or any(l.lstrip().startswith("WARN") for l in lines) or not any(
                l.lstrip().startswith("PASS") and "1 hook(s) registered with no trust record" in l and "(1 examined)" in l
                for l in lines):
            failures.append("untrusted hook, %s: exit %s, output %r" % (label, rc, " | ".join(lines)))
        rc, lines = run("{bad")
        if rc != 1 or not any(l.lstrip().startswith("FAIL") and "hooks.json unreadable" in l for l in lines):
            failures.append("unreadable manifest, %s: exit %s, output %r" % (label, rc, " | ".join(lines)))
    harness(True)

    cases = [6]

    def both(label, fail_name, fail_text, **kw):
        """The same input twice. A normal run exits 1 with the FAIL line. --hook exits 0, never
        a traceback, and prints only the summary line and the FAIL/WARN lines."""
        cases[0] += 2
        rc, lines = run_full(**kw)
        if rc != 1 or not any(l.lstrip().startswith("FAIL") and fail_name in l and fail_text in l
                              for l in lines):
            failures.append("%s: exit %r, wanted exit 1 and FAIL %s %r; output %r"
                            % (label, rc, fail_name, fail_text, lines[-4:]))
        rc, lines = run_full(hook=True, **kw)
        if rc != 0 or not lines or not lines[0].startswith("memory_doctor:") \
                or any(not l.startswith(("memory_doctor:", "FAIL", "WARN")) for l in lines):
            failures.append("%s --hook: exit %r, output %r" % (label, rc, lines))

    mixed = {"hooks": {"SessionStart": [{"hooks": ["x", GOOD_HOOK]}]}}
    bad_shapes = {
        "hooks is a list": {"hooks": ["x"]},
        "event is a string": {"hooks": {"SessionStart": "x"}},
        "group is a string": {"hooks": {"SessionStart": ["x"]}},
        "group hooks is a string": {"hooks": {"SessionStart": [{"hooks": "x"}]}},
        "hook is a string": {"hooks": {"SessionStart": [{"hooks": ["x"]}]}},
        "one bad entry beside a good one": mixed,
    }
    for label, doc in bad_shapes.items():
        both("manifest, " + label, "codex-untrusted", "hooks.json unreadable",
             manifest=json.dumps(doc))

    # The trust key counts the ORIGINAL positions: the good hook sits at index 1 of its group.
    cases[0] += 1
    try:
        entries, malformed = md.lib.hook_entries(mixed)
        if [(e, g, h) for e, g, h, _ in entries] != [("SessionStart", 0, 1)] or malformed != 1:
            failures.append("hook_entries: %r, %r malformed" % (entries, malformed))
    except Exception as e:                                    # noqa: BLE001 - report it
        failures.append("hook_entries: %s: %s" % (type(e).__name__, e))

    for raw in ("[1]", "{bad"):
        both("rendered config " + raw, "hindsight-config", "unreadable", manifest=None, hind=raw)
    cases[0] += 1
    rc, lines = run_full(None, hind=False)
    if rc != 1 or not any(l.lstrip().startswith("FAIL") and "hindsight-config" in l and "missing" in l
                          for l in lines):
        failures.append("rendered config missing: exit %r, output %r" % (rc, lines))
    cases[0] += 1
    rc, lines = run_full(None, hind=json.dumps({"apiUrl": LIVE, "bankId": "personal", "banks": [1]}))
    if rc != 0 or not any("PASS" in l and "hindsight-server" in l for l in lines):
        failures.append("banks is a list: exit %r, output %r" % (rc, lines))

    for raw in ("[1]", '{"known": [1]}'):
        both("known-empty " + raw, "known-empty", "unreadable", manifest=None, known=raw)
    both("truncated settings.local.json", "settings-local", "unreadable", manifest=None,
         settings='{"env": {')

    both("top-level apiUrl dead, banks {}", "hindsight-server", "personal", manifest=None,
         hind=json.dumps({"apiUrl": DEAD, "bankId": "personal", "banks": {}}))
    cases[0] += 1
    rc, lines = run_full(None)
    if rc != 0 or not any("PASS" in l and "hindsight-server" in l and "serves personal" in l for l in lines):
        failures.append("top-level apiUrl live: exit %r, output %r" % (rc, lines))

    # A store whose database exists with zero rows says "0 observations", and one with a row is the
    # control that says "1 observations" and PASSes. Seen failing on 29b885e, the
    # zero-row detail was a bare "0": "FAIL store with 0 rows: wanted FAIL lite-store-has-rows
    # '0 observations'; output ['  FAIL  lite-store-has-rows 0', 'FAIL  toy/lite-store-has-rows: 0']".
    # LITE_ROOT points at a toy directory, because the
    # real one is under the checkout's data/.
    import sqlite3
    real_root = md.memory.LITE_ROOT
    try:
        for rows, verdict in ((0, "FAIL"), (1, "PASS")):
            cases[0] += 1
            md.memory.LITE_ROOT = os.path.join(sandbox.mkdtemp("memdoctor-lite-"), "lite")
            store = os.path.join(md.memory.LITE_ROOT, "toy")
            os.makedirs(store)
            con = sqlite3.connect(os.path.join(store, "claude-mem-lite.db"))
            con.execute("create table observations (project text)")
            con.executemany("insert into observations values ('x')", [()] * rows)
            con.commit()
            con.close()
            toy = json.dumps({"env": {"CLAUDE_MEM_DIR": store},
                              "enabledPlugins": {md.memory.LITE_PLUGIN: True}})
            rc, lines = run_full(None, settings=toy)
            want = "%d observations" % rows
            if not any(l.lstrip().startswith(verdict) and "lite-store-has-rows" in l and want in l
                       for l in lines):
                failures.append("store with %d rows: wanted %s lite-store-has-rows %r; output %r"
                                % (rows, verdict, want, [l for l in lines if "lite-store" in l]))
    finally:
        md.memory.LITE_ROOT = real_root

    backend_cases(failures, cases)

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over %d cases" % (len(failures), cases[0]))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
