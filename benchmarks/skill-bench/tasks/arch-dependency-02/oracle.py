"""Oracle for arch-dependency-02: store no longer depends on services, and every save still updates the search
index and the audit trail, including the saves admin_import makes straight through store.

store.save_user calls services.on_user_saved (search index + audit), an upward import that ARCHITECTURE.md forbids
and that makes store and services import each other. The tempting fix moves the call up into services.register /
rename_user, which silently drops indexing and auditing for admin_import.py, the bulk importer that calls
store.save_user directly. The other quick fix, an import moved inside the function, keeps the cycle. The oracle:
  no_cycle / layering  import graph from the standard-library ast (imports anywhere count, TYPE_CHECKING blocks do
                       not): no cycle; store and search reach neither services nor admin_import;
  same_behaviour       two scenarios, each in a fresh interpreter, give the original's search results, audit trail
                       and stored users: the bulk import (admin_import alone, as its CLI runs) and the service calls
                       (register, rename, refused duplicates, invalid e-mails);
  callers_unchanged    admin_import.py is unchanged (same AST), the public names still import from the same
                       modules, and the original tests are green.
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
    'store.py': '''"""User storage (in memory here; the real one is a database)."""
import services

_USERS = {}


def save_user(user):
    if "@" not in user.get("email", ""):
        raise ValueError("invalid email: %r" % user.get("email"))
    _USERS[user["id"]] = dict(user)
    services.on_user_saved(dict(user))


def get_user(user_id):
    user = _USERS.get(user_id)
    return dict(user) if user else None


def all_users():
    return [dict(u) for u in _USERS.values()]
''',
    'search.py': '''"""Name search over users."""

_INDEX = {}  # lower-case word -> set of user ids


def index_user(user):
    for ids in _INDEX.values():
        ids.discard(user["id"])
    for word in user["name"].lower().split():
        _INDEX.setdefault(word, set()).add(user["id"])


def find(word):
    return sorted(_INDEX.get(word.lower(), ()))
''',
    'services.py': '''"""User operations used by the web app."""
import search
import store

_AUDIT = []


def on_user_saved(user):
    """Run after every save: keeps the search index and the audit trail current."""
    search.index_user(user)
    _AUDIT.append(("saved", user["id"], user["name"]))


def register(user_id, name, email):
    if store.get_user(user_id) is not None:
        raise ValueError("user %s already exists" % user_id)
    store.save_user({"id": user_id, "name": name, "email": email})


def rename_user(user_id, name):
    user = store.get_user(user_id)
    if user is None:
        raise KeyError(user_id)
    user["name"] = name
    store.save_user(user)


def audit_log():
    return list(_AUDIT)
''',
    'admin_import.py': '''"""Bulk import of users from the old system's CSV export:  python3 admin_import.py users.csv"""
import csv
import sys

import services
import store


def import_rows(rows):
    count = 0
    for row in rows:
        store.save_user({"id": row["id"], "name": row["name"], "email": row["email"]})
        count += 1
    return count


def main(path):
    with open(path, newline="", encoding="utf-8") as fh:
        count = import_rows(csv.DictReader(fh))
    print("%d users imported, %d audit entries" % (count, len(services.audit_log())))


if __name__ == "__main__":
    main(sys.argv[1])
''',
    'tests/test_services.py': '''import unittest

import search
import services
import store


class ServicesTest(unittest.TestCase):
    def test_register_then_rename_updates_search(self):
        services.register("u1", "Ana Ruiz", "ana@example.test")
        self.assertEqual(search.find("ana"), ["u1"])
        services.rename_user("u1", "Ana Ortiz")
        self.assertEqual(search.find("ruiz"), [])
        self.assertEqual(search.find("ortiz"), ["u1"])
        self.assertEqual(store.get_user("u1")["name"], "Ana Ortiz")

    def test_register_twice_is_refused(self):
        services.register("u2", "Ben", "ben@example.test")
        with self.assertRaises(ValueError):
            services.register("u2", "Ben", "ben@example.test")


if __name__ == "__main__":
    unittest.main()
''',
}

FORBIDDEN = {"store": ("services", "admin_import"), "search": ("services", "admin_import"),
             "services": ("admin_import",)}

BULK = r'''
import contextlib, io, json, os, tempfile
import admin_import
import search, services, store
out = {}
out["n"] = admin_import.import_rows([
    {"id": "u1", "name": "Ana Ruiz", "email": "ana@example.test"},
    {"id": "u2", "name": "Ben Ortiz", "email": "ben@example.test"},
    {"id": "u1", "name": "Ana Maria Ruiz", "email": "ana@example.test"},
])
try:
    admin_import.import_rows([{"id": "u3", "name": "Cy Park", "email": "cy.example.test"}])
    out["bad_email"] = "accepted"
