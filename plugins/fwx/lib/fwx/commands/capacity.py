"""How many agents of a role can start now: fwx capacity --role R --want N [--per-agent-mb M] [--wait S] [--unattended] [--json].

Prints `allowed N` and what it looked at (or one JSON object with --json): `{role, want, allowed, running, counted_from, limit,
ram_free_gb, ram_min_gb, quota, reasons}`. Exit 0 when `allowed` is above 0, 1 when it is 0, 2 when it cannot read (an unknown
role, a limit that is not a positive number, a flag it does not know, no git repository), 77 with `NOT RUN, NOT ARMED: ...` on
stderr where there is no /proc or no meminfo to read.

A role with a worktree (`executor`) is counted by its live agents: `allowed = min(want, limit - running, room)`. `running` is the
number of worktrees of the repository locked by `claude agent <id> (pid P start T)` with P alive and T its start time (the lock
is not enough: execute/cleanup.py `lock_state` says why). A read-only role (`ui-walker`, `reviewer`...) has no worktree and is
not counted (`running: not counted (read-only role)`); it is bounded by `limits.per_project[role]`, when there is one, and by
`room`. `room` is `floor((MemAvailable - ram_min_free_gb) / per agent)`, 0 under the floor; one agent reserves
`limits.ram_per_agent_mb` unless `--per-agent-mb` says what this role weighs (3.5 asks it for the browsers of the UI walk).
`limit` of an executor is `limits.per_project.executor`, else `limits.default_cap.supervised` (3), or `.unattended` (4) with
`--unattended`; `reasons` says which. With `limits.on` false `allowed = want` and nothing is read.

`quota` is what `fwx statusline` last saved of the account's usage windows for this session (the same reading as `fwx budget`),
or "unknown": the first limit met in practice was the usage quota, not the RAM, so the orchestrator sees it here, but it is
information and never changes `allowed`.

`--wait S` asks again every 15 s, never past S seconds, until `allowed` is above 0. MemAvailable is read from /proc/meminfo, or
from the file named by FWX_MEMINFO (the tests' fake).
"""
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

from fwx import config, state
from fwx.commands import budget
from fwx.execute import base, cleanup

MEMINFO = "/proc/meminfo"
INTERVAL_S = 15
WORKTREE_ROLES = ("executor",)  # the roles that run in a worktree of their own; every other role is read-only
USAGE = ("usage: fwx capacity --role R --want N [--per-agent-mb M] [--wait S] [--unattended] [--json]\n  roles: %s\n"
         % ", ".join(config.ROLES))
_AGENT_LOCK = re.compile(r"claude agent (agent-\S+|wf_\S+-\d+) \(pid \d+ start \d+\)\Z")


class Bad(Exception):
    """Cannot be used: exit 2 and the message."""


class NotRun(Exception):
    """Exit 77: the message is the reason."""


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def limits_of(cfg, role):
    """The limits this call uses, each checked: a bad value is Bad and names the key and what it holds."""
    lim = cfg.get("limits")
    if not isinstance(lim, dict):
        raise Bad("limits is not a table")
    if not isinstance(lim.get("on"), bool):
        raise Bad("limits.on is %r, not true or false" % (lim.get("on"),))
    if not (_number(lim.get("ram_min_free_gb")) and lim["ram_min_free_gb"] >= 0):
        raise Bad("limits.ram_min_free_gb is %r, not a number of GB (0 or more)" % (lim.get("ram_min_free_gb"),))
    if not (_number(lim.get("ram_per_agent_mb")) and lim["ram_per_agent_mb"] > 0):
        raise Bad("limits.ram_per_agent_mb is %r, not a positive number of MB" % (lim.get("ram_per_agent_mb"),))
    caps, per = lim.get("default_cap"), lim.get("per_project")
    if not isinstance(caps, dict) or not all(_count(caps.get(k)) for k in ("supervised", "unattended")):
        raise Bad("limits.default_cap is %r, not {supervised: N, unattended: N} with positive whole numbers" % (caps,))
    if not isinstance(per, dict):
        raise Bad("limits.per_project is not a table of role to a positive whole number")
    if role in per and not _count(per[role]):
        raise Bad("limits.per_project.%s is %r, not a positive whole number" % (role, per[role]))
    return lim


