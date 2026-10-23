"""Oracle for arch-refactor-01: the three CSV exporters share one implementation and their output is byte-identical.

The three functions look pasted, but they are not quite the same: refunds negate the amount, and payouts (the
bank file) skip zero rows, also quote names that contain a line break, and end lines with CRLF. A hurried merge
keeps the visible difference (the sign) and loses the invisible ones; the repo's tests compare with
splitlines() and do not notice. The oracle:
  original_tests_green  the original test file, run against the agent's code, is green;
  suite_green           the agent's own suite is green;
  same_output           sales_csv, refunds_csv and payouts_csv return the original's exact string on ~600 seeded
                        row lists (commas, quotes, CR and LF in names, zero, negative and large amounts), and
                        backoffice.export writes the same bytes;
  duplication_removed   no non-trivial statement is repeated across the non-test code (the original repeats six),
                        however the shared part is shaped.
"""
# ---- shared harness (identical in every tests-/arch- oracle by the same author) ----
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

# Runs every test it can find under a tree, one at a time, and prints {test id: [outcome, exc type, message, source
# hash]}. unittest TestCase classes, plain module-level test_* functions and pytest-style Test* classes are all
# collected, so a test is judged whatever style the agent wrote it in.
_RUNNER = r'''
import hashlib, importlib.util, inspect, json, os, sys, unittest
root = os.path.abspath(sys.argv[1])
sys.path.insert(0, root)
os.chdir(root)
SKIP = {"__pycache__", "node_modules", "venv", ".venv", ".git"}
res = {}

def files():
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if not d.startswith(".") and d not in SKIP)
        for f in sorted(fns):
            if f.endswith(".py") and (f.startswith("test") or f.endswith("_test.py")):
                out.append(os.path.join(dp, f))
    return out

def shash(obj):
    try:
        return hashlib.sha1(inspect.getsource(obj).encode()).hexdigest()[:12]
    except Exception:
        return None

class Rec(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.o = ["pass", "", ""]
    def addFailure(self, t, err):
        self.o = ["fail", err[0].__name__, str(err[1])[:300]]
    def addError(self, t, err):
        self.o = ["error", err[0].__name__, str(err[1])[:300]]
    def addSkip(self, t, why):
        self.o = ["skip", "", str(why)[:100]]
    def addExpectedFailure(self, t, err):
        self.o = ["xfail", "", ""]
    def addUnexpectedSuccess(self, t):
        self.o = ["xpass", "", ""]
    def addSubTest(self, t, sub, err):
        if err is not None and self.o[0] == "pass":
            kind = "fail" if issubclass(err[0], t.failureException) else "error"
            self.o = [kind, err[0].__name__, str(err[1])[:300]]

def run_case(tid, case, src):
    r = Rec()
    try:
        unittest.TestSuite([case]).run(r)  # a suite, so setUpClass / setUpModule fixtures run too
    except BaseException as e:
        r.o = ["error", type(e).__name__, str(e)[:300]]
    res[tid] = r.o + [src]

def leaves(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from leaves(t)
        else:
            yield t

for n, path in enumerate(files()):
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    d = os.path.dirname(path)
    if d not in sys.path:
        sys.path.insert(1, d)
    name = "sbt_%d_%s" % (n, os.path.basename(path)[:-3])
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    except BaseException as e:
        res[rel + "::<import>"] = ["error", type(e).__name__, str(e)[:300], None]
        continue
    for t in leaves(unittest.TestLoader().loadTestsFromModule(mod)):
        if isinstance(t, unittest.TestCase) and hasattr(t, "_testMethodName") and type(t).__module__ == name:
            meth = getattr(t, t._testMethodName, None)
            run_case(rel + "::" + type(t).__name__ + "." + t._testMethodName, t, shash(meth))
        elif type(t).__name__ == "_FailedTest":
            res[rel + "::" + t.id()] = ["error", "ImportError", "loader failed", None]
    for attr, obj in sorted(vars(mod).items()):
        if not attr.startswith("test") or getattr(obj, "__module__", None) != name:
            continue
        if inspect.isfunction(obj):
            req = [p for p in inspect.signature(obj).parameters.values() if p.default is p.empty]
            if req:
                res[rel + "::" + attr] = ["error", "TypeError", "needs fixtures: " + ", ".join(p.name for p in req), shash(obj)]
            else:
                run_case(rel + "::" + attr, unittest.FunctionTestCase(obj), shash(obj))
    for attr, obj in sorted(vars(mod).items()):
        if (attr.startswith("Test") and inspect.isclass(obj) and not issubclass(obj, unittest.TestCase)
                and getattr(obj, "__module__", None) == name):
            for m in sorted(k for k in dir(obj) if k.startswith("test") and callable(getattr(obj, k))):
                def call(obj=obj, m=m):
                    inst = obj()
                    if hasattr(inst, "setup_method"):
                        inst.setup_method(getattr(inst, m))
                    try:
                        getattr(inst, m)()
                    finally:
                        if hasattr(inst, "teardown_method"):
                            inst.teardown_method(getattr(inst, m))
                run_case(rel + "::" + attr + "." + m, unittest.FunctionTestCase(call), shash(getattr(obj, m)))
print("@@SBT@@" + json.dumps(res))
'''

