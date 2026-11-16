#!/usr/bin/env python3
"""Resync the cross-project capability baseline: which GLOBAL skills every project keeps,
plus the shared permission allowlist and env every project needs to use them.

WHY THIS EXISTS
  sync_agent_config.py full-replaces each project's settings.local.json `skillOverrides`
  every SessionStart (incl. /clear, resume, compact): "all global skills off EXCEPT
  project-local skills + this project's skills_keep". So a skill absent from skills_keep
  gets disabled on the next /clear -- the flapping that once switched a whole stack off in one project.

  The fix is declarative: list the skills a project must keep in its skills_keep, and this script
  keeps those lists complete (the COMMON layer) and free of names no skill answers to.

  Project-LOCAL skills (.claude/skills/<name>/) are auto-kept by sync_agent_config.py and
  must NOT be listed here. Only GLOBAL skills (~/.claude/skills) need an entry.

THE LAYERS (the tables named below are config/forge.json skill_keep, see docs/portable-design.md)
  1. EXTRAS           -- per-project skills_keep, a full replace for the projects listed in it (a project
                         with no row keeps the names it holds).
  2. COMMON_*         -- the capability baseline that belongs in EVERY project:
                         COMMON_SKILLS / COMMON_PERMISSIONS / COMMON_ENV, UNION-merged
                         into every project except COMMON_EXCLUDE. Union (not replace) so
                         hand-curated projects (a study-skill set, an ssh permission set)
                         survive untouched.
  Before this existed there was no way to say "this global skill goes everywhere" -- a new
  cross-cutting skill had to be pasted into 13 projects by hand.

USAGE
  python scripts/sync/sync_skill_keep.py            # dry-run (prints diffs)
  python scripts/sync/sync_skill_keep.py --apply     # write projects
  python scripts/sync/sync_skill_keep.py --check     # the dry-run, exit 1 when a project would change
                                                     # (forge doctor's "skill keep" row); never writes
  # then: python scripts/sync/sync_agent_config.py --apply   (propagate to settings.local.json)
"""
import json, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.expanduser("~")
GLOBAL_SKILLS = os.path.join(HOME, ".claude", "skills")
PROF = os.path.join(ROOT, "config", "projects")
sys.path.insert(0, ROOT)
from forge import lib  # noqa: E402
CHECK = "--check" in sys.argv
if CHECK and "--apply" in sys.argv:
    sys.exit("! --check never writes: drop --apply (or drop --check to write)")
APPLY = lib.apply_allowed("--apply" in sys.argv)  # a worktree or a copy of forge writes nothing

# The tables are data, in config/forge.json's skill_keep (docs/portable-design.md section 4); the
# WHY of each is the `_doc` key beside it there. Order is output (the unions append in list order),
# so nothing here sorts. `~` in a common_env value is this HOME's, and `@NAME` in an extras row is
# skill_keep.sets[NAME], in place. A missing key is an empty table, which is a stranger's forge.
SKILL_KEEP = lib.settings().get("skill_keep") or {}


def expand_extras(rows, sets):
    """{project file: names} with each `@NAME` replaced by sets[NAME]. A name no set answers to
    exits 1: left as it is, `@NAME` would be written into a project as a skill."""
    out = {}
    for fn, row in rows.items():
        names = []
        for n in row:
            if n.startswith("@"):
                if n[1:] not in sets:
                    sys.exit("! config/forge.json skill_keep.extras[%s] names %s, which is not in skill_keep.sets"
                             % (fn, n))
                names += sets[n[1:]]
            else:
                names.append(n)
        out[fn] = names
    return out


EXTRAS = expand_extras(SKILL_KEEP.get("extras") or {}, SKILL_KEEP.get("sets") or {})
DESIGN_PERMISSIONS = SKILL_KEEP.get("design_permissions") or {"allow": [], "additionalDirectories": []}
COMMON_SKILLS = SKILL_KEEP.get("common_skills") or []
COMMON_PERMISSIONS = SKILL_KEEP.get("common_permissions") or {"allow": []}
COMMON_ENV = {k: os.path.expanduser(v) for k, v in (SKILL_KEEP.get("common_env") or {}).items()}
COMMON_PLUGINS = SKILL_KEEP.get("common_plugins") or []
COMMON_OPT_OUT = {fn: set(names) for fn, names in (SKILL_KEEP.get("common_opt_out") or {}).items()}
COMMON_EXCLUDE = set(SKILL_KEEP.get("common_exclude") or [])


def union(existing, additions):
    """Order-preserving union: keep what's there, append what's missing."""
    return list(dict.fromkeys(list(existing or []) + list(additions)))


def common_for(fn, names):
    """The COMMON names this project takes: all of them minus its COMMON_OPT_OUT entry."""
    out = COMMON_OPT_OUT.get(fn, set())
    return [n for n in names if n not in out]