def mem_available_gb(path):
    """MemAvailable of the meminfo file in GiB; NotRun when there is no such file, Bad when it has no usable MemAvailable."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        raise NotRun("no %s" % path)
    except OSError as e:
        raise Bad("%s cannot be read (%s)" % (path, e.strerror))
    for line in lines:
        m = re.match(r"MemAvailable:\s+(\d+)\s*kB\s*\Z", line)
        if m:
            return int(m.group(1)) / (1024 * 1024)
    raise Bad("%s has no MemAvailable line (kernel before 3.14?)" % path)


def live_agents(top):
    """(live, locked, total): the worktrees of the repository locked by a live Claude Code agent, the ones locked by anyone,
    and every worktree but the main one."""
    others = cleanup.worktrees(top)[1:]
    live = [w for w in others if _AGENT_LOCK.match(w["locked"] or "") and cleanup.lock_state(w) == "live"]
    return live, [w for w in others if w["locked"] is not None], others


def quota(cwd):
    """The quota windows from the session's saved budget (fresh ones only), else "unknown"; it reads nothing else."""
    try:
        sid = state.session_id()
        data = budget.read_file(sid, cwd) if sid else None
    except (state.StateError, config.ConfigError):
        return "unknown"
    now = datetime.now(timezone.utc)
    if not data or (now - data["when"]).total_seconds() > budget.STALE_S:
        return "unknown"
    return budget.quota(data.get("rate_limits"), now)


def decide(cwd, top, role, want, unattended, per_agent_mb, lim):
    """The result dict for one look."""
    q = quota(cwd)
    res = {"role": role, "want": want, "allowed": want, "running": None, "counted_from": None, "limit": None,
           "ram_free_gb": None, "ram_min_gb": lim["ram_min_free_gb"], "quota": q, "reasons": []}
    why = res["reasons"]
    if not lim["on"]:
        why.append("limits.on is false: allowed = want, nothing counted and no RAM read")
        res["running"] = "not counted (limits off)"
        res["counted_from"] = "nothing (limits off)"
        return res
    free = mem_available_gb(os.environ.get("FWX_MEMINFO") or MEMINFO)
    per_mb = per_agent_mb if per_agent_mb is not None else lim["ram_per_agent_mb"]
    res["ram_free_gb"] = round(free, 2)
    room = max(0, math.floor((free - lim["ram_min_free_gb"]) / (per_mb / 1024)))
    why.append("RAM: %.2f GB free, floor %s GB, %s MB reserved per agent (%s): room for %d" % (
        free, lim["ram_min_free_gb"], per_mb, "--per-agent-mb" if per_agent_mb is not None else "limits.ram_per_agent_mb", room))
    if free < lim["ram_min_free_gb"]:
        why.append("the free RAM %.2f GB is under the floor of %s GB (limits.ram_min_free_gb)" % (free, lim["ram_min_free_gb"]))
    per = lim["per_project"].get(role)
    if role in WORKTREE_ROLES:
        live, locked, others = live_agents(top)
        if per is not None:
            res["limit"] = per
            why.append("limit %d: limits.per_project.%s" % (per, role))
        else:
            kind = "unattended" if unattended else "supervised"
            res["limit"] = lim["default_cap"][kind]
            why.append("limit %d: default cap for a %s run (limits.default_cap.%s; no limits.per_project.%s)" % (res["limit"], kind, kind, role))
        res["running"] = len(live)
        res["counted_from"] = "git worktree list --porcelain in %s: %d worktrees besides the main one, %d locked, %d locked by a live claude agent" % (
            top, len(others), len(locked), len(live))
        why.append("running %d of limit %d: %d free" % (len(live), res["limit"], max(0, res["limit"] - len(live))))
        res["allowed"] = max(0, min(want, res["limit"] - len(live), room))
    else:
        res["running"] = "not counted (read-only role)"
        res["counted_from"] = "no worktrees: a read-only role is bounded by RAM and limits.per_project only"
        if per is not None:
            res["limit"] = per
            why.append("limit %d: limits.per_project.%s" % (per, role))
        else:
            why.append("no limits.per_project.%s: only the RAM bounds it" % role)
        res["allowed"] = max(0, min([want, room] + ([per] if per is not None else [])))
    why.append("allowed = %d (want %d)" % (res["allowed"], want))
    return res


