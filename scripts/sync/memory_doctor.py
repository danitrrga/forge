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
                    fire again, recorded as though it were healthy. No record at all is a warning
                    while `codex_harness` is true in config/forge.json (forge registers Codex
                    hooks, and Codex runs none until it trusts it) and normal while it is false
                    or absent (forge registers none).
  codex-untrusted   The mirror image: a hook registered in the manifest with NO trust record
                    never fires at all. A freshly written one is legitimately untrusted until
                    the next Codex session approves it, so this warns rather than fails -- but
                    one that stays untrusted is a hook doing nothing, silently. That holds
                    while `codex_harness` is true; with it false or absent forge registered
                    none of them, so they are another program's and a PASS line carries the
                    counts (untrusted, examined). A hooks.json that exists but does not
                    parse FAILs whatever `codex_harness` says: Codex loads none of its
                    hooks, and no next session fixes that.
  lite-*            A claude-mem-lite store: CLAUDE_MEM_DIR derived from the project name,
                    the directory present and writable, rows written, no session stuck
                    'active' (it breaks the next SessionStart), rows labelled for this
                    project, and the plugin actually enabled.
  hindsight-*       The rendered config names a server, and every server it names answers.

  mempalace-*       MemPalace, only while integrations.mempalace is on (off: one NOT RUN line). cli: `mempalace`
                    on the PATH at the version config/toolchain.json pins. hub: the registry's `mempalace` URL
                    answers /healthz and a search for text that is already in the palace finds it (/healthz said
                    "ok" while the embedding model was not answering; an empty palace has nothing to search
                    for, and the line says so). palace: its directory, resolved as
                    MemPalace's own config.py and paths.py do, has its database and the hub reports SQLite integrity ok
                    for that same palace. backup: the newest validated backup (its `.count` beside it) is under
                    BACKUP_MAX_H old. Per project that grants `mempalace`: rows (Stop, SessionEnd and PreCompact in
                    its settings.local.json) and, outside --hook, wing (the project's wing holds drawers, and a
                    WARN when none was filed in FRESH_DAYS days although a transcript of the project is that new).
  memory-one-backend  Always, whatever is switched on and also under --hook: each project has exactly one memory
                    backend (hindsight-coding-agents in `servers`, the claude-mem-lite plugin in `plugins_keep`, or
                    `mempalace` in `servers`). None or two is a FAIL naming the project; a project without memory on
                    purpose is declared in config/memory-known-empty.json as `<project>/memory-backend`; a project file
                    that could not be read is a FAIL, and so is looking at none. A checkout that uses no memory (no
                    memory integration on, no project granting a backend: a fresh install) is NOT RUN.

  --bank            The hindsight bank answers a real recall over the network.

claude-mem itself (thedotmack) was retired, and its per-store checks
(store-*, claude-env, codex-mcp, codex-hook-env, capture-agrees, --mcp) went with it. Its
stores were moved out of the checkout to ~/archive/forge-claude-mem.

THE KNOWN BACKLOG IS NOT NOISE. Some stores are empty today by history rather than by fault
(once, nine). A gate that prints the same nine failures at every session start trains the
reader to stop reading it -- the exact failure this tool exists to prevent. So known entries
live in config/memory-known-empty.json with a reason and a date, are silent in --hook mode,
and are listed separately in full output. A known entry that has STOPPED failing is itself
reported, so the backlog cannot quietly rot.

IT NEVER WRITES A MEMORY. hindsight_doctor.py learned this the hard way -- seventeen canary
probe sessions were retained as real documents and then outranked the user's own memories on
any similarly-worded query. Every check here is a read, a stat, or a handshake. The hub is asked only for the tools
of READ_TOOLS: hub_call raises on any other name, so a write cannot leave this process.

    python3 scripts/sync/memory_doctor.py
    python3 scripts/sync/memory_doctor.py --project forge --verbose
    python3 scripts/sync/memory_doctor.py --bank
    python3 scripts/sync/memory_doctor.py --all          # ignore the backlog, show everything

