"""MCP servers: the registry's definitions with their secrets resolved, as each project receives
them in ~/.claude.json (ClaudeJson) and <project>/.codex/config.toml (write_codex_project_mcp).

A `${VAR}` in the registry (tracked in git) names a key of credentials/secrets.json (git-ignored),
the only place a real token lives; this module is where one becomes the other. ~/.claude.json is
one document every profile writes into and every open Claude Code session writes too, so it is
opened once, changed in memory profile by profile, and committed once at the end."""
import copy
import os
import re
import tomllib

from forge import lib, owned

VARRE = re.compile(r"^\$\{(\w+)\}$")


def resolve_secrets(env, secrets, errors, server, block="env"):
    out = {}
    for k, v in (env or {}).items():
        if isinstance(v, str):
            m = VARRE.match(v)
            if m:
                var = m.group(1)
                val = secrets.get(var, "")
                if val == "" or val is None:
                    errors.append("server '%s' %s %s -> secret %s is EMPTY/missing" % (server, block, k, var))
                    continue
                out[k] = val
                continue
        out[k] = v
    return out


def migrate_project_keys(cj, relocations):
    """Move explicitly registered old project keys before profile generation.

    The generator deliberately preserves unrelated Claude project entries, so repository
    relocations need an explicit canonical migration rather than broad orphan pruning.
    """
    projects = cj.setdefault("projects", {})
    changed = []
    for item in relocations:
        old, new = item.get("from"), item.get("to")
        if not old or not new:
            continue
        # Both ends in the key form, or a trailing slash misses the key or moves it onto itself.
        old, new = project_key(old), project_key(new)
        if old == new or old not in projects:
            continue
        old_state = projects.pop(old)
        if new not in projects:
            projects[new] = old_state
        else:
            merge_project_entry(projects[new], old_state)
        changed.append((old, new))
    return changed


def record_claims(file, claims, apply, part=None):
    """owned.record, but a run that would record what the registry already holds writes nothing. owned.record
    moves the part it replaces to the end of the file's claims, so with several parts in one file (~/.claude.json
    holds one per project) each record would leave the registry in another order than the next, and a run that
    changed nothing would write it twice. Equal means the same (kind, at, sum, owner) in the same order."""
    if not apply:
        return False
    key = lambda c: (c["kind"], c["at"], c["sum"], c["owner"])
    prev, _ = owned.previous(file, part)
    if [key(c) for c in prev] == [key(c) for c in claims]:
        return False
    return owned.record(file, claims, apply, part)


def _ignore_site(ppath, entry, repo_owned):
    """(the file ensure_ignored puts `entry` in, the line it writes there), or None when it cannot be said. A
    project the repo owns gets the repository's info/exclude and the line anchored to the project's
    directory (lib._exclude_entry); any other gets its .gitignore and `entry` as it is."""
    if not repo_owned:
        return os.path.join(ppath, ".gitignore"), entry
    common = lib._git_out(ppath, "rev-parse", "--path-format=absolute", "--git-common-dir")
    prefix = lib._git_out(ppath, "rev-parse", "--show-prefix")
    if not common or prefix is None:
        return None
    return os.path.join(common, "info", "exclude"), "/" + prefix + entry


def _holds_line(file, line):
    """Whether `file` has `line` as a line, with or without a trailing slash (ignore rules read both as one)."""
    try:
        with open(file, encoding="utf-8") as fh:
            return any(l.strip() in (line, line.rstrip("/")) for l in fh.read().splitlines())
    except (OSError, UnicodeDecodeError):
        return False


def claim_ignore_line(apply, ppath, entry, suffix, repo_owned, part, owner):
    """Claim the ignore line lib.ensure_ignored(apply, ppath, entry, repo_owned) has just ensured, whose
    summary suffix is `suffix`, as the item ["line", <the line>] of the file that holds it, under `part`.
    Only a line forge added is claimed: the suffix says "+gitignore" or "+exclude" when it did. A line that was
    there before is not, and one claimed on an earlier run stays claimed while it is still in the file. The
    claims of the same part for any other line are kept where they are: an `.agents/` line is another
    writer's. Nothing for a dry-run (the suffix then says "would add")."""
    if not apply:
        return False
    site = _ignore_site(ppath, entry, repo_owned)
    if site is None:
        return False
    file, line = site
    mine = ["line", line]
    added = suffix.startswith(" +exclude" if repo_owned else " +gitignore")
    prev, _ = owned.previous(file, part)
    out, seen = [], False
    for c in prev:
        if c["kind"] == "item" and c["at"] == mine:
            seen = True
            if added or _holds_line(file, line):
                out.append(owned.claim("item", mine, line, owner))
        else:
            out.append(c)
    if added and not seen:
        out.append(owned.claim("item", mine, line, owner))
    return record_claims(file, out, apply, part)


