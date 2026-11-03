"""The Linear client: the factory's and the sessions' only way to read and write issues.

copied-from: marshal-factory lib/linear.ts @999ad20, adapted (comment_id, the retry loop, the way a Linear error
answer becomes `conflict` or `not_found`, and "a replayed create converges"; the methods and the rules are fwx's own)

A Client is fixed to one Linear project and to the label names of one configuration. It sends one GraphQL POST
per call with the key as the bare `authorization` header, three attempts with backoff and jitter on a network
error, a 5xx or a 429, 15 s each. Every write converges when replayed (a reset can arrive after Linear applied it):
Linear stores a create under the id we pass, so the retry gets `conflict`, and `conflict` means "already there",
never an error and never an edit.

What it will do, and what it refuses (LinearError with a code):
  - touch only issues of its own project (`forbidden`), reading included; a project that has no issue is `not_found`;
  - add only the labels of data/linear/labels.tsv, `factory` included, and remove only those that table marks
    removable: never `factory`, `review` or a label that is not ours, because the owner or a rule of the owner sets those;
  - only create comments, never edit or delete one; create an issue only with a non-empty Context and Expected;
  - never create a label: a missing one is `missing_label`, naming it and the table;
  - send the key only to api.linear.app, or to 127.0.0.1 (a fake server in a test), and never follow a redirect.
Label names in and out are the neutral ones of this repository; `cfg` (config.load) maps them to the user's Linear
through config.label_to_linear and label_from_linear.

A list that does not fit the one page asked for is said on `warn` (stderr by default), never returned as if whole.
Imports only the standard library.
"""
import hashlib
import http.client
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from fwx import config

ENDPOINT = "https://api.linear.app/graphql"
TIMEOUT = 15
ATTEMPTS = 3
BACKOFF = 0.25  # seconds; doubled each attempt and multiplied by 0.5..1.5
PAGE = 100
MARK = "<!-- fwx:"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
DATA = os.path.join(ROOT, "data", "linear")
WAITING = ("needs-owner", "factory-review", "factory-failed")
FIELDS = ("context", "reproduce", "expected", "out_of_scope", "evidence", "origin")
REQUIRED = ("context", "expected")
IDENT = re.compile(r"[A-Za-z][A-Za-z0-9]*-[0-9]+\Z")
KIND = re.compile(r"[a-z][a-z0-9-]*\Z")
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")
# Linear words a deleted entity, or one the key can no longer see, only in the message.
NOT_FOUND = re.compile(r"(Could not find referenced|Entity not found)")

ISSUE_FIELDS = ("identifier title description updatedAt state { name type } labels { nodes { name } } "
                "project { name } assignee { name email }")
Q_PROJECT = ("query($name: String!) { projects(filter: { name: { eq: $name } }) "
             "{ nodes { id name teams { nodes { id key } } } } }")
Q_REF = "query($id: String!) { issue(id: $id) { id identifier project { name } } }"
Q_LIST = ("query($project: String!, $labels: [String!]) { issues(first: %d, filter: { "
          "project: { name: { eq: $project } }, labels: { some: { name: { in: $labels } } } }) { "
          "nodes { %s } pageInfo { hasNextPage } } }" % (PAGE, ISSUE_FIELDS))
Q_ISSUE = ("query($id: String!) { issue(id: $id) { %s comments(first: %d) { nodes { body createdAt user { name } } "
           "pageInfo { hasNextPage } } } }" % (ISSUE_FIELDS, PAGE))
Q_LABEL = ("query($name: String!) { issueLabels(first: 50, filter: { name: { eqIgnoreCase: $name } }) "
           "{ nodes { id name team { id } } } }")
Q_BY_ID = "query($id: String!) { issue(id: $id) { identifier url } }"
M_COMMENT = "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success } }"
M_UPDATE = "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success } }"
M_CREATE = "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { issue { id identifier url } } }"