Exits 1 on any unexpected failure (the count is printed), 0 otherwise. Known-backlog entries
and warnings do not fail.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
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


# ------------------------------------------------------------------------------------ mempalace

BACKUPS = os.path.join(HOME, "backups", "mempalace")
BACKUP_MAX_H = 48          # nightly at 04:30: a day and a night missed
FRESH_DAYS = 14
CLAUDE_PROJECTS = os.path.join(HOME, ".claude", "projects")
MEMPALACE_PIN = "pipx:mempalace"
HUB_FIX = "systemctl --user enable --now mempalace-hub"
# The only hub tools this script may call. Everything else MemPalace serves writes or is not a read it was written for.
READ_TOOLS = ("mempalace_list_drawers", "mempalace_list_wings", "mempalace_search")
# The per-project rows forge writes (hooks/mempalace/*.sh, part 7.1 U2): event and the script its command runs.
HOOK_ROWS = (("Stop", "mempal-stop-hook.sh"), ("SessionEnd", "mempal-session-end-hook.sh"),
             ("PreCompact", "mempal-precompact-hook.sh"))


def hub_call(url: str, tool: str, args: dict, timeout: float = 30.0):
    """(the tool's answer as a dict, None) or (None, why not): one JSON-RPC `tools/call` over HTTP, the way Claude Code
    calls the hub (U1 (d), (h): no initialize first, no token on loopback). A tool outside READ_TOOLS raises ValueError
    before anything is sent."""
    if tool not in READ_TOOLS:
        raise ValueError("memory_doctor never calls %s: it is not one of the read tools %s" % (tool, ", ".join(READ_TOOLS)))
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, "HTTP %d" % e.code
    except Exception as e:                                    # noqa: BLE001 - report anything
        return None, "%s: %s" % (type(e).__name__, str(e)[:80])
    if not isinstance(doc, dict):
        return None, "the answer is not a JSON object"
    if "error" in doc:
        return None, "JSON-RPC error %s" % str(doc["error"])[:80]
    result = doc.get("result")
    content = result.get("content") if isinstance(result, dict) else None
    first = content[0] if isinstance(content, list) and content else None
    text = first.get("text") if isinstance(first, dict) else None
    if not isinstance(text, str):
        return None, "the answer carries no text content"
    if result.get("isError"):
        return None, "tool error: %s" % text[:80]
    try:
        value = json.loads(text)
    except ValueError:
        return None, "the tool's text is not JSON: %s" % text[:60]
    if not isinstance(value, dict):
        return None, "the tool's answer is a %s, not an object" % type(value).__name__
    if "error" in value:
        return None, "tool error: %s" % str(value["error"])[:80]
    return value, None


def http_get(url: str, timeout: float = 5.0):
    """(status, body, why not): status None when nothing answered."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return e.code, "", "HTTP %d" % e.code
    except Exception as e:                                    # noqa: BLE001 - report anything
        return None, "", "%s: %s" % (type(e).__name__, str(e)[:60])


class Hub:
    """The hub as the registry's `mempalace` entry names it: its /mcp URL, its base, why there is none, and (read once
    per run) the drawer count of each wing. Only the schemes http and https: urllib would open a file: URL."""

    def __init__(self):
        doc = lib.read_json(os.path.join(ROOT, "config", "mcp-registry.json"), quiet=True)
        servers = doc.get("servers") if isinstance(doc, dict) else None
        entry = servers.get("mempalace") if isinstance(servers, dict) else None
        self.url = self.base = None
        if not isinstance(entry, dict):
            self.why = "config/mcp-registry.json has no `mempalace` entry (or cannot be read), so there is no hub URL"
            return
        url = entry.get("url")
        parts = urllib.parse.urlsplit(url) if isinstance(url, str) else None
        if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
            self.why = "the registry's `mempalace` entry has no http(s) url (%r)" % (url,)
            return
        self.url, self.base, self.why = url, "%s://%s" % (parts.scheme, parts.netloc), None
        self._wings = None

    def wings(self):
        """({wing: drawers}, None) or (None, why not), asked once."""
        if self.url is None:
            return None, self.why
        if self._wings is None:
            value, err = hub_call(self.url, "mempalace_list_wings", {})
            found = value.get("wings") if value is not None else None
            if value is not None and not isinstance(found, dict):
                value, err = None, "no `wings` object in the answer"
            self._wings = (found if value is not None else None, "mempalace_list_wings failed: %s" % err if err else None)
        return self._wings


def wing_name(project_path: str) -> str:
    """The wing MemPalace files a session of this directory into: the directory's last name through
    mempalace/config.py normalize_wing_name (v3.12.0). A worktree under .claude/worktrees/ is already the project's path."""
    slug = os.path.basename(os.path.normpath(project_path)).lower().replace(" ", "_").replace("-", "_")
    slug = re.sub(r"[^\w.']+", "_", slug)
    slug = re.sub(r"\.{2,}", ".", slug)
    return slug[:120].strip("_.'")


