"""Oracle for tests-characterization-02: parse_date is rewritten, pinned by tests first, and accepts and rejects
exactly what it did.

dates.parse_date is hand-rolled and full of live quirks: two-digit years pivot at 50 (50 -> 1950, 49 -> 2049;
strptime's %y pivots at 69), a middle number above 12 is read the American way round, dashes are accepted only in
ISO order, int() tolerates spaces inside the parts ("5/ 6/2026"), and anything impossible returns None instead of
raising. The usual rewrite (a strptime format list, or a regex of \\d+) changes several of these. The oracle:
  pins_original     the agent's tests are green on the ORIGINAL dates.py (a test of a helper only the agent's code
                    has is tolerated);
  kills_mutants     each of four oracle-held quirk changes to the original turns one of those tests red;
  suite_green       the agent's tests are green on the agent's own code;
  same_behaviour    parse_date gives the original's result on ~2500 typed-looking inputs (no underscores, signs or
                    non-ASCII digits: only what a guest could plausibly type), and booking.validate is unchanged;
  restructured      the code is actually reorganised: shallower nesting or a much shorter longest function.
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
    'dates.py': '''import datetime


def parse_date(s):
    # parse whatever people type in the booking form's date box
    # returns a datetime.date, or None if we can't make sense of it
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    if "-" in s:
        parts = s.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            try:
                y = int(parts[0])
                m = int(parts[1])
                d = int(parts[2])
            except ValueError:
                return None
        else:
            return None
    else:
        sep = None
        for c in "/.":
            if c in s:
                sep = c
                break
        if sep == None:
            return None
        parts = s.split(sep)
        if len(parts) != 3:
            return None
        try:
            d = int(parts[0])
            m = int(parts[1])
            y = int(parts[2])
        except ValueError:
            return None
        if len(parts[2]) == 2:
            if y >= 50:
                y = y + 1900
            else:
                y = y + 2000
        else:
            if len(parts[2]) != 4:
                return None
        if m > 12:
            if d <= 12:
                # somebody typed it the American way round
                t = d
                d = m
                m = t
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None
''',
    'booking.py': '''"""Booking form handling."""
from dates import parse_date


def validate(form, today):
    """List of error messages for the booking form (empty when it is fine)."""
    errors = []
    arrive = parse_date(form.get("arrive"))
    leave = parse_date(form.get("leave"))
    if arrive is None:
        errors.append("Arrival date not understood")
    if leave is None:
        errors.append("Departure date not understood")
    if arrive and leave:
        if leave <= arrive:
            errors.append("Departure must be after arrival")
        if arrive < today:
            errors.append("Arrival is in the past")
    return errors
''',
    'tests/test_booking.py': '''import unittest
from datetime import date

from booking import validate


class ValidateTest(unittest.TestCase):
    def test_good_form(self):
        self.assertEqual(validate({"arrive": "2026-07-01", "leave": "2026-07-04"}, date(2026, 6, 1)), [])

    def test_departure_before_arrival(self):
        errors = validate({"arrive": "2026-07-04", "leave": "2026-07-01"}, date(2026, 6, 1))
        self.assertEqual(errors, ["Departure must be after arrival"])


if __name__ == "__main__":
    unittest.main()
''',
}

MODULE = "dates.py"
O = ORIG[MODULE]
MUTANTS = {
    "two-digit years pivot at 69 (strptime's rule)": mutate(O, "if y >= 50:", "if y >= 69:"),
    "no American month/day swap": mutate(O, "        if m > 12:\n", "        if False:\n"),
    "day-first dates with dashes accepted": mutate(O, '''        else:
            return None
    else:
        sep = None''', '''        elif len(parts) == 3 and len(parts[2]) == 4:
            try:
                d = int(parts[0])
                m = int(parts[1])
                y = int(parts[2])
            except ValueError:
                return None
        else:
            return None
    else:
        sep = None'''),
    "impossible dates raise instead of returning None": mutate(O, '''        return datetime.date(y, m, d)
    except ValueError:''', '''        return datetime.date(y, m, d)
    except OverflowError:'''),
}

GOLDEN = r'''
import json, random
from datetime import date
from dates import parse_date
from booking import validate
rng = random.Random(23102026)
inputs = [None, "", "   ", "2026-10-23", " 2026-10-23 ", "2026-1-5", "2026- 01-05", "26-10-23", "23-10-2026",
          "2026-10", "2026-10-23-1", "23/10/2026", "23.10.2026", "23/10/26", "23.10.26", "1/2/49", "1/2/50",
          "1/2/68", "1/2/69", "1/2/00", "1/2/99", "10/23/2026", "10.23.26", "13/13/2026", "12/13/2026",
          "31/02/2026", "29/02/2028", "29/02/2026", "2026-02-30", "5/6/202", "5/6/02026", "23/10", "23/10/2026/1",
          "23.10/2026", "23/10.2026", "5/ 6/2026", "5 /6/2026", "5/6/ 2026", "5/6/26 ", "abc", "1/a/2026",
          "0/1/2026", "1/0/2026", "32/1/2026", "1/1/0000", "2026/10/23", "10 23 2026", "23\\10\\2026", "today"]
digits = ["0", "1", "5", "9", "01", "05", "09", "10", "12", "13", "25", "28", "29", "30", "31", "32", "00", "99", "7 ",
          " 7", "123"]
years = ["26", "49", "50", "68", "69", "99", "00", "2026", "1999", "0026", "026", "20266", "", "2O26", "28"]
for _ in range(2400):
    a, b = rng.choice(digits), rng.choice(digits)
    y = rng.choice(years)
    kind = rng.random()
    if kind < 0.45:
        s = "%s/%s/%s" % (a, b, y)
    elif kind < 0.7:
        s = "%s.%s.%s" % (a, b, y)
    elif kind < 0.9:
        s = "%s-%s-%s" % (y, a, b)
    else:
        s = "%s-%s-%s" % (a, b, y)
    inputs.append(s)
out = []
for s in inputs:
    try:
        r = parse_date(s)
        out.append(r.isoformat() if isinstance(r, date) else repr(r))
    except Exception as e:
        out.append("raised %s" % type(e).__name__)
today = date(2026, 6, 1)
for form in [{"arrive": "1/7/26", "leave": "4/7/26"}, {"arrive": "07/13/2026", "leave": "2026-07-01"},
             {"arrive": "31/6/2026", "leave": "1.7.2026"}, {}, {"arrive": "1/5/2026", "leave": "2/5/26"}]:
    out.append(validate(form, today))
print(json.dumps([inputs, out]))
'''


def check(repo, message):
    try:
        return _check(repo)
    finally:
        cleanup()


def _check(repo):
    out = []
    add = lambda i, ok, ev: out.append({"id": i, "passed": bool(ok), "evidence": ev})

    mine = real_tests(run_tests(repo))
    on_orig = run_tests(tree_copy(repo, {MODULE: O}))
    pinned = [k for k in mine if green(get(on_orig, k))]
    contradicts = [k for k in mine if not green(get(on_orig, k)) and not missing_name(get(on_orig, k))]
    add("tests_pin_original_behaviour", pinned and not contradicts,
        "%d test(s) green on the original dates.py; red on it (they describe changed behaviour): %s"
        % (len(pinned), short(contradicts) or "none"))

    survivors = []
    for label, src in MUTANTS.items():
        res = run_tests(tree_copy(repo, {MODULE: src}))
        if not any(red(get(res, k)) for k in pinned):
            survivors.append(label)
    add("tests_catch_quirk_changes", pinned and not survivors,
        "%d quirk mutant(s) of the original; not caught by any test: %s" % (len(MUTANTS), "; ".join(survivors) or "none"))

    broken = [k for k, v in mine.items() if not green(v)]
    add("suite_green_after_refactor", mine and not broken,
        "%d test(s) on the agent's tree; not green: %s" % (len(mine), short(broken) or "none"))

    want = probe_json(tree_from(ORIG), GOLDEN, timeout=50)
    got = probe_json(repo, GOLDEN, timeout=50)
    if isinstance(got, dict):
        add("same_behaviour", False, "golden run crashed: %s" % got.get("crash"))
    else:
        diffs = [i for i, (a, b) in enumerate(zip(want[1], got[1])) if a != b]
        ev = "%d inputs compared with the original; %d differ" % (len(want[1]), len(diffs))
        if diffs:
            ev += "; e.g. " + "; ".join("%r -> original %s, now %s" % (
                want[0][i] if i < len(want[0]) else "booking form", want[1][i], got[1][i]) for i in diffs[:3])
        add("same_behaviour", not diffs and len(got[1]) == len(want[1]), ev[:600])

    files = py_files(repo)
    try:
        depth = max(max_depth(s) for s in files.values())
        longest = max(longest_function(s) for s in files.values())
        ok = depth < max_depth(O) or longest <= 0.75 * longest_function(O)
        ev = "nesting depth %d (original %d), longest function %d lines (original %d)" % (
            depth, max_depth(O), longest, longest_function(O))
    except SyntaxError as e:
        ok, ev = False, "unparseable: %s" % e
    add("restructured", ok, ev)
    return out
