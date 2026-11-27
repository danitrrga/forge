#!/usr/bin/env python3
"""`forge config NAME --on option:framework` / `--off option:framework`: the CLI way to switch the agent framework on and off for a
project (DTC-73), in the grammar of --on/--off, dry-run by default and written with --apply.

The world is a toy (tests/sandbox.py): an engine copy, a toy HOME whose user scope has the plugins `mine@mk` (on) and `off@mk` (off),
forge.json with `common_plugins: ["common@mk"]` and a framework.plugin_source that is a directory marketplace of one plugin
(`toyfw`), a stand-in `claude`, and the project `demo` (no plugins_keep, framework not set), `kept` (plugins_keep set) and `fixed`
(`framework: true` already). Every command runs the copy's bin/forge with no terminal.

Cases (each assertion was seen failing first, see the control record below):
  a  the dry-run (no --apply) says what it would change and changes no file.
  b  --apply writes `framework: true` into the project file; a project with no plugins_keep gets the plugins it already had on (the user
     scope's, then skill_keep.common_plugins, as `forge new --framework` does) so the generator can serve it; one that has plugins_keep
     keeps it as it is; the generator ran (the plugin's .claude/toyfw.json is in the project); --off turns it off again (no command can restore
     "absent", so the output names the two keys that were not there, by hand).
  c  --off writes `framework: false`, and the generated plugin file is no longer wanted by forge doctor's `framework fields` row.
  d  already in the state asked: exit 0, "nothing to change", no write.
  e  a framework that the generator would refuse (no framework.plugin_source) is refused with exit 2 and nothing written; so is a frozen
     project.
  f  `--names` lists option:framework; a misspelling (option:framwork) is exit 2 naming the closest one.
  g  `forge doctor demo` reports the framework state through its `framework fields` row (SKIP, framework off; once on, the row names
     the fields still unset).

Written first, run against master (6e4e54c), where OPTIONS is ("ui", "command_guard", "enableAllProjectMcpServers"): 17 FAIL, first
  "FAIL a: the dry-run of --on option:framework exits 0 -- exit 2, stderr "forge config: no option 'framework'. There are:
  command_guard, enableAllProjectMcpServers, ui"" and "FAIL f: --names lists option:framework".
Negative controls, each a one-line mutation of forge/configure.py, run once and put back (the first message each produced):
  b  the `plugins_keep` assignment in framework_ready() replaced by `pass` -> "FAIL a: the dry-run of --on option:framework exits 0 --
     exit 2, stderr "forge config: framework cannot be switched on for project 'demo': framework is true but the project has no
     plugins_keep: ..."" (and the b assertions: "a project with no plugins_keep gets the plugins it had on -- None")
  e  the refusal in framework_ready() taken out -> "FAIL e: no plugin_source is refused (exit 2) and nothing is written -- exit 1,
     forge config: written, but forge sync demo --apply exits 1 (...)".
  h  (after the review of PR 217) `plugins_keep` defaulted when falsy instead of when absent, run against head 9721a48 -> "FAIL h: an
     empty plugins_keep is refused (exit 2) and nothing is written -- exit 1, ... forge config: written, but forge sync nokeep
     --apply exits 1 (...); undo with: no command does; by hand: ... plugins_keep in config/projects/nokeep.claude.json: was []"."""
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures = []
n_checks = [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))
        print("FAIL %s -- %s" % (label, detail))


def read_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


PROJECTS = {"demo": {}, "kept": {"plugins_keep": ["only@mk"]}, "fixed": {"framework": True, "plugins_keep": ["only@mk"]},
            "frozen-p": {"frozen": True}, "nokeep": {"plugins_keep": []}}