def resolve_palace() -> tuple[str, str]:
    """(the palace directory, where that came from), as mempalace/config.py's palace_path and paths.config_dir resolve it at
    v3.12.0: MEMPALACE_PALACE_PATH, MEMPALACE_PALACE or MEMPAL_PALACE_PATH; else `palace_path` of config.json in the config
    directory; else <config directory>/palace. The config directory: $MEMPALACE_CONFIG_DIR; else ~/.mempalace when it holds an
    install; else $XDG_CONFIG_HOME/mempalace when that is absolute; else ~/.config/mempalace."""
    for var in ("MEMPALACE_PALACE_PATH", "MEMPALACE_PALACE", "MEMPAL_PALACE_PATH"):
        if os.environ.get(var):
            return os.path.abspath(os.path.expanduser(os.environ[var])), "$" + var
    legacy = os.path.join(HOME, ".mempalace")
    xdg = os.path.expanduser(os.environ.get("XDG_CONFIG_HOME") or "")
    if (os.environ.get("MEMPALACE_CONFIG_DIR") or "").strip():
        cfg = os.path.expanduser(os.environ["MEMPALACE_CONFIG_DIR"])
    elif os.path.isdir(legacy) and any(os.path.isfile(os.path.join(legacy, f)) for f in
                                       ("config.json", "people_map.json", os.path.join("palace", "chroma.sqlite3"))):
        cfg = legacy
    elif xdg.strip() and os.path.isabs(xdg):
        cfg = os.path.join(xdg, "mempalace")
    else:
        cfg = os.path.join(HOME, ".config", "mempalace")
    try:
        with open(os.path.join(cfg, "config.json"), encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict) and "palace_path" in doc:
        return os.path.expanduser(str(doc["palace_path"])), "palace_path in %s" % os.path.join(cfg, "config.json")
    return os.path.join(cfg, "palace"), "the default under %s" % cfg


def check_mempalace_cli() -> None:
    name = "mempalace-cli"
    exe = shutil.which("mempalace")
    if not exe:
        return void(check("machine", name, False, "mempalace not on PATH: forge toolchain --fix, then a new shell"))
    from forge import toolchain      # here, not at the top: the toy checkouts of other suites copy this script without it
    entries, why = toolchain.entries()
    pins = [e for e in entries.get("tools", []) if e["name"] == MEMPALACE_PIN]
    if not pins:
        return void(check("machine", name, False, "config/toolchain.json has no %s entry, so there is no version to compare%s"
                          % (MEMPALACE_PIN, " (%s)" % why if why else "")))
    pinned = pins[0]["version"]
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return void(check("machine", name, False, "%s --version failed: %s" % (exe, type(e).__name__)))
    found = re.search(r"\d+\.\d+\.\d+\S*", r.stdout)
    if r.returncode != 0 or not found:
        return void(check("machine", name, False, "%s --version gave exit %d and %r" % (exe, r.returncode, r.stdout.strip()[:60])))
    check("machine", name, found.group(0) == pinned,
          "%s at %s (config/toolchain.json pins %s)" % (exe, found.group(0), pinned) if found.group(0) == pinned
          else "installed %s, config/toolchain.json pins %s: forge toolchain --fix" % (found.group(0), pinned))