def project_key(path):
    """A project's ~/.claude.json key: the forward-slash, normalised path, case kept -- the form
    Claude Code itself writes. A profile's `/x/proj/` used to become the key as written, which
    turned Claude Code's own `/x/proj` into the "duplicate" and deleted it every session."""
    return os.path.normpath(path).replace("\\", "/")


def merge_project_entry(dst, src):
    """Fold a project entry that is going away into the one that stays: the survivor's values win,
    and every key only the other has (trust, allowedTools, disabledMcpServers, history...) is
    kept. It once carried over only mcpServers."""
    ms = dst.setdefault("mcpServers", {})
    for name, definition in (src.get("mcpServers") or {}).items():
        ms.setdefault(name, definition)
    for k, v in src.items():
        dst.setdefault(k, v)


def resolved_server(name, regdef, secrets, errors):
    # A top-level key starting with '_' is a note in the registry (`_doc`, `_deny_tools_doc`,
    # `_headers_present`), never configuration: none of them is written to a generated file.
    d = {k: copy.deepcopy(v) for k, v in regdef.items() if not str(k).startswith("_")}
    d.pop("deny_tools", None)
    # `headers` is resolved exactly like `env`. It was once not resolved at all --
    # the only mention of headers in this file was the no-op pop above -- so a "${VAR}" inside a
    # headers block was written into the generated config verbatim and shipped to the server as a
    # literal dollar-brace string. A type:http MCP server that authenticates by header (the first
    # was `openviking`, since retired) needed the same secrets indirection type:stdio servers already get through
    # env, and putting the credential straight into mcp-registry.json is not an option: that file
    # is tracked in git and secrets live in credentials/secrets.json.
    for block in ("env", "headers"):
        if block in d:
            d[block] = resolve_secrets(d[block], secrets, errors, name, block)
            if not d[block]:
                d.pop(block)
    return d


def with_denied_tools(prof, sel, registry):
    """The profile plus a permissions.deny row for every `deny_tools` entry of a server it grants.

    Declared on the registry entry, not per profile, so a new project granted the server cannot
    miss it. Codex gets the same list as `disabled_tools` in write_codex_project_mcp."""
    deny = ["mcp__%s__%s" % (s, t) for s in sel
            for t in (registry.get(s) or {}).get("deny_tools") or []]
    if not deny:
        return prof
    prof = copy.deepcopy(prof)
    perms = prof.setdefault("permissions", {})
    perms["deny"] = list(dict.fromkeys((perms.get("deny") or []) + deny))
    return prof


def loose_files(paths):
    """The `paths` that are regular files group or others can read: the secret-bearing files whose
    mode a run corrects even when their content is current. A symlink is never one -- os.chmod
    follows it to someone else's file -- and only the mode is looked at, never the content.
    Shared by .codex/config.toml, its .bak, and, through loose_secrets, the .bak of ~/.claude.json
    and of the Hindsight config."""
    return [p for p in paths if os.path.isfile(p) and not os.path.islink(p) and os.stat(p).st_mode & 0o077]


def loose_secrets(path):
    """`path` and its once-ever .bak, those whose mode a run must correct to 600: ~/.claude.json and
    ~/.hindsight/coding-agent.json, both carrying resolved secrets.

    The file itself must be exactly 600, and the check follows a link by design, so a 0400 file is
    corrected too. The .bak is checked where lib.write_text keeps it, beside the resolved file, and
    never through a link (loose_files): a .bak beside the link itself is one write_text never makes."""
    loose = [path] if os.path.exists(path) and (os.stat(path).st_mode & 0o777) != 0o600 else []
    return loose + loose_files([os.path.realpath(path) + ".bak"])


def diff_keys(old, new):
    o, n = set(old), set(new)
    add = sorted(n - o); rem = sorted(o - n)
    return add, rem


_TOML_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def toml_str(v):
    """TOML basic-string literal. FIXED (adversarial haiku testing caught this):
    the original version escaped only backslash and double-quote -- a secret or env value
    containing a literal newline, CR, tab, or other control character produced a raw control
    character inside a TOML basic string, which is illegal per the TOML spec and made
    tomllib refuse to parse the file (or worse, a crafted `\\n[mcp_servers.evil]` -style
    value could inject a bogus TOML section, since an unescaped newline ends the logical
    line the string was supposed to contain it on). Every character below 0x20 and 0x7f
    (DEL) now gets escaped, not just the two ASCII-art-obvious ones.

    TOML quoted keys use the exact same escaping as basic strings, so this is also the form of
    EVERY key this generator emits (server names in table headers, env var names) -- not just
    ones that "need" it -- because unconditional quoting is always valid TOML and removes a whole
    class of bugs a bare key would otherwise allow: a name containing `.` silently creating a
    NESTED table instead of the flat key intended, one containing `=` breaking `key = value`
    parsing outright, whitespace, `#` starting a comment mid-line, etc. Found by adversarial
    testing (registry entries are repo-controlled today, but there was no defense if
    that ever changed, or if a typo slipped a stray character into a name)."""
    out = []
    for ch in str(v):
        if ch in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _mcporter_config():
    """The MCPORTER_CONFIG value forge puts in a project's Codex env, `~` expanded as sync_skill_keep.py
    expands it, or None when config/forge.json's skill_keep.common_env has none."""
    keep = lib.settings().get("skill_keep")
    common_env = keep.get("common_env") if isinstance(keep, dict) else None
    mcporter = common_env.get("MCPORTER_CONFIG") if isinstance(common_env, dict) else None
    return os.path.expanduser(mcporter) if isinstance(mcporter, str) else None