class World:
    def __init__(self, mutate=(), plugin_source=True):
        self.top = sandbox.mkdtemp("conf-fw-")
        self.root, self.home = os.path.join(self.top, "forge"), os.path.join(self.top, "home")
        self.tmp, self.logs = os.path.join(self.top, "tmp"), os.path.join(self.top, "log")
        for d in (self.home, os.path.join(self.home, ".claude"), self.tmp, self.logs):
            os.makedirs(d)
        sandbox.copy_engine(self.root)
        for rel, old, new in mutate:
            p = os.path.join(self.root, rel)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            assert text.count(old) == 1, "the control's anchor is not in %s: %r" % (rel, old)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
        sandbox.git(self.root, "init", "-q")
        sandbox.git(self.root, "add", "-A")
        sandbox.git(self.root, "commit", "-q", "-m", "engine")
        cfg = os.path.join(self.root, "config")
        os.makedirs(os.path.join(cfg, "projects"))
        doc = read_json(os.path.join(self.root, "examples", "forge.json"))
        doc.pop("projects_dir", None)
        doc["integrations"] = {}
        self.plugin = os.path.join(self.top, "plug", "toyfw")
        os.makedirs(os.path.join(self.plugin, ".claude-plugin"))
        write_json(os.path.join(self.plugin, ".claude-plugin", "marketplace.json"), {"name": "toyfw", "plugins": [{"name": "toyfw"}]})
        if plugin_source:
            doc["framework"]["plugin_source"] = {"source": "directory", "path": self.plugin}
        else:
            doc["framework"].pop("plugin_source", None)
        doc["skill_keep"]["common_plugins"] = ["common@mk"]
        write_json(os.path.join(cfg, "forge.json"), doc)
        write_json(os.path.join(self.home, ".claude", "settings.json"), {"enabledPlugins": {"mine@mk": True, "off@mk": False}})
        for name in ("mcp-registry.json", "gateway.json"):
            with open(os.path.join(self.root, "examples", name), encoding="utf-8") as fh, open(os.path.join(cfg, name), "w", encoding="utf-8") as out:
                out.write(fh.read())
        os.makedirs(os.path.join(self.root, "credentials"), mode=0o700)
        write_json(os.path.join(self.root, "credentials", "secrets.json"), {})
        os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg, "secrets.json"))
        with open(os.path.join(self.root, "examples", "AGENT-SYSTEM.md"), encoding="utf-8") as fh, \
                open(os.path.join(cfg, "AGENT-SYSTEM.md"), "w", encoding="utf-8") as out:
            out.write(fh.read())
        for name, body in PROJECTS.items():
            write_json(os.path.join(cfg, "projects", name + ".claude.json"), dict(body, project=name, project_path=self.pp(name)))
            os.makedirs(self.pp(name))
            sandbox.git(self.pp(name), "init", "-q")
        bin_dir = sandbox.stub_claude(os.path.join(self.top, "bin"), os.path.join(self.logs, "claude.log"))
        self.env = sandbox.bare_env(self.home, self.tmp, bin_dir, FORGE_WRITE_LOG=os.path.join(self.logs, "writes.log"),
                                    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

    def pp(self, name):
        return os.path.join(self.top, "projects", name)

    def pfile(self, name):
        return os.path.join(self.root, "config", "projects", name + ".claude.json")

    def proj(self, name):
        return read_json(self.pfile(name))

    def forge(self, *args):
        r = subprocess.run([sys.executable, os.path.join(self.root, "bin", "forge")] + list(args), cwd=self.root, env=self.env,
                           capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout.replace(self.top, "@W@"), r.stderr.replace(self.top, "@W@")

    def fingerprint(self):
        h = hashlib.sha256()
        for base in (os.path.join(self.root, "config"), self.pp("demo"), self.pp("kept"), self.pp("fixed"), self.pp("frozen-p"), self.pp("nokeep")):
            for d, dirs, files in os.walk(base):
                dirs[:] = sorted(x for x in dirs if x != ".git")
                for f in sorted(files):
                    p = os.path.join(d, f)
                    h.update(p.encode())
                    if os.path.isfile(p):
                        with open(p, "rb") as fh:
                            h.update(fh.read())
        return h.hexdigest()


def case_a(w):
    before = w.fingerprint()
    code, out, err = w.forge("config", "demo", "--on", "option:framework")
    check("a: the dry-run of --on option:framework exits 0", code == 0, "exit %d, stderr %r" % (code, err.strip()[:300]))
    check("a: the dry-run says it is one", "dry-run" in out and "option:framework" in out, out)
    check("a: the dry-run changes no file", w.fingerprint() == before, "files changed")


def case_b(w):
    code, out, err = w.forge("config", "demo", "--on", "option:framework", "--apply")
    check("b: --apply exits 0", code == 0, "exit %d, stdout %r, stderr %r" % (code, out.strip()[-300:], err.strip()[-300:]))
    p = w.proj("demo")
    check("b: framework is true in the project file", p.get("framework") is True, p)
    check("b: a project with no plugins_keep gets the plugins it had on, the common ones after",
          p.get("plugins_keep") == ["mine@mk", "common@mk"], p.get("plugins_keep"))
    check("b: the generator served it: the plugin's file is in the project", os.path.isfile(os.path.join(w.pp("demo"), ".claude", "toyfw.json")),
          "no .claude/toyfw.json")
    # The state before had no `framework` and no plugins_keep, and --off writes `false`, so no command restores it: the output says
    # so and names both keys (as it does for `ui` on a project that never set it); the way back is --off, which case c runs.
    check("b: the output names what was not there before, by hand", "framework in config/projects/demo.claude.json: was not there" in out and
          "plugins_keep in config/projects/demo.claude.json: was not there" in out, out)
    code, out2, err2 = w.forge("config", "demo", "--off", "option:framework", "--apply")
    check("b: --off turns it off again", code == 0 and w.proj("demo").get("framework") is False, "exit %d %s" % (code, err2.strip()[-200:]))
    code, out, err = w.forge("config", "kept", "--on", "option:framework", "--apply")
    p = w.proj("kept")
    check("b: kept: exit 0, framework true, plugins_keep as it was", code == 0 and p.get("framework") is True and p.get("plugins_keep") == ["only@mk"],
          "exit %d, %s, %s" % (code, p, err.strip()[-200:]))
    check("b: the generator served it: the plugin's file is in the project", os.path.isfile(os.path.join(w.pp("kept"), ".claude", "toyfw.json")),
          "no .claude/toyfw.json")


def case_c(w):
    code, out, err = w.forge("config", "fixed", "--off", "option:framework", "--apply")
    check("c: --off exits 0", code == 0, "exit %d, %s" % (code, err.strip()[-300:]))
    check("c: framework is false in the project file", w.proj("fixed").get("framework") is False, w.proj("fixed"))
    code, out, err = w.forge("doctor", "fixed")
    row = [l for l in out.splitlines() if "framework fields" in l]
    check("c: forge doctor reports framework off for it", bool(row) and "framework off" in row[0], row or out[-400:])


def case_d(w):
    before = w.fingerprint()
    code, out, err = w.forge("config", "fixed", "--on", "option:framework", "--apply")
    check("d: on when already on: exit 0, nothing to change", code == 0 and "nothing to change" in out, "exit %d, %s" % (code, out + err))
    check("d: and no file changed", w.fingerprint() == before, "files changed")


def case_e():
    w = World(plugin_source=False)
    before = w.fingerprint()
    code, out, err = w.forge("config", "demo", "--on", "option:framework", "--apply")
    check("e: no plugin_source is refused (exit 2) and nothing is written", code == 2 and w.fingerprint() == before and "plugin_source" in err,
          "exit %d, %s" % (code, err.strip()[-300:]))
    w = World()
    before = w.fingerprint()
    code, out, err = w.forge("config", "frozen-p", "--on", "option:framework", "--apply")
    check("e: a frozen project is refused (exit 2) and nothing is written", code == 2 and w.fingerprint() == before, "exit %d, %s" % (code, err.strip()[-300:]))


def case_h(w):
    # CodeRabbit on PR 217: plugins_keep is defaulted only when the key is absent. A present `[]` is the owner's explicit "no plugins": it
    # is refused (the generator needs plugins_keep), never replaced silently by the defaults. (A present invalid value such as "" is already
    # refused when the file is read; that was seen passing before the fix, so it is not asserted here.)
    before = w.fingerprint()
    code, out, err = w.forge("config", "nokeep", "--on", "option:framework", "--apply")
    check("h: an empty plugins_keep is refused (exit 2) and nothing is written", code == 2 and w.fingerprint() == before,
          "exit %d, stdout %r, stderr %r" % (code, out.strip()[-200:], err.strip()[-300:]))


def case_f(w):
    code, out, err = w.forge("config", "--names")
    check("f: --names lists option:framework", "option:framework" in out.splitlines(), out[-300:])
    code, out, err = w.forge("config", "demo", "--on", "option:framwork")
    check("f: a misspelling is exit 2 naming the closest", code == 2 and "framework" in err, "exit %d, %s" % (code, err.strip()[-300:]))


def case_g(w):
    code, out, err = w.forge("doctor", "demo")
    row = [l for l in out.splitlines() if "framework fields" in l]
    check("g: doctor demo reports the framework state with framework off", bool(row) and "framework off" in row[0], row or out[-400:])
    w.forge("config", "demo", "--on", "option:framework", "--apply")
    code, out, err = w.forge("doctor", "demo")
    row = [l for l in out.splitlines() if "framework fields" in l]
    check("g: and with it on the row names what is still unset", bool(row) and "protected_paths" in row[0], row or out[-400:])


def attempt(fn, *args):
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001
        check("%s ran to its end" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))


def main():
    for fn in (case_a, case_b, case_c, case_d, case_f, case_g, case_h):
        attempt(lambda f=fn: f(World()))
    attempt(case_e)
    sandbox.cleanup()
    if failures:
        print("%d FAIL" % len(failures))
        return 1
    print("test_config_framework: ok (%d checks)" % n_checks[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
