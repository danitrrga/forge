#!/usr/bin/env python3
"""A toy HOME writes nothing when the environment points a write destination outside the toy world (DTC-57).

The incident: `forge toolchain --fix` ran with a faked HOME while the real XDG_CONFIG_HOME was still in the
environment, so toolchain.mise_file() resolved to the real mise file and replaced it. lib.may_write() said yes:
its toy-HOME rule only looked at where the projects point. It now also refuses when a variable the engine takes a
write destination from (lib.WRITE_ENV) is set and points outside both HOME and the world.

Seen failing against the code before the rule (lib.WRITE_ENV and the branch in may_write did not exist):
  "may_write, XDG_CONFIG_HOME outside the world = (True, ''), want (False, 'forge: HOME is a sandbox (<home>) but
   XDG_CONFIG_HOME points outside it (<outside>) -- nothing written')" (the same for MISE_CONFIG_DIR,
   MISE_PYTHON_DEFAULT_PACKAGES_FILE and CODEX_HOME, and for a sibling directory that only shares the world's name as a
   prefix);
  "the incident: forge toolchain --fix, XDG_CONFIG_HOME outside = (exit, outside file, refusal printed) = (0,
   '<the file, rewritten>', False), want (1, '<its old bytes>', True)" -- the outside file was replaced;
  "bare_env sets XDG_CONFIG_HOME = None" (and XDG_DATA_HOME, XDG_CACHE_HOME, MISE_CONFIG_DIR).
Mutant (the loop in may_write removed): controls 1 and 2 fail with those same messages; the positive controls, the
real-HOME control and the bare_env control stay green, which is what they are for.

Everything here runs in this process on a toy world: lib.ROOT, lib.HOME and lib.PROJECTS point at dirs of the test, and
the four variables a toy world needs (XDG_CONFIG_HOME, XDG_DATA_HOME, XDG_CACHE_HOME, MISE_CONFIG_DIR) are set inside
the toy HOME before anything runs; the one variable under test points at a second temp dir of the test, never at a
real path. The incident case unsets MISE_CONFIG_DIR, which would otherwise win over XDG_CONFIG_HOME in
toolchain.mise_file(), and asserts where the file resolves before the run that can write.
"""
import contextlib
import io
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib, toolchain  # noqa: E402
import sandbox  # noqa: E402
import test_toolchain as tt  # noqa: E402

failures = []
REFUSAL = "forge: HOME is a sandbox (%s) but %s points outside it (%s) -- nothing written"
# the variables of lib.WRITE_ENV, each with the shape of what it names
FILE_VARS = {"MISE_PYTHON_DEFAULT_PACKAGES_FILE"}
TOY_VARS = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "MISE_CONFIG_DIR")
VARS = ("XDG_CONFIG_HOME", "MISE_CONFIG_DIR", "MISE_PYTHON_DEFAULT_PACKAGES_FILE", "CODEX_HOME")


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def value(var, base):
    return os.path.join(base, "default-python-packages") if var in FILE_VARS else os.path.join(base, var.lower())


def with_env(**env):
    """Context manager: os.environ with each of `env` set (None removes it), put back after."""
    @contextlib.contextmanager
    def cm():
        saved = {k: os.environ.get(k) for k in env}
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return cm()


def toy_env(home):
    """The four variables of a toy world, inside the toy HOME, and the other write variables cleared."""
    env = dict.fromkeys(VARS)
    env.update({"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"), "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
                "XDG_CACHE_HOME": os.path.join(home, ".cache"), "MISE_CONFIG_DIR": os.path.join(home, ".config", "mise")})
    return env


def refusal_cases(world, home, outside):
    # 1: each variable outside the world is refused, and the line names it and its value
    for var in VARS:
        val = value(var, outside)
        with with_env(**dict(toy_env(home), **{var: val})):
            want("may_write, %s outside the world" % var, lib.may_write(), (False, REFUSAL % (home, var, val)))
    # a sibling that only shares the world's name as a prefix is outside it (whole components)
    lookalike = world + "-elsewhere"
    with with_env(**dict(toy_env(home), XDG_CONFIG_HOME=lookalike)):
        want("may_write, XDG_CONFIG_HOME in a sibling that shares the world's prefix", lib.may_write(),
             (False, REFUSAL % (home, "XDG_CONFIG_HOME", lookalike)))
    # 3: the positive control: the same variable inside the toy HOME, and inside the world beside it, is allowed
    for var in VARS:
        for label, base in (("HOME", home), ("the world", os.path.join(world, "shared"))):
            with with_env(**dict(toy_env(home), **{var: value(var, base)})):
                want("may_write, %s inside %s" % (var, label), lib.may_write(), (True, ""))
    with with_env(**toy_env(home)):
        want("may_write, the toy world's own variables", lib.may_write(), (True, ""))
    # an empty value is no value: toolchain.py and codex read `VAR or default`
    with with_env(**dict(toy_env(home), XDG_CONFIG_HOME="")):
        want("may_write, XDG_CONFIG_HOME empty", lib.may_write(), (True, ""))
    # 4: with the real HOME nothing changes: a set variable pointing anywhere refuses nothing
    real_pwd = getattr(lib, "pwd", None)
    lib.pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_dir=lib.HOME))
    try:
        for var in VARS:
            with with_env(**dict(toy_env(home), **{var: value(var, outside)})):
                want("the real HOME, %s outside: may_write" % var, lib.may_write(), (True, ""))
    finally:
        lib.pwd = real_pwd


