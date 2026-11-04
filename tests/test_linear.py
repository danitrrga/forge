"""lib/fwx/linear.py: the Linear client, against a fake Linear behind a loopback HTTP server (no network).

copied-from: marshal-factory scripts/linear-regressions.ts @999ad20, adapted (the retry, reset-after and
conflict cases, over a real socket instead of a fake fetch; the rest is the client's own rules)

Seen red before linear.py existed:
  ImportError: cannot import name 'linear' from 'fwx' (lib/fwx/linear.py absent)
Seen red for the owner's addition (decision 22: `issues()`, `issue()` and `waiting()` also return `assignee`, as
{name, email} or None, so the factory classifier never touches work assigned to the owner), on the client written
without it (158 checks, 7 failed):
  FAIL: issues: the shape: got ['description', 'identifier', 'labels', 'project', 'state', 'title', 'updatedAt'], want ['assignee', ...]
  FAIL: assignee: {name, email} when assigned: got 'MISSING', want {'name': 'Toy Owner', 'email': 'owner@example.test'}
  FAIL: assignee: None when unassigned: got 'MISSING', want None
  FAIL: assignee: the query asks for the name and the email: got False, want True
  FAIL: issue: assignee: got 'MISSING', want {'name': 'Toy Owner', 'email': 'owner@example.test'}
  FAIL: issue: unassigned is None: got 'MISSING', want None
  FAIL: waiting: the assignee, name only when there is no email: got 'MISSING', want {'name': 'Toy Reviewer', 'email': None}
Seen red for `url` (3.1 U1: the discuss lists what waits for the owner with each issue's link; the fake server already
served `url`), on the client before `ISSUE_FIELDS` and `_shape` carried it (161 checks, 4 failed):
  FAIL: issues: the shape: got ['assignee', ..., 'updatedAt'], want [..., 'updatedAt', 'url']
  FAIL: issues: the url of each issue: got [('TOY-1', 'MISSING'), ('TOY-2', 'MISSING')], want [('TOY-1', 'https://linear.example.test/TOY-1'), ...]
  FAIL: issue: url: got 'MISSING', want 'https://linear.example.test/TOY-1'
  FAIL: waiting: the url the owner opens: got 'MISSING', want 'https://linear.example.test/TOY-3'
Controls seen red, each on a copy of linear.py (or of a data file) changed in one place, the first FAIL (or the
exception, when the bad version cannot even finish the case) shown; 158 checks each:
  retry and transport
  - ATTEMPTS 1: LinearError: cannot reach Linear after 1 attempts: Remote end closed connection without response
  - ATTEMPTS 4: FAIL: three cuts raises a LinearError: it returned
  - a 500 not retried: LinearError: Linear answered 500;  a 429 not retried: LinearError: Linear answered 429
  - a Linear error answer retried: FAIL: a Linear error answer raises a LinearError: it returned
  - no `not_found` code: FAIL: a deleted entity: code: got None, want 'not_found'
  - no backoff: FAIL: the backoff is short and positive: sleeps [0, 0]
  - no timeout: FAIL: a server that never answers raises a LinearError: it returned
  - a redirect followed: FAIL: a redirect raises a LinearError: it returned
  - any endpoint accepted: FAIL: endpoint https://example.org/graphql raises a LinearError: it returned
  - `Bearer ` before the key: FAIL: the key goes as the bare authorization header: got 'Bearer key-123', want 'key-123'
  comments
  - a conflict edits the existing comment: KeyError: 'id' (the second request was an update, not a create)
  - a conflict is an error: LinearError: conflict on insert
  - a random comment id: FAIL: comment: the id is (issue, kind, hash of the body): got '53fcc774-...', want '0df50390-...'
  - no mark: IndexError: list index out of range (the body has no first line to read)
  - kind not checked: FAIL: comment kind '' raises a LinearError: it returned
  - identifier not checked: FAIL: a malformed identifier: the message names 'identifier': message: Could not find referenced Issue.
  safety rules (PM I13)
  - no project comparison: FAIL: a comment on another project's issue raises a LinearError: it returned
  - `label` removes `factory`: FAIL: label -factory (the owner's label) raises a LinearError: it returned
  - `review` made removable in labels.tsv: FAIL: label -review (the owner's label) raises a LinearError: it returned
  - a foreign label added: FAIL: label +Bug (not on the list) raises a LinearError: it returned
  - an empty Context accepted: FAIL: create with empty context raises a LinearError: it returned
  - `create` without the factory label: FAIL: create: one mutation, with the factory label: got [[]], want [['lab-factory']]
  - the items of a list checked one at a time, after the first is created: FAIL: create: the labels of each: got [['lab-factory'], []], ...
  - braces in the text substituted a second time: FAIL: create: braces in the text are text, not placeholders
  - a conflict on create an error: LinearError: conflict on insert (created before this: none)
  - a missing label not noticed: IndexError: list index out of range
  reading (B5)
  - the state not asked for: LinearError: Linear's answer has no state.name
  - every comment `own`: FAIL: issue: who wrote each comment and which are ours: got [('Toy Person', True), ('Toy Bot', True), ...
  - no comment `own`: FAIL: ... got [('Toy Person', False), ('Toy Bot', False), ...
  - `own` when the mark is anywhere in the body (a person quoting it): FAIL: ... got [..., ('Toy Person', True)], want [..., ('Toy Person', False)]
  - `issues()` with the comments of each issue: KeyError: 'labels' (1+N requests)
  - labels not translated on read: FAIL: issues: a Linear label comes out under its neutral name: got ['factory', 'toy-needs-help'], want ['factory', 'needs-owner']
  - labels not translated on write: FAIL: label: the mutation adds the translated label ...: got [{'addedLabelIds': ['lab-needs-owner'], ...
  - the filter of issues() and waiting() not translated: KeyError: 'TOY-3'
  - `waiting()` with only needs-owner: KeyError: 'TOY-5'
  - a silent first page of comments: FAIL: issue: more comment pages is said, not silent: warnings []
  - a silent first page of issues: FAIL: issues: more pages is said, not silent: warnings []
  - project() asked every time: FAIL: project() is asked once per client: got 3, want 2
  - assignee: not in the shape (6 failed), email dropped (FAIL: assignee: {name, email} when assigned: got {'name': 'Toy Owner', 'email': None}), not asked for (LinearError: Linear's answer has no assignee)
  data
  - the template without `{{origin}}`: FAIL: the template: its placeholders are the issue's fields: got [... no 'origin']
"""
import contextlib
import hashlib
import http.server
import io
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import linear  # noqa: E402

