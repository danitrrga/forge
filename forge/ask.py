"""The questions of `forge new NAME` and `forge new @NAME`, in the owner's order, and what each answer becomes.

The order, which `Asker.asked` records so a test can read it:
  1 profiles      "profiles in this project?" (names, by `input()`); naming one begins its questions
  2 sets, skills  per profile (or once, for the project): the sets of skill_keep.sets (each with its skill_keep.set_docs line, else its
                  members), then the final list of skills, which is the sets' members edited by adding and removing;
                  `--sets` or `--skills` alone answers both, and so does the pair
  3 servers       the MCP servers of config/mcp-registry.json (an account server is `<service>-<project>`)
  4 memory        among the memory integrations that are on (MEMORY) and none; a project question, a profile has no memory
  5 stack         what the stack asks: its checks, its plugins and the options ui and command_guard

Every question is a flag: --profiles, --sets, --skills (the final list, replacing what the sets give), --server, --memory, and for
5 --check, --plugin, --ui, --command-guard. `none` is the explicit empty answer of the first four. A flag asks nothing; a question
whose flag is absent is asked only in a terminal and never with --yes, so the same data by flags or by answers writes the same
files. Where nothing is asked (no terminal, or --yes), one question flag makes every other question need its flag (`none` is an answer),
and the error names all that are missing; with none of them the command is what it was before the questions. With profiles named, `--sets`, `--skills` and `--server` apply to each of them (`@NAME:` in front of a value limits it to
one and replaces the unscoped value for that profile: `--sets @code:A,B`); with none, to the project. An answer is validated whole, before the first write, with every problem named.

The layer rules are forge/configure.py's (`Plan`): for the project a Draft of it runs the same `set_on`, `skill_on` and `server_on` on
documents that are not on disk yet. A profile row is built beside them: `Plan` edits a profile through its definition on disk, and
this one does not exist yet.

What is written is not here: forge/new.py writes it (all or nothing)."""
import copy
import os
import sys

from forge import configure, lib, memory, profiles, selector, suggest

DEFAULT_LABEL = "default"  # the label of the project's own lists when a project offers profiles (profiles.default)
# The memory integrations a project can be given (the project scopes of forge/hooks.py SCOPES, which read the project's `servers`), and
# the registry servers each one means: a project is on one when its `servers` hold them. The others of lib.INTEGRATIONS are not memory.
MEMORY = {"hindsight": ("hindsight-coding-agents", "hindsight-recall"), "mempalace": ("mempalace",)}
NONE = "none"


class Cancelled(Exception):
    """The owner ended a question (Esc, the input ending), or the recorded answers of a test ran out. Ctrl-C at a question that reads a
    line is a KeyboardInterrupt, which forge/new.py turns into one line and exit 130."""


class Asker:
    """The questions' transport. `keys` (a list with one list of key names per selector question) and `lines` (one text per
    `input()` question) replace the terminal in a test; without them the terminal is asked. `interactive` says whether anything
    may be asked at all. `asked` is the id of each question, in the order it was asked."""

    def __init__(self, keys=None, lines=None, interactive=None):
        self.keys = None if keys is None else list(keys)
        self.lines = None if lines is None else list(lines)
        self.interactive = (sys.stdin.isatty() and sys.stdout.isatty()) if interactive is None else interactive
        self.asked = []

    def pick(self, qid, title, rows):
        """The ids switched on after the owner went through `rows` ((id, label, on)): the starting ones, changed as asked."""
        self.asked.append(qid)
        if self.keys is not None:
            if not self.keys:
                raise Cancelled("the recorded keys ran out at the question %s" % qid)
            changes = selector.run([(title, rows)], keys=self.keys.pop(0))
        else:
            changes = selector.run([(title, rows)])
        if changes is None:
            raise Cancelled("cancelled at the question %s" % qid)
        return [key for key, _, on in rows if changes.get(key, on)]

    def pick_one(self, qid, title, rows):
        """Like pick, for an answer that is exactly one row; asked again while it is not."""
        while True:
            chosen = self.pick(qid, title + " (exactly one)", rows)
            if len(chosen) == 1:
                return chosen[0]
            print("forge new: pick exactly one, %d are on" % len(chosen), file=sys.stderr)
            self.asked.pop()

    def line(self, qid, prompt):
        self.asked.append(qid)
        if self.lines is not None:
            if not self.lines:
                raise Cancelled("the recorded lines ran out at the question %s" % qid)
            return self.lines.pop(0)
        try:
            return input(prompt)
        except EOFError:
            raise Cancelled("the input ended at the question %s" % qid)


