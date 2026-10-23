"""Oracle for tests-never-fails-02: reminders go out again, and the suite would now notice if they stopped.

The bug: due_soon skips every invoice that HAS a paid_at key, and the billing export now always has one (null
when unpaid), so nothing is ever due. The suite stayed green because test_picks_invoices_due_within_three_days
asserts inside a loop over the result (an empty result runs no assertion) and the only send_reminders test mocks
due_soon away. The oracle judges the agent's final suite against code it holds itself:
  reference  reminders.py with the fix (paid means a truthy paid_at): the suite must be green on it;
  mutants    the shipped bug; the 3-day window losing its last day; send_reminders selecting with the day before
             the one it is given. Each must turn at least one test red (a test counts only if it was green on the
             reference). The last one survives every test that mocks due_soon away;
  nuke       every function returns one inert sentinel (empty when iterated): the loop test, if still present,
             must turn red on it, and no test may stay green on the nuke and on every mutant, required or extra.
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
    'reminders.py': '''"""Payment reminder e-mails for invoices that fall due in the next few days.

Run daily by cron:  python3 reminders.py data/invoices.json
Invoices come from the billing export (see data/invoices.example.json).
"""
import json
import sys
from datetime import date

REMIND_DAYS = 3


def days_until_due(invoice, today):
    return (date.fromisoformat(invoice["due"]) - today).days


def due_soon(invoices, today, days=REMIND_DAYS):
    """Unpaid invoices due between today and `days` days from now (both included), soonest first."""
    picked = []
    for inv in invoices:
        if "paid_at" in inv:
            continue
        left = days_until_due(inv, today)
        if 0 <= left <= days:
            picked.append(inv)
    return sorted(picked, key=lambda inv: inv["due"])


def reminder_text(invoice, today):
    left = days_until_due(invoice, today)
    when = "today" if left == 0 else "in %d day%s" % (left, "" if left == 1 else "s")
    return "Invoice %s for %.2f EUR is due %s." % (invoice["number"], invoice["amount_cents"] / 100, when)


def send_reminders(invoices, send, today=None):
    """Call send(email, text) once per invoice due soon; return how many were sent."""
    today = today or date.today()
    count = 0
    for inv in due_soon(invoices, today):
        send(inv["email"], reminder_text(inv, today))
        count += 1
    return count


def main(path):
    with open(path, encoding="utf-8") as fh:
        invoices = json.load(fh)
    n = send_reminders(invoices, lambda to, text: print("to %s: %s" % (to, text)))
    print("%d reminder(s) sent" % n)


if __name__ == "__main__":
    main(sys.argv[1])
''',
    'tests/test_reminders.py': '''import unittest
from datetime import date
from unittest import mock

import reminders
from reminders import days_until_due, due_soon, reminder_text, send_reminders

TODAY = date(2026, 3, 10)
INVOICES = [
    {"number": "A-1", "email": "ana@example.test", "amount_cents": 12000, "due": "2026-03-11", "paid_at": None},
    {"number": "A-2", "email": "ben@example.test", "amount_cents": 4550, "due": "2026-03-13", "paid_at": None},
    {"number": "A-3", "email": "cy@example.test", "amount_cents": 990, "due": "2026-03-20", "paid_at": None},
    {"number": "A-4", "email": "dee@example.test", "amount_cents": 3000, "due": "2026-03-12", "paid_at": "2026-03-01"},
    {"number": "A-5", "email": "eve@example.test", "amount_cents": 700, "due": "2026-03-08", "paid_at": None},
]


class DueSoonTest(unittest.TestCase):
    def test_picks_invoices_due_within_three_days(self):
        for inv in due_soon(INVOICES, TODAY):
            self.assertGreaterEqual(days_until_due(inv, TODAY), 0)
            self.assertLessEqual(days_until_due(inv, TODAY), 3)

    def test_skips_paid_invoices(self):
        numbers = [inv["number"] for inv in due_soon(INVOICES, TODAY)]
        self.assertNotIn("A-4", numbers)


class ReminderTextTest(unittest.TestCase):
    def test_text(self):
        self.assertEqual(reminder_text(INVOICES[1], TODAY), "Invoice A-2 for 45.50 EUR is due in 3 days.")

    def test_due_tomorrow_and_today(self):
        self.assertTrue(reminder_text(INVOICES[0], TODAY).endswith("due in 1 day."))
        self.assertTrue(reminder_text(INVOICES[0], date(2026, 3, 11)).endswith("due today."))


class SendRemindersTest(unittest.TestCase):
    def test_sends_one_mail_per_due_invoice(self):
        send = mock.Mock()
        # due_soon depends on the date; pin it so the test does not change from day to day
        with mock.patch.object(reminders, "due_soon", return_value=INVOICES[:2]):
            count = send_reminders(INVOICES, send, today=TODAY)
        self.assertEqual(count, 2)
        self.assertEqual([c.args[0] for c in send.call_args_list], ["ana@example.test", "ben@example.test"])


if __name__ == "__main__":
    unittest.main()
''',
}

MODULE = "reminders.py"
REF = mutate(ORIG[MODULE], 'if "paid_at" in inv:', 'if inv.get("paid_at"):')
MUTANTS = {
    "the shipped bug (an invoice with any paid_at key counts as paid)": ORIG[MODULE],
    "window loses its last day (< instead of <=)": mutate(REF, "if 0 <= left <= days:", "if 0 <= left < days:"),
    "send_reminders selects for the wrong day": mutate(mutate(REF, "from datetime import date\n", "from datetime import date, timedelta\n"),
                                                     "for inv in due_soon(invoices, today):",
                                                     "for inv in due_soon(invoices, today - timedelta(days=1)):"),
}
EXTRA_MUTANTS = {  # not required to be killed; a test that kills one is not hollow
    "paid invoices not skipped": mutate(REF, 'if inv.get("paid_at"):', "if False:"),
    "overdue invoices included": mutate(REF, "if 0 <= left <= days:", "if left <= days:"),
    "no upper bound on the window": mutate(REF, "if 0 <= left <= days:", "if 0 <= left:"),
    "unsorted result": mutate(REF, 'return sorted(picked, key=lambda inv: inv["due"])', "return picked"),
    "wrong day count in the text": mutate(REF, "left = days_until_due(invoice, today)", "left = days_until_due(invoice, today) + 1"),
    "reminder window constant changed": mutate(REF, "REMIND_DAYS = 3", "REMIND_DAYS = 4"),
}
VACUOUS = ["DueSoonTest.test_picks_invoices_due_within_three_days"]

PROBE = r'''
import json
from datetime import date
from reminders import due_soon, send_reminders
T = date(2026, 3, 10)
def inv(n, due, **kw):
    d = {"number": n, "email": n.lower() + "@example.test", "amount_cents": 1000, "due": due}
    d.update(kw)
    return d
data = [inv("C", "2026-03-13", paid_at=None), inv("A", "2026-03-10", paid_at=None), inv("B", "2026-03-11"),
        inv("D", "2026-03-12", paid_at="2026-03-01"), inv("E", "2026-03-14", paid_at=None),
        inv("F", "2026-03-09", paid_at=None)]
bad = []
got = [i["number"] for i in due_soon(data, T)]
if got != ["A", "B", "C"]:
    bad.append("due_soon: got %r, want ['A', 'B', 'C']" % got)
sent = []
n = send_reminders(data, lambda to, text: sent.append(to), today=T)
if n != 3 or sent != ["a@example.test", "b@example.test", "c@example.test"]:
    bad.append("send_reminders: got %r / %r" % (n, sent))
print(json.dumps(bad))
'''


def check(repo, message):
    try:
        return _check(repo)
    finally:
        cleanup()


def name(tid):
    return tid.split("::", 1)[1]


def _check(repo):
    out = []
    add = lambda i, ok, ev: out.append({"id": i, "passed": bool(ok), "evidence": ev})

    bad = probe_json(repo, PROBE)
    add("bug_fixed", bad == [], "behaviour probe: " + ("all cases right" if bad == [] else json.dumps(bad)[:400]))

    mine = real_tests(run_tests(repo))
    broken = [k for k, v in mine.items() if not green(v)]
    add("suite_green", mine and not broken,
        "%d test(s) on the agent's tree; not green: %s" % (len(mine), short(broken) or "none"))

    ref = run_tests(tree_copy(repo, {MODULE: REF}))
    coupled = [k for k in mine if not green(get(ref, k)) and not missing_name(get(ref, k))]
    add("green_on_reference_fix", mine and not coupled,
        "tests red on the oracle's own fixed %s: %s" % (MODULE, short(coupled) or "none"))

    live = [k for k in mine if green(get(ref, k))]
    mres = {label: run_tests(tree_copy(repo, {MODULE: src})) for label, src in MUTANTS.items()}
    survivors = [label for label, res in mres.items() if not any(red(get(res, k)) for k in live)]
    add("suite_kills_mutants", live and not survivors,
        "%d mutant(s); surviving (no test turns red): %s" % (len(MUTANTS), "; ".join(survivors) or "none"))

    nuked = run_tests(tree_copy(repo, {MODULE: nuke(REF)}))
    still_vacuous = [k for k in mine if name(k) in VACUOUS and green(get(nuked, k))]
    xres = [run_tests(tree_copy(repo, {MODULE: src})) for src in EXTRA_MUTANTS.values()]
    hollow = [k for k in live if green(get(nuked, k)) and all(green(get(res, k)) for res in list(mres.values()) + xres)]
    add("no_test_that_cannot_fail", not still_vacuous and not hollow,
        "original vacuous tests still green when every function returns a dummy: %s; tests green on the dummy and "
        "on every mutant: %s" % (short(still_vacuous) or "none", short(hollow) or "none"))
    return out
