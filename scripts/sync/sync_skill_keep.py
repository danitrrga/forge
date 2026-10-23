#!/usr/bin/env python3
"""Resync the cross-profile capability baseline: which GLOBAL skills every project keeps,
plus the shared permission allowlist and env every project needs to use them.

WHY THIS EXISTS
  sync_agent_config.py full-replaces each project's settings.local.json `skillOverrides`
  every SessionStart (incl. /clear, resume, compact): "all global skills off EXCEPT
  project-local skills + this profile's skills_keep". So a skill absent from skills_keep
  gets disabled on the next /clear -- the flapping that silently killed GSD in one project.

  The fix is declarative: list the skills a project must keep in its profile's skills_keep.
  GSD is the canonical plan/execute loop (CLAUDE.md) so EVERY dev project keeps all gsd-*.
  This script regenerates those gsd-* lists from disk so new/removed gsd skills are picked
  up automatically -- run it after GSD adds or drops a skill, then run sync_agent_config.py.

  Project-LOCAL skills (.claude/skills/<name>/) are auto-kept by sync_agent_config.py and
  must NOT be listed here. Only GLOBAL skills (~/.claude/skills) need an entry.

THREE LAYERS (added for the agent-reach research stack; the tables named below are
config/forge.json skill_keep since T3 of docs/portable-design.md, and the gsd-* layers need the gsd integration on)
  1. gsd-* baseline   -- regenerated from disk. Full replace for profiles listed in EXTRAS,
                         union for every other trimmed profile. Now the only way
                         out is NO_GSD_BASELINE: registering a project is no longer what
                         decides whether it keeps up with GSD.
  2. EXTRAS           -- per-project additions beyond that baseline.
  2c. GSD_EXCLUDE / GSD_OPT_IN -- the user's own trim of the gsd-* names (skill_keep.gsd_exclude: in no
                         profile and not linked by relink_skills.py; gsd_opt_in: kept only by a profile whose
                         EXTRAS row names it). Applied last to the gsd-* names, authoritative.
  3. COMMON_*         -- the capability baseline that belongs in EVERY project:
                         COMMON_SKILLS / COMMON_PERMISSIONS / COMMON_ENV, UNION-merged
                         into every profile except COMMON_EXCLUDE. Union (not replace) so
                         hand-curated profiles (a study-skill set, an ssh permission set)
                         survive untouched.
  Before this existed there was no way to say "this global skill goes everywhere" -- a new
  cross-cutting skill had to be pasted into 13 profiles by hand.

USAGE
  python scripts/sync/sync_skill_keep.py            # dry-run (prints diffs)
  python scripts/sync/sync_skill_keep.py --apply     # write profiles
  python scripts/sync/sync_skill_keep.py --check     # the dry-run, exit 1 when a profile would change
                                                     # (forge doctor's "skill keep" row); never writes
  # then: python scripts/sync/sync_agent_config.py --apply   (propagate to settings.local.json)
"""
import json, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.expanduser("~")
GLOBAL_SKILLS = os.path.join(HOME, ".claude", "skills")
PROF = os.path.join(ROOT, "config", "profiles")
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
    """{profile file: names} with each `@NAME` replaced by sets[NAME]. A name no set answers to
    exits 1: left as it is, `@NAME` would be written into a profile as a skill."""
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
NO_GSD_BASELINE = set(SKILL_KEEP.get("no_gsd_baseline") or [])
COMMON_SKILLS = SKILL_KEEP.get("common_skills") or []
COMMON_PERMISSIONS = SKILL_KEEP.get("common_permissions") or {"allow": []}
COMMON_ENV = {k: os.path.expanduser(v) for k, v in (SKILL_KEEP.get("common_env") or {}).items()}
COMMON_PLUGINS = SKILL_KEEP.get("common_plugins") or []
COMMON_OPT_OUT = {fn: set(names) for fn, names in (SKILL_KEEP.get("common_opt_out") or {}).items()}
COMMON_EXCLUDE = set(SKILL_KEEP.get("common_exclude") or [])
# gsd_exclude: skills this user does not want at all (relink_skills.py also stops linking them).
# gsd_opt_in: skills linked but in no baseline, kept only by a profile whose extras row names them.
GSD_EXCLUDE = set(SKILL_KEEP.get("gsd_exclude") or [])
GSD_OPT_IN = set(SKILL_KEEP.get("gsd_opt_in") or [])
# The gsd-* baseline is the gsd integration's. Off, a profile keeps the gsd-* names it holds and none is added.
TRACK_GSD = lib.on("gsd")


def union(existing, additions):
    """Order-preserving union: keep what's there, append what's missing."""
    return list(dict.fromkeys(list(existing or []) + list(additions)))