def strip_opted_out(fn, d, key):
    """An opt-out is authoritative: a name it lists is removed from the project too, so taking a
    COMMON name out is one edit here rather than an edit here plus one in the project."""
    out = COMMON_OPT_OUT.get(fn, set())
    cur = d.get(key)
    if not out or not isinstance(cur, list):
        return []
    kept = [n for n in cur if n not in out]
    if kept == cur:
        return []
    d[key] = kept
    return ["%s -%s (COMMON_OPT_OUT)" % (key, sorted(set(cur) - set(kept)))]


def apply_common_plugins(fn, d):
    """Union COMMON_PLUGINS into one project's plugins_keep. Separate from apply_common()
    on purpose: this layer ignores COMMON_EXCLUDE (see the COMMON_PLUGINS note)."""
    if "plugins_keep" not in d:
        return []
    changes = strip_opted_out(fn, d, "plugins_keep")
    want = union(d["plugins_keep"], common_for(fn, COMMON_PLUGINS))
    if want == d["plugins_keep"]:
        return changes
    added = sorted(set(want) - set(d["plugins_keep"]))
    d["plugins_keep"] = want
    return changes + ["plugins +%s" % added]


def apply_design(d):
    """Give a project that carries the design set the file access those skills need.
    Keyed off the skills themselves, not a project list, so the two can never drift."""
    if "design-taste" not in (d.get("skills_keep") or []):
        return []
    changes = []
    perms = d.setdefault("permissions", collections.OrderedDict())
    want = union(perms.get("allow"), DESIGN_PERMISSIONS["allow"])
    if want != (perms.get("allow") or []):
        changes.append("design perms +%d" % len(set(want) - set(perms.get("allow") or [])))
        perms["allow"] = want
    want_dirs = union(perms.get("additionalDirectories"), DESIGN_PERMISSIONS["additionalDirectories"])
    if want_dirs != (perms.get("additionalDirectories") or []):
        changes.append("design dirs +%s" % sorted(set(want_dirs) - set(perms.get("additionalDirectories") or [])))
        perms["additionalDirectories"] = want_dirs
    return changes


def apply_common(fn, d):
    """Union COMMON_SKILLS / COMMON_PERMISSIONS / COMMON_ENV into one project dict.
    Returns a list of human-readable change descriptions (empty = already in sync)."""
    if fn in COMMON_EXCLUDE:
        return []
    changes = []

    # skills -- trimmed projects only (see COMMON_SKILLS note above). A ["*"] project already
    # keeps every global skill, so unioning names into it adds churn and no capability.
    if "skills_keep" in d and "*" not in (d["skills_keep"] or []):
        changes += strip_opted_out(fn, d, "skills_keep")
        want = union(d["skills_keep"], common_for(fn, COMMON_SKILLS))
        if want != d["skills_keep"]:
            changes.append("skills +%s" % sorted(set(want) - set(d["skills_keep"])))
            d["skills_keep"] = want

    perms = d.setdefault("permissions", collections.OrderedDict())
    want = union(perms.get("allow"), COMMON_PERMISSIONS["allow"])
    if want != (perms.get("allow") or []):
        changes.append("perms +%d" % len(set(want) - set(perms.get("allow") or [])))
        perms["allow"] = want
    if not d["permissions"]:
        del d["permissions"]

    env = d.setdefault("env", collections.OrderedDict())
    opted_out = COMMON_OPT_OUT.get(fn, set())
    for k, v in COMMON_ENV.items():
        if k in opted_out:  # authoritative, as strip_opted_out is for the lists: not added, removed
            if k in env:
                del env[k]
                changes.append("env -%s (COMMON_OPT_OUT)" % k)
        elif env.get(k) != v:
            changes.append("env %s" % k)
            env[k] = v
    if not d["env"]:
        del d["env"]

    return changes


def installed_skills():
    """Every skill name a project could actually keep: the dirs under ~/.claude/skills.
    forge skills reach there as symlinks (relink_skills.py), standalone ones like
    omarchy lives there directly -- so this is the real universe, not `skills/`."""
    if not os.path.isdir(GLOBAL_SKILLS):  # a stranger who has installed no skill yet
        return set()
    return set(d for d in os.listdir(GLOBAL_SKILLS)
               if os.path.isdir(os.path.join(GLOBAL_SKILLS, d)))


def check_declared(installed):
    """Fail loudly on a skill name this script would write that no longer exists.

    Set subtraction in sync_agent_config.py makes a dangling `skills_keep` entry a silent
    no-op, so a renamed or deleted skill used to sit in the projects forever while the
    SessionStart banner still counted it in "kept-global N"."""
    bad = []
    for name in COMMON_SKILLS:
        if name not in installed:
            bad.append("COMMON_SKILLS -> %s" % name)
    for fn, names in EXTRAS.items():
        for name in names:
            if name not in installed:
                bad.append("EXTRAS[%s] -> %s" % (fn, name))
    # An opt-out naming something the COMMON layer does not carry is a typo that opts out of
    # nothing, and the name it meant keeps coming back.
    for fn, names in COMMON_OPT_OUT.items():
        for name in sorted(names):
            if name not in COMMON_SKILLS and name not in COMMON_PLUGINS and name not in COMMON_ENV:
                bad.append("COMMON_OPT_OUT[%s] -> %s is in none of COMMON_SKILLS, COMMON_PLUGINS, COMMON_ENV"
                           % (fn, name))
        if not os.path.exists(os.path.join(PROF, fn)):
            bad.append("COMMON_OPT_OUT[%s] -> no such project" % fn)
    if bad:
        sys.exit("! declared skill(s) not installed in %s:\n    %s"
                 % (GLOBAL_SKILLS, "\n    ".join(bad)))


