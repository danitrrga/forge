"""Playbook tools: `fwx playbook list` prints the workflow tree; `fwx playbook lint` checks the playbooks against it.

`fwx playbook lint [--tree PATH] [--only NAME]` reads every playbook (lib/fwx/playbooks.py says what it checks) and
prints its problems, one per line, then how many blocks and arrows it compared. Exit 0 clean, 1 with any problem, 77 when
what could run passed but no tree was given or no playbook has nodes yet (neither green nor red), 2 for a usage error or
a file that cannot be read. The tree is PATH, else `paths.tree` of the configuration, also from a worktree.

`fwx playbook list [--raw] [--tree PATH] [--scope NAME]` reads the Excalidraw tree (PATH, else `paths.tree` of the
configuration). Its default output is for a person: the nodes grouped by playbook (the stretch of the workflow), in
the drawing's order, each as `kind: text` with its exits indented under it as `then TITLE`, `loops back to TITLE`,
`sometimes TITLE` or `later TITLE` plus the arrow's label, and no internal id. TITLE is the target's text up to its
first colon (else cut at a word), and says `[playbook]` when the target is in another one. `--raw` prints the form the
agents and the checks read: `id | kind | scope | text` per node, its exits indented under it as `kind id «label»`. In
both, the counts come last. `scope` is the playbook playbooks/scope.tsv gives the node, `-` when it has no row;
`--scope NAME` keeps only that playbook's nodes. Exit 0, 1 when the tree has a fault (each is printed, naming what to change), 2 for a
usage error, a tree or scope file that cannot be read (or whose scope file is wrong), or no tree path at all.
"""
import sys

from fwx import config, playbooks, tree

USAGE = ("usage: fwx playbook list [--raw] [--tree PATH] [--scope NAME]\n"
         "       fwx playbook lint [--tree PATH] [--only NAME]\n")
NO_TREE = ("fwx playbook list: no tree path: pass --tree PATH, or set `paths.tree` in .claude/fwx.json "
           "(the setup tool writes it)\n")


def _options(argv, flags=("--tree", "--scope"), switches=()):
    """{flag: value} for the flags given (a switch has the value True); None on a usage error."""
    opts, args = {}, list(argv)
    while args:
        flag = args.pop(0)
        if flag in switches and flag not in opts:
            opts[flag] = True
            continue
        if flag not in flags or flag in opts or not args or args[0].startswith("-"):
            return None
        opts[flag] = args.pop(0)
    return opts


EXIT_WORDS = {"to": "then", "loop": "loops back to", "sometimes": "sometimes", "later": "later"}
WIDTH = 110


def _cut(text, n):
    """text on one line, at most n characters, cut at a word."""
    if len(text) <= n:
        return text
    return text[:n - 1].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"


def _title(text):
    """A short name in words for a node: its text up to the first colon, else cut at a word."""
    head = text.split(":", 1)[0].strip()
    return head if 4 <= len(head) <= 50 else _cut(text, 50)


def _readable(t, shown, scope):
    """The tree for a person: groups by playbook, one line per node, exits as `then TITLE`, no ids."""
    groups = {}
    for n in shown:
        groups.setdefault(scope.get(n.id), []).append(n)
    out = []
    for name in list(tree.PLAYBOOKS) + [None]:
        if name not in groups:
            continue
        nodes = groups[name]
        out += ["", "%s (%d)" % ((name or "no playbook").upper(), len(nodes)), ""]
        for n in nodes:
            out.append("  %-12s %s" % (n.kind, _cut(n.text, WIDTH - 14)))
            for a in t.exits(n.id):
                dst = t.node(a.dst)
                where = scope.get(dst.id)
                line = "%s %s%s" % (EXIT_WORDS.get(a.kind, a.kind), _title(dst.text),
                                    " [%s]" % where if where not in (name, "connector") else "")
                out.append("               " + line + (" — %s" % a.label if a.label else ""))
    return out[1:]


def _tree_command(argv):
    opts = _options(argv, switches=("--raw",))
    if opts is None:
        sys.stderr.write(USAGE)
        return 2
    path, wanted, raw = opts.get("--tree"), opts.get("--scope"), opts.get("--raw", False)
    try:
        if path is None:
            path = (config.load().get("paths") or {}).get("tree")
        if not path:
            sys.stderr.write(NO_TREE)
            return 2
        scope = tree.read_scope()
    except (config.ConfigError, tree.TreeError) as e:
        sys.stderr.write("fwx playbook list: %s\n" % e)
        return 2
    if wanted is not None and wanted not in tree.PLAYBOOKS:
        sys.stderr.write("fwx playbook list: unknown scope %r (scopes: %s)\n" % (wanted, ", ".join(tree.PLAYBOOKS)))
        return 2
    try:
        t = tree.read(path)
    except tree.TreeError as e:  # a path that cannot be read is a usage fault; a fault of the drawing exits 1
        sys.stderr.write("fwx playbook list: %s\n" % e)
        return 2 if isinstance(e, tree.Unreadable) else 1
    shown = [n for n in t.nodes if wanted is None or scope.get(n.id) == wanted]
    out = []
    if raw:
        for n in shown:
            out.append("%s | %s | %s | %s" % (n.id, n.kind, scope.get(n.id, "-"), n.text))
            for a in t.exits(n.id):
                out.append("    %s %s%s" % (a.kind, a.dst, " «%s»" % a.label if a.label else ""))
    else:
        out = _readable(t, shown, scope)
        out.append("")
    ids = {n.id for n in shown}
    n_arrows = sum(1 for a in t.arrows if a.src in ids)
    from_conn = sum(1 for a in t.arrows if a.src in ids and t.node(a.src).kind == "connector")
    out.append("%d nodes, %d connectors, %d notes, %d arrows (%d from a connector)"
               % (sum(1 for n in shown if n.kind != "connector"), sum(1 for n in shown if n.kind == "connector"),
                  t.notes if wanted is None else 0, n_arrows, from_conn))
    print("\n".join(out))
    return 0


def _check_command(argv):
    opts = _options(argv, ("--tree", "--only"))
    if opts is None:
        sys.stderr.write(USAGE)
        return 2
    path, only = opts.get("--tree"), opts.get("--only")
    if only is not None and only not in playbooks.NAMES:
        sys.stderr.write("fwx playbook lint: unknown playbook %r (playbooks: %s)\n" % (only, ", ".join(playbooks.NAMES)))
        return 2
    try:
        if path is None:
            path = (config.load().get("paths") or {}).get("tree")
        report = playbooks.check(tree_path=path or None, only=only)
    except (config.ConfigError, tree.TreeError) as e:
        sys.stderr.write("fwx playbook lint: %s\n" % e)
        return 2
    print("\n".join(report.lines()))
    return report.exit_code


def main(argv):
    if argv and argv[0] == "tree":
        return _tree_command(argv[1:])
    if argv and argv[0] == "check":
        return _check_command(argv[1:])
    sys.stderr.write(USAGE)
    return 2
