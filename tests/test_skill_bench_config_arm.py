#!/usr/bin/env python3
"""scripts/bench/skill_bench.py: an arm can be a config overlay, not only skill directories.

`--arm NAME=DIR` where DIR has no SKILL.md is a config overlay: its files (CLAUDE.md, .claude/settings.json,
.claude/agents/, any file) are copied over the run's work dir BEFORE the start commit, so they are part of the start
state like a real project's tracked CLAUDE.md. Why: the run's own config dir is stripped (no hooks, CLAUDE.md, agents), so
before this an arm could change skills only and "full config against trimmed config" could not be measured. Spiked on a
real CLI first: under that stripped config dir a project-scope CLAUDE.md, hook and agent in the work dir all take effect
(reply began with the CLAUDE.md marker, the hook wrote its file, the agent was listed) and none did in an empty dir.

The agent is a fake `claude` that reports what it finds in its working directory (CLAUDE.md, agents, skills, git status,
the head of the prompt) in its final message; the oracle reads that message.

Controls, each seen failing before the behaviour existed or with it removed (messages in the commit):
  overlay applied      a `--arm cfg=DIR` run exited 1 with "cfg: DIR has no SKILL.md" before this change
  start commit         overlay copied after the commit instead of before: the check "overlay is tracked" fails
  fingerprint          overlay left out of the manifest hash: re-running an arm name with changed content is accepted
Old manifests: an arm without an overlay keeps exactly the old shape {"skills": [...]}, so existing run.json files stay valid."""
import gzip
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

SCRIPT = os.path.join(sandbox.FORGE, "scripts", "bench", "skill_bench.py")
failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


ORACLE = '''
import os
def check(repo, message):
    status = message.split("STATUS=")[-1]
    return [{"id": "claude-md-seen", "passed": "MARKER-42" in message, "evidence": message[:60]},
            {"id": "settings-present", "passed": os.path.isfile(os.path.join(repo, ".claude", "settings.json")), "evidence": ".claude/settings.json"},
            {"id": "agent-seen", "passed": "zebra" in message, "evidence": "AGENTS="},
            {"id": "overlay-is-tracked", "passed": "CLAUDE.md" not in status and "settings.json" not in status, "evidence": status.strip()[:80]}]
'''
FAKE = '''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
if args and args[0] == "--version":
    print("9.9.9 (Fake Code)")
    sys.exit(0)
prompt = args[args.index("-p") + 1] if "-p" in args else ""
claude_md = open("CLAUDE.md").read().strip() if os.path.exists("CLAUDE.md") else ""
agents = sorted(os.listdir(".claude/agents")) if os.path.isdir(".claude/agents") else []
skills = sorted(os.listdir(".claude/skills")) if os.path.isdir(".claude/skills") else []
status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
msg = "CLAUDE=%s;AGENTS=%s;SKILLS=%s;PROMPTHEAD=%s;STATUS=%s" % (claude_md, ",".join(agents), ",".join(skills), prompt[:70], status)
print(json.dumps({"type": "system", "subtype": "init", "model": "fake-model-1"}))
print(json.dumps({"type": "result", "result": msg, "is_error": False, "num_turns": 1, "total_cost_usd": 0.01,
                  "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}))
'''


