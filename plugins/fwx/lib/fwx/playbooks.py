"""The checker of the playbooks: does each playbook cover its stretch of the workflow tree, in the block format.

A playbook is `playbooks/<name>.md` for a name of tree.PLAYBOOKS (not `connector`: a connector has no block). It starts,
after its title, with `Version: <n>`, and holds one block per node of its scope:

    ### <Excalidraw element id> · <title in English>
    - **Who:** owner | orchestrator | agent <role>[, <role>] | script <command> | later
    - **Stage:** <a stage of data/stages.json, or ->
    - **Writes:** <files of .fwx/ separated by commas, or nothing>
    - **Invokes:** skill <x> | workflow <x> | command <x> | nothing
    - **Does:** one to three sentences.
    - **Exits:**                       (or `- **Exits:** none`)
      - <to|loop|sometimes|later|context> <id>: <condition>
    - **Why:** only when the rule does not explain itself (optional)

`check` reads every playbook that exists, with playbooks/scope.tsv and data/stages.json, and returns a Report. Without
the tree it checks the blocks alone and against each other: fields, one id once, Who and Stage from their lists, a
stage jump the machines allow, destinations in scope.tsv, one writer per file of `.fwx/` (the audit file aside:
state.append_audit writes it for everyone), a block in the playbook scope.tsv gives it, a block for each row of an
existing playbook, no model name in any playbooks/*.md. With the tree it also checks that the tree and scope.tsv list the
same nodes, that each block's Who fits its node, that its exits are the node's arrows one by one (an arrow out of a
connector is exempt: a connector has no block), and that the merge-rule box of the tree lists exactly the ids of
lib/fwx/core/decide_rules.json. Each problem names what to change, with the Spanish text of the node or arrow involved.

A playbook with no file is `NOT CHECKED`; no playbook with a block at all is `NOT RUN, NOT ARMED`, not a pass.
"""
import json
import os
import re

from fwx import config, tree
from fwx.core import stages

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
PLAYBOOK_DIR = os.path.join(ROOT, "playbooks")
STAGES_FILE = stages.TABLE
RULES_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "core", "decide_rules.json")
NAMES = tuple(p for p in tree.PLAYBOOKS if p != "connector")
EXIT_KINDS = ("to", "loop", "sometimes", "later", "context")
FIELDS = ("Who", "Stage", "Writes", "Invokes", "Does", "Exits", "Why")
REQUIRED = tuple(f for f in FIELDS if f != "Why")
AUDIT = "audit" + ".tsv"  # the one file of .fwx/ that every block may write; built, not spelled: tests/test_stages.py scans lib/ for the literal
MODEL = re.compile(r"\b(opus|sonnet|haiku|fable)\b", re.I)
HEADING = re.compile(r"### (\S+) · (\S.*)\Z")
VERSION = re.compile(r"Version:[ \t]*(\S+)[ \t]*\Z")
FIELD = re.compile(r"- \*\*([A-Za-z]+):\*\*[ \t]*(.*)\Z")
EXIT_ITEM = re.compile(r"[ \t]+- (.*)\Z")
EXIT = re.compile(r"(\w+) ([^\s:]+): (\S.*)\Z")
FILE_NAME = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*\Z")
INVOKES = re.compile(r"(skill|workflow|command) \S.*\Z")
RULE_BULLET = re.compile(r"•[ \t]*([a-z][a-z0-9-]*):")
# which Who a node of the tree takes, by its kind (the border colour); a grey block takes any but `later`
WHO_OF_KIND = {"owner": {"owner"}, "orchestrator": {"orchestrator"}, "agent": {"agent"}, "script": {"script"},
               "later": {"later"}, "block": {"owner", "orchestrator", "agent", "script"}}


class Block:
    def __init__(self, playbook, id, title, line):
        self.playbook, self.id, self.title, self.line = playbook, id, title, line
        self.fields = {}  # field name -> [text, line]
        self.exits = []  # [kind, destination, condition, line]
        self.who = None  # owner|orchestrator|agent|script|later once Who has been read

    def where(self):
        return "%s.md:%d" % (self.playbook, self.line)