def toolchain_run(w, argv, xdg_config_home, home):
    """(exit code, output lines) of cli.main(argv) in this process with the REAL lib.may_write, on the fake machine's PATH.
    The environment is the toy world's (toy_env), XDG_CONFIG_HOME as given and MISE_CONFIG_DIR unset (it would win over
    XDG_CONFIG_HOME in toolchain.mise_file(), and the incident's environment had none)."""
    env = dict(w.env(), **toy_env(home))
    env.update({"XDG_CONFIG_HOME": xdg_config_home, "MISE_CONFIG_DIR": None,
                "MISE_PYTHON_DEFAULT_PACKAGES_FILE": w.pip_file})
    saved = (toolchain.MANIFEST, cli.CHECKS, lib.STATE, lib.LOCK, lib.JOURNAL)
    toolchain.MANIFEST = w.config
    lib.STATE = os.path.join(home, ".local", "state", "forge")
    lib.LOCK, lib.JOURNAL = os.path.join(lib.STATE, "sync.lock"), os.path.join(lib.STATE, "journal.log")
    out = io.StringIO()
    try:
        with with_env(**env):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = cli.main(list(argv))
    except SystemExit as e:
        code = e.code
    finally:
        toolchain.MANIFEST, cli.CHECKS, lib.STATE, lib.LOCK, lib.JOURNAL = saved
    return code, out.getvalue().splitlines()


def incident_cases(tmp, home, outside):
    """2: the incident itself. 3: its positive control, the variable inside the toy HOME."""
    old = tt.HEADER + "[tools]\n# a file that is not this test's, in forge's own format\n"
    xdg_outside = os.path.join(outside, "config")
    theirs = os.path.join(xdg_outside, "mise", "conf.d", "forge.toml")
    os.makedirs(os.path.dirname(theirs))
    with open(theirs, "w") as fh:
        fh.write(old)
    w = tt.World(os.path.join(tmp, "world", "machine"), tt.DOC, tt.ALL_TOOLS, tt.ALL_PIP, files=None)
    # Where a run can write, printed first (ORDERS 21) and checked: a temp dir of this test, or the test stops.
    with with_env(**dict(toy_env(home), XDG_CONFIG_HOME=xdg_outside, MISE_CONFIG_DIR=None)):
        print("incident case writes to:", toolchain.mise_file(), "and", w.pip_file)
        if not toolchain.mise_file().startswith(outside + os.sep) or not w.pip_file.startswith(tmp + os.sep):
            failures.append("the incident case would write outside its temp dirs: %s" % toolchain.mise_file())
            return
    code, lines = toolchain_run(w, ("toolchain", "--fix"), xdg_outside, home)
    with open(theirs) as fh:
        after = fh.read()
    want("the incident: forge toolchain --fix, XDG_CONFIG_HOME outside = (exit, outside file, refusal printed)",
         (code, after, REFUSAL % (home, "XDG_CONFIG_HOME", xdg_outside) in lines), (1, old, True))
    want("the incident: the toy world's pip file is not written either", w.read(w.pip_file), None)

    # 3: the same run with XDG_CONFIG_HOME inside the toy HOME writes there
    inside = os.path.join(home, ".config")
    mine = os.path.join(inside, "mise", "conf.d", "forge.toml")
    code, lines = toolchain_run(w, ("toolchain", "--fix"), inside, home)
    want("control: forge toolchain --fix, XDG_CONFIG_HOME inside the toy HOME = (exit, file written, no refusal)",
         (code, w.read(mine) == toolchain.render_mise(tt.DOC["tools"]), any("points outside it" in l for l in lines)),
         (0, True, False))


def env_cases(tmp):
    """5: bare_env hands every toy world its own XDG_* and MISE_CONFIG_DIR, under the toy HOME it is given."""
    home = os.path.join(tmp, "bare-home")
    e = sandbox.bare_env(home, tmp)
    for var in TOY_VARS:
        want("bare_env sets %s" % var, e.get(var) is not None and e[var].startswith(home + os.sep), True)
    want("bare_env: `extra` still wins", sandbox.bare_env(home, tmp, XDG_CONFIG_HOME="/srv/real-config")["XDG_CONFIG_HOME"],
         "/srv/real-config")


def main():
    # lib.SETTINGS and the settings cache: the toolchain run reads a toy forge.json, never this checkout's
    restore = tt.toy_settings(sandbox.mkdtemp("toy-home-env-settings-"))
    tmp = sandbox.mkdtemp("toy-home-env-")
    outside = sandbox.mkdtemp("toy-home-env-outside-")  # not under the world: this is "somewhere real"
    world = os.path.join(tmp, "world")
    home = os.path.join(world, "home")
    root = os.path.join(world, "forge")
    for d in (home, os.path.join(root, "config", "projects")):
        os.makedirs(d)
    real = (lib.ROOT, lib.HOME, lib.PROJECTS)
    lib.ROOT, lib.HOME, lib.PROJECTS = root, home, os.path.join(root, "config", "projects")
    try:
        refusal_cases(world, home, outside)
        incident_cases(tmp, home, outside)
        env_cases(tmp)
    finally:
        lib.ROOT, lib.HOME, lib.PROJECTS = real
        restore()
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
