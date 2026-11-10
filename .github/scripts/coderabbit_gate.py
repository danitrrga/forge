#!/usr/bin/env python3
"""The commit status `CodeRabbit approval` of a PR: CodeRabbit's approval is required only where a PR
is security-relevant, and everything else merges on green CI without it.

A PR is security-relevant when it changes a path in RISKY (kept equal to the stricter-limit paths of
.coderabbit.yaml by tests/test_coderabbit_gate.py) or carries the `security` label. Then the status is
`pending` until the latest approval-or-rejection review by CodeRabbit is an approval of the PR's current
head commit; otherwise `success`. A Dependabot PR is never reviewed by CodeRabbit, so there a human
with write access approving the head commit releases it. The ruleset requires this status by name.

Run by .github/workflows/coderabbit-gate.yml on pull_request and pull_request_review with GH_TOKEN,
REPO and PR in the environment. It posts to the PR's head commit through the statuses API, because a
check run made on a pull_request_review event lands on the merge commit and would never satisfy a
required check on the head. A failed API call exits 1 and posts nothing, so the required status is
missing and the PR stays blocked.
"""
import json
import os
import re
import subprocess
import sys

CONTEXT = "CodeRabbit approval"
BOT = "coderabbitai[bot]"
LABEL = "security"
HUMAN = ("OWNER", "MEMBER", "COLLABORATOR")
RISKY = [
    ".coderabbit.yaml",
    ".gitignore",
    ".github/**",
    "githooks/**",
    "hooks/**",
    "scripts/{consent,sync}/**",
    "forge/{hooks,sync,skills,framework,mcp,marketplace,owned,uninstall,publish}.py",
]


def glob_re(g):
    """A minimatch-style glob as a regex: `**` crosses `/`, `*` and `?` do not, `{a,b}` alternates;
    case-insensitive, as CodeRabbit's path matching is."""
    out, i = "", 0
    while i < len(g):
        c = g[i]
        if g.startswith("**", i):
            out, i = out + ".*", i + 2
        elif c == "*":
            out, i = out + "[^/]*", i + 1
        elif c == "?":
            out, i = out + "[^/]", i + 1
        elif c == "{":
            j = g.index("}", i)
            out, i = out + "(?:" + "|".join(re.escape(a) for a in g[i + 1:j].split(",")) + ")", j + 1
        else:
            out, i = out + re.escape(c), i + 1
    return re.compile(out + r"\Z", re.I)


def decide(files, labels, author, head, reviews):
    """(state, description) for the status. `reviews` are the PR's reviews, oldest first, as the REST
    API lists them."""
    hit = [f for f in files if any(glob_re(g).match(f) for g in RISKY)]
    if not hit and LABEL not in labels:
        return "success", "not security-relevant: CodeRabbit's approval is not required"
    why = "%s changed" % hit[0] if hit else "labelled %s" % LABEL
    latest = {}
    for r in reviews:
        who = r["user"]["login"]
        human = author == "dependabot[bot]" and who != author and r.get("author_association") in HUMAN
        if (who == BOT or human) and r["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[who] = r
    for r in latest.values():
        if r["state"] == "APPROVED" and r["commit_id"] == head:
            return "success", "approved by %s" % r["user"]["login"]
    if any(r["state"] == "APPROVED" for r in latest.values()):
        return "pending", "%s: the approval is of an older commit, waiting for a review of %s" % (why, head[:7])
    if any(r["state"] == "CHANGES_REQUESTED" for r in latest.values()):
        return "pending", "%s: CodeRabbit requested changes" % why
    return "pending", "%s: waiting for CodeRabbit's approval of %s" % (why, head[:7])


def gh(args):
    r = subprocess.run(["gh", "api"] + args, capture_output=True, text=True)
    if r.returncode:
        sys.exit("gh api %s: exit %d: %s" % (" ".join(args), r.returncode, r.stderr.strip()))
    return r.stdout


def lines(path):
    return [json.loads(x) for x in gh(["--paginate", path, "--jq", ".[]"]).splitlines() if x]


def main():
    repo, pr = os.environ["REPO"], os.environ["PR"]
    meta = json.loads(gh(["repos/%s/pulls/%s" % (repo, pr)]))
    head = meta["head"]["sha"]
    files = []
    for f in lines("repos/%s/pulls/%s/files" % (repo, pr)):
        files += [f["filename"]] + ([f["previous_filename"]] if f.get("previous_filename") else [])
    state, desc = decide(files, [x["name"] for x in meta["labels"]], meta["user"]["login"], head,
                         lines("repos/%s/pulls/%s/reviews" % (repo, pr)))
    gh(["-X", "POST", "repos/%s/statuses/%s" % (repo, head), "-f", "state=" + state, "-f", "context=" + CONTEXT,
        "-f", "description=" + desc[:140]])
    print("%s on %s (%d files): %s, %s" % (CONTEXT, head[:7], len(files), state, desc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