def write_codex_project_mcp(ctx, prof, sel, registry, secrets, errors):
    """Mirror a project's resolved MCP server set (the SAME `sel` list already written to
    that project's ~/.claude.json entry) into <project>/.codex/config.toml, so a Codex CLI
    session opened in that directory gets the same tools -- part of the push for
    provider independence.

    EVERY managed project gets a .codex/config.toml (extended from the original
    handful of projects, which already had a hand-created .codex/ dir that predated
    the split of this config out of its first home -- every one of them still
    pointed CLAUDE_MEM_DATA_DIR and the
    claude-mem launcher at paths that no longer exist, so the claude-mem MCP server in
    Codex was silently dead in all of them before this generator existed). Creating the directory
    is safe: it holds only this generated file plus whatever `codex` itself caches there, same
    footprint as `.claude/`. Before writing anything into a NEW .codex/ dir, this ensures the
    project's .gitignore blocks it -- these files carry real secrets (one project's `.codex/`
    held a live FIRECRAWL_API_KEY, untracked but one `git add -A` from leaking, found and
    fixed), so a repo must never get one without the matching ignore line landing
    first.

    FORMAT LIMIT (confirmed against `codex mcp add --help`): Codex's http MCP
    entries take only `url` and an optional single `bearer_token_env_var` -- there is no
    field for arbitrary custom headers. The one registry server that needed several (the retired
    `openviking` entry: x-api-key + 3 identity headers) could not be expressed this way, and no
    registry server has a `headers` block today. The skip is a guard for a future one: a server
    with an unexpressable `headers` block is skipped with a loud warning rather than silently
    dropped or wrongly emitted.

    Whole-file rewrite (not a merge): every existing .codex/config.toml on this machine
    contains ONLY the two sections written here, so there is nothing else to preserve --
    same "fully generated, never hand-edited" contract as settings.local.json.

    Only called while config/forge.json's `codex_harness` is true (Codex configured like Claude Code,
    lib.codex_harness); with it false forge writes no MCP server for Codex and drop_codex_project_mcp
    takes out the ones it wrote. Returns a one-line summary."""
    ppath = prof["project_path"]
    if not os.path.isdir(ppath):
        errors.append("codex mcp: project_path does not exist on disk: %s" % ppath)
        return None
    codex_dir = os.path.join(ppath, ".codex")
    path = os.path.join(codex_dir, "config.toml")
    short = lib.short(path)
    # lib.write_text replaces a link's target, so a planted .codex/config.toml link, or a
    # .codex that is one (a `.codex/` ignore line does not match a link), would send the resolved
    # secrets wherever it points, a tracked file included.
    where = os.path.realpath(path)
    if where != os.path.join(os.path.realpath(ppath), ".codex", "config.toml"):
        return "   ! codex mcp -> %s NOT written: it resolves to %s" % (short, lib.short(where))
    repo_owned = lib.repo_owns_tracked_files(prof)
    ignored, gi_line = lib.ensure_ignored(ctx.apply, ppath, ".codex/", repo_owned)
    claim_ignore_line(ctx.apply, ppath, ".codex/", gi_line, repo_owned, "codex", "codex")
    if not ignored:
        # It carries resolved secrets: never written where git would pick it up.
        return "   ! codex mcp -> %s NOT written%s" % (short, gi_line)

    lines = ["[shell_environment_policy]", 'inherit = "core"', ""]
    env_set = dict(prof.get("env") or {})
    # A ${NAME} value is the secret, as in settings.local.json (skills.write_settings_local, which also
    # says when it is missing); this file is 0600 and git-ignored like it, so never the literal text.
    refs = {k: v for k, v in env_set.items() if isinstance(v, str) and VARRE.match(v)}
    got = resolve_secrets(refs, secrets, [], "")
    env_set = {k: got.get(k, v) for k, v in env_set.items() if k not in refs or k in got}
    # The same value as sync_skill_keep.py's common_env, which every profile it manages already
    # carries; this reaches the ones it does not. Read from config/forge.json's
    # skill_keep.common_env, not imported from that script (it decides APPLY from sys.argv at
    # import time, which would print its refusal into this run's output); a file without the key
    # writes nothing. `~` expands as sync_skill_keep.py expands it.
    mcporter = _mcporter_config()
    if mcporter is not None:
        env_set.setdefault("MCPORTER_CONFIG", mcporter)
    if env_set:
        lines.append("[shell_environment_policy.set]")
        for k, v in sorted(env_set.items()):
            lines.append("%s = %s" % (toml_str(k), toml_str(v)))
        lines.append("")

    skipped = []
    seen = set()
    for name in sel:
        # Dedupe: a profile's servers list is hand-authored JSON and could, in principle,
        # repeat a name -- two identical `[mcp_servers.X]` table headers is a TOML "duplicate
        # key" DecodeError. Silently keep the first occurrence rather than emit invalid TOML.
        if name in seen:
            continue
        seen.add(name)
        regdef = registry.get(name)
        if not isinstance(regdef, dict):
            if regdef is not None:
                errors.append("codex mcp: registry entry '%s' is not an object (%r) -- skipped"
                              % (name, type(regdef).__name__))
            continue
        d = resolved_server(name, regdef, secrets, errors)
        if d.get("headers"):
            skipped.append(name)
            continue
        lines.append("[mcp_servers.%s]" % toml_str(name))
        if "url" in d:
            lines.append("url = %s" % toml_str(d["url"]))
        else:
            lines.append("command = %s" % toml_str(d.get("command", "")))
            args = d.get("args") or []
            if args:
                lines.append("args = [%s]" % ", ".join(toml_str(a) for a in args))
        denied = regdef.get("deny_tools") or []
        if denied:
            lines.append("disabled_tools = [%s]" % ", ".join(toml_str(t) for t in denied))
        lines.append("")
        env = d.get("env") or {}
        if env:
            lines.append("[mcp_servers.%s.env]" % toml_str(name))
            for k, v in sorted(env.items()):
                lines.append("%s = %s" % (toml_str(k), toml_str(v)))
            lines.append("")

    content = "\n".join(lines).rstrip() + "\n"

    # Validate the TOML we just built BEFORE it ever touches disk -- same principle as
    # lib.write_json's json.loads() round-trip check. Every escaping fix above should make
    # this always pass now, but this is the last line of defense: if some future registry
    # shape slips past the escaping logic, the project's Codex config is left UNCHANGED
    # (the file on disk preserved / nothing written) and a loud error surfaces instead of a
    # corrupt file Codex would silently fail to parse. Found necessary by adversarial
    # testing.
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        errors.append("codex mcp: generated TOML for %s failed to parse (%s) -- NOT written"
                      % (ppath, e))
        return None

    # Byte-exact, and a file that is not UTF-8 is simply not `content`: read here with universal
    # newlines, a CRLF copy was "(already current)" forever, and one holding b'\xff' raised
    # UnicodeDecodeError, which took every later profile, ~/.claude.json and the user scope.
    existed = os.path.exists(path)
    changed = not lib.holds(path, content)
    # Mode is part of the contract, as for the hindsight config: the file and its once-ever .bak
    # hold the resolved secrets, and round 2 found both 644 in every project (the writer
    # was called without a mode). A loose one is corrected even when the content is current.
    loose = [os.path.basename(p) for p in loose_files((path, path + ".bak"))]
    msg = "   codex mcp -> %s (%d servers%s)%s" % (
        short, len(sel) - len(skipped),
        ", skipped %s: unexpressable headers" % skipped if skipped else "",
        gi_line)
    if ctx.apply and (changed or loose):
        lib.write_text(path, content, mode=0o600, backup=True)
    if ctx.apply:  # the file holds `content` now, whoever wrote it last: only its hash is kept
        record_claims(path, [owned.claim("file", [], content, "codex")], True, part="codex")
    if ctx.apply and (changed or loose):
        if not changed:
            return msg + " (content current, chmod 600 %s)" % ", ".join(loose)
        return msg + (" (updated)" if existed else " (created)")
    if not changed:
        return msg + (" (would chmod 600 %s)" % ", ".join(loose) if loose else " (already current)")
    return msg + (" (would update)" if existed else " (would create)")


