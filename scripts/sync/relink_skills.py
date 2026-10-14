#!/usr/bin/env python3
"""relink_skills.py — keep global skill dirs synced to the single source of truth.

Source of truth:  forge/skills/    (every global skill is FULLY written here)
Mirrors (links):  ~/.claude/skills   (Claude Code)
                  $CODEX_HOME/skills (Codex CLI, ~/.codex/skills by default — same SKILL.md
                  frontmatter format, added so both agents see the identical skill set)

Non-destructive & idempotent: only CREATES / REPOINTS symlinks and PRUNES
dangling ones. Never deletes or overwrites real skill content. Safe to run on
every session start. Run manually after adding a skill:  python relink_skills.py

Project-dependent technical skills do NOT live here — they belong in the
consuming project's .claude/skills (e.g. Tauri skills -> an-app/.claude/skills).

(Ported from relink_skills.ps1 for Linux: Windows junctions -> POSIX symlinks.)
"""
import errno
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from forge import lib  # noqa: E402
HOME = lib.HOME
SRC = os.path.join(ROOT, "skills")
TARGETS = [
    os.path.join(HOME, ".claude", "skills"),
    os.path.join(lib.CODEX_HOME, "skills"),
]
CODEX_TARGET = TARGETS[1]  # only while integrations.codex is on in config/forge.json

# Skills provided by an installed plugin (superpowers) — kept real in the source
# but NOT mirrored, to avoid duplicate listings with the plugin.
DUPES = {
    "test-driven-development", "writing-plans", "systematic-debugging",
    "executing-plans", "verification-before-completion", "writing-skills",
}


def skill_names():
    return [
        d for d in os.listdir(SRC)
        if os.path.isdir(os.path.join(SRC, d))
        and not d.startswith("_") and not d.startswith(".")
        and d not in DUPES
    ]


def ensure_memory_link():
    """Native Claude memory is DISABLED: project memory now comes from
    Hindsight or the project's claude-mem-lite store, not an in-repo
    file-per-fact store or the Obsidian Vault.
    So each SessionStart removes the `memory` symlink under forge's own key,
    ~/.claude/projects/<forge-key>/memory, when it points at forge/memories: a leftover of the
    layout from before a project split, which bound curated memories/ files to the
    harness's native recall. Only that link goes, never its target; a real directory there
    (which the harness may create) is left untouched."""
    key = ROOT.replace("/", "-")
    link = os.path.join(HOME, ".claude", "projects", key, "memory")
    target = os.path.join(ROOT, "memories")
    try:
        # Only remove our own symlink into <root>/memories — never the target dir itself.
        if os.path.islink(link):
            if os.path.realpath(link) == os.path.realpath(target):
                lib.unlink(link)
                print("relink_skills: native memory unlinked (disabled — see CLAUDE.md)")
            return
    except Exception as e:
        print("relink_skills: memory unlink failed: %s" % e)


def main():
    # Applies unless --dry-run (forge sync without --apply); SessionStart runs it plain.
    ctx = lib.context(sys.argv[1:], flag="--dry-run", invert=True)
    if not ctx.globals:
        return 0  # user-scope files; a SessionStart outside forge leaves them alone
    dry = not ctx.apply
    if not dry:
        ensure_memory_link()
    names = skill_names() if os.path.isdir(SRC) else []
    if not names:
        # A checkout with no skills/ (a stranger's, before it has any) or none in it: no mirror is
        # made and no link is touched. Said, so a run that did nothing is not mistaken for one that
        # linked everything.
        print("relink_skills: SKIP -- %s, so there is nothing to link" %
              ("skills/ holds no skill" if os.path.isdir(SRC) else "no skills/ directory"))
        return 0
    created = pruned = 0
    blocked = []
    # A link that cannot be made, repointed or pruned (a read-only or full mirror) is named here
    # and the run goes on: the first one once ended it with a traceback, leaving the
    # other skills and the other mirror undone.
    failed = []

    def fail(p, e):
        failed.append("%s (%s)" % (p, e.strerror or e))

    skipped_targets = []
    # $CODEX_HOME/skills only while Codex is on (config/forge.json): off, it is not made or pruned.
    for t in TARGETS if lib.on("codex") else [x for x in TARGETS if x != CODEX_TARGET]:
        if os.path.islink(t):
            # t is supposed to be a real directory this script owns and fully controls the
            # contents of (create/repoint/prune symlinks freely). If it's ACTUALLY a symlink
            # -- pointing anywhere, including a perfectly legitimate spot someone set up on
            # purpose -- the prune loop below would delete dangling links living in whatever
            # directory that symlink resolves to, not in a mirror forge created. Found by
            # adversarial testing. Refuse rather than guess.
            skipped_targets.append(t)
            continue
        if not dry:
            try:
                os.makedirs(t, exist_ok=True)
            except OSError as e:
                fail(t, e)
                continue
        elif os.path.lexists(t) and not os.path.isdir(t):
            # What the apply's makedirs raises on a file there, named the same way.
            fail(t, FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST)))
            continue
        # A dry-run over a mirror that does not exist yet goes on: every link below counts as
        # created and the listdir finds nothing to prune. An attack round found that it
        # skipped the mirror before counting, so a fresh HOME or a new CODEX_HOME previewed as
        # nothing to do while the apply made every link.

        # A link counted as repointed is not also pruned: a dangling one named after a current
        # skill is repointed, and only the dry-run, which leaves it dangling, then counted it again
        # as pruned (found in an attack round). A repoint that failed is not in here, so the
        # prune still tries it, as before.
        repointed = set()
        for n in names:
            link = os.path.join(t, n)
            target = os.path.join(SRC, n)
            try:
                if os.path.islink(link):
                    if os.path.realpath(link) != os.path.realpath(target):
                        if not dry:
                            lib.replace_symlink(target, link)
                        created += 1
                        repointed.add(n)
                elif os.path.exists(link):
                    # A REAL dir/file with this name exists in the mirror — a skill
                    # authored in the wrong place. Don't auto-destroy; surface it.
                    blocked.append(link)
                else:
                    if not dry:
                        lib.symlink(target, link)
                    created += 1
            except OSError as e:
                fail(link, e)

        # Prune dangling symlinks: ones we manage (into SRC, source skill removed) AND
        # any other dead link sitting in the mirror (e.g. links from before a repo split into the
        # old skills directory, which no longer exists) — a broken link is never useful
        # regardless of what it used to point to.
        try:
            entries = os.listdir(t)
        except FileNotFoundError:
            entries = []
        except OSError as e:
            fail(t, e)
            entries = []
        for d in entries:
            p = os.path.join(t, d)
            if d in repointed:
                continue
            if os.path.islink(p) and not os.path.exists(p):
                try:
                    if not dry:
                        lib.unlink(p)
                    pruned += 1
                except OSError as e:
                    fail(p, e)

    if created or pruned or blocked or skipped_targets or failed:
        # A leading '!' exactly when the run exits 1: forge/sync.py agent_config's exit rule, which
        # forge/cli.py's CHANGED shows at session start.
        msg = "%srelink_skills: %d skills | %d %slinked, %d %spruned" % (
            "! " if failed else "", len(names), created, "would be " if dry else "", pruned,
            "would be " if dry else "")
        if blocked:
            msg += " | BLOCKED(real dir in mirror): " + ", ".join(blocked)
        if skipped_targets:
            msg += " | SKIPPED(target is a symlink, not managed): " + ", ".join(skipped_targets)
        if failed:
            msg += " | FAILED: " + ", ".join(failed)
        print(msg)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
