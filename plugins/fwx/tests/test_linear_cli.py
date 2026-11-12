"""`fwx linear`: the command over lib/fwx/linear.py, against a fake Linear on 127.0.0.1 (port 0, no network).

Every case runs bin/fwx as a subprocess in a toy repo whose .claude/fwx.json fixes the Linear project, with
FWX_LINEAR_ENDPOINT on the fake. A control is the same case run against a copy of this repository (bin, lib, data)
with one line of the command or of the client changed, and it must fail; the last block of this test does that.

Seen red before lib/fwx/commands/linear.py existed (the file moved away), 76 checks, 44 failed; every case failed on
`fwx: unknown command: linear`:
  FAIL: list: exit 0: got 2, want 0
  FAIL: list --json is not JSON: Expecting value: line 1 column 1 (char 0)
  FAIL: fwx lists linear: stdout "usage: fwx <command> [args]\n\ncommands:\n  budget ..."
Seen red for the second round (no key is exit 2 with `LINEAR_API_KEY is not set: <fix>`, and `create` puts only the labels
an issue names, none by default: lateral bug issues carry no entry label), on the first version (exit 77, `factory` added
to every issue), 78 checks, 6 failed:
  FAIL: create two: no label unless the issue carries it: got [['lab-factory'], ['lab-factory', 'lab-mini-plan']], want [[], ['lab-mini-plan']]
  FAIL: no key (unset): exit 2: got 77, want 2
  FAIL: no key (unset): says LINEAR_API_KEY is not set, with the fix: stderr 'NOT RUN, NOT ARMED: no LINEAR_API_KEY\n ...
Controls, each seen red (the first FAIL of the case it was made for); the run is 86 checks, the last 8 being these:
  behaviour
  - `--json` printing the text form:          FAIL: list --json is not JSON: Expecting value: line 1 column 1 (char 0)
  - a random comment id (the client):         FAIL: comment twice: one comment on the issue: got 2, want 1
  - create sending only the first issue:      FAIL: create two: two identifiers: got ['TOY-101'], want ['TOY-101', 'TOY-102']
  - create adding factory to every issue:     FAIL: create two: no label unless the issue carries it: got [['lab-factory'], ['lab-factory', 'lab-mini-plan']], want [[], ['lab-mini-plan']]
  safety (PM I13)
  - no key, the request made anyway:          FAIL: no key (unset): exit 2: got 0, want 2 (and "no request reached Linear: got 1, want 0")
  - an endpoint outside 127.0.0.1 accepted:   FAIL: endpoint localhost: exit 2: got 0, want 2 (and "no request reached it: got 1, want 0")
  - `--project` other than the configured one accepted: FAIL: --project other-project: exit 2: got 0, want 2
  - `label` on another project's issue sending its mutation: FAIL: label on another project's issue: exit 2: got 0, want 2 (and "no mutation: got 1, want 0")
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import http.server

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
CFG = {"schema": 1, "project": {"linear_project": "toy-project"},
       "linear": {"labels": {"needs-owner": "toy-needs-help"}}}
OWNER = {"name": "Toy Owner", "email": "owner@example.test"}


def iso(ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago))


class Fake:
    """An in-memory Linear on 127.0.0.1: the operations the command's five subcommands need."""

    def __init__(self):
        self.requests, self.issues, self.comment_ids, self.created, self.n = [], {}, set(), {}, 0
        self.projects = {"toy-project": {"id": "p1", "teams": [{"id": "t1", "key": "TOY"}]},
                         "other-project": {"id": "p2", "teams": [{"id": "t2", "key": "OTH"}]}}
        names = ["factory", "review", "factory-review", "factory-failed", "toy-needs-help", "mini-plan", "full-plan"]
        self.labels = [{"id": "lab-" + n, "name": n, "team": None} for n in names]
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["content-length"])))
                req["auth"] = self.headers.get("authorization")
                fake.requests.append(req)
                body = json.dumps(fake.answer(req["query"], req["variables"])).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.server.handle_error = lambda *a: None
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d/graphql" % self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add_issue(self, ident, project="toy-project", labels=(), state=("Todo", "unstarted"), ago=90, assignee=None):
        self.issues[ident] = {"id": "uuid-" + ident, "identifier": ident, "title": "title of " + ident,
                              "description": "what is wrong", "updatedAt": iso(ago),
                              "state": {"name": state[0], "type": state[1]}, "labels": list(labels),
                              "project": project, "assignee": assignee, "comments": []}

    def find(self, key):
        return next((i for i in self.issues.values() if key in (i["id"], i["identifier"])), None)

    def node(self, issue, query):
        out = {"id": issue["id"], "identifier": issue["identifier"]}
        for k in ("title", "description", "updatedAt", "state", "assignee"):
            if k in query:
                out[k] = issue[k]
        if "labels" in query:
            out["labels"] = {"nodes": [{"name": n} for n in issue["labels"]]}
        if "project" in query:
            out["project"] = {"name": issue["project"]}
        if "url" in query:
            out["url"] = "https://linear.example.test/" + issue["identifier"]
        return out

    def answer(self, query, v):
        conflict = {"errors": [{"message": "conflict on insert", "extensions": {}}]}
        if "commentCreate" in query:
            i = v["input"]
            if i["id"] in self.comment_ids:
                return conflict
            self.comment_ids.add(i["id"])
            self.find(i["issueId"])["comments"].append(i["body"])
            return {"data": {"commentCreate": {"success": True}}}
        if "issueCreate" in query:
            i = v["input"]
            if i["id"] in self.created:
                return conflict
            self.n += 1
            ident = "TOY-%d" % (100 + self.n)
            self.add_issue(ident)
            self.issues[ident].update(id=i["id"], title=i["title"], description=i["description"])
            self.created[i["id"]] = ident
            return {"data": {"issueCreate": {"issue": {"id": i["id"], "identifier": ident,
                                                       "url": "https://linear.example.test/" + ident}}}}
        if "issueUpdate" in query:
            issue, i = self.find(v["id"]), v["input"]
            by_id = {l["id"]: l["name"] for l in self.labels}
            for lid in i.get("addedLabelIds", []):
                issue["labels"].append(by_id[lid])
            for lid in i.get("removedLabelIds", []):
                issue["labels"] = [n for n in issue["labels"] if n != by_id[lid]]
            return {"data": {"issueUpdate": {"success": True}}}
        if "issueLabels(" in query:
            nodes = [l for l in self.labels if l["name"].lower() == v["name"].lower()]
            return {"data": {"issueLabels": {"nodes": nodes}}}
        if "projects(" in query:
            p = self.projects.get(v["name"])
            nodes = [{"id": p["id"], "name": v["name"], "teams": {"nodes": p["teams"]}}] if p else []
            return {"data": {"projects": {"nodes": nodes}}}
        if "issues(" in query:
            hits = [i for i in self.issues.values() if i["project"] == v["project"] and set(i["labels"]) & set(v["labels"])]
            return {"data": {"issues": {"nodes": [self.node(i, query) for i in hits], "pageInfo": {"hasNextPage": False}}}}
        if "issue(" in query:
            issue = self.find(v["id"])
            if issue is None:
                return {"errors": [{"message": "Entity not found: Issue",
                                    "extensions": {"userPresentableMessage": "Could not find referenced Issue."}}]}
            return {"data": {"issue": self.node(issue, query)}}
        raise AssertionError("the fake does not know this query: " + query)

    def mutations(self):
        return [r for r in self.requests if r["query"].lstrip().startswith("mutation")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def tree(changes):
    """A copy of bin, lib and data in a temp dir with `changes` ({relpath: [(old, new)]}) applied; each `old` must be
    in the file, so a control that no longer matches the code is an error and not a silent pass."""
    dest = helpers.mkdtemp("fwx-linear-cli-")
    for d in ("bin", "lib", "data"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(dest, d), ignore=shutil.ignore_patterns("__pycache__"))
    for rel, pairs in changes.items():
        p = os.path.join(dest, rel)
        text = open(p, encoding="utf-8").read()
        for old, new in pairs:
            assert old in text, "control: %r is not in %s" % (old, rel)
            text = text.replace(old, new, 1)
        open(p, "w", encoding="utf-8").write(text)
    return dest


def env(fake=None, key="key-123", **extra):
    e = helpers.clean_env()
    for k in list(e):
        if k.lower().endswith("_proxy") or k in ("LINEAR_API_KEY", "FWX_LINEAR_ENDPOINT"):
            del e[k]
    e["no_proxy"] = "*"
    if key is not None:
        e["LINEAR_API_KEY"] = key
    if fake is not None:
        e["FWX_LINEAR_ENDPOINT"] = fake.url  # no case reaches Linear: the endpoint is always the fake
    e.update(extra)
    return e


def cli(root, cwd, fake, *args, stdin=None, **kw):
    return subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "linear"] + list(args), cwd=cwd,
                          env=env(fake, **kw), input=stdin, capture_output=True, text=True, timeout=60)