def _toml_header_path(line):
    """The key path of a TOML table header line (`[a."b".c]`, `[[a.b]]`) as a list, or None when the line
    is not one. The line is parsed by tomllib itself, so quoting and spacing are its business."""
    if not line.lstrip().startswith("["):
        return None
    try:
        node = tomllib.loads(line)
    except tomllib.TOMLDecodeError:
        return None
    path = []
    while isinstance(node, (dict, list)):
        if isinstance(node, list):  # [[array of tables]]
            node = node[0] if node else {}
            continue
        if len(node) != 1:
            break
        (key, node), = node.items()
        path.append(key)
    return path or None


def _drop_blocks(text, owns):
    """The text without every table whose header path `owns` says is the caller's: a block runs from its
    header to the next one, a comment that sits directly above the next header stays with it. The caller
    parses and compares the result; this only edits lines."""
    out, tail, dropping = [], [], False
    for line in text.splitlines(keepends=True):
        path = _toml_header_path(line)
        if path is not None:
            if dropping and any(l.strip() for l in tail):  # comments above the next header are its own
                out.extend(tail)
            tail = []
            dropping = owns(path)
            if not dropping:
                out.append(line)
        elif dropping:
            tail = tail + [line] if (line.strip() == "" or line.lstrip().startswith("#")) else []
        else:
            out.append(line)
    if dropping and any(l.strip() for l in tail):
        out.extend(tail)
    return "".join(out).lstrip("\n")


