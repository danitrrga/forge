#!/usr/bin/env python3
"""The merge gate that makes CodeRabbit's approval required only where it is security-relevant
(.github/scripts/coderabbit_gate.py, run by .github/workflows/coderabbit-gate.yml): which changed paths
and labels arm it, whose approval of which commit releases it, and that its list of risky paths is the
list `.coderabbit.yaml` gives CodeRabbit's stricter risk limit.

`check(decide)` returns every case the function gets wrong; `main` runs it on the real `decide` (must
find nothing) and on naive variants (each must be caught naming its case), which is the negative control.
Seen failing first, before the script existed: "FileNotFoundError ... coderabbit_gate.py".
The PyYAML part prints NOT RUN, NOT ARMED without PyYAML (CLAUDE.md, rule 4)."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BOT = "coderabbitai[bot]"
HEAD, OLD = "a" * 40, "b" * 40


def load():
    spec = importlib.util.spec_from_file_location("gate", os.path.join(ROOT, ".github", "scripts", "coderabbit_gate.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rv(state, login=BOT, sha=HEAD, assoc="NONE"):
    return {"user": {"login": login}, "state": state, "commit_id": sha, "author_association": assoc}


def check(decide):
    """Each case is (label, call args, wanted state); the PR's author defaults to the owner."""
    safe, risky = ["README.md", "forge/lib.py", "tests/test_x.py"], ["README.md", "hooks/guard_tool_use.py"]
    cases = [
        ("no risky path, no review", (safe, [], "owner", HEAD, []), "success"),
        ("no risky path, changes requested", (safe, [], "owner", HEAD, [rv("CHANGES_REQUESTED")]), "success"),
        ("hooks/ and no review", (risky, [], "owner", HEAD, []), "pending"),
        ("hooks/ and a comment only", (risky, [], "owner", HEAD, [rv("COMMENTED")]), "pending"),
        ("hooks/ approved", (risky, [], "owner", HEAD, [rv("APPROVED")]), "success"),
        ("hooks/ approved an older commit", (risky, [], "owner", HEAD, [rv("APPROVED", sha=OLD)]), "pending"),
        ("hooks/ approved then changes requested", (risky, [], "owner", HEAD, [rv("APPROVED"), rv("CHANGES_REQUESTED")]), "pending"),
        ("hooks/ approved, then dismissed", (risky, [], "owner", HEAD, [rv("DISMISSED")]), "pending"),
        ("hooks/ approved by a human, not CodeRabbit", (risky, [], "owner", HEAD, [rv("APPROVED", "someone", assoc="OWNER")]), "pending"),
        ("hooks/ approved, then only a comment", (risky, [], "owner", HEAD, [rv("APPROVED"), rv("COMMENTED")]), "success"),
        ("a .github/ file and no review", ([".github/workflows/x.yml"], [], "owner", HEAD, []), "pending"),
        ("security label on a safe PR", (safe, ["security"], "owner", HEAD, []), "pending"),
        ("security label, approved", (safe, ["security"], "owner", HEAD, [rv("APPROVED")]), "success"),
        ("dependabot on .github/, no review", ([".github/workflows/ci.yml"], [], "dependabot[bot]", HEAD, []), "pending"),
        ("dependabot on .github/, owner approved", ([".github/workflows/ci.yml"], [], "dependabot[bot]", HEAD,
                                                    [rv("APPROVED", "owner", assoc="OWNER")]), "success"),
        ("dependabot, a stranger approved", ([".github/workflows/ci.yml"], [], "dependabot[bot]", HEAD,
                                             [rv("APPROVED", "x", assoc="NONE")]), "pending"),
    ]
    out = []
    for label, args, want in cases:
        got = decide(*args)[0]
        if got != want:
            out.append("%s: %s, want %s" % (label, got, want))
    return out


def main():
    gate = load()
    failures = ["FAIL " + m for m in check(gate.decide)]

    def control(label, naive, needle):
        if not any(needle in m for m in check(naive)):
            failures.append("FAIL control %s: check() did not name %r" % (label, needle))

    real = gate.decide
    # Each naive variant forgets one rule; check() must name the case that rule exists for.
    control("ignores the commit", lambda f, l, a, h, r: real(f, l, a, h, [dict(x, commit_id=h) for x in r]),
            "approved an older commit")
    control("any approver", lambda f, l, a, h, r: real(f, l, a, h, [dict(x, user={"login": BOT}) for x in r]),
            "not CodeRabbit")
    control("never arms", lambda f, l, a, h, r: real([], [], a, h, r), "hooks/ and no review")
    control("ignores the label", lambda f, l, a, h, r: real(f, [], a, h, r), "security label on a safe PR")
    control("first review wins", lambda f, l, a, h, r: real(f, l, a, h, r[:1]), "then changes requested")

    try:
        import yaml
    except ImportError:
        print("NOT RUN, NOT ARMED: PyYAML is not installed, so the risky paths were not compared with .coderabbit.yaml")
        yaml = None
    if yaml:
        with open(os.path.join(ROOT, ".coderabbit.yaml"), encoding="utf-8") as f:
            ov = yaml.safe_load(f)["reviews"]["auto_approvals"]["overrides"]
        paths = [p for o in ov if o.get("max_merge_risk") == "low" for p in o["paths"]]
        if not paths:
            failures.append("FAIL .coderabbit.yaml has no stricter-limit override paths to compare")
        elif sorted(paths) != sorted(gate.RISKY):
            failures.append("FAIL gate RISKY %s differs from .coderabbit.yaml's stricter-limit paths %s"
                            % (sorted(gate.RISKY), sorted(paths)))
        # Every risky glob matches an example file, so a glob that matches nothing fails here.
        for g, example in (("hooks/**", "hooks/guard_tool_use.py"), ("scripts/{consent,sync}/**", "scripts/consent/omarchy/x"),
                           ("forge/{hooks,sync}.py", "forge/sync.py"), (".github/**", ".github/workflows/ci.yml")):
            if not gate.glob_re(g).match(example):
                failures.append("FAIL glob %s does not match %s" % (g, example))
        if gate.glob_re("hooks/**").match("tests/hooks/x.py") or gate.glob_re("forge/{hooks,sync}.py").match("forge/lib.py"):
            failures.append("FAIL a glob matched a path it should not")
    for m in failures:
        print(m)
    print("%d failure(s); %d risky globs" % (len(failures), len(gate.RISKY)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
