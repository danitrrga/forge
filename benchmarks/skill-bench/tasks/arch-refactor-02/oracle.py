"""Oracle for arch-refactor-02: the report functions take an optional `today`, it reaches every date the report
uses, and callers that pass nothing behave exactly as before.

date.today() is read in four places: days_late (used by overdue, aging_buckets, the per-line day count in _line,
and by dunning.py), and the header of weekly_summary. The seam only works if `today` is threaded into all of
them; the usual miss is _line or the header, so weekly_summary(today=X) silently mixes X with the real date. The
other classic slip is a default evaluated once at import (today=date.today()), which freezes the long-running
scheduler on its start day. The probe replaces datetime.date and datetime.datetime with clocks it controls BEFORE
importing the agent's code, so whatever the agent captures is the controlled clock. Then:
  seam            overdue / aging_buckets / weekly_summary called with today=X while the clock says Y equal the
                  original's output when the clock says X, on ~120 seeded invoice lists and several X;
  default         the same functions (and dunning.late_fee) called with no today equal the original's output at
                  the clock's date, and still do after the clock moves on (no default frozen at import);
  original_tests  the original test file is green against the agent's code; the agent's own suite is green;
  callers         dunning.py and scheduler.py import unchanged.
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
            req = [p.name for p in inspect.signature(obj).parameters.values() if p.default is p.empty]
            if [r for r in req if r != "tmp_path"]:
                res[rel + "::" + attr] = ["error", "TypeError", "needs fixtures: " + ", ".join(req), shash(obj)]
            else:
                def call(obj=obj, req=req):
                    import pathlib, tempfile
                    with tempfile.TemporaryDirectory() as d:
                        obj(**({"tmp_path": pathlib.Path(d)} if req else {}))
                run_case(rel + "::" + attr, unittest.FunctionTestCase(call), shash(obj))
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
        pkg = p[:-3] if p.endswith(".py") else None
        if pkg and os.path.isdir(pkg):  # the agent turned the module into a package: it would shadow the swap
            shutil.rmtree(pkg)
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
    'report.py': '''"""Accounts-receivable report for the weekly finance e-mail.

An invoice is a dict: {"number": "F-101", "customer": "Acme", "amount_cents": 12000,
                       "due": datetime.date(2026, 3, 1), "paid": False}