def drop_codex_servers(text, names):
    """(the text without the `[mcp_servers.<name>]` tables and their sub-tables for every `name` in `names`,
    the names it took out, None), or (None, [], why not) when it cannot be done safely.

    Line by line: a table header whose path is mcp_servers.<name>[...] opens a block that runs to the next
    header, a comment that sits directly above the next header stays with it. The result is then parsed
    and compared with the original less those names; a mismatch (a name set by dotted keys or an inline
    table, a header-looking line inside a multi-line string) means the text is returned unchanged with
    the reason, never a guess. Everything else, comments included, is kept as written."""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return None, [], "it does not parse as TOML (%s)" % e
    servers = before.get("mcp_servers")
    ours = [n for n in (servers if isinstance(servers, dict) else {}) if n in names]
    if not ours:
        return text, [], None
    new = _drop_blocks(text, lambda path: len(path) >= 2 and path[0] == "mcp_servers" and path[1] in ours)
    want = {k: v for k, v in before.items() if k != "mcp_servers"}
    rest = {n: v for n, v in servers.items() if n not in ours}
    if rest:
        want["mcp_servers"] = rest
    try:
        got = tomllib.loads(new)
    except tomllib.TOMLDecodeError:
        got = None
    if got is None or {k: v for k, v in got.items() if not (k == "mcp_servers" and v == {})} != want:
        return None, [], "a server of forge's name is written in a shape that cannot be taken out whole"
    return new, ours, None


POLICY = "shell_environment_policy"


def _policy_mismatch(table, names):
    """Why `table` (the parsed [shell_environment_policy]) is not the one write_codex_project_mcp writes for a
    profile whose env keys are `names`, or None when it is. Forge's is `inherit = "core"` and nothing else but
    a `set` table, whose keys are all `names` or MCPORTER_CONFIG; with no `names` it writes no `set`, and a
    table with none is its too. Values are never compared, and never named: a rotated secret or an edited
    profile leaves a table whose values are stale and still forge's, and the reason lines are printed."""
    if not isinstance(table, dict):
        return "it is not a table"
    extra = sorted(set(table) - {"inherit", "set"})
    if extra:
        return "it holds keys forge does not write (%s)" % ", ".join(extra)
    if table.get("inherit") != "core":
        return 'its inherit is not "core"'
    env = table.get("set")
    if env is None:
        return None if not names else "forge would write a set table for this profile and this one has none"
    if not isinstance(env, dict):
        return "its set is not a table"
    foreign = sorted(k for k in env if k not in names and k != "MCPORTER_CONFIG")
    if foreign:
        return "it sets keys forge does not write for this profile (%s)" % ", ".join(foreign)
    return None


def drop_codex_policy(text, names):
    """(the text without the [shell_environment_policy] table and its `.set` table, True, None) when forge's
    is there, (text, False, None) when no such table is, and (text, False, why) when one is that is not
    forge's shape (_policy_mismatch) or cannot be taken out whole: dotted keys, a header-looking line inside
    a multi-line string. As for drop_codex_servers, the line edit is checked by parsing the result and
    comparing it with the original less the table, and a mismatch changes nothing."""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return text, False, "it does not parse as TOML (%s)" % e
    if POLICY not in before:
        return text, False, None
    why = _policy_mismatch(before[POLICY], names)
    if why:
        return text, False, why
    new = _drop_blocks(text, lambda path: path[0] == POLICY)
    try:
        got = tomllib.loads(new)
    except tomllib.TOMLDecodeError:
        got = None
    if got != {k: v for k, v in before.items() if k != POLICY}:
        return text, False, "it is written in a shape that cannot be taken out whole"
    return new, True, None


def _codex_env_names(prof):
    """The env keys write_codex_project_mcp writes into a profile's [shell_environment_policy.set]."""
    names = set(prof.get("env") or {})
    if _mcporter_config() is not None:
        names.add("MCPORTER_CONFIG")
    return names


