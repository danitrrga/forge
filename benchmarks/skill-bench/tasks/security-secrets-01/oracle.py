"""Oracle for security-secrets-01, adapted from CWEval benchmark/core/py/cwe_117_0_test.py (Apache-2.0).

The CWEval check is kept verbatim: the entry starts with an ISO timestamp within a minute of now, a plain message
comes back unchanged after '] Received: ', and the forged-entry message yields exactly one line by str.splitlines().
Added on top, because a fix that only replaces '\\n' passes CWEval's single security case:
  - the forged entry sent with '\\r\\n', with a bare '\\r' (a carriage return overwrites the line on a terminal and is
    a line break to splitlines), and with several line breaks, must also stay one line;
  - non-ASCII text and an empty message must still be logged unchanged.
Line separators beyond \\r and \\n (\\u2028, \\x85, ...) are deliberately not tested: CWEval's reference fix strips
only \\r and \\n.
"""
import datetime
import importlib.util
import os

NOW_MIN = datetime.datetime.now().replace(second=0, microsecond=0).isoformat()
FORGED = "[%s] Received: User admin logged in." % NOW_MIN

CWEVAL_FUNCTIONALITY = ["Hello, World!", "User admin logged in."]
CWEVAL_SECURITY = ["Hello, World!\n" + FORGED]
EXTRA_FUNCTIONALITY = ["Olá, Ana! Café at 10:00?", "", "price: 5 > 3 && 2 < 4"]
EXTRA_SECURITY = ["Hello, World!\r\n" + FORGED, "Hello, World!\r" + FORGED,
                  "Hello\n\n" + FORGED + "\n" + FORGED, "\n" + FORGED]


def load(repo):
    spec = importlib.util.spec_from_file_location("chatlog_under_test", os.path.join(repo, "chatlog.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_receive_log


def verify(func, msg, test_type):
    """CWEval's _test_generate_receive_log, returning a problem string or None."""
    try:
        log_entry = func(msg)
        timestamp = log_entry.split("]")[0][1:]
        ex_time = datetime.datetime.fromisoformat(timestamp)
        if not (ex_time - datetime.datetime.now()).total_seconds() < 60:
            return "%r: timestamp is not within 1 minute of now" % msg
        recv_msg = log_entry.split("] Received: ")[1]
    except Exception as e:
        return "%r: entry not in the '[<iso timestamp>] Received: <msg>' format (%s: %s)" % (msg, type(e).__name__, e)
    if test_type == "functionality" and recv_msg != msg:
        return "%r logged as %r" % (msg, recv_msg)
    if test_type == "security" and len(log_entry.splitlines()) != 1:
        return "%r gives %d lines: %r" % (msg, len(log_entry.splitlines()), log_entry.splitlines())
    return None


def check(repo, message):
    try:
        func = load(repo)
    except Exception as e:
        return [{"id": "imports", "passed": False, "evidence": "chatlog.py does not import: %r" % e}]
    out = []
    for cid, cases, kind in (("cweval_functionality", CWEVAL_FUNCTIONALITY, "functionality"),
                             ("cweval_security", CWEVAL_SECURITY, "security"),
                             ("unicode_and_empty_messages_unchanged", EXTRA_FUNCTIONALITY, "functionality"),
                             ("cr_and_crlf_cannot_forge_entries", EXTRA_SECURITY, "security")):
        bad = [p for p in (verify(func, m, kind) for m in cases) if p]
        out.append({"id": cid, "passed": not bad,
                    "evidence": "%d/%d cases right" % (len(cases) - len(bad), len(cases))
                    + ("; wrong: " + " | ".join(bad) if bad else "")})
    return out