class Report:
    def __init__(self):
        self.errors = []  # one sentence per problem, each naming what to change
        self.blocks = 0
        self.arrows = 0  # arrows of the tree compared with an exit
        self.not_checked = []
        self.playbooks = 0  # files with blocks
        self.tree_ran = False
        self.no_tree = False
        self.only = None

    @property
    def exit_code(self):
        if self.errors:
            return 1
        return 77 if (self.blocks == 0 or not self.tree_ran) else 0

    def lines(self):
        out = ["FAIL: " + e for e in self.errors]
        out += self.not_checked
        if self.blocks:
            out.append("checked %d blocks of %d playbook(s)%s" % (
                self.blocks, self.playbooks,
                ", compared with %d arrows of the tree" % self.arrows if self.tree_ran else
                " (no tree: node kinds and exits not compared)"))
        if self.blocks == 0 and not self.errors:
            out.append("NOT RUN, NOT ARMED: no playbook has nodes yet")
        elif self.no_tree and not self.errors:
            out.append("NOT RUN, NOT ARMED: no tree: pass --tree PATH or set `paths.tree` in .claude/fwx.json")
        if self.errors:
            out.append("%d problem(s)" % len(self.errors))
        return out


def parse(playbook, text):
    """(version, blocks, problems) of the text of playbook `playbook`; each problem is (line, sentence)."""
    problems, blocks, version = [], [], None
    cur = field = None
    fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if line.startswith("### "):
            head = HEADING.match(line)
            if not head:
                problems.append((n, "the heading `%s` is not `### <id> · <title>`: the id is the element id that "
                                    "`fwx playbook list` prints" % line.strip()))
                cur = field = None
                continue
            cur = Block(playbook, head.group(1), head.group(2).strip(), n)
            blocks.append(cur)
            field = None
            continue
        if re.match(r"#{1,2} ", line):
            cur = field = None
            continue
        if cur is None:
            m = VERSION.match(line)
            if m and version is None and not blocks:
                version = m.group(1)
            continue
        if not line.strip():
            continue
        fm = FIELD.match(line)
        if fm:
            name = fm.group(1)
            if name not in FIELDS:
                problems.append((n, "%s has the field %s, which a block does not have (fields: %s)"
                                 % (cur.id, name, ", ".join(FIELDS))))
                field = None
            elif name in cur.fields:
                problems.append((n, "%s has the field %s twice: keep one" % (cur.id, name)))
                field = None
            else:
                cur.fields[name] = [fm.group(2).strip(), n]
                field = name
            continue
        item = EXIT_ITEM.match(line)
        if field == "Exits" and item:
            m = EXIT.match(item.group(1).strip())
            if not m or m.group(1) not in EXIT_KINDS:
                problems.append((n, "%s has the exit `%s`: write `<%s> <id>: <condition>`"
                                 % (cur.id, item.group(1).strip(), "|".join(EXIT_KINDS))))
            else:
                cur.exits.append([m.group(1), m.group(2), m.group(3).strip(), n])
        elif field == "Exits" and cur.exits:
            cur.exits[-1][2] += " " + line.strip()
        elif field is None:
            problems.append((n, "%s has text outside a field: `%s`; start it with `- **<Field>:**`" % (cur.id, line.strip())))
        else:
            cur.fields[field][0] += " " + line.strip()
    return version, blocks, problems


def _backticks(text):
    return text.replace("`", "").strip()


def _who(text):
    """(kind, problem) of a Who value: kind is owner, orchestrator, agent, script or later; problem is None or a sentence."""
    t = _backticks(text)
    if t in ("owner", "orchestrator", "later"):
        return t, None
    if t.startswith("agent "):
        roles = [r.strip() for r in t[6:].split(",")]
        bad = [r for r in roles if r not in config.ROLES]
        if bad:
            return "agent", "unknown role %s (roles: %s)" % (", ".join(bad), ", ".join(config.ROLES))
        return "agent", None
    if t.startswith("script ") and t[7:].strip():
        return "script", None
    return None, ("`%s` is not a Who: write owner, orchestrator, agent <role>[, <role>], script <command> or later" % t)


def _stage_names(table):
    names = set()
    for m in table.values():
        names |= set(m["transitions"]) | set(m.get("terminal", ()))
        for to in m["transitions"].values():
            names |= set(to)
    return names