def make_asker():
    """The asker `forge new` uses. A function so a test replaces it with one that holds recorded answers."""
    return Asker()


class Draft(configure.Plan):
    """configure.Plan on documents that are not on disk yet: the rules of `set_on`, `skill_on` and `server_on` (what must exist, what
    the layers already keep, which secret is missing) without reading the project file, which a new project does not have."""

    def __init__(self, name, forge, proj):
        self.name, self.profile, self.fn = name, None, name + ".claude.json"
        self.before = self.expected = None
        self.paths, self.texts = {}, {}
        self.docs = {"forge": forge, "project": proj}
        self.start = copy.deepcopy(self.docs)
        self.forge, self.proj = forge, proj
        self.items = []


# ---- the flags ---------------------------------------------------------------------------------------------------------------

def _names(text):
    return [t.strip() for t in text.split(",")]


def parse_scoped(flag, occurrences, problems):
    """{scope: [values]} of a repeatable flag whose value may start `@PROFILE:`. The scope None is the unscoped one. `none` is [].
    None when the flag was not given."""
    if not occurrences:
        return None
    out = {}
    for text in occurrences:
        scope = None
        if text.startswith("@"):
            head, sep, text = text.partition(":")
            if not sep or not head[1:]:
                problems.append("%s %s: a scoped value is written @PROFILE:VALUE" % (flag, head + sep + text))
                continue
            scope = head[1:]
        values = _names(text)
        if "" in values:
            problems.append("%s: an empty name in %r" % (flag, text))
            continue
        out.setdefault(scope, [])
        out[scope] += [] if values == [NONE] else values
    return out


class Flags:
    """What the command line answered: None where a flag was not given."""

    def __init__(self, a, problems):
        raw = getattr(a, "profiles", None)
        self.profiles = None
        if raw is not None:
            self.profiles = [] if raw.strip() == NONE else _names(raw)
            if "" in self.profiles:
                problems.append("--profiles: an empty name in %r" % raw)
                self.profiles = [p for p in self.profiles if p]
        self.sets = parse_scoped("--sets", getattr(a, "sets", None), problems)
        self.skills = parse_scoped("--skills", getattr(a, "skills", None), problems)
        self.servers = parse_scoped("--server", getattr(a, "server", None), problems)
        self.memory = getattr(a, "memory", None)
        self.checks = getattr(a, "check", None) or []
        self.plugins = getattr(a, "plugin", None) or []
        self.ui = bool(getattr(a, "ui", False))
        self.command_guard = bool(getattr(a, "command_guard", False))

    def of(self, table, scope):
        """What `table` (sets, skills or servers) says for one scope: its own value, else the unscoped one, else None."""
        if table is None:
            return None
        return table[scope] if scope in table else table.get(None)

    def stack_given(self):
        return bool(self.checks or self.plugins or self.ui or self.command_guard)


# ---- the context -------------------------------------------------------------------------------------------------------------