def _bak_verdict(ppath, path, registry):
    """What drop_codex_project_mcp finds at `path`.bak, the once-ever copy lib.write_text keeps of the file's
    first replaced content: ("none", None) when there is none, ("forge", None) when it is forge's,
    ("foreign", None) when it holds nothing forge writes, and ("unsure", why) when forge cannot tell or
    must not touch it. Forge's is a regular file, not a link nor behind one, that parses and holds a
    registry server, or whose only top-level keys are mcp_servers and a [shell_environment_policy] with
    `inherit = "core"` (the oldest content, so its names have drifted: the writer's whole-file rewrite
    always had that table first and nothing else but the servers). Its content is never printed."""
    bak = path + ".bak"
    if not os.path.lexists(bak):
        return "none", None
    if os.path.islink(bak) or os.path.realpath(bak) != os.path.join(os.path.realpath(ppath), ".codex", "config.toml.bak"):
        return "unsure", "it is a link, or sits behind one"
    if not os.path.isfile(bak):
        return "unsure", "it is not a regular file"
    try:
        with open(bak, encoding="utf-8", newline="") as fh:
            doc = tomllib.loads(fh.read())
    except (OSError, UnicodeDecodeError) as e:
        return "unsure", "it cannot be read as UTF-8: %s" % e
    except tomllib.TOMLDecodeError as e:
        return "unsure", "it does not parse as TOML (%s)" % e
    servers = doc.get("mcp_servers")
    if isinstance(servers, dict) and any(n in registry for n in servers):
        return "forge", None
    # The oldest content, so its names have drifted: a retired server, a key the profile no longer carries.
    # The writer's whole-file rewrite always began with the policy table and held nothing but it and the
    # servers, so that is the mark: those two top-level keys at most, the policy `inherit = "core"`.
    pol = doc.get(POLICY)
    if isinstance(pol, dict) and set(doc) <= {"mcp_servers", POLICY} and set(pol) <= {"inherit", "set"} \
            and pol.get("inherit") == "core":
        return "forge", None
    return "foreign", None


def drop_codex_project_mcp(ctx, prof, registry, errors):
    """The `codex_harness` false half of write_codex_project_mcp: with the switch off Codex gets nothing
    Claude-style from forge, so forge takes out of <project>/.codex/config.toml what it wrote there: the
    `[mcp_servers.<name>]` tables (and their `.env` tables) whose name is a registry server, and the
    [shell_environment_policy] table (with its `.set`) when it has the shape forge writes for this profile
    (drop_codex_policy); one of another shape stays and the line says so. Any other table, key and comment
    stays, and so does the file itself: forge keeps no record of who created it, and Codex may have written
    to it since. The once-ever `.bak` that lib.write_text kept of its first replaced content holds the old
    values (resolved secrets among them), so it goes too when it is forge's (_bak_verdict), and the edit is
    written without making a new one, which would hold them again. A file that is absent is not created;
    one that does not parse, or holds a registry name in a shape the line reader cannot take out whole, is
    left as it is, its .bak with it, and the line says so. A project_path that is not a directory is the
    writer's error, word for word, so the run exits 1 in both states. Returns a one-line summary, or None."""
    ppath = prof["project_path"]
    if not os.path.isdir(ppath):
        errors.append("codex mcp: project_path does not exist on disk: %s" % ppath)
        return None
    path = os.path.join(ppath, ".codex", "config.toml")
    short = lib.short(path)
    head = "   codex mcp -> %s (codex_harness off: no MCP server written" % short
    names = _codex_env_names(prof)
    parts, written = [], None
    if os.path.lexists(path):
        # Same as the writer: a link anywhere in the path would send the rewrite wherever it points.
        where = os.path.realpath(path)
        if where != os.path.join(os.path.realpath(ppath), ".codex", "config.toml"):
            return "   ! codex mcp -> %s NOT changed: it resolves to %s" % (short, lib.short(where))
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            return head + "; file left alone, it cannot be read as UTF-8: %s)" % e
        new, dropped, why = drop_codex_servers(text, set(registry))
        if why:
            return head + "; file left alone, %s)" % why
        new, policy, pwhy = drop_codex_policy(new, names)
        out = dropped + (["[%s]" % POLICY] if policy else [])
        if out:
            parts.append("forge's out: %s" % ", ".join(out))
            written = new
        if pwhy:
            parts.append("[%s] left alone, %s" % (POLICY, pwhy))
    state, why = _bak_verdict(ppath, path, registry)
    if state == "unsure":
        parts.append(".bak left alone, %s" % why)
    if written is not None and ctx.apply:
        lib.write_text(path, written, mode=0o600, backup=False)  # before the .bak goes: a failed write keeps both
        record_claims(path, [], True, part="codex")  # no longer the text forge wrote
    if state == "forge":
        removed = "would be removed"
        if ctx.apply:
            try:
                os.remove(path + ".bak")
                removed = "removed"
            except OSError as e:
                removed = "NOT removed: %s" % e
        parts.append(".bak %s (the copy forge made, it holds what forge wrote)" % removed)
    if not parts:
        return head + ", none of forge's in it)"
    msg = head + "; " + "; ".join(parts) + ")"
    if written is not None:
        msg += " (updated)" if ctx.apply else " (would update)"
    return msg


