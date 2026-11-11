#!/usr/bin/env python3
"""U1 of the plan that reorganises forge's configuration by concept: forge/config.py is the one place that knows where each
concept's settings live (LAYOUT), in the layout forge has and in the one it is moving to, and `lib.settings()` is composed with
its `load`, so its callers and the suites that write a toy forge.json do not notice which layout is on disk.

Two parts, each prints how much it looked at and fails at a count of 0:

1. A toy config directory built from the LAYOUT table (every row gets a value, so a row added to the table is covered at once),
   written in the old layout and rewritten into the new one by this file's own code. `lib.settings()` and every concept's `load`
   answer the same on both; a row whose value is in both places exits 1 naming both files; an unreadable new file exits 1; the
   old layout keeps lib.settings()'s messages (missing, unreadable, not an object).
2. A toy world (an engine copy + the fixtures of tests/fixtures/config, a toy HOME, a framework project, a logging `claude`) in
   the old layout, where `forge sync --all` is dry-run, then `--apply`ed, and every file under HOME and the projects is hashed; the
   same world with config/forge.json rewritten into the new layout (the settings `lib.settings()` serves; the files other code
   opens by path stay, their readers move in later units) must dry-run the same text and hash the same files. The new layout's
   file names are read from LAYOUT and never spelled here, so a name chosen differently is one line in forge/config.py.

Controls, run every time: a key put in the wrong file of the table (the common env into the memory file, which `load` does not read
there) must change what the world generates, or the comparison could not see a misplaced key; one of the keys put in both places
exits 1 in the world too.

Seen failing (forge/config.py with LAYOUT and `load` but lib.settings() not composed with it), part 2 only, with the new layout's
common keys never merged into lib.settings():
  skill_keep missing in new layout -- lib.settings() of the new-layout world lacks it (the old one has it)
  dry-run text differs between layouts -- the old world prints its pending writes from the common tables, the new one from none
Mutation of this suite's own (load ignores the new place: `new = None` in _found): the same two, plus every concept check of
part 1 ("<concept>: load is the same in both layouts").
"""
import copy
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

sys.path.insert(0, sandbox.FORGE)
from forge import config, lib  # noqa: E402

failures, notrun, counts = [], [], {}


def check(label, ok, detail="", group=None):
    group = group or label.split(":")[0]
    counts[group] = counts.get(group, 0) + 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))


def read_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def put(doc, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


def pop(doc, path):
    parts = path.split(".")
    for part in parts[:-1]:
        doc = doc[part]
    return doc.pop(parts[-1])


def rows(concept, served_only=False):
    """[(old file, old path, new file, new path)] of a concept whose rows move to another file."""
    entry = config.LAYOUT[concept]
    out = []
    for old_file, rs in entry["old"].items():
        for row in rs:
            old_path, new_path = (row, row) if isinstance(row, str) else row
            if old_file != entry["new"] and not (served_only and old_file != config.ENGINE):
                out.append((old_file, old_path, entry["new"], new_path))
    return out


def moving(served_only=False):
    return [c for c in config.LAYOUT if c != "projects" and rows(c, served_only)]


# ---------------------------------------------------------------- the layouts, written by this file

def value_of(concept, path):
    return {"toy": concept} if path == "" else "%s:%s" % (concept, path)


def write_old(directory):
    """The old layout: a value at every row of the table, in the file the table names."""
    files = {}
    for concept in config.LAYOUT:
        if concept == "projects":
            continue
        for old_file, old_path, new_path in config._rows(config.LAYOUT[concept]):
            doc = files.setdefault(old_file, {})
            if old_path == "":
                files[old_file] = value_of(concept, "")
            else:
                put(doc, old_path, value_of(concept, old_path))
    for name, doc in files.items():
        write_json(os.path.join(directory, name), doc)
    entry = config.LAYOUT["projects"]
    for name in ("alpha", "beta"):
        write_json(os.path.join(directory, entry["old"], name + entry["old_suffix"]), {"project": name})


def to_new(directory, served_only=False):
    """Rewrite an old layout (a directory of files, or a forge.json holding what the engine serves) into the new one, by the table."""
    for concept in moving(served_only):
        new_doc = {}
        for old_file, old_path, new_file, new_path in rows(concept, served_only):
            path = os.path.join(directory, old_file)
            doc = read_json(path)
            if old_path == "":
                value = doc
                os.remove(path)
            else:
                value = pop(doc, old_path)
                write_json(path, doc)
            put(new_doc, new_path, value)
        write_json(os.path.join(directory, config.LAYOUT[concept]["new"]), new_doc)
    if not served_only:
        entry = config.LAYOUT["projects"]
        old, new = os.path.join(directory, entry["old"]), os.path.join(directory, entry["new"])
        os.makedirs(new)
        for n in os.listdir(old):
            os.rename(os.path.join(old, n), os.path.join(new, n[:-len(entry["old_suffix"])] + entry["new_suffix"]))
        os.rmdir(old)


def asking(directory, expr):
    """(exit code or None, what it printed or its result) of `expr`, evaluated in a fresh interpreter whose lib.SETTINGS is
    directory/forge.json: lib.settings() caches per path, and a SystemExit is the contract."""
    code = ("import json, sys\nfrom forge import config, lib\nlib.SETTINGS = %r\n"
            "print(json.dumps(%s, sort_keys=True))\n" % (os.path.join(directory, config.ENGINE), expr))
    r = subprocess.run([sys.executable, "-c", code], cwd=sandbox.FORGE, capture_output=True, text=True,
                       env=sandbox.bare_env(directory, directory))
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr.strip())