class Context:
    """What the questions are about: the project's name, forge.json's tables and the registry as they are now, the stack (None for
    `forge new @NAME`), and the Draft the project's lists are applied to."""

    def __init__(self, name, forge, proj, stack):
        self.name, self.forge, self.proj, self.stack = name, forge, proj, stack
        self.draft = Draft(name, forge, proj)
        keep = forge.get("skill_keep") if isinstance(forge.get("skill_keep"), dict) else {}
        self.sets, self.docs = keep.get("sets") or {}, keep.get("set_docs") or {}
        self.error = None  # why the tables of config/forge.json cannot be asked about: gather() says it and nothing is asked
        if not isinstance(self.sets, dict) or not all(isinstance(v, list) for v in self.sets.values()):
            self.error = "config/forge.json skill_keep.sets must be an object of lists of skill names"
        elif not isinstance(self.docs, dict):
            self.error = "config/forge.json skill_keep.set_docs must be an object of texts (a line for each set), it is %s" % (
                type(self.docs).__name__)
        if self.error:
            self.sets, self.docs = {}, {}
        self.installed = sorted(configure.installed_skills())
        self.registry = sorted(self.draft.registry())
        others = [n for n in lib.projects() if n != name]
        self.owner = {s: o for s in self.registry for o in [owner_of(s, name, others)] if o}  # an account server of another project

    def memory_servers(self):
        return {s for servers in MEMORY.values() for s in servers}

    def memory_options(self):
        return [m for m in lib.INTEGRATIONS if m in MEMORY and lib.on(m)]

    def server_rows(self, kinds=None):
        """The servers worth asking about: not another project's account server and not a memory server (that is question 4)."""
        out = []
        for s in self.registry:
            if s in self.owner or s in self.memory_servers():
                continue
            if kinds is not None and kind_of(s, self.name) not in kinds:
                continue
            out.append(s)
        return out

    def set_label(self, name):
        doc = self.docs.get(name)
        return "%s: %s" % (name, doc if isinstance(doc, str) and doc.strip() else ", ".join(self.sets[name]))


def owner_of(server, project, others):
    """The other project whose account server `server` (`<service>-<project>`) is, or None. A project's own is its own, and when the
    names of two projects both end the server's, the longer is the owner: hero does not take vercel-el-hero, which is el-hero's."""
    named = [o for o in [project] + list(others) if server.endswith("-" + o) and len(server) > len(o) + 1]
    if not named:
        return None
    best = max(named, key=len)
    return None if best == project else best


def kind_of(server, project):
    """The kind of MCP server a profile definition lists for `server`: the service of an account server `<service>-<project>`, else
    the server's own name."""
    suffix = "-" + project
    return server[:-len(suffix)] if server.endswith(suffix) and len(server) > len(suffix) else server


# ---- the answers -------------------------------------------------------------------------------------------------------------

class Answers:
    """`profiles`: the names of the profiles this run makes. `targets`: {scope: {"sets", "skills", "servers"}} for each scope the
    lists were asked for (a profile's name, or None for the project), `skills` None when the final list is the sets' members as
    they are. `memory`: a key of MEMORY or None. `stack`: {"checks", "plugins", "ui", "command_guard"} or None."""

    def __init__(self):
        self.profiles, self.targets, self.memory = [], {}, None
        self.stack = None


def lists_answered(flags, scope):
    """Whether the flags answer the skills question of `scope` (`--sets`, `--skills` or both): the one rule of ask_lists and of the
    questions that are skipped when every answer came by flag."""
    return flags.of(flags.sets, scope) is not None or flags.of(flags.skills, scope) is not None


def ask_lists(ctx, asker, scope, flags, definition_kinds, interactive):
    """The three list questions of one scope, each only when its flag is absent; the answers for it."""
    given_sets, given_skills, given_servers = flags.of(flags.sets, scope), flags.of(flags.skills, scope), flags.of(flags.servers, scope)
    label = "" if scope is None else "profile @%s: " % scope
    sets, skills, servers = given_sets, given_skills, given_servers
    if interactive and not lists_answered(flags, scope):  # the two questions, or none of them
        stack_sets = set(ctx.stack["skill_sets"]) if ctx.stack else set()
        rows = [(s, ctx.set_label(s) + (" (the stack's)" if s in stack_sets else ""), False) for s in ctx.sets]
        sets = asker.pick("sets", label + "skills, by sets of similar ones", rows)
        members = {n for s in sets or [] for n in ctx.sets.get(s, [])}
        skills = asker.pick("skills", label + "the final list of skills (the sets' members are on; add and remove)",
                            [(n, n, n in members) for n in ctx.installed])
    if servers is None and interactive:
        rows = ctx.server_rows(definition_kinds)
        servers = asker.pick("servers", label + "MCP servers (an account server is <service>-<project>)", [(s, s, False) for s in rows])
    return {"sets": sets or [], "skills": skills, "servers": servers or []}


