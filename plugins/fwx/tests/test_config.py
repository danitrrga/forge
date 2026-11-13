#!/usr/bin/env python3
"""lib/fwx/config.py: the one reader of the generated .claude/fwx.json.

A worktree finds the main checkout's file, defaults apply when the file is missing (one stderr line per
process), a bad file is a ConfigError that names the fix, and the Linear label mapping works both ways.

Seen red before config.py existed (the file was not there):
  Traceback ...: ImportError: cannot import name 'config' from 'fwx' (lib/fwx/__init__.py)

Controls seen red, each on a copy of config.py changed in one place (78 checks each):
  - the file read from the cwd instead of the main checkout (the plan's control), 9 failed:
      FAIL: load from a worktree subfolder: the file's rounds: got 3, want 7
      FAIL: load from a worktree subfolder: _source is the main checkout's file: got None, want '<main>/.claude/fwx.json'
      FAIL: the file's model: got 'sonnet', want 'haiku'
  - no alias check on a model (the plan's control: the full id is accepted):
      FAIL: a full model id is a ConfigError: load accepted it
  - no schema check:
      FAIL: schema 2 is a ConfigError: load accepted it
  - label_to_linear that ignores the mapping (the plan's control):
      FAIL: label_to_linear maps a neutral name: got 'needs-owner', want 'toy-needs-help'
  - no check for two neutral names sent to one Linear name:
      FAIL: two neutral names to one Linear name: label_to_linear raises: returned
  - the missing-file line printed on every call:
      FAIL: no file, second call: no more lines: got 'fwx: no .claude/fwx.json at <main>/.claude/fwx.json; using defaults\\n', want ''
"""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import config  # noqa: E402

for k in [k for k in os.environ if k.startswith("GIT_")]:  # a hook run exports GIT_DIR: not for these toy repos
    del os.environ[k]

s = helpers.Suite()


def put(main, data):
    text = data if isinstance(data, str) else json.dumps(data)
    return helpers.write(main, ".claude/fwx.json", text)