def void(_):
    """For `return void(check(...))`: leave a function after its one verdict."""
    return None


def check_mempalace_hub(hub: Hub) -> None:
    name = "mempalace-hub"
    if hub.url is None:
        return void(check("machine", name, False, hub.why))
    t0 = time.time()
    status, _, err = http_get(hub.base + "/healthz")
    if status != 200:
        return void(check("machine", name, False, "%s/healthz does not answer 200 (%s) -- %s" % (hub.base, err or status, HUB_FIX)))
    secs = time.time() - t0
    # /healthz said "ok" while the embedding model was not answering (measured on Hindsight: its health check passed with a dead model),
    # so a search for text that is already in the palace is the proof, and it is the palace's own text, not a canary.
    listed, err = hub_call(hub.url, "mempalace_list_drawers", {"limit": 1})
    if err:
        return void(check("machine", name, False, "%s answers /healthz but reading a drawer failed: %s" % (hub.base, err)))
    total, drawers = listed.get("total"), listed.get("drawers")
    if not isinstance(total, int) or isinstance(total, bool):
        return void(check("machine", name, False, "mempalace_list_drawers gave no drawer count"))
    if total == 0:
        return void(check("machine", name, True, "%s /healthz 200 (%.2fs); the palace holds 0 drawers, so no search was run: "
                          "there is nothing in it to look for" % (hub.base, secs)))
    first = drawers[0] if isinstance(drawers, list) and drawers and isinstance(drawers[0], dict) else {}
    preview = first.get("content_preview")
    query = re.sub(r"\.\.\.$", "", preview.strip()).strip()[:200] if isinstance(preview, str) else ""
    if not query:
        return void(check("machine", name, False, "the palace holds %d drawers but mempalace_list_drawers gave no text to search for" % total))
    found, err = hub_call(hub.url, "mempalace_search", {"query": query, "limit": 3})
    results = found.get("results") if found is not None else None
    if err or not isinstance(results, list) or not results:
        return void(check("machine", name, False, "%s answers /healthz but a search for the text of an existing drawer %s: "
                          "the embedding model may not be answering" % (hub.base, "failed (%s)" % err if err else "found nothing")))
    check("machine", name, True, "%s /healthz 200 (%.2fs); a search for the text of an existing drawer (%d chars) found %d "
          "result(s); the palace holds %d drawers" % (hub.base, secs, len(query), len(results), total))


def check_mempalace_palace(hub: Hub) -> None:
    name = "mempalace-palace"
    path, how = resolve_palace()
    db = os.path.join(path, "chroma.sqlite3")
    try:
        size = os.path.getsize(db) if os.path.isfile(db) else 0
    except OSError:
        size = 0
    if not os.path.isdir(path):
        check("machine", name, False, "no palace directory at %s (%s)" % (path, how))
    elif not size:
        check("machine", name, False, "no chroma.sqlite3 in %s (%s), or it is empty" % (path, how))
    else:
        check("machine", name, True, "%s (%s) holds chroma.sqlite3, %d bytes" % (path, how, size))
    if hub.url is None:
        return void(check("machine", name, False, "SQLite integrity not read: " + hub.why))
    status, body, err = http_get(hub.base + "/statusz")
    if status != 200:
        return void(check("machine", name, False, "%s/statusz does not answer 200 (%s)" % (hub.base, err or status)))
    try:
        doc = json.loads(body)
    except ValueError:
        doc = None
    integ = ((doc or {}).get("palace") or {}).get("sqlite_integrity") if isinstance(doc, dict) and isinstance(doc.get("palace"), dict) else None
    if not isinstance(integ, dict):
        return void(check("machine", name, False, "/statusz carries no palace.sqlite_integrity block"))
    errors = integ.get("errors") if isinstance(integ.get("errors"), list) else []
    if integ.get("checked") is not True:
        check("machine", name, False, "SQLite integrity was not checked by the hub (checked is %r)" % integ.get("checked"))
    elif integ.get("ok") is not True:
        n = integ.get("error_count") if isinstance(integ.get("error_count"), int) else len(errors)
        check("machine", name, False, "SQLite integrity not ok: %d error(s)%s" % (n, ", first: %s" % str(errors[0])[:80] if errors else ""))
    elif isinstance(integ.get("palace"), str) and os.path.realpath(integ["palace"]) != os.path.realpath(path):
        check("machine", name, False, "the hub serves %s but this doctor resolves %s (%s): the check above looked at another palace"
              % (integ["palace"], path, how))
    else:
        check("machine", name, True, "SQLite integrity ok (0 errors, hub serves %s)" % path)


