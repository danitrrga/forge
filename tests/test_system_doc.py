#!/usr/bin/env python3
"""The pointer block sync_system_doc.py writes into a project's CLAUDE.md tells the truth to the
frozen projects below it. Claude Code loads a parent directory's CLAUDE.md in every session below
it, so every session in a frozen project reads ~/dev/CLAUDE.md, the dev project's pointer. That pointer says
the generated files "here" are "overwritten on every SessionStart" and sends the agent to
.claude/AGENT-SYSTEM.md, and for a frozen project both are false: forge writes nothing there, and
the frozen project's copy is a stale one (research study 19, section
1.3 point 3; plan step 4).

A toy world: a dev project whose directory holds a frozen frozen-app and an unfrozen app, all
three fresh, run with --apply from a toy checkout this toy HOME names as installed. dev's pointer
gains a note naming frozen-app; app's is the plain POINTER, byte for byte, so no other project's
CLAUDE.md moves; the frozen directory gets nothing; a second run changes nothing.

Seen failing before the fix: "dev's CLAUDE.md names its frozen project frozen-app and
its project: got '<!-- BEGIN <pointer marker> (managed by sync_system_doc.py) -->\\n\\n##
Shared agent-config system...'" -- the plain pointer, with no note.

The constants the script and forge/uninstall.py share (banner, canonical doc, markers, marker_error) live in
forge/system_doc.py, so uninstall imports them instead of running the script. Seen failing on 813e597, where
the module does not exist: "FileNotFoundError: [Errno 2] No such file or directory: '.../forge/system_doc.py'"
from this file's own read of the markers."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join("scripts", "sync", "sync_system_doc.py")
MODULE = os.path.join("forge", "system_doc.py")
END = re.search(r'^END = "(.*)"$', open(os.path.join(sandbox.FORGE, MODULE), encoding="utf-8").read(), re.M).group(1)


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
    prof_app = os.path.join(dev, "Projects", "prof-app")
    ui_app = os.path.join(dev, "Projects", "ui-app")
    # The doc is the fixture's, not config/AGENT-SYSTEM.md of this checkout: a copy_engine copy has none. Red there
    # before (M1): "FileNotFoundError" copying .../docs/AGENT-SYSTEM.md (its path before it moved to config/) from sandbox.mini_root.
    sandbox.mini_root(root, SCRIPT, os.path.join("forge", "mcp.py"), os.path.join("forge", "owned.py"),
                     MODULE, os.path.join("forge", "profiles.py"), os.path.join("forge", "suggest.py"))  # the script claims what it creates
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    shutil.copy(os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "AGENT-SYSTEM.md"),
                os.path.join(root, "config", "AGENT-SYSTEM.md"))
    os.makedirs(os.path.join(root, "bin"))
    open(os.path.join(root, "bin", "forge"), "w").close()  # lib.installed_root() wants it a file
    projects = os.path.join(root, "config", "projects")
    os.makedirs(projects)
    declared = ', "profiles": {"default": "toy-a", "offered": {"toy-b": {}}}'
    ui = ', "ui": true, "verdict_command": "toy-verdict"'
    # frozen-twin and frozen-ui-twin are frozen files that share their folder with a live project that declares nothing.
    for name, path, extra in (("dev", dev, ""), ("frozen-app", portal, ', "frozen": true'), ("app", app, ""),
                              ("prof-app", prof_app, declared), ("ui-app", ui_app, ""),
                              ("frozen-twin", app, ', "frozen": true' + declared),
                              ("frozen-ui-twin", ui_app, ', "frozen": true' + ui)):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(projects, name + ".claude.json"), "w") as f:
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

    # forge/system_doc.py holds what the script and uninstall share; the script re-exports it, same objects.
    probe = ("import sys; sys.argv = ['x']; sys.path.insert(0, %r); sys.path.insert(0, %r); import sync_system_doc as s; "
             "from forge import system_doc as m; "
             "sys.stdout.write(repr([getattr(s, n) is getattr(m, n) for n in ('CANON', 'GEN_BANNER', 'BEGIN', 'END', 'marker_error')]"
             " + [m.marker_error(m.BEGIN + m.BEGIN + m.END + m.END) is not None, m.marker_error(m.END + m.BEGIN) is not None,"
             " m.marker_error(m.BEGIN + m.END) is None, m.marker_error('') is None]))"
             % (root, os.path.dirname(os.path.join(root, SCRIPT))))
    r = subprocess.run([sys.executable, "-c", probe], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
    check("forge.system_doc is what the script uses, and marker_error names the bad pairs",
          r.stdout == repr([True] * 9), r.stdout + r.stderr)
    # The canonical doc is the owner's own setup, so it lives in config/, not in docs/ (engine documents only).
    # Seen failing on 4c4b33c: "FAIL the canonical doc is config/AGENT-SYSTEM.md and the banner names it: got ('docs/AGENT-SYSTEM.md', False)".
    probe = ("import sys, os; sys.path.insert(0, %r); from forge import system_doc as m; "
             "sys.stdout.write(repr((os.path.relpath(m.CANON, %r), '/config/AGENT-SYSTEM.md by ' in m.GEN_BANNER)))" % (root, root))
    r = subprocess.run([sys.executable, "-c", probe], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
    check("the canonical doc is config/AGENT-SYSTEM.md and the banner names it",
          r.stdout == repr(("config/AGENT-SYSTEM.md", True)), "got " + r.stdout + r.stderr)

    before = sandbox.manifest(portal)
    rc, out = run("--apply")
    check("the first --apply exits 0", rc == 0, out)
    got = read(os.path.join(dev, "CLAUDE.md"))
    note = (got or "")[len(plain) - len(END):-len(END + "\n")]
    check("dev's CLAUDE.md names its frozen project frozen-app and its project",
          got is not None and got.startswith(plain[:-len(END)]) and got.endswith(END + "\n")
          and "frozen" in note and "frozen-app" in note
          and os.path.join(projects, "frozen-app.claude.json") in note, got)
    got = read(os.path.join(app, "CLAUDE.md"))
    check("app's CLAUDE.md is the plain pointer, byte for byte", got == plain + "\n", got)
    # A project without `profiles` gets no word of them: `plain` is read from the script's own POINTER, so a sentence put into
    # POINTER itself would pass the line above and is caught here. Seen failing on 3ecfca4 (no sentence anywhere), for prof-app below:
    # "FAIL prof-app, which declares profiles, is told how to hand a task to another one: the one sentence, once: got
    # '<!-- BEGIN FORGE-SYSTEM-POINTER (managed by sync_system_doc.py) -->...'" (exit 1, 1 failure)
    check("app, which declares no profiles, is told nothing of them",
          got is not None and "forge run" not in got and "FORGE_PROFILE" not in got and "forge list @" not in got, got)
    got = read(os.path.join(prof_app, "CLAUDE.md"))
    check("prof-app, which declares profiles, is told how to hand a task to another one: the one sentence, once",
          got is not None and got.startswith(plain[:-len(END)]) and got.endswith(END + "\n")
          and got.count('forge run @PROFILE "PROMPT"') == 1 and got.count("forge list @") == 1
          and got.count("FORGE_PROFILE") == 1, got)
    # The review's second finding: a project nested inside prof-app reads this file too, and the two commands refuse there. The
    # paragraph names the project and its folder, says the commands are run from that folder and that a nested project has its own
    # profiles or none. Seen failing on 94802e2: "FAIL prof-app's paragraph names the project and its folder and where the two
    # commands are run: got '...To hand a task to another profile of this project** (`forge list @` names them), run ...'".
    check("prof-app's paragraph names the project and its folder and where the two commands are run",
          got is not None and "(`prof-app`, in `%s`)" % prof_app in got and "from that folder" in got
          and "nested inside it" in got and "its own profiles or none" in got, got)
    check("prof-app's block is the plain pointer plus the sentence, and nothing before it moved",
          got is not None and got.replace(got[len(plain) - len(END):-len(END + "\n")], "") == plain + "\n", got)
    # The review's first finding: a frozen file that declares profiles (or a ui) and shares its folder with a live project that
    # does not is not eligible; only a live project that declares it gets the paragraph. Seen failing on 94802e2: "FAIL app, which
    # shares its folder with a frozen file that declares profiles, gets the plain pointer: got '...To hand a task to another
    # profile of this project**...'"; the same for ui-app with the UI paragraph.
    got = read(os.path.join(app, "CLAUDE.md"))
    check("app, which shares its folder with a frozen file that declares profiles, gets the plain pointer", got == plain + "\n", got)
    got = read(os.path.join(ui_app, "CLAUDE.md"))
    check("ui-app, which shares its folder with a frozen file that declares a ui, gets the plain pointer", got == plain + "\n", got)
    check("the frozen frozen-app gets nothing", sandbox.manifest(portal) == before, out)
    rc, out = run("--apply")
    check("a second --apply changes nothing", rc == 0 and "0 change(s) applied." in out, out)

    # A checkout installed before the move still has docs/AGENT-SYSTEM.md and no config/ copy: master's code runs at its next
    # SessionStart before the owner moves the file, so the doc in docs/ is read until config/ has one, and the banner names it.
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    os.replace(os.path.join(root, "config", "AGENT-SYSTEM.md"), os.path.join(root, "docs", "AGENT-SYSTEM.md"))
    probe = ("import sys, os; sys.path.insert(0, %r); from forge import system_doc as m; "
             "sys.stdout.write(repr((os.path.relpath(m.CANON, %r), '/docs/AGENT-SYSTEM.md by ' in m.GEN_BANNER)))" % (root, root))
    r = subprocess.run([sys.executable, "-c", probe], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
    check("with only docs/AGENT-SYSTEM.md, the canonical doc is that one and the banner names it",
          r.stdout == repr(("docs/AGENT-SYSTEM.md", True)), "got " + r.stdout + r.stderr)
    rc, out = run("--apply")
    check("with only docs/AGENT-SYSTEM.md, --apply exits 0", rc == 0 and "canonical doc missing" not in out, out)

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over 15 cases" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