# --- the cases: each takes a Suite, the root of the tree to run, and the two toy repos ---------------------------------
def case_list(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-1", labels=["factory"], state=("In Progress", "started"))
    f.add_issue("TOY-2", project="other-project", labels=["factory"])
    f.add_issue("TOY-3", labels=["review"])
    f.add_issue("TOY-4", labels=["toy-needs-help"], assignee=OWNER)
    r = cli(root, repo, f, "list", "--label", "factory")
    s.eq("list: exit 0", r.returncode, 0)
    s.ok("list: the pinned project's issue", "TOY-1" in r.stdout, "stdout %r" % r.stdout)
    s.ok("list: not another project's, not another label's", "TOY-2" not in r.stdout and "TOY-3" not in r.stdout,
         "stdout %r" % r.stdout)
    asked = [q["variables"] for q in f.requests if "project" in q["variables"]]
    s.ok("list: the query is fixed to the configured project", asked and all(a["project"] == "toy-project" for a in asked),
         "got %r" % asked)
    r = cli(root, repo, f, "list", "--label", "factory", "--json")
    s.eq("list --json: exit 0", r.returncode, 0)
    try:
        got = json.loads(r.stdout)
    except ValueError as e:
        s.ok("list --json is not JSON", False, str(e))
        got = []
    s.eq("list --json: the identifiers", [i["identifier"] for i in got], ["TOY-1"])
    if got:
        s.eq("list --json: the state with its type", got[0]["state"], {"name": "In Progress", "type": "started"})
        s.eq("list --json: the project", got[0]["project"], "toy-project")
        s.ok("list --json: labels, title, description, updatedAt",
             got[0]["labels"] == ["factory"] and got[0]["title"] and got[0]["description"] and got[0]["updatedAt"],
             "got %r" % got[0])
    r = cli(root, repo, f, "list", "--label", "needs-owner", "--json")
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = []
    s.eq("list: the neutral label is asked for, and comes back neutral", [i["labels"] for i in got], [["needs-owner"]])
    s.eq("list: the assignee is kept", [i["assignee"] for i in got], [OWNER])
    s.eq("list without --label: exit 2", cli(root, repo, f, "list").returncode, 2)
    f.close()


def case_waiting(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-4", labels=["toy-needs-help"], ago=3600)
    f.add_issue("TOY-5", labels=["factory-review"], ago=60)
    f.add_issue("TOY-6", labels=["factory"])
    f.add_issue("OTH-1", project="other-project", labels=["factory-failed"])
    r = cli(root, repo, f, "waiting", "--json")
    s.eq("waiting --json: exit 0", r.returncode, 0)
    try:
        got = json.loads(r.stdout)
    except ValueError as e:
        s.ok("waiting --json is not JSON", False, str(e))
        got = {"count": None, "issues": []}
    s.eq("waiting --json: the count", got["count"], 2)
    s.eq("waiting --json: the issues, all of this project", sorted(i["identifier"] for i in got["issues"]), ["TOY-4", "TOY-5"])
    s.ok("waiting --json: updatedAt on each", all(i.get("updatedAt") for i in got["issues"]), "got %r" % got)
    r = cli(root, repo, f, "waiting")
    s.ok("waiting: the text says how many", r.returncode == 0 and r.stdout.startswith("2 waiting"), "stdout %r" % r.stdout)
    f.close()


def case_comment(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-1", labels=["factory"])
    f.add_issue("OTH-1", project="other-project")
    first = cli(root, repo, f, "comment", "TOY-1", "--kind", "claim", stdin="picked up\nby a job\n")
    again = cli(root, repo, f, "comment", "TOY-1", "--kind", "claim", stdin="picked up\nby a job\n")
    s.eq("comment: exit 0", (first.returncode, again.returncode), (0, 0))
    s.ok("comment twice: the first creates, the second says it was there",
         first.stdout.startswith("commented") and again.stdout.startswith("already commented"),
         "stdout %r then %r" % (first.stdout, again.stdout))
    cs = f.issues["TOY-1"]["comments"]
    s.eq("comment twice: one comment on the issue", len(cs), 1)
    s.ok("comment: the mark is the first line, the body follows",
         cs and cs[0] == "<!-- fwx:claim -->\npicked up\nby a job\n", "got %r" % cs)
    r = cli(root, repo, f, "comment", "TOY-1", "--kind", "claim", stdin="   \n")
    s.eq("comment with an empty body: exit 2", r.returncode, 2)
    s.eq("comment without --kind: exit 2", cli(root, repo, f, "comment", "TOY-1", stdin="x").returncode, 2)
    r = cli(root, repo, f, "comment", "OTH-1", "--kind", "claim", stdin="x")
    s.eq("comment on another project's issue: exit 2", r.returncode, 2)
    s.eq("comment on another project's issue: nothing written", f.issues["OTH-1"]["comments"], [])
    r = cli(root, repo, f, "comment", "TOY-999", "--kind", "claim", stdin="x")
    s.ok("comment on an issue that does not exist: exit 2, says so", r.returncode == 2 and ("no issue" in r.stderr.lower() or "could not find" in r.stderr.lower()), "exit %d stderr %r" % (r.returncode, r.stderr))
    f.close()


def case_create(s, root, repo, bare):
    f = Fake()
    two = [{"title": "first", "context": "c1", "expected": "e1"},
           {"title": "second", "context": "c2", "expected": "e2", "labels": ["mini-plan"]}]
    r = cli(root, repo, f, "create", "--template", "general", stdin=json.dumps(two))
    s.eq("create two: exit 0", r.returncode, 0)
    ids = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
    s.eq("create two: two identifiers", ids, ["TOY-101", "TOY-102"])
    sent = [m["variables"]["input"]["labelIds"] for m in f.mutations() if "issueCreate" in m["query"]]
    s.eq("create two: no label unless the issue carries it", sent, [[], ["lab-mini-plan"]])
    s.ok("create: the description is the template's, with the sections",
         f.issues.get("TOY-101", {}).get("description", "").startswith("## Context\n\nc1"),
         "got %r" % f.issues.get("TOY-101"))
    n = len(f.created)
    r = cli(root, repo, f, "create", "--template", "general", stdin=json.dumps(two))
    s.ok("create replayed: nothing new, said so", r.returncode == 0 and len(f.created) == n and "already there" in r.stdout,
         "exit %d, created %d, stdout %r" % (r.returncode, len(f.created), r.stdout))
    r = cli(root, repo, f, "create", "--template", "general", stdin=json.dumps({"title": "one", "context": "c", "expected": "e"}))
    s.ok("create one issue as an object", r.returncode == 0 and r.stdout.startswith("TOY-103"), "stdout %r" % r.stdout)
    r = cli(root, repo, f, "create", "--template", "general",
            stdin=json.dumps({"title": "entry", "context": "c", "expected": "e", "labels": ["factory", "needs-owner"]}))
    sent = [m["variables"]["input"]["labelIds"] for m in f.mutations() if "issueCreate" in m["query"]][-1]
    s.eq("create: the labels the issue names, by their Linear names", (r.returncode, sent),
         (0, ["lab-factory", "lab-toy-needs-help"]))
    n += 1
    for label, text in (("not JSON", "title: x"), ("empty", ""), ("a number", "3"),
                        ("an issue with no expected", json.dumps({"title": "t", "context": "c"}))):
        r = cli(root, repo, f, "create", "--template", "general", stdin=text)
        s.eq("create with stdin %s: exit 2" % label, r.returncode, 2)
    r = cli(root, repo, f, "create", "--template", "nope", stdin=json.dumps(two[0]))
    s.eq("create with an unknown template: exit 2", r.returncode, 2)
    s.eq("create refused: nothing more was created", len(f.created), n + 1)
    f.close()


def case_label(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-1", labels=["factory", "toy-needs-help"])
    f.add_issue("OTH-1", project="other-project")
    r = cli(root, repo, f, "label", "TOY-1", "+factory-review", "-needs-owner")
    s.eq("label: exit 0", r.returncode, 0)
    s.eq("label: added and removed, by the Linear names", sorted(f.issues["TOY-1"]["labels"]), ["factory", "factory-review"])
    before = len(f.mutations())
    r = cli(root, repo, f, "label", "OTH-1", "+needs-owner")
    s.eq("label on another project's issue: exit 2", r.returncode, 2)
    s.ok("label on another project's issue: the message names the project", "other-project" in r.stderr, "stderr %r" % r.stderr)
    s.eq("label on another project's issue: no mutation", len(f.mutations()) - before, 0)
    for args in (["-factory"], ["-review"], ["+Bug"]):
        r = cli(root, repo, f, "label", "TOY-1", *args)
        s.eq("label %s (not ours to set or take): exit 2" % args[0], r.returncode, 2)
    s.eq("label with nothing to do: exit 2", cli(root, repo, f, "label", "TOY-1").returncode, 2)
    s.eq("label with a bare word: exit 2", cli(root, repo, f, "label", "TOY-1", "review").returncode, 2)
    f.close()


def case_no_key(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-1", labels=["factory"])
    for label, kw in (("unset", {"key": None}), ("empty", {"key": ""})):
        r = cli(root, repo, f, "list", "--label", "factory", **kw)
        s.eq("no key (%s): exit 2" % label, r.returncode, 2)
        s.ok("no key (%s): says LINEAR_API_KEY is not set, with the fix" % label,
             r.stderr.startswith("LINEAR_API_KEY is not set: ") and "forge" in r.stderr, "stderr %r" % r.stderr)
    r = cli(root, repo, f, "comment", "TOY-1", "--kind", "claim", stdin="x", key=None)
    s.eq("no key, a write: exit 2", r.returncode, 2)
    s.eq("no key: no request reached Linear", len(f.requests), 0)
    f.close()


def case_endpoint(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-1", labels=["factory"])
    ok = cli(root, repo, f, "list", "--label", "factory")
    s.ok("the loopback override is read: the fake answered", ok.returncode == 0 and f.requests, "exit %d" % ok.returncode)
    s.eq("the key goes as the bare authorization header", {q["auth"] for q in f.requests}, {"key-123"})
    f.requests.clear()
    for label, url in (("localhost", "http://localhost:%d/graphql" % f.port),
                       ("127.0.0.2", "http://127.0.0.2:%d/graphql" % f.port)):
        r = subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "linear", "list", "--label", "factory"],
                           cwd=repo, env=env(None, FWX_LINEAR_ENDPOINT=url), capture_output=True, text=True, timeout=60)
        s.eq("endpoint %s: exit 2" % label, r.returncode, 2)
        s.ok("endpoint %s: the message names 127.0.0.1" % label, "127.0.0.1" in r.stderr, "stderr %r" % r.stderr)
        s.eq("endpoint %s: no request reached it" % label, len(f.requests), 0)
    f.close()


def case_project(s, root, repo, bare):
    f = Fake()
    f.add_issue("TOY-1", labels=["factory"])
    f.add_issue("OTH-1", project="other-project", labels=["factory"])
    r = cli(root, repo, f, "--project", "toy-project", "list", "--label", "factory")
    s.ok("--project the same as the configured one: accepted", r.returncode == 0 and "TOY-1" in r.stdout, "exit %d" % r.returncode)
    f.requests.clear()
    r = cli(root, repo, f, "--project", "other-project", "list", "--label", "factory")
    s.eq("--project other-project: exit 2", r.returncode, 2)
    s.ok("--project other-project: the message names both", "other-project" in r.stderr and "toy-project" in r.stderr,
         "stderr %r" % r.stderr)
    s.eq("--project other-project: no request", len(f.requests), 0)
    r = cli(root, bare, f, "list", "--label", "factory")
    s.ok("no .claude/fwx.json and no --project: exit 2, says so", r.returncode == 2 and "--project" in r.stderr,
         "exit %d stderr %r" % (r.returncode, r.stderr))
    r = cli(root, bare, f, "--project", "toy-project", "list", "--label", "factory")
    s.ok("no .claude/fwx.json, --project: accepted", r.returncode == 0 and "TOY-1" in r.stdout, "exit %d" % r.returncode)
    f.close()


def case_failures(s, root, repo, bare):
    port = helpers.free_port()
    e = env(None, FWX_LINEAR_ENDPOINT="http://127.0.0.1:%d/graphql" % port)
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "linear", "list", "--label", "factory"],
                       cwd=repo, env=e, capture_output=True, text=True, timeout=60)
    s.ok("Linear unreachable: exit 1, says so", r.returncode == 1 and "cannot reach" in r.stderr, "exit %d stderr %r" % (r.returncode, r.stderr))
    f = Fake()
    for args in ([], ["nope"], ["list", "--label", "factory", "extra"], ["waiting", "--bogus"], ["--project"]):
        r = cli(root, repo, f, *args)
        s.eq("usage %r: exit 2" % (args,), r.returncode, 2)
    r = cli(root, repo, f, "--help")
    s.ok("--help: exit 0, the usage on stdout", r.returncode == 0 and "usage: fwx linear" in r.stdout, "exit %d" % r.returncode)
    s.eq("usage and help made no request", len(f.requests), 0)
    f.close()
    r = helpers.fwx(repo, "help")
    s.ok("fwx lists linear", any(l.split()[:1] == ["linear"] for l in r.stdout.splitlines()), "stdout %r" % r.stdout)


CASES = [case_list, case_waiting, case_comment, case_create, case_label, case_no_key, case_endpoint, case_project,
         case_failures]
CMD = "lib/fwx/commands/linear.py"
LIB = "lib/fwx/linear.py"
# control name -> (case it must fail, the first fail's needle, {file: [(old, new)]})
CONTROLS = [
    ("`--json` printing the text form", case_list, "list --json is not JSON",
     {CMD: [("    if as_json:\n        print(json.dumps(issues, indent=2))\n    else:\n        for i in issues:",
             "    if False:\n        print(json.dumps(issues, indent=2))\n    else:\n        for i in issues:")]}),
    ("a random comment id (the client)", case_comment, "comment twice: one comment on the issue",
     {LIB: [('cid = comment_id(ref["identifier"], kind, hashlib.sha256(body.encode("utf-8")).hexdigest())',
             'cid = comment_id(ref["identifier"], kind, hashlib.sha256(body.encode("utf-8")).hexdigest(), str(time.time_ns()))')]}),
    ("create sending only the first issue", case_create, "create two: two identifiers",
     {CMD: [("client.create(template, items)", "client.create(template, items[:1])")]}),
    ("create adding factory to every issue", case_create, "create two: no label unless the issue carries it",
     {CMD: [("        for got in client.create(template, items):",
             '        for i in items:\n            i["labels"] = ["factory"] + [l for l in i.get("labels") or [] if l != "factory"]\n'
             "        for got in client.create(template, items):")]}),
    ("no key, the request made anyway", case_no_key, "no key: no request reached Linear",
     {CMD: [("key = os.environ.get(KEY)\n", 'key = os.environ.get(KEY) or "anonymous"\n')]}),
    ("an endpoint outside 127.0.0.1 accepted", case_endpoint, "no request reached it",
     {LIB: [("if endpoint != ENDPOINT and not loopback:", "if False:")]}),
    ("`--project` other than the configured one accepted", case_project, "--project other-project: exit 2",
     {CMD: [("if asked is not None and asked != configured:", "if False:"),
            ("        return configured\n    if not asked:", "        return asked or configured\n    if not asked:")]}),
    ("`label` on another project's issue sending its mutation", case_label, "no mutation",
     {LIB: [("        if name != self.project_name:", "        if False:")]}),
]


def main():
    s = helpers.Suite()
    repo = helpers.toy_repo({".claude/fwx.json": json.dumps(CFG), "README": "toy\n"})
    bare = helpers.toy_repo()
    for case in CASES:
        case(s, ROOT, repo, bare)
    print("%d checks on the command" % s.checks)
    for name, case, needle, changes in CONTROLS:
        root = tree(changes)
        c = helpers.Suite()
        case(c, root, repo, bare)
        hit = [l for l in c.fails if needle in l]
        s.ok("control %s: fails with %r" % (name, needle), hit, "its failures: %r" % c.fails[:3])
        shutil.rmtree(root, ignore_errors=True)
    s.done()


if __name__ == "__main__":
    main()