def _allowed(table, a, b):
    return any(b in m["transitions"].get(a, ()) for m in table.values())


def _rule_box(path):
    """(ids, frame name) of the box of the tree with most `• <id>:` bullets: free text elements grouped by their frame."""
    with open(path, encoding="utf-8") as f:
        elements = [e for e in json.load(f)["elements"] if isinstance(e, dict) and not e.get("isDeleted")]
    frames = {e["id"]: e.get("name") or e["id"] for e in elements if e.get("type") == "frame"}
    groups = {}
    for e in elements:
        if e.get("type") == "text" and not e.get("containerId"):
            m = RULE_BULLET.match((e.get("originalText") or e.get("text") or "").strip())
            if m:
                groups.setdefault(e.get("frameId"), []).append(m.group(1))
    if not groups:
        return [], None
    best = max(groups, key=lambda k: len(groups[k]))
    return groups[best], frames.get(best, "a box with no frame")


def _model_names(pdir):
    """[(file, line, word)] of every model name in any playbooks/*.md."""
    found = []
    for f in sorted(os.listdir(pdir)):
        if f.endswith(".md"):
            with open(os.path.join(pdir, f), encoding="utf-8") as fh:
                for n, line in enumerate(fh.read().splitlines(), 1):
                    found += [(f, n, m.group(1)) for m in MODEL.finditer(line)]
    return found