def text(res):
    lines = ["allowed %d" % res["allowed"],
             "role %s, want %d, running %s, limit %s" % (res["role"], res["want"], res["running"],
                                                          "none" if res["limit"] is None else res["limit"]),
             "counted from: %s" % res["counted_from"]]
    if res["ram_free_gb"] is not None:
        lines.append("RAM free %.1f GB, floor %s GB" % (res["ram_free_gb"], res["ram_min_gb"]))
    lines.append("quota: %s" % ("unknown" if res["quota"] == "unknown" else json.dumps(res["quota"])))
    lines += ["- " + r for r in res["reasons"]]
    return "\n".join(lines) + "\n"


def parse(argv):
    got, i = {"unattended": False, "json": False}, 0
    valued = {"--role": "role", "--want": "want", "--per-agent-mb": "per_agent_mb", "--wait": "wait"}
    while i < len(argv):
        a = argv[i]
        if a in valued and i + 1 < len(argv):
            got[valued[a]] = argv[i + 1]
            i += 2
        elif a in ("--unattended", "--json"):
            got[a[2:]] = True
            i += 1
        else:
            raise Bad("%s is not an option it takes, or lacks its value" % a)
    if "role" not in got or "want" not in got:
        raise Bad("--role and --want are required")
    if got["role"] not in config.ROLES:
        raise Bad("unknown role %r (roles: %s)" % (got["role"], ", ".join(config.ROLES)))
    try:
        got["want"] = int(got["want"])
        got["wait"] = int(got.get("wait", 0))
        mb = got.get("per_agent_mb")
        got["per_agent_mb"] = None if mb is None else float(mb)
    except ValueError as e:
        raise Bad("a number is not one: %s" % e)
    if got["want"] < 0 or got["wait"] < 0 or (got["per_agent_mb"] is not None and not got["per_agent_mb"] > 0):
        raise Bad("--want and --wait are 0 or more, --per-agent-mb above 0")
    return got


def main(argv):
    try:
        a = parse(argv)
        cwd = os.getcwd()
        cfg = config.load(cwd)
        lim = limits_of(cfg, a["role"])
        top = base.toplevel(cwd)
        if top is None:
            raise Bad("not inside a git repository: %s" % cwd)
        deadline = time.monotonic() + a["wait"]
        while True:
            res = decide(cwd, top, a["role"], a["want"], a["unattended"], a["per_agent_mb"], lim)
            left = deadline - time.monotonic()
            if res["allowed"] > 0 or left <= 0:
                break
            time.sleep(min(INTERVAL_S, left))
    except Bad as e:
        sys.stderr.write("fwx capacity: %s\n%s" % (e, USAGE))
        return 2
    except cleanup.NoProc as e:
        sys.stderr.write("fwx capacity: %s\n" % e)
        return 77
    except (config.ConfigError, base.WaveError) as e:
        sys.stderr.write("fwx capacity: %s\n" % e)
        return 2
    except NotRun as e:
        sys.stderr.write("fwx capacity: NOT RUN, NOT ARMED: %s\n" % e)
        return 77
    sys.stdout.write(json.dumps(res) + "\n" if a["json"] else text(res))
    return 0 if res["allowed"] > 0 else 1
