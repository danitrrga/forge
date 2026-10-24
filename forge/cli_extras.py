"""The entries Claude Code ships itself, which a project's `/` menu carries whether anyone approved them.

forge's skill trim (skills.write_settings_local) sees only the skills on disk, so these were out of its
reach. This module is their registry and the rule that chooses among them. Captured on Claude Code 2.1.308,
in the real TUI; the `cli built-ins` doctor row compares CAPTURED with `claude --version`, and `forge cli --probe`
compares the registry with the live menu, so a version that adds or drops an entry is named instead of silently
drifting.

What can be hidden, and how (HIDEABLE: name -> (kind, env variable or None, one line)):
  override  skillOverrides {name: "off"} hides it from the `/` menu and from the model. The twenty bundled
            skills and five built-in prompt commands (auto-mode-setup, init, insights, security-review,
            team-onboarding). It hides no plugin entry and no other built-in.
  env       one key of the settings `env` block hides one built-in: DISABLE_LOGIN_COMMAND (login),
            DISABLE_LOGOUT_COMMAND (logout), DISABLE_UPGRADE_COMMAND (upgrade),
            DISABLE_INSTALL_GITHUB_APP_COMMAND (install-github-app), DISABLE_EXTRA_USAGE_COMMAND
            (usage-credits), each set to "1".
  DISABLE_FEEDBACK_COMMAND is left out on purpose: it hid neither /feedback nor /bug in 2.1.308.
Every other built-in has no switch and always stays (ALWAYS).

The choice is an allowlist, like skills_keep. A registry name is kept in a project when it is in
config/forge.json skill_keep.cli_common (kept everywhere) or in the profile's `cli_keep` (a list of names,
or ["*"] for all of them); every other registry name is hidden. With neither the cli_common key nor a
profile's cli_keep the feature is off for that project: nothing is written, and only what forge wrote
before is taken out (skills.write_settings_local, by ownership claims). So a machine that never opts in
sees today's output unchanged."""
import os
import re
import shutil
import subprocess

from forge import lib

OVERRIDE, ENV = "override", "env"

# The Claude Code version the registry was captured on: `forge doctor` WARNs when `claude --version` says another.
CAPTURED = "2.1.308"
# Entries Claude Code lists in the init line but hides from the menu by design: `forge cli --probe` takes them as known.
BY_DESIGN = ("design-consent", "design-revoke", "extra-usage", "heapdump", "agents", "__remote-workflow",
             "workflow-launch-exec")

HIDEABLE = {
    "batch": (OVERRIDE, None, "bundled skill"),
    "claude-api": (OVERRIDE, None, "bundled skill: Claude API and SDK reference"),
    "claude-in-chrome": (OVERRIDE, None, "bundled skill: drive the Chrome extension"),
    "code-review": (OVERRIDE, None, "bundled skill: review the current diff or a pull request"),
    "dataviz": (OVERRIDE, None, "bundled skill: chart and dashboard guidance"),
    "debug": (OVERRIDE, None, "bundled skill: debug a failing session or command"),
    "deep-research": (OVERRIDE, None, "bundled skill: multi-source web research"),
    "design": (OVERRIDE, None, "bundled skill"),
    "design-sync": (OVERRIDE, None, "bundled skill"),
    "doctor": (OVERRIDE, None, "bundled skill: diagnose the Claude Code install"),
    "fewer-permission-prompts": (OVERRIDE, None, "bundled skill: build an allowlist from past transcripts"),
    "loop": (OVERRIDE, None, "bundled skill: run a prompt on an interval"),
    "plugin-authoring": (OVERRIDE, None, "bundled skill: write a mod for Claude Code's interface"),
    "run": (OVERRIDE, None, "bundled skill: launch and drive the project's app"),
    "run-skill-generator": (OVERRIDE, None, "bundled skill"),
    "schedule": (OVERRIDE, None, "bundled skill: scheduled cloud agents"),
    "simplify": (OVERRIDE, None, "bundled skill: clean up the changed code"),
    "update-config": (OVERRIDE, None, "bundled skill: edit settings.json"),
    "verify": (OVERRIDE, None, "bundled skill: check that a change works"),
    "workflow-authoring": (OVERRIDE, None, "bundled skill: write a Workflow script"),
    "auto-mode-setup": (OVERRIDE, None, "built-in command: set up auto mode"),
    "init": (OVERRIDE, None, "built-in command: write a CLAUDE.md"),
    "insights": (OVERRIDE, None, "built-in command: a report on past sessions"),
    "security-review": (OVERRIDE, None, "built-in command: security review of the branch"),
    "team-onboarding": (OVERRIDE, None, "built-in command: onboarding guide for a team"),
    "login": (ENV, "DISABLE_LOGIN_COMMAND", "built-in command: sign in"),
    "logout": (ENV, "DISABLE_LOGOUT_COMMAND", "built-in command: sign out"),
    "upgrade": (ENV, "DISABLE_UPGRADE_COMMAND", "built-in command: upgrade the plan"),
    "install-github-app": (ENV, "DISABLE_INSTALL_GITHUB_APP_COMMAND", "built-in command: install the GitHub app"),
    "usage-credits": (ENV, "DISABLE_EXTRA_USAGE_COMMAND", "built-in command: buy extra usage"),
}