def cli(*a):
    r = subprocess.run([sys.executable, SCRIPT] + list(a), capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def results(out):
    res = {}
    for root, _, fs in os.walk(out):
        if "result.json" in fs:
            r = json.load(open(os.path.join(root, "result.json")))
            res[r["arm"]] = r
    return res


def transcript(out, arm):
    for root, _, fs in os.walk(out):
        if "agent.jsonl.gz" in fs and os.path.basename(os.path.dirname(root)) == arm:
            return gzip.open(os.path.join(root, "agent.jsonl.gz"), "rt").read()
    return ""


def main():
    tmp = sandbox.mkdtemp("skillbench-cfgarm-")
    fake = os.path.join(tmp, "claude")
    put(fake, FAKE)
    os.chmod(fake, 0o755)
    bench = os.path.join(tmp, "bench")
    put(os.path.join(bench, "concepts.json"), json.dumps({"logic.arith": {"field": "logic", "title": "arithmetic"}}))
    d = os.path.join(bench, "tasks", "t0")
    put(os.path.join(d, "task.json"), json.dumps({"id": "t0", "field": "logic", "concept": "logic.arith", "difficulty": 1,
                                                   "prompt": "Fix add() in task 0.", "source": {"kind": "authored"}, "message_required": True}))
    put(os.path.join(d, "repo", "calc.py"), "def add(a, b):\n    return a - b\n")
    put(os.path.join(d, "oracle.py"), ORACLE)

    overlay = os.path.join(tmp, "arms", "cfg")
    put(os.path.join(overlay, "CLAUDE.md"), "MARKER-42 always\n")
    put(os.path.join(overlay, ".claude", "settings.json"), '{"hooks": {}}\n')
    put(os.path.join(overlay, ".claude", "agents", "zebra.md"), "---\nname: zebra\n---\n")
    skill = os.path.join(tmp, "arms", "sk1")
    put(os.path.join(skill, "SKILL.md"), "---\nname: sk1\ndescription: fake\n---\n")

    out = os.path.join(tmp, "runs")
    common = ["--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--k", "1", "--seed", "3"]
    code, text = cli("run", *common, "--out", out, "--arm", "none", "--arm", "cfg=" + overlay, "--arm", "mix=%s:%s" % (overlay, skill))
    want("run with an overlay arm exits 0", code, 0)
    if code:
        failures.append("the run said: " + text.strip()[-160:])
        for msg in failures:
            print("FAIL", msg)
        print("%d failure(s)" % len(failures))
        sandbox.cleanup(failures)
        sys.exit(1)
    res = results(out)
    want("arm none: nothing from the overlay, the run fails the oracle", (res["none"]["passed"], res["none"]["invalid"]), (False, False))
    want("overlay arm passes every check (CLAUDE.md, settings, agent seen; all tracked in the start commit)",
         [(c["id"], c["passed"]) for c in res["cfg"]["checks"]],
         [("claude-md-seen", True), ("settings-present", True), ("agent-seen", True), ("overlay-is-tracked", True)])
    mixed = transcript(out, "mix")
    want("overlay + skill arm: both applied", ("MARKER-42" in mixed, "SKILLS=sk1" in mixed), (True, True))

    man = json.load(open(os.path.join(out, "run.json")))
    want("an arm without an overlay keeps the old manifest shape", man["arms"]["none"], {"skills": []})
    want("an overlay arm records its folder hash under config and no skills", (list(man["arms"]["cfg"]), man["arms"]["cfg"]["skills"]),
         (["skills", "config"], []))
    want("a mixed arm lists the skill and the overlay separately", (len(man["arms"]["mix"]["skills"]), len(man["arms"]["mix"].get("config", []))), (1, 1))

    code, text = cli("run", *common, "--out", out, "--arm", "cfg=" + overlay)
    want("same overlay, same --out: accepted", code, 0)
    put(os.path.join(overlay, "CLAUDE.md"), "MARKER-43 changed\n")
    code, text = cli("run", *common, "--out", out, "--arm", "cfg=" + overlay)
    want("changed overlay under the same arm name: refused", (code != 0, "changed since" in text), (True, True))

    out2 = os.path.join(tmp, "runs2")
    put(os.path.join(overlay, "CLAUDE.md"), "MARKER-42 always\n")
    code, text = cli("run", *common, "--out", out2, "--force-skill", "--arm", "mix=%s:%s" % (overlay, skill))
    want("--force-skill names the skill even when the overlay is listed first", "PROMPTHEAD=Use the skill in .claude/skills/sk1" in transcript(out2, "mix"), True)

    empty = os.path.join(tmp, "arms", "empty")
    os.makedirs(empty)
    code, text = cli("run", *common, "--out", os.path.join(tmp, "r3"), "--arm", "e=" + empty)
    want("an empty folder is refused (a typo, not an overlay)", (code != 0, "empty" in text), (True, True))
    code, text = cli("run", *common, "--out", os.path.join(tmp, "r4"), "--arm", "m=" + os.path.join(tmp, "arms", "missing"))
    want("a missing folder is refused", (code != 0, "not a directory" in text), (True, True))

    # a project task: its start state is already a repository, so the overlay is committed on top of it
    proj = os.path.join(tmp, "proj")
    os.makedirs(proj)
    subprocess.run(["git", "init", "-q", proj], check=True)
    put(os.path.join(proj, "calc.py"), "def add(a, b):\n    return a - b\n")
    gitc = ["git", "-C", proj, "-c", "user.name=t", "-c", "user.email=t"]
    subprocess.run(gitc + ["add", "-A"], check=True)
    subprocess.run(gitc + ["commit", "-qm", "base"], check=True)
    base = subprocess.run(gitc + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    pd = os.path.join(proj, ".bench", "tasks", "p0")
    put(os.path.join(pd, "task.json"), json.dumps({
        "id": "p0", "field": "logic", "concept": "logic.arith", "difficulty": 1, "prompt": "Fix add() in the project.",
        "source": {"kind": "project", "project": "toy", "ref": "git:" + base}, "message_required": False,
        "base": {"commit": base}, "setup": [],
        "checks": [{"id": "overlay-tracked", "cmd": 'test -f CLAUDE.md && test -z "$(git status --porcelain)"', "before": "fail"}]}))
    pout = os.path.join(tmp, "runp")
    code, text = cli("run", "--bench", os.path.join(proj, ".bench"), "--claude-bin", fake, "--sandbox", "none", "--k", "1", "--out", pout,
                     "--arm", "none", "--arm", "cfg=" + overlay)
    pres = results(pout)
    want("project task: overlay arm has CLAUDE.md and a clean tree (overlay committed), arm none has no CLAUDE.md",
         (code, pres.get("cfg", {}).get("passed"), pres.get("none", {}).get("passed")), (0, True, False))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
