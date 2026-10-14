#!/usr/bin/env python3
"""memory_doctor.py — assert that memory actually works, per project, per agent.

WHY THIS EXISTS. Memory is the one subsystem on this machine that fails silently. Nothing
breaks, no error appears; the agent simply does not know what it knew yesterday. An
injection abort was found a day later by chance. A timeout was still
unaddressed a day after that. And a store was found that had been collecting
other projects' memories for four months while its own registry entry called it "read-only".

Every one of those was visible in a file on disk the whole time. Nobody was looking.

WHAT IT CHECKS, and why each one earns its place:

  codex-trust       Codex gates hooks behind a persisted trust hash. An entry in
                    [hooks.state] whose manifest no longer exists is a hook that will never
                    fire again, recorded as though it were healthy. No record at all is normal:
                    forge registers no Codex hook.
  codex-untrusted   The mirror image: a hook registered in the manifest with NO trust record
                    never fires at all. A freshly written one is legitimately untrusted until
                    the next Codex session approves it, so this warns rather than fails -- but
                    one that stays untrusted is a hook doing nothing, silently. A hooks.json
                    that exists but does not parse FAILs: Codex loads none of its hooks, and
                    no next session fixes that.
  lite-*            A claude-mem-lite store: CLAUDE_MEM_DIR derived from the project name,
                    the directory present and writable, rows written, no session stuck
                    'active' (it breaks the next SessionStart), rows labelled for this
                    project, and the plugin actually enabled.
  hindsight-*       The rendered config names a server, and every server it names answers.

  --bank            The hindsight bank answers a real recall over the network.

claude-mem itself (thedotmack) was retired, and its per-store checks
(store-*, claude-env, codex-mcp, codex-hook-env, capture-agrees, --mcp) went with it. Its
stores stay on disk under data/memory/ as an archive.

THE KNOWN BACKLOG IS NOT NOISE. Some stores are empty today by history rather than by fault
(once, nine). A gate that prints the same nine failures at every session start trains the
reader to stop reading it -- the exact failure this tool exists to prevent. So known entries
live in config/memory-known-empty.json with a reason and a date, are silent in --hook mode,
and are listed separately in full output. A known entry that has STOPPED failing is itself
reported, so the backlog cannot quietly rot.

IT NEVER WRITES A MEMORY. hindsight_doctor.py learned this the hard way -- seventeen canary
probe sessions were retained as real documents and then outranked the user's own memories on
any similarly-worded query. Every check here is a read, a stat, or a handshake.

    python3 scripts/sync/memory_doctor.py
    python3 scripts/sync/memory_doctor.py --project forge --verbose
    python3 scripts/sync/memory_doctor.py --bank
    python3 scripts/sync/memory_doctor.py --all          # ignore the backlog, show everything

Exits 1 on any unexpected failure (the count is printed), 0 otherwise. Known-backlog entries
and warnings do not fail.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import tomllib
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from forge import lib, memory  # noqa: E402
HOME = lib.HOME
KNOWN = os.path.join(ROOT, "config", "memory-known-empty.json")
HINDSIGHT_RENDERED = os.path.join(HOME, ".hindsight", "coding-agent.json")

# $CODEX_HOME, Codex's own convention for relocating its config: the gate can be aimed at a
# fixture without touching the live file, and it reads the file the generator writes.
CODEX_HOME = lib.CODEX_HOME
CODEX_USER_CONFIG = os.path.join(CODEX_HOME, "config.toml")

COLOR = {"PASS": "\033[32m", "FAIL": "\033[31m", "WARN": "\033[33m", "KNOWN": "\033[2m"}
DIM, OFF = "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    COLOR = {k: "" for k in COLOR}
    DIM = OFF = ""

QUIET = False        # --hook: say nothing per check, speak only if something is unexpected
SHOW_ALL = False     # --all: treat the declared backlog as ordinary failures

fails: list[str] = []
warns: list[str] = []
backlog: list[str] = []      # failures declared in config/memory-known-empty.json
known_map: dict[str, dict] = {}
known_still_failing: set[str] = set()


def emit(level: str, name: str, detail: str) -> None:
    if not QUIET:
        print("  %s%-5s%s %-18s %s"
              % (COLOR[level], level, OFF, name, (DIM + detail + OFF) if detail else ""))


def check(scope: str, name: str, ok: bool, detail: str = "") -> bool:
    """Record and print one check. A failed check is the whole point of the script."""
    key = "%s/%s" % (scope, name)
    if ok:
        emit("PASS", name, detail)
        return True
    if key in known_map and not SHOW_ALL:
        known_still_failing.add(key)
        entry = known_map[key]
        emit("KNOWN", name, "%s — known since %s: %s"
             % (detail, entry.get("since", "?"), entry.get("why", "no reason recorded")))
        backlog.append("%s: %s" % (key, detail or "no detail"))
        return False
    emit("FAIL", name, detail)
    fails.append("%s: %s" % (key, detail or "no detail"))
    return False


def warn(scope: str, name: str, detail: str) -> None:
    emit("WARN", name, detail)
    warns.append("%s/%s: %s" % (scope, name, detail))


def note(text: str) -> None:
    if not QUIET:
        print("  %s%s%s" % (DIM, text, OFF))


def short(path: str) -> str:
    return path.replace(ROOT, "").replace(HOME, "~")


# --------------------------------------------------------------------------- codex config

def load_toml(path: str) -> dict:
    """Parse a Codex config. tomllib, not a regex: forge/mcp.py already depends on
    tomllib unconditionally to validate this same file, and it writes array values
    (`args = [...]`) that no flat key = "value" scanner can read."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