def gather(a, ctx, asker, profile=None):
    """(Answers, problems). `profile`: the one profile `forge new @NAME` makes, None for `forge new NAME`. Asks what the flags did not
    answer, in the owner's order, only when `asker.interactive` and `a.yes` is not given; never writes."""
    problems = []
    if ctx.error:
        return Answers(), [ctx.error]
    flags = Flags(a, problems)
    ans = Answers()
    ask_on = asker.interactive and not getattr(a, "yes", False)
    if profile is not None:
        for flag, bad in (("--profiles", flags.profiles is not None), ("--memory", flags.memory is not None),
                          ("--check, --plugin, --ui and --command-guard", flags.stack_given())):
            if bad:
                problems.append("%s belong to making a project, not to a profile" % flag)
        ans.profiles = [profile]
    elif flags.profiles is not None:
        ans.profiles = flags.profiles
    elif ask_on:
        text = asker.line("profiles", "profiles in this project? names, separated by commas (empty for none): ")
        ans.profiles = [t for t in _names(text) if t] if text.strip() else []
    for n in ans.profiles:
        why = profiles.name_error(n)
        if why:
            problems.append("profile %s: %s" % (n, why))
    if len(set(ans.profiles)) != len(ans.profiles):
        problems.append("--profiles names a profile twice")
    if DEFAULT_LABEL in ans.profiles and profile is None:
        problems.append("a profile cannot be called %r: that is the label of the project's own lists" % DEFAULT_LABEL)
    scopes = list(ans.profiles) or [None]
    for table, flag in ((flags.sets, "--sets"), (flags.skills, "--skills"), (flags.servers, "--server")):
        for scope in (table or {}):
            if scope is not None and scope not in scopes:
                problems.append("%s @%s: that is not one of the profiles of this run (%s)" % (
                    flag, scope, ", ".join("@" + s for s in scopes if s) or "none: no profile is being made"))
    given_some = (any(t is not None for t in (flags.sets, flags.skills, flags.servers))
                  or (profile is None and (flags.profiles is not None or flags.memory is not None or flags.stack_given())))
    if given_some and not ask_on:  # nothing will be asked: one answer by flag, so every question needs its flag
        missing = ["--profiles"] if profile is None and flags.profiles is None else []
        for scope in scopes:
            where = "" if scope is None else " for @%s" % scope
            if not lists_answered(flags, scope):
                missing.append("--sets or --skills" + where)
            if flags.of(flags.servers, scope) is None:
                missing.append("--server" + where)
        if profile is None and flags.memory is None:
            missing.append("--memory")
        if missing:
            problems.append("nothing is asked here, and one question has its flag, so each needs its flag (none is an answer): missing %s"
                            % ", ".join(missing))
    if problems:
        return ans, problems
    for scope in scopes:
        kinds = None
        if scope is not None:
            try:
                existing = definition_or_none(scope)
            except profiles.ProfileError as e:
                problems.append(str(e))
                continue
            kinds = set(existing["server_kinds"]) if existing is not None else None
        ans.targets[scope] = ask_lists(ctx, asker, scope, flags, kinds, ask_on)
    if profile is None:
        memory_given = flags.memory is not None
        if memory_given:
            ans.memory = None if flags.memory == NONE else flags.memory
        elif ask_on:
            options = ctx.memory_options()
            rows = [(NONE, "none", True)] + [(m, "%s (%s)" % (m, ", ".join(MEMORY[m])), False) for m in options]
            chosen = asker.pick_one("memory", "memory", rows)
            ans.memory = None if chosen == NONE else chosen
        given_all = (flags.profiles is not None and flags.memory is not None and all(lists_answered(flags, s) for s in scopes)
                     and all(flags.of(flags.servers, s) is not None for s in scopes))
        stack = ctx.stack
        ans.stack = {"checks": flags.checks, "plugins": flags.plugins, "ui": flags.ui, "command_guard": flags.command_guard}
        if ask_on and not given_all and not flags.stack_given():
            rows = ([("check:%s" % c, "check: %s" % c, False) for c in stack["checks"]]
                    + [("plugin:%s" % p, "plugin: %s" % p, False) for p in stack["plugins"]]
                    + [("ui", "option: ui (the project has a user interface)", False),
                       ("command_guard", "option: command_guard", False)])
            chosen = asker.pick("stack", "what the %s stack asks (plugins: only these are kept, besides the common ones)" % (
                stack.get("name") or "chosen"), rows)
            ans.stack = {"checks": [k[6:] for k in chosen if k.startswith("check:")],
                         "plugins": [k[7:] for k in chosen if k.startswith("plugin:")],
                         "ui": "ui" in chosen, "command_guard": "command_guard" in chosen}
    return ans, problems


