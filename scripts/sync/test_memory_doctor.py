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

Part 7.1, unit U3 (the MemPalace rows and memory-one-backend) is driven by mempalace_cases() below, against a fake hub:
a standard-library HTTP server on a free loopback port that answers /healthz, /statusz and the read `tools/call`s
(mempalace_list_wings, mempalace_list_drawers, mempalace_search) and records, then fails the run, on any other tool. The
fake carries its own list of read tools, not the code's, so the guard cannot agree with a wrong list by construction.
`mempalace` is a one-line script on a PATH that holds only its own directory (a system dir behind it would find the
real one, ORDERS 10).

Control record. Red against the baseline (14a340f, memory_doctor.py with no MemPalace row), 67 of the 105 cases that existed at
that commit failed, each
with the shape "healthy: exit 0; output []", "on, hub stopped: exit 0; output []", "palace_path missing: exit 0; output []",
"profile without a backend, integration on: exit 0; output []", "looking at zero profiles is a FAIL: exit 0; output []" and
"hub_call: module 'memory_doctor' has no attribute 'hub_call'". Each mutation below, applied to memory_doctor.py alone, was
seen to turn the named case red (and only the cases named, or a superset that follows from the same line):
  - version comparison dropped          "cli at another version: exit 0; output [... PASS mempalace-cli installed 3.11.0 ...]"
  - /healthz asked as /health           "healthy: exit 1" and every search case (the pinned hub answers /healthz only)
  - search removed from the hub row     "healthz ok, search http500|rpcerror|toolerror|empty: exit 0" (the plan's control)
  - MEMPALACE_PALACE_PATH ignored       "MEMPALACE_PALACE_PATH beats config.json: exit 1"
  - `.count` requirement removed        "backup without .count: exit 0; output [... PASS mempalace-backup ...]"
  - transcript condition removed        "stale wing, transcript older than the window: exit 0" (the parked-project cases)
  - transcript window removed           "stale wing, transcript older than the window: exit 0"
  - sibling directory prefix            "a sibling project's transcript does not: exit 0"
  - `== 1` to `>= 0` for the backend    "profile without a backend, integration on|off|--hook, off: exit 0" and the three-backend case
  - zero examined passes                "only unreadable project files: looked at zero, FAIL: exit 0; output [... PASS memory-one-backend 0 project(s) examined ...]"
  - always armed                        "not armed, a starter project without memory: NOT RUN, exit 0: exit 1" and, outside this file,
                                        tests/test_fresh_install.py (8 cases) and tests/test_integration_sites.py
  - unreadable project files ignored    "an unreadable project file is not a pass: exit 0"
  - write-tool guard removed            "hub_call let a write tool through", "a write tool reached the hub"
  - palace mismatch check removed       "hub serves another palace than the doctor resolves: exit 0"
  - integrity `ok` not required         "integrity not ok: exit 1" (no "3 error(s)" line)
  - row marker ignored                  "a foreign hook in the event is not the row: exit 0"
  - wing read under --hook              "--hook: the rows are checked, the wing is not read (no list_wings call)"
  - a stopped hub passes                "on, hub stopped: exit 1" (no FAIL mempalace-hub line)
"""
import contextlib
import datetime
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback

sys.dont_write_bytecode = True
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


_srv = http.server.HTTPServer(("127.0.0.1", 0), _Health)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
LIVE = "http://127.0.0.1:%d" % _srv.server_address[1]
DEAD = "http://127.0.0.1:9"     # the discard port: connection refused at once


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


# ------------------------------------------------------------------------------------------------ MemPalace (7.1 U3)

# What the fake hub accepts. Its own list, not md.READ_TOOLS: a doctor that learned a wrong list must still be caught.
FAKE_READ_TOOLS = {"mempalace_list_drawers", "mempalace_list_wings", "mempalace_search"}
HUB = {}


def hub_reset(**kw):
    HUB.clear()
    HUB.update(health="/healthz", statusz=None, drawers=[], search="ok", since_no_total=False, log=[], violations=[],
               hang=None, total_bool=False, preview=None)
    HUB.update(kw)


def _tool_answer(value):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(value)}]}}


def _since(args):
    got = datetime.datetime.fromisoformat(args["since"])
    return got if got.tzinfo else got.replace(tzinfo=datetime.timezone.utc)


class _Hub(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except OSError:                          # the doctor gave up on a stalled call and closed the socket
            pass

    def _stalled(self, is_tool):
        """True when this request is to be left unanswered. hang: "all" (healthz, statusz and tools never answer),
        "tools" (only the tools/call), "slow" (every call answers, 2.9 s late: just inside a 3 s per-call timeout)."""
        mode = HUB["hang"]
        if mode == "all" or (mode == "tools" and is_tool):
            time.sleep(12)                       # longer than any timeout of the doctor, and the answer never comes
            return True
        if mode == "slow":
            time.sleep(2.9)
        return False

    def do_GET(self):
        HUB["log"].append(("GET", self.path))
        if self._stalled(False):
            return
        if self.path == HUB["health"]:
            self._send(200, "ok\n", "text/plain")
        elif self.path == "/statusz" and HUB["statusz"] is not None:
            self._send(200, HUB["statusz"])
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path != "/mcp" or req.get("method") != "tools/call":
            HUB["violations"].append("a call that is not tools/call on /mcp: %s %r" % (self.path, req.get("method")))
            return self._send(400, {"error": "unsupported"})
        tool, args = req["params"]["name"], req["params"].get("arguments") or {}
        HUB["log"].append(("tool", tool))
        if self._stalled(True):
            return
        if tool not in FAKE_READ_TOOLS:
            HUB["violations"].append(tool)
            return self._send(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "refused: " + tool}})
        drawers = [d for d in HUB["drawers"] if not args.get("wing") or d["wing"] == args["wing"]]
        if tool == "mempalace_list_wings":
            if HUB.get("wings_bad"):
                return self._send(200, _tool_answer([1]))
            wings = {}
            for d in HUB["drawers"]:
                wings[d["wing"]] = wings.get(d["wing"], 0) + 1
            if HUB["total_bool"]:
                wings = {k: True for k in wings}
            return self._send(200, _tool_answer({"wings": wings}))
        if tool == "mempalace_list_drawers":
            if "since" in args:
                if HUB["since_no_total"]:
                    return self._send(200, _tool_answer({"drawers": []}))
                drawers = [d for d in drawers if d["filed_at"] >= _since(args)]
            shown = [{"drawer_id": "d%d" % i, "wing": d["wing"],
                      "content_preview": d["text"][:100] + "..." if HUB["preview"] is None else HUB["preview"]}
                     for i, d in enumerate(drawers[: args.get("limit", 10)])]
            return self._send(200, _tool_answer({"drawers": shown, "total": True if HUB["total_bool"] else len(drawers),
                                                 "count": len(shown)}))
        mode = HUB["search"]                                                  # mempalace_search
        if mode == "http500":
            return self._send(500, "boom", "text/plain")
        if mode == "rpcerror":
            return self._send(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "model not loaded"}})
        if mode == "toolerror":
            return self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "embedder failed"}]}})
        if mode == "empty":
            return self._send(200, _tool_answer({"results": []}))
        unrelated = {"text": "UNRELATED", "source_file": "s.jsonl", "distance": 0.1}
        if mode in ("unrelated", "nulls", "emptyobj", "notext"):          # a non-empty list that is not the drawer
            junk = {"unrelated": [unrelated], "nulls": [None], "emptyobj": [{}], "notext": [{"text": 5, "distance": 0.1}]}[mode]
            return self._send(200, _tool_answer({"results": junk}))
        hits = [{"text": d["text"], "source_file": "s.jsonl", "distance": 0.1} for d in drawers if args["query"] in d["text"]]
        if mode == "late":                                                   # the drawer is there, behind an unrelated hit
            hits = [unrelated] + hits
        if mode == "badbeside":                                              # the drawer is there, beside a malformed entry
            hits = hits + [None]
        return self._send(200, _tool_answer({"results": hits[: args.get("limit", 5)]}))

    def log_message(self, *a):
        pass


_hub_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hub)
threading.Thread(target=_hub_srv.serve_forever, daemon=True).start()
FAKE_HUB = "http://127.0.0.1:%d" % _hub_srv.server_address[1]

NOW = datetime.datetime.now(datetime.timezone.utc)
HOOK_ROWS = (("Stop", "mempal-stop-hook.sh"), ("SessionEnd", "mempal-session-end-hook.sh"),
             ("PreCompact", "mempal-precompact-hook.sh"))
OFF_LINE = "mempalace checks -> NOT RUN, NOT ARMED: mempalace is off in config/forge.json"


def integration(name, value):
    """The toy world's config/forge.json with integrations.<name> set."""
    path = os.path.join(WORLD, "config", "forge.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc.setdefault("integrations", {})[name] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    md.lib.settings.cache_clear()


@contextlib.contextmanager
def environ(**kw):
    """os.environ with exactly the MemPalace variables in kw (and no XDG_CONFIG_HOME unless given), then as it was."""
    names = ("MEMPALACE_CONFIG_DIR", "MEMPALACE_PALACE_PATH", "MEMPALACE_PALACE", "MEMPAL_PALACE_PATH",
             "XDG_CONFIG_HOME", "PATH")
    old = {n: os.environ.get(n) for n in names}
    for n in names:
        os.environ.pop(n, None)
    os.environ.update(kw)
    try:
        yield
    finally:
        for n, v in old.items():
            os.environ.pop(n, None)
            if v is not None:
                os.environ[n] = v


def mp_world(**o):
    """A toy MemPalace install and one toy project, from keyword options (each default is the healthy case):
    cli (False: no `mempalace` on PATH), cli_version, cli_sleep (seconds `--version` takes), palace (False: no directory), db (False: no database file),
    palace_path (what config.json says), hub (the registry's URL base; None: no registry entry), pinned (toolchain
    version; None: no entry), backup_age_h (default 1; None: no backup), count (False: no .count), rows (events kept),
    transcript_age_days (None: none), proj_name (the project directory's name), drawers (list of (age in days, text)), statusz (override), hub_opts."""
    root = sandbox.mkdtemp("memdoctor-mp-")
    w = {"root": root, "proj": os.path.join(root, o.get("proj_name", "toy-proj")), "bin": os.path.join(root, "bin"),
         "palace": os.path.join(root, "palace"), "cfg": os.path.join(root, "cfg"),
         "backups": os.path.join(root, "backups"), "claude": os.path.join(root, "claude-projects")}
    os.makedirs(w["bin"])
    if o.get("cli", True):
        if o.get("cli_sleep"):                   # `mempalace --version` that takes this long (a `sleep` linked in: PATH holds only bin)
            os.symlink(shutil.which("sleep"), os.path.join(w["bin"], "sleep"))
        write(os.path.join(w["bin"], "mempalace"), "#!/bin/sh\n%secho 'MemPalace %s'\n"
              % ("sleep %d\n" % o["cli_sleep"] if o.get("cli_sleep") else "", o.get("cli_version", "3.12.0")))
        os.chmod(os.path.join(w["bin"], "mempalace"), 0o755)
    if o.get("palace", True):
        os.makedirs(w["palace"])
        if o.get("db", True):
            write(os.path.join(w["palace"], "chroma.sqlite3"), "SQLite format 3")
    os.makedirs(w["cfg"])
    write(os.path.join(w["cfg"], "config.json"), json.dumps({"palace_path": o.get("palace_path", w["palace"])}))
    os.makedirs(w["backups"])
    if o.get("backup_age_h", 1) is not None:
        arch = os.path.join(w["backups"], "mempalace-20261118T043000Z.tar.zst")
        write(arch, "archive")
        if o.get("count", True):
            write(arch + ".count", "100\n")
        stamp = time.time() - o.get("backup_age_h", 1) * 3600
        os.utime(arch, (stamp, stamp))
    os.makedirs(os.path.join(w["proj"], ".claude"))
    kept = o.get("rows", [e for e, _ in HOOK_ROWS])
    hooks = {e: [{"hooks": [{"type": "command", "command": "/srv/forge/hooks/mempalace/" + s}]}]
             for e, s in HOOK_ROWS if e in kept}
    write(os.path.join(w["proj"], ".claude", "settings.local.json"), o.get("settings", json.dumps({"hooks": hooks})))
    enc = re.sub(r"[^A-Za-z0-9]", "-", w["proj"])
    for name, age in o.get("transcripts", ([(enc, o["transcript_age_days"])] if o.get("transcript_age_days") is not None else [])):
        d = os.path.join(w["claude"], name)
        os.makedirs(d, exist_ok=True)
        write(os.path.join(d, "s.jsonl"), "{}\n")
        stamp = time.time() - age * 86400
        os.utime(os.path.join(d, "s.jsonl"), (stamp, stamp))
    os.makedirs(w["claude"], exist_ok=True)
    hub_reset(drawers=[{"wing": "toy_proj", "text": "the deploy key rotates on thursdays " + "x" * 200 + str(i),
                        "filed_at": NOW - datetime.timedelta(days=age)} for i, (age, _) in enumerate(o.get("drawers", [(1, "")]))],
              statusz=o.get("statusz", {"ok": True, "server": {"version": "3.12.0"}, "palace": {"backend": "chroma", "sqlite_integrity": {
                  "checked": True, "ok": True, "palace": w["palace"], "error_count": 0, "errors": []}}}),
              **o.get("hub_opts", {}))
    reg = {"servers": {}}
    if o.get("hub", FAKE_HUB) is not None:
        reg["servers"]["mempalace"] = {"type": "http", "url": o.get("hub", FAKE_HUB) + "/mcp"}
    write(os.path.join(WORLD, "config", "mcp-registry.json"), json.dumps(reg))
    tools = [{"name": "npm:pnpm", "version": "10.32.1", "why": "toy"}]
    if o.get("pinned", "3.12.0") is not None:
        tools.append({"name": "pipx:mempalace", "version": o.get("pinned", "3.12.0"), "why": "toy", "when": {"integration": "mempalace"}})
    write(os.path.join(WORLD, "config", "toolchain.json"), json.dumps({"tools": tools}))
    w["profs"] = o.get("profs", {"toy": {"project_path": w["proj"], "servers": ["mempalace"]}})
    return w


def mp_run(w, hook=False, known=None, env=None, on=True, hind=False):
    """main() with the mempalace integration on (or off) and, with `hind`, the hindsight one on over the live stand-in, in
    `w`'s toy world. Returns (rc or traceback line, lines)."""
    knownf = os.path.join(w["root"], "known.json")
    if known is not None:
        write(knownf, known)
    md.CODEX_HOME = os.path.join(w["root"], "codex")
    integration("codex", False)
    integration("mempalace", on)
    md.HINDSIGHT_RENDERED = os.path.join(w["root"], "hindsight.json")
    integration("hindsight", hind)
    if hind:
        write(md.HINDSIGHT_RENDERED, json.dumps({"apiUrl": LIVE, "bankId": "personal", "banks": {}}))
    md.KNOWN, md.BACKUPS, md.CLAUDE_PROJECTS, md.HOME = knownf, w["backups"], w["claude"], w["root"]
    def projects(skipped=None):
        if skipped is not None:
            skipped.extend(w.get("skipped", []))
        return w["profs"]
    md.lib.projects = projects
    md.known_map.clear()
    with environ(**(env if env is not None else {"MEMPALACE_CONFIG_DIR": w["cfg"], "PATH": w["bin"]})):
        return _invoke(hook)


def has(lines, level, name, text=""):
    return any(l.lstrip().startswith(level) and name in l and text in l for l in lines)


def mempalace_cases(failures, cases):
    real_home = md.HOME
    real_paths = (md.KNOWN, getattr(md, "BACKUPS", None), getattr(md, "CLAUDE_PROJECTS", None), md.HINDSIGHT_RENDERED, md.CODEX_HOME)

    def expect(label, ok, rc, lines, names=("mempalace", "memory-")):
        cases[0] += 1
        if not ok:
            failures.append("%s: exit %r; output %r" % (label, rc, [l for l in lines if any(n in l for n in names)]))

    def case(label, w=None, want=None, forbid=(), rc_is=None, **run):
        """Run `w` and assert every (level, row, text) of `want` is there, no (level, row) of `forbid` is, and the exit
        code is rc_is (default: 1 when a FAIL is wanted, else 0). The fake hub must have seen no tool that writes."""
        w = w or mp_world()
        rc, lines = mp_run(w, **run)
        want, ok = want or [], True
        for level, name, *text in want:
            ok = ok and has(lines, level, name, text[0] if text else "")
        for level, name in forbid:
            ok = ok and not has(lines, level, name)
        wanted_rc = rc_is if rc_is is not None else (1 if any(x[0] == "FAIL" for x in want) and not run.get("hook") else 0)
        ok = ok and rc == wanted_rc and not HUB["violations"]
        expect(label, ok, rc, lines)
        return rc, lines

    try:
        # ---- the healthy world: every row PASSes and says how much it looked at. Red against the baseline (no
        # mempalace row at all): "healthy: exit 0; output []". Control for the fake's guard further down.
        w = mp_world(backup_age_h=1)
        case("healthy", w, [("PASS", "mempalace-cli", "3.12.0"), ("PASS", "mempalace-hub", "1 result"),
                            ("PASS", "mempalace-palace", "chroma.sqlite3"), ("PASS", "mempalace-palace", "integrity ok"),
                            ("PASS", "mempalace-backup", "1.0 h old"), ("PASS", "mempalace-rows", "3 of 3"),
                            ("PASS", "mempalace-wing", "toy_proj"),
                            ("PASS", "memory-one-backend", "1 project(s) examined, 1 with exactly one backend")],
             forbid=[("FAIL", ""), ("WARN", "")])

        # ---- off: one NOT RUN line, no row, no call to the hub; memory-one-backend still runs. And on with the hub
        # stopped is a FAIL, never the NOT RUN line: a hub that is down is not an integration that is off.
        # Red against the baseline: the NOT RUN line is not printed ("off: exit 0; output []").
        w = mp_world(backup_age_h=1)
        rc, lines = case("off", w, [("PASS", "memory-one-backend")], forbid=[("FAIL", "mempalace"), ("PASS", "mempalace")], on=False)
        expect("off: the NOT RUN line, once, and no call to the hub",
               lines.count("  " + OFF_LINE) == 1 and not HUB["log"], rc, lines)
        case("on, hub stopped", mp_world(backup_age_h=1, hub="http://127.0.0.1:9"),
             [("FAIL", "mempalace-hub", "systemctl --user enable --now mempalace-hub")], forbid=[("PASS", "mempalace-hub")])
        rc, lines = mp_run(mp_world(backup_age_h=1, hub="http://127.0.0.1:9"))
        expect("on, hub stopped: no NOT RUN line for mempalace", not any(OFF_LINE in l for l in lines), rc, lines)

        # ---- mempalace-cli. Red: no row. Mutation: dropping the version comparison turns the second case red
        # ("cli at another version: exit 0; output [... PASS mempalace-cli ...]").
        case("cli not on PATH", mp_world(cli=False), [("FAIL", "mempalace-cli", "forge toolchain --fix, then a new shell")])
        case("cli at another version", mp_world(cli_version="3.11.0"),
             [("FAIL", "mempalace-cli", "3.11.0"), ("FAIL", "mempalace-cli", "pins 3.12.0")])
        case("toolchain has no mempalace entry", mp_world(pinned=None), [("FAIL", "mempalace-cli", "pipx:mempalace")])

        # ---- mempalace-hub. Plan's control: /health says ok and the search fails -> FAIL; removing the search turns
        # the case green (that is the red: "healthz ok, search fails: exit 0"). The fake answers /healthz only, as the
        # pinned 3.12.0 does (U1 (h): /health is 404): a doctor that asks /health FAILs the healthy case above.
        for mode in ("http500", "rpcerror", "toolerror", "empty"):
            case("healthz ok, search %s" % mode, mp_world(hub_opts={"search": mode}),
                 [("FAIL", "mempalace-hub", "search")], forbid=[("PASS", "mempalace-hub")])
        case("palace with no drawer: nothing to search, said so", mp_world(drawers=[]),
             [("PASS", "mempalace-hub", "0 drawers"), ("FAIL", "mempalace-wing", "0 drawers")])
        case("hub answers /health only", mp_world(hub_opts={"health": "/health"}),
             [("FAIL", "mempalace-hub", "/healthz")])
        # The palace row says why it could not read the integrity too (mutation: that line removed, the suite stayed green).
        case("no registry entry", mp_world(hub=None), [("FAIL", "mempalace-hub", "mcp-registry.json"),
                                                       ("FAIL", "mempalace-palace", "integrity not read")])
        # Fix round (review of the pull request, findings 4 and 8). The search must find the drawer the hub itself listed; any
        # non-empty list used to pass. Red on 5078c50: "search returns an unrelated result: exit 0; output [... PASS
        # mempalace-hub ... found 1 result(s) ...]" (and the same for [None], [{}] and a result without text).
        for mode in ("unrelated", "nulls", "emptyobj", "notext", "badbeside"):
            case("search returns %s: not the drawer" % mode, mp_world(hub_opts={"search": mode}),
                 [("FAIL", "mempalace-hub", "search")], forbid=[("PASS", "mempalace-hub")])
        case("search returns the drawer behind an unrelated hit: found", mp_world(hub_opts={"search": "late"}),
             [("PASS", "mempalace-hub", "2 result(s)")])
        # Mutation: the empty-preview FAIL removed -> "list_drawers gives no text: exit 0; output [... PASS mempalace-hub ...]"
        # (an empty query is searched for and any hit passes). `isinstance(total, bool)` removed -> "total true: exit 0".
        for preview in ("", "..."):
            case("list_drawers gives no text (%r) to search for" % preview, mp_world(hub_opts={"preview": preview}),
                 [("FAIL", "mempalace-hub", "no text to search for")], forbid=[("PASS", "mempalace-hub")])
        rc, lines = case("list_drawers total is true, not a count", mp_world(hub_opts={"total_bool": True}),
                         [("FAIL", "mempalace-hub", "no drawer count"), ("FAIL", "mempalace-wing", "0 drawers")],
                         forbid=[("PASS", "mempalace-hub")])
        case("registry url is not http", mp_world(hub="file:///etc"), [("FAIL", "mempalace-hub", "no http(s) url")])
        # Scheme and host are checked apart: `ftp://h/` has a host, `http:///` has a scheme (the review's surviving mutants).
        case("registry url is ftp: the scheme guard", mp_world(hub="ftp://h"), [("FAIL", "mempalace-hub", "no http(s) url")])
        case("registry url has no host: the host guard", mp_world(hub="http://"), [("FAIL", "mempalace-hub", "no http(s) url")])

        # ---- mempalace-palace. Red: no row ("palace_path that does not exist: exit 0; output []").
        w = mp_world(palace=False)
        case("palace_path missing", w, [("FAIL", "mempalace-palace", w["palace"])])
        w = mp_world(db=False)
        case("palace without its database", w, [("FAIL", "mempalace-palace", "chroma.sqlite3")])
        case("integrity not ok", mp_world(statusz={"palace": {"sqlite_integrity": {
            "checked": True, "ok": False, "palace": "x", "error_count": 3, "errors": ["row 4 missing"]}}}),
             [("FAIL", "mempalace-palace", "3 error(s)")])
        case("integrity not checked", mp_world(statusz={"palace": {"sqlite_integrity": {"checked": False, "ok": True}}}),
             [("FAIL", "mempalace-palace", "not checked")])
        # Finding 2. /statusz that does not name its palace used to PASS "hub serves <the doctor's own path>". Red on 5078c50:
        # "statusz names no palace: exit 0; output [... PASS mempalace-palace SQLite integrity ok (0 errors, hub serves <path>)]".
        for label, named in (("absent", None), ("not a string", 5)):
            block = {"checked": True, "ok": True, "error_count": 0, "errors": []}
            if named is not None:
                block["palace"] = named
            rc, lines = case("statusz names no palace (%s): a FAIL that says so" % label,
                             mp_world(statusz={"palace": {"sqlite_integrity": block}}),
                             [("FAIL", "mempalace-palace", "does not name its palace")])
            expect("statusz names no palace (%s): no PASS that claims the hub serves a path" % label,
                   not has(lines, "PASS", "mempalace-palace", "integrity ok") and not any("hub serves" in l and "PASS" in l for l in lines), rc, lines)
        case("statusz without the integrity block", mp_world(statusz={"ok": True}), [("FAIL", "mempalace-palace", "integrity")])
        case("no /statusz", mp_world(statusz=None), [("FAIL", "mempalace-palace", "/statusz")])
        for label, junk in (("html", "<html>nope</html>"), ("a list", [1])):
            case("/statusz is " + label, mp_world(statusz=junk), [("FAIL", "mempalace-palace", "/statusz")])
        w = mp_world()
        elsewhere = os.path.join(w["root"], "other-palace")
        os.makedirs(elsewhere)
        write(os.path.join(elsewhere, "chroma.sqlite3"), "SQLite format 3")
        write(os.path.join(w["cfg"], "config.json"), json.dumps({"palace_path": elsewhere}))
        case("hub serves another palace than the doctor resolves", w,
             [("FAIL", "mempalace-palace", "serves"), ("FAIL", "mempalace-palace", elsewhere)])
        # Resolution order as mempalace/config.py and paths.py do it at v3.12.0: env var, config.json palace_path,
        # default of the config directory (MEMPALACE_CONFIG_DIR, then ~/.mempalace when it holds an install, then XDG, then
        # ~/.config/mempalace). Mutation: ignoring the env var turns the first case red.
        w = mp_world(palace_path="/nonexistent/in-config-json")
        case("MEMPALACE_PALACE_PATH beats config.json", w, [("PASS", "mempalace-palace", "$MEMPALACE_PALACE_PATH")],
             env={"MEMPALACE_CONFIG_DIR": w["cfg"], "PATH": w["bin"], "MEMPALACE_PALACE_PATH": w["palace"]})
        w = mp_world(palace_path="/nonexistent/in-config-json")
        case("config.json palace_path, broken: names it", w, [("FAIL", "mempalace-palace", "/nonexistent/in-config-json")])
        w = mp_world()
        os.remove(os.path.join(w["cfg"], "config.json"))
        os.replace(w["palace"], os.path.join(w["cfg"], "palace"))
        HUB["statusz"]["palace"]["sqlite_integrity"]["palace"] = os.path.join(w["cfg"], "palace")
        case("no config.json: the palace is under the config directory", w, [("PASS", "mempalace-palace", "default")])
        w = mp_world()
        os.remove(os.path.join(w["cfg"], "config.json"))
        legacy = os.path.join(w["root"], ".mempalace")
        os.makedirs(legacy)
        write(os.path.join(legacy, "config.json"), json.dumps({}))
        os.replace(w["palace"], os.path.join(legacy, "palace"))
        HUB["statusz"]["palace"]["sqlite_integrity"]["palace"] = os.path.join(legacy, "palace")
        case("no config dir variable: ~/.mempalace that holds an install", w, [("PASS", "mempalace-palace", ".mempalace")],
             env={"PATH": w["bin"]})
        w = mp_world()
        os.remove(os.path.join(w["cfg"], "config.json"))
        xdg_palace = os.path.join(w["root"], "xdg", "mempalace", "palace")
        os.makedirs(os.path.dirname(xdg_palace))
        os.replace(w["palace"], xdg_palace)
        HUB["statusz"]["palace"]["sqlite_integrity"]["palace"] = xdg_palace
        case("no config dir variable, no install: XDG_CONFIG_HOME/mempalace", w, [("PASS", "mempalace-palace", "xdg")],
             env={"PATH": w["bin"], "XDG_CONFIG_HOME": os.path.join(w["root"], "xdg")})

        # ---- mempalace-backup. Red: no row. Mutation: dropping the .count requirement turns "no .count" red
        # ("backup without .count: exit 0; output [... PASS mempalace-backup ...]").
        case("backup of 1 h", mp_world(backup_age_h=1), [("PASS", "mempalace-backup", "threshold 48 h")])
        case("backup of 3 days", mp_world(backup_age_h=72), [("FAIL", "mempalace-backup", "72.0 h"), ("FAIL", "mempalace-backup", "48 h")])
        # Finding 9: an mtime in the future gave a negative age and PASSed. Red on 5078c50: "backup dated in the future: exit 0;
        # output [... PASS mempalace-backup newest validated backup is -5.0 h old ...]".
        case("backup dated in the future", mp_world(backup_age_h=-5),
             [("FAIL", "mempalace-backup", "future"), ("FAIL", "mempalace-backup", "mempalace-20261118T043000Z.tar.zst")],
             forbid=[("PASS", "mempalace-backup")])
        case("backup without .count", mp_world(backup_age_h=1, count=False),
             [("FAIL", "mempalace-backup", "mempalace-backup.timer")], forbid=[("PASS", "mempalace-backup")])
        case("no backup at all", mp_world(backup_age_h=None), [("FAIL", "mempalace-backup", "mempalace-backup.timer")])
        w = mp_world(backup_age_h=1)
        os.replace(os.path.join(w["backups"], "mempalace-20261118T043000Z.tar.zst"),
                   os.path.join(w["backups"], "mempalace-20261118T043000Z.tar.zst.rejected"))
        case("only a rejected backup", w, [("FAIL", "mempalace-backup")], forbid=[("PASS", "mempalace-backup")])
        w = mp_world(backup_age_h=1)
        sandbox.rmtree(w["backups"])
        case("backup directory missing", w, [("FAIL", "mempalace-backup", "mempalace-backup.timer")])

        # ---- mempalace-rows. Red: no row.
        case("a row missing", mp_world(rows=["Stop", "PreCompact"]), [("FAIL", "mempalace-rows", "SessionEnd")])
        case("no hooks at all", mp_world(rows=[]), [("FAIL", "mempalace-rows", "Stop"), ("FAIL", "mempalace-rows", "0 of 3")])
        case("a foreign hook in the event is not the row",
             mp_world(settings=json.dumps({"hooks": {e: [{"hooks": [{"type": "command", "command": "echo toy"}]}] for e, _ in HOOK_ROWS}})),
             [("FAIL", "mempalace-rows", "0 of 3")])
        case("truncated settings.local.json", mp_world(settings='{"hooks": {'), [("FAIL", "mempalace-rows", "unreadable")])
        case("hooks of the wrong shape", mp_world(settings=json.dumps({"hooks": ["x"]})), [("FAIL", "mempalace-rows", "wrong shape")])

        # ---- mempalace-wing. Red: no row. Freshness: no drawer in 14 days AND a transcript of the project in those 14
        # days is a WARN; the same without the transcript, or with a transcript older than that, is a parked project and
        # says nothing. Mutation: dropping the transcript condition turns the next two cases red.
        old = [(20, ""), (25, "")]
        case("wing with 0 drawers", mp_world(drawers=[]), [("FAIL", "mempalace-wing", "0 drawers")])
        case("stale wing and a newer transcript", mp_world(drawers=old, transcript_age_days=3),
             [("WARN", "mempalace-wing", "14 days"), ("WARN", "mempalace-wing", "3.0 days")])
        case("stale wing, no transcript: a parked project", mp_world(drawers=old),
             [("PASS", "mempalace-wing", "2 drawers")], forbid=[("WARN", "")])
        case("stale wing, transcript older than the window", mp_world(drawers=old, transcript_age_days=30),
             [("PASS", "mempalace-wing")], forbid=[("WARN", "")])
        case("fresh wing and a transcript from today", mp_world(drawers=[(1, "")], transcript_age_days=0.01),
             [("PASS", "mempalace-wing")], forbid=[("WARN", "")])
        w = mp_world(drawers=old)
        e = re.sub(r"[^A-Za-z0-9]", "-", w["proj"])
        for name in (e + "--claude-worktrees-wt1",):
            d = os.path.join(w["claude"], name)
            os.makedirs(d)
            write(os.path.join(d, "s.jsonl"), "{}\n")
        case("a worktree's transcript counts as the project's", w, [("WARN", "mempalace-wing")])
        w = mp_world(drawers=old)
        d = os.path.join(w["claude"], re.sub(r"[^A-Za-z0-9]", "-", w["proj"]) + "-other")
        os.makedirs(d)
        write(os.path.join(d, "s.jsonl"), "{}\n")
        case("a sibling project's transcript does not", w, [("PASS", "mempalace-wing")], forbid=[("WARN", "")])
        case("the freshness read gives no total: no traceback, a WARN",
             mp_world(drawers=old, transcript_age_days=3, hub_opts={"since_no_total": True}),
             [("WARN", "mempalace-wing", "freshness")])
        # The wing name is the directory's, lower-cased (docs/memory-health-gate.md (g): `Toy-Proj` is `toy_proj`). Mutation:
        # `.lower()` removed -> "a project directory with capitals: exit 1; output [... FAIL mempalace-wing wing Toy_Proj has 0 drawers]".
        case("a project directory with capitals: its wing is lower-case", mp_world(proj_name="Toy-Proj"),
             [("PASS", "mempalace-wing", "wing toy_proj has 1 drawers")])
        case("known-empty wing", mp_world(drawers=[]), [("KNOWN", "mempalace-wing")], known=json.dumps(
            {"known": {"toy/mempalace-wing": {"since": "long ago", "why": "not switched on yet"}}}), rc_is=0)
        case("list_wings answers a list: a FAIL, no traceback", mp_world(hub_opts={"wings_bad": True}),
             [("FAIL", "mempalace-wing", "list_wings")])
        case("hub stopped: the wing rows fail too", mp_world(hub="http://127.0.0.1:9"), [("FAIL", "mempalace-wing", "hub")])
        w = mp_world(backup_age_h=1, rows=["Stop"])
        HUB["log"].clear()
        rc, lines = mp_run(w, hook=True)
        expect("--hook: the rows are checked, the wing is not read (no list_wings call)",
               rc == 0 and has(lines, "FAIL", "mempalace-rows") and ("tool", "mempalace_list_wings") not in HUB["log"], rc, lines)

        # ---- finding 3: under --hook a hub that answers slowly or never must not outlast the hook's 15 s (forge/hooks.py). Short
        # per-call timeouts, a budget for the whole part, and no call after the first that did not answer. The fake accepts and
        # never answers ("all": /healthz and /statusz too; "tools": /healthz answers, the tools/call never does) or answers every
        # call 2.9 s late ("slow": each call inside its own timeout, so only the budget ends it). Red on 5078c50, measured on the toy
        # (hindsight off): all 10.1 s (5 s for /healthz, 5 s for /statusz), tools 30.2 s (one tools/call), slow 11.7 s (four calls).
        for mode, limit in (("all", 8), ("tools", 8), ("slow", 9.5)):
            w = mp_world(hub_opts={"hang": mode})
            HUB["log"].clear()
            t0 = time.time()
            rc, lines = mp_run(w, hook=True)
            took = time.time() - t0
            expect("--hook, hub %s: ends in under %s s (took %.1f s) and prints its FAIL" % (mode, limit, took),
                   rc == 0 and took < limit and has(lines, "FAIL", "mempalace-hub") and has(lines, "FAIL", "mempalace-palace"), rc, lines)
            if mode != "slow":
                expect("--hook, hub %s: nothing is asked after the first call that did not answer" % mode,
                       ("GET", "/statusz") not in HUB["log"] and ("tool", "mempalace_search") not in HUB["log"], rc, HUB["log"])
        # `mempalace --version` is capped under --hook too (30 s before). Red on 5078c50: "--hook, mempalace --version takes 15 s:
        # ends in under 8 s (took 15.1 s)"; mutation: the cap removed turns it red the same way.
        w = mp_world(cli_sleep=15)
        t0 = time.time()
        rc, lines = mp_run(w, hook=True)
        took = time.time() - t0
        expect("--hook, mempalace --version takes 15 s: ends in under 8 s (took %.1f s) with a FAIL" % took,
               rc == 0 and took < 8 and has(lines, "FAIL", "mempalace-cli"), rc, lines)
        # The full run keeps its long timeouts: a hub that is merely slow (2.9 s a call) is judged healthy outside --hook.
        w = mp_world(hub_opts={"hang": "slow"})
        rc, lines = mp_run(w)
        expect("full run, slow hub: still healthy (the long timeouts stay)", rc == 0 and has(lines, "PASS", "mempalace-hub")
               and has(lines, "PASS", "mempalace-palace", "integrity ok"), rc, lines)

        # ---- memory-one-backend: also with mempalace off and under --hook. Armed when the checkout uses memory at all (the
        # hindsight or mempalace integration on, or a project that grants a backend): there, a profile without a backend says
        # so. Red against the baseline: it says nothing ("no backend: exit 0; output []"). Mutation: `== 1` to `>= 0` turns the
        # no-backend cases red.
        none = {"toy": {"project_path": "/srv/toy", "servers": []}}
        two = {"toy": {"project_path": "/srv/toy", "servers": ["hindsight-coding-agents", "mempalace"],
                       "plugins_keep": [md.memory.LITE_PLUGIN]}}
        for label, profs, on, hook in (("on", none, True, False), ("off", none, False, False), ("--hook, off", none, False, True)):
            w = mp_world(backup_age_h=1, profs=profs)
            rc, lines = mp_run(w, on=on, hook=hook, hind=True)
            expect("profile without a backend, integration %s" % label, rc == (0 if hook else 1) and has(
                lines, "FAIL", "memory-backend", "toy has no memory backend"), rc, lines)
        w = mp_world(backup_age_h=1, profs=two)
        rc, lines = mp_run(w, on=False, hind=True)
        expect("profile with three backends names them", rc == 1 and has(
            lines, "FAIL", "memory-backend", "toy has 3 memory backends: hindsight-coding-agents, claude-mem-lite, mempalace"), rc, lines)
        for servers, plugins, backend in ((["hindsight-coding-agents", "mempalace"], [], "hindsight-coding-agents, mempalace"),
                                          (["mempalace"], [md.memory.LITE_PLUGIN], "claude-mem-lite, mempalace"),
                                          (["hindsight-coding-agents"], [md.memory.LITE_PLUGIN], "hindsight-coding-agents, claude-mem-lite")):
            w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": servers, "plugins_keep": plugins}})
            rc, lines = mp_run(w, on=False, hind=True)
            expect("profile with two backends: " + backend, rc == 1 and has(lines, "FAIL", "memory-backend", "2 memory backends: " + backend), rc, lines)
        for servers, plugins, backend in ((["hindsight-coding-agents"], [], "hindsight-coding-agents"),
                                          ([], [md.memory.LITE_PLUGIN], "claude-mem-lite"), (["mempalace"], [], "mempalace")):
            w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": servers, "plugins_keep": plugins}})
            rc, lines = mp_run(w, on=False, hind=True)
            # (claude-mem-lite brings its own rows, which FAIL in this toy world: only the memory-backend lines are asserted.)
            expect("profile with one backend: " + backend, rc == (1 if plugins else 0)
                   and not has(lines, "FAIL", "memory-backend") and has(
                       lines, "PASS", "memory-one-backend", "1 project(s) examined, 1 with exactly one backend"), rc, lines)
        # A project file that cannot be read has a backend nobody looked at: the row says so and FAILs (--project X leaves
        # the others out of scope). Red against the row that took lib.projects() whole: "unreadable project: exit 0".
        # Mutation: ignoring `skipped` turns it red. Looking at none is a FAIL too, once armed.
        w = mp_world(backup_age_h=1)
        w["skipped"] = [("broken.claude.json", "invalid JSON")]
        rc, lines = mp_run(w, on=False)
        expect("an unreadable project file is not a pass", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "1 project file(s) could not be read: broken.claude.json"), rc, lines)
        w = mp_world(backup_age_h=1, profs={})
        w["skipped"] = [("broken.claude.json", "invalid JSON")]
        rc, lines = mp_run(w, on=False, hind=True)
        expect("only unreadable project files: looked at zero, FAIL", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "0 project(s) examined: a check that saw nothing is not a pass; 1 project file(s)"), rc, lines)
        w = mp_world(backup_age_h=1, profs={})
        rc, lines = mp_run(w, on=False, hind=True)
        expect("armed and looking at zero projects is a FAIL", rc == 1 and has(lines, "FAIL", "memory-one-backend", "0 project(s)"), rc, lines)
        rc, lines = mp_run(w, on=False, hind=True, hook=True)
        expect("armed and looking at zero projects, --hook: said, exit 0", rc == 0 and has(lines, "FAIL", "memory-one-backend"), rc, lines)
        # Not armed: no memory integration on and no project that grants a backend, which is a stranger's fresh checkout with its
        # one starter project. `forge init` runs this doctor on it. Red while the row FAILed there (tests/test_fresh_install.py,
        # 8 cases: "forge doctor exits 0 with no FAIL or WARN line -- exit 1: FAIL memory 1 unexpected failure(s)", and
        # tests/test_integration_sites.py "memory_doctor, codex and hindsight off ... exit 1": "FAIL memory-one-backend 0 project(s)
        # examined"): NOT RUN, NOT ARMED, exit 0, silent under --hook. Mutation: arming always turns these red.
        NOT_RUN = "memory-one-backend -> NOT RUN, NOT ARMED: no memory integration is on"
        for label, profs in (("a starter project without memory", none), ("no project file", {})):
            w = mp_world(backup_age_h=1, profs=profs)
            rc, lines = mp_run(w, on=False)
            expect("not armed, %s: NOT RUN, exit 0" % label, rc == 0 and any(NOT_RUN in l for l in lines)
                   and not has(lines, "PASS", "memory-one-backend") and not has(lines, "FAIL", "memory"), rc, lines)
            rc, lines = mp_run(w, on=False, hook=True)
            expect("not armed, %s, --hook: silent, exit 0" % label, rc == 0 and lines == [], rc, lines)
        w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": []},
                                            "other": {"project_path": "/srv/other", "servers": ["mempalace"]}})
        rc, lines = mp_run(w, on=False)
        expect("armed by another project's backend: the one without says so", rc == 1 and has(
            lines, "FAIL", "memory-backend", "toy has no memory backend") and not any(NOT_RUN in l for l in lines), rc, lines)
        # Finding 5: the row a reader greps must not PASS while a project it examined fails. Red on 5078c50: "the row fails when
        # a project does: exit 1; output [... PASS memory-one-backend 4 project(s) examined, 2 with exactly one backend ...]".
        # Known-empty projects are counted apart and do not fail it. Mutation: the PASS condition back to `bool(projects)` turns
        # the first two cases red.
        mixed = {"a": {"project_path": "/srv/a", "servers": ["mempalace"]}, "b": {"project_path": "/srv/b", "servers": []},
                 "c": {"project_path": "/srv/c", "servers": ["mempalace"]}, "d": {"project_path": "/srv/d", "servers": []}}
        w = mp_world(backup_age_h=1, profs=mixed)
        rc, lines = mp_run(w, on=False, hind=True)
        expect("the row fails when a project does", rc == 1 and has(lines, "FAIL", "memory-one-backend",
               "4 project(s) examined, 2 with exactly one backend, 2 failing") and not has(lines, "PASS", "memory-one-backend"), rc, lines)
        rc, lines = mp_run(w, on=False, hind=True, hook=True)
        expect("the row fails when a project does, --hook: said, exit 0", rc == 0 and has(lines, "FAIL", "memory-one-backend", "2 failing"), rc, lines)
        rc, lines = mp_run(w, on=False, hind=True, known=json.dumps({"known": {
            "b/memory-backend": {"since": "long ago", "why": "no memory on purpose"}, "d/memory-backend": {"since": "long ago", "why": "same"}}}))
        expect("two known-empty projects are counted apart: the row passes", rc == 0 and has(
            lines, "PASS", "memory-one-backend", "4 project(s) examined, 2 with exactly one backend, 2 declared in config")
            and not has(lines, "FAIL", "memory"), rc, lines)
        rc, lines = mp_run(w, on=False, hind=True, known=json.dumps({"known": {"b/memory-backend": {"since": "long ago", "why": "x"}}}))
        expect("one known-empty and one failing project: the row fails and says both", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "2 with exactly one backend, 1 declared in config") and has(
            lines, "FAIL", "memory-one-backend", "1 failing"), rc, lines)
        w = mp_world(backup_age_h=1, profs=mixed)
        w["profs"] = {"b": mixed["b"]}
        rc, lines = mp_run(w, on=False, hind=True)
        expect("a project alone that has no backend: the row fails", rc == 1 and has(
            lines, "FAIL", "memory-one-backend", "1 project(s) examined, 0 with exactly one backend, 1 failing"), rc, lines)
        w = mp_world(backup_age_h=1, profs=none)
        rc, lines = mp_run(w, on=True)
        expect("armed by the mempalace integration alone: the one without says so", rc == 1 and has(
            lines, "FAIL", "memory-backend", "toy has no memory backend"), rc, lines)
        w = mp_world(backup_age_h=1, profs=none)
        rc, lines = mp_run(w, on=False, hind=True, known=json.dumps(
            {"known": {"toy/memory-backend": {"since": "long ago", "why": "no memory on purpose"}}}))
        expect("profile declared without memory is KNOWN", rc == 0 and has(lines, "KNOWN", "memory-backend", "no memory on purpose")
               and not has(lines, "FAIL", "memory-backend"), rc, lines)
        w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": ["mempalace"]}})
        rc, lines = mp_run(w, on=False, hind=True, known=json.dumps(
            {"known": {"toy/memory-backend": {"since": "long ago", "why": "no memory on purpose"}}}))
        expect("a declared-empty profile that now has a backend is reported stale", has(lines, "STALE", "toy/memory-backend"), rc, lines)

        # ---- the fake hub's guard can fail, and the code refuses a write tool before it leaves the process. Control: the
        # guard fires when a write tool reaches the hub; md.hub_call raises on one and the hub sees nothing.
        hub_reset()
        cases[0] += 1
        try:
            md.hub_call(FAKE_HUB + "/mcp", "mempalace_add_drawer", {"wing": "x", "room": "y", "content": "z"})
            failures.append("hub_call let a write tool through")
        except ValueError:
            pass
        except AttributeError as e:
            failures.append("hub_call: %s" % e)
        if ("tool", "mempalace_add_drawer") in HUB["log"]:
            failures.append("a write tool reached the hub")
        cases[0] += 1
        req = md.urllib.request.Request(FAKE_HUB + "/mcp", method="POST", headers={"Content-Type": "application/json"},
                                        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                                            "name": "mempalace_add_drawer", "arguments": {}}}).encode())
        md.urllib.request.urlopen(req, timeout=5).read()
        if HUB["violations"] != ["mempalace_add_drawer"]:
            failures.append("the fake hub did not record a write tool: %r" % HUB["violations"])
        hub_reset()
    finally:
        md.HOME = real_home
        md.KNOWN, md.BACKUPS, md.CLAUDE_PROJECTS, md.HINDSIGHT_RENDERED, md.CODEX_HOME = real_paths
        for name in ("mempalace", "hindsight", "codex"):
            integration(name, name != "mempalace")


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

    mempalace_cases(failures, cases)

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over %d cases" % (len(failures), cases[0]))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
