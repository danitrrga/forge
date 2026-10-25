#!/usr/bin/env python3
"""The `gsd engine` row of forge doctor: with the gsd integration on, `node <HOME>/.claude/gsd-core/bin/gsd-tools.cjs
--help` must exit 0. Until this row existed nothing ran the installed engine: gsd-tools.cjs died on `Cannot find
module '../../../scripts/fix-slash-commands.cjs'` for two days while every doctor row was green.

Each case builds a toy HOME (lib.HOME swapped, as the row reads it) holding a toy gsd-core and a toy
config/forge.json; nothing reads the real HOME.
Red before the row, run on the code that did not have it (9 failures, exit 1): "the row is registered = False,
want True"; "2 a gsd-core that loads: PASS, says what it ran = ('raised', \"AttributeError: module 'forge.cli' has
no attribute 'gsd_engine_row'\"), want ('PASS', 'node ~/.claude/gsd-core/bin/gsd-tools.cjs --help exited 0')"; the
same AttributeError for "3 gsd off" (want a SKIP) and "4 no node on PATH" (want a SKIP, NOT RUN, NOT ARMED); and
"1 ... a missing module", "5 an engine that exits 3", "6 gsd on, no gsd-core directory", "7 an engine that never
returns" each = ('raised', False, False), want ('FAIL', True, True).
Negative control: with the exit code ignored (`if r.returncode == 0` made `if True`) two cases fail: "1 a gsd-core
that requires a missing module: FAIL, the module error, the fix = ('PASS', False, False), want ('FAIL', True,
True)" and "5 an engine that exits 3 = ('PASS', False, False), want ('FAIL', True, True)"."""
import contextlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import lib  # noqa: E402
import sandbox  # noqa: E402

lib.SETTINGS = os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "forge.json")
from forge import cli  # noqa: E402

failures = []
FIX = "python3 bin/forge skills --apply"


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def settings_world(tmp, name, gsd):
    d = os.path.join(tmp, "settings-" + name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "forge.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"integrations": {"codex": False, "gsd": gsd, "hindsight": False}}, fh)
    return path


@contextlib.contextmanager
def world(tmp, name, gsd=True, engine=None, path=None, timeout=None):
    """A toy HOME whose gsd-core/bin/gsd-tools.cjs holds `engine` (no gsd-core at all when None), forge.json
    with gsd on or off, PATH as given (the real one when None), and the row's timeout when given."""
    home = os.path.join(tmp, "home-" + name)
    if engine is not None:
        os.makedirs(os.path.join(home, ".claude", "gsd-core", "bin"), exist_ok=True)
        with open(os.path.join(home, ".claude", "gsd-core", "bin", "gsd-tools.cjs"), "w", encoding="utf-8") as fh:
            fh.write(engine)
    saved = (lib.HOME, lib.SETTINGS, os.environ["PATH"], getattr(cli, "GSD_ENGINE_TIMEOUT", None))
    lib.HOME, lib.SETTINGS = home, settings_world(tmp, name, gsd)
    lib.settings.cache_clear()
    if path is not None:
        os.environ["PATH"] = path
    if timeout is not None:
        cli.GSD_ENGINE_TIMEOUT = timeout
    try:
        yield
    finally:
        lib.HOME, lib.SETTINGS, os.environ["PATH"] = saved[:3]
        if timeout is not None:
            cli.GSD_ENGINE_TIMEOUT = saved[3]
        lib.settings.cache_clear()


def row():
    try:
        r = cli.gsd_engine_row()
    except Exception as e:
        return ("raised", "%s: %s" % (type(e).__name__, e))
    return (r.level, r.detail)


def main():
    tmp = sandbox.mkdtemp("doctor-gsd-engine-")
    registered = {n: c for n, c, _ in cli.CHECKS}.get("gsd engine")
    want("the row is registered", registered is getattr(cli, "gsd_engine_row", 0), True)
    broken = "require('../../../scripts/no-such-module.cjs');\n"
    good = "process.stdout.write('Usage: gsd-tools <command>\\n');\n"
    if shutil.which("node"):
        with world(tmp, "broken", engine=broken):
            level, detail = row()
            want("1 a gsd-core that requires a missing module: FAIL, the module error, the fix",
                 (level, "Cannot find module" in detail and "no-such-module.cjs" in detail, FIX in detail), ("FAIL", True, True))
            want("1 the detail is the one error line, not the stack", "\n" not in detail, True)
        with world(tmp, "good", engine=good):
            script = os.path.join(lib.HOME, ".claude", "gsd-core", "bin", "gsd-tools.cjs")
            want("2 a gsd-core that loads: PASS, says what it ran", row(), ("PASS", "node %s --help exited 0" % lib.short(script)))
        with world(tmp, "exit3", engine="process.exit(3);\n"):
            level, detail = row()
            want("5 an engine that exits 3", (level, FIX in detail, "exited 3" in detail), ("FAIL", True, True))
        with world(tmp, "slow", engine="setInterval(() => {}, 1000);\n", timeout=1):
            level, detail = row()
            want("7 an engine that never returns", (level, FIX in detail, "1 s" in detail), ("FAIL", True, True))
    else:
        failures.append("this machine has no node on PATH, so cases 1, 2, 5 and 7 could not run")
    with world(tmp, "off", gsd=False, engine=broken):
        want("3 gsd off: a SKIP that did not run node", row(), ("SKIP", "NOT RUN, NOT ARMED: gsd is off in config/forge.json"))
    empty = os.path.join(tmp, "empty-path")
    os.makedirs(empty, exist_ok=True)
    with world(tmp, "nonode", engine=good, path=empty):
        want("4 no node on PATH: NOT RUN, NOT ARMED, neither a PASS nor a FAIL", row(),
             ("SKIP", "NOT RUN, NOT ARMED: node is not on PATH, so the engine was not run"))
    with world(tmp, "noengine"):
        level, detail = row()
        want("6 gsd on, no gsd-core directory: FAIL naming the fix", (level, FIX in detail, "gsd-tools.cjs" in detail), ("FAIL", True, True))
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