# ---- applying the answers to the documents ----------------------------------------------------------------------------------

def refusal_text(e):
    return str(e).replace("\n", " ")


def final_skills(ctx, target):
    """The final list of skills of one scope, sorted: `skills` as given, else the members of the sets."""
    if target["skills"] is not None:
        return sorted(set(target["skills"]))
    return sorted({n for s in target["sets"] for n in ctx.sets.get(s, [])})


def skill_items(ctx, target):
    """([the sets to name as `@SET`], [the skills to name]) of one scope: a chosen set whose every member is in the final list stays
    a set, and the rest of the final list is named. The same function for flags and for answers, so the same data gives the same row."""
    final = final_skills(ctx, target)
    whole = [s for s in ctx.sets if s in target["sets"] and set(ctx.sets[s]) <= set(final)]
    covered = {n for s in whole for n in ctx.sets[s]}
    return whole, [n for n in final if n not in covered]


def apply_project(ctx, ans, problems):
    """Puts the project's answers in ctx.proj and ctx.forge (the extras row), through the Draft. Problems for what the rules refuse."""
    target = ans.targets.get(None)
    if target is None:
        return
    draft = ctx.draft
    for s in target["sets"]:
        try:
            draft.need_set(s)
        except configure.Refusal as e:
            problems.append(refusal_text(e))
    if problems:
        return
    whole, _ = skill_items(ctx, target)
    steps = [("set", s, draft.set_on) for s in whole] + [("skill", n, draft.skill_on) for n in final_skills(ctx, target)]
    steps += [("server", s, draft.server_on) for s in sorted(set(target["servers"]))]
    for kind, name, fn in steps:
        if kind == "server" and name in ctx.memory_servers():
            problems.append("server '%s' is what the memory answer gives: --memory %s" % (
                name, next(m for m, servers in MEMORY.items() if name in servers)))
        elif kind == "server" and name in ctx.owner:
            problems.append("server '%s' is the account server of project %s; one for this project is named <service>-%s" % (
                name, ctx.owner[name], ctx.name))
        else:
            try:
                fn(name)
            except configure.Refusal as e:
                problems.append(refusal_text(e))


def profile_row(ctx, scope, target, kinds, problems):
    """(the project's row for profile `scope`, whether the definition needs `server_kinds` of the row's servers). The names are
    checked with the Draft's rules (what must exist), written as the profile's row holds them."""
    draft = ctx.draft
    whole, names = skill_items(ctx, target)
    for s in target["sets"]:
        try:
            draft.need_set(s)
            draft.need_members_installed(s)
        except configure.Refusal as e:
            problems.append("profile @%s: %s" % (scope, refusal_text(e)))
    for n in final_skills(ctx, target):
        try:
            draft.need_skill(n)
        except configure.Refusal as e:
            problems.append("profile @%s: %s" % (scope, refusal_text(e)))
    row = {}
    if whole or names:
        row["skills"] = ["@" + s for s in whole] + names
    assigned = {}
    for s in sorted(set(target["servers"])):
        try:
            draft.need("server", s, draft.registry(), " in config/mcp-registry.json")
            draft.need_secrets(s)
        except configure.Refusal as e:
            problems.append("profile @%s: %s" % (scope, refusal_text(e)))
            continue
        if s in ctx.memory_servers():
            problems.append("profile @%s: server '%s' is memory, which a profile does not have" % (scope, s))
        elif s in ctx.owner:
            problems.append("profile @%s: server '%s' is the account server of project %s" % (scope, s, ctx.owner[s]))
        else:
            kind = kind_of(s, ctx.name)
            if kind in assigned:
                problems.append("profile @%s: servers '%s' and '%s' are both the kind '%s'" % (scope, assigned[kind], s, kind))
            elif kinds is not None and kind not in kinds:
                problems.append("profile @%s: server '%s' is the kind '%s', and its definition lists %s" % (
                    scope, s, kind, ", ".join(sorted(kinds)) or "no kind"))
            else:
                assigned[kind] = s
    if kinds is not None:
        for kind in sorted(kinds - set(assigned)):
            problems.append("profile @%s: its definition needs a server of the kind '%s' (--server @%s:%s)" % (
                scope, kind, scope, "<server>"))
    if assigned:
        row["servers"] = assigned
    return row