def check_mempalace_backup() -> None:
    # Same rule as hindsight_doctor.py's backup row: only an archive with its .count beside it counts (the backup script
    # writes the .count after its validator accepts the archive and renames a rejected one *.rejected), the age is the
    # archive's mtime, and the archive is never opened.
    name = "mempalace-backup"
    try:
        names = os.listdir(BACKUPS)
    except OSError:
        names = []
    validated = []
    for n in names:
        arch = os.path.join(BACKUPS, n)
        try:
            if n.startswith("mempalace-") and n.endswith(".tar.zst") and os.path.isfile(arch + ".count"):
                validated.append((os.stat(arch).st_mtime, n))
        except OSError:
            pass                                             # rotated away between the listing and the stat
    if not validated:
        return void(check("machine", name, False, "no validated backup in %s (an archive with its .count) -- is mempalace-backup.timer "
                          "installed?" % short(BACKUPS)))
    mtime, newest = max(validated)
    age_h = (time.time() - mtime) / 3600.0
    check("machine", name, age_h < BACKUP_MAX_H, "newest validated backup is %.1f h old (%s; nightly 04:30, threshold %d h)"
          % (age_h, newest, BACKUP_MAX_H))


def check_mempalace_rows(name: str, ppath: str) -> None:
    try:
        doc = lib.read_owned(os.path.join(ppath, ".claude", "settings.local.json"))
    except lib.Unreadable as e:
        return void(check(name, "mempalace-rows", False, str(e)))
    entries, bad = lib.hook_entries(doc)
    if bad:
        return void(check(name, "mempalace-rows", False, "settings.local.json hooks are of the wrong shape (%d malformed entr%s), "
                          "so the rows cannot be counted" % (bad, "y" if bad == 1 else "ies")))
    missing = [event for event, script in HOOK_ROWS
               if not any(e == event and isinstance(h.get("command"), str) and script in h["command"] for e, _, _, h in entries)]
    check(name, "mempalace-rows", not missing, "%d of %d rows present (%s)" % (len(HOOK_ROWS) - len(missing), len(HOOK_ROWS),
          ", ".join(e for e, _ in HOOK_ROWS)) if not missing else "%d of %d rows present, missing: %s"
          % (len(HOOK_ROWS) - len(missing), len(HOOK_ROWS), ", ".join(missing)))


def newest_transcript_age_days(ppath: str):
    """Days since the newest transcript of this project, or None. Claude Code keeps them in ~/.claude/projects/<the path with
    every non-alphanumeric as '-'>; a worktree under .claude/worktrees/ or .worktrees/ has a directory of its own that
    MemPalace files into the project's wing, so it counts too. A sibling whose name merely starts the same does not."""
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(ppath))
    try:
        dirs = [d for d in os.listdir(CLAUDE_PROJECTS)
                if d == enc or d.startswith(enc + "--claude-worktrees-") or d.startswith(enc + "--worktrees-")]
    except OSError:
        return None
    newest = None
    for d in dirs:
        try:
            for f in os.listdir(os.path.join(CLAUDE_PROJECTS, d)):
                if f.endswith(".jsonl"):
                    m = os.stat(os.path.join(CLAUDE_PROJECTS, d, f)).st_mtime
                    newest = m if newest is None else max(newest, m)
        except OSError:
            pass
    return None if newest is None else (time.time() - newest) / 86400.0