s = helpers.Suite()
MAP = {"linear": {"labels": {"needs-owner": "toy-needs-help"}}}  # the toy mapping: neutral name -> the name in Linear
OWNER = {"name": "Toy Owner", "email": "owner@example.test"}


def iso(ago):
    """A timestamp `ago` seconds before now: fixtures carry no literal dates."""
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago))


class Fake:
    """An in-memory Linear on 127.0.0.1. It answers by the operation named in the query and by the variables, and
    includes an issue's field only when the query text names it, so a client that stops asking for one sees it missing.
    `outages` is consumed one per HTTP request: reset-before (drop the connection, nothing applied), reset-after (apply,
    then drop), hang (answer only after the client's timeout), redirect (302 to another server), an int (that HTTP status), or ok."""

    def __init__(self):
        self.requests, self.outages, self.force = [], [], []
        self.hang_s = 0.6
        self.redirect_to = None
        self.page_size = 100
        self.comment_page = 100
        self.n = 0
        self.projects = {"toy-project": {"id": "p1", "teams": [{"id": "t1", "key": "TOY"}]},
                         "other-project": {"id": "p2", "teams": [{"id": "t2", "key": "OTH"}]}}
        names = ["factory", "review", "factory-review", "factory-failed", "toy-needs-help", "needs-owner",
                 "mini-plan", "full-plan", "Bug"]
        self.labels = [{"id": "lab-" + n, "name": n, "team": None} for n in names]
        self.issues, self.comment_ids, self.created = {}, set(), {}
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["content-length"])))
                req["auth"] = self.headers.get("authorization")
                fake.requests.append(req)
                outage = fake.outages.pop(0) if fake.outages else "ok"
                if outage == "reset-before":
                    return
                if outage == "hang":  # then it answers properly: only a timeout makes the client give up
                    time.sleep(fake.hang_s)
                if outage == "redirect":  # 302: urllib follows it for a POST, carrying the headers
                    self.send_response(302)
                    self.send_header("Location", fake.redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                answer = fake.force.pop(0) if fake.force else fake.answer(req["query"], req["variables"])
                if outage == "reset-after":
                    return
                if isinstance(outage, int):
                    body, status, ctype = b"<html>busy</html>", outage, "text/html"
                else:
                    body, status, ctype = json.dumps(answer).encode(), 200, "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.server.handle_error = lambda *a: None  # a client that timed out leaves a broken pipe: not a finding
        self.url = "http://127.0.0.1:%d/graphql" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add_issue(self, ident, project="toy-project", labels=(), state=("Todo", "unstarted"), ago=90,
                  assignee=None, description="what is wrong", comments=()):
        self.issues[ident] = {"id": "uuid-" + ident, "identifier": ident, "title": "title of " + ident,
                              "description": description, "updatedAt": iso(ago),
                              "state": {"name": state[0], "type": state[1]}, "labels": list(labels),
                              "project": project, "assignee": assignee, "comments": list(comments)}
        return self.issues[ident]

    def find_issue(self, key):
        return next((i for i in self.issues.values() if key in (i["id"], i["identifier"])), None)

    def node(self, issue, query):
        out = {"id": issue["id"], "identifier": issue["identifier"]}
        for k in ("title", "description", "updatedAt", "state", "assignee"):
            if k in query:
                out[k] = issue[k]
        if "labels" in query:
            out["labels"] = {"nodes": [{"name": n} for n in issue["labels"]]}
        if "project" in query:
            out["project"] = {"name": issue["project"]} if issue["project"] else None
        if "url" in query:
            out["url"] = "https://linear.example.test/" + issue["identifier"]
        if "comments" in query:
            cs = issue["comments"]
            out["comments"] = {"nodes": cs[:self.comment_page],
                               "pageInfo": {"hasNextPage": len(cs) > self.comment_page}}
        return out

    def answer(self, query, v):
        if "commentCreate" in query:
            i = v["input"]
            if i["id"] in self.comment_ids:
                return {"errors": [{"message": "conflict on insert", "extensions": {}}]}
            self.comment_ids.add(i["id"])
            self.find_issue(i["issueId"])["comments"].append(
                {"id": i["id"], "body": i["body"], "createdAt": iso(10), "user": {"name": "Toy Bot"}})
            return {"data": {"commentCreate": {"success": True}}}
        if "issueCreate" in query:
            i = v["input"]
            if i["id"] in self.created:
                return {"errors": [{"message": "conflict on insert", "extensions": {}}]}
            self.n += 1
            ident = "TOY-%d" % (100 + self.n)
            issue = self.add_issue(ident)
            issue.update(id=i["id"], title=i["title"], description=i["description"])
            self.created[i["id"]] = ident
            return {"data": {"issueCreate": {"issue": {"id": i["id"], "identifier": ident,
                                                       "url": "https://linear.example.test/" + ident}}}}
        if "issueUpdate" in query:
            issue, i = self.find_issue(v["id"]), v["input"]
            by_id = {l["id"]: l["name"] for l in self.labels}
            for lid in i.get("addedLabelIds", []):
                issue["labels"].append(by_id[lid])
            for lid in i.get("removedLabelIds", []):
                issue["labels"] = [n for n in issue["labels"] if n != by_id[lid]]
            return {"data": {"issueUpdate": {"success": True}}}
        if "issueLabels(" in query:
            nodes = [l for l in self.labels if l["name"].lower() == v["name"].lower()]
            return {"data": {"issueLabels": {"nodes": [
                {"id": l["id"], "name": l["name"], "team": l["team"]} for l in nodes]}}}
        if "projects(" in query:
            p = self.projects.get(v["name"])
            nodes = [{"id": p["id"], "name": v["name"], "teams": {"nodes": p["teams"]}}] if p else []
            return {"data": {"projects": {"nodes": nodes}}}
        if "issues(" in query:
            hits = [i for i in self.issues.values()
                    if i["project"] == v["project"] and set(i["labels"]) & set(v["labels"])]
            return {"data": {"issues": {"nodes": [self.node(i, query) for i in hits[:self.page_size]],
                                        "pageInfo": {"hasNextPage": len(hits) > self.page_size}}}}
        if "issue(" in query:
            issue = self.find_issue(v["id"])
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


def client(fake, cfg=None, project="toy-project", **kw):
    """(Client, sleeps, warnings): a client on the fake, whose backoff sleeps are recorded, not slept."""
    sleeps, warnings = [], []
    kw.setdefault("sleep", sleeps.append)
    kw.setdefault("warn", warnings.append)
    return linear.Client("key-123", project, cfg, endpoint=fake.url, **kw), sleeps, warnings


def fails(label, fn, code=None, needle=None):
    """The LinearError fn raises (or None, recording a failure); code and needle are checked when given."""
    try:
        fn()
    except linear.LinearError as e:
        if code is not None:
            s.eq("%s: code" % label, e.code, code)
        if needle is not None:
            s.ok("%s: the message names %r" % (label, needle), needle in str(e), "message: %s" % e)
        return e
    s.ok("%s raises a LinearError" % label, False, "it returned")
    return None


def mut_kinds(fake):
    return [re.search(r"\b(comment\w+|issue\w+)\(", r["query"]).group(1) for r in fake.mutations()]


# --- comment_id
a = linear.comment_id("TOY-1", "claim", "abc")
s.ok("comment_id is a UUID v4", re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", a),
     "got %r" % a)
s.eq("comment_id is a function of its parts", a, linear.comment_id("TOY-1", "claim", "abc"))
s.ok("another part, another id", a != linear.comment_id("TOY-1", "claim", "abd"))
s.ok("the order of the parts counts", linear.comment_id("a", "b") != linear.comment_id("b", "a"))

# --- the transport: retries, timeout, key, redirect, endpoint
f = Fake()
c, sleeps, _ = client(f)
f.outages = ["reset-before", "reset-before"]
got = c.project()
s.eq("two cuts then success: the answer", got, {"id": "p1", "name": "toy-project", "team": {"id": "t1", "key": "TOY"}})
s.eq("two cuts then success: 3 requests", len(f.requests), 3)
s.eq("two cuts then success: it backed off twice", len(sleeps), 2)
s.ok("the backoff is short and positive", all(0 < x < 2 for x in sleeps), "sleeps %r" % sleeps)

f.requests.clear()
c, sleeps, _ = client(f)
f.outages = ["reset-before"] * 3
fails("three cuts", c.project, code="network")
s.eq("three cuts: 3 attempts, no more", len(f.requests), 3)

for status in (500, 429):
    f.requests.clear()
    c, _, _ = client(f)
    f.outages = [status]
    c.project()
    s.eq("%d is retried: 2 requests" % status, len(f.requests), 2)

f.requests.clear()
c, _, _ = client(f)
f.outages = [500, 500, 500]
fails("persistent 500", c.project, needle="answered 500")
s.eq("persistent 500: 3 attempts", len(f.requests), 3)

f.requests.clear()
c, _, _ = client(f)
f.force = [{"errors": [{"message": "Argument Validation Error"}]}]
fails("a Linear error answer", c.project, needle="Argument Validation Error")
s.eq("a Linear error answer is not retried", len(f.requests), 1)

c, _, _ = client(f)
f.force = [{"errors": [{"message": "Entity not found: Issue",
                        "extensions": {"userPresentableMessage": "Could not find referenced Issue."}}]}]
fails("a deleted entity", c.project, code="not_found")

f.requests.clear()
c, _, _ = client(f)
c.project()
s.eq("the key goes as the bare authorization header", f.requests[0]["auth"], "key-123")
e = fails("an unknown project", lambda: client(f, project="nope-project")[0].project(), code="not_found",
          needle="nope-project")
s.ok("no error message carries the key", e is not None and "key-123" not in str(e))
n = len(f.requests)
c.project()
s.eq("project() is asked once per client", len(f.requests), n)

s.eq("the timeout is 15 s", (linear.TIMEOUT, client(f)[0].timeout), (15, 15))
f.requests.clear()
c, _, _ = client(f, timeout=0.1)
f.outages = ["hang"] * 3
fails("a server that never answers", c.project, code="network")
s.eq("a server that never answers: 3 attempts", len(f.requests), 3)

other = Fake()
f.requests.clear()
c, _, _ = client(f)
f.outages, f.redirect_to = ["redirect"], other.url
fails("a redirect", c.project)
s.eq("a redirect never carries the key to the other server", other.requests, [])
other.close()

for bad in ("https://example.org/graphql", "http://127.0.0.1.example.org/graphql", "http://localhost:1/x",
            "http://192.0.2.1/x"):
    fails("endpoint %s" % bad, lambda: linear.Client("key-123", "toy-project", None, endpoint=bad),
          code="forbidden", needle="loopback")
s.ok("the real endpoint is accepted", linear.Client("key-123", "toy-project", None).endpoint == linear.ENDPOINT)
f.close()

# --- comment
f = Fake()
f.add_issue("TOY-1")
f.add_issue("OTH-1", project="other-project")
c, _, _ = client(f)
r = c.comment("TOY-1", "claim", "Picked up")
posted = f.issues["TOY-1"]["comments"]
s.eq("comment: one comment", len(posted), 1)
s.eq("comment: the mark is the first line", posted[0]["body"].split("\n")[0], "<!-- fwx:claim -->")
s.eq("comment: then the body", posted[0]["body"].split("\n", 1)[1], "Picked up")
want_id = linear.comment_id("TOY-1", "claim", hashlib.sha256(b"Picked up").hexdigest())
s.eq("comment: the id is (issue, kind, hash of the body)", posted[0]["id"], want_id)
s.eq("comment: reports it was created", r, {"id": want_id, "created": True})
f.requests.clear()
r = c.comment("TOY-1", "claim", "Picked up")
s.eq("comment again: reports 'already there'", r, {"id": want_id, "created": False})
s.eq("comment again: still one comment", len(f.issues["TOY-1"]["comments"]), 1)
s.eq("comment again: a conflict is not an edit, only commentCreate was sent", mut_kinds(f), ["commentCreate"])
c.comment("TOY-1", "claim", "Picked up again")
s.eq("another text, another comment", len(f.issues["TOY-1"]["comments"]), 2)

f2 = Fake()
f2.add_issue("TOY-1")
c2, _, _ = client(f2)
f2.outages = ["ok", "reset-after"]  # the guard read, then the write that Linear applies and the reset hides
r = c2.comment("TOY-1", "claim", "Picked up")
s.eq("reset after the write: one comment", len(f2.issues["TOY-1"]["comments"]), 1)
ids = {q["variables"]["input"]["id"] for q in f2.mutations()}
s.eq("reset after the write: two attempts, one comment id", (len(f2.mutations()), len(ids)), (2, 1))
s.eq("reset after the write: 'already there'", r["created"], False)
f2.close()

f.requests.clear()
fails("a comment on another project's issue", lambda: c.comment("OTH-1", "claim", "x"), code="forbidden",
      needle="other-project")
s.eq("another project's issue: nothing written", f.mutations(), [])
fails("a comment on a missing issue", lambda: c.comment("TOY-99", "claim", "x"), code="not_found")
for bad_kind in ("", "Claim", "a b", "a-->"):
    n = len(f.requests)
    fails("comment kind %r" % bad_kind, lambda: c.comment("TOY-1", bad_kind, "x"), needle="kind")
    s.eq("comment kind %r: no request" % bad_kind, len(f.requests), n)
fails("an empty comment", lambda: c.comment("TOY-1", "claim", "  "), needle="body")
fails("a malformed identifier", lambda: c.comment("not an id", "claim", "x"), needle="identifier")
f.close()

# --- label
f = Fake()
f.add_issue("TOY-1", labels=["factory", "factory-review", "Bug"])
f.add_issue("OTH-1", project="other-project", labels=["factory-failed"])
c, _, _ = client(f, MAP)
c.label("TOY-1", ["needs-owner"], ["factory-review"])
s.eq("label: the mutation adds the translated label and removes the other",
     [(q["variables"]["input"]) for q in f.mutations()],
     [{"addedLabelIds": ["lab-toy-needs-help"], "removedLabelIds": ["lab-factory-review"]}])
s.ok("label: the lookup asked for the translated name (expected toy-needs-help)",
     any(r["variables"].get("name") == "toy-needs-help" for r in f.requests))
s.eq("label: the issue now", sorted(f.issues["TOY-1"]["labels"]), ["Bug", "factory", "toy-needs-help"])
f.requests.clear()
c0, _, _ = client(f)  # no mapping: the neutral name is the Linear name
c0.label("TOY-1", ["needs-owner"], [])
s.ok("label without a mapping: needs-owner is asked for as it is",
     any(r["variables"].get("name") == "needs-owner" for r in f.requests))
f.requests.clear()
c.label("TOY-1", ["factory"], [])
s.eq("label: +factory is allowed", [q["variables"]["input"]["addedLabelIds"] for q in f.mutations()], [["lab-factory"]])

for add, rem, why, code in (([], ["factory"], "-factory (the owner's label)", "forbidden"),
                            ([], ["review"], "-review (the owner's label)", "forbidden"),
                            ([], ["Bug"], "-Bug (not ours)", "forbidden"),
                            (["Bug"], [], "+Bug (not on the list)", "forbidden"),
                            (["toy-needs-help"], [], "+toy-needs-help (the Linear name, not the neutral one)", "forbidden"),
                            (["needs-owner"], ["needs-owner"], "the same label added and removed", "usage")):
    f.requests.clear()
    fails("label " + why, lambda: c.label("TOY-1", add, rem), code=code)
    s.eq("label %s: no mutation" % why, f.mutations(), [])
f.requests.clear()
fails("label on another project's issue", lambda: c.label("OTH-1", ["needs-owner"], []), code="forbidden",
      needle="other-project")
s.eq("another project's issue: no mutation", f.mutations(), [])
f.labels = [l for l in f.labels if l["name"] != "mini-plan"]
f.requests.clear()
e = fails("a label Linear lacks", lambda: c.label("TOY-1", ["mini-plan"], []), code="missing_label",
          needle="mini-plan")
s.ok("a missing label names the list", e is not None and "labels.tsv" in str(e))
s.eq("a missing label: no mutation, no label created", f.mutations(), [])
f.close()

# --- create
f = Fake()
c, _, _ = client(f)
issue = {"title": "Login fails", "context": "The form returns 500 on submit.", "expected": "It signs the user in.",
         "reproduce": "Submit the form.", "origin": "agent in session s-1", "labels": ["factory"]}
out = c.create("general", issue)
sent = [q["variables"]["input"] for q in f.mutations()]
s.eq("create: one mutation, with the factory label", [m["labelIds"] for m in sent], [["lab-factory"]])
s.eq("create: the project and its team", [(m["projectId"], m["teamId"]) for m in sent], [("p1", "t1")])
s.eq("create: the id is (project, title, hash of the body)", sent[0]["id"],
     linear.comment_id("toy-project", "Login fails", hashlib.sha256(sent[0]["description"].encode()).hexdigest()))
body = sent[0]["description"]
heads = re.findall(r"^## (.*)$", body, re.M)
s.eq("create: the sections of the template, in order", heads,
     ["Context", "How to reproduce or where to look", "Expected", "Out of scope", "Evidence and links", "Origin"])
s.ok("create: the text lands under its section", "## Context\n\nThe form returns 500 on submit." in body)
s.ok("create: no placeholder is left", "{{" not in body)
s.eq("create: returns the created issue", [(o["identifier"], o["created"]) for o in out], [("TOY-101", True)])

f.requests.clear()
out = c.create("general", [dict(issue, title="First"), dict(issue, title="Second", labels=["needs-owner", "review"])])
s.eq("create: several in one call", [o["identifier"] for o in out], ["TOY-102", "TOY-103"])
s.eq("create: the labels of each", [m["variables"]["input"]["labelIds"] for m in f.mutations()],
     [["lab-factory"], ["lab-needs-owner", "lab-review"]])
r = c.create("general", dict(issue, title="No label", labels=[]))
s.eq("create: no label is allowed", f.mutations()[-1]["variables"]["input"]["labelIds"], [])

f.requests.clear()
again = c.create("general", issue)
s.eq("create again: the same issue back, 'already there'", [(o["identifier"], o["created"]) for o in again],
     [("TOY-101", False)])
s.eq("create again: no second issue", len([i for i in f.issues if i.startswith("TOY-1")]), 4)

f3 = Fake()
c3, _, _ = client(f3)
f3.outages = ["ok", "reset-after"]  # project(), then the create that Linear applies and the reset hides
out = c3.create("general", issue)
s.eq("create, reset after the write: one issue, the same back", ([o["identifier"] for o in out], f3.n), (["TOY-101"], 1))
s.eq("create, reset after the write: two attempts with one id",
     len({q["variables"]["input"]["id"] for q in f3.mutations() if "issueCreate" in q["query"]}), 1)
f3.close()

f.requests.clear()
for k, bad_issue in (("empty context", dict(issue, context="")), ("blank context", dict(issue, context=" \n ")),
                     ("no context", {k: v for k, v in issue.items() if k != "context"}),
                     ("empty expected", dict(issue, expected="")), ("no title", dict(issue, title=" "))):
    fails("create with " + k, lambda: c.create("general", bad_issue), needle=k.split()[-1])
s.eq("create with a missing section: nothing sent", f.mutations(), [])
fails("create: a label that is not ours", lambda: c.create("general", dict(issue, labels=["Bug"])), code="forbidden")
fails("create: an unknown field", lambda: c.create("general", dict(issue, contxt="x")), needle="contxt")
fails("create: an unknown template", lambda: c.create("nosuch", issue), code="no_template")
fails("create: a template name that climbs out", lambda: c.create("../labels", issue), code="no_template")
fails("create: nothing to create", lambda: c.create("general", []), needle="no issues")
s.eq("create: still nothing sent", f.mutations(), [])
before = len(f.issues)
fails("create: the second of two is bad", lambda: c.create("general", [dict(issue, title="Third"),
                                                                       dict(issue, title="Bad", context="")]))
s.eq("create: a bad item in a list creates none of them", len(f.issues), before)
tricky = c.create("general", dict(issue, title="Tricky", context="see {{expected}} and {{nosuch}}"))
s.ok("create: braces in the text are text, not placeholders",
     "see {{expected}} and {{nosuch}}" in f.find_issue(tricky[0]["identifier"])["description"])
f.labels = [l for l in f.labels if l["name"] != "factory"]
f.requests.clear()
c, _, _ = client(f)  # a new client: the old one remembers the label's id
fails("create: the factory label Linear lacks", lambda: c.create("general", dict(issue, title="Z")),
      code="missing_label", needle="factory")
s.eq("create: a missing label stops before any mutation", f.mutations(), [])
f.close()

# --- reads
f = Fake()
f.add_issue("TOY-1", labels=["factory"], state=("Done", "completed"), assignee=OWNER, ago=90,
            comments=[{"id": "c1", "body": "a person wrote this", "createdAt": iso(50), "user": {"name": "Toy Person"}},
                      {"id": "c2", "body": "<!-- fwx:claim -->\nPicked up", "createdAt": iso(40),
                       "user": {"name": "Toy Bot"}},
                      {"id": "c3", "body": "no author", "createdAt": iso(30), "user": None},
                      {"id": "c4", "body": "> <!-- fwx:claim -->\n> quoted by a person", "createdAt": iso(20),
                       "user": {"name": "Toy Person"}}])
f.add_issue("TOY-2", labels=["factory", "toy-needs-help"], ago=3600)
f.add_issue("TOY-3", labels=["toy-needs-help"], state=("In Progress", "started"), ago=7200)
f.add_issue("TOY-4", labels=["factory-failed"], ago=100)
f.add_issue("TOY-5", labels=["factory-review"], ago=200, assignee={"name": "Toy Reviewer", "email": None})
f.add_issue("TOY-6", labels=["Bug"], ago=300)
f.add_issue("OTH-1", project="other-project", labels=["factory"], ago=60)
c, _, warns = client(f, MAP)
f.requests.clear()
rows = c.issues("factory")
s.eq("issues: one request for the list (no request per issue)", len(f.requests), 1)
s.eq("issues: the project and the label filter", (f.requests[0]["variables"]["project"],
                                                  f.requests[0]["variables"]["labels"]), ("toy-project", ["factory"]))
s.eq("issues: the issues of this project with that label", sorted(r["identifier"] for r in rows), ["TOY-1", "TOY-2"])
one = {r["identifier"]: r for r in rows}["TOY-1"]
s.eq("issues: a completed issue keeps its state type (the claimer excludes it)", one["state"],
     {"name": "Done", "type": "completed"})
s.eq("issues: the shape", sorted(one), ["assignee", "description", "identifier", "labels", "project", "state",
                                         "title", "updatedAt", "url"])
s.eq("issues: the url of each issue", sorted((r["identifier"], r.get("url", "MISSING")) for r in rows),
     [("TOY-1", "https://linear.example.test/TOY-1"), ("TOY-2", "https://linear.example.test/TOY-2")])
s.eq("issues: no comments", [("comments" in r) for r in rows], [False, False])
s.eq("issues: the values", (one["description"], one["project"], one["labels"], one["updatedAt"] == f.issues["TOY-1"]["updatedAt"]),
     ("what is wrong", "toy-project", ["factory"], True))
two = {r["identifier"]: r for r in rows}["TOY-2"]
s.eq("issues: a Linear label comes out under its neutral name", two["labels"], ["factory", "needs-owner"])
rows = c.issues("needs-owner")
s.eq("issues: the filter is the Linear name", f.requests[-1]["variables"]["labels"], ["toy-needs-help"])
s.eq("issues: found by the translated name", sorted(r["identifier"] for r in rows), ["TOY-2", "TOY-3"])
s.eq("issues: nothing silent when the list is whole", warns, [])

# the owner's own work: the classifier never touches an issue assigned to the owner
rows = {r["identifier"]: r for r in c.issues("factory")}
s.eq("assignee: {name, email} when assigned", rows["TOY-1"].get("assignee", "MISSING"), OWNER)
s.eq("assignee: None when unassigned", rows["TOY-2"].get("assignee", "MISSING"), None)
s.eq("assignee: the query asks for the name and the email", all(
    "assignee" in r["query"] and "email" in r["query"] for r in f.requests if "issues(" in r["query"]), True)

f.page_size = 1
f.requests.clear()
rows = c.issues("factory")
s.eq("issues: a first page only", len(rows), 1)
s.ok("issues: more pages is said, not silent", len(warns) == 1 and "more" in warns[0] and "factory" in warns[0],
     "warnings %r" % warns)
f.page_size = 100

# one issue, with its comments
del warns[:]
iss = c.issue("TOY-1")
s.eq("issue: description and state", (iss["description"], iss["state"]), ("what is wrong", {"name": "Done", "type": "completed"}))
s.eq("issue: assignee", iss.get("assignee", "MISSING"), OWNER)
s.eq("issue: url", iss.get("url", "MISSING"), "https://linear.example.test/TOY-1")
s.eq("issue: project, labels", (iss["project"], iss["labels"]), ("toy-project", ["factory"]))
s.eq("issue: who wrote each comment and which are ours", [(x["author"], x["own"]) for x in iss["comments"]],
     [("Toy Person", False), ("Toy Bot", True), (None, False), ("Toy Person", False)])
s.eq("issue: a comment's body and time", (iss["comments"][1]["body"], iss["comments"][1]["created_at"]),
     ("<!-- fwx:claim -->\nPicked up", f.issues["TOY-1"]["comments"][1]["createdAt"]))
s.eq("issue: unassigned is None", c.issue("TOY-2").get("assignee", "MISSING"), None)
s.eq("issue: a Linear label under its neutral name", c.issue("TOY-2")["labels"], ["factory", "needs-owner"])
s.eq("issue: all the comments, so no warning", warns, [])
f.comment_page = 2
iss = c.issue("TOY-1")
s.eq("issue: a first page of comments only", len(iss["comments"]), 2)
s.ok("issue: more comment pages is said, not silent", len(warns) == 1 and "TOY-1" in warns[0] and "comments" in warns[0],
     "warnings %r" % warns)
f.comment_page = 100
fails("issue of another project", lambda: c.issue("OTH-1"), code="forbidden", needle="other-project")
fails("issue that does not exist", lambda: c.issue("TOY-99"), code="not_found")

# waiting
del warns[:]
f.requests.clear()
rows = c.waiting()
s.eq("waiting: one request, the three labels by their Linear names", (len(f.requests),
     f.requests[0]["variables"]["labels"]), (1, ["toy-needs-help", "factory-review", "factory-failed"]))
s.eq("waiting: the issues that wait", sorted(r["identifier"] for r in rows), ["TOY-2", "TOY-3", "TOY-4", "TOY-5"])
byid = {r["identifier"]: r for r in rows}
s.eq("waiting: labels under neutral names", byid["TOY-3"]["labels"], ["needs-owner"])
s.eq("waiting: updatedAt to group by age", byid["TOY-3"]["updatedAt"], f.issues["TOY-3"]["updatedAt"])
s.eq("waiting: the url the owner opens", byid["TOY-3"].get("url", "MISSING"), "https://linear.example.test/TOY-3")
s.eq("waiting: the assignee, name only when there is no email", byid["TOY-5"].get("assignee", "MISSING"),
     {"name": "Toy Reviewer", "email": None})
s.eq("waiting: not one with only factory or Bug", [i for i in ("TOY-1", "TOY-6") if i in byid], [])
c0, _, _ = client(f)
f.requests.clear()
c0.waiting()
s.eq("waiting without a mapping: needs-owner as it is", f.requests[0]["variables"]["labels"],
     ["needs-owner", "factory-review", "factory-failed"])
f.page_size = 1
c.waiting()
s.ok("waiting: more pages is said, not silent", len(warns) == 1 and "waiting" in warns[0], "warnings %r" % warns)
f.close()

# the default warning goes to stderr
f = Fake()
f.add_issue("TOY-1", labels=["factory"])
f.add_issue("TOY-2", labels=["factory"])
f.page_size = 1
err = io.StringIO()
with contextlib.redirect_stderr(err):
    linear.Client("key-123", "toy-project", None, endpoint=f.url).issues("factory")
s.ok("the default warning is a line on stderr", err.getvalue().startswith("fwx: warning: ") and
     err.getvalue().endswith("\n"), "stderr %r" % err.getvalue())
f.close()

# --- data/linear
table = linear.label_table()
s.eq("labels.tsv: the seven labels", sorted(table),
     ["factory", "factory-failed", "factory-review", "full-plan", "mini-plan", "needs-owner", "review"])
s.eq("labels.tsv: the client may remove these", sorted(n for n, r in table.items() if r["removable"]),
     ["factory-failed", "factory-review", "full-plan", "mini-plan", "needs-owner"])
s.ok("labels.tsv: every row says who sets it and what it means",
     all(r["set_by"] and r["meaning"] for r in table.values()))
with open(os.path.join(helpers.ROOT, "data", "linear", "templates", "general.md"), encoding="utf-8") as fh:
    tpl = fh.read()
s.eq("the template: its placeholders are the issue's fields", sorted(set(re.findall(r"\{\{(\w+)\}\}", tpl))),
     sorted(["context", "reproduce", "expected", "out_of_scope", "evidence", "origin"]))

helpers.cleanup(bool(s.fails))
s.done()