# Codex normalises the manifest's CamelCase event names into snake_case for its trust keys.
CODEX_EVENT_KEY = {"SessionStart": "session_start", "UserPromptSubmit": "user_prompt_submit",
                   "PreToolUse": "pre_tool_use", "PostToolUse": "post_tool_use",
                   "Stop": "stop", "SessionEnd": "session_end", "PreCompact": "pre_compact"}


def codex_untrusted_hooks(config_path: str, manifest_path: str) -> tuple[list[str], int, str | None]:
    """Hooks registered in a manifest that carry no trust record, so they never fire.

    Codex keys a trust record as "<manifest>:<event>:<group index>:<hook index>". A hook with
    no record is not an error -- a newly written one is untrusted until the next Codex session
    approves it -- but one that stays untrusted is a hook that silently does nothing, which is
    the whole class of failure this gate exists for.

    Returns (untrusted, hooks examined, why the manifest is unreadable or None). A missing
    manifest is no hooks. One that exists but does not parse, or is not a JSON object, is
    unreadable: until round 7 (S2) load_json turned it into {}, no hook was examined, and the
    caller PASSed "every registered hook is trusted" on the one input where none can fire.
    lexists, not exists: a dangling link is a manifest Codex cannot open either, and
    lib.read_owned would call it missing. A manifest with any entry of the wrong shape is
    unreadable too (lib.hook_entries counts them): the hooks around it cannot be trusted to be
    the ones Codex loads.
    """
    if not os.path.lexists(manifest_path):
        return [], 0, None
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        return [], 0, "%s: %s" % (type(e).__name__, e)
    if not isinstance(manifest, dict):
        return [], 0, "the top level is %s, not an object" % type(manifest).__name__
    state = (load_toml(config_path).get("hooks") or {}).get("state") or {}
    entries, malformed = lib.hook_entries(manifest)
    if malformed:
        return [], 0, "%d entr%s of the wrong shape" % (malformed, "y" if malformed == 1 else "ies")
    out = []
    for event, gi, hi, hook in entries:
        key = "%s:%s:%d:%d" % (manifest_path, CODEX_EVENT_KEY.get(event, event), gi, hi)
        if key not in state:
            cmd = hook.get("command")
            out.append("%s %s" % (event, (cmd if isinstance(cmd, str) else "")[:70]))
    return out, len(entries), None


def codex_trusted_hook_sources(path: str) -> list[str]:
    """Every trust record in [hooks.state], reduced to the manifest it points at."""
    state = (load_toml(path).get("hooks") or {}).get("state") or {}
    out = set()
    for raw in state:
        # Trailing ":<event>:<i>:<j>" is the hook's position, not part of the source.
        parts = raw.rsplit(":", 3)
        out.add(parts[0] if len(parts) == 4 else raw)
    return sorted(out)


def resolve_codex_hook_source(src: str) -> str | None:
    """Turn a trust-record source into a path on disk, or None if it cannot be resolved.

    Two shapes exist: an absolute path, and "<plugin>@<marketplace>:<relative path>". The
    plugin form walks versions newest-first rather than taking the newest outright, because
    an update can drop a file that an older version still has and the record still names.
    """
    if src.startswith("/"):
        return src if os.path.exists(src) else None
    m = re.match(r"^([^@]+)@([^:]+):(.+)$", src)
    if not m:
        return None
    plugin, marketplace, rel = m.groups()
    base = os.path.join(CODEX_HOME, "plugins", "cache", marketplace, plugin)
    if not os.path.isdir(base):
        return None
    versions = sorted(os.listdir(base),
                      key=lambda v: [int(x) if x.isdigit() else x
                                     for x in re.split(r"(\d+)", v)])
    for v in reversed(versions):
        cand = os.path.join(base, v, rel)
        if os.path.exists(cand):
            return cand
    return None