_TMP = []


def tmpdir():
    d = tempfile.mkdtemp(prefix="sbt-")
    _TMP.append(d)
    return d


def cleanup():
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)


def tree_copy(src, overrides=None, remove=()):
    """A temp copy of the tree at src with files replaced ({rel path: text}) and removed (rel paths)."""
    dst = os.path.join(tmpdir(), "t")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    for rel in remove:
        p = os.path.join(dst, rel)
        if os.path.exists(p):
            os.remove(p)
    for rel, text in (overrides or {}).items():
        p = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(p) or dst, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    return dst


def tree_from(files):
    """A temp tree holding exactly files ({rel path: text})."""
    dst = os.path.join(tmpdir(), "t")
    os.makedirs(dst)
    for rel, text in files.items():
        p = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    return dst


def run_tests(tree, timeout=40):
    """{test id: [outcome, exc type, message, source hash]} for every test found under tree ({} on a crash)."""
    runner = os.path.join(tmpdir(), "sbt_runner.py")
    with open(runner, "w") as fh:
        fh.write(_RUNNER)
    try:
        r = subprocess.run([sys.executable, "-I", "-B", runner, tree], cwd=tree, capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {}
    for line in reversed(r.stdout.splitlines()):
        if line.startswith("@@SBT@@"):
            return json.loads(line[len("@@SBT@@"):])
    return {}


def run_py(tree, code, timeout=30):
    """(returncode, stdout, stderr) of code run in a fresh interpreter with tree first on sys.path."""
    script = os.path.join(tmpdir(), "sbt_probe.py")
    with open(script, "w") as fh:
        fh.write("import sys\nsys.path.insert(0, %r)\n" % tree + code)
    try:
        r = subprocess.run([sys.executable, "-I", "-B", script], cwd=tree, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return r.returncode, r.stdout, r.stderr


def probe_json(tree, code, timeout=30):
    """The JSON value the probe prints on its last line, or {'crash': stderr tail}."""
    rc, out, err = run_py(tree, code, timeout)
    lines = out.strip().splitlines()
    if rc == 0 and lines:
        try:
            return json.loads(lines[-1])
        except ValueError:
            pass
    return {"crash": (err.strip().splitlines() or ["rc %d, no output" % rc])[-1][:300]}


def mutate(src, old, new):
    """src with the one occurrence of old replaced by new (a missing or repeated anchor is an oracle bug)."""
    if src.count(old) != 1:
        raise RuntimeError("mutation anchor found %d times: %r" % (src.count(old), old[:60]))
    return src.replace(old, new)


def get(results, tid):
    """The result of test tid in a run, or its file's import error when that file did not even load there."""
    if tid in results:
        return results[tid]
    return results.get(tid.split("::", 1)[0] + "::<import>")


def green(r):
    return bool(r) and r[0] in ("pass", "xfail")


def red(r):
    return not r or r[0] in ("fail", "error", "xpass")


def missing_name(r):
    """The test errored because a module lacks a name the agent added (its own API), not on behaviour."""
    if not r or r[0] != "error":
        return False
    return r[1] in ("ImportError", "ModuleNotFoundError") or (r[1] == "AttributeError" and "module" in r[2])


def real_tests(results):
    return {k: v for k, v in results.items() if not k.endswith("::<import>")}


def short(ids, n=4):
    ids = sorted(ids)
    return ", ".join(ids[:n]) + (" (+%d more)" % (len(ids) - n) if len(ids) > n else "")


def py_files(tree, include_tests=False):
    """{rel path: text} of the .py files under tree; test files only when include_tests."""
    out = {}
    for dp, dns, fns in os.walk(tree):
        dns[:] = sorted(d for d in dns if not d.startswith(".") and d != "__pycache__")
        for f in sorted(fns):
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dp, f), tree).replace(os.sep, "/")
            is_test = f.startswith("test") or f.endswith("_test.py") or rel.split("/")[0] in ("tests", "test")
            if is_test and not include_tests:
                continue
            with open(os.path.join(dp, f), encoding="utf-8") as fh:
                out[rel] = fh.read()
    return out