def part1():
    tmp = sandbox.mkdtemp("config-layout-toy-")
    old, new = os.path.join(tmp, "old"), os.path.join(tmp, "new")
    os.makedirs(old)
    write_old(old)
    shutil.copytree(old, new)
    to_new(new)
    check("toy: the table moves rows", len(moving()) >= 4, "moving concepts %s" % moving())
    check("toy: the new layout has a file per moving concept",
          all(os.path.isfile(os.path.join(new, config.LAYOUT[c]["new"])) for c in moving()), os.listdir(new))
    for concept in config.LAYOUT:
        a, b = (config.load(concept, d) for d in (old, new))
        check("%s: load is the same in both layouts" % concept, a == b and bool(a), "old %r, new %r" % (a, b))
    code_a, a = asking(old, "lib.settings()")
    code_b, b = asking(new, "lib.settings()")
    check("settings: lib.settings() is the same in both layouts", code_a == code_b == 0 and a == b,
          "old %s %s, new %s %s" % (code_a, a[:200], code_b, b[:200]))
    want = json.loads(a)
    check("settings: every row the engine served is in lib.settings() of the new layout",
          all(config._get(want, path) is not config._MISSING for c in moving(True) for _, path, _, _ in rows(c, True)), "")
    # one place each: the engine file of the new layout no longer holds a moved key
    served = [(c, r) for c in moving(True) for r in rows(c, True)]
    engine = read_json(os.path.join(new, config.ENGINE))
    check("toy: the new engine file holds none of the keys that moved out",
          all(config._get(engine, r[1]) is config._MISSING for _, r in served) and bool(served), "")

    # a key in both places: every moved row, put back in the old place beside the new one
    for concept in moving():
        for old_file, old_path, new_file, new_path in rows(concept):
            both = os.path.join(tmp, "both")
            shutil.copytree(new, both)
            p = os.path.join(both, old_file)
            doc = read_json(p) if os.path.exists(p) else {}
            if old_path == "":
                doc = value_of(concept, "")
            else:
                put(doc, old_path, "twin")
            write_json(p, doc)
            name = old_path or os.path.splitext(old_file)[0]
            code, out = asking(both, "config.load(%r, %r)" % (concept, both))
            check("both: %s of %s in two places exits 1 naming both files" % (name, concept),
                  code == 1 and old_file in out and new_file in out and "in both" in out, "exit %s, %s" % (code, out[-200:]))
            if old_file == config.ENGINE:
                code, out = asking(both, "lib.settings()")
                check("both: lib.settings() exits 1 too for %s" % name, code == 1 and "in both" in out, "exit %s, %s" % (code, out[-200:]))
            shutil.rmtree(both)
    # the projects folder: a name in both
    entry = config.LAYOUT["projects"]
    both = os.path.join(tmp, "both")
    shutil.copytree(new, both)
    write_json(os.path.join(both, entry["old"], "alpha" + entry["old_suffix"]), {})
    code, out = asking(both, "config.load('projects', %r)" % both)
    check("both: a project in two folders exits 1", code == 1 and "alpha" in out and "in both" in out, "exit %s, %s" % (code, out))
    check("projects: both folders are listed", sorted(config.load("projects", old)) == sorted(config.load("projects", new))
          == ["alpha", "beta"], "")
    shutil.rmtree(both)

    # lib.settings() before and after: what a missing, broken or odd forge.json says
    for label, text, want_text in (
            ("missing", None, "! config/forge.json missing -- run bin/forge init"),
            ("unreadable", "{", "! config/forge.json unreadable (Expecting property name enclosed in double quotes: line 1 column 2"),
            ("not an object", "[]", "! config/forge.json unreadable (top level is list, not an object)")):
        d = os.path.join(tmp, "odd-" + label.replace(" ", "-"))
        os.makedirs(d)
        if text is not None:
            with open(os.path.join(d, config.ENGINE), "w") as fh:
                fh.write(text)
        code, out = asking(d, "lib.settings()")
        check("errors: a %s forge.json exits 1 with its message" % label, code == 1 and out.startswith(want_text), "exit %s, %s" % (code, out))
    d = os.path.join(tmp, "odd-new")
    shutil.copytree(new, d)
    with open(os.path.join(d, config.LAYOUT["common"]["new"]), "w") as fh:
        fh.write("[]")
    code, out = asking(d, "lib.settings()")
    check("errors: a new file that is not an object exits 1", code == 1 and config.LAYOUT["common"]["new"] in out, "exit %s, %s" % (code, out))
    code, out = asking(new, "config.load('nope', %r)" % new)
    check("errors: an unknown concept is a ValueError", code == 1 and "ValueError: unknown concept 'nope'" in out, "exit %s, %s" % (code, out[-200:]))
    # a toy world's forge-0.json, with files of the new layout beside it, is read as the engine file
    d = os.path.join(tmp, "named")
    shutil.copytree(new, d)
    os.rename(os.path.join(d, config.ENGINE), os.path.join(d, "forge-0.json"))
    r = subprocess.run([sys.executable, "-c", "import json; from forge import lib; lib.SETTINGS = %r; print(json.dumps(lib.settings(), sort_keys=True))"
                        % os.path.join(d, "forge-0.json")], cwd=sandbox.FORGE, capture_output=True, text=True, env=sandbox.bare_env(d, d))
    check("settings: a differently named engine file is the engine file", r.returncode == 0 and r.stdout.strip() == a,
          "exit %s, %s" % (r.returncode, r.stderr.strip()[-200:]))


