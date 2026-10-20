#!/usr/bin/env python3
"""Sync the canonical agent-system doc into every managed project + wire a pointer.

WHY
  Claude Code keeps breaking the shared config system through amnesia / editing the
  wrong (generated) file. The cure is one canonical explainer, present and current in every
  project, referenced from each project's CLAUDE.md so the agent reads it only when it's about
  to touch config.

  AGENTS.md is a symlink to CLAUDE.md, so Codex CLI reads the same rules Claude Code does; the
  WHY is in ensure_agents_md().

WHAT IT DOES (idempotent, dry-run by default)
  Canonical doc: forge/docs/AGENT-SYSTEM.md
  For each managed project (derived from config/profiles/*.claude.json project_path):
    1. copy the doc -> <project>/.claude/AGENT-SYSTEM.md  (with a GENERATED banner)
    2. ensure <project>/.gitignore ignores .claude/AGENT-SYSTEM.md
    3. ensure <project>/CLAUDE.md exists and contains the pointer block
       (replaced between stable markers -> never touches the rest of the file)
    4. make <project>/AGENTS.md a symlink to CLAUDE.md

  What it creates and could not recognise afterwards is recorded in the ownership record (forge/owned.py,
  part "system-doc"): the ignore line of step 2 and the link of step 4, each only when this run made it.
  The copy and the pointer block are recognisable by their content and markers, and need no claim.

USAGE
  python scripts/sync/sync_system_doc.py            # dry-run (prints what would change)
  python scripts/sync/sync_system_doc.py --apply     # write

Runs from `forge session-start`, scoped to the session's own project.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT_FS = ROOT.replace("\\", "/")  # forward-slash form for doc text
CANON = os.path.join(ROOT, "docs", "AGENT-SYSTEM.md")
sys.path.insert(0, ROOT)
from forge import lib, owned  # noqa: E402
# A SessionStart run writes its own project only; a refused --apply is a dry-run.
CTX = lib.context(sys.argv[1:])
PART = "system-doc"  # this script's share of the ownership record's claims on a file
LINK_VALUE = "symlink:CLAUDE.md"

GEN_BANNER = (
    "<!-- GENERATED — DO NOT EDIT. Synced from "
    + ROOT_FS + "/docs/AGENT-SYSTEM.md by "
    "scripts/sync/sync_system_doc.py. Edit the canonical copy in forge. -->\n\n"
)

BEGIN = "<!-- BEGIN LIFEOS-SYSTEM-POINTER (managed by sync_system_doc.py) -->"
END = "<!-- END LIFEOS-SYSTEM-POINTER -->"
# La linea en blanco tras BEGIN no es cosmetica. `gsd-tools
# generate-claude-md` normaliza el fichero dejando un renglon vacio entre el
# marcador y el encabezado; este guion lo escribia sin el. Los dos corren en cada
# SessionStart, asi que se lo quitaban y se lo ponian por turnos y CLAUDE.md
# aparecia sucio en `git status` para siempre. Un fichero permanentemente sucio
# ensena a la gente a no mirar `git status`, que es exactamente el modo de fallo
# que el .gitignore de otro proyecto lleva documentando: no da error,
# da silencio.
POINTER = (
    BEGIN + "\n\n"
    "## Shared agent-config system\n\n"
    "This project's MCP servers, skills, plugins, and memory are governed by a **shared system "
    "rooted in forge** (`" + ROOT_FS + "`). Generated files here "
    "(`.claude/settings.local.json`, `~/.claude.json`) are **overwritten on every "
    "SessionStart** — do not hand-edit them. `.mcp.json` is NOT one of them: nothing generates "
    "it, so it is yours to maintain and it will never be corrected.\n\n"
    "**Before changing any MCP server, skill, plugin, secret, or memory store, read "
    "[`.claude/AGENT-SYSTEM.md`](.claude/AGENT-SYSTEM.md)** — it explains what to edit in forge "
    "`config/` and which generator to run. Editing the wrong file silently breaks across "
    "sessions.\n"
    + END
)


def pointer(proj_dir, profs):
    """POINTER, plus a note when a frozen project lies below proj_dir. Claude Code loads a parent
    directory's CLAUDE.md in every session below it, so every session of a frozen project reads the dev
    profile's ~/dev/CLAUDE.md, whose "overwritten on every SessionStart" and AGENT-SYSTEM.md
    pointer are false for a frozen project: forge writes nothing there (a study of that project,
    section 1.3 point 3; plan step 4)."""
    frozen = sorted(n for n, p in profs.items() if p.get("frozen") and p.get("project_path")
                    and os.path.normpath(p["project_path"]).startswith(proj_dir + os.sep))
    if not frozen:
        return POINTER
    note = "".join(
        "**Not in `%s`, a frozen project:** forge writes nothing there, so its files are not "
        "regenerated at SessionStart and a `.claude/AGENT-SYSTEM.md` in it, if any, is a stale "
        "copy. Why, and how to lift it: `_frozen_doc` in `%s/config/profiles/%s.claude.json`.\n"
        % (os.path.normpath(profs[n]["project_path"]), ROOT_FS, n) for n in frozen)
    return POINTER[:-len(END)] + "\n" + note + END


def read_profiles():
    """({file name: profile} for every profile, read once; whether one was left out). One that
    cannot be read or is not a JSON object is named on a '!' line and left out: until attack round
    3 each of this script's three readers json.loaded every file unguarded, so one `{broken`,
    `null` or list profile aborted the whole run with a traceback and no project got its doc."""
    skipped = []
    profs = lib.profiles(skipped)
    for name, reason in skipped:
        print("  ! could not read %s: %s" % (os.path.join(lib.PROFILES, name), reason))
    return profs, bool(skipped)


def _read(p):
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


def ensure_doc_copy(proj_dir, changes):
    dst = os.path.join(proj_dir, ".claude", "AGENT-SYSTEM.md")
    want = GEN_BANNER + open(CANON, encoding="utf-8").read()
    if lib.holds(dst, want):
        return
    changes.append(("copy", dst))
    if CTX.apply:
        lib.write_text(dst, want)


def ensure_gitignore(proj_dir, changes):
    """Whether the doc may be written: git ignores it, or there is no git. Two of the managed
    directories are not checkouts -- ~/dev, which is where the omarchy repair agent runs, and
    a second plain project directory -- and a .gitignore there is a file no git will ever read. A
    .gitignore that is a symlink is not written through, and git does not read one: unless git
    ignores the doc some other way, that is reported, not repaired, and the doc is not copied."""
    if not lib.in_git_repo(proj_dir):
        return True
    gi = os.path.join(proj_dir, ".gitignore")
    ignored, suffix = lib.ensure_ignored(CTX.apply, proj_dir, ".claude/AGENT-SYSTEM.md", False)
    owned.claim_ignore_line(CTX.apply, proj_dir, ".claude/AGENT-SYSTEM.md", suffix, False, PART, "core")
    if not ignored:
        changes.append(("SKIP-gitignore(a symlink, which git does not read)", gi))
    elif suffix:
        changes.append(("gitignore", gi))
    return ignored


def claude_md_refused(proj_dir):
    """Why CLAUDE.md is not written, or None. lib.write_text writes a symlink's target, so a
    CLAUDE.md -> AGENTS.md put the pointer block into the user's real AGENTS.md; ensure_agents_md
    then found forge's markers there, took the file for forge's and replaced it with a link to
    CLAUDE.md -- CLAUDE.md -> AGENTS.md -> CLAUDE.md, the user's rules gone and neither file
    readable, while the dry-run said SKIP-agents-md(non-forge content) (found in an attack round).
    A hard link to AGENTS.md is the same file without a symlink: the temp-and-rename
    write split the pair. Either way neither step runs, as a symlinked .gitignore is refused.
    AGENTS.md -> CLAUDE.md is also one file under two names, and it is the layout this script
    makes, so an AGENTS.md link is not a reason."""
    claude_md, agents = os.path.join(proj_dir, "CLAUDE.md"), os.path.join(proj_dir, "AGENTS.md")
    if os.path.islink(claude_md):
        return "SKIP-claude-md(a symlink, which forge does not write through)"
    if os.path.isfile(claude_md) and os.path.isfile(agents) and not os.path.islink(agents) \
            and os.path.samefile(claude_md, agents):
        return "SKIP-claude-md(the same file as AGENTS.md)"
    return None


class MarkerError(ValueError):
    """CLAUDE.md holds a BEGIN or END marker that is not one complete ordered pair."""


def marker_error(text):
    """Why the markers in `text` are not forge's one complete pair, or None when they are (or there are none).
    The block is replaced from the first BEGIN to the first END, so a BEGIN quoted in prose or left orphaned
    started the replacement and the user's text up to the END went with it (found in an attack round: the
    second sync took a note away). The same rule ds_readiness applies to its stanza: a file whose markers are
    not one complete pair is refused and named, never guessed at."""
    nb, ne = text.count(BEGIN), text.count(END)
    if nb != ne:
        return "%d BEGIN and %d END marker(s), not one complete pair" % (nb, ne)
    if nb > 1:
        return "%d BEGIN...END pairs, forge writes one" % nb
    if nb and text.index(END) < text.index(BEGIN):
        return "the END marker comes before its BEGIN"
    return None


def ensure_pointer(proj_dir, fname, changes, text):
    p = os.path.join(proj_dir, fname)
    cur = _read(p)
    why = marker_error(cur) if cur is not None else None
    if why:
        raise MarkerError("%s: %s" % (fname, why))
    if cur is None:
        # create a minimal file that is just the pointer
        changes.append(("create", p))
        new = text + "\n"
        if CTX.apply:
            lib.write_text(p, new)
        return
    if BEGIN in cur and END in cur:
        pre = cur[: cur.index(BEGIN)]
        post = cur[cur.index(END) + len(END):]
        new = pre + text + post  # replace the managed block exactly, keep the rest
        if new == cur:
            return
        changes.append(("update-pointer", p))
        if CTX.apply:
            lib.write_text(p, new)
        return
    else:
        # append the pointer block at the end, preserving existing content
        changes.append(("append-pointer", p))
        sep = "" if cur.endswith("\n\n") else ("\n" if cur.endswith("\n") else "\n\n")
        new = cur + sep + "\n" + text + "\n"
        if CTX.apply:
            lib.write_text(p, new)


def claim_link(p, created):
    """The ownership record of the AGENTS.md link at `p`, kind `file`, whose value is LINK_VALUE. `created` is
    True when this run made the link, and it is claimed; None when the right link was already there, which
    may be the user's own, so it is claimed only if an earlier run claimed it; False when AGENTS.md is
    something forge leaves alone, and a claim of it goes. Nothing for a dry-run."""
    held = created is True or (created is None and owned.previous(p, PART)[0] != [])
    owned.record(p, [owned.claim("file", [], LINK_VALUE, "core")] if held else [], CTX.apply, PART)


def ensure_agents_md(proj_dir, changes):
    """AGENTS.md is a SYMLINK to CLAUDE.md, not a copy -- the precedent
    another project already set after living with the alternative:
    "Ahora es un enlace simbolico de 9 bytes a CLAUDE.md: se sigue, no puede divergir, y no
    hay duplicado que ignorar" (it's followed, can't diverge, no duplicate to ignore). Codex
    reads repository AGENTS.md as its durable-rules file the way Claude Code reads CLAUDE.md
    (confirmed via the bundled openai-docs reference) -- a symlink means both
    agents see identical rules always, with no regeneration step and nothing to keep in sync.

    SAFETY: only replaces an AGENTS.md that is absent, already the right symlink, or a real
    file recognizably forge-owned (contains BOTH the BEGIN and END pointer
    markers -- true of every stale hand-copy found on this machine except one: a Next.js project's
    AGENTS.md carries a Next.js-tool-injected compatibility warning with no such markers, and
    is deliberately left alone -- overwriting a build tool's own file destroys content this
    system did not create and cannot recreate. That skip is reported in `changes` like every
    other action, not silently.

    FIXED by adversarial haiku testing, which found the check originally required
    only BEGIN, not both markers -- a plain-text mention of the marker string (e.g. in
    documentation explaining how this generator works, or a code example) would have been
    enough to make real non-forge content look "forge-owned" and get destroyed. Requiring
    BOTH markers matches ensure_pointer()'s own, stricter block-replace condition, and a
    document merely discussing the marker in prose is exceedingly unlikely to also contain
    the exact END string.

    Also fixed the same pass: a symlink is never created pointing at a CLAUDE.md that does
    not exist (would silently leave Codex with nothing to read), and the file-replace uses a
    temp-symlink + os.replace swap instead of remove-then-symlink, so a crash or a
    concurrent writer between the two steps can never leave AGENTS.md simply missing."""
    p = os.path.join(proj_dir, "AGENTS.md")
    claude_md = os.path.join(proj_dir, "CLAUDE.md")
    if not os.path.exists(claude_md):
        changes.append(("SKIP-agents-md(no CLAUDE.md to point at)", p))
        return
    if os.path.islink(p):
        if os.readlink(p) == "CLAUDE.md":
            claim_link(p, None)
            return
        changes.append(("agents-md-relink", p))
        if CTX.apply:
            lib.replace_symlink("CLAUDE.md", p)
            claim_link(p, True)
        return
    cur = _read(p)
    if cur is not None and not (BEGIN in cur and END in cur):
        changes.append(("SKIP-agents-md(non-forge content)", p))
        claim_link(p, False)
        return
    changes.append(("agents-md-symlink", p))
    if CTX.apply:
        lib.replace_symlink("CLAUDE.md", p)
        claim_link(p, True)


def main():
    """Returns the exit code by forge/sync.py agent_config's rule: 1 exactly when a line printed
    here starts with '!' (a profile left out, a project missing on disk, one that raised), and the
    other projects still run. It once returned None, so every one of those exited 0."""
    if not os.path.exists(CANON):
        sys.exit("! canonical doc missing: %s" % CANON)
    print("MODE:", "APPLY" if CTX.apply else "DRY-RUN (pass --apply to write)")
    profs, failed = read_profiles()
    # Named by file, as --project and the session scope name them, in the order of their paths.
    managed = sorted(((n, p) for n, p in profs.items() if p.get("project_path")),
                     key=lambda kv: os.path.normpath(kv[1]["project_path"]))
    print("managed projects: %d (%d repo-owned)\n"
          % (len(managed), sum(lib.repo_owns_tracked_files(p) for _, p in managed)))
    total = []
    for tag, prof in managed:
        if not CTX.wants(tag):
            continue
        proj_dir = os.path.normpath(prof["project_path"])
        if not os.path.isdir(proj_dir):
            print("  ! %s missing on disk -- skipping" % proj_dir)
            failed = True
            continue
        changes = []
        if prof.get("frozen"):  # nothing written at all
            print("  = %-20s frozen: nothing written" % tag)
            continue
        try:
            if lib.repo_owns_tracked_files(prof):
                # Forge writes nothing git tracks here: no pointer block in CLAUDE.md, no AGENTS.md
                # symlink and no .gitignore line. The doc copy is still written, but only where the
                # repo's own ignore rules already cover it: a project whose
                # CLAUDE.md and AGENTS.md are versioned and owned by the repo -- with AGENTS.md the
                # canonical file, the symlink this script makes would have replaced it with a link
                # to CLAUDE.md.
                idle = "up to date (repo-owned: CLAUDE.md, AGENTS.md, .gitignore left alone)"
                if lib.git_ignores(proj_dir, ".claude/AGENT-SYSTEM.md"):
                    ensure_doc_copy(proj_dir, changes)
                else:
                    changes.append(("SKIP-doc(repo-owned .gitignore does not ignore it)",
                                    os.path.join(proj_dir, ".claude", "AGENT-SYSTEM.md")))
            else:
                idle = "up to date"
                # The ignore line first, so the doc never exists un-ignored; reported in the old order.
                ignore = []
                if ensure_gitignore(proj_dir, ignore):
                    ensure_doc_copy(proj_dir, changes)
                changes += ignore
                refused = claude_md_refused(proj_dir)
                if refused:
                    changes.append((refused, os.path.join(proj_dir, "CLAUDE.md")))
                else:
                    ensure_pointer(proj_dir, "CLAUDE.md", changes, pointer(proj_dir, profs))
                    ensure_agents_md(proj_dir, changes)
        except MarkerError as e:
            print("  ! %-20s %s -- left as it is, fix the markers by hand" % (tag, e))
            failed = True
            continue
        except Exception as e:
            # Adversarial testing: none of these four had a try/except, so a
            # permission error, a mid-write race, or any other exception on ONE project
            # aborted the whole 15-project run with a traceback -- projects sorted after the
            # failing one never got touched. One project's filesystem trouble should not
            # block every other project's sync.
            print("  ! %-20s ERROR: %s -- skipped, other projects unaffected" % (tag, e))
            failed = True
            continue
        print("  ~ %-20s %s" % (tag, ", ".join("%s:%s" % (a, os.path.basename(b)) for a, b in changes))
              if changes else "  = %-20s %s" % (tag, idle))
        total += changes
    print("\n%d change(s) %s." % (len(total), "applied" if CTX.apply else "would apply"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
