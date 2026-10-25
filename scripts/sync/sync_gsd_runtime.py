#!/usr/bin/env python3
"""Regenerate the whole GSD surface from the npm package, with forge's edits re-applied.

WHAT THIS REPLACES
  GSD ships as `@opengsd/gsd-core` on npm (the archived `get-shit-done-cc` before 2026-10), installed by mise
  as the `npm:@opengsd/gsd-core` tool of config/toolchain.json. Its own installer writes the agents
  (~/.claude/agents/gsd-*.md), the engine (~/.claude/gsd-core/) and its skills
  (~/.claude/skills/gsd-*/SKILL.md). Three things make running that installer against the real
  ~/.claude unacceptable here, all verified:

  1. IT WRITES THROUGH OUR SYMLINKS, INTO THIS REPO. ~/.claude/skills/gsd-* are symlinks to
     forge/skills/. The installer's wipe loop skips them (a symlink is not a directory to
     readdir), then writes `skills/<name>/SKILL.md` straight through the link. Measured in a
     sandbox: a file whose only content was "FORGE OWNED CONTENT — must survive" came back as
     upstream's plan-phase skill. Every forge edit to a gsd-* skill dies that way, inside git,
     with no message.
  2. IT INSTALLS EVERY SKILL IN THE PACKAGE (67 in 1.42.3). forge ships a small subset on
     purpose (the description of every skill is loaded into every session); `--skills` prints
     the live counts. After an install, sync_skill_keep.py would read every gsd-* name off disk
     and push all of them into every project's keep list.
  3. IT OVERWRITES THE AGENTS AND THE ENGINE, which is where our edits live -- including the
     93-line Output Discipline section (config/gsd/output-discipline.md) that tells every GSD
     agent to name the thing instead of the identifier and to cut repetition, not content.

  So the installer never touches ~/.claude. It runs into a STAGING config dir instead, and this
  script copies out of the staging tree, re-applying forge's patches on the way. That also makes
  the runtime reproducible: staged output + patches == what is on disk, checked every run.

  Verified equivalence: normalising the staging path back to $HOME/.claude makes
  every engine file and every agent identical to what was installed earlier, except the
  files forge patches. The `$HOME/.claude/...` spelling in those files is the installer's own
  output for a global install, not a hand edit.

WHAT FORGE SYNCS (the whole of gsd-core, no cap)
  Every agent, the whole engine, the scripts it requires (staged scripts/ to ~/.claude/scripts, minus changeset/,
  which is the package's own release tooling), every skill (--skills) and every hook script (staged hooks/ to ~/.claude/hooks, but
  the two files forge keeps its own hardened version of): forge/hooks.py wires them (GSD_CORE_ROWS). forge sets no GSD
  default (config/gsd/defaults.md).

WHAT FORGE OWNS ON TOP
  * output discipline -- the block appended to references/mandatory-initial-read.md, which the
    five document-writing GSD agents import. Kept as a file (config/gsd/output-discipline.md) so
    it stays editable prose, not a Python string.
  * doc-classifier hash -- the agent is told to name its output file with 8 hex chars of the
    SHA-256 of the source path, and given `Read, Write, Grep, Glob`. No shell: it CANNOT hash.
    Four classifiers in one project invented the suffix, two said so. The hash is what keeps two
    `README.md` files in different folders from overwriting each other's classification. Fixed on
    the orchestrator side: ingest-docs computes it and passes SOURCE_HASH.
  * research routing -- researchers are told to check an `exa_search` flag that is only true with
    an Exa API key in ~/.gsd. There is no key here: Exa is keyless through the agent-reach skill
    (mcporter). Unpatched, every research phase concludes it has no semantic search. GSD's own
    `agent_skills` injection cannot carry agent-reach either -- `global:agent-reach` resolves the
    symlink and its path check rejects anything outside ~/.claude/skills ("Path escapes allowed
    directory", measured).
  * spike free-form -- workflows/spike.md gets the block of config/gsd/spike-freeform.md first, and the gsd-spike skill
    loses its "Preserve all workflow gates" sentence: the main agent runs the experiments itself so the owner can steer,
    each gate becomes a turn boundary, and only the state other GSD commands read back (README verdicts, MANIFEST.md) and the
    commit stay mandatory.
  * (retired with gsd-core 1.18: the planner now has Edit, and the config skill names the right package.)
  * (retired: the graphify and MemPalace router rows are back, every upstream skill ships now.)
  * quick lean path -- config/gsd/quick-lean.md goes first in workflows/quick.md: with no flag the task is done in the main
    thread (no planner, executor, checker or verifier subagent), and only the state GSD reads back is written (a minimal
    PLAN.md, which the gsd-quick skill's `status` and `resume` read, the SUMMARY.md with `status: complete`, the STATE.md
    row, the commits). The four flags bring the full pipeline back. The gsd-quick skill's two sentences that told the
    agent to spawn a planner and an executor and to preserve every gate are replaced to match (SKILL_PATCHES).
  * update route -- the update skill is rewritten to run the procedure below instead of the
    installer, for reason 1 above.

  forge-authored skills (gsd-musk, gsd-cut-the-ceremony, gsd-boil-the-ocean) have
  no upstream counterpart. They are never generated and never touched here. gsd-sketch is
  forge-authored too: upstream ships one, forge replaced it with a thin wrapper that
  files the project's design skill under .planning/sketches/, so the package's copy is neither
  compared nor written.

AN ANCHOR THAT NO LONGER MATCHES IS AN ERROR, NOT A SKIP. If upstream rewrites a patched
paragraph, this exits 1 naming the patch, because silently dropping a fix is how the classifier
bug would have come back unnoticed. The file that patch belongs to is not written: the patched
copy already on disk stays until the anchor is re-derived.

UPDATING GSD
  # set the new version of npm:@opengsd/gsd-core in config/toolchain.json, then:
  python3 bin/forge toolchain --fix                            # mise installs it
  python3 bin/forge skills                                     # dry-run: what changes, what is new
  python3 bin/forge skills --apply                             # write agents, engine, forge skills
  python3 bin/forge sync --apply --all

USAGE
  python3 scripts/sync/sync_gsd_runtime.py            # dry-run: agents + engine + checks
  python3 scripts/sync/sync_gsd_runtime.py --apply    # write agents + engine (`forge skills --apply` runs this)
  --skills        also compare (and with --apply, rewrite or create) forge/skills/gsd-*: every skill of the package
                  is shipped, the ones forge has not written yet are new
  --restage       force a fresh staging install even if the package version has not changed
  --check         read-only, for session start: no restage, no write; exit 0 when the runtime is what
                  --apply would write, 2 when it differs (a file, or a staging made for another package
                  version), 1 on an error
  --check-npm     ask npm right now (with --apply a throttled check runs on its own, once a day,
                  and says nothing unless a newer version exists)
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from forge import lib  # noqa: E402
HOME = lib.HOME
AGENTS_DIR = os.path.join(HOME, ".claude", "agents")
PACKAGE = "@opengsd/gsd-core"
GSD_DIR = os.path.join(HOME, ".claude", "gsd-core")
# The engine requires ../../../scripts/{fix-slash-commands,gen-capability-registry}.cjs from gsd-core/bin/lib, so
# staged scripts/ sits beside gsd-core/ (gsd-core 1.18: without it gsd-tools.cjs dies with MODULE_NOT_FOUND).
SCRIPTS_DIR = os.path.join(HOME, ".claude", "scripts")
HOOKS_DIR = os.path.join(HOME, ".claude", "hooks")
SKILLS_MIRROR = os.path.join(HOME, ".claude", "skills")
FORGE_SKILLS = os.path.join(ROOT, "skills")
BLOCKS = os.path.join(ROOT, "config", "gsd")
# Outside the repo on purpose: a staging install is megabytes of generated files with no business
# in git, and state/ here is tracked.
STAGE_ROOT = os.path.join(HOME, ".cache", "forge", "gsd-stage")
STAGE = os.path.join(STAGE_ROOT, "cfg")
STAMP = os.path.join(STAGE_ROOT, "STAGED-VERSION")
NPM_STAMP = os.path.join(STAGE_ROOT, "NPM-CHECKED")
GSD_DEFAULTS = os.path.join(HOME, ".gsd", "defaults.json")  # GSD's user-level defaults, a copy of BLOCKS/defaults.json

# A run outside forge, or a refused --apply, leaves the user-scope files alone.
CTX = lib.context(sys.argv[1:])
DO_SKILLS = "--skills" in sys.argv
RESTAGE = "--restage" in sys.argv
CHECK_NPM = "--check-npm" in sys.argv
CHECK = "--check" in sys.argv
DIFFERS = 2  # --check's exit code for a runtime that differs; 1 stays "something is wrong"

# Skills forge authored itself -- no upstream file, never generated, never overwritten.
FORGE_AUTHORED = {"gsd-musk", "gsd-cut-the-ceremony", "gsd-boil-the-ocean", "gsd-sketch"}

# The two hook files forge keeps its own version of (hooks/ of this checkout, hardened; forge/hooks.py wires them
# from there) and the scripts of the other runtimes the installer stages: not copied to ~/.claude/hooks.
HOOKS_NOT_COPIED = ("gsd-prompt-guard.js", "gsd-read-injection-scanner.js")

# What config/gsd/defaults.json held before forge stopped capping GSD. A ~/.gsd/defaults.json with
# exactly these bytes is forge's own stale copy, not the user's, and is replaced.
FORMER_DEFAULTS = ('{\n  "workflow": {\n    "ui_phase": false,\n    "ui_safety_gate": false\n  }\n}\n',)


def scripts_wanted(rel):
    """Whether the staged scripts/<rel> is copied into ~/.claude/scripts: all of it but changeset/, the package's own
    release tooling, which the engine never requires."""
    return not rel.startswith("changeset" + os.sep)


def hook_wanted(rel):
    """Whether the staged hooks/<rel> is copied into ~/.claude/hooks."""
    return rel not in HOOKS_NOT_COPIED and not rel.startswith(("gsd-cursor", "gsd-windsurf"))

# --------------------------------------------------------------------------------------
# Patches. Each is (id, op, anchor, payload): "replace" swaps anchor for payload, "append" adds
# payload at the end of the file and uses the anchor only to prove it is the right file.
# A payload of "file:<name>" is read from config/gsd/<name>.
# --------------------------------------------------------------------------------------

CLASSIFIER_OLD = (
    "Write to `{OUTPUT_DIR}/{slug}-{source_hash}.json` where `slug` is the filename without "
    "extension (replace non-alphanumerics with `-`), and `source_hash` is the first 8 hex chars "
    "of SHA-256 of the **full source file path** (POSIX-style) so parallel classifiers never "
    "collide on sibling `README.md` files."
)
CLASSIFIER_NEW = (
    "Write to `{OUTPUT_DIR}/{slug}-{SOURCE_HASH}.json` where `slug` is the filename without "
    "extension (replace non-alphanumerics with `-`), and `SOURCE_HASH` is the value handed to "
    "you in the prompt: the first 8 hex chars of SHA-256 of the full source file path "
    "(POSIX-style), so parallel classifiers never collide on sibling `README.md` files.\n\n"
    "**Do not compute the hash yourself and do not invent one.** You have `Read, Write, Grep, "
    "Glob` and no shell, so you cannot hash anything; a made-up suffix defeats the collision "
    "guard, and two `README.md` files from different folders then overwrite each other's "
    "classification. If `SOURCE_HASH` is missing from the prompt, write "
    "`{OUTPUT_DIR}/{slug}.json` and say in your one-line confirmation that SOURCE_HASH was not "
    "supplied, so the orchestrator can catch the collision risk instead of inheriting it."
)

REACH_BLOCK = """### Semantic Search + Page Reads (agent-reach)

