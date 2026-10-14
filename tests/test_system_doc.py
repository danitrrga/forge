#!/usr/bin/env python3
"""The pointer block sync_system_doc.py writes into a project's CLAUDE.md tells the truth to the
frozen projects below it. Claude Code loads a parent directory's CLAUDE.md in every session below
it, so every session in a frozen project reads ~/dev/CLAUDE.md, the dev profile's pointer. That pointer says
the generated files "here" are "overwritten on every SessionStart" and sends the agent to
.claude/AGENT-SYSTEM.md, and for a frozen project both are false: forge writes nothing there, and
the frozen project's copy is a stale one (research study 19, section
1.3 point 3; plan step 4).

A toy world: a dev profile whose directory holds a frozen frozen-app and an unfrozen app, all
three fresh, run with --apply from a toy checkout this toy HOME names as installed. dev's pointer
gains a note naming frozen-app; app's is the plain POINTER, byte for byte, so no other project's
CLAUDE.md moves; the frozen directory gets nothing; a second run changes nothing.

Seen failing before the fix: "dev's CLAUDE.md names its frozen project frozen-app and
its profile: got '<!-- BEGIN <pointer marker> (managed by sync_system_doc.py) -->\\n\\n##
Shared agent-config system...'" -- the plain pointer, with no note."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join("scripts", "sync", "sync_system_doc.py")
END = re.search(r'^END = "(.*)"$', open(os.path.join(sandbox.FORGE, SCRIPT), encoding="utf-8").read(), re.M).group(1)


def read(p):
    """p's text, or None when there is no file."""
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    tmp = sandbox.mkdtemp("forge-sysdoc-")
    root, home, dev = (os.path.join(tmp, d) for d in ("forge", "home", "dev"))
    portal, app = os.path.join(dev, "Projects", "frozen-app"), os.path.join(dev, "Projects", "app")
    # The doc is the fixture's, not docs/AGENT-SYSTEM.md of this checkout: a copy_engine copy has none. Red there
    # before (M1): "FileNotFoundError" copying .../docs/AGENT-SYSTEM.md from sandbox.mini_root.
    sandbox.mini_root(root, SCRIPT)
    os.makedirs(os.path.join(root, "docs"))
    shutil.copy(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "AGENT-SYSTEM.md"),
                os.path.join(root, "docs", "AGENT-SYSTEM.md"))
    os.makedirs(os.path.join(root, "bin"))
    open(os.path.join(root, "bin", "forge"), "w").close()  # lib.installed_root() wants it a file
    profiles = os.path.join(root, "config", "profiles")
    os.makedirs(profiles)
    for name, path, extra in (("dev", dev, ""), ("frozen-app", portal, ', "frozen": true'), ("app", app, "")):
        os.makedirs(path)
        with open(os.path.join(profiles, name + ".claude.json"), "w") as f:
            f.write('{"project_path": "%s"%s}\n' % (path, extra))
    sandbox.installed_settings(home, root)
    env = sandbox.bare_env(home, tmp)
    failures = []

    def check(label, ok, got):
        if not ok:
            failures.append("%s: got %r" % (label, got if len(str(got)) < 300 else str(got)[:300] + "..."))

    def run(*args):
        r = subprocess.run([sys.executable, os.path.join(root, SCRIPT)] + list(args), cwd=tmp, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        return r.returncode, r.stdout

    plain = subprocess.run(
        [sys.executable, "-c", "import sys; sys.argv = ['x']; sys.path.insert(0, %r); "
         "import sync_system_doc as s; sys.stdout.write(s.POINTER)" % os.path.dirname(os.path.join(root, SCRIPT))],
        cwd=tmp, env=env, capture_output=True, text=True, timeout=60).stdout
    check("the toy checkout's POINTER can be read", plain.endswith(END), plain)

    before = sandbox.manifest(portal)
    rc, out = run("--apply")
    check("the first --apply exits 0", rc == 0, out)
    got = read(os.path.join(dev, "CLAUDE.md"))
    note = (got or "")[len(plain) - len(END):-len(END + "\n")]
    check("dev's CLAUDE.md names its frozen project frozen-app and its profile",
          got is not None and got.startswith(plain[:-len(END)]) and got.endswith(END + "\n")
          and "frozen" in note and "frozen-app" in note
          and os.path.join(profiles, "frozen-app.claude.json") in note, got)
    got = read(os.path.join(app, "CLAUDE.md"))
    check("app's CLAUDE.md is the plain pointer, byte for byte", got == plain + "\n", got)
    check("the frozen frozen-app gets nothing", sandbox.manifest(portal) == before, out)
    rc, out = run("--apply")
    check("a second --apply changes nothing", rc == 0 and "0 change(s) applied." in out, out)

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over 5 cases" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