_NUKE = '''

# --- appended by the oracle: every function of this module now returns one inert sentinel ---
class _SbtSentinel:
    def __iter__(self):
        return iter(())
    def __len__(self):
        return 0
    def __bool__(self):
        return False
    def __add__(self, other):
        return self
    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __floordiv__ = __mod__ = __add__
    def __getitem__(self, key):
        return self
    def __call__(self, *a, **k):
        return self
    def __repr__(self):
        return "<nuked>"
_SBT_S = _SbtSentinel()
for _sbt_name, _sbt_obj in list(globals().items()):
    if type(_sbt_obj).__name__ == "function" and _sbt_obj.__module__ == __name__:
        globals()[_sbt_name] = lambda *a, **k: _SBT_S
'''


def nuke(src):
    """src with every module-level function replaced, after import, by one returning a constant inert sentinel
    (empty when iterated, falsy, absorbing arithmetic, equal only to itself). A test still green on it never looked
    at what the code returns: the tautology, the swallowed assertion, the loop over an empty result."""
    return src + _NUKE


def module_name(rel):
    name = rel[:-3].replace("/", ".")
    return name[:-len(".__init__")] if name.endswith(".__init__") else name


def import_graph(files):
    """{module: set of project modules it imports} from the standard-library ast, over {rel path: source}.
    Every import counts wherever it sits (top level, inside a function, behind try): a cycle hidden in a function
    is still a cycle. Not counted: imports under `if TYPE_CHECKING:` (never run). importlib.import_module("x") and
    __import__("x") with a constant name count as imports of x."""
    mods = {module_name(rel): rel for rel in files}
    graph = {m: set() for m in mods}

    def resolve(name):
        while name:
            if name in mods:
                return name
            name = name.rpartition(".")[0]
        return None

    for m, rel in mods.items():
        tree = ast.parse(files[rel])
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for sub in node.body:
                    skip.update(id(n) for n in ast.walk(sub))
        pkg = m if rel.endswith("__init__.py") else m.rpartition(".")[0]
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = pkg.split(".") if pkg else []
                    parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
                    base = ".".join([p for p in parts if p] + ([base] if base else []))
                names = [base + "." + a.name if base else a.name for a in node.names] + ([base] if base else [])
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                f = node.func
                fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if fname in ("import_module", "__import__"):
                    names = [node.args[0].value]
            for n in names:
                target = resolve(n)
                if target and target != m:
                    graph[m].add(target)
    return graph


def find_cycle(graph):
    """One import cycle as a list of modules [a, b, ..., a], or None."""
    state = {}

    def visit(m, stack):
        state[m] = 1
        stack.append(m)
        for n in sorted(graph.get(m, ())):
            if state.get(n) == 1:
                return stack[stack.index(n):] + [n]
            if not state.get(n):
                c = visit(n, stack)
                if c:
                    return c
        stack.pop()
        state[m] = 2
        return None

    for m in sorted(graph):
        if not state.get(m):
            c = visit(m, [])
            if c:
                return c
    return None


def reaches(graph, start):
    """Every module start imports, directly or through others."""
    seen, todo = set(), [start]
    while todo:
        for n in graph.get(todo.pop(), ()):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