def load_inputs(cfg):
    """(the registry's servers, the secrets without their `_` keys), both read from `cfg`, after
    saying so when config/secrets.json is not the link to credentials/secrets.json. The servers
    are None when the registry is unreadable, missing, or not an object holding a `servers`
    object: the caller refuses the run (a `[]` registry raised here, at the `.get`)."""
    doc = lib.read_json(os.path.join(cfg, "mcp-registry.json"))
    registry = doc.get("servers") if isinstance(doc, dict) else None
    registry = registry if isinstance(registry, dict) else None
    secrets = {k: v for k, v in lib.read_json(os.path.join(cfg, "secrets.json")).items() if not k.startswith("_")}

    # config/secrets.json MUST be the symlink to credentials/secrets.json, never a copy. Found
    # in use: it had been a regular file for days, so this line was reading a frozen
    # snapshot -- six secrets added to credentials/ since were invisible here, two retired ones
    # lingered, and one held a different value in each. Nothing errored, because a profile only
    # fails when it REFERENCES a missing secret and none of the six was referenced yet. A stale
    # copy is therefore silent until the day it is not, which is why this is a check and not a
    # sentence in the docs.
    _sec = os.path.join(cfg, "secrets.json")
    if not os.path.lexists(_sec):
        # A worktree has none (git ignores it); a missing file is not a stale copy.
        print("!! config/secrets.json is missing, so no secret resolves.")
        print("   Fix: ln -s ../credentials/secrets.json config/secrets.json")
        print()
    elif not os.path.islink(_sec):
        canonical = os.path.join(os.path.dirname(cfg), "credentials", "secrets.json")  # beside cfg, as the link
        stale = sorted(set(lib.read_json(canonical)) - set(lib.read_json(_sec)))
        print("!! config/secrets.json is a COPY, not the symlink to credentials/secrets.json.")
        print("   The generator reads it, so every secret added since the copy was made is invisible.")
        if stale:
            print("   Missing here: %s" % ", ".join(k for k in stale if not k.startswith("_")))
        print("   Fix: rm config/secrets.json && ln -s ../credentials/secrets.json config/secrets.json")
        print()
    return registry, secrets


def relocations_in_scope(ctx, loaded, relocations):
    """A relocation writes a project's key, so it follows the same scope as the profile loop: a
    scoped run moves only its own projects' keys, and a frozen project's key is never moved
    into or out of (the loop's frozen skip promises it is left exactly as it is). Returns the
    relocations to apply, after one line for each one skipped for a frozen or skipped end."""
    # No project_path, no key to move or protect; a frozen profile may name none (2c1cc85).
    every = {os.path.basename(pf)[:-len(".claude.json")]: p for pf, p in loaded.items()
             if isinstance(p, dict) and isinstance(p.get("project_path"), str) and p["project_path"]}
    # A profile the loop skips for a wrong type (lib.profile_error) is held like a frozen one: the
    # loop says nothing was written for it, so its key is not moved either.
    held = {}
    for p in every.values():
        bad = lib.profile_error(p)
        if bad or p.get("frozen"):
            held[project_key(p["project_path"])] = (
                "its profile is skipped (%s)" % bad if bad else "a frozen project's key is never touched")
    mine = None if ctx.only is None else {project_key(p["project_path"]) for n, p in every.items() if n in ctx.only}
    kept = []
    for item in relocations:
        ends = {project_key(item[k]) for k in ("from", "to") if item.get(k)}
        if mine is not None and not ends & mine:
            continue
        hit = sorted(ends & held.keys())
        if hit:
            print("  ! relocation %s -> %s skipped: %s" % (item.get("from"), item.get("to"), held[hit[0]]))
            continue
        kept.append(item)
    return kept