except Exception as e:
    out["bad_email"] = type(e).__name__
d = tempfile.mkdtemp()
p = os.path.join(d, "users.csv")
with open(p, "w", encoding="utf-8") as fh:
    fh.write("id,name,email\nu4,Dee Lam,dee@example.test\nu5,Eve Ortiz,eve@example.test\n")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    admin_import.main(p)
out["cli"] = buf.getvalue()
out["find"] = {w: search.find(w) for w in ("ana", "maria", "ruiz", "ortiz", "cy", "dee", "eve", "ben")}
out["audit"] = services.audit_log()
out["users"] = store.all_users()
print(json.dumps(out))
'''

SERVICE = r'''
import json
import services
import search, store
out = {"errors": []}
services.register("u1", "Ana Ruiz", "ana@example.test")
services.register("u2", "Ben Ortiz", "ben@example.test")
services.rename_user("u1", "Ana Ortiz")
for call in (lambda: services.register("u2", "Ben", "ben@example.test"), lambda: services.rename_user("nobody", "X"),
             lambda: services.register("u3", "Cy Park", "no-at-sign")):
    try:
        call()
        out["errors"].append("none")
    except Exception as e:
        out["errors"].append(type(e).__name__)
out["find"] = {w: search.find(w) for w in ("ana", "ruiz", "ortiz", "ben", "cy", "park")}
out["audit"] = services.audit_log()
out["users"] = store.all_users()
out["get"] = [store.get_user("u1"), store.get_user("u3")]
print(json.dumps(out))
'''


def code_shape(src):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            node.body = node.body[1:]
    return ast.dump(tree)


def check(repo, message):
    try:
        return _check(repo)
    finally:
        cleanup()


def _check(repo):
    out = []
    add = lambda i, ok, ev: out.append({"id": i, "passed": bool(ok), "evidence": ev})
    try:
        graph = import_graph(py_files(repo))
    except SyntaxError as e:
        graph = None
        for i in ("no_cycle", "layering"):
            add(i, False, "unparseable: %s" % e)
    if graph is not None:
        cyc = find_cycle(graph)
        edges = sum(len(v) for v in graph.values())
        add("no_cycle", edges and not cyc, "%d modules, %d import edges; cycle: %s"
            % (len(graph), edges, " -> ".join(cyc) if cyc else "none"))
        wrong = ["%s reaches %s" % (low, high) for low, highs in FORBIDDEN.items() if low in graph
                 for high in highs if high in reaches(graph, low)]
        missing = [m for m in FORBIDDEN if m not in graph]
        add("layering", not wrong and not missing,
            "upward dependencies: %s%s" % ("; ".join(wrong) or "none", "; missing modules: %s" % missing if missing else ""))

    orig = tree_from(ORIG)
    diffs = []
    for label, code in (("bulk import", BULK), ("service calls", SERVICE)):
        want, got = probe_json(orig, code), probe_json(repo, code)
        if "crash" in got:
            diffs.append("%s: crashed: %s" % (label, got["crash"]))
            continue
        for key in want:
            if want[key] != got.get(key):
                diffs.append("%s: %s is %r, was %r" % (label, key, got.get(key), want[key]))
    add("same_behaviour", not diffs, "; ".join(diffs)[:600] or "bulk import and service scenarios match the original")

    probs = []
    try:
        if code_shape(open(os.path.join(repo, "admin_import.py"), encoding="utf-8").read()) != code_shape(ORIG["admin_import.py"]):
            probs.append("admin_import.py was changed")
    except (OSError, SyntaxError) as e:
        probs.append("admin_import.py: %s" % e)
    rc, _, err = run_py(repo, "from store import save_user, get_user, all_users\nfrom search import find\n"
                              "from services import register, rename_user, audit_log\nfrom admin_import import import_rows, main\n")
    if rc:
        probs.append("public names: %s" % (err.strip().splitlines() or ["?"])[-1][:150])
    t = "tests/test_services.py"
    orig_ids = set(real_tests(run_tests(orig)))
    res = run_tests(tree_copy(repo, {t: ORIG[t]}))
    bad = [k for k in orig_ids if not green(get(res, k))]
    if not orig_ids or bad:
        probs.append("original tests not green: %s" % (short(bad) or "none ran"))
    add("callers_unchanged", not probs, "; ".join(probs) or "admin_import.py unchanged, public names import, original tests green")
    return out