# ---------------------------------------------------------------- the world

class World:
    def __init__(self, tag, new_layout, misplace=False):
        self.top = sandbox.mkdtemp("config-layout-%s-" % tag)
        self.forge, self.home = os.path.join(self.top, "forge"), os.path.join(self.top, "home")
        self.projects, self.bin = os.path.join(self.top, "projects"), os.path.join(self.top, "bin")
        self.log = os.path.join(self.top, "claude.log")
        sandbox.copy_engine(self.forge)
        sandbox.seed(self.forge)
        os.makedirs(self.home)
        sandbox.stub_claude(self.bin, self.log)
        sandbox.stub_systemctl(self.bin, os.path.join(self.top, "systemctl.log"))
        cfg = os.path.join(self.forge, "config")
        self.settings = self._settings(cfg)
        self._profiles(cfg)
        self._secrets()
        self._home()
        if new_layout:
            to_new(cfg, served_only=True)
            if misplace:  # the common env goes to a file that is not its file in the table
                common = os.path.join(cfg, config.LAYOUT["common"]["new"])
                doc, wrong = read_json(common), os.path.join(cfg, config.LAYOUT["memory"]["new"])
                other = read_json(wrong) if os.path.exists(wrong) else {}
                other["common_env"] = doc.pop("common_env")
                write_json(wrong, other)
                write_json(common, doc)
        # the generator refuses to write where the checkout is not a git repository (its write deny), as a stranger's is
        for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "world")):
            sandbox.git(self.forge, *args)

    def _settings(self, cfg):
        """The fixture's forge.json with a value for every concept the engine serves, the framework included."""
        src = os.path.join(self.top, "plugin-src")
        write_json(os.path.join(src, ".claude-plugin", "marketplace.json"), {"name": "toyfw", "plugins": [{"name": "toyfw", "source": "./"}]})
        p = os.path.join(cfg, config.ENGINE)
        doc = read_json(p)
        doc["session_wait"] = {"project": "toy", "health": "http://127.0.0.1:1/health", "unit": "toy.service"}
        doc["lock_exclude"] = ["toy"]
        doc["skill_keep"]["common_env"]["TOY_SECOND"] = "2"
        doc["skill_keep"]["sets"] = {"toy-set": ["toy-common"]}
        doc["framework"] = {
            "plugin_source": {"source": "directory", "path": src},
            "models": {"worker": {"small": "haiku", "medium": "sonnet", "large": "opus"}},
            "limits": {"default_cap": 3},
            "rounds": {"critique": 2},
            "critique_rounds_unattended": 1,
            "factory": {"label": "toy-factory"},
            "weekly": {"day": "mon"},
            "paths": {"verdict": "toy-verdicts"},
            "linear": {"team": "toy-team", "labels": {"toy": "toy"}},
        }
        write_json(p, doc)
        return doc

    def _profiles(self, cfg):
        fw = {"project": "fw", "project_path": "x", "framework": True, "enableAllProjectMcpServers": True, "servers": [], "env": {},
              "plugins_keep": ["toyfw@toyfw"], "skills_keep": ["toy-common"], "permissions": {}}
        write_json(os.path.join(cfg, "profiles", "fw.claude.json"), fw)
        for n in sorted(os.listdir(os.path.join(cfg, "profiles"))):
            p = os.path.join(cfg, "profiles", n)
            name, prof = n[:-len(".claude.json")], read_json(p)
            if prof.get("frozen"):
                os.remove(p)  # the freeze is not what this world is about
                continue
            prof["project_path"] = os.path.join(self.projects, name)
            write_json(p, prof)
            os.makedirs(os.path.join(self.projects, name))
            sandbox.git(os.path.join(self.projects, name), "init", "-q")

    def _secrets(self):
        write_json(os.path.join(self.forge, "credentials", "secrets.json"), {})
        os.chmod(os.path.join(self.forge, "credentials", "secrets.json"), 0o600)
        os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(self.forge, "config", "secrets.json"))

    def _home(self):
        """The Hindsight runtime the toy config asks for is a stub file, as in tests/test_sync_fixture.py's world."""
        hs = os.path.join(self.home, ".hindsight", "coding-agents")
        os.makedirs(os.path.join(hs, "dist"))
        with open(os.path.join(hs, "dist", "claude-hook.js"), "w") as fh:
            fh.write("// stub runtime; knows autoInject\n")
        write_json(os.path.join(hs, ".install-origin.json"), {"commit": "63da8d7" + "0" * 33})
        os.makedirs(os.path.join(self.home, ".vscode", "extensions"))

    def env(self):
        return sandbox.bare_env(self.home, self.top, self.bin)

    def forge_cmd(self, *args):
        r = subprocess.run(["unshare", "-rn", sys.executable, os.path.join(self.forge, "bin", "forge")] + list(args), cwd=self.forge,
                           env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
        return r.returncode, r.stdout.replace(self.top, "@S@")

    def dump_settings(self):
        r = subprocess.run([sys.executable, "-c", "import json; from forge import lib; print(json.dumps(lib.settings(), sort_keys=True))"],
                           cwd=self.forge, env=self.env(), capture_output=True, text=True)
        return r.returncode, r.stdout.strip() if r.returncode == 0 else r.stderr.strip()

    def hashes(self):
        """{path: (type, mode, sha256)} of the toy HOME and the projects, the root masked; the ownership record without its sums."""
        m = sandbox.manifest(self.top, ("home", "projects"), mask=True)
        rel = os.path.join("home", ".local", "state", "forge", "owned.json")
        if rel in m and m[rel][0] == "f":
            import hashlib
            doc = read_json(os.path.join(self.top, rel))
            for claims in doc.get("claims", {}).values():
                for c in claims:
                    c.pop("sum", None)
            m[rel] = m[rel][:2] + (hashlib.sha256(json.dumps(doc, sort_keys=True).replace(self.top, "@S@").encode()).hexdigest(),) + m[rel][3:]
        return {k: v[:3] for k, v in m.items()}


def part2():
    ok, why = sandbox.unshare_ok()
    if not ok:
        notrun.append("part 2: NOT RUN, NOT ARMED: no empty network namespace here (%s)" % why)
        return
    runs = {}
    for tag, new_layout, misplace in (("old", False, False), ("new", True, False), ("misplaced", True, True)):
        w = World(tag, new_layout, misplace)
        code, dry = w.forge_cmd("sync", "--all")
        runs[tag] = {"world": w, "dry": (code, dry), "settings": w.dump_settings()}
        code, applied = w.forge_cmd("sync", "--all", "--apply")
        runs[tag]["apply"] = (code, applied)
        runs[tag]["hashes"] = w.hashes()
    old, new, bad = runs["old"], runs["new"], runs["misplaced"]
    lines = old["dry"][1].count("\n")
    check("world: the old layout's dry-run looked at the projects", lines > 5 and "fw" in old["dry"][1], "%d lines: %s" % (lines, old["dry"][1][-300:]))
    check("world: the old layout's files were generated", len(old["hashes"]) > 20, "%d files" % len(old["hashes"]))
    check("world: the old layout's --apply exits like its dry-run", old["apply"][0] == old["dry"][0], "%s, then %s: %s" % (old["dry"][0], old["apply"][0], old["apply"][1][-200:]))
    check("world: a toy world is no machine's", "unreadable" not in old["dry"][1], old["dry"][1][-200:])

    sa, sb_ = old["settings"], new["settings"]
    check("settings: both worlds can be read", sa[0] == 0 and sb_[0] == 0, "%s | %s" % (sa[1][-200:], sb_[1][-200:]))
    if sa[0] == 0 and sb_[0] == 0:
        a, b = json.loads(sa[1]), json.loads(sb_[1])
        for key in sorted(a):  # each key, and each key of a table one level down: `skill_keep` is there with only the keys that stayed
            leaves = [(key, a[key], b.get(key, config._MISSING))]
            if isinstance(a[key], dict) and isinstance(b.get(key), dict):
                leaves = [(key + "." + sub, v, b[key].get(sub, config._MISSING)) for sub, v in sorted(a[key].items())]
            for name, want_value, got in leaves:
                check("%s missing in new layout" % name if got is config._MISSING else "settings: %s present in new layout" % name,
                      got is not config._MISSING, "lib.settings() of the new-layout world lacks it (the old one has it)", "settings")
                check("settings: %s is equal in both layouts" % name, got is config._MISSING or got == want_value,
                      "old %r, new %r" % (want_value, got), "settings")
    check("world: the new layout's dry-run text is the old layout's", old["dry"] == new["dry"],
          "old %s, new %s" % (sandbox.tail(old["dry"][1], 3), sandbox.tail(new["dry"][1], 3)))
    check("world: the new layout's --apply text is the old layout's", old["apply"] == new["apply"],
          "old %s, new %s" % (sandbox.tail(old["apply"][1], 3), sandbox.tail(new["apply"][1], 3)))
    diff = sorted(k for k in set(old["hashes"]) | set(new["hashes"]) if old["hashes"].get(k) != new["hashes"].get(k))
    check("world: every generated file is byte-identical in both layouts (%d files)" % len(old["hashes"]), not diff, diff[:6])

    # the controls
    moved = sorted(k for k in set(old["hashes"]) | set(bad["hashes"]) if old["hashes"].get(k) != bad["hashes"].get(k))
    projects_moved = [k for k in moved if k.startswith("projects/")]
    check("control: misplaced key not detected", bool(projects_moved), "the common env in the memory file changed no project file (moved: %s)" % moved)
    print("control: the common env in the wrong file changes %d generated project file(s), first %s" % (len(projects_moved), projects_moved[:1]))
    w = new["world"]
    p = os.path.join(w.forge, "config", config.ENGINE)
    doc = read_json(p)
    put(doc, "skill_keep.sets", {"twin": []})
    write_json(p, doc)
    code, out = w.forge_cmd("sync", "--all")
    check("control: a key in two places exits 1 in the world too", code == 1 and "in both" in out, "exit %s: %s" % (code, sandbox.tail(out, 2)))


try:
    part1()
    part2()
finally:
    sandbox.cleanup()

if notrun:
    print("\n".join(notrun))
if failures:
    print("\n".join("FAIL: " + f for f in failures))
    sys.exit(1)
print("config layout: %s -- ok" % ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())))
