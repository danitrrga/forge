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
real one, ORDERS 10). The red of every case, and the mutation that turns it red, is in a comment at the case.
"""
import contextlib
import datetime
import http.server
import importlib.util
import io
import json
import os
import re
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
    md.lib.projects = lambda: profs
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
    HUB.update(health="/healthz", statusz=None, drawers=[], search="ok", since_no_total=False, log=[], violations=[])
    HUB.update(kw)


def _tool_answer(value):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(value)}]}}


def _since(args):
    got = datetime.datetime.fromisoformat(args["since"])
    return got if got.tzinfo else got.replace(tzinfo=datetime.timezone.utc)


class _Hub(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        HUB["log"].append(("GET", self.path))
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
            return self._send(200, _tool_answer({"wings": wings}))
        if tool == "mempalace_list_drawers":
            if "since" in args:
                if HUB["since_no_total"]:
                    return self._send(200, _tool_answer({"drawers": []}))
                drawers = [d for d in drawers if d["filed_at"] >= _since(args)]
            shown = [{"drawer_id": "d%d" % i, "wing": d["wing"], "content_preview": d["text"][:100] + "..."}
                     for i, d in enumerate(drawers[: args.get("limit", 10)])]
            return self._send(200, _tool_answer({"drawers": shown, "total": len(drawers), "count": len(shown)}))
        mode = HUB["search"]                                                  # mempalace_search
        if mode == "http500":
            return self._send(500, "boom", "text/plain")
        if mode == "rpcerror":
            return self._send(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "model not loaded"}})
        if mode == "toolerror":
            return self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "embedder failed"}]}})
        if mode == "empty":
            return self._send(200, _tool_answer({"results": []}))
        hits = [{"text": d["text"], "source_file": "s.jsonl", "distance": 0.1} for d in drawers if args["query"] in d["text"]]
        return self._send(200, _tool_answer({"results": hits[: args.get("limit", 5)]}))

    def log_message(self, *a):
        pass


_hub_srv = http.server.HTTPServer(("127.0.0.1", 0), _Hub)
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
    cli (False: no `mempalace` on PATH), cli_version, palace (False: no directory), db (False: no database file),
    palace_path (what config.json says), hub (the registry's URL base; None: no registry entry), pinned (toolchain
    version; None: no entry), backup_age_h (default 1; None: no backup), count (False: no .count), rows (events kept),
    transcript_age_days (None: none), drawers (list of (age in days, text)), statusz (override), hub_opts."""
    root = sandbox.mkdtemp("memdoctor-mp-")
    w = {"root": root, "proj": os.path.join(root, "toy-proj"), "bin": os.path.join(root, "bin"),
         "palace": os.path.join(root, "palace"), "cfg": os.path.join(root, "cfg"),
         "backups": os.path.join(root, "backups"), "claude": os.path.join(root, "claude-projects")}
    os.makedirs(w["bin"])
    if o.get("cli", True):
        write(os.path.join(w["bin"], "mempalace"), "#!/bin/sh\necho 'MemPalace %s'\n" % o.get("cli_version", "3.12.0"))
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


