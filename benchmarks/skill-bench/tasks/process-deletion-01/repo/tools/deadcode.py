"""Dead-code check: top-level functions in billing/ that no application code refers to.

A function counts as used when its name appears as an identifier (a call, an attribute, an import) in billing/ or
scheduler.py; tests do not count. Names listed in tools/deadcode-allow.txt are not reported. Exit 1 if any is unused."""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = ["billing", "scheduler.py"]


def py_files():
    for src in SOURCES:
        path = os.path.join(ROOT, src)
        if os.path.isfile(path):
            yield path
        for base, _, files in os.walk(path):
            for f in sorted(files):
                if f.endswith(".py"):
                    yield os.path.join(base, f)


def allowed():
    with open(os.path.join(ROOT, "tools", "deadcode-allow.txt")) as fh:
        return {line.split("#")[0].strip() for line in fh if line.split("#")[0].strip()}


def main():
    defs, used = {}, set()
    for path in py_files():
        rel = os.path.relpath(path, ROOT)
        with open(path) as fh:
            tree = ast.parse(fh.read(), rel)
        if rel.startswith("billing" + os.sep):
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    defs[node.name] = (rel, node.lineno)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.alias):
                used.add(node.name.split(".")[-1])
    unused = sorted((rel, line, name) for name, (rel, line) in defs.items()
                    if name not in used and name not in allowed())
    for rel, line, name in unused:
        print("%s:%d: unused function %s" % (rel, line, name))
    print("deadcode: %d unused function(s)" % len(unused))
    return 1 if unused else 0


if __name__ == "__main__":
    sys.exit(main())