This machine has no Exa API key and no `exa_search` flag — ignore both. Exa reaches you
keyless through the **agent-reach** skill, which also covers clean page reads, GitHub and
video transcripts. Do not report "no search available": you have it.

```bash
mcporter call exa.web_search_exa query="your semantic query" numResults=8
curl -s "https://r.jina.ai/https://docs.example.com/guide"   # one page -> clean markdown
gh search repos "your query" --sort stars --limit 10
```

**Best for:** research questions where keyword search fails — "best approaches to X", niche
libraries, ecosystem exploration. Read the full routing table (Reddit, X, YouTube, RSS, ~190
`oc` adapters) at @$HOME/.claude/skills/agent-reach/SKILL.md before reaching for WebSearch.
Announce the route ("agent-reach → exa") and never silently substitute one source for another.
"""

# gsd-core 1.18 replaced the "Exa Semantic Search (MCP)" section with a fetch plan (`gsd_run query research-plan`)
# whose provider table ends in this line, in both researchers; Exa is still only a provider when the exa_search
# flag is true, which needs a key, so the routing block goes right after it.
RESEARCHER_TABLE_END = "For any other provider id `X` not listed above: use `mcp__X__*` if available, else fall back to `WebSearch`."

UI_RESEARCHER_OLD = (
    "**Exa/Firecrawl:** Check `exa_search` and `firecrawl` from orchestrator context. "
    "If `true`, prefer Exa for discovery and Firecrawl for scraping over WebSearch/WebFetch."
)
UI_RESEARCHER_NEW = (
    "**Exa/Firecrawl:** Ignore the `exa_search` flag — this machine has no Exa API key and "
    "does not need one. Exa is keyless here through the **agent-reach** skill: "
    "`mcporter call exa.web_search_exa query=\"...\" numResults=8`, with "
    "`curl -s \"https://r.jina.ai/<url>\"` for a clean page read. Full routing table at "
    "@$HOME/.claude/skills/agent-reach/SKILL.md. Firecrawl stays flag-gated: it exists only in "
    "the projects whose profile lists it. Prefer both over "
    "WebSearch/WebFetch."
)

AGENT_PATCHES = {
    "gsd-doc-classifier.md": [("classifier-hash", "replace", CLASSIFIER_OLD, CLASSIFIER_NEW)],
    "gsd-project-researcher.md": [("reach-routing", "replace", RESEARCHER_TABLE_END, RESEARCHER_TABLE_END + "\n\n" + REACH_BLOCK)],
    "gsd-phase-researcher.md": [("reach-routing", "replace", RESEARCHER_TABLE_END, RESEARCHER_TABLE_END + "\n\n" + REACH_BLOCK)],
    "gsd-ui-researcher.md": [("reach-routing", "replace", UI_RESEARCHER_OLD, UI_RESEARCHER_NEW)],
}

INGEST_OLD = """Per-spawn prompt fields:
- `FILEPATH` — absolute path to the doc
"""
INGEST_NEW = """Before spawning, compute one collision-proof suffix per doc — the classifier
has no shell and cannot do this itself:

```bash
for f in <the discovered docs>; do
  printf '%s %s\\n' "$f" "$(printf '%s' "$f" | sha256sum | cut -c1-8)"
done
```

Per-spawn prompt fields:
- `FILEPATH` — absolute path to the doc
- `SOURCE_HASH` — the 8-hex-char suffix computed above for THIS doc. Mandatory: without it
  two `README.md` files from different folders write the same classification file and one
  silently overwrites the other.
"""

ENGINE_PATCHES = {
    # gsd-spike is free-form and run by the main agent so the owner can steer it: the block (config/gsd/spike-freeform.md) goes
    # first in the workflow. The anchor is the whole first line of upstream's file, so a rewrite is an error, not a skip.
    "workflows/spike.md": [("spike-freeform", "replace", "<purpose>", "file:spike-freeform.md")],
    "workflows/ingest-docs.md": [("classifier-hash-dispatch", "replace", INGEST_OLD, INGEST_NEW)],
    "references/mandatory-initial-read.md": [
        ("output-discipline", "append",
         "**CRITICAL: Mandatory Initial Read**", "file:output-discipline.md"),
    ],
    # The anchor is the whole first line, so an upstream rewrite of it is an error, never a silent skip.
    "workflows/quick.md": [("forge-lean-path", "replace", "<purpose>", "file:quick-lean.md")],
}

UPDATE_OLD = """<objective>
Check for GSD updates, install if available, and display what changed."""
UPDATE_NEW = """<objective>
**STOP. On this machine GSD is NOT updated by this skill.** Running the GSD installer against
`~/.claude` destroys forge's copy of every `gsd-*` skill: those paths are symlinks into
forge's `skills/` directory, the installer's wipe loop skips symlinks and then
writes through them, so upstream text lands inside the repo (measured in a sandbox).
It also installs every skill in the package where forge ships a small subset, and overwrites
the patched agents and the Output Discipline rules in the engine.