# ------------------------------------------------------------------------------- hindsight

def hindsight_recall(cfg: dict, bank: str, query: str, timeout: float = 20.0):
    """Read-only recall against the bank. urllib.error is imported here: import cost on a path
    --hook never takes."""
    import urllib.error
    import urllib.request

    url = "%s/v1/default/banks/%s/memories/recall" % (cfg["apiUrl"].rstrip("/"), bank)
    req = urllib.request.Request(url, data=json.dumps({"query": query}).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    if cfg.get("apiToken"):
        req.add_header("Authorization", "Bearer %s" % cfg["apiToken"])
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return True, len(data.get("results", [])), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return False, 0, time.time() - t0, "HTTP %s" % e.code
    except Exception as e:                                    # noqa: BLE001 - report anything
        return False, 0, time.time() - t0, type(e).__name__ + ": " + str(e)[:80]


# ------------------------------------------------------------------------------ one project

def check_project(name: str, prof: dict) -> None:
    ppath = prof.get("project_path", "")
    settings_path = os.path.join(ppath, ".claude", "settings.local.json")
    try:
        settings_local = lib.read_owned(settings_path)
    except lib.Unreadable as e:
        check(name, "settings-local", False, str(e))
        return

    # ---------------------------------------------------------------- claude-mem-lite
    # A plugin rather than a registry server, so there is no registry entry to compare
    # against: the profile opting in IS the grant, and the only outside input is where the
    # database goes. The failure this catches is the loudest-quiet one in the package --
    # CLAUDE_MEM_DIR unset resolves to the single shared default at ~/.claude-mem-lite and
    # every project's memory silently lands in one file together.
    lite_on = (prof.get("plugins_keep") or [])
    if memory.LITE_PLUGIN in lite_on:
        shared = prof.get("memory_lite_store") is not None
        want = os.path.join(memory.LITE_ROOT, memory.lite_store_name(prof, name) or name)
        got = (settings_local.get("env") or {}).get("CLAUDE_MEM_DIR")
        if check(name, "lite-env", got == want,
                 short(want) if got == want
                 else "settings.local.json says %r, the project name says %r" % (got, want)):
            here = os.path.isdir(want)
            if check(name, "lite-dir-exists", here,
                     short(want) if here else "no directory at " + short(want)):
                w = os.access(want, os.W_OK)
                check(name, "lite-dir-writable", w,
                      short(want) if w else "not writable: " + short(want))
                db = os.path.join(want, "claude-mem-lite.db")
                rows = None
                if os.path.exists(db):
                    try:
                        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
                        rows = con.execute("select count(*) from observations").fetchone()[0]
                        con.close()
                    except Exception as e:
                        rows = str(e)
                check(name, "lite-store-has-rows", isinstance(rows, int) and rows > 0,
                      "%d observations" % rows if isinstance(rows, int)
                      else "no claude-mem-lite.db yet — nothing has been written"
                      if rows is None else str(rows))
                # And that those rows answer to the name the plugin will ask for. lite derives
                # the label from the directory as `<parent>--<basename>`; claude-mem used its
                # own project name. A store seeded from claude-mem therefore holds its history
                # under one label while every new row arrives under another, and the
                # project-scoped surfaces see only the new ones -- measured on forge's store,
                # `recent` answered "No recent observations (Projects--forge)" with 1,901 rows
                # in the file. Nothing errors, which is why it needs a check rather than a
                # reader. Only a store seeded from claude-mem can trip it, and claude-mem was retired
                # since; the repair, relabel_lite_project.py, was removed since
                # and is in git history.
                # A shared store holds rows labelled for every project that writes to it, so a
                # project that has not written yet has none under its own label: not a fault.
                if isinstance(rows, int) and rows and not shared:
                    pp = os.path.normpath(ppath).rstrip(os.sep)
                    clean = lambda x: "".join(c if c.isalnum() else "-" for c in x)
                    want_label = "%s--%s" % (clean(os.path.basename(os.path.dirname(pp))),
                                             clean(os.path.basename(pp)))
                    try:
                        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
                        mine = con.execute("select count(*) from observations where project = ?",
                                           (want_label,)).fetchone()[0]
                        top = con.execute("select project, count(*) from observations "
                                          "group by 1 order by 2 desc limit 1").fetchone()
                        con.close()
                    except Exception as e:
                        mine, top = 0, (str(e)[:40], 0)
                    check(name, "lite-rows-are-labelled-for-this-project", mine > 0,
                          "%d of %d under %r" % (mine, rows, want_label) if mine
                          else "0 rows under %r — the store's rows say %r, so every "
                               "project-scoped read returns nothing (repair: "
                               "relabel_lite_project.py from git history: git log --all -- scripts/sync/relabel_lite_project.py)"
                               % (want_label, top[0] if top else "?"))
        plug = (settings_local.get("enabledPlugins", {}) or {}).get(memory.LITE_PLUGIN)
        check(name, "lite-capture-agrees", plug is True,
              "plugin enabled" if plug is True
              else "store configured but the claude-mem-lite plugin is %r" % plug)


# ------------------------------------------------------------------------------------ main

def main() -> int:
    global QUIET, SHOW_ALL

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="check only this profile")
    ap.add_argument("--bank", action="store_true", help="also recall from the hindsight bank")
    ap.add_argument("--verbose", action="store_true", help="show projects with no memory too")
    ap.add_argument("--all", action="store_true", dest="show_all",
                    help="treat the declared backlog as ordinary failures")
    ap.add_argument("--hook", action="store_true",
                    help="SessionStart mode: print only unexpected failures, say nothing "
                         "when clean, and always exit 0 so a sick store never blocks a session")
    args = ap.parse_args()

    QUIET, SHOW_ALL = args.hook, args.show_all
    try:
        known = lib.read_owned(KNOWN).get("known", {})
        if not isinstance(known, dict):
            raise lib.Unreadable(KNOWN, "`known` is %s, not an object" % type(known).__name__)
        known_map.update(known)
    except lib.Unreadable as e:
        check("machine", "known-empty", False, str(e))

    # Through lib, like every other profile reader: a profile that is not an object or carries a
    # field of the wrong type is skipped instead of raising AttributeError here (`[1]`) or being
    # substring-matched (`"servers": "hindsight-coding-agents"`). Skipped silently, as the
    # unreadable ones always were: session start and verify_skill_refs already name them, and
    # --hook must print nothing.
    profiles = [(n, p) for n, p in lib.profiles().items() if not args.project or n == args.project]

    if args.project and not profiles:
        print("no profile named %r under %s" % (args.project, lib.PROFILES))
        return 1

    for name, prof in profiles:
        has_hindsight = "hindsight-coding-agents" in prof.get("servers", [])
        # claude-mem-lite grants nothing in `servers` -- it is a plugin, and the profile
        # listing it IS the grant. Without this a lite-only project (the vault) was skipped
        # entirely and its checks never ran, which looked exactly like passing.
        has_lite = memory.LITE_PLUGIN in (prof.get("plugins_keep") or [])
        if not has_hindsight and not has_lite:
            if args.verbose:
                print("\n== %s ==" % name)
                note("no memory server granted")
            continue
        if not QUIET:
            print("\n== %s ==" % name)
        if has_hindsight:
            note("hindsight-coding-agents granted")
        if has_lite:
            check_project(name, prof)

    # ------------------------------------------------------------------ machine-wide checks
    if not QUIET:
        print("\n== machine ==")

    # An integration that is off in config/forge.json is not checked: its files are not written, so
    # their absence is not a finding. Said once, as the sync's NOT RUN, NOT ARMED lines say it.
    if lib.on("codex"):
        trusted = codex_trusted_hook_sources(CODEX_USER_CONFIG)
        if not trusted:  # normal: forge registers no Codex hook, so this is a line and not a warning
            check("machine", "codex-trust", True, "no hook trust records in %s (0 examined)" % CODEX_USER_CONFIG)
        for src in trusted:
            resolved = resolve_codex_hook_source(src)
            check("machine", "codex-trust", resolved is not None,
                  src if resolved is not None
                  else "%s — trusted but the manifest is gone, so the hook can never fire" % src)

        manifest = os.path.join(CODEX_HOME, "hooks.json")
        untrusted, examined, unreadable = codex_untrusted_hooks(CODEX_USER_CONFIG, manifest)
        if unreadable:
            check("machine", "codex-untrusted", False,
                  "hooks.json unreadable (%s), so Codex loads none of its hooks: %s"
                  % (short(manifest), unreadable))
        elif untrusted:
            warn("machine", "codex-untrusted",
                 "%d hook(s) registered with no trust record, so they do not fire until the next "
                 "Codex session approves them: %s" % (len(untrusted), "; ".join(untrusted)))
        else:
            check("machine", "codex-untrusted", True,
                  "every registered hook is trusted (%d examined)" % examined)
    else:
        note("codex checks -> NOT RUN, NOT ARMED: codex is off in config/forge.json")

    cfg = None
    if not lib.on("hindsight"):
        note("hindsight checks -> NOT RUN, NOT ARMED: hindsight is off in config/forge.json")
    else:
        try:
            cfg = lib.read_owned(HINDSIGHT_RENDERED, missing=None)
        except lib.Unreadable as e:
            check("machine", "hindsight-config", False, str(e))
        else:
            if cfg is None:
                check("machine", "hindsight-config", False, "missing " + HINDSIGHT_RENDERED)
    if cfg is not None:
        check("machine", "hindsight-config", bool(cfg.get("apiUrl")),
              cfg.get("apiUrl") or "no apiUrl")

        # Every distinct server the banks name, and the top-level one too: it serves the bank
        # `bankId` names (the personal bank), which has no banks entry of its own. Four projects now
        # depend on a daemon running on this laptop, and a daemon that is not running is the
        # quietest failure in the whole subsystem: capture posts into nothing and recall says
        # the bank is empty. This is a liveness probe -- /health, no bank, no query, no writes.
        urls = {}
        if cfg.get("apiUrl"):
            urls[cfg["apiUrl"].rstrip("/")] = [cfg.get("bankId") or "coding"]
        banks = cfg.get("banks")
        for bank, sec in (banks.items() if isinstance(banks, dict) else ()):
            if not isinstance(sec, dict) or sec.get("disabled") or not sec.get("apiUrl"):
                continue
            named = urls.setdefault(sec["apiUrl"].rstrip("/"), [])
            if bank not in named:
                named.append(bank)
        for url, banks in sorted(urls.items()):
            t0 = time.time()
            try:
                with urllib.request.urlopen(url + "/health", timeout=5) as r:
                    live, why = r.status == 200, "%d" % r.status
            except Exception as e:
                live, why = False, "%s: %s" % (type(e).__name__, str(e)[:60])
            check("machine", "hindsight-server", live,
                  "%s serves %s (%.2fs)" % (url, ", ".join(sorted(banks)), time.time() - t0)
                  if live else "%s does not answer /health — %s serves nothing until it does"
                                % (url, ", ".join(sorted(banks))) + " [%s]" % why)
        if args.bank:
            bank = cfg.get("bankId") or "coding"
            ok, n, secs, err = hindsight_recall(cfg, bank, "memory system configuration")
            check("machine", "hindsight-recall", ok and n > 0,
                  "%s in %.2fs" % (err or ("%d results" % n), secs))

    # A declared backlog entry that stopped failing is a stale declaration. Reporting it is
    # what stops config/memory-known-empty.json from outliving its reasons. Only meaningful
    # on a full sweep -- a --project run never visits the other entries.
    # --all deliberately routes every known entry through the FAIL path, so nothing is ever
    # recorded as still-failing and every entry would look stale. Skip the report there.
    stale_known = [] if (args.project or SHOW_ALL) \
        else sorted(set(known_map) - known_still_failing)

    if fails or warns or stale_known or (backlog and not QUIET):
        if QUIET:
            print("memory_doctor: %d unexpected failure(s), %d warning(s), "
                  "%d stale backlog entr(ies) — "
                  "python3 scripts/sync/memory_doctor.py for detail"
                  % (len(fails), len(warns), len(stale_known)))
        else:
            print()
        for f in fails:
            print("%sFAIL%s  %s" % (COLOR["FAIL"], OFF, f))
        for w in warns:
            print("%sWARN%s  %s" % (COLOR["WARN"], OFF, w))
        for k in stale_known:
            print("%sSTALE%s %s no longer fails — drop it from %s"
                  % (COLOR["WARN"], OFF, k, short(KNOWN)))
        if not QUIET:
            for b in backlog:
                print("%sKNOWN%s %s" % (COLOR["KNOWN"], OFF, b))

    if not QUIET:
        print("%d unexpected failure(s), %d warning(s), %d known."
              % (len(fails), len(warns), len(backlog)))

    # --hook always returns 0: a sick store must not stop a session from starting.
    # 0/1, not the count: an exit status is taken modulo 256, so 256 failures would read as 0.
    return 1 if fails and not QUIET else 0


if __name__ == "__main__":
    sys.exit(main())