"""
from datetime import date

BUCKETS = [(0, "current"), (1, "1-30"), (31, "31-60"), (61, "61+")]


def days_late(invoice):
    """Days past the due date (0 when not due yet)."""
    return max(0, (date.today() - invoice["due"]).days)


def overdue(invoices):
    """Unpaid invoices past their due date, latest first."""
    late = [inv for inv in invoices if not inv["paid"] and days_late(inv) > 0]
    return sorted(late, key=lambda inv: (-days_late(inv), inv["number"]))


def aging_buckets(invoices):
    """Unpaid amount per age bucket, in cents."""
    totals = {label: 0 for _, label in BUCKETS}
    for inv in invoices:
        if inv["paid"]:
            continue
        late = days_late(inv)
        label = [name for start, name in BUCKETS if late >= start][-1]
        totals[label] += inv["amount_cents"]
    return totals


def _line(inv):
    return "%-8s %-16s %10.2f %4d days" % (inv["number"], inv["customer"], inv["amount_cents"] / 100, days_late(inv))


def weekly_summary(invoices):
    """Body of the weekly e-mail."""
    lines = ["Receivables on %s" % date.today().isoformat(), ""]
    lines += [_line(inv) for inv in overdue(invoices)] or ["Nothing overdue."]
    buckets = aging_buckets(invoices)
    lines += ["", "  ".join("%s %.2f" % (name, buckets[name] / 100) for _, name in BUCKETS)]
    return "\\n".join(lines)
''',
    'dunning.py': '''"""Late fees, charged by the nightly billing run."""
from report import days_late

FEE_PER_WEEK_CENTS = 500


def late_fee(invoice):
    return 0 if invoice["paid"] else (days_late(invoice) // 7) * FEE_PER_WEEK_CENTS
''',
    'scheduler.py': '''"""Long-running worker: sends the weekly summary every Monday morning."""
import time
from datetime import date

from report import weekly_summary


def run_forever(load_invoices, send_mail):
    last = None
    while True:
        today = date.today()
        if today.weekday() == 0 and today != last:
            send_mail("finance@example.test", "Receivables", weekly_summary(load_invoices()))
            last = today
        time.sleep(600)
''',
    'tests/test_report.py': '''import unittest
from datetime import date

from report import aging_buckets, overdue

PAID = [{"number": "F-1", "customer": "Acme", "amount_cents": 1000, "due": date(2020, 1, 1), "paid": True}]


class ReportTest(unittest.TestCase):
    # Anything that depends on the date cannot be tested yet: report.py reads date.today() itself.
    def test_paid_invoices_are_never_overdue(self):
        self.assertEqual(overdue(PAID), [])

    def test_paid_invoices_are_not_aged(self):
        self.assertEqual(aging_buckets(PAID), {"current": 0, "1-30": 0, "31-60": 0, "61+": 0})


if __name__ == "__main__":
    unittest.main()
''',
}

PROBE = r'''
import datetime as dt, importlib.util, json, random
RealDate, RealDT = dt.date, dt.datetime
class FakeDate(RealDate):
    now_ = (2031, 7, 15)
    @classmethod
    def today(cls):
        return cls(*cls.now_)
class FakeDateTime(RealDT):
    @classmethod
    def now(cls, tz=None):
        return cls(*FakeDate.now_, 12, 0)
    @classmethod
    def today(cls):
        return cls.now()
    @classmethod
    def utcnow(cls):
        return cls.now()
dt.date, dt.datetime = FakeDate, FakeDateTime
def clock(d):
    FakeDate.now_ = (d.year, d.month, d.day)
# Every date the probe hands over is a FakeDate, the class the agent's module sees as `date`, so an
# isinstance(today, date) guard in the agent's code holds.
RealDate = FakeDate
spec = importlib.util.spec_from_file_location("report_orig", "@ORIG@")
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)
import report, dunning, scheduler
rng = random.Random(310)
start = RealDate(2026, 1, 1)
datasets = []
for _ in range(120):
    datasets.append([{"number": "F-%03d" % rng.randint(1, 60), "customer": rng.choice(["Acme", "Globex", "Initech", "Umbrella"]),
                      "amount_cents": rng.choice([990, 12000, 45050, 100]), "due": start + dt.timedelta(days=rng.randint(0, 2100)),
                      "paid": rng.random() < 0.25} for _ in range(rng.randint(0, 7))])
datasets.append([])
FNS = ("overdue", "aging_buckets", "weekly_summary")
def norm(name, value):
    return [i["number"] + str(i["due"]) for i in value] if name == "overdue" else value
bad = {"seam": [], "default": [], "late_fee": []}
counts = {"seam": 0, "default": 0, "late_fee": 0}
Y, Y2 = RealDate(2031, 7, 15), RealDate(2031, 9, 2)
for X in (RealDate(2026, 3, 10), RealDate(2028, 2, 29), RealDate(2030, 12, 31), RealDate(2026, 1, 1)):
    for data in datasets:
        for name in FNS:
            clock(Y)
            try:
                got = norm(name, getattr(report, name)(data, today=X))
            except Exception as e:
                got = "raised %s: %s" % (type(e).__name__, e)
            clock(X)
            want = norm(name, getattr(orig, name)(data))
            counts["seam"] += 1
            if got != want and len(bad["seam"]) < 3:
                bad["seam"].append("%s(today=%s) while the clock says %s: %r, want %r" % (name, X, Y, got, want))
for day in (Y, Y2):
    clock(day)
    for data in datasets:
        for name in FNS:
            try:
                got = norm(name, getattr(report, name)(data))
            except Exception as e:
                got = "raised %s: %s" % (type(e).__name__, e)
            want = norm(name, getattr(orig, name)(data))
            counts["default"] += 1
            if got != want and len(bad["default"]) < 3:
                bad["default"].append("%s() on %s: %r, want %r" % (name, day, got, want))
        for inv in data:
            counts["late_fee"] += 1
            want = 0 if inv["paid"] else (orig.days_late(inv) // 7) * 500
            got = dunning.late_fee(inv)
            if got != want and len(bad["late_fee"]) < 3:
                bad["late_fee"].append("late_fee on %s: %r, want %r" % (day, got, want))
print(json.dumps({"bad": bad, "counts": counts}))
'''


def check(repo, message):
    try:
        return _check(repo)
    finally:
        cleanup()


def _check(repo):
    out = []
    add = lambda i, ok, ev: out.append({"id": i, "passed": bool(ok), "evidence": ev})

    orig_dir = tree_from({"report.py": ORIG["report.py"]})
    r = probe_json(repo, PROBE.replace("@ORIG@", os.path.join(orig_dir, "report.py")), timeout=50)
    if "crash" in r:
        for i in ("seam_reaches_every_date", "default_is_the_current_date", "callers_unchanged"):
            add(i, False, "probe crashed: %s" % r["crash"])
    else:
        b, n = r["bad"], r["counts"]
        add("seam_reaches_every_date", n["seam"] and not b["seam"],
            "%d calls with today=X while the clock said otherwise; wrong: %s" % (n["seam"], " | ".join(b["seam"]) or "none"))
        add("default_is_the_current_date", n["default"] and not b["default"],
            "%d calls without today, on two successive clock dates; wrong: %s" % (n["default"], " | ".join(b["default"]) or "none"))
        add("callers_unchanged", n["late_fee"] and not b["late_fee"],
            "dunning.late_fee on %d invoices; scheduler imported; wrong: %s" % (n["late_fee"], " | ".join(b["late_fee"]) or "none"))

    t = "tests/test_report.py"
    orig_ids = set(real_tests(run_tests(tree_from(ORIG))))
    res = run_tests(tree_copy(repo, {t: ORIG[t]}))
    bad = [k for k in orig_ids if not green(get(res, k))]
    mine = real_tests(run_tests(repo))
    broken = [k for k, v in mine.items() if not green(v)]
    add("tests_green", orig_ids and not bad and mine and not broken,
        "original tests against the agent's code, not green: %s; the agent's %d test(s), not green: %s"
        % (short(bad) or "none", len(mine), short(broken) or "none"))
    return out