Run this instead, from the forge checkout (the directory that holds `bin/forge`), and report
what it prints:

```bash
# set the new version of npm:@opengsd/gsd-core in config/toolchain.json, then:
python3 bin/forge toolchain --fix
python3 bin/forge skills
python3 bin/forge skills --apply
python3 bin/forge sync --apply --all
```

That installs the package through mise, regenerates agents, engine and skills from it, re-applies forge's
patches, and names the upstream skills that are new since last time. Everything below this
paragraph describes the upstream flow and is kept for reference only — do not execute it.

Original objective: check for GSD updates, install if available, and display what changed."""

# The gsd-quick skill said the command spawns gsd-planner and gsd-executor and must "preserve all workflow gates"; the lean path
# of config/gsd/quick-lean.md (ENGINE_PATCHES) spawns neither by default and keeps the state and commit gates.
QUICK_SPAWN_OLD = "- Spawns gsd-planner (quick mode) + gsd-executor(s)"
QUICK_SPAWN_NEW = ("- By default the main agent does the task itself, with no planner or executor subagent (the forge lean path at "
                   "the top of the workflow); any of --full, --validate, --discuss, --research brings gsd-planner (quick mode) "
                   "and gsd-executor(s) back")
QUICK_GATES_OLD = "Preserve all workflow gates (validation, task description, planning, execution, state updates, commits)."
QUICK_GATES_NEW = ("Follow the forge lean path at the top of the workflow when none of --full, --validate, --discuss, --research "
                   "is given: it keeps the state and commit gates (ROADMAP.md check, a minimal PLAN.md, the SUMMARY.md with "
                   "`status: complete`, the STATE.md row, the commits). With any of those flags, run every step and gate of "
                   "the workflow as written.")

# The gsd-spike skill told the agent to keep every workflow gate; the free-form block (ENGINE_PATCHES) keeps two, the state
# other GSD commands read back and the commit.
SPIKE_GATES_OLD = ("Preserve all workflow gates (prior spike check, decomposition, research, risk ordering, observability "
                   "assessment, verification, MANIFEST updates, commit patterns).")
SPIKE_GATES_NEW = ("In the spike workflow (not `--wrap-up`), run the spike yourself in this conversation, without "
                   "subagents, and follow the forge free-form block at the top of the workflow: each spike's README "
                   "verdict, the MANIFEST.md update and the commit stay mandatory. `--wrap-up` includes only "
                   "VALIDATED, PARTIAL and INVALIDATED spikes, therefore it skips PENDING ones and names each skipped "
                   "one in its inventory.")
# The skill handed the whole idea to the workflow end-to-end; the block runs one experiment per turn.
SPIKE_E2E_OLD = "pass all of the `<arguments>` block as the idea to the spike workflow end-to-end."
SPIKE_E2E_NEW = ("pass all of the `<arguments>` block as the idea to the spike workflow, one experiment per turn, "
                 "per the forge block.")

SKILL_PATCHES = {
    "gsd-update": [("forge-update-route", "replace", UPDATE_OLD, UPDATE_NEW)],
    # Claude Code 2.1.268 stopped offering TodoWrite on current models unless
    # CLAUDE_CODE_ENABLE_TODO_TOOLS=1, so the entry is dead (031aa98). The neighbours are in the
    # anchor and the payload because a payload that is a substring of upstream reads as applied.
    "gsd-execute-phase": [("no-todowrite", "replace",
                           "  - Agent\n  - TodoWrite\n  - AskUserQuestion\n",
                           "  - Agent\n  - AskUserQuestion\n")],
    "gsd-quick": [("quick-lean-spawn", "replace", QUICK_SPAWN_OLD, QUICK_SPAWN_NEW),
                  ("quick-lean-gates", "replace", QUICK_GATES_OLD, QUICK_GATES_NEW)],
    "gsd-spike": [("spike-freeform", "replace", SPIKE_GATES_OLD, SPIKE_GATES_NEW),
                  ("spike-one-per-turn", "replace", SPIKE_E2E_OLD, SPIKE_E2E_NEW)],
}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def listdir(path):
    """os.listdir, with a directory that is not there listed as empty."""
    try:
        return os.listdir(path)
    except FileNotFoundError:
        return []


def package_root():
    """Where `@opengsd/gsd-core` is installed: under the directory mise gives its `npm:` tool
    (`mise where`, node_modules/@opengsd/gsd-core in it), else under `npm root -g`. Neither is a fixed
    path: mise switches node versions, and a path baked in goes stale on the next bump."""
    for cmd, sub in ((["mise", "where", "npm:" + PACKAGE], os.path.join("node_modules", PACKAGE)),
                     (["npm", "root", "-g"], PACKAGE)):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
        except Exception:
            out = ""
        pkg = os.path.join(out, sub) if out else ""
        if pkg and os.path.isfile(os.path.join(pkg, "package.json")):
            return pkg
    sys.exit("! %s not found under mise or `npm root -g` -- run `forge toolchain --fix` (config/toolchain.json lists npm:%s)"
             % (PACKAGE, PACKAGE))


def package_version(pkg):
    m = re.search(r'"version"\s*:\s*"([^"]+)"', read(os.path.join(pkg, "package.json")))
    return m.group(1) if m else "?"


def staged_current(version):
    """Whether the staging was made for `version` and still has its skills."""
    have = read(STAMP).strip() if os.path.exists(STAMP) else ""
    return have == version and os.path.isdir(os.path.join(STAGE, "skills"))


def stage(pkg, version):
    """Run GSD's own installer into a throwaway config dir.

    The installer is the only faithful source of the converted skill and agent text -- it
    rewrites frontmatter, paths and attribution -- so forge uses it rather than reimplementing
    the conversion, and points it at a staging directory where it can touch nothing real."""
    if staged_current(version) and not RESTAGE:
        return False
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
        lib.record("rmtree", STAGE)
    lib.makedirs(STAGE)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=STAGE)
    r = subprocess.run(["node", os.path.join(pkg, "bin", "install.js"),
                        "--claude", "--global", "--config-dir", STAGE],
                       cwd=STAGE_ROOT, env=env, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.isdir(os.path.join(STAGE, "skills")):
        sys.exit("! staging install failed (exit %s):\n%s" % (r.returncode, r.stdout[-2000:]))
    lib.write_text(STAMP, version + "\n")
    return True


def stage_forms():
    """The spellings of the staging directory in the installer's text, each with what it becomes: `$HOME/<rel>` and
    `~/<rel>` (gsd-core writes its @-references this way) keep their spelling over the real config dir, and the absolute
    path becomes `$HOME/.claude`. Only a staging directory under HOME has the first two."""
    forms = [(STAGE, "$HOME/.claude")]
    if STAGE.startswith(HOME + os.sep):
        rel = os.path.relpath(STAGE, HOME)
        forms = [("$HOME/" + rel, "$HOME/.claude"), ("~/" + rel, "~/.claude")] + forms
    return forms


def normalize(text):
    """Staging paths back to the real config dir, in each spelling (stage_forms), the trailing-slash variant first so
    the bare directory cannot eat its own prefix."""
    for form, real in stage_forms():
        text = text.replace(form + "/", real + "/").replace(form, real)
    return text


def apply_patches(text, name, patches, errors):
    for pid, op, anchor, payload in patches:
        if payload.startswith("file:"):
            payload = read(os.path.join(BLOCKS, payload[5:]))
        if op == "replace":
            if payload in text:
                continue
            if anchor not in text:
                errors.append("%s: anchor for patch '%s' no longer matches upstream -- re-derive "
                              "it against the new text before trusting this file" % (name, pid))
                continue
            text = text.replace(anchor, payload)
        elif op == "append":
            if payload.strip() and payload.strip() in text:
                continue
            if anchor not in text:
                errors.append("%s: anchor for patch '%s' is gone from upstream -- the file this "
                              "block belongs to has changed shape" % (name, pid))
                continue
            text = text.rstrip("\n") + "\n\n" + payload
        else:
            errors.append("%s: unknown patch op '%s'" % (name, op))
    return text


def want_text(src, name, patches, errors):
    text = apply_patches(normalize(read(src)), name, patches, errors)
    # A spelling no rule knows would leave the file pointing into the cache: refused, not copied.
    marker = os.path.relpath(STAGE, HOME) if STAGE.startswith(HOME + os.sep) else STAGE
    if marker in text:
        errors.append("%s: still names the staging directory (%s) after normalising -- add its spelling to stage_forms" % (name, marker))
    return text


def sync_tree(src_dir, dst_dir, patch_map, label, errors, only=None):
    """Copy every staged file into place, patched. Never prunes: the runtime carries files the
    package does not ship (bin/shared), and deleting what we did not create is not this script's
    job.

    A file whose patch failed is held back: not written, not counted. It was once
    written unpatched, so the run that exited 1 to protect a fix had already replaced the patched
    runtime file with upstream text, undoing the fix it named.

    A patch keyed to a file this walk never reaches (gone from the package, renamed, or excluded
    by `only`) applies to nothing, which is the unmatched-anchor case one level up: an error.
    It was once dropped and the run exited 0."""
    added, updated, held, same, seen = [], [], [], 0, set()
    for base, _dirs, files in os.walk(src_dir):
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(base, fn), src_dir)
            if only and not only(rel):
                continue
            seen.add(rel)
            n_errors = len(errors)
            want = want_text(os.path.join(src_dir, rel), rel, patch_map.get(rel, []), errors)
            if len(errors) > n_errors:
                held.append(rel)
                continue
            dst = os.path.join(dst_dir, rel)
            if lib.holds(dst, want):  # byte for byte: a CRLF copy of the LF text is not in sync
                same += 1
                continue
            bucket = updated if os.path.exists(dst) else added
            if CTX.apply:
                try:
                    lib.write_text(dst, want)
                except OSError as e:  # FileExistsError too: a user's directory where a file goes, or a file where a directory goes
                    errors.append("%s %s: %s; the entry at that path is not ours, left as it is" % (label, rel, e.strerror or e))
                    continue
            bucket.append(rel)
    for rel in sorted(set(patch_map) - seen):
        errors.append("%s: not in the staged package, so patch '%s' applies to nothing -- find "
                      "where upstream moved it and re-key the patch, or delete it"
                      % (rel, "', '".join(p[0] for p in patch_map[rel])))
    verb = "wrote" if CTX.apply else "would write"
    print("== %s ==" % label)
    print("   %d in sync" % same)
    for kind, names in (("new", added), ("changed", updated)):
        if names:
            shown = ", ".join(sorted(names)[:8]) + (" …" if len(names) > 8 else "")
            print("   %s %d %s: %s" % (verb, len(names), kind, shown))
    if held:
        print("   ! held back %d (a patch failed; the file on disk is kept): %s"
              % (len(held), ", ".join(sorted(held))))
    if not added and not updated and not held:
        print("   nothing to do")
    return len(added) + len(updated)


def sync_skills(errors):
    """forge/skills/gsd-* for EVERY upstream skill (gsd-core's whole set: no cap): the ones forge
    already has are compared, the ones it has not are new and written whole. FORGE_AUTHORED names have no upstream file
    and are never touched.

    Read-only unless --skills --apply, because these files are in git and a run that
    silently reverted a hand edit would be worse than the drift it fixes. Drift reported here is
    the prompt to turn that edit into a patch above."""
    staged = os.path.join(STAGE, "skills")
    if CTX.apply:
        lib.makedirs(FORGE_SKILLS)  # a checkout with no skills yet: nothing to list, nothing to fail on
    have_forge = sorted(d for d in listdir(FORGE_SKILLS)
                        if d.startswith("gsd-") and os.path.isdir(os.path.join(FORGE_SKILLS, d)))
    upstream = sorted(d for d in listdir(staged) if d.startswith("gsd-") and os.path.exists(os.path.join(staged, d, "SKILL.md")))
    # A forge skill with no staged file and no authorship is the error below. A name both authored and
    # upstream would be overwritten, so authorship wins.
    shipped = [n for n in upstream if n not in FORGE_AUTHORED]
    missing = [n for n in have_forge if n not in FORGE_AUTHORED and n not in upstream]
    changed, new, drift, held, seen = 0, [], [], [], set()
    for name in shipped:
        src = os.path.join(staged, name, "SKILL.md")
        seen.add(name)
        n_errors = len(errors)
        want = want_text(src, name, SKILL_PATCHES.get(name, []), errors)
        if len(errors) > n_errors:  # held back, as in sync_tree
            held.append(name)
            continue
        dst = os.path.join(FORGE_SKILLS, name, "SKILL.md")
        if lib.holds(dst, want):
            continue
        changed += 1
        (drift if name in have_forge else new).append(name)
        if CTX.apply:
            lib.makedirs(os.path.dirname(dst))
            lib.write_text(dst, want)
    # A patch with no target, as in sync_tree. A forge skill with no staged file is already an
    # error below ("skill without upstream counterpart"), so it is not reported twice.
    for name in sorted(set(SKILL_PATCHES) - seen - set(missing)):
        errors.append("%s: it is not in the staged package, so patch '%s' applies to nothing -- re-key the patch or delete it"
                      % (name, "', '".join(p[0] for p in SKILL_PATCHES[name])))
    print("== forge skills vs package ==")
    print("   %d shipped here (%d new), %d forge-authored" % (len(shipped), len(new), len(FORGE_AUTHORED)))
    for n in missing:
        print("   ! %s has no upstream counterpart -- declare it in FORGE_AUTHORED or it will "
              "never be regenerated" % n)
        errors.append("skill without upstream counterpart: %s" % n)
    if held:
        print("   ! held back %d (a patch failed; the file in forge is kept): %s"
              % (len(held), ", ".join(held)))
    if new:
        shown = ", ".join(new[:12]) + (" …" if len(new) > 12 else "")
        print("   %s %d new: %s" % ("wrote" if CTX.apply else "would write", len(new), shown))
    if drift:
        print("   %s %d: %s" % ("rewrote" if CTX.apply else "differ from the package",
                                len(drift), ", ".join(drift)))
        if not CTX.apply:
            print("     (--skills --apply regenerates them; if a difference is a forge edit "
                  "worth keeping, encode it in SKILL_PATCHES first)")
    return changed


def check_skill_refs(errors):
    """Every gsd-* name a forge GSD skill routes to must resolve to a skill or an agent, and
    every engine file a skill imports must exist.

    WHY: the codebase-intelligence router sent three of its six rows to `gsd-map-codebase`, a
    skill never packaged into forge. It read as if it worked; invoking it did nothing.
    verify_skill_refs.py only checks profile -> installed skill, the other direction.

    A directory that is not there counts as empty: a fresh HOME, or a dry-run before the mirror
    exists, once raised FileNotFoundError here."""
    # The mirror, and forge's own skills/ it links from: a skill written a moment ago is only in the second
    # until relink_skills runs, which is after this step in forge skills.
    mirrored = set(d for d in listdir(SKILLS_MIRROR) if os.path.isdir(os.path.join(SKILLS_MIRROR, d)))
    skills = mirrored | set(d for d in listdir(FORGE_SKILLS) if d.startswith("gsd-") and os.path.isdir(os.path.join(FORGE_SKILLS, d)))
    agents = set(f[:-3] for f in listdir(AGENTS_DIR) if f.endswith(".md"))
    dangling, missing_wf = [], []
    for name in sorted(skills):
        if not name.startswith("gsd-"):
            continue
        p = next((q for q in (os.path.join(SKILLS_MIRROR, name, "SKILL.md"), os.path.join(FORGE_SKILLS, name, "SKILL.md"))
                  if os.path.exists(q)), None)
        if p is None:
            continue
        body = read(p)
        for wf in set(re.findall(r"@\$HOME/\.claude/gsd-core/([A-Za-z0-9_./-]+\.md)", body)):
            if not os.path.exists(os.path.join(GSD_DIR, wf)):
                missing_wf.append("%s -> %s" % (name, wf))
        # A routing table's action column: `| ... | gsd-foo |`. Prose mentions are deliberately
        # not checked -- skills discuss commands upstream deleted, and flagging those is noise.
        for ref in sorted(set(re.findall(r"\|\s*(gsd-[a-z0-9-]+)[^|]*\|\s*$", body, re.M))):
            if shutil.which(ref):          # gsd-sdk, gsd-tools: CLIs on PATH, not skills
                continue
            if ref not in skills and ref not in agents:
                dangling.append("%s -> %s" % (name, ref))
    # An installer run against ~/.claude leaves REAL gsd-* directories next to forge's symlinks
    # (it installs 67 of them). Nothing else on this machine creates one, so a non-symlink here
    # is the fingerprint of the thing this whole script exists to prevent.
    intruders = sorted(d for d in mirrored if d.startswith("gsd-")
                       and not os.path.islink(os.path.join(SKILLS_MIRROR, d)))
    for d in intruders:
        errors.append("~/.claude/skills/%s is a real directory, not a symlink into forge -- the "
                      "GSD installer has been run against ~/.claude. Check `git status` in forge "
                      "for overwritten skills, then delete the stray directories and re-run "
                      "relink_skills.py" % d)

    print("== skill -> skill/engine references ==")
    print("   %d gsd-* skills, %d agents installed" % (
        len([s for s in skills if s.startswith("gsd-")]), len(agents)))
    for d in dangling + missing_wf + intruders:
        print("   ! %s" % d)
    errors.extend("dangling reference: %s" % d for d in dangling + missing_wf)
    if not dangling and not missing_wf and not intruders:
        print("   every reference resolves, every gsd-* skill is a forge symlink")


def npm_latest(timeout=60):
    try:
        r = subprocess.run(["npm", "view", PACKAGE, "version"],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def npm_nag(pkg_v):
    """Say, at most once a day, that a newer GSD exists.

    WHY AUTOMATIC. "Check for a new version" as a habit is a thing nobody does; the runtime sat
    on 1.42.3 with six agents missing for six weeks and the only reason anyone looked was a
    stuck command. WHY THROTTLED AND SILENT. This runs at every --apply: a network call
    per run is rude, and a line saying "you are up to date" every time is noise that gets
    filtered out along with the line that matters. One check a day, 8 seconds, prints only when
    there is something to say, and any failure (offline, npm slow) is simply skipped.

    Apply only: the stamp is a write, and a dry-run writes nothing. The nag still comes once a
    day, from an --apply (a session start only runs --check, which never calls it); --check-npm asks on demand."""
    if not CTX.apply:
        return
    import time
    try:
        last = float(read(NPM_STAMP).split()[0]) if os.path.exists(NPM_STAMP) else 0.0
    except Exception:
        last = 0.0
    if time.time() - last < 86400:
        return
    latest = npm_latest(timeout=8)
    try:
        lib.write_text(NPM_STAMP, "%f %s\n" % (time.time(), latest))
    except Exception:
        pass
    if latest not in ("?", pkg_v):
        print("GSD %s is published (installed %s). Update: see the procedure at the top of "
              "scripts/sync/sync_gsd_runtime.py\n" % (latest, pkg_v))


def sync_defaults(errors):
    """~/.gsd/defaults.json is a COPY of config/gsd/defaults.json, so every project GSD creates
    starts with forge's user-level defaults (GSD's buildNewProjectConfig reads that file; why these
    values: config/gsd/defaults.md). A copy and not a link because GSD writes the file: the
    settings workflow's "save as global defaults" (workflows/settings.md:393-399) has the agent
    write ~/.gsd/defaults.json, which through a link would overwrite forge's tracked file
    (config.cjs:148 also rewrites it, by temp file and rename, but only for a deprecated `depth`
    key). Written by --apply only. Absent: copied. A symlink there (forge's first design, or a
    stranger's) is replaced by the copy, since a link to forge's file is that very hazard. A real
    file with forge's bytes is in sync. A real file that differs is the user's choice (GSD's own
    settings workflow writes it), or forge's older text: left alone, one informational line with
    no '!', not an error, 0 changes. Returns how many changes an apply would make."""
    src = os.path.join(BLOCKS, "defaults.json")
    print("== GSD user defaults (~/.gsd/defaults.json) ==")
    if not os.path.isfile(src):
        errors.append("%s is missing, so ~/.gsd/defaults.json has nothing to copy" % src)
        return 0
    dst = GSD_DEFAULTS
    verb = "copied" if CTX.apply else "would copy"
    if os.path.islink(dst):
        verb = "replaced the link with a copy of" if CTX.apply else "would replace the link with a copy of"
    elif os.path.lexists(dst):
        if os.path.isfile(dst) and read_bytes(dst) == read_bytes(src):
            print("   in sync (%s)" % lib.short(dst))
            return 0
        if os.path.isfile(dst) and read(dst) in FORMER_DEFAULTS:
            verb = "replaced forge's earlier text in" if CTX.apply else "would replace forge's earlier text in"
            if CTX.apply:
                lib.write_text(dst, read(src))
            print("   %s %s (it capped GSD's UI phase; forge sets no default now)" % (verb, lib.short(dst)))
            return 1
        print("   %s differs from %s -- yours (GSD's settings can write it), left alone; delete it "
              "to take forge's" % (lib.short(dst), lib.short(src)))
        return 0
    if CTX.apply:
        lib.makedirs(os.path.dirname(dst))
        if os.path.islink(dst):
            os.remove(dst)  # write_text writes through a link, into the file the link points at
        lib.write_text(dst, read(src))
    print("   %s %s -> %s" % (verb, lib.short(src), lib.short(dst)))
    return 1


def main():
    if CHECK and CTX.apply:
        sys.exit("! --check reads only: drop --apply")
    if not CTX.globals:
        return 0  # user-scope files; a run outside forge leaves them alone
    if lib.on("gsd") and not lib.gsd_patched():
        # A stranger gets GSD straight from its package, installed by forge init
        # through `pnpm dlx get-shit-done-cc`. The patches, the staging and the copy are forge's own
        # maintainer's, behind config/forge.json gsd_patches.
        print("GSD is your own unpatched install: forge stages, patches and copies nothing "
              "(config/forge.json gsd_patches is not true).")
        return 0
    pkg = package_root()
    pkg_v = package_version(pkg)
    vfile = os.path.join(GSD_DIR, "VERSION")
    inst_v = read(vfile).strip() if os.path.exists(vfile) else "?"
    print("MODE:", "APPLY" if CTX.apply else "DRY-RUN (pass --apply to write)")
    print("package %s | runtime %s | staging %s" % (pkg_v, inst_v, STAGE))
    if CHECK_NPM:
        latest = npm_latest()
        newer = latest not in ("?", pkg_v)
        print("npm latest: %s%s" % (latest, "   <- newer than installed" if newer else ""))
    else:
        npm_nag(pkg_v)
    if CHECK and not staged_current(pkg_v):
        # Session start must not run GSD's installer, nor hold the lock it needs: a staging made for
        # another version already says the runtime will change.
        print("staging: not made for package %s, so --apply would restage and change the runtime" % pkg_v)
        return DIFFERS
    fresh = False if CHECK else stage(pkg, pkg_v)
    print("staging: %s\n" % ("rebuilt from the package" if fresh else "reused (same version)"))

    errors = []
    changes = sync_tree(os.path.join(STAGE, "agents"), AGENTS_DIR, AGENT_PATCHES,
                        "GSD agents (~/.claude/agents)", errors,
                        only=lambda rel: rel.startswith("gsd-") and rel.endswith(".md"))
    changes += sync_tree(os.path.join(STAGE, "gsd-core"), GSD_DIR, ENGINE_PATCHES,
                         "GSD engine (~/.claude/gsd-core)", errors)
    changes += sync_tree(os.path.join(STAGE, "scripts"), SCRIPTS_DIR, {}, "GSD scripts (~/.claude/scripts)", errors,
                         only=scripts_wanted)
    changes += sync_tree(os.path.join(STAGE, "hooks"), HOOKS_DIR, {}, "GSD hooks (~/.claude/hooks)", errors, only=hook_wanted)
    changes += sync_defaults(errors)
    if DO_SKILLS:
        changes += sync_skills(errors)
    else:
        print("== forge skills vs package ==\n   skipped (pass --skills)")
    check_skill_refs(errors)

    print()
    if errors:
        for e in errors:
            print("! %s" % e)
        return 1
    if changes and not CTX.apply:
        print("%d file(s) would change. Re-run with --apply." % changes)
        return DIFFERS if CHECK else 0
    else:
        print("GSD runtime in sync (%d file(s) %s)." % (changes, "written" if CTX.apply else "pending"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
