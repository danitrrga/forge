"""config/forge.lock.json: the versions forge ships that mise does not install (docs/toolchain-design.md section 4).

`forge lock` reads what is on this machine and writes the file; `forge versions [--md]` prints it next to the
pins of config/toolchain.json, for release notes. A release is a commit of both, so a newcomer gets the versions
the maintainer runs. Four sections:

  plugins  Claude Code plugins: the newest install of each (installed_plugins.json lists one per project), less
           the names in config/forge.json `lock_exclude`: the lock is published, and a plugin of the user's own is not
  skills   outside skills, from each skills/<name>/NOTICE.md: a repository and a commit, or an npm package
  gsd      the GSD runtime's VERSION file
  mcp      the package each `npx` server in config/mcp-registry.json launches, by package (a server's name can
           carry a project's), with the version as written or "floating" (resolving it needs the network, and
           step 5 turns these into pinned tools)
"""
import json
import os
import re

from forge import lib, toolchain

SECTIONS = ("plugins", "skills", "gsd", "mcp")
# The three forms of a NOTICE.md in skills/: "From <repo> at commit <sha>", a "- Repository:" and "- Commit:" list,
# and "From the npm package <name>@<version> (".
FROM_COMMIT = re.compile(r"From (https://\S+) at commit ([0-9a-f]{40})")
LIST_REPO = re.compile(r"^- Repository: (https://\S+)", re.M)
LIST_COMMIT = re.compile(r"^- Commit: ([0-9a-f]{40})", re.M)
FROM_NPM = re.compile(r"From the npm package (\S+@\S+) \(")


def path():
    return os.path.join(lib.ROOT, "config", "forge.lock.json")


def dumps(doc):
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def plugins():
    """{"name@market": {"version", "sha"?}}: the entry with the newest lastUpdated of each plugin."""
    doc = lib.read_json(os.path.join(lib.HOME, ".claude", "plugins", "installed_plugins.json")).get("plugins", {})
    out, skip = {}, lib.settings().get("lock_exclude") or []
    for name, installs in doc.items():
        if name in skip:
            continue
        newest = max(installs, key=lambda e: e.get("lastUpdated", ""))
        out[name] = {"version": newest["version"]}
        if newest.get("gitCommitSha"):
            out[name]["sha"] = newest["gitCommitSha"]
    return out


def notice(text):
    """The pin a NOTICE.md records, or None."""
    m = FROM_COMMIT.search(text)
    if m:
        return {"repo": m.group(1), "commit": m.group(2)}
    repo, commit = LIST_REPO.search(text), LIST_COMMIT.search(text)
    if repo and commit:
        return {"repo": repo.group(1), "commit": commit.group(1)}
    m = FROM_NPM.search(text)
    return {"npm": m.group(1)} if m else None


def skills(problems):
    """{skill: pin} for each skills/<name>/NOTICE.md; one that records no pin is a line in `problems`."""
    out, base = {}, os.path.join(lib.ROOT, "skills")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        f = os.path.join(base, name, "NOTICE.md")
        if not os.path.isfile(f):
            continue  # forge's own skill, not a third-party copy
        with open(f, encoding="utf-8") as fh:
            pin = notice(fh.read())
        if pin:
            out[name] = pin
        else:
            problems.append("skills/%s/NOTICE.md names neither a repository with a commit nor an npm package" % name)
    return out


def mcp():
    """{package: version} for the `npx` servers of the registry: the first argument that is no flag, split at the
    version's `@` (a leading one is the scope's), "floating" when there is none or it is `latest`."""
    out = {}
    for server in lib.read_json(os.path.join(lib.ROOT, "config", "mcp-registry.json")).get("servers", {}).values():
        if server.get("command") == "npx":
            spec = next((a for a in server.get("args", []) if not a.startswith("-")), None)
            if spec:
                name, _, version = spec.rpartition("@") if "@" in spec[1:] else (spec, "", "")
                out[name] = version if version and version != "latest" else "floating"
    return out


def collect():
    """(the lock document, problems): what this machine has, sorted. A section with nothing in it is left out."""
    problems = []
    doc = {"plugins": plugins(), "skills": skills(problems), "mcp": mcp()}
    try:
        with open(os.path.join(lib.HOME, ".claude", "gsd-core", "VERSION"), encoding="utf-8") as fh:
            doc["gsd"] = fh.read().strip()
    except FileNotFoundError:
        pass
    return {k: v for k, v in sorted(doc.items()) if v}, problems


def summary(doc):
    return "%d plugin(s), %d skill(s), gsd %s, %d mcp package(s)" % (
        len(doc.get("plugins", {})), len(doc.get("skills", {})), doc.get("gsd", "absent"), len(doc.get("mcp", {})))


def changes(old, new):
    """One line per entry that differs between two lock documents."""
    out = []
    for sec in SECTIONS:
        a, b = old.get(sec), new.get(sec)
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a or {}, b or {}
            out += ["%s %s: %s -> %s" % (sec, k, a.get(k, "absent"), b.get(k, "absent")) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        elif a != b:
            out.append("%s: %s -> %s" % (sec, a or "absent", b or "absent"))
    return out


def cmd_lock(a):
    """forge lock [--apply]: what the lock would say, against what it says; --apply writes it. A skill whose
    NOTICE.md records no pin is a failure and nothing is written: a lock that skips one is not the lock."""
    doc, problems = collect()
    print("saw %s" % summary(doc))
    for p in problems:
        print("! %s" % p)
    if problems:
        return 1
    old = lib.read_json(path())
    diff = changes(old, doc)
    if not diff:
        print("config/forge.lock.json is up to date")
        return 0
    for line in diff:
        print("  " + line)
    if not a.apply:
        print("would write config/forge.lock.json (%d change(s)); pass --apply" % len(diff))
        return 0
    ok, why = lib.may_write()
    if not ok:
        print(why)
        return 1
    lib.write_text(path(), dumps(doc))
    print("wrote config/forge.lock.json")
    return 0


def rows():
    """[(section, name, version)]: the mise pins of config/toolchain.json, then the lock's four sections."""
    manifest, _ = toolchain.entries()
    out = [(sec, e["name"], e["version"]) for sec in toolchain.SECTIONS for e in manifest.get(sec, [])
           if sec != "tools" or toolchain.wanted(e)[0]]  # a tool whose GSD default is off is not installed
    lock = lib.read_json(path())
    for name, p in lock.get("plugins", {}).items():
        out.append(("plugins", name, p["version"] + (" (%s)" % p["sha"][:7] if p.get("sha") else "")))
    for name, p in lock.get("skills", {}).items():
        out.append(("skills", name, p["npm"] if "npm" in p else "%s@%s" % (p["repo"].rsplit("github.com/", 1)[-1], p["commit"][:7])))
    if "gsd" in lock:
        out.append(("gsd", "gsd", lock["gsd"]))
    out += [("mcp", name, version) for name, version in lock.get("mcp", {}).items()]
    return out


def cmd_versions(a):
    """forge versions [--md]: the pins, one per line or as a markdown table per section. No lock file is a
    failure: the table would read as complete without it."""
    if not os.path.exists(path()):
        print("! no config/forge.lock.json -- run forge lock --apply")
        return 1
    table = rows()
    if not table:
        print("! nothing to show: config/toolchain.json and config/forge.lock.json are both empty")
        return 1
    last = None
    for sec, name, version in table:
        if sec != last:
            print(("\n### %s\n\n| name | version |\n|---|---|" if a.md else "\n%s") % sec)
            last = sec
        print("| %s | %s |" % (name, version) if a.md else "  %s %s" % (name, version))
    return 0