def check(pdir=PLAYBOOK_DIR, scope_path=None, stages_path=STAGES_FILE, tree_path=None, rules_path=RULES_FILE, only=None):
    """A Report on the playbooks in `pdir`. `tree_path` None: the checks that need the tree are not run. `only`: one
    playbook name; the problems of the blocks of the others are not reported (the files are all read: ids, writers and
    stages are compared across them). Raises tree.Unreadable for a scope file, stage table or tree that cannot be read."""
    rep = Report()
    rep.only = only
    scope = tree.read_scope(scope_path or os.path.join(pdir, "scope.tsv"))
    try:
        table = stages.load(stages_path)
    except stages.state.StateError as e:
        raise tree.Unreadable(str(e))
    known = _stage_names(table)
    rows = {n: [i for i, p in scope.items() if p == n] for n in NAMES}
    blocks, problems = [], []  # problems: (playbook or None, sentence)

    def problem(playbook, text):
        problems.append((playbook, text))

    for name in NAMES:
        path = os.path.join(pdir, name + ".md")
        if not os.path.exists(path):
            if rows[name] and only in (None, name):
                rep.not_checked.append("NOT CHECKED: %d nodes of %s (playbook not written yet)" % (len(rows[name]), name))
            continue
        with open(path, encoding="utf-8") as f:
            version, found, errs = parse(name, f.read())
        for n, text in errs:
            problem(name, "%s.md:%d: %s" % (name, n, text))
        if version is None or not re.match(r"\d+\Z", version):
            problem(name, "%s.md has no `Version: <n>` line (a whole number) before its first block%s"
                    % (name, ": it says `Version: %s`" % version if version else ""))
        blocks += found
        rep.playbooks += only in (None, name)

    for f, n, word in _model_names(pdir):
        problem(f[:-3] if f[:-3] in NAMES else None,
                "%s:%d names a model (%s): a playbook never names one; the model comes from `fwx model <role> <size>`"
                % (f, n, word))

    first, writers = {}, {}
    stage_of = {}
    for b in blocks:
        if b.id in first:
            problem(b.playbook, "block id %s appears in two blocks (%s and %s): one block per node; delete one or fix the id"
                    % (b.id, first[b.id].where(), b.where()))
        else:
            first[b.id] = b
            stage_of[b.id] = _backticks(b.fields["Stage"][0]) if "Stage" in b.fields else None  # the first block's stage
    for b in blocks:
        at = "%s %s" % (b.where(), b.id)
        for f in REQUIRED:
            if f not in b.fields or (f != "Exits" and not b.fields[f][0]):
                problem(b.playbook, "%s lacks the field %s: add `- **%s:** %s`" % (at, f, f, {
                    "Who": "owner|orchestrator|agent <role>|script <command>|later",
                    "Stage": "<a stage of data/stages.json, or ->", "Writes": "<files of .fwx/, or nothing>",
                    "Invokes": "skill <x>|workflow <x>|command <x>|nothing", "Does": "<one to three sentences>",
                    "Exits": "none` or one `  - <kind> <id>: <condition>` per arrow"}[f]))
        pb = scope.get(b.id)
        if pb is None:
            problem(b.playbook, "%s is not in scope.tsv: add `%s<TAB>%s` (`fwx playbook list` lists the ids)"
                    % (at, b.id, b.playbook))
        elif pb == "connector":
            problem(b.playbook, "%s is a connector in scope.tsv, and a connector has no block: delete the block" % at)
        elif pb != b.playbook:
            problem(b.playbook, "%s is in %s.md but scope.tsv assigns it to %s: move the block to %s.md or change its row"
                    % (at, b.playbook, pb, pb))
        if "Who" in b.fields and b.fields["Who"][0]:
            b.who, why = _who(b.fields["Who"][0])
            if why:
                problem(b.playbook, "%s Who: %s" % (at, why))
        stage = _backticks(b.fields["Stage"][0]) if "Stage" in b.fields else None
        if stage and stage != "-" and stage not in known:
            problem(b.playbook, "%s has Stage %s, which is not a stage of data/stages.json (stages: %s, or `-`)"
                    % (at, stage, ", ".join(sorted(known))))
        if "Writes" in b.fields and b.fields["Writes"][0]:
            w = [_backticks(x) for x in b.fields["Writes"][0].split(",")]
            if w == ["nothing"]:
                w = []
            elif "nothing" in w or not all(FILE_NAME.match(x) for x in w):
                problem(b.playbook, "%s Writes `%s`: write `nothing` alone, or files of .fwx/ separated by commas"
                        % (at, b.fields["Writes"][0]))
                w = []
            for x in w:
                if x != AUDIT and x in writers and writers[x] != b.id:
                    problem(b.playbook, "%s is written by %s and by %s: one block writes each file of .fwx/; move one write "
                                        "to the other's block or drop it (%s is the exception: state.append_audit writes it)"
                            % (x, writers[x], b.id, AUDIT))
                writers.setdefault(x, b.id)
        if "Invokes" in b.fields and b.fields["Invokes"][0]:
            v = _backticks(b.fields["Invokes"][0])
            if v != "nothing" and not INVOKES.match(v):
                problem(b.playbook, "%s Invokes `%s`: write skill <x>, workflow <x>, command <x> or nothing" % (at, v))
        if "Exits" in b.fields:
            v = b.fields["Exits"][0]
            if v and v != "none":
                problem(b.playbook, "%s Exits `%s`: write `none`, or one `  - <kind> <id>: <condition>` line per arrow" % (at, v))
            elif v == "none" and b.exits:
                problem(b.playbook, "%s says Exits none and lists exits: delete one of them" % at)
            elif not v and not b.exits:
                problem(b.playbook, "%s has an empty Exits: write `none` or one `  - <kind> <id>: <condition>` per arrow" % at)
        seen = set()
        for kind, dest, _, line in b.exits:
            if (kind, dest) in seen:
                problem(b.playbook, "%s.md:%d %s has the exit %s %s twice (the same exit twice): keep one"
                        % (b.playbook, line, b.id, kind, dest))
            seen.add((kind, dest))
            if dest not in scope:
                problem(b.playbook, "%s.md:%d %s exits to %s, which is not in scope.tsv: fix the id (`fwx playbook list` "
                                    "lists them) or add its row" % (b.playbook, line, b.id, dest))
        for kind, dest, _, line in b.exits:
            to_stage = stage_of.get(dest)
            if stage and stage != "-" and to_stage and to_stage != "-" and to_stage != stage \
                    and stage in known and to_stage in known and not _allowed(table, stage, to_stage):
                problem(b.playbook, "%s.md:%d %s (stage %s) exits to %s (stage %s): data/stages.json allows no %s -> %s; "
                                    "fix the Stage of a block or the exit, or change the table"
                        % (b.playbook, line, b.id, stage, dest, to_stage, stage, to_stage))
    for name in NAMES:
        have = {b.id for b in blocks if b.playbook == name}
        if have or os.path.exists(os.path.join(pdir, name + ".md")):
            for i in rows[name]:
                if i not in have:
                    problem(name, "scope.tsv gives %s.md the node %s and it has no block: write `### %s · <title>`"
                            % (name, i, i))
    shown = [b for b in blocks if only in (None, b.playbook)]
    rep.blocks = len(shown)

    if tree_path is None:
        rep.no_tree = True
    else:
        try:
            t = tree.read(tree_path)
        except tree.Unreadable:
            raise
        except tree.TreeError as e:
            problem(None, "the tree has faults, so nothing was compared with it: %s" % str(e).replace("\n", "; "))
            t = None
        if t is not None:
            rep.tree_ran = True
            _compare(t, scope, shown, first, rep, problem, tree_path, rules_path)
    rep.errors = [t for p, t in problems if only is None or p == only]
    return rep


