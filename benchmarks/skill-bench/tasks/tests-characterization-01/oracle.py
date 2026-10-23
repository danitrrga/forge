"""Oracle for tests-characterization-01: compute_total is restructured, pinned by tests first, and unchanged.

billing.compute_total has quirks that look like bugs and are live behaviour: lines with a negative quantity are
ignored, free domestic shipping looks at the amount BEFORE discounts, the member 5% applies only when no code gave
a discount, tax is 21% rounded half-up. A tidy rewrite (sum over all lines, shipping on the discounted amount,
discounts that stack, plain floor division) changes what customers pay. The oracle:
  pins_original     the agent's tests are green on the ORIGINAL billing.py (they describe today's behaviour; a test
                    of a helper only the agent's code has is tolerated);
  kills_mutants     each of four oracle-held quirk changes to the original turns one of those tests red;
  suite_green       the agent's tests are green on the agent's own code;
  same_behaviour    compute_total (and checkout.summary) give the original's output on ~3000 seeded inputs;
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
    'billing.py': '''# billing.py - order totals for the checkout (written 2019, "temporarily")


def compute_total(lines, code=None, country="ES", member=False):
    # lines = list of (sku, qty, unit_cents)
    t = 0
    n = 0
    for l in lines:
        if l[1] > 0:
            t = t + l[1] * l[2]
            n = n + l[1]
        else:
            if l[1] < 0:
                pass  # returns go through refunds.py, not here
    d = 0
    if code != None:
        c = code.strip().upper()
        if c == "WELCOME10":
            if t >= 3000:
                d = t * 10 // 100
        elif c == "BULK":
            if n >= 10:
                d = t * 15 // 100
            else:
                if n >= 5:
                    d = t * 5 // 100
    if member:
        if d == 0:
            d = t * 5 // 100  # members get 5% unless a code already gave something
    s = 0
    if country == "ES":
        if t < 5000:  # NB free shipping looks at the amount before discounts
            s = 490
    else:
        if country == "PT" or country == "FR":
            s = 890
        else:
            s = 1500
    taxable = t - d
    if country == "ES" or country == "PT" or country == "FR":
        x = taxable * 21
        tax = x // 100
        if x % 100 >= 50:
            tax = tax + 1
    else:
        tax = 0
    return {"subtotal": t, "discount": d, "shipping": s, "tax": tax, "total": t - d + s + tax}
''',
    'checkout.py': '''"""Checkout page: turns the cart into the summary the customer confirms."""
from billing import compute_total


def euros(cents):
    return "%d.%02d EUR" % divmod(cents, 100)


def summary(cart, code=None, country="ES", member=False):
    lines = [(item["sku"], item["qty"], item["unit_cents"]) for item in cart]
    totals = compute_total(lines, code=code, country=country, member=member)
    return {key: euros(value) for key, value in totals.items()}
''',
    'tests/test_checkout.py': '''import unittest

from checkout import euros


class EurosTest(unittest.TestCase):
    def test_formats_cents(self):
        self.assertEqual(euros(123456), "1234.56 EUR")
        self.assertEqual(euros(5), "0.05 EUR")


if __name__ == "__main__":
    unittest.main()
''',
}

MODULE = "billing.py"
MUTANTS = {
    "negative-quantity lines counted": mutate(ORIG[MODULE], "        if l[1] > 0:", "        if l[1] != 0:"),
    "free shipping judged after the discount": mutate(ORIG[MODULE], "if t < 5000:", "if t - d < 5000:"),
    "member discount stacks with a code": mutate(ORIG[MODULE], "        if d == 0:\n            d = t * 5 // 100",
                                                 "        if True:\n            d = d + t * 5 // 100"),
    "tax rounded down instead of half-up": mutate(ORIG[MODULE], "if x % 100 >= 50:", "if False:"),
}

GOLDEN = r'''
import json, random
from billing import compute_total
from checkout import summary
rng = random.Random(20261023)
codes = [None, "", "WELCOME10", " welcome10 ", "BULK", "bulk ", "WELCOME", "SAVE5"]
countries = ["ES", "PT", "FR", "DE", "US"]
cases = [
    ([("A", 1, 4990)], "WELCOME10", "ES", False), ([("A", 1, 5000)], None, "ES", False),
    ([("A", 1, 5200)], "WELCOME10", "ES", False), ([("A", 2, 2000)], "WELCOME10", "ES", True),
    ([("A", 1, 2999)], "WELCOME10", "ES", True), ([("A", 10, 100)], "BULK", "PT", False),
    ([("A", 9, 100)], "BULK", "PT", True), ([("A", 4, 100), ("B", 1, 100)], "BULK", "FR", False),
    ([("A", 3, 1000), ("R", -1, 1000)], None, "ES", False), ([("A", 0, 1000)], None, "ES", False),
    ([], None, "ES", False), ([], "BULK", "US", True), ([("A", 1, 1990)], None, "ES", False),
    ([("A", 1, 1050)], None, "FR", False), ([("A", 1, 1049)], None, "PT", False),
]
for _ in range(3000):
    lines = [("S%d" % i, rng.choice([-2, -1, 0, 1, 1, 2, 3, 5, 7, 10, 12]), rng.choice([1, 99, 250, 990, 1999, 2500, 4999, 5000]))
             for i in range(rng.randint(0, 4))]
    cases.append((lines, rng.choice(codes), rng.choice(countries), rng.random() < 0.4))
out = []
for lines, code, country, member in cases:
    try:
        r = compute_total(lines, code=code, country=country, member=member)
        r = {k: r[k] for k in ("subtotal", "discount", "shipping", "tax", "total")}
    except Exception as e:
        r = "raised %s" % type(e).__name__
    out.append(r)
cart = [{"sku": "A", "qty": 2, "unit_cents": 2650}, {"sku": "B", "qty": -1, "unit_cents": 990}]
out.append(summary(cart, code="welcome10", country="ES", member=True))
out.append(summary(cart))
print(json.dumps([cases, out]))
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
    on_orig = run_tests(tree_copy(repo, {MODULE: ORIG[MODULE]}))
    pinned = [k for k in mine if green(get(on_orig, k))]
    contradicts = [k for k in mine if not green(get(on_orig, k)) and not missing_name(get(on_orig, k))]
    add("tests_pin_original_behaviour", pinned and not contradicts,
        "%d test(s) green on the original billing.py; red on it (they describe changed behaviour): %s"
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
            i = diffs[0]
            ev += "; first: %s -> original %s, now %s" % (want[0][i] if i < len(want[0]) else "checkout.summary",
                                                         want[1][i], got[1][i])
        add("same_behaviour", not diffs and len(got[1]) == len(want[1]), ev[:500])

    o = ORIG[MODULE]
    files = py_files(repo)
    try:
        depth = max(max_depth(s) for s in files.values())
        longest = max(longest_function(s) for s in files.values())
        ok = depth < max_depth(o) or longest <= 0.75 * longest_function(o)
        ev = "nesting depth %d (original %d), longest function %d lines (original %d)" % (
            depth, max_depth(o), longest, longest_function(o))
    except SyntaxError as e:
        ok, ev = False, "unparseable: %s" % e
    add("restructured", ok, ev)
    return out