ALWAYS = frozenset("""add-dir autocompact autofix-pr background branch btw bug cd chrome clear color compact config
context copy design-login diff effort exit export fast feedback focus fork goal help hooks ide import
install-slack-app keybindings list-agents memory mcp mobile model output-style permissions plan plugin powerup
radio rate-limit-options recap release-notes reload-plugins reload-skills remote-control remote-env rename
resume rewind sandbox scroll-speed skill-doctor skills status statusline stickers subtask tasks teleport
terminal-setup theme tui usage voice workflows""".split())


def common_setting():
    """config/forge.json skill_keep.cli_common as the file has it, or None when the key is absent (the
    feature's off switch)."""
    table = lib.settings().get("skill_keep")
    return table.get("cli_common") if isinstance(table, dict) else None


def known_setting():
    """config/forge.json skill_keep.cli_known: the menu names the user accepts as unknown to forge (a plugin
    command without a prefix, say), or [] when the key is absent."""
    table = lib.settings().get("skill_keep")
    names = table.get("cli_known") if isinstance(table, dict) else None
    return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []


def plan(prof, common, global_skills):
    """(on, errors, overrides, env) for one profile: `common` is skill_keep.cli_common (None: no such key),
    `global_skills` the names of the user-global skill directories. `on` is whether the feature applies
    (cli_common given, or the profile has cli_keep); `overrides` is the names to hide as "off"; `env` the
    {variable: "1"} to set. A refusal, as one line each in `errors`, leaves overrides and env empty: a
    registry name that is also a global skill (skillOverrides matches by name, so it could not tell the two
    apart), a cli_keep that is not a list of registry names or ["*"], a cli_common name not in the registry."""
    keep = prof.get("cli_keep")
    on = common is not None or "cli_keep" in prof
    if not on:
        return False, [], [], {}
    errors = []
    clash = sorted(set(HIDEABLE) & set(global_skills))
    if clash:
        errors.append("cli built-ins: %s is also a global skill directory, so skillOverrides could not tell the "
                      "two apart" % ", ".join(clash))
    for label, names in (("config/forge.json skill_keep.cli_common", common), ("cli_keep", keep)):
        if names is None:
            continue
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            errors.append("%s is not a list of names" % label)
            continue
        for n in names:
            if n == "*" and label == "cli_keep":
                continue
            if n in ALWAYS:
                errors.append("%s names %s, a built-in with no switch: it always stays" % (label, n))
            elif n not in HIDEABLE:
                errors.append("%s names %s, which is not in forge/cli_extras.py's registry" % (label, n))
    if errors:
        return True, errors, [], {}
    kept = set(common or []) | set(keep or [])
    if "*" in kept:
        return True, [], [], {}
    hidden = [n for n in HIDEABLE if n not in kept]
    return (True, [], sorted(n for n in hidden if HIDEABLE[n][0] == OVERRIDE),
            {HIDEABLE[n][1]: "1" for n in sorted(hidden) if HIDEABLE[n][0] == ENV})


def listing(prof, common, global_skills):
    """(on, errors, rows) for `forge cli`: `rows` is (name, "kept" or "hidden", why) per registry name, in the
    registry's order, why being cli_common, cli_keep or "not kept". `on` and `errors` are plan's: with a refusal
    there are no rows, since forge hides nothing then."""
    on, errors, _, _ = plan(prof, common, global_skills)
    if not on or errors:
        return on, errors, []
    common_names = common if isinstance(common, list) else []
    keep = prof.get("cli_keep") or []
    rows = []
    for n in HIDEABLE:
        why = "cli_common" if n in common_names else "cli_keep" if (n in keep or "*" in keep) else None
        rows.append((n, "kept" if why else "hidden", why or "not kept"))
    return on, errors, rows


def _stems(path):
    """The names in a directory of skills, commands or workflows: a directory by its name, a file without its
    extension. Nothing when it is not there."""
    try:
        return {os.path.splitext(f)[0] if os.path.isfile(os.path.join(path, f)) else f
                for f in os.listdir(path) if not f.startswith(".")}
    except OSError:
        return set()


def known_names(prof, global_skills, known_extra=()):
    """The slash commands forge accounts for in the menu of one project: the registry's names and the always-on
    built-ins, the global skills the project keeps (all of them without a trim, none but its skills_keep with one),
    the project's own .claude/skills, .claude/commands and .claude/workflows, what Claude Code hides by design
    (BY_DESIGN) and `known_extra` (config/forge.json skill_keep.cli_known). A name with a ':' is a plugin's and is
    left to unknown()."""
    sk = set(prof.get("skills_keep") or [])
    trimmed = bool(prof.get("plugins_keep")) or "skills_keep" in prof
    kept = set(global_skills) if (not trimmed or "*" in sk) else sk
    ppath = prof.get("project_path") or ""
    own = set()
    for sub in ("skills", "commands", "workflows"):
        own |= _stems(os.path.join(ppath, ".claude", sub))
    return set(HIDEABLE) | ALWAYS | kept | own | set(BY_DESIGN) | set(known_extra)


def unknown(listed, known):
    """The names in `listed` (the init line's slash_commands) that are neither in `known` nor a plugin's
    (a ':' in the name), in the order Claude Code listed them, once each."""
    out = []
    for n in listed:
        n = n[1:] if n.startswith("/") else n
        if n not in known and ":" not in n and n not in out:
            out.append(n)
    return out


def claude_version():
    """(path, version): where `claude` is on PATH (None when it is not) and the version `claude --version` prints
    (None when it prints none forge can read, or does not answer in time)."""
    exe = shutil.which("claude")
    if not exe:
        return None, None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return exe, None
    m = re.search(r"\d+\.\d+\.\d+", r.stdout)
    return exe, m.group(0) if m else None