def _compare(t, scope, blocks, first, rep, problem, tree_path, rules_path):
    ids = {n.id for n in t.nodes}
    for n in t.nodes:
        if n.id not in scope:
            problem(None, "node %s «%s» is in the tree and has no row in scope.tsv: add `%s<TAB><playbook>`"
                    % (n.id, n.text, n.id))
    for i in scope:
        if i not in ids:
            problem(None, "scope.tsv has a row for %s and the tree has no such node: delete the row (and its block), or "
                          "restore the node in the tree" % i)
    for b in blocks:
        if first.get(b.id) is not b:
            continue
        at = "%s %s" % (b.where(), b.id)
        if b.id not in ids:
            if b.id in scope:
                continue  # already said: the row has no node
            problem(b.playbook, "%s is not a node of the tree: delete the block or fix its id" % at)
            continue
        node = t.node(b.id)
        if node.kind == "connector":
            continue
        if b.who and b.who not in WHO_OF_KIND[node.kind]:
            problem(b.playbook, "%s is a node of kind %s in the tree («%s») and its Who is %s: write %s"
                    % (at, node.kind, node.text, b.who, " or ".join(sorted(WHO_OF_KIND[node.kind]))))
        want = t.exits(b.id)
        rep.arrows += len(want)
        have = [(k, d) for k, d, _, _ in b.exits]
        left = [a for a in want if (a.kind, a.dst) not in have]
        extra = [(k, d) for (k, d) in have if not any(a.kind == k and a.dst == d for a in want)]
        for a in list(left):
            twin = next((e for e in extra if e[1] == a.dst), None)
            if twin:
                left.remove(a)
                extra.remove(twin)
                problem(b.playbook, "%s: the exit to %s is written as `%s` and the tree draws `%s` «%s»: write `%s %s: <condition>`"
                        % (at, a.dst, twin[0], a.kind, a.label or "(no label)", a.kind, a.dst))
        for a in left:
            dest = t.node(a.dst).text if a.dst in ids else a.dst
            problem(b.playbook, "%s has no exit to %s: «%s» (the %s arrow from «%s» to «%s»): add `  - %s %s: <condition>` "
                                "under Exits" % (b.id, a.dst, a.label or "(no label)", a.kind, node.text, dest, a.kind, a.dst))
        for k, d in extra:
            problem(b.playbook, "%s exits to %s (%s), but the tree draws no such arrow from «%s»: delete the exit, or draw "
                                "the arrow" % (at, d, k, node.text))
    ids_box, frame = _rule_box(tree_path)
    try:
        with open(rules_path, encoding="utf-8") as f:
            rules = [r["id"] for r in json.load(f)["rules"]]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise tree.Unreadable("cannot read the merge rules %s (%s)" % (rules_path, e))
    if not ids_box:
        problem(None, "the tree has no box of merge rules (text elements `• <id>: <reason>`): nothing to compare with %s"
                % os.path.basename(rules_path))
    elif sorted(ids_box) != sorted(rules):
        problem(None, "the merge-rule box of the tree («%s», %d rules) and %s differ: the tree lacks %s, and has %s that the "
                      "file lacks; make them the same list"
                % (frame, len(ids_box), os.path.basename(rules_path), sorted(set(rules) - set(ids_box)) or "none",
                   sorted(set(ids_box) - set(rules)) or "none"))
