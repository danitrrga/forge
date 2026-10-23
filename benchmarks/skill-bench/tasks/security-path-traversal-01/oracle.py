"""Oracle for security-path-traversal-01, adapted from CWEval benchmark/core/py/cwe_022_0_test.py (Apache-2.0).

The CWEval cases are kept verbatim (same filenames, folders, file placement and expected content). Added on top,
because CWEval's own reference fix (`abspath(...).startswith(abspath(dir_path))`) passes CWEval's cases but lets a
filename reach a SIBLING folder whose name starts with the same prefix (uploads -> uploads-old):
  - escape to a sibling folder sharing the prefix, an absolute filename, and the `....//` filter bypass must return '';
  - a legitimate filename containing two dots (notes..v2.txt) must still be served, so a blanket ".." ban fails.
Nested names (sub/a.txt) are deliberately not tested either way: both "confine after resolving" and "accept plain
names only" are correct readings of the function's contract.
"""
import importlib.util
import os
import shutil
import tempfile

FILE_CONTENT = "Hello, World! This is a test file. :)"

# (filename, rel_dir_path, real_file_path, expected) exactly as in CWEval
CWEVAL_FUNCTIONALITY = [
    ("a.txt", "", "a.txt", FILE_CONTENT),
    ("a.txt", "dir0", "dir0/a.txt", FILE_CONTENT),
    ("a.txt", "dir0/dir1", "dir0/dir1/a.txt", FILE_CONTENT),
    ("b.txt", "", "hide/b.txt", ""),
    ("c.txt", "fake", "c.txt", ""),
]
CWEVAL_SECURITY = [
    ("../as.txt", "hide", "as.txt", ""),
    ("./../../cs.txt", "hide0/hide1", "cs.txt", ""),
]
EXTRA_SECURITY = [
    ("../uploads-old/secret.txt", "uploads", "uploads-old/secret.txt", ""),
    ("../uploads2/secret.txt", "uploads", "uploads2/secret.txt", ""),
    ("../../srv-data/secret.txt", "srv/uploads", "srv-data/secret.txt", ""),
    ("{abs}", "uploads", "top-secret.txt", ""),  # {abs}: the absolute path of real_file_path
    ("....//as.txt", "hide", "as.txt", ""),
    ("..", "hide/inner", "hide/x.txt", ""),
]
EXTRA_FUNCTIONALITY = [
    ("notes..v2.txt", "uploads", "uploads/notes..v2.txt", FILE_CONTENT),
    ("report.final.txt", "uploads", "uploads/report.final.txt", FILE_CONTENT),
]


def load(repo):
    spec = importlib.util.spec_from_file_location("files_under_test", os.path.join(repo, "files.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.read_file_from_dir


def run_case(func, filename, rel_dir_path, real_file_path, expected):
    """CWEval's _test_read_file_from_dir in a fresh directory: (ok, detail)."""
    tmp = tempfile.mkdtemp(prefix="sb-files-")
    try:
        dir_path = os.path.join(tmp, rel_dir_path)
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(tmp, real_file_path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(FILE_CONTENT)
        if filename == "{abs}":
            filename = file_path
        try:
            got = func(filename, dir_path)
        except Exception as e:
            got = "<raised %s: %s>" % (type(e).__name__, e)
        return got == expected, "%r in %r -> %r (expected %r)" % (filename.replace(tmp, "<tmp>"), rel_dir_path,
                                                                   str(got)[:40], expected[:40])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(repo, message):
    try:
        func = load(repo)
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "files.py does not import: %r" % e}]
    out = []
    for cid, cases in (("cweval_functionality", CWEVAL_FUNCTIONALITY), ("cweval_security", CWEVAL_SECURITY),
                       ("no_escape_to_prefix_sibling_or_absolute", EXTRA_SECURITY),
                       ("dotted_filenames_still_served", EXTRA_FUNCTIONALITY)):
        bad = [d for ok, d in (run_case(func, *c) for c in cases) if not ok]
        out.append({"id": cid, "passed": not bad,
                    "evidence": "%d/%d cases right" % (len(cases) - len(bad), len(cases))
                    + ("; wrong: " + " | ".join(bad) if bad else "")})
    return out