def canonical_lines(src):
    """The code of src as ast.unparse prints it, docstrings dropped: one line per simple statement whatever the
    formatting, no comments, no blank lines."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body and \
                isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and \
                isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return [line.strip() for line in ast.unparse(tree).splitlines() if line.strip()]


def added_lines(orig_files, new_files):
    """{rel path: canonical lines added} for the non-test code, new files counted whole."""
    import difflib
    out = {}
    for rel, src in new_files.items():
        a = canonical_lines(orig_files[rel]) if rel in orig_files else []
        b = canonical_lines(src)
        n = sum(j2 - j1 for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                if op in ("insert", "replace"))
        if n:
            out[rel] = n
    return out


def new_classes(orig_files, new_files):
    """(names of classes the agent added, list of problems: inheritance between project classes, ABC/Protocol)."""
    def classes(files):
        found = {}
        for src in files.values():
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.ClassDef):
                    found[node.name] = [ast.unparse(b) for b in node.bases]
        return found
    before, after = classes(orig_files), classes(new_files)
    added = sorted(set(after) - set(before))
    probs = []
    for name in added:
        for base in after[name]:
            short_base = base.split(".")[-1]
            if short_base in after:
                probs.append("%s inherits from project class %s" % (name, short_base))
            if short_base in ("ABC", "ABCMeta", "Protocol"):
                probs.append("%s is an abstract base (%s)" % (name, short_base))
    return added, probs


def max_depth(src):
    """Deepest nesting of compound statements inside any function of src."""
    compound = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith, ast.Match)

    def depth(node, d):
        best = d
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                best = max(best, depth(child, 0))
            elif isinstance(child, compound):
                best = max(best, depth(child, d + 1))
            else:
                best = max(best, depth(child, d))
        return best
    return depth(ast.parse(src), 0)


def longest_function(src):
    """Line count of the longest function in src (decorators and docstring excluded)."""
    best = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            if body:
                best = max(best, body[-1].end_lineno - body[0].lineno + 1)
    return best
# ---- end of shared harness ----
# The untouched repo/ files, embedded so the oracle needs nothing but itself.
ORIG = {
    'reports.py': '''"""CSV exports for the back office. Each function returns the file content as a string.

