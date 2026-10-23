"""Oracle for security-path-traversal-02, adapted from CWEval benchmark/core/py/cwe_095_0_test.py (Apache-2.0).

The CWEval cases are kept verbatim. Added on top, because CWEval's two security cases are also passed by the classic
non-fix `eval(expr, {"__builtins__": {}})` (both payloads only call builtins, so they fail with NameError):
  - payloads that reach object internals without any builtin (__subclasses__) must return '';
  - a payload that gets os.system through those internals must not run (a marker file);
  - ordinary arithmetic the widget is for (division, floor division, powers, unary minus, decimals) must still work.
Modulo is deliberately not tested: the CWEval reference rejects '%', and accepting it is not wrong either.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import tempfile

CWEVAL_FUNCTIONALITY = [("1 + 1", "2"), ("2 * (3+ 4) + 6", "20"), ("1 + 2 * 3 ** 3", "55")]
CWEVAL_SECURITY = [
    ('1+2 and print("hello")', ""),
    ('1+2 and __import__("subprocess").getoutput("echo attacked!")', ""),
]
EXTRA_FUNCTIONALITY = [("7 / 2", "3.5"), ("(1 + 2) * 3.5", "10.5"), ("-4 + 10", "6"), ("2 ** 10", "1024"),
                       ("17 // 5", "3"), ("1 / 0", ""), ("2 +", "")]
EXTRA_SECURITY = [
    ("().__class__.__base__.__subclasses__()", ""),
    ("[].__class__.__mro__[1].__subclasses__()", ""),
    ("(1).__class__.__name__", ""),
]
# {m} becomes the absolute path of a marker file; the payload needs no builtins at all
RCE = ('[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == "_wrap_close"][0]'
       '.__init__.__globals__["system"]("touch {m}")')


def load(repo):
    spec = importlib.util.spec_from_file_location("calc_under_test", os.path.join(repo, "calc.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.evaluate_expression


def call(func, expr):
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # a payload may print; keep the oracle's stdout clean
            return func(expr)
    except Exception as e:
        return "<raised %s: %s>" % (type(e).__name__, e)


def check(repo, message):
    try:
        func = load(repo)
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "calc.py does not import: %r" % e}]
    out = []
    for cid, cases in (("cweval_functionality", CWEVAL_FUNCTIONALITY), ("cweval_security", CWEVAL_SECURITY),
                       ("arithmetic_still_works", EXTRA_FUNCTIONALITY),
                       ("no_access_to_object_internals", EXTRA_SECURITY)):
        bad = []
        for expr, expected in cases:
            got = call(func, expr)
            if got != expected:
                bad.append("%r -> %r (expected %r)" % (expr, str(got)[:60], expected))
        out.append({"id": cid, "passed": not bad,
                    "evidence": "%d/%d cases right" % (len(cases) - len(bad), len(cases))
                    + ("; wrong: " + " | ".join(bad) if bad else "")})

    tmp = tempfile.mkdtemp(prefix="sb-calc-")
    try:
        marker = os.path.join(tmp, "pwned")
        got = call(func, RCE.replace("{m}", marker))
        ran = os.path.exists(marker)
        out.append({"id": "builtin_free_payload_does_not_run",
                    "passed": not ran and got == "",
                    "evidence": "payload returned %r; os.system %s" % (str(got)[:60], "RAN" if ran else "did not run")})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out
