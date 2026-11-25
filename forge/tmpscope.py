"""A temp dir outside any git checkout, for the tests. Standalone on purpose: stdlib only, no `forge` package and no config, so
tests/sandbox.py can load it by path at import without putting `forge` in sys.modules (a suite that imports forge.hooks from a
seeded copy of the engine depends on that), and forge/testgroup.py and forge/cli.py use the very same functions."""
import contextlib
import os
import shutil
import subprocess
import tempfile


def clean_env():
    """The environment without GIT_*: inside a git hook GIT_DIR and GIT_INDEX_FILE point at the
    repo being committed, and a test that builds its own repos must not reach it."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def inside_checkout(directory):
    """Whether `directory` is inside a git work tree. A test that makes a temp dir and expects to be outside any repository (it builds
    its own, or asks git where it is) fails falsely when TMPDIR sits in a checkout: 13 to 17 of forge's files did (DTC-119)."""
    try:
        r = subprocess.run(["git", "-C", directory, "rev-parse", "--is-inside-work-tree"], env=clean_env(),
                           capture_output=True, text=True)
    except OSError:  # no git, or no such folder: nothing there to be inside of
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


@contextlib.contextmanager
def private_tmp(env):
    """The environment for test children, a copy of `env`. When its temp dir (TMPDIR, else the default) is
    inside a git work tree, TMPDIR is a fresh folder under /tmp for the length of the with block, removed after; otherwise TMPDIR is left as it is."""
    env = dict(env)
    here = env.get("TMPDIR") or tempfile.gettempdir()
    if not inside_checkout(here):
        yield env
        return
    made = tempfile.mkdtemp(prefix="forge-test-", dir="/tmp" if os.path.isdir("/tmp") else None)
    env["TMPDIR"] = made
    try:
        yield env
    finally:
        shutil.rmtree(made, ignore_errors=True)