def load(cwd):
    """(cfg, stderr) of config.load(cwd=cwd); cfg is the ConfigError when it raises."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            cfg = config.load(cwd=cwd)
        except config.ConfigError as e:
            cfg = e
    return cfg, err.getvalue()


def refuses(label, cwd, needle):
    cfg, _ = load(cwd)
    if not s.ok("%s is a ConfigError" % label, isinstance(cfg, config.ConfigError), "load accepted it"):
        return
    s.ok("%s: the message names %r" % (label, needle), needle in str(cfg), "message: %s" % cfg)
    s.ok("%s: the message names the fix" % label, "forge sync" in str(cfg), "message: %s" % cfg)


# --- the file of the main checkout, found from a worktree
main = helpers.toy_repo()
wt = helpers.add_worktree(main, "side")
sub = os.path.join(wt, "src", "deep")
os.makedirs(sub)
path = put(main, {"schema": 1, "rounds": 7, "models": {"executor": {"small": "haiku"}},
                  "project": {"name": "toyfw"}})
cfg, err = load(sub)
s.eq("load from a worktree subfolder: the file's rounds", cfg.get("rounds") if isinstance(cfg, dict) else cfg, 7)
s.eq("load from a worktree subfolder: _source is the main checkout's file",
     cfg.get("_source") if isinstance(cfg, dict) else cfg, path)
s.eq("load from a worktree subfolder: stderr is quiet", err, "")
if isinstance(cfg, dict):
    s.eq("the file's model", cfg["models"]["executor"]["small"], "haiku")
    s.eq("a role the file lacks keeps the seed", cfg["models"]["planner"], config.DEFAULTS["models"]["planner"])
    s.eq("a size the file lacks keeps the seed", cfg["models"]["executor"]["big"],
         config.DEFAULTS["models"]["executor"]["big"])
    s.eq("the file's project name", cfg["project"]["name"], "toyfw")
    s.eq("a key the file lacks keeps its default", cfg["critique_rounds_unattended"],
         config.DEFAULTS["critique_rounds_unattended"])
s.eq("main_checkout from a worktree subfolder", config.main_checkout(sub), main)
s.eq("main_checkout from the main checkout", config.main_checkout(main), main)
cfg2, _ = load(main)
s.eq("load from the main checkout: the same file", cfg2.get("_source") if isinstance(cfg2, dict) else cfg2, path)

# --- no file: defaults, one line per process
bare = helpers.toy_repo()
bare_wt = helpers.add_worktree(bare, "side")
config._warned = False
cfg, err = load(bare_wt)
want_line = "fwx: no .claude/fwx.json at %s; using defaults\n" % os.path.join(bare, ".claude", "fwx.json")
s.eq("no file: one stderr line", err, want_line)
cfg3, err3 = load(bare_wt)
s.eq("no file, second call: no more lines", err3, "")
if isinstance(cfg, dict):
    s.eq("no file: _source is None", cfg["_source"], None)
    s.eq("no file: the seed models", cfg["models"], config.DEFAULTS["models"])
    s.eq("no file: the project name is the main checkout's folder", cfg["project"]["name"], os.path.basename(bare))
    s.eq("no file: the project main_checkout", cfg["project"]["main_checkout"], bare)
    s.eq("no file: schema", cfg["schema"], 1)
    s.eq("no file: empty label mapping", cfg["linear"]["labels"], {})
    cfg["models"]["executor"]["small"] = "changed"
    s.ok("no file: the caller's edits do not reach DEFAULTS", config.DEFAULTS["models"]["executor"]["small"] != "changed")

# --- a bad file is a ConfigError with the fix
bad = helpers.toy_repo()
put(bad, {"schema": 2})
refuses("schema 2", bad, "schema")
put(bad, {"schema": 1, "models": {"nosuch": {"small": "sonnet"}}})
refuses("an unknown role", bad, "nosuch")
put(bad, {"schema": 1, "models": {"executor": {"huge": "sonnet"}}})
refuses("an unknown size", bad, "huge")
put(bad, {"schema": 1, "models": {"executor": {"small": "claude-sonnet-5-5"}}})
refuses("a full model id", bad, "claude-sonnet-5-5")
put(bad, {"schema": 1, "models": {"executor": "sonnet"}})
refuses("a role that is not a table of sizes", bad, "executor")
put(bad, "{not json")
refuses("a file that is not JSON", bad, "fwx.json")
put(bad, "[1, 2]")
refuses("a file that is not an object", bad, "fwx.json")
put(bad, {"schema": 1, "models": {"executor": {"small": "fable"}}})
cfg, _ = load(bad)
s.ok("an alias the engine knows is accepted (fable)", isinstance(cfg, dict), str(cfg))
for alias in ("sonnet", "opus", "haiku", "fable"):
    s.ok("%s is an alias" % alias, alias in config.ALIASES)

# --- outside a git repo
outside = helpers.mkdtemp("fwx-nogit-")
os.environ["GIT_CEILING_DIRECTORIES"] = outside  # a /tmp inside some repo must not turn this into a repo
try:
    cfg, _ = load(outside)
    s.ok("outside a git repo is a ConfigError", isinstance(cfg, config.ConfigError), "load returned a configuration")
    s.ok("outside a git repo: the message says so", isinstance(cfg, Exception) and "git" in str(cfg), "load returned a configuration")
    try:
        config.main_checkout(outside)
        s.ok("main_checkout outside a repo raises", False, "returned")
    except config.ConfigError:
        s.ok("main_checkout outside a repo raises", True)
    try:
        config.main_checkout(os.path.join(outside, "missing"))
        s.ok("main_checkout of a missing folder raises", False, "returned")
    except config.ConfigError:
        s.ok("main_checkout of a missing folder raises", True)
finally:
    del os.environ["GIT_CEILING_DIRECTORIES"]

# --- roles, sizes, model()
s.eq("sizes", config.SIZES, ("small", "normal", "big"))
s.eq("21 roles", len(config.ROLES), 21)
for role in ("orchestrator", "pre-mortem", "planner", "executor", "review-verifier", "ui-walker", "vision"):
    s.ok("role %s" % role, role in config.ROLES)
s.eq("the seed has every role and size", sorted((r, z) for r in config.ROLES for z in config.SIZES),
     sorted((r, z) for r, v in config.DEFAULTS["models"].items() for z in v))
s.ok("every seeded model is an alias",
     all(m in config.ALIASES for v in config.DEFAULTS["models"].values() for m in v.values()))
cfg = config.DEFAULTS
s.eq("seed: planner is opus", config.model(cfg, "planner", "normal"), "opus")
s.eq("seed: pre-mortem is sonnet", config.model(cfg, "pre-mortem", "normal"), "sonnet")
s.eq("seed: detector is haiku", config.model(cfg, "detector", "normal"), "haiku")
s.eq("seed: executor is sonnet", config.model(cfg, "executor", "big"), "sonnet")
for role, size, what in (("nosuch", "small", "role"), ("executor", "huge", "size")):
    try:
        config.model(cfg, role, size)
        s.ok("model(%s, %s) raises" % (role, size), False, "returned")
    except config.ConfigError as e:
        s.ok("model(%s, %s): the message lists the valid %ss" % (role, size, what),
             all(x in str(e) for x in (config.ROLES if what == "role" else config.SIZES)), str(e))

# --- Linear labels (neutral name <-> the user's name)
mapped = {"linear": {"labels": {"needs-owner": "toy-needs-help"}}}
s.eq("label_to_linear maps a neutral name", config.label_to_linear(mapped, "needs-owner"), "toy-needs-help")
s.eq("label_from_linear maps back", config.label_from_linear(mapped, "toy-needs-help"), "needs-owner")
s.eq("label_to_linear without an entry is the same name", config.label_to_linear(mapped, "blocked"), "blocked")
s.eq("label_from_linear without an entry is the same name", config.label_from_linear(mapped, "blocked"), "blocked")
s.eq("an empty mapping is the same name", config.label_to_linear({"linear": {"labels": {}}}, "needs-owner"), "needs-owner")
for label, labels in (("two neutral names to one Linear name", {"a": "same", "b": "same"}),
                      ("a value that is not a string", {"a": 3}),
                      ("a mapping that is not a table", ["a"])):
    for fn in (config.label_to_linear, config.label_from_linear):
        try:
            fn({"linear": {"labels": labels}}, "a")
            s.ok("%s: %s raises" % (label, fn.__name__), False, "returned")
        except config.ConfigError as e:
            s.ok("%s: %s raises" % (label, fn.__name__), "forge sync" in str(e) or "labels" in str(e), str(e))

# --- the cap of agents at once: a number in the configuration, nothing measured (D90)
# Seen red on master (no config.cap, and `limits` still carrying the two RAM keys and `on`):
#   Traceback ...: AttributeError: module 'fwx.config' has no attribute 'cap'
#   FAIL: limits keeps no RAM key: got ['default_cap', 'on', 'per_project', 'ram_min_free_gb', 'ram_per_agent_mb'], want ['default_cap', 'per_project']
capdir = helpers.toy_repo()
cfg, _ = load(capdir)
s.eq("limits keeps no RAM key and no switch", sorted(cfg["limits"]) if isinstance(cfg, dict) else cfg, ["default_cap", "per_project"])
has_cap = hasattr(config, "cap")
s.ok("config.cap exists", has_cap, "no such function")
if has_cap:
    s.eq("no limits in the file: the documented default, 3 with the owner present", config.cap(cfg, "executor"), 3)
    s.eq("no limits in the file: the documented default, 4 with nobody present", config.cap(cfg, "executor", unattended=True), 4)
    s.eq("a role with no per_project row takes the default", config.cap(cfg, "ui-walker"), 3)
    # the old RAM keys, `on` and a key nobody knows are ignored, with no error and no change of the cap
    put(capdir, {"schema": 1, "limits": {"on": False, "ram_min_free_gb": 3, "ram_per_agent_mb": 512, "nosuch": 1,
                                         "default_cap": {"supervised": 2, "unattended": 6}, "per_project": {"ui-walker": 5}}})
    old, _ = load(capdir)
    s.ok("a file with the removed limits keys loads", isinstance(old, dict), "ConfigError: %s" % old)
    if isinstance(old, dict):
        s.eq("the removed keys: the cap is read, supervised", config.cap(old, "executor"), 2)
        s.eq("the removed keys: the cap is read, unattended", config.cap(old, "executor", unattended=True), 6)
        s.eq("limits.on false is ignored: never an unlimited run", config.cap(old, "executor"), 2)
        s.eq("per_project of a role wins over default_cap", (config.cap(old, "ui-walker"), config.cap(old, "ui-walker", unattended=True)), (5, 5))
    # a value that is no positive whole number is an error that names the key, never "unlimited" (a missing, null, 0, text, float or boolean cap)
    for what, limits, needle in (("default_cap null", {"default_cap": None}, "limits.default_cap"),
                                 ("default_cap a number", {"default_cap": 3}, "limits.default_cap"),
                                 ("supervised 0", {"default_cap": {"supervised": 0}}, "limits.default_cap.supervised"),
                                 ("supervised text", {"default_cap": {"supervised": "3"}}, "limits.default_cap.supervised"),
                                 ("supervised float", {"default_cap": {"supervised": 2.5}}, "limits.default_cap.supervised"),
                                 ("supervised true", {"default_cap": {"supervised": True}}, "limits.default_cap.supervised"),
                                 ("unattended null", {"default_cap": {"unattended": None}}, "limits.default_cap.unattended"),
                                 ("per_project not a table", {"per_project": [1]}, "limits.per_project"),
                                 ("per_project row 0", {"per_project": {"executor": 0}}, "limits.per_project.executor"),
                                 ("limits not a table", "many", "limits")):
        put(capdir, {"schema": 1, "limits": limits})
        c, _ = load(capdir)
        got = None
        if isinstance(c, dict):
            try:
                got = config.cap(c, "executor", unattended="unattended" in what)
                msg = "returned %r" % (got,)
            except config.ConfigError as e:
                got, msg = e, str(e)
            s.ok("%s: a ConfigError naming %s" % (what, needle), isinstance(got, config.ConfigError) and needle in msg, msg)
        else:
            s.ok("%s: a ConfigError naming %s" % (what, needle), needle in str(c), str(c))
    try:
        config.cap(cfg, "nosuch")
        s.ok("an unknown role raises", False, "returned")
    except config.ConfigError as e:
        s.ok("an unknown role: the message lists the roles", all(r in str(e) for r in config.ROLES), str(e))

s.done()
