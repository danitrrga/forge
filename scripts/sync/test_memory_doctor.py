#!/usr/bin/env python3
"""memory_doctor.py's checks, driven through main() in-process on a toy CODEX_HOME.

main() runs with every path it reads pointed into a temp dir: the Codex config and hooks.json, the
rendered hindsight config (by default one whose top-level server is a loopback stand-in answering
/health, so nothing leaves the machine), the known-empty backlog (absent) and the profile list
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
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import sys
import threading
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


def run_full(manifest, trusted=False, hind=None, known=None, hook=False, settings=None):
    """main() against a fresh toy CODEX_HOME; manifest None means no hooks.json at all.
    hind: raw text of the rendered hindsight config (default: the live stand-in as top-level
    server, bank personal, no banks), or False for no file. known: raw text of the known-empty
    file, or None for none. settings: raw text of a toy project's settings.local.json (the
    project opts in to claude-mem-lite), or None for no project.
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
    profs = {}
    if settings is not None:
        proj = os.path.join(home, "proj")
        os.makedirs(os.path.join(proj, ".claude"))
        write(os.path.join(proj, ".claude", "settings.local.json"), settings)
        profs = {"toy": {"project_path": proj, "plugins_keep": [md.memory.LITE_PLUGIN]}}
    md.lib.profiles = lambda: profs
    md.COLOR = {k: "" for k in md.COLOR}
    md.DIM = md.OFF = ""
    for state in (md.fails, md.warns, md.backlog, md.known_still_failing):
        state.clear()
    md.known_map.clear()
    sys.argv = ["memory_doctor.py"] + (["--hook"] if hook else [])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            rc = md.main()
        except Exception:
            rc = traceback.format_exc().strip().splitlines()[-1]
    return rc, out.getvalue().splitlines()


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

    rc, lines = run(json.dumps(HOOK))
    want = ("1 hook(s) registered with no trust record, so they do not fire until the next "
            "Codex session approves them: SessionStart echo toy")
    if rc != 0 or not any(l.lstrip().startswith("WARN") and want in l for l in lines):
        failures.append("one untrusted hook: exit %s, output %r" % (rc, " | ".join(lines)))

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

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over %d cases" % (len(failures), cases[0]))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