class LinearError(Exception):
    """Linear refused, could not be reached, or the client refused to ask. `code`: conflict, not_found, network,
    forbidden, missing_label, no_template, usage, shape, unauthorized, or the code Linear sent (None when it sent none)."""

    def __init__(self, message, code=None):
        Exception.__init__(self, message)
        self.code = code


def comment_id(*parts):
    """A UUID v4 derived from a hash of `parts`: Linear stores a create under the id we pass, so a replay conflicts
    instead of duplicating."""
    hex_ = hashlib.sha256(("fwx\n" + "\n".join(parts)).encode("utf-8")).hexdigest()
    variant = "%x" % ((int(hex_[16], 16) & 0x3) | 0x8)
    return "%s-%s-4%s-%s%s-%s" % (hex_[:8], hex_[8:12], hex_[13:16], variant, hex_[17:20], hex_[20:32])


def label_table():
    """{name: {set_by, meaning, removable}} from data/linear/labels.tsv, the labels this client may add and, when
    `removable`, remove."""
    path = os.path.join(DATA, "labels.tsv")
    with open(path, encoding="utf-8") as f:
        rows = [l.rstrip("\n").split("\t") for l in f if l.strip()][1:]
    table = {}
    for r in rows:
        if len(r) != 4 or r[3] not in ("yes", "no"):
            raise LinearError("%s: bad row %r (want name, set_by, meaning, yes|no)" % (path, r), "usage")
        table[r[0]] = {"set_by": r[1], "meaning": r[2], "removable": r[3] == "yes"}
    if not table:
        raise LinearError("%s has no labels" % path, "usage")
    return table


