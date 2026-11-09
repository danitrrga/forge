#!/usr/bin/env python3
"""`.coderabbit.yaml` keeps the properties the merge gate and the owner's decisions rest on: CodeRabbit
requests changes and approves (auto_approvals on), approves only within a risk limit with a stricter one
for the risky paths, cannot be paused into a green-but-unreviewed check, runs no docstring-coverage check, skips only the bot that the gate
could hold forever, and can commit, push or open a PR through no finishing touch. The schema check
(https://coderabbit.ai/integrations/schema.v2.json) needs the network and is not run here.

Needs PyYAML; without it this prints NOT RUN, NOT ARMED and exits 0 (rule 4 of CLAUDE.md).

Controls, each a copy of the real config with one property broken that `problems` must name. Seen
failing first, before .coderabbit.yaml existed: "FAIL .coderabbit.yaml is missing". """
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TOUCHES = ("docstrings", "unit_tests", "simplify", "autofix", "fix_ci", "resolve_merge_conflict")


def problems(cfg):
    """Each way the config breaks a property above; looks at the whole of it, never at zero keys."""
    r = cfg.get("reviews") or {}
    aa, ar, ft = r.get("auto_approvals") or {}, r.get("auto_review") or {}, r.get("finishing_touches") or {}
    out = []
    if aa.get("enabled") is not True:
        out.append("auto_approvals.enabled is not true: CodeRabbit would neither request changes nor approve")
    if "request_changes_workflow" in r:
        out.append("request_changes_workflow beside auto_approvals: two names for one switch is a config error")
    if aa.get("max_merge_risk") not in ("minimal", "low", "moderate", "high", "critical"):
        out.append("auto_approvals.max_merge_risk is not a level: approval would not depend on risk")
    if aa.get("allow_author_approval") is not False:
        out.append("allow_author_approval is not false: the PR author could force an approval")
    if not any(o.get("max_merge_risk") == "low" and o.get("paths") for o in aa.get("overrides") or []):
        out.append("no override gives the risky paths a stricter limit")
    if ar.get("enabled") is not True or ar.get("drafts") is not False:
        out.append("auto_review is not on for non-draft PRs")
    if ar.get("auto_pause_after_reviewed_commits") != 0:
        out.append("auto_pause_after_reviewed_commits is not 0: a paused review leaves the required check green")
    if ar.get("ignore_usernames") != ["dependabot[bot]"]:
        out.append("ignore_usernames is %s, want only dependabot[bot]" % ar.get("ignore_usernames"))
    if ((r.get("pre_merge_checks") or {}).get("docstrings") or {}).get("mode") != "off":
        out.append("pre_merge_checks.docstrings.mode is not off: forge has no docstring convention to enforce")
    for t in TOUCHES:
        if (ft.get(t) or {}).get("enabled") is not False:
            out.append("finishing_touches.%s is not off: CodeRabbit could write to the repo" % t)
    if ft.get("custom"):
        out.append("finishing_touches.custom has recipes: CodeRabbit could write to the repo")
    if not [p for p in r.get("path_instructions") or [] if p.get("path") == "**" and "personal" in p.get("instructions", "")]:
        out.append("no path_instructions entry carries the nothing-personal rule for every path")
    return out


def main():
    try:
        import yaml
    except ImportError:
        print("NOT RUN, NOT ARMED: PyYAML is not installed, so .coderabbit.yaml was not read")
        return 0
    p = os.path.join(ROOT, ".coderabbit.yaml")
    if not os.path.exists(p):
        print("FAIL .coderabbit.yaml is missing")
        return 1
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    failures = ["FAIL " + m for m in problems(cfg)]

    def broken(label, mutate, needle):
        c = copy.deepcopy(cfg)
        mutate(c["reviews"])
        if not any(needle in m for m in problems(c)):
            failures.append("FAIL control %s: problems() did not name %r" % (label, needle))

    broken("auto_approvals off", lambda r: r["auto_approvals"].update(enabled=False), "auto_approvals.enabled")
    broken("legacy key", lambda r: r.update(request_changes_workflow=True), "request_changes_workflow")
    broken("no limit", lambda r: r["auto_approvals"].pop("max_merge_risk"), "max_merge_risk")
    broken("author approval", lambda r: r["auto_approvals"].update(allow_author_approval=True), "author")
    broken("no override", lambda r: r["auto_approvals"].pop("overrides"), "stricter limit")
    broken("pause", lambda r: r["auto_review"].update(auto_pause_after_reviewed_commits=5), "paused")
    broken("ignored users", lambda r: r["auto_review"].update(ignore_usernames=[]), "ignore_usernames")
    broken("autofix on", lambda r: r["finishing_touches"].update(autofix={"enabled": True}), "finishing_touches.autofix")
    broken("a touch left out", lambda r: r["finishing_touches"].pop("fix_ci"), "finishing_touches.fix_ci")
    broken("docstrings check on", lambda r: r.pop("pre_merge_checks"), "docstrings")
    broken("no personal rule", lambda r: r.update(path_instructions=[]), "nothing-personal")
    for m in failures:
        print(m)
    print("%d failure(s); read %d top-level and %d reviews keys" % (len(failures), len(cfg), len(cfg["reviews"])))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