def check_memory(ctx, ans, problems):
    if ans.memory is None:
        return
    if ans.memory not in MEMORY:
        problems.append("--memory: %s" % suggest.message("memory", ans.memory, [NONE] + list(MEMORY), ""))
    elif not lib.on(ans.memory):
        problems.append("--memory %s: the integration is off in config/forge.json (integrations.%s)" % (ans.memory, ans.memory))
    else:
        missing = [s for s in MEMORY[ans.memory] if s not in ctx.registry]
        if missing:
            problems.append("--memory %s needs %s in config/mcp-registry.json" % (ans.memory, ", ".join(missing)))
        else:
            for s in MEMORY[ans.memory]:
                try:
                    ctx.draft.server_on(s)
                except configure.Refusal as e:
                    problems.append(refusal_text(e))


def check_one_backend(ans, problems):
    """One project, one memory backend (the doctor's memory-one-backend row): the memory answer and the memory plugin are two."""
    if ans.memory and memory.LITE_PLUGIN in (ans.stack or {}).get("plugins", []):
        problems.append("--plugin %s is a memory backend and --memory %s is another: one per project, never both" % (memory.LITE_PLUGIN, ans.memory))


def check_stack(ctx, ans, problems):
    st = ans.stack
    if not st or ctx.stack is None:  # no stack: --stack is missing, and that is already said
        return
    for key, flag in (("checks", "--check"), ("plugins", "--plugin")):
        for item in st[key]:
            if item not in ctx.stack[key]:
                problems.append("%s: %s" % (flag, suggest.message(key[:-1], item, ctx.stack[key], " in the stack's list")))
    if st["ui"]:
        ctx.proj["ui"] = True
    if st["command_guard"]:
        ctx.proj["command_guard"] = True
    if st["checks"]:
        ctx.proj["checks"] = list(st["checks"])
    if st["plugins"]:
        ctx.proj["plugins_keep"] = list(st["plugins"])


def definition_or_none(name):
    """The definition of profile `name`, None when there is none yet; ProfileError when the file is there and wrong."""
    return profiles.definition(name) if os.path.exists(profiles.definition_path(name)) else None


def apply(ctx, ans):
    """Applies every answer to the documents of `ctx`. Returns (rows, new_definitions, problems): `rows` {profile: the project's row},
    `new_definitions` {profile: the definition to write} for the profiles that have none yet. Nothing is written."""
    problems = []
    rows, new_defs = {}, {}
    apply_project(ctx, ans, problems)
    check_memory(ctx, ans, problems)
    check_one_backend(ans, problems)
    check_stack(ctx, ans, problems)
    for scope in ans.profiles:
        target = ans.targets.get(scope)
        if target is None:
            continue
        try:
            existing = definition_or_none(scope)
        except profiles.ProfileError as e:
            problems.append(str(e))
            continue
        kinds = set(existing["server_kinds"]) if existing is not None else None
        row = profile_row(ctx, scope, target, kinds, problems)
        rows[scope] = row
        if existing is None:
            new_defs[scope] = {"description": "", "color": "", "skills": [], "plugins": [],
                               "server_kinds": sorted(row.get("servers", {})), "permissions": {}, "env": {}}
    if not problems:
        check_resolves(ctx, rows, new_defs, problems)
    return rows, new_defs, problems


def check_resolves(ctx, rows, new_defs, problems):
    """Each profile this run makes, as it will be (its definition, the one on disk or the new one, and its row in the project's file), goes
    through profiles.resolve: one that does not resolve, or resolves to nothing, is a problem with the reason resolve gives."""
    given = ctx.proj.get("profiles") if isinstance(ctx.proj.get("profiles"), dict) else {"default": DEFAULT_LABEL, "offered": {}}
    prof = dict(ctx.proj, profiles={"default": given["default"], "offered": {**given["offered"], **rows}})
    with profiles.pending_definitions(new_defs):
        for scope in rows:
            _, why = profiles.unresolved(ctx.name, prof, scope)
            if why:
                problems.append("profile @%s: %s" % (scope, why))
