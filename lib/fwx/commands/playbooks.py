"""Playbook tools: `fwx playbooks tree` prints the workflow tree, one node per line with its exits.

`fwx playbooks tree [--tree PATH] [--scope NAME]` reads the Excalidraw tree (PATH, else `paths.tree` of the
configuration) and prints `id | kind | scope | text` per node, its exits indented under it as `kind id «label»`, and
the counts last. `scope` is the playbook playbooks/scope.tsv gives the node, `-` when it has no row; `--scope NAME`
keeps only that playbook's nodes. Exit 0, 1 when the tree has a fault (each is printed, naming what to change), 2 for a
usage error, a tree or scope file that cannot be read (or whose scope file is wrong), or no tree path at all.
"""
import sys

from fwx import config, tree

USAGE = "usage: fwx playbooks tree [--tree PATH] [--scope NAME]\n"
NO_TREE = ("fwx playbooks tree: no tree path: pass --tree PATH, or set `paths.tree` in .claude/fwx.json "
           "(the setup tool writes it)\n")


def _options(argv):
    """{flag: value} for --tree and --scope; None on a usage error."""
    opts, args = {}, list(argv)
    while args:
        flag = args.pop(0)
        if flag not in ("--tree", "--scope") or flag in opts or not args or args[0].startswith("-"):
            return None
        opts[flag] = args.pop(0)
    return opts


def _tree_command(argv):
    opts = _options(argv)
    if opts is None:
        sys.stderr.write(USAGE)
        return 2
    path, wanted = opts.get("--tree"), opts.get("--scope")
    try:
        if path is None:
            path = (config.load().get("paths") or {}).get("tree")
        if not path:
            sys.stderr.write(NO_TREE)
            return 2
        scope = tree.read_scope()
    except (config.ConfigError, tree.TreeError) as e:
        sys.stderr.write("fwx playbooks tree: %s\n" % e)
        return 2
    if wanted is not None and wanted not in tree.PLAYBOOKS:
        sys.stderr.write("fwx playbooks tree: unknown scope %r (scopes: %s)\n" % (wanted, ", ".join(tree.PLAYBOOKS)))
        return 2
    try:
        t = tree.read(path)
    except tree.TreeError as e:  # a path that cannot be read is a usage fault; a fault of the drawing exits 1
        sys.stderr.write("fwx playbooks tree: %s\n" % e)
        return 2 if isinstance(e, tree.Unreadable) else 1
    shown = [n for n in t.nodes if wanted is None or scope.get(n.id) == wanted]
    out = []
    for n in shown:
        out.append("%s | %s | %s | %s" % (n.id, n.kind, scope.get(n.id, "-"), n.text))
        for a in t.exits(n.id):
            out.append("    %s %s%s" % (a.kind, a.dst, " «%s»" % a.label if a.label else ""))
    ids = {n.id for n in shown}
    n_arrows = sum(1 for a in t.arrows if a.src in ids)
    from_conn = sum(1 for a in t.arrows if a.src in ids and t.node(a.src).kind == "connector")
    out.append("%d nodes, %d connectors, %d notes, %d arrows (%d from a connector)"
               % (sum(1 for n in shown if n.kind != "connector"), sum(1 for n in shown if n.kind == "connector"),
                  t.notes if wanted is None else 0, n_arrows, from_conn))
    print("\n".join(out))
    return 0


def main(argv):
    if argv and argv[0] == "tree":
        return _tree_command(argv[1:])
    sys.stderr.write(USAGE)
    return 2