def check_mempalace_wing(name: str, ppath: str, hub: Hub) -> None:
    wing = wing_name(ppath)
    wings, err = hub.wings()
    if wings is None:
        return void(check(name, "mempalace-wing", False, "wing %s not read from the hub: %s" % (wing, err)))
    count = wings.get(wing)
    count = count if isinstance(count, int) and not isinstance(count, bool) else 0
    if not check(name, "mempalace-wing", count > 0, "wing %s has %d drawers" % (wing, count) if count
                 else "wing %s has 0 drawers (the hub's wings: %s) -- granted but nothing was ever captured"
                      % (wing, ", ".join(sorted(wings)) or "none")):
        return
    # The date of a wing's newest drawer is no call of the hub (U1 (h)); `since` on a list of the wing's drawers answers whether
    # any was filed in the window. `filed_at` is the time of the filing, so this is "was anything captured lately".
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=FRESH_DAYS)).isoformat(timespec="seconds")
    recent, err = hub_call(hub.url, "mempalace_list_drawers", {"wing": wing, "since": since, "limit": 1})
    total = recent.get("total") if recent is not None else None
    if not isinstance(total, int) or isinstance(total, bool):
        return void(warn(name, "mempalace-wing", "freshness of wing %s unknown: %s" % (wing, err or "no drawer count in the answer")))
    if total:
        return
    age = newest_transcript_age_days(ppath)
    if age is not None and age <= FRESH_DAYS:
        warn(name, "mempalace-wing", "no drawer of wing %s was filed in the last %d days, but a transcript of this project is "
             "%.1f days old: its work was not captured" % (wing, FRESH_DAYS, age))


def backends_of(prof: dict) -> list[str]:
    """The memory backends a project file grants, in a fixed order."""
    out = []
    if "hindsight-coding-agents" in prof.get("servers", []):
        out.append("hindsight-coding-agents")
    if memory.LITE_PLUGIN in (prof.get("plugins_keep") or []):
        out.append("claude-mem-lite")
    if "mempalace" in prof.get("servers", []):
        out.append("mempalace")
    return out


