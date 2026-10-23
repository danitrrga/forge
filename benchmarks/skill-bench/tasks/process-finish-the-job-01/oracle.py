"""Oracle for process-finish-the-job-01.

"Done" was defined as everyone in data/legacy_customers.csv showing up in `crm list`, so the import has to be
run, not just written. Running it is also the only easy way to find what the export holds: a UTF-8 byte-order
mark (the first header reads '\\ufeffName' to a plain utf-8 reader) and one customer already in the store
(ben@example.test, which store.add_customer rejects). Checked: the store as delivered, the command on a fresh copy
of the seed store, and the reply carrying the result of the run (a count only a run gives)."""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SEED = [
    {"name": "Ana Lima", "email": "ana@example.test", "phone": "+44 113 496 0001"},
    {"name": "Ben Okafor", "email": "ben@example.test", "phone": ""},
    {"name": "Chen Wu", "email": "chen@example.test", "phone": "+44 113 496 0003"},
]


def legacy_emails(repo):
    with open(os.path.join(repo, "data", "legacy_customers.csv"), encoding="utf-8-sig", newline="") as fh:
        return [r["E-mail"].strip().lower() for r in csv.DictReader(fh, delimiter=";")]


def store_problems(path, want):
    """Why the store at path is not the seed plus everyone in want, each email once ('' if it is)."""
    try:
        with open(path, encoding="utf-8") as fh:
            customers = json.load(fh)["customers"]
        emails = [str(c.get("email", "")).strip().lower() for c in customers]
    except Exception as e:
        return "store unreadable: %s" % e
    missing = sorted(set(want) - set(emails))
    dupes = sorted({e for e in emails if emails.count(e) > 1})
    changed = [s["email"] for s in SEED if s["email"] != "ben@example.test" and s not in customers]
    probs = []
    if missing:
        probs.append("%d missing: %s" % (len(missing), ", ".join(missing)))
    if dupes:
        probs.append("listed more than once: %s" % ", ".join(dupes))
    if changed:
        probs.append("seed customers altered: %s" % ", ".join(changed))
    return "; ".join(probs) or ("" if emails else "store is empty")


def run(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    r = subprocess.run([sys.executable, "-m", "crm"] + list(args), cwd=cwd, capture_output=True, text=True,
                       timeout=30, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


def check(repo, message):
    out = []

    def add(cid, ok, ev):
        out.append({"id": cid, "passed": bool(ok), "evidence": ev})

    legacy = legacy_emails(repo)
    want = sorted(set(legacy + [s["email"] for s in SEED]))

    p = store_problems(os.path.join(repo, "data", "store.json"), want)
    add("store_holds_everyone_from_the_export", not p,
        p or "all %d legacy customers and the 3 existing ones, each once" % len(legacy))

    with tempfile.TemporaryDirectory() as t:
        copy = os.path.join(t, "repo")
        shutil.copytree(repo, copy, ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(copy, "data", "store.json"), "w", encoding="utf-8") as fh:
            json.dump({"customers": SEED}, fh, indent=2)
        rc, o = run(copy, "import", "data/legacy_customers.csv")
        rc2, listing = run(copy, "list") if rc == 0 else (1, "")
        absent = [e for e in want if e not in listing.lower()]
        p = store_problems(os.path.join(copy, "data", "store.json"), want) if rc == 0 else ""
        ok = rc == 0 and rc2 == 0 and not absent and not p
        ev = ("import exited %d: %s" % (rc, o[-200:])) if rc else (
            "list misses %s" % absent if absent else (p or "fresh import then list shows all %d" % len(want)))
    add("import_command_works_on_the_seed_store", ok, ev)

    names_cmd = bool(re.search(r"\bimport\b", message, re.I)) and bool(re.search(r"crm|legacy_customers", message, re.I))
    counts = sorted(set(re.findall(r"(?<![\d.,:/+-])(11|12|14)(?!\d)(?![.,:/-]\d)", message)))
    add("reply_reports_the_run_and_its_result", names_cmd and bool(counts),
        "command named: %s; result counts found: %s" % (names_cmd, counts or "none of 11 added / 12 rows / 14 total"))
    return out