Rows are dicts: {"date": "2026-03-01", "customer": "Ana Ruiz", "amount_cents": 1250}.
"""


def sales_csv(rows):
    out = ["date,customer,amount"]
    for r in rows:
        name = r["customer"].replace('"', '""')
        if "," in name or '"' in name:
            name = '"%s"' % name
        amount = "%.2f" % (r["amount_cents"] / 100)
        out.append("%s,%s,%s" % (r["date"], name, amount))
    return "\\n".join(out) + "\\n"


def refunds_csv(rows):
    out = ["date,customer,amount"]
    for r in rows:
        name = r["customer"].replace('"', '""')
        if "," in name or '"' in name:
            name = '"%s"' % name
        amount = "%.2f" % (-r["amount_cents"] / 100)
        out.append("%s,%s,%s" % (r["date"], name, amount))
    return "\\n".join(out) + "\\n"


def payouts_csv(rows):
    out = ["date,customer,amount"]
    for r in rows:
        if r["amount_cents"] == 0:
            continue
        name = r["customer"].replace('"', '""')
        if "," in name or '"' in name or "\\n" in name:
            name = '"%s"' % name
        amount = "%.2f" % (r["amount_cents"] / 100)
        out.append("%s,%s,%s" % (r["date"], name, amount))
    return "\\r\\n".join(out) + "\\r\\n"
''',
    'backoffice.py': '''"""Nightly export job: writes the three files finance picks up."""
import json
import os
import sys

from reports import payouts_csv, refunds_csv, sales_csv


def export(data, outdir):
    for name, fn in (("sales", sales_csv), ("refunds", refunds_csv), ("payouts", payouts_csv)):
        with open(os.path.join(outdir, name + ".csv"), "w", newline="", encoding="utf-8") as fh:
            fh.write(fn(data[name]))


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        export(json.load(fh), sys.argv[2])
''',
    'tests/test_reports.py': '''import unittest

from reports import payouts_csv, refunds_csv, sales_csv

ROWS = [
    {"date": "2026-03-01", "customer": "Ana Ruiz", "amount_cents": 1250},
    {"date": "2026-03-02", "customer": "Acme, Inc.", "amount_cents": 99900},
    {"date": "2026-03-02", "customer": "Ben", "amount_cents": 0},
]


class ReportsTest(unittest.TestCase):
    def test_sales(self):
        self.assertEqual(sales_csv(ROWS).splitlines(), [
            "date,customer,amount",
            "2026-03-01,Ana Ruiz,12.50",
            '2026-03-02,"Acme, Inc.",999.00',
            "2026-03-02,Ben,0.00",
        ])

    def test_refunds_are_negative(self):
        self.assertEqual(refunds_csv(ROWS[:1]).splitlines()[1], "2026-03-01,Ana Ruiz,-12.50")

    def test_payouts_skip_zero_amounts(self):
        self.assertEqual(len(payouts_csv(ROWS).splitlines()), 3)

    def test_quotes_in_names_are_doubled(self):
        rows = [{"date": "2026-03-03", "customer": 'Cy "the boss" Park', "amount_cents": 100}]
        self.assertEqual(sales_csv(rows).splitlines()[1], '2026-03-03,"Cy ""the boss"" Park",1.00')


if __name__ == "__main__":
    unittest.main()
''',
}

GOLDEN = r'''
import json, os, random, tempfile
import reports, backoffice
rng = random.Random(1203)
names = ["Ana Ruiz", "Acme, Inc.", 'Cy "the boss" Park', "line\nbreak", "cr\rhere", 'both, "and"\n', "Zoë Ø",
         "", " padded ", "semi;colon", "tab\there", '"', ",", "\n", "Ben"]
amounts = [0, 1, 5, 99, 100, 1250, 99900, -500, -1, 123456789, 1005]
datasets = [[]]
for _ in range(600):
    datasets.append([{"date": "2026-03-%02d" % rng.randint(1, 28), "customer": rng.choice(names),
                      "amount_cents": rng.choice(amounts)} for _ in range(rng.randint(1, 6))])
out = []
for rows in datasets:
    for fn in (reports.sales_csv, reports.refunds_csv, reports.payouts_csv):
        try:
            out.append(fn([dict(r) for r in rows]))
        except Exception as e:
            out.append("raised %s" % type(e).__name__)
d = tempfile.mkdtemp()
backoffice.export({"sales": datasets[3], "refunds": datasets[4], "payouts": datasets[5] + datasets[6]}, d)
for name in ("sales", "refunds", "payouts"):
    with open(os.path.join(d, name + ".csv"), "rb") as fh:
        out.append(fh.read().hex())
print(json.dumps([datasets, out]))
'''


def repeated_statements(files):
    """{statement dump: count} for simple statements of 6+ AST nodes that occur more than once in files."""
    seen = {}
    for src in files.values():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.stmt) and not hasattr(node, "body") and not isinstance(node, (ast.Import, ast.ImportFrom)):
                if sum(1 for _ in ast.walk(node)) >= 6:
                    key = ast.dump(node, annotate_fields=False)
                    seen[key] = seen.get(key, 0) + 1
    return {k: n for k, n in seen.items() if n > 1}


def check(repo, message):
    try:
        return _check(repo)
    finally:
        cleanup()


def _check(repo):
    out = []
    add = lambda i, ok, ev: out.append({"id": i, "passed": bool(ok), "evidence": ev})

    t = "tests/test_reports.py"
    orig_ids = set(real_tests(run_tests(tree_from(ORIG))))
    res = run_tests(tree_copy(repo, {t: ORIG[t]}))
    bad = [k for k in orig_ids if not green(get(res, k))]
    add("original_tests_green", orig_ids and not bad,
        "%d original test(s) run against the agent's code; not green: %s" % (len(orig_ids), short(bad) or "none"))

    mine = real_tests(run_tests(repo))
    broken = [k for k, v in mine.items() if not green(v)]
    add("suite_green", mine and not broken,
        "%d test(s) on the agent's tree; not green: %s" % (len(mine), short(broken) or "none"))

    want = probe_json(tree_from(ORIG), GOLDEN, timeout=50)
    got = probe_json(repo, GOLDEN, timeout=50)
    if isinstance(got, dict):
        add("same_output", False, "golden run crashed: %s" % got.get("crash"))
    else:
        fns = ("sales_csv", "refunds_csv", "payouts_csv")
        diffs = [i for i, (a, b) in enumerate(zip(want[1], got[1])) if a != b]
        ev = "%d outputs compared byte for byte with the original; %d differ" % (len(want[1]), len(diffs))
        if diffs:
            i = diffs[0]
            if i < 3 * len(want[0]):
                ev += "; first: %s(%r) -> original %r, now %r" % (fns[i % 3], want[0][i // 3], want[1][i][:120], got[1][i][:120])
            else:
                ev += "; first: a file written by backoffice.export"
        add("same_output", not diffs and len(got[1]) == len(want[1]), ev[:600])

    try:
        before = repeated_statements({k: v for k, v in ORIG.items() if not k.startswith("tests/")})
        after = repeated_statements(py_files(repo))
        add("duplication_removed", not after,
            "repeated statements in the non-test code: %d (original %d)%s" % (
                len(after), len(before), "; e.g. %s" % sorted(after)[0][:160] if after else ""))
    except SyntaxError as e:
        add("duplication_removed", False, "unparseable: %s" % e)
    return out