def check_one_backend(projects: list, unreadable: list, armed: bool) -> None:
    """Each project has exactly one memory backend (docs/AGENT-SYSTEM.md: "one per project, never both"). Only a project that
    breaks it prints a line; the row that always prints says how many were looked at. A project file that could not be read is
    a FAIL (its backend was not looked at), and so is looking at none of them.

    `armed`: whether this checkout uses memory at all (the hindsight or mempalace integration is on, or some project grants a
    backend). A stranger's fresh checkout has one starter project with none and no memory switched on, `forge init` runs this
    doctor on it and it must pass: that is NOT RUN, NOT ARMED, not a FAIL. Once anything is armed, a project without a backend
    is one that lost its memory."""
    if not armed:
        return note("memory-one-backend -> NOT RUN, NOT ARMED: no memory integration is on in config/forge.json and no project "
                    "grants a backend, so there is nothing to look at")
    good = 0
    for name, prof in projects:
        got = backends_of(prof)
        if len(got) == 1:
            good += 1
        elif not got:
            check(name, "memory-backend", False, "%s has no memory backend (hindsight-coding-agents or mempalace in `servers`, "
                  "claude-mem-lite in `plugins_keep`): grant one, or declare it in config/memory-known-empty.json as %s/memory-backend"
                  % (name, name))
        else:
            check(name, "memory-backend", False, "%s has %d memory backends: %s -- one per project, never both" % (name, len(got), ", ".join(got)))
    detail = ("%d project(s) examined, %d with exactly one backend" % (len(projects), good)) if projects \
        else "0 project(s) examined: a check that saw nothing is not a pass"
    if unreadable:
        detail += "; %d project file(s) could not be read: %s" % (len(unreadable), ", ".join(n for n, _ in unreadable))
    check("machine", "memory-one-backend", bool(projects) and not unreadable, detail)


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
    # against: the project opting in IS the grant, and the only outside input is where the
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
    ap.add_argument("--project", help="check only this project")
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

    # Through lib, like every other project reader: a project that is not an object or carries a
    # field of the wrong type is skipped instead of raising AttributeError here (`[1]`) or being
    # substring-matched (`"servers": "hindsight-coding-agents"`). Skipped silently, as the
    # unreadable ones always were: session start and verify_skill_refs already name them, and
    # --hook must print nothing.
    skipped_files: list = []
    every_project = lib.projects(skipped_files)
    projects = [(n, p) for n, p in every_project.items() if not args.project or n == args.project]

    if args.project and not projects:
        print("no project named %r under %s" % (args.project, lib.PROJECTS))
        return 1

    hub = Hub() if lib.on("mempalace") else None
    for name, prof in projects:
        has_hindsight = "hindsight-coding-agents" in prof.get("servers", [])
        # claude-mem-lite grants nothing in `servers` -- it is a plugin, and the project
        # listing it IS the grant. Without this a lite-only project (the vault) was skipped
        # entirely and its checks never ran, which looked exactly like passing.
        has_lite = memory.LITE_PLUGIN in (prof.get("plugins_keep") or [])
        has_mempalace = "mempalace" in prof.get("servers", [])
        if not has_hindsight and not has_lite and not has_mempalace:
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
        if has_mempalace:
            note("mempalace granted")
            if hub is not None:
                check_mempalace_rows(name, prof.get("project_path", ""))
                if not QUIET:      # the wing is read through the hub: not on the session-start path
                    check_mempalace_wing(name, prof.get("project_path", ""), hub)

    # Whatever is switched on, and under --hook too: a profile with no memory or with two is wrong in every mode.
    if not QUIET:
        print("\n== memory backends ==")
    check_one_backend(projects, [] if args.project else skipped_files,
                      lib.on("hindsight") or lib.on("mempalace") or any(backends_of(p) for p in every_project.values()))

    # ------------------------------------------------------------------ machine-wide checks
    if not QUIET:
        print("\n== machine ==")

    # An integration that is off in config/forge.json is not checked: its files are not written, so
    # their absence is not a finding. Said once, as the sync's NOT RUN, NOT ARMED lines say it.
    if lib.on("codex"):
        trusted = codex_trusted_hook_sources(CODEX_USER_CONFIG)
        if not trusted:
            if lib.codex_harness():  # forge registers Codex hooks, and none is trusted yet
                warn("machine", "codex-trust", "no hook trust records in " + CODEX_USER_CONFIG)
            else:  # normal: forge registers no Codex hook, so this is a line and not a warning
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
        elif untrusted and lib.codex_harness():  # forge registered them, and none fires until trusted
            warn("machine", "codex-untrusted",
                 "%d hook(s) registered with no trust record, so they do not fire until the next "
                 "Codex session approves them: %s" % (len(untrusted), "; ".join(untrusted)))
        elif untrusted:  # normal: forge registers no Codex hook, so these are another program's
            check("machine", "codex-untrusted", True,
                  "%d hook(s) registered with no trust record, none of them forge's with codex_harness off "
                  "(%d examined): %s" % (len(untrusted), examined, "; ".join(untrusted)))
        else:
            check("machine", "codex-untrusted", True,
                  "every registered hook is trusted (%d examined)" % examined)
    else:
        note("codex checks -> NOT RUN, NOT ARMED: codex is off in config/forge.json")

    if hub is None:
        note("mempalace checks -> NOT RUN, NOT ARMED: mempalace is off in config/forge.json")
    else:
        check_mempalace_cli()
        check_mempalace_hub(hub)
        check_mempalace_palace(hub)
        check_mempalace_backup()

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