def _template(name):
    if not isinstance(name, str) or not NAME.match(name):
        raise LinearError("template %r: a template is a name such as 'general'" % (name,), "no_template")
    path = os.path.join(DATA, "templates", name + ".md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        raise LinearError("no template %r (the templates are the files of data/linear/templates/)" % name, "no_template")
    found = set(re.findall(r"\{\{(\w+)\}\}", text))
    if not found <= set(FIELDS) or not set(REQUIRED) <= found:
        raise LinearError("template %r: its placeholders must be among %s and include %s"
                          % (name, ", ".join(FIELDS), ", ".join(REQUIRED)), "no_template")
    return text


def _dig(obj, *path):
    for p in path:
        if not isinstance(obj, dict) or p not in obj:
            raise LinearError("Linear's answer has no %s" % ".".join(path), "shape")
        obj = obj[p]
    return obj


def _check_ident(ident):
    if not isinstance(ident, str) or not IDENT.match(ident):
        raise LinearError("%r is not an issue identifier (such as ABC-12)" % (ident,), "usage")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # the key is not sent anywhere the endpoint check did not allow
        return None


def _stderr_warn(msg):
    sys.stderr.write("fwx: warning: %s\n" % msg)


class Client:
    """One Linear project, one configuration. `sleep` and `warn` are injectable for tests; `endpoint` other than
    Linear's must be on 127.0.0.1."""

    def __init__(self, api_key, project, cfg=None, endpoint=ENDPOINT, timeout=TIMEOUT, sleep=time.sleep, warn=None):
        if not api_key or not project:
            raise LinearError("a Linear client needs an API key and a project name", "usage")
        u = urllib.parse.urlparse(endpoint)
        loopback = u.scheme in ("http", "https") and u.hostname == "127.0.0.1"
        if endpoint != ENDPOINT and not loopback:
            raise LinearError("endpoint %s refused: the key goes only to %s or to a loopback address (127.0.0.1)"
                              % (endpoint, ENDPOINT), "forbidden")
        self.api_key, self.project_name, self.cfg = api_key, project, cfg or {}
        self.endpoint, self.timeout, self.sleep = endpoint, timeout, sleep
        self.warn = warn or _stderr_warn
        proxy = urllib.request.ProxyHandler({}) if loopback else urllib.request.ProxyHandler()
        self._opener = urllib.request.build_opener(proxy, _NoRedirect)
        self._project = None
        self._labels = {}

    # -- transport
    def _post(self, body):
        """(status, raw) after at most ATTEMPTS tries: a network error, a 5xx and a 429 are tried again."""
        for attempt in range(1, ATTEMPTS + 1):
            req = urllib.request.Request(self.endpoint, body, method="POST",
                                         headers={"authorization": self.api_key, "content-type": "application/json"})
            try:
                with self._opener.open(req, timeout=self.timeout) as r:
                    status, raw = r.status, r.read()
            except urllib.error.HTTPError as e:
                try:
                    status, raw = e.code, e.read()
                except (OSError, http.client.HTTPException):
                    status, raw = e.code, b""
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                if attempt == ATTEMPTS:
                    raise LinearError("cannot reach Linear after %d attempts: %s" % (ATTEMPTS, getattr(e, "reason", e)),
                                      "network")
                status = None
            if status is not None and (attempt == ATTEMPTS or (status < 500 and status != 429)):
                return status, raw
            self.sleep(BACKOFF * 2 ** (attempt - 1) * (0.5 + random.random()))

    def _gql(self, query, variables):
        status, raw = self._post(json.dumps({"query": query, "variables": variables}).encode("utf-8"))
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise LinearError("Linear answered %d" % status, "unauthorized" if status in (401, 403) else None)
        errors = payload.get("errors")
        if errors:
            first = errors[0] if isinstance(errors[0], dict) else {"message": str(errors[0])}
            ext = first.get("extensions") or {}
            msgs = [m for m in (first.get("message"), ext.get("userPresentableMessage")) if isinstance(m, str)]
            if (first.get("message") or "").startswith("conflict on insert"):
                code = "conflict"
            elif any(NOT_FOUND.match(m) for m in msgs):
                code = "not_found"
            else:
                code = ext.get("code")
            raise LinearError((ext.get("userPresentableMessage") or first.get("message") or "Linear error"), code)
        if status >= 400 or not isinstance(payload.get("data"), dict):
            raise LinearError("Linear answered %d without data" % status)
        return payload["data"]

    # -- the project, its issues, its labels
    def project(self):
        """{id, name, team: {id, key}} of this client's project; `not_found` when Linear has none by that name."""
        if self._project is None:
            nodes = _dig(self._gql(Q_PROJECT, {"name": self.project_name}), "projects", "nodes")
            if not nodes:
                raise LinearError("Linear has no project named %r" % self.project_name, "not_found")
            if len(nodes) > 1:
                raise LinearError("Linear has %d projects named %r" % (len(nodes), self.project_name), "usage")
            teams = _dig(nodes[0], "teams", "nodes")
            if not teams:
                raise LinearError("the Linear project %r belongs to no team" % self.project_name, "not_found")
            self._project = {"id": nodes[0]["id"], "name": nodes[0]["name"],
                             "team": {"id": teams[0]["id"], "key": teams[0]["key"]}}
        return self._project

    def _mine(self, node):
        name = (node.get("project") or {}).get("name")
        if name != self.project_name:
            raise LinearError("%s belongs to %s, and this client is fixed to the project %s"
                              % (node.get("identifier"), "the project %s" % name if name else "no project", self.project_name),
                              "forbidden")

    def _ref(self, ident):
        """{id, identifier} of an issue of this project; the other projects' issues are never touched."""
        _check_ident(ident)
        node = _dig(self._gql(Q_REF, {"id": ident}), "issue")
        if node is None:
            raise LinearError("no issue %s" % ident, "not_found")
        self._mine(node)
        return node

    def _label_id(self, name):
        if name not in self._labels:
            linear_name = config.label_to_linear(self.cfg, name)
            nodes = _dig(self._gql(Q_LABEL, {"name": linear_name}), "issueLabels", "nodes")
            team = self.project()["team"]["id"]
            mine = [n for n in nodes if (n.get("team") or {}).get("id") == team] or [n for n in nodes if not n.get("team")]
            if not mine:
                raise LinearError("Linear has no label %r%s in this team; create it there (this client never creates "
                                  "labels). The labels it may use are listed in data/linear/labels.tsv"
                                  % (linear_name, "" if linear_name == name else " (the neutral name %r)" % name),
                                  "missing_label")
            self._labels[name] = mine[0]["id"]
        return self._labels[name]

    # -- reading
    def _shape(self, node):
        return {"identifier": _dig(node, "identifier"), "title": _dig(node, "title"),
                "description": _dig(node, "description"),
                "state": {"name": _dig(node, "state", "name"), "type": _dig(node, "state", "type")},
                "labels": [config.label_from_linear(self.cfg, l["name"]) for l in _dig(node, "labels", "nodes")],
                "project": (node.get("project") or {}).get("name"), "updatedAt": _dig(node, "updatedAt"),
                "assignee": self._assignee(_dig(node, "assignee"))}

    @staticmethod
    def _assignee(node):
        """{name, email} of whoever the issue is assigned to, or None: the classifier never touches work that is
        assigned to the owner."""
        return None if node is None else {"name": node.get("name"), "email": node.get("email")}

    def _list(self, names, what):
        data = self._gql(Q_LIST, {"project": self.project_name,
                                  "labels": [config.label_to_linear(self.cfg, n) for n in names]})
        if (_dig(data, "issues", "pageInfo") or {}).get("hasNextPage"):
            self.warn("Linear has more than %d issues %s in %s; only the first %d are listed"
                      % (PAGE, what, self.project_name, PAGE))
        return [self._shape(n) for n in _dig(data, "issues", "nodes")]

    def issues(self, label):
        """The issues of this project that carry the neutral `label`, one request, without comments."""
        return self._list([label], "with the label %r" % label)

    def waiting(self):
        """The issues waiting for the owner (the labels of WAITING), with `updatedAt` to group them by age."""
        return self._list(WAITING, "waiting for the owner (%s)" % ", ".join(WAITING))

    def issue(self, ident):
        """One issue of this project with its comments; a comment is `own` when it starts with the fwx mark."""
        _check_ident(ident)
        node = _dig(self._gql(Q_ISSUE, {"id": ident}), "issue")
        if node is None:
            raise LinearError("no issue %s" % ident, "not_found")
        self._mine(node)
        out = self._shape(node)
        page = _dig(node, "comments")
        if (page.get("pageInfo") or {}).get("hasNextPage"):
            self.warn("%s has more than %d comments; only the first %d are listed" % (out["identifier"], PAGE, PAGE))
        out["comments"] = [{"author": (c.get("user") or {}).get("name"), "body": c["body"],
                            "created_at": c["createdAt"], "own": c["body"].lstrip().startswith(MARK)}
                           for c in _dig(page, "nodes")]
        return out

    # -- writing
    def comment(self, ident, kind, body):
        """Create the comment `<!-- fwx:KIND -->` + body on an issue of this project. `created` is False when Linear
        already had it (the same issue, kind and text): that is a conflict, not an error and not an edit."""
        if not isinstance(kind, str) or not KIND.match(kind):
            raise LinearError("comment kind %r: lower-case words joined by hyphens" % (kind,), "usage")
        if not isinstance(body, str) or not body.strip():
            raise LinearError("a comment needs a non-empty body", "usage")
        ref = self._ref(ident)
        cid = comment_id(ref["identifier"], kind, hashlib.sha256(body.encode("utf-8")).hexdigest())
        try:
            self._gql(M_COMMENT, {"input": {"id": cid, "issueId": ref["id"], "body": "%s%s -->\n%s" % (MARK, kind, body)}})
        except LinearError as e:
            if e.code != "conflict":
                raise
            return {"id": cid, "created": False}
        return {"id": cid, "created": True}

    def label(self, ident, add, remove):
        """Add and remove neutral labels on an issue of this project. Adds only the labels of the table (`factory`
        included), removes only those it marks removable; the rest is refused before any request."""
        table = label_table()
        for n in add:
            if n not in table:
                raise LinearError("label %r is not one of ours (data/linear/labels.tsv): not added" % n, "forbidden")
        for n in remove:
            if n not in table:
                raise LinearError("label %r is not one of ours (data/linear/labels.tsv): not removed" % n, "forbidden")
            if not table[n]["removable"]:
                raise LinearError("label %r is set by the owner or a rule of the owner; this client never removes it" % n,
                                  "forbidden")
        if set(add) & set(remove):
            raise LinearError("label(s) %s both added and removed" % sorted(set(add) & set(remove)), "usage")
        if not add and not remove:
            return {"added": [], "removed": []}
        ref = self._ref(ident)
        change = {}
        if add:
            change["addedLabelIds"] = [self._label_id(n) for n in add]
        if remove:
            change["removedLabelIds"] = [self._label_id(n) for n in remove]
        self._gql(M_UPDATE, {"id": ref["id"], "input": change})
        return {"added": list(add), "removed": list(remove)}

    def _render(self, tpl, item):
        if not isinstance(item, dict):
            raise LinearError("an issue is a table of title, labels and the sections %s" % ", ".join(FIELDS), "usage")
        extra = set(item) - set(FIELDS) - {"title", "labels"}
        if extra:
            raise LinearError("unknown issue field(s) %s (known: title, labels, %s)" % (sorted(extra), ", ".join(FIELDS)),
                              "usage")
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            raise LinearError("an issue needs a title", "usage")
        for key in FIELDS:
            if not isinstance(item.get(key, ""), str):
                raise LinearError("issue %r: %s is not text" % (title, key), "usage")
        for key in REQUIRED:
            if not item.get(key, "").strip():
                raise LinearError("issue %r needs a non-empty %s: every issue explains itself" % (title, key), "usage")
        labels = list(item.get("labels") or [])
        table = label_table()
        for n in labels:
            if n not in table:
                raise LinearError("label %r is not one of ours (data/linear/labels.tsv): not added" % n, "forbidden")
        body = re.sub(r"\{\{(\w+)\}\}", lambda m: item.get(m.group(1), "").strip() or "Not given.", tpl)
        return title.strip(), body, labels

    def create(self, template, issues):
        """Create one issue (a dict) or several (a list) from the template of that name, in this project. Everything
        is checked and every label looked up before the first is created. The id is (project, title, hash of the
        body), so a replay gets the issue the first create made (`created` False). One dict per issue:
        {identifier, url, created}."""
        tpl = _template(template)
        items = [issues] if isinstance(issues, dict) else list(issues)
        if not items:
            raise LinearError("no issues to create", "usage")
        rendered = [self._render(tpl, i) for i in items]
        info = self.project()
        ids = [[self._label_id(n) for n in labels] for _, _, labels in rendered]
        out = []
        for (title, body, _), label_ids in zip(rendered, ids):
            iid = comment_id(self.project_name, title, hashlib.sha256(body.encode("utf-8")).hexdigest())
            try:
                try:
                    node = _dig(self._gql(M_CREATE, {"input": {"id": iid, "teamId": info["team"]["id"],
                                                               "projectId": info["id"], "title": title,
                                                               "description": body, "labelIds": label_ids}}),
                                "issueCreate", "issue")
                    created = True
                except LinearError as e:
                    if e.code != "conflict":
                        raise
                    node, created = _dig(self._gql(Q_BY_ID, {"id": iid}), "issue"), False
            except LinearError as e:
                done = ", ".join(o["identifier"] for o in out) or "none"
                err = LinearError("%s (created before this: %s)" % (e, done), e.code)
                err.created = out
                raise err
            out.append({"identifier": node["identifier"], "url": node["url"], "created": created})
        return out