class ClaudeJson:
    """~/.claude.json, which holds every project's MCP servers with their secrets resolved.

    It is loaded ONCE (open), every profile mutates this one copy (project), and it is written
    once after the loop, only if the serialized text changed (commit). It once was
    loaded 21 times and written 20 times per run (~38 ms of ~95), all of them on a normal run that
    changed nothing -- and Claude Code writes this same file from every open session, so a write
    that changes nothing is a chance to clobber one for no gain."""

    def __init__(self, path, doc, err, mtime):
        self.path, self.doc, self.err, self.mtime = path, doc, err, mtime
        self.before = lib.dumps(doc)
        self.claims = {}  # project key -> the claims of the servers this run wrote there

    @classmethod
    def open(cls, ctx):
        """The document, with its mode asserted and its mtime taken before the load. An unreadable
        file loads as {} and is never written (commit raises it)."""
        path = os.path.join(lib.HOME, ".claude.json")
        # ~/.claude.json holds every MCP server's env with the secrets ALREADY RESOLVED -- that is
        # the point of it, and it is why the file must not be world-readable. Measured:
        # it was mode 644 and seven of the twenty-eight values in credentials/secrets.json appeared
        # in it verbatim, while secrets.json, secrets.env and the rendered hindsight config were all
        # 600. Writing it 0600 only fixes it on runs that change something, so the mode is asserted
        # on every run, the same way the hindsight config's is.
        # Its once-ever .bak holds the same secrets. Only a write corrected it (lib.write_text), and
        # most runs write nothing: commit() returns "already current" first, so a 644 .bak beside
        # a current file stayed 644 for good (round 5). Asserted here, beside the file's own mode,
        # so every way commit() ends is covered. The .bak is where lib.write_text puts it, beside
        # the file a link resolves to; only its mode is read.
        for p in loose_secrets(path):
            if ctx.apply:
                lib.chmod(p, 0o600)
            print("%schmod 600 %s (it carries resolved secrets)" % ("" if ctx.apply else "would ", lib.short(p)))

        mtime = os.stat(path).st_mtime_ns if os.path.exists(path) else None
        try:
            doc, err = lib.read_owned(path), None
        except lib.Unreadable as e:
            doc, err = {}, e  # the profile loop still runs; the file is never written
        return cls(path, doc, err, mtime)

    def relocate(self, ctx, loaded, relocations):
        """Apply the `relocations` (config/project-relocations.json) that are in this run's scope,
        given every profile as {profile file: profile}, printing one line per key moved. It runs
        before the profile loop, which then finds each project under its new key."""
        kept = relocations_in_scope(ctx, loaded, relocations)
        if kept:
            for old, new in migrate_project_keys(self.doc, kept):
                print("project key relocation:", old, "->", new)

    def project(self, prof, sel, registry, secrets, errors):
        """Give one profile's project its servers `sel`, resolved. A secret that does not resolve
        is appended to `errors` and leaves the project's servers as they were."""
        fk = project_key(prof["project_path"])
        # SANDBOX: top-level `mcpServers` is USER scope -> every server there leaks into
        # EVERY project Claude opens. The design assigns every server per-project
        # (via these profiles), so user scope must stay EMPTY. Clear it each run so a stray
        # `claude mcp add -s user` / manual edit can't re-leak. Servers wanted
        # by a project remain in that project's own mcpServers below.
        top = self.doc.get("mcpServers") or {}
        if top:
            print("   ! clearing user-scope (top-level) mcpServers -- leak into ALL projects: %s" % sorted(top.keys()))
            self.doc["mcpServers"] = {}
        projects = self.doc.setdefault("projects", {})
        # INVARIANT: exactly one canonical forward-slash project key. Fold in any duplicate path
        # key (slash, trailing separator; case and drive letter only where the filesystem ignores
        # case -- on Linux `/x/App` is another directory, not a duplicate of `/x/app`).
        dups = [k for k in projects if k != fk and os.path.normcase(project_key(k)) == os.path.normcase(fk)]
        for dk in dups:
            print("   ! removing duplicate project key:", dk)
            merge_project_entry(projects.setdefault(fk, {}), projects.pop(dk))
        proj = projects.setdefault(fk, {})
        old = list((proj.get("mcpServers") or {}).keys())
        new_ms = {s: resolved_server(s, registry[s], secrets, errors) for s in sel}
        add, rem = diff_keys(old, new_ms.keys())
        print("   claude key:", fk)
        print("   servers +%s  -%s" % (add or "[]", rem or "[]"))
        if not errors:
            proj["mcpServers"] = new_ms
            self.claims[fk] = [owned.claim("key", ["projects", fk, "mcpServers", s], d, prof.get("project") or "")
                               for s, d in new_ms.items()]
            # The .mcp.json approval keys are not written here: Claude Code reads them from the
            # project's settings.local.json (forge/skills.py), and removes them from this entry on
            # its own, so putting them back made every run a write. Neither added nor removed.
            # preserve disabledMcpServers as-is

    def commit(self, ctx):
        """The status line for ~/.claude.json, written when its text changed and nobody else wrote
        the file since open(). Raises the lib.Unreadable open() met: that file is never written."""
        if self.err:
            raise self.err
        if lib.dumps(self.doc) == self.before:
            self._record(ctx)
            return "   ~/.claude.json -> already current"
        if ctx.apply and os.path.exists(self.path) and os.stat(self.path).st_mtime_ns != self.mtime:
            # Every open Claude Code session writes this file too. Writing our copy now would drop
            # whatever that session just saved; the next run starts from the new file instead.
            return "   ~/.claude.json -> changed by another process while generating; not written, next run retries"
        if ctx.apply:
            lib.write_json(self.path, self.doc, mode=0o600, backup=True)
            self._record(ctx)
            return "   ~/.claude.json -> wrote"
        return "   ~/.claude.json -> would write"

    def _record(self, ctx):
        """The ownership record (forge/owned.py) of the servers forge wrote this run, one part per project
        key: the file is every project's, so a run over one project leaves the others' claims. Only the
        projects this run wrote are touched, and only the hash of each definition is kept (it holds secrets)."""
        for fk, claims in self.claims.items():
            record_claims(self.path, claims, ctx.apply, part="mcp:" + fk)
