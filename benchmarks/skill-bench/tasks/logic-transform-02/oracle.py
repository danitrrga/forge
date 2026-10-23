"""Oracle for logic-transform-02 (authored): merging records where a falsy value is not a missing value.

The docstring of merge_contacts is the contract: later records win field by field; only a field that is missing
or None keeps the earlier value. So false, 0, "" and [] from a later export replace the earlier value, None does
not, and a falsy value in the first record is kept. Values are compared with their JSON type (0 is not false).
The email is compared ignoring case and spaces, so keeping the first-seen spelling is accepted too."""
import json
import re
import subprocess
import sys

SHOP = [
    {"email": "ana@example.test", "name": "Ana", "newsletter": True, "open_balance_cents": 1250,
     "phone": "+34 600 000 001", "tags": ["vip"]},
    {"email": "ben@example.test", "name": "Ben", "newsletter": True, "open_balance_cents": 0},
]
NEWSLETTER = [
    {"email": "Ben@Example.test ", "newsletter": False},
    {"email": "cleo@example.test", "name": "Cleo", "newsletter": True},
]
CRM = [
    {"email": "ana@example.test", "name": None, "open_balance_cents": 0, "phone": "", "tags": []},
    {"email": "ben@example.test", "name": "Ben Ortiz"},
    {"email": "dan@example.test", "name": "Dan", "newsletter": False, "tags": []},
]
EXPECTED = [
    {"email": "ana@example.test", "name": "Ana", "newsletter": True, "open_balance_cents": 0, "phone": "", "tags": []},
    {"email": "ben@example.test", "name": "Ben Ortiz", "newsletter": False, "open_balance_cents": 0},
    {"email": "cleo@example.test", "name": "Cleo", "newsletter": True},
    {"email": "dan@example.test", "name": "Dan", "newsletter": False, "tags": []},
]

RUN = r'''
import copy, json
from crm.merge import merge_contacts
exports = json.loads(EXPORTS)
before = copy.deepcopy(exports)
try:
    merged = merge_contacts(*exports)
    print(json.dumps({"merged": [dict(r) for r in merged], "mutated": exports != before or
                      json.dumps(exports, sort_keys=True) != json.dumps(before, sort_keys=True)}))
except Exception as e:
    print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}))
'''


def _py(repo, code, timeout=40):
    prog = "import sys\nsys.path.insert(0, %r)\n" % repo + code
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", prog], cwd=repo, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        return None, (r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[-1][:300]
    try:
        return json.loads(lines[-1]), None
    except ValueError:
        return None, "unparseable output: " + lines[-1][:200]


def _repo_tests(repo):
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=repo, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    ran = re.search(r"Ran (\d+) test", r.stderr)
    n = int(ran.group(1)) if ran else 0
    return r.returncode == 0 and n > 0, "%d test(s) ran, exit %d: %s" % (n, r.returncode, r.stderr.strip().splitlines()[-1:])


def _norm(record):
    r = dict(record)
    if isinstance(r.get("email"), str):
        r["email"] = r["email"].strip().lower()
    return r


def _field(people, email, field):
    """JSON text of a person's field, or '<missing>'."""
    p = people.get(email)
    if p is None:
        return "<no record>"
    return json.dumps(p[field]) if field in p else "<missing>"


def check(repo, message):
    res, err = _py(repo, "EXPORTS = %r\n" % json.dumps([SHOP, NEWSLETTER, CRM]) + RUN)
    err = err or (res or {}).get("error")
    merged = [] if err else [_norm(r) for r in res["merged"]]
    people = {r.get("email"): r for r in merged}
    want = {r["email"]: r for r in EXPECTED}

    def field_check(cid, pairs):
        bad = ["%s %s = %s, want %s" % (e, f, _field(people, e, f), _field(want, e, f))
               for e, f in pairs if _field(people, e, f) != _field(want, e, f)]
        return {"id": cid, "passed": not err and not bad,
                "evidence": err or ("; ".join(bad) or "%d field(s) as the contract says" % len(pairs))}

    out = [
        field_check("later-false-unsubscribes", [("ben@example.test", "newsletter")]),
        field_check("later-zero-empty-string-empty-list-win",
                    [("ana@example.test", "open_balance_cents"), ("ana@example.test", "phone"),
                     ("ana@example.test", "tags")]),
        field_check("falsy-value-in-first-record-kept",
                    [("ben@example.test", "open_balance_cents"), ("dan@example.test", "newsletter"),
                     ("dan@example.test", "tags")]),
        field_check("none-or-missing-keeps-earlier",
                    [("ana@example.test", "name"), ("ana@example.test", "newsletter"), ("cleo@example.test", "name")]),
    ]
    exact = [json.dumps(r, sort_keys=True) for r in merged] == [json.dumps(r, sort_keys=True) for r in EXPECTED]
    out.append({"id": "whole-result-one-record-per-person-in-order", "passed": not err and exact,
                "evidence": err or ("matches" if exact else json.dumps(merged)[:300])})
    out.append({"id": "inputs-not-mutated", "passed": not err and not res["mutated"],
                "evidence": err or ("exports unchanged" if not res["mutated"] else "merge_contacts changed its input records")})
    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