def mp_run(w, hook=False, known=None, env=None, on=True):
    """main() with the integration on (or off) in `w`'s toy world. Returns (rc or traceback line, lines)."""
    knownf = os.path.join(w["root"], "known.json")
    if known is not None:
        write(knownf, known)
    md.CODEX_HOME = os.path.join(w["root"], "codex")
    integration("codex", False)
    integration("mempalace", on)
    md.HINDSIGHT_RENDERED = os.path.join(w["root"], "absent-hindsight.json")
    integration("hindsight", False)
    md.KNOWN, md.BACKUPS, md.CLAUDE_PROJECTS, md.HOME = knownf, w["backups"], w["claude"], w["root"]
    md.lib.projects = lambda: w["profs"]
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
        case("no registry entry", mp_world(hub=None), [("FAIL", "mempalace-hub", "mcp-registry.json")])
        case("registry url is not http", mp_world(hub="file:///etc"), [("FAIL", "mempalace-hub", "http")])

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

        # ---- memory-one-backend: always, also with the integration off and under --hook. Red against the baseline: a
        # profile without a backend says nothing ("no backend: exit 0; output []"). Mutation: `== 1` to `>= 0` turns the
        # no-backend case red; dropping the `examined > 0` condition turns the zero-profile case red.
        none = {"toy": {"project_path": "/srv/toy", "servers": []}}
        two = {"toy": {"project_path": "/srv/toy", "servers": ["hindsight-coding-agents", "mempalace"],
                       "plugins_keep": [md.memory.LITE_PLUGIN]}}
        for label, profs, on, hook in (("on", none, True, False), ("off", none, False, False), ("--hook, off", none, False, True)):
            w = mp_world(backup_age_h=1, profs=profs)
            rc, lines = mp_run(w, on=on, hook=hook)
            expect("profile without a backend, integration %s" % label, rc == (0 if hook else 1) and has(
                lines, "FAIL", "memory-backend", "toy has no memory backend"), rc, lines)
        w = mp_world(backup_age_h=1, profs=two)
        rc, lines = mp_run(w, on=False)
        expect("profile with three backends names them", rc == 1 and has(
            lines, "FAIL", "memory-backend", "toy has 3 memory backends: hindsight-coding-agents, claude-mem-lite, mempalace"), rc, lines)
        for servers, plugins, backend in ((["hindsight-coding-agents", "mempalace"], [], "hindsight-coding-agents, mempalace"),
                                          (["mempalace"], [md.memory.LITE_PLUGIN], "claude-mem-lite, mempalace"),
                                          (["hindsight-coding-agents"], [md.memory.LITE_PLUGIN], "hindsight-coding-agents, claude-mem-lite")):
            w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": servers, "plugins_keep": plugins}})
            rc, lines = mp_run(w, on=False)
            expect("profile with two backends: " + backend, rc == 1 and has(lines, "FAIL", "memory-backend", "2 memory backends: " + backend), rc, lines)
        for servers, plugins, backend in ((["hindsight-coding-agents"], [], "hindsight-coding-agents"),
                                          ([], [md.memory.LITE_PLUGIN], "claude-mem-lite"), (["mempalace"], [], "mempalace")):
            w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": servers, "plugins_keep": plugins}})
            rc, lines = mp_run(w, on=False)
            # (claude-mem-lite brings its own rows, which FAIL in this toy world: only the memory-backend lines are asserted.)
            expect("profile with one backend: " + backend, rc == (1 if plugins else 0)
                   and not has(lines, "FAIL", "memory-backend") and has(lines, "PASS", "memory-one-backend", "1 project(s) examined"), rc, lines)
        w = mp_world(backup_age_h=1, profs={})
        rc, lines = mp_run(w, on=False)
        expect("looking at zero profiles is a FAIL", rc == 1 and has(lines, "FAIL", "memory-one-backend", "0 project(s)"), rc, lines)
        rc, lines = mp_run(w, on=False, hook=True)
        expect("looking at zero profiles, --hook: said, exit 0", rc == 0 and has(lines, "FAIL", "memory-one-backend"), rc, lines)
        w = mp_world(backup_age_h=1, profs=none)
        rc, lines = mp_run(w, on=False, known=json.dumps(
            {"known": {"toy/memory-backend": {"since": "long ago", "why": "no memory on purpose"}}}))
        expect("profile declared without memory is KNOWN", rc == 0 and has(lines, "KNOWN", "memory-backend", "no memory on purpose")
               and not has(lines, "FAIL", "memory-backend"), rc, lines)
        w = mp_world(backup_age_h=1, profs={"toy": {"project_path": "/srv/toy", "servers": ["mempalace"]}})
        rc, lines = mp_run(w, on=False, known=json.dumps(
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