def common_for(fn, names):
    """The COMMON names this profile takes: all of them minus its COMMON_OPT_OUT entry."""
    out = COMMON_OPT_OUT.get(fn, set())
    return [n for n in names if n not in out]


def strip_opted_out(fn, d, key):
    """An opt-out is authoritative: a name it lists is removed from the profile too, so taking a
    COMMON name out is one edit here rather than an edit here plus one in the profile."""
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
    """Union COMMON_PLUGINS into one profile's plugins_keep. Separate from apply_common()
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
    """Give a profile that carries the design set the file access those skills need.
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
    """Union COMMON_SKILLS / COMMON_PERMISSIONS / COMMON_ENV into one profile dict.
    Returns a list of human-readable change descriptions (empty = already in sync)."""
    if fn in COMMON_EXCLUDE:
        return []
    changes = []

    # skills -- trimmed profiles only (see COMMON_SKILLS note above). A ["*"] profile already
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


def gsd_skills(installed):
    skills = sorted(d for d in installed if d.startswith("gsd-") and d not in GSD_EXCLUDE | GSD_OPT_IN)
    if not skills:
        sys.exit("! no gsd-* skills found in %s -- aborting (refusing to wipe keep-lists)" % GLOBAL_SKILLS)
    return skills


def check_gsd_tables(installed):
    """Exit 1 on a gsd_exclude / gsd_opt_in table that cannot mean what it says: a name that no skill
    answers to (a typo trims nothing), a name in both tables, or an extras row asking for a skill the
    user excluded. A name counts as existing when skills/ holds it, since an excluded skill is no
    longer in the mirror."""
    src = os.path.join(ROOT, "skills")
    known = installed | (set(os.listdir(src)) if os.path.isdir(src) else set())
    bad = []
    for table, names in (("gsd_exclude", GSD_EXCLUDE), ("gsd_opt_in", GSD_OPT_IN)):
        bad += ["skill_keep.%s names %s, which is in neither skills/ nor %s" % (table, n, GLOBAL_SKILLS)
                for n in sorted(names - known)]
    bad += ["skill_keep.gsd_exclude and skill_keep.gsd_opt_in both name %s" % n
            for n in sorted(GSD_EXCLUDE & GSD_OPT_IN)]
    bad += ["skill_keep.extras[%s] names %s, which skill_keep.gsd_exclude drops" % (fn, n)
            for fn, names in sorted(EXTRAS.items()) for n in sorted(set(names) & GSD_EXCLUDE)]
    if bad:
        sys.exit("! config/forge.json:\n    " + "\n    ".join(bad))


def apply_gsd_trim(fn, d):
    """Authoritative, as strip_opted_out is for COMMON: an excluded name is removed from every
    trimmed profile, an opt-in name from every profile whose extras row does not name it."""
    cur = d.get("skills_keep")
    if not isinstance(cur, list) or "*" in cur:
        return []
    own = set(EXTRAS.get(fn, []))
    kept = [n for n in cur if n not in GSD_EXCLUDE and (n not in GSD_OPT_IN or n in own)]
    if kept == cur:
        return []
    d["skills_keep"] = kept
    return ["gsd trim -%s" % sorted(set(cur) - set(kept))]


