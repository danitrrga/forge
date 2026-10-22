"""Online skills: a `skills` list in config/toolchain.json, rebuilt from the manifest by `forge skills`.

Each entry names an `http:` tool of the same file (the archive of a repository at a commit, with a checksum, which
mise downloads and verifies) and a path inside that archive. The skill is copied out of the mise install into
skills/<name>, byte for byte, and NOTICE.md is generated beside it from the entry (repository, commit, path, and
the licence text out of the archive), so a copy stays "installed unchanged" and a new checkout rebuilds it from the
manifest instead of git carrying it (docs/toolchain-design.md section 3, G).

  {"name": "grilling", "source": "http:some-skills", "path": "skills/productivity/grilling",
   "repo": "https://github.com/owner/some-skills", "license_file": "LICENSE", "why": "..."}

The licence is the text of `license_file` out of the archive, or, with a `license` line instead, that line (for a skill
whose directory already ships its LICENSE: the NOTICE says so rather than copying it a second time).

A dry-run names what would change per skill (created, or the files that differ, are missing or are extra); --apply
makes the copy match: it overwrites a changed file and removes an extra one, so a skill listed here is derived data
and an edit inside it is drift, never kept.
"""
import json
import os
import re
import stat
import sys

from forge import lib, toolchain

NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _error(e, tools):
    """What is wrong with one `skills` entry, or None."""
    if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e[k].strip() for k in ("name", "source", "repo", "why")):
        return "needs a name, a source, a repo and a why"
    if ("license" in e) == ("license_file" in e) or not isinstance(e.get("license", e.get("license_file")), str) or not e.get("license", e.get("license_file")).strip():
        return "needs a license_file or a license line, and not both"
    if not NAME.match(e["name"]) or e["name"] in (".", ".."):
        return "has a name that is not a plain directory name"
    if not isinstance(e.get("path", ""), str) or os.path.isabs(e.get("path", "")) or ".." in e.get("path", "").split("/"):
        return "has a path that leaves the archive"
    if not e["repo"].startswith("https://"):
        return "has a repo that is no https URL"
    if os.path.isabs(e.get("license_file", "")) or ".." in e.get("license_file", "").split("/"):
        return "has a license_file that leaves the archive"
    tool = tools.get(e["source"])
    if tool is None or not e["source"].startswith("http:"):
        return "names %s, which is no `http:` tool of this file" % e["source"]
    if not (tool.get("options") or {}).get("checksum"):
        return "names %s, which has no `checksum` option: a changed archive would pass" % e["source"]
    return None


def entries():
    """([skills], why not): the `skills` list of config/toolchain.json, each checked against the tools it names. An
    absent or empty list is no skills and no reason, and so is a checkout with no manifest."""
    if not os.path.exists(toolchain.MANIFEST):
        return [], None
    doc, why = toolchain.entries()
    if why:
        return [], why
    with open(toolchain.MANIFEST, encoding="utf-8") as fh:
        items = json.load(fh).get("skills", [])
    if not isinstance(items, list):
        return [], "config/toolchain.json: \"skills\" is not a list"
    tools = {t["name"]: t for t in doc["tools"]}
    names = []
    for e in items:
        bad = _error(e, tools)
        if bad:
            return [], "config/toolchain.json: a \"skills\" entry %s: %r" % (bad, e)
        if e["name"] in names:
            return [], "config/toolchain.json: \"skills\" lists %s twice" % e["name"]
        names.append(e["name"])
    return [dict(e, tool=tools[e["source"]]) for e in items], None


def read_tree(base):
    """{relative path: bytes} of every file under `base`."""
    out = {}
    for d, _, files in os.walk(base):
        for f in files:
            with open(os.path.join(d, f), "rb") as fh:
                out[os.path.relpath(os.path.join(d, f), base)] = fh.read()
    return out


def render_notice(e, commit, licence):
    """NOTICE.md: where the copy is from, that it is unchanged, and the licence text of the archive. The first line
    is the form forge lock reads (lockfile.notice)."""
    where = e["path"] or "the whole repository"
    return ("From %s at commit %s, %s.\n\nUnchanged: every file is byte-identical to that commit; this NOTICE.md is the only "
            "addition.\n\n%s" % (e["repo"], commit, where, licence if "license_file" in e else "Licence: %s\n" % e["license"])).encode("utf-8")


def plan(e):
    """(want {path: bytes}, modes {path: permission bits}, why not) for one entry, from its mise install."""
    code, out, err = toolchain.tool_run(["mise", "where", "%s@%s" % (e["source"], e["tool"]["version"])], toolchain.LIST_TIMEOUT)
    if code != 0 or not out.strip():
        return None, None, "%s@%s is not installed (%s) -- run forge toolchain --fix" % (e["source"], e["tool"]["version"], err or "mise gave no path")
    install = out.strip()
    where = os.path.join(install, e["path"])
    try:
        want = read_tree(where)
        licence = ""
        if "license_file" in e:
            with open(os.path.join(install, e["license_file"]), encoding="utf-8") as fh:
                licence = fh.read()
    except OSError as ex:
        return None, None, "%s is not readable in %s: %s" % (e["path"] or "the archive", install, ex)
    if not want:
        return None, None, "%s holds no file in %s" % (e["path"] or "the archive", install)
    if "NOTICE.md" in want:
        return None, None, "%s already has a NOTICE.md, which the generated one would replace" % e["path"]
    modes = {rel: stat.S_IMODE(os.stat(os.path.join(where, rel)).st_mode) for rel in want}
    want["NOTICE.md"] = render_notice(e, e["tool"]["version"], licence)
    return want, modes, None


def write(dest, want, have, modes):
    for rel, data in want.items():
        if have.get(rel) != data:
            path = os.path.join(dest, rel)
            lib.makedirs(os.path.dirname(path))
            with open(path, "wb") as fh:
                fh.write(data)
            if rel in modes:
                os.chmod(path, modes[rel])
            lib.record("wrote", path)
    for rel in have.keys() - want.keys():
        os.remove(os.path.join(dest, rel))
        lib.record("unlink", os.path.join(dest, rel))


def main(argv):
    """The `online skills` step of forge skills; returns the exit code (1 when a skill could not be planned)."""
    items, why = entries()
    if why:
        print("! %s" % why)
        return 1
    if not items:
        print(lib.NOT_ARMED + "no `skills` in config/toolchain.json, so no online skill is rebuilt")
        return 0
    apply = "--apply" in argv and lib.apply_allowed(True)
    failed = 0
    for e in items:
        want, modes, why = plan(e)
        if why:
            print("! %s: %s" % (e["name"], why))
            failed = 1
            continue
        dest = os.path.join(lib.ROOT, "skills", e["name"])
        have = read_tree(dest) if os.path.isdir(dest) else {}
        diff = [("would change" if not apply else "changed", sorted(r for r in want if r in have and have[r] != want[r])),
                ("missing", sorted(want.keys() - have.keys())), ("extra", sorted(have.keys() - want.keys()))]
        if not have:
            print("%s: %s (%d files)" % (e["name"], "created" if apply else "would create", len(want)))
        elif any(files for _, files in diff):
            print("%s: %s" % (e["name"], "; ".join("%s: %s" % (k, ", ".join(f)) for k, f in diff if f)))
        else:
            print("%s: in sync (%d files)" % (e["name"], len(want)))
        if apply:
            write(dest, want, have, modes)
    return failed