def prune_dangling(d, installed):
    """Drop skills_keep entries with no installed skill behind them."""
    sk = d.get("skills_keep")
    if sk is None:
        return []
    keep = [s for s in sk if s == "*" or s in installed]  # "*" = keep-all wildcard, not a name
    if keep == sk:
        return []
    d["skills_keep"] = keep
    return ["pruned dangling %s" % sorted(set(sk) - set(keep))]


def audit_trim(projects):
    """A state that looks like configuration and is really an accident.

    EMPTY skills_keep: trimming is ON and nothing is kept, so every global skill is off. That
    is what one project shipped with from the day the new-project skill created it -- every
    global skill and the whole COMMON layer dark for its entire life, surfacing only as "that command
    does nothing". Nobody has ever wanted this state on purpose."""
    notes = []
    for fn, d in projects.items():
        sk = d.get("skills_keep")
        if sk is None:
            continue
        if sk == []:
            notes.append("! %s has skills_keep: [] -- trimming ON, every global skill off. "
                         "Add it to EXTRAS (or delete the key to stop trimming)." % fn)
            continue
    return notes


def main():
    installed = installed_skills()
    check_declared(installed)
    print("MODE:", "APPLY" if APPLY else "DRY-RUN (pass --apply to write)")
    print("COMMON: %d skills, %d perms, %d env, %d plugins | excluded: %d\n"
          % (len(COMMON_SKILLS), len(COMMON_PERMISSIONS["allow"]),
             len(COMMON_ENV), len(COMMON_PLUGINS), len(COMMON_EXCLUDE)))

    for fn in EXTRAS:
        if not os.path.exists(os.path.join(PROF, fn)):
            print("  ! %s listed in EXTRAS but missing on disk" % fn)

    changed = 0
    seen = {}
    # The files lib.projects() reads (config/projects/*.claude.json), read the way it reads them:
    # one that cannot be read, is not an object or has a field of the wrong type is named and
    # skipped, the rest still run, and the exit is 1 at the end (a '!' line means exit 1).
    skipped = []
    profs = {name + ".claude.json": d for name, d in lib.projects(skipped).items()}
    for fn, why in sorted(skipped):
        print("! %s unreadable: %s -- skipped" % (fn, why))
    for fn in sorted(profs):
        p = os.path.join(PROF, fn)
        d = profs[fn]
        notes = []

        # Layer 0: drop names no installed skill answers to (self-heals after a deletion)
        notes += prune_dangling(d, installed)

        # Layer 1: per-project extras (full replace, EXTRAS projects only)
        if fn in EXTRAS:
            # COMMON_SKILLS folded in HERE too -- this branch full-replaces skills_keep, so
            # leaving them to apply_common's union below would strip and re-add them every
            # run (a rewrite + churn on each invocation instead of a clean no-op).
            want = sorted(EXTRAS[fn])
            if fn not in COMMON_EXCLUDE:
                want = union(want, common_for(fn, COMMON_SKILLS))
            old = d.get("skills_keep", [])
            if sorted(old) != sorted(want):
                add = sorted(set(want) - set(old)); rem = sorted(set(old) - set(want))
                notes.append("extras +%s -%s" % (add or "[]", rem or "[]"))
                d["skills_keep"] = want

        # Layer 2: the common capability baseline (union, every project but COMMON_EXCLUDE)
        notes += apply_common(fn, d)

        # Layer 3: plugins every project keeps on (union, every trimmed project, no exclude)
        notes += apply_common_plugins(fn, d)

        # Layer 4: file access for the design set, on the projects that carry it. Runs after
        # layers 1-2 so it sees the skills_keep those wrote, not the one on disk.
        notes += apply_design(d)

        seen[fn] = d
        if not notes:
            print("  = %-38s no change" % fn); continue
        changed += 1
        print("  ~ %-38s %s" % (fn, "; ".join(notes)))
        if APPLY:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=2); fh.write("\n")

    audit = audit_trim(seen)
    if audit:
        print()
        for line in audit:
            print(line)

    print("\n%d project(s) %s." % (changed, "updated" if APPLY else "would change"))
    if CHECK:
        return 1 if changed or skipped else 0
    if changed and not APPLY:
        print("Re-run with --apply, then: python scripts/sync/sync_agent_config.py --apply")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