def check_declared(installed):
    """Fail loudly on a skill name this script would write that no longer exists.

    Set subtraction in sync_agent_config.py makes a dangling `skills_keep` entry a silent
    no-op, so a renamed or deleted skill used to sit in the profiles forever while the
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
            bad.append("COMMON_OPT_OUT[%s] -> no such profile" % fn)
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


def audit_trim(profiles):
    """Two states that look like configuration and are really accidents.

    EMPTY skills_keep: trimming is ON and nothing is kept, so every global skill is off. That
    is what one project shipped with from the day the new-project skill created it -- 25 GSD
    skills and the whole COMMON layer dark for its entire life, surfacing only as "that command
    does nothing". Nobody has ever wanted this state on purpose.

    NO GSD AT ALL: a trimmed profile that opted out of the baseline. Printed so the opt-out
    stays a visible decision rather than a thing nobody remembers choosing."""
    notes = []
    for fn, d in profiles.items():
        sk = d.get("skills_keep")
        if sk is None:
            continue
        if sk == []:
            notes.append("! %s has skills_keep: [] -- trimming ON, every global skill off. "
                         "Add it to EXTRAS (or delete the key to stop trimming)." % fn)
            continue
        if fn in NO_GSD_BASELINE:
            gsd_names = [s for s in sk if s.startswith("gsd-")]
            notes.append("  note: %s does not track the GSD baseline (keeps %d gsd-* skills of "
                         "its own choosing)." % (fn, len(gsd_names)))
    return notes


def main():
    installed = installed_skills()
    check_gsd_tables(installed)
    check_declared(installed)
    gsd = gsd_skills(installed) if TRACK_GSD else []
    print("MODE:", "APPLY" if APPLY else "DRY-RUN (pass --apply to write)")
    print("gsd-* skills on disk: %d | COMMON: %d skills, %d perms, %d env, %d plugins | excluded: %d | gsd excluded: %d, opt-in: %d\n"
          % (len(gsd), len(COMMON_SKILLS), len(COMMON_PERMISSIONS["allow"]),
             len(COMMON_ENV), len(COMMON_PLUGINS), len(COMMON_EXCLUDE), len(GSD_EXCLUDE), len(GSD_OPT_IN)))

    for fn in EXTRAS:
        if not os.path.exists(os.path.join(PROF, fn)):
            print("  ! %s listed in EXTRAS but missing on disk" % fn)

    changed = 0
    seen = {}
    # The files lib.profiles() reads (config/profiles/*.claude.json), read the way it reads them:
    # one that cannot be read, is not an object or has a field of the wrong type is named and
    # skipped, the rest still run, and the exit is 1 at the end (a '!' line means exit 1).
    skipped = []
    profs = {name + ".claude.json": d for name, d in lib.profiles(skipped).items()}
    for fn, why in sorted(skipped):
        print("! %s unreadable: %s -- skipped" % (fn, why))
    for fn in sorted(profs):
        p = os.path.join(PROF, fn)
        d = profs[fn]
        notes = []

        # Layer 0: drop names no installed skill answers to (self-heals after a deletion)
        notes += prune_dangling(d, installed)

        # Layer 1+2: gsd-* baseline + per-project extras (full replace, EXTRAS profiles only)
        if fn in EXTRAS:
            # COMMON_SKILLS folded in HERE too -- this branch full-replaces skills_keep, so
            # leaving them to apply_common's union below would strip and re-add them every
            # run (a rewrite + churn on each invocation instead of a clean no-op).
            if fn in NO_GSD_BASELINE or not TRACK_GSD:
                # Profile curates its own gsd-* subset: keep what it declares, never top up.
                base = [s for s in (d.get("skills_keep") or []) if s.startswith("gsd-")]
            else:
                base = gsd
            want = base + sorted(EXTRAS[fn])
            if fn not in COMMON_EXCLUDE:
                want = union(want, common_for(fn, COMMON_SKILLS))
            old = d.get("skills_keep", [])
            if sorted(old) != sorted(want):
                add = sorted(set(want) - set(old)); rem = sorted(set(old) - set(want))
                notes.append("gsd/extras +%s -%s" % (add or "[]", rem or "[]"))
                d["skills_keep"] = want

        # Layer 2b: every OTHER trimmed profile still tracks the gsd-* baseline, by union.
        #
        # WHY THIS EXISTS. Layer 1 only ever ran for profiles listed in EXTRAS, so
        # a project got new GSD skills only if somebody had remembered to register it. Nobody
        # remembers: one project sat on the GSD of the day it was written (25 skills, August), the
        # another on one, a third on two, and two more would have missed
        # gsd-map-codebase the day it appeared. The registration step was load-bearing and
        # invisible, which is the same shape as the bug that left one project with nothing.
        #
        # So the default inverted: a trimmed profile tracks GSD unless it is in
        # NO_GSD_BASELINE. Union, never replace -- this branch must not touch a single
        # hand-curated name, it only adds what the baseline gained.
        elif (TRACK_GSD and fn not in NO_GSD_BASELINE and "skills_keep" in d
              and "*" not in (d["skills_keep"] or [])):
            want = union(d["skills_keep"], gsd)
            if want != d["skills_keep"]:
                notes.append("gsd baseline +%s" % sorted(set(want) - set(d["skills_keep"])))
                d["skills_keep"] = want

        # Layer 2c: the user's own trim of the gsd-* names (gsd_exclude, gsd_opt_in), after the union above
        notes += apply_gsd_trim(fn, d)

        # Layer 3: the common capability baseline (union, every profile but COMMON_EXCLUDE)
        notes += apply_common(fn, d)

        # Layer 4: plugins every project keeps on (union, every trimmed profile, no exclude)
        notes += apply_common_plugins(fn, d)

        # Layer 5: file access for the design set, on the profiles that carry it. Runs after
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

    print("\n%d profile(s) %s." % (changed, "updated" if APPLY else "would change"))
    if CHECK:
        return 1 if changed or skipped else 0
    if changed and not APPLY:
        print("Re-run with --apply, then: python scripts/sync/sync_agent_config.py --apply")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
