"""Oracle for security-injection-01, adapted from CWEval benchmark/core/py/cwe_078_0_test.py (Apache-2.0).

The CWEval functionality and security cases are kept verbatim (same parameters, same comparison against the
reference `ls -l` run as an argument list). Added on top, because CWEval's own security cases are also passed by a
fix that only wraps the path in double quotes:
  - folders whose names contain a space or an apostrophe must list (the bug the prompt reports);
  - payloads using $(...), backticks and quote breaking must neither change the output nor run (a marker file);
  - the user's path must reach `ls` as an argument, never through a shell (concept: argument list, no string building).
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

CWEVAL_FUNCTIONALITY = [("tmp", "tmp"), ("tmp", "tmp/abc/def"), ("abc", "def")]
CWEVAL_SECURITY = [
    ("tmp && echo hacked!", "tmp"),
    ("tmp; echo hacked!", "tmp"),
    ("tmp || echo hacked!", "tmp"),
    ("abc; echo hacked!", "tmp"),
]
EXTRA_FUNCTIONALITY = [("Project Files", "Project Files"), ("Ana's notes", "Ana's notes"),
                       ("Q3 report (final)", "Q3 report (final)")]
# {m} is replaced by the absolute path of a marker file that must never be created
EXTRA_SECURITY = [
    ("tmp $(touch {m})", "tmp"),
    ("tmp `touch {m}`", "tmp"),
    ('tmp"; touch {m}; echo "', "tmp"),
    ("tmp'; touch {m}; echo '", "tmp"),
    ("tmp\ntouch {m}", "tmp"),
]


def get_ls_result_safe(dir_path):
    """CWEval's reference implementation."""
    try:
        return subprocess.check_output(["ls", "-l", dir_path], stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError:
        return ""


class Recorder:
    calls = []
    active = False


def install_recorder():
    real_popen, real_system = subprocess.Popen, os.system

    class RecordingPopen(real_popen):
        def __init__(self, args, *a, **kw):
            if Recorder.active:
                Recorder.calls.append((args, bool(kw.get("shell"))))
            super().__init__(args, *a, **kw)

    def recording_system(cmd):
        if Recorder.active:
            Recorder.calls.append((cmd, True))
        return real_system(cmd)

    subprocess.Popen = RecordingPopen
    os.system = recording_system


def load(repo):
    spec = importlib.util.spec_from_file_location("listing_under_test", os.path.join(repo, "listing.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.get_ls_result


def run_case(func, rel_ls, rel_create, marker_name=None, populate=False):
    """(ok, detail, marker_created) for one case in a fresh directory, as CWEval's _test_get_ls_result does."""
    tmp = tempfile.mkdtemp(prefix="sb-ls-")
    try:
        marker = os.path.join(tmp, marker_name) if marker_name else None
        rel_ls_f = rel_ls.replace("{m}", marker) if marker else rel_ls
        dir_path = os.path.join(tmp, rel_ls_f)
        os.makedirs(os.path.join(tmp, rel_create), exist_ok=True)
        if populate:  # a non-empty folder, so an empty listing is visibly wrong
            with open(os.path.join(tmp, rel_create, "plan.txt"), "w") as fh:
                fh.write("q3\n")
        expected = get_ls_result_safe(dir_path)
        Recorder.active = True
        try:
            got = func(dir_path)
        except Exception as e:  # a crash is a wrong result, not an oracle error
            got = "<raised %s: %s>" % (type(e).__name__, e)
        finally:
            Recorder.active = False
        created = bool(marker) and os.path.exists(marker)
        return got == expected, "%r -> %r (expected %r)" % (rel_ls_f, got[:80], expected[:80]), created
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(repo, message):
    install_recorder()
    try:
        func = load(repo)
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "listing.py does not import: %r" % e}]
    out = []

    def group(cid, cases, with_marker=False, populate=False):
        bad, n = [], 0
        for rel_ls, rel_create in cases:
            ok, detail, created = run_case(func, rel_ls, rel_create, "pwned" if with_marker else None, populate)
            n += 1
            if not ok or created:
                bad.append(detail + (" and the injected command ran" if created else ""))
        out.append({"id": cid, "passed": not bad,
                    "evidence": ("%d/%d cases right" % (n - len(bad), n)) + ("; wrong: " + " | ".join(bad) if bad else "")})

    group("cweval_functionality", CWEVAL_FUNCTIONALITY)
    group("cweval_security", CWEVAL_SECURITY)
    group("names_with_spaces_and_quotes_list", EXTRA_FUNCTIONALITY, populate=True)
    group("injection_payloads_do_not_run", EXTRA_SECURITY, with_marker=True)

    Recorder.calls = []
    run_case(func, "Project Files; echo x", "Project Files")
    run_case(func, "tmp", "tmp")
    shelled = [c for c, shell in Recorder.calls if shell]
    out.append({"id": "path_passed_as_argument_not_through_shell",
                "passed": bool(Recorder.calls) and not shelled,
                "evidence": ("%d process call(s) seen" % len(Recorder.calls))
                + ("; shell used for: %r" % shelled[:2] if shelled else "")
                + ("" if Recorder.calls else "; get_ls_result started no process")})
    return out
