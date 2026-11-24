#!/usr/bin/env python3
"""`forge test [fwx] --shard I/N`: one slice of a suite, so CI can run the slices on separate runners. The slices of a suite together run
every file once and none twice, and the CI matrix names exactly the slices 1/N .. N/N.

Why: the engine suite (about 530 s) and the fwx suite (about 410 s) are CPU-bound on a 4-vCPU runner; more files at once on the same
runner cannot cut them, more runners can (see the table of the PR that added this).

Cases: a toy repository (as tests/test_test_group.py builds) with 7 files, in the group and with no group, for N = 1, 2, 3, 4:
  every file runs in exactly one shard; a shard says "shard I/N: K of M ..."; the slow files of SLOW_FIRST land in different shards;
  a malformed --shard is exit 2; a shard that gets no file (N above the file count) is exit 1, never a green run that looked at zero;
  .github/workflows/checks.yml names every shard of each sharded job once, as `I/N`, and `--shard ${{ matrix.shard }}` is all that is passed.

Written first and run on master, where `--shard` did not exist (the first FAILs printed):
  FAIL: group, N=1: every file ran once: exit code: got 2, want 0   (forge: error: unrecognized arguments: --shard 1/1)
  FAIL: the workflow's engine job shards its suite: no `--shard` in the job
Controls (a copy of forge/testgroup.py changed in one place, the suite run on the copy; the mutations are not kept):
  the dealing skips the last file (`order[i - 1::n]` -> `order[i - 1::n][:-1]`):
      FAIL: group, N=1: every file ran exactly once: got ['tests/test_b.py', 'tests/test_c.py', ...] (test_a.py missing)
  every shard takes the first slice (`i - 1` -> `0`):
      FAIL: group, N=2: every file ran exactly once: got ['tests/test_a.py', 'tests/test_a.py', 'tests/test_c.py', ...
  the suite job's matrix loses its third entry (["1/4", "2/4", "3/4", "4/4"] -> ["1/4", "2/4", "4/4"]), the one FAIL:
      FAIL: the suite job's matrix is exactly 1/4 .. 4/4, once each: got ['1/4', '2/4', '4/4'], want ['1/4', '2/4', '3/4', '4/4']
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

FORGE = sandbox.FORGE
fails = []
checks = 0
HOME = sandbox.mkdtemp("forge-shard-home-")


def ok(label, cond, detail=""):
    global checks
    checks += 1
    if not cond:
        fails.append("FAIL: %s%s" % (label, (": " + detail) if detail else ""))
    return bool(cond)


def eq(label, got, want):
    return ok(label, got == want, "got %r, want %r" % (got, want))


def env():
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1", HOME=HOME)
    return e


def toy(files):
    """A git repository with a toy copy of forge; `files` is {path: text}, all committed."""
    repo = sandbox.mkdtemp("forge-shard-")
    sandbox.git(repo, "init", "-q", "-b", "master")
    shutil.copytree(os.path.join(FORGE, "forge"), os.path.join(repo, "forge"), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(repo, "bin"))
    shutil.copy(os.path.join(FORGE, "bin", "forge"), os.path.join(repo, "bin", "forge"))
    for rel, text in files.items():
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    sandbox.git(repo, "add", "-A")
    sandbox.git(repo, "commit", "-q", "-m", "toy")
    return repo


def forge(repo, *args):
    return subprocess.run([sys.executable, os.path.join(repo, "bin", "forge"), "test"] + list(args), cwd=repo, env=env(),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)


SKIP_TEXT = 'print("NOT RUN, NOT ARMED: no such tool")\nraise SystemExit(77)\n'
NAMES = ["test_a.py", "test_b.py", "test_c.py", "test_d.py", "test_e.py", "test_f.py", "test_g.py"]
# sizes differ, so the order the files are dealt in is not the alphabetical one
BODY = {n: "x = 1\n" * (10 * (i + 1)) for i, n in enumerate(NAMES)}


def ran(r, prefix):
    """The files a run printed a PASS line for, in the order printed."""
    return [l.split()[1] for l in r.stdout.splitlines() if l.startswith(prefix)]


def shards(repo, n, *base, prefix, rel):
    """(per shard: the files that ran, the exit codes) of `forge test <base> --shard i/n` for i in 1..n."""
    got, codes, outs = [], [], []
    for i in range(1, n + 1):
        r = forge(repo, *base, "--shard", "%d/%d" % (i, n))
        got.append([rel(x) for x in ran(r, prefix)])
        codes.append(r.returncode)
        outs.append(r.stdout)
    return got, codes, outs


# ---- the group: forge test fwx --shard I/N -------------------------------------------------------------------------------------------
grepo = toy({"plugins/fwx/tests/" + n: BODY[n] for n in NAMES})
want = sorted("tests/" + n for n in NAMES)
for n in (1, 2, 3, 4):
    got, codes, outs = shards(grepo, n, "fwx", prefix="PASS", rel=lambda x: x)
    flat = sorted(f for g in got for f in g)
    eq("group, N=%d: every file ran exactly once" % n, flat, want)
    eq("group, N=%d: every shard exits 0" % n, codes, [0] * n)
    for i, text in enumerate(outs, 1):
        first = text.splitlines()[0] if text else ""
        eq("group, N=%d: shard %d says what it looked at" % (n, i), first, "shard %d/%d: %d of %d test file(s)" % (i, n, len(got[i - 1]), len(NAMES)))
sizes = [len(g) for g in shards(grepo, 3, "fwx", prefix="PASS", rel=lambda x: x)[0]]
eq("group, N=3: 7 files are dealt 3, 2, 2 (the largest first)", sizes, [3, 2, 2])

# ---- no group: forge test --shard I/N (the files of the repository's own top folder) ----------------------------------------------------
top = {n: BODY[n] for n in NAMES}
top["hooks/test_guard_mutants.py"] = "raise SystemExit(1)\n"  # on demand: a SKIP line in every shard, never dealt
trepo = toy(top)
want_top = sorted(NAMES)
for n in (1, 2, 3, 4):
    got, codes, outs = shards(trepo, n, prefix="PASS", rel=lambda x: x)
    eq("no group, N=%d: every file ran exactly once" % n, sorted(f for g in got for f in g), want_top)
    eq("no group, N=%d: every shard exits 0" % n, codes, [0] * n)
    ok("no group, N=%d: the on-demand file stays a SKIP in every shard" % n, all("SKIP  test_guard_mutants.py" in o for o in outs))
    for i, text in enumerate(outs, 1):
        first = text.splitlines()[0] if text else ""
        eq("no group, N=%d: shard %d says what it looked at" % (n, i), first, "shard %d/%d: %d of %d test file(s)" % (i, n, len(got[i - 1]), len(NAMES)))

# ---- the slow files of SLOW_FIRST are dealt to different shards, not piled into one ----------------------------------------------------
from forge import cli, testgroup  # noqa: E402

take_shard = getattr(testgroup, "take_shard", None)
ok("forge.testgroup.take_shard exists", take_shard is not None)
take_shard = take_shard or (lambda order, shard: [])
order = cli.start_order(list(cli.SLOW_FIRST) + ["tests/test_%s.py" % c for c in "abcdefgh"])
slices = [take_shard(order, (i, len(cli.SLOW_FIRST))) for i in range(1, len(cli.SLOW_FIRST) + 1)]
eq("SLOW_FIRST: with as many shards as slow files each shard gets exactly one of them",
   [sum(1 for f in s if f in cli.SLOW_FIRST) for s in slices], [1] * len(cli.SLOW_FIRST))
eq("take_shard: the slices of any N are the whole list, once", sorted(f for n in (1, 2, 5) for i in range(1, n + 1) for f in take_shard(order, (i, n))),
   sorted(order * 3))
eq("take_shard: no shard asked for is the whole list", take_shard(order, None), order)

# ---- a malformed --shard is a usage error; a shard with no file is a failure -----------------------------------------------------------
for label, args in (("0/3", ("--shard", "0/3")), ("4/3", ("--shard", "4/3")), ("1/0", ("--shard", "1/0")), ("abc", ("--shard", "abc")),
                    ("1-3", ("--shard", "1-3")), ("-1/3", ("--shard=-1/3",)), ("1/3/5", ("--shard", "1/3/5")), ("empty", ("--shard=",)),
                    ("twice", ("--shard", "1/2", "--shard", "2/2"))):
    for base in (("fwx",), ()):
        r = forge(grepo if base else trepo, *base, *args)
        eq("--shard %s, %s: exit 2" % (label, "group" if base else "no group"), r.returncode, 2)
        ok("--shard %s, %s: one line on stderr naming --shard, no traceback, nothing ran" % (label, "group" if base else "no group"),
           "--shard wants I/N" in r.stderr and "Traceback" not in r.stderr and r.stdout == "", r.stdout + r.stderr)
r = forge(grepo, "fwx", "--shard", "9/9")
eq("group, 9 shards of 7 files: the ninth has no file: exit 1", r.returncode, 1)
ok("group, the empty shard says so", "shard 9/9: 0 of 7" in r.stdout, r.stdout + r.stderr)
r = forge(trepo, "--shard", "9/9")
eq("no group, 9 shards of 7 files: the ninth has no file: exit 1", r.returncode, 1)
ok("no group, the empty shard is a FAIL line", "FAIL  shard 9/9" in r.stdout, r.stdout + r.stderr)
r = forge(grepo, "fwx", "--shard", "1/3", "--expect-not-run", "tests/test_g.py")
eq("group, --expect-not-run names a file of another shard: it is a known file, not a typo: exit 0", r.returncode, 0)

# ---- the real fwx suite: its three slow files are dealt to three different shards -------------------------------------------------------
# The deal is by bytes unless the slow files are pinned first: replayed over the real files by size alone, test_walk and
# test_ui_walk_workflow both land in shard 1 of 3 (the first FAIL below on the code before FWX_SLOW_FIRST existed).
fwx_root = os.path.join(FORGE, "plugins", "fwx")
fwx_files = testgroup.test_files(fwx_root, env())
slow = tuple(getattr(testgroup, "FWX_SLOW_FIRST", ()))
ok("FWX_SLOW_FIRST names the slow fwx files", len(slow) == 3, repr(slow))
ok("every FWX_SLOW_FIRST name is a tracked fwx test (a renamed file would leave the list stale)", all(f in fwx_files for f in slow), repr(slow))
deal = testgroup.start_order(fwx_files, fwx_root) if hasattr(testgroup, "start_order") else sorted(
    fwx_files, key=lambda f: (-os.path.getsize(os.path.join(fwx_root, f)), f))
home = {f: i for i in range(1, 4) for f in take_shard(deal, (i, 3))}
WANT_SLOW = ("tests/test_walk.py", "tests/test_execute_workflow.py", "tests/test_ui_walk_workflow.py")
eq("the three slow fwx files are in three different shards of 3", sorted(home.get(f, 0) for f in WANT_SLOW), [1, 2, 3])
eq("the fwx shards of 3 together are every file, once", sorted(f for i in (1, 2, 3) for f in take_shard(deal, (i, 3))), sorted(fwx_files))

# ---- a shard that holds only declared files, and one with an undeclared exit 77 --------------------------------------------------------
# Three slices of four files: test_a and test_b pass, test_decl exits 77 and is declared, test_skip exits 77 and is not. The sizes make
# the deal test_a, test_decl, test_skip, test_b: shard 1 = a, b; shard 2 = decl alone; shard 3 = skip alone. Before this was handled,
# shard 2 exited 1 (`expect and passed == 0`: "everything declared away proves nothing", true of a whole run, not of one slice).
PAD = lambda n: "# pad\n" * n
srepo = toy({"plugins/fwx/tests/test_a.py": "pass\n" + PAD(60), "plugins/fwx/tests/test_decl.py": SKIP_TEXT + PAD(30),
             "plugins/fwx/tests/test_skip.py": SKIP_TEXT + PAD(20), "plugins/fwx/tests/test_b.py": "pass\n" + PAD(10)})
codes = [forge(srepo, "fwx", "--shard", "%d/3" % i, "--expect-not-run", "tests/test_decl.py").returncode for i in (1, 2, 3)]
eq("--shard 1/3 .. 3/3 with one declared and one undeclared 77: the declared-only shard is 0, the undeclared 77 is 77", codes, [0, 0, 77])
codes = [forge(srepo, "fwx", "--shard", "%d/2" % i, "--expect-not-run", "tests/test_decl.py").returncode for i in (1, 2)]
eq("--shard 1/2, 2/2: the shard with the undeclared 77 exits 77, the other 0", sorted(codes), [0, 77])
r = forge(srepo, "fwx", "--expect-not-run", "tests/test_decl.py")
eq("no shard: the whole run with an undeclared 77 is still 77", r.returncode, 77)
only = toy({"plugins/fwx/tests/test_decl.py": SKIP_TEXT})
eq("no shard: everything declared away proves nothing, still exit 1", forge(only, "fwx", "--expect-not-run", "tests/test_decl.py").returncode, 1)

# ---- the workflow: every sharded job names the shards 1/N .. N/N, once each ------------------------------------------------------------
text = open(os.path.join(FORGE, ".github", "workflows", "checks.yml")).read()
jobs = {}
for m in re.finditer(r"^  (\w+):\n((?:(?:    .*|)\n)+)", text, re.M):  # a job: two-space key, its indented body
    jobs[m.group(1)] = m.group(2)
for job in ("fwx", "suite"):
    body = jobs.get(job, "")
    ok("the workflow's %s job shards its suite: `--shard ${{ matrix.shard }}`" % job, "--shard ${{ matrix.shard }}" in body, body[:200])
    m = re.search(r"shard: \[([^\]]*)\]", body)
    specs = [s.strip().strip("\"'") for s in m.group(1).split(",")] if m else []
    total = {s.split("/")[1] for s in specs if "/" in s}
    ok("the %s job's matrix is one list of I/N entries, all with the same N" % job, bool(specs) and len(total) == 1, repr(specs))
    if len(total) == 1:
        n = int(total.pop())
        eq("the %s job's matrix is exactly 1/%d .. %d/%d, once each" % (job, n, n, n), specs, ["%d/%d" % (i, n) for i in range(1, n + 1)])
    ok("the %s job does not give up on the first red shard (fail-fast off: a run shows every shard's failures)" % job,
       "fail-fast: false" in body, body[:200])
    ok("the %s job is still skipped only on `false`" % job, "needs.changes.outputs.%s != 'false'" % job in body, body[:200])

if fails:
    print("\n".join(fails))
    print("%d FAIL of %d checks" % (len(fails), checks))
    sys.exit(1)
print("ok: test_test_shard (%d checks)" % checks)
