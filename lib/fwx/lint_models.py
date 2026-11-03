"""Lint: every agent() call in a workflow names its model and its agentType, no agents/*.md declares a
model, and nothing launches a fork.

Why: the model of a subagent is chosen by whoever launches it (a per-call `model` outranks the
frontmatter, which outranks the environment), so a call without one silently inherits the parent's.
This reads workflows/*.js with a small tokenizer that skips comments, strings, regular expressions
and the text of templates (their `${...}` expressions are read, as code), then checks that the second
argument of each `agent(` is an object literal with a `model` key and an `agentType` key. `agent(p, opts)`
fails: the model is not visible. agents/*.md fails when its frontmatter has a top-level `model:`.

agentType: without it the agent reaches the SubagentStart hook as `workflow-subagent` (measured) and the
hook cannot tell its role. A fork (`subagent_type` or `agentType` set to `fork`, in a workflow script or in
any text of workflows/, skills/, agents/ or playbooks/) ignores `model` and carries the launcher's whole
conversation, against the explicit-model rule and the independence of reviewers. The text check is a line
pattern, so prose that quotes `subagent_type: fork` is a fault too.

Run it: `python3 lib/fwx/lint_models.py [--root DIR | PATH...]`. With no PATH it lints DIR (default:
this repo) and a tree with no workflow or agent file is fine, it says "0 workflow file(s)". With
PATHs (a .js, a .md, or a directory holding workflows/ and agents/) looking at zero files is a
failure. Exit 0 clean, 1 on a fault or a script it could not read.
"""
import glob
import os
import re
import sys

OPEN = {"(": ")", "[": "]", "{": "}", "${": "}"}
# after these a `/` starts a regular expression; after anything else a name, a number, `)` or `]` it divides
REGEX_AFTER_WORD = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do",
                    "else", "yield", "await"}


class Unreadable(Exception):
    def __init__(self, line, msg):
        Exception.__init__(self, msg)
        self.line, self.msg = line, msg


def tokenize(text):
    """[(kind, value, line)]: kind is 'id' (names and numbers), 'str' (value: the text of a quoted
    string, else None) or 'p' (one punctuation character, or '${'). Raises Unreadable."""
    toks, i, n, line = [], 0, len(text), 1
    depth = []  # one counter per open `${`: how many plain `{` are open inside it

    def regex_here():
        if not toks:
            return True
        kind, val, _ = toks[-1]
        if kind == "id":
            return val in REGEX_AFTER_WORD
        return kind == "p" and val not in (")", "]")

    def template(i, line):  # scan a template's text from i; stops after the closing backtick or at a `${`
        start = line
        while i < n:
            c = text[i]
            if c == "\\":
                line += text[i:i + 2].count("\n")
                i += 2
            elif c == "`":
                toks.append(("str", None, start))
                return i + 1, line
            elif c == "$" and text.startswith("${", i):
                toks.append(("str", None, start))
                toks.append(("p", "${", line))
                depth.append(0)
                return i + 2, line
            else:
                line += c == "\n"
                i += 1
        raise Unreadable(start, "unterminated template literal")

    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                raise Unreadable(line, "unterminated comment")
            line += text.count("\n", i, j)
            i = j + 2
        elif c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\n":
                    raise Unreadable(line, "unterminated string")
                if text[j] == "\\":
                    if text[j + 1:j + 2] == "\n":
                        line += 1
                    j += 1
                j += 1
            if j >= n:
                raise Unreadable(line, "unterminated string")
            toks.append(("str", text[i + 1:j], line))
            i = j + 1
        elif c == "`":
            i, line = template(i + 1, line)
        elif c == "/" and regex_here() and _regex_end(text, i) > 0:
            j = _regex_end(text, i)
            toks.append(("str", None, line))
            i = j
        elif c == "}" and depth and depth[-1] == 0:  # the end of a `${...}`: back into the template's text
            depth.pop()
            toks.append(("p", "}", line))
            i, line = template(i + 1, line)
        elif c.isalnum() or c in "_$" or ord(c) > 127:
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_$" or ord(text[j]) > 127):
                j += 1
            toks.append(("id", text[i:j], line))
            i = j
        else:
            if depth and c == "{":
                depth[-1] += 1
            elif depth and c == "}":
                depth[-1] -= 1
            toks.append(("p", c, line))
            i += 1
    return toks


def _regex_end(text, i):
    """Index after the regular expression (and its flags) starting at text[i] == '/', or 0 when the
    line ends first (then it was a division)."""
    j, n, in_class = i + 1, len(text), False
    while j < n and text[j] != "\n":
        c = text[j]
        if c == "\\":
            j += 1
        elif c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < n and text[j].isalpha():
                j += 1
            return j
        j += 1
    return 0


def match_brackets(toks):
    """{index of an opener: index of its closer}; raises Unreadable on a stray or missing bracket."""
    match, stack = {}, []
    for k, (kind, val, line) in enumerate(toks):
        if kind != "p":
            continue
        if val in OPEN:
            stack.append(k)
        elif val in (")", "]", "}"):
            if not stack or OPEN[toks[stack[-1]][1]] != val:
                raise Unreadable(line, "unbalanced %r" % val)
            match[stack.pop()] = k
    if stack:
        raise Unreadable(toks[stack[-1]][2], "unclosed %r" % toks[stack[-1]][1])
    return match


def split(toks, match, lo, hi):
    """The top-level comma-separated pieces of toks[lo:hi] as (start, end) ranges; a trailing comma adds no piece."""
    parts, start, k = [], lo, lo
    while k < hi:
        if toks[k][0] == "p" and toks[k][1] in OPEN:
            k = match[k]
        elif toks[k][0] == "p" and toks[k][1] == ",":
            parts.append((start, k))
            start = k + 1
        k += 1
    if start < hi:
        parts.append((start, hi))
    return parts


def names_key(toks, match, lo, hi, key="model"):
    """True when toks[lo:hi], one property of an object literal, is `key: <value>` or the shorthand `key`."""
    if lo >= hi or toks[lo][0] not in ("id", "str") or toks[lo][1] != key:
        return False
    if hi == lo + 1:
        return toks[lo][0] == "id"  # `{ model }`
    if toks[lo + 1][:2] != ("p", ":"):
        return False
    value = toks[lo + 2:hi]
    return bool(value) and not (len(value) == 1 and value[0][0] == "id" and value[0][1] in ("undefined", "null"))


def lint_js(text):
    """(agent() calls looked at, [problem]) for one script; a problem is (None, line, kind, message) with kind
    'model', 'agentType', 'fork' or 'parse'. A script it cannot read is one 'parse' problem and 0 calls."""
    try:
        toks = tokenize(text)
        match = match_brackets(toks)
    except Unreadable as e:
        return 0, [(None, e.line, "parse", e.msg)]
    calls, problems = 0, []
    for k, (kind, val, line) in enumerate(toks):
        if (kind in ("id", "str") and val in FORK_KEYS and k + 2 < len(toks)
                and toks[k + 1][:2] == ("p", ":") and toks[k + 2][:2] == ("str", "fork")):
            problems.append((None, line, "fork", FORK_MSG))
        if kind != "id" or val != "agent" or k + 1 >= len(toks) or toks[k + 1][:2] != ("p", "("):
            continue
        close = match[k + 1]
        if (k > 0 and toks[k - 1][:2] == ("id", "function")) or (close + 1 < len(toks) and toks[close + 1][:2] == ("p", "{")):
            continue  # `function agent(...)` or a method `agent(...) {`: a declaration, not a call
        calls += 1
        args = split(toks, match, k + 2, close)
        if len(args) < 2:
            problems.append((None, line, "model", "agent() has no options argument, so it names no model"))
            continue
        lo, hi = args[1]
        if toks[lo][:2] != ("p", "{") or match[lo] != hi - 1:
            problems.append((None, line, "model", "agent()'s second argument is not an object literal, so the model is not visible"))
            continue
        props = split(toks, match, lo + 1, hi - 1)
        if not any(names_key(toks, match, a, b) for a, b in props):
            problems.append((None, line, "model", "agent() options have no `model` key"))
        if not any(names_key(toks, match, a, b, "agentType") for a, b in props):
            problems.append((None, line, "agentType", "agent() without agentType: it would be workflow-subagent"))
    return calls, problems


FORK_KEYS = ("agentType", "subagent_type")
FORK_MSG = "a fork launch: a fork ignores `model` and carries the launcher's whole conversation"
FORK_TEXT = re.compile(r"""(?:subagent_type|agentType)["'`]*\s*[:=]\s*["'`]*fork(?![\w-])""")


def lint_text(text):
    """[problem] for any text of workflows/, skills/, agents/ or playbooks/: a line that sets `subagent_type` or
    `agentType` to `fork` (quoted or not, `:` or `=`)."""
    return [(None, k, "fork", FORK_MSG) for k, row in enumerate(text.split("\n"), start=1) if FORK_TEXT.search(row)]


FRONT_MODEL = re.compile(r"""^["']?model["']?\s*:""")


def lint_md(text):
    """[problem] for one agents/*.md: a top-level `model:` in its frontmatter (the lines between a first `---` and the next)."""
    rows = text.split("\n")
    if not rows or rows[0].rstrip() != "---":
        return []
    out = []
    for k, row in enumerate(rows[1:], start=2):
        if row.rstrip() == "---":
            break
        if FRONT_MODEL.match(row):
            out.append((None, k, "model", "agent frontmatter declares `model:`; whoever launches the agent passes it"))
    return out


class Report:
    def __init__(self):
        self.js = self.md = self.text = self.calls = 0
        self.problems = []  # (path, line, kind, message)

    def add_file(self, path, text_only=False):
        """A .md is an agent file (frontmatter and fork check) unless text_only (fork check only)."""
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if path.endswith(".md"):
            if text_only:
                self.text += 1
                found = lint_text(text)
            else:
                self.md += 1
                found = lint_md(text) + lint_text(text)
        else:
            self.js += 1
            calls, found = lint_js(text)
            self.calls += calls
        self.problems.extend((path,) + p[1:] for p in found)


def lint_root(root):
    """Lint root/workflows/*.js and root/agents/*.md, and look for a fork in the .md of workflows/, skills/ and
    playbooks/ (skills and playbooks are walked). Looking at none is not a fault here."""
    rep = Report()
    for path in sorted(glob.glob(os.path.join(root, "workflows", "*.js")) + glob.glob(os.path.join(root, "agents", "*.md"))):
        rep.add_file(path)
    prose = glob.glob(os.path.join(root, "workflows", "*.md"))
    for d in ("skills", "playbooks"):
        prose += glob.glob(os.path.join(root, d, "**", "*.md"), recursive=True)
    for path in sorted(prose):
        rep.add_file(path, text_only=True)
    return rep


def lint_paths(paths):
    """Lint explicit paths: a .js or .md file, or a directory holding workflows/ and agents/. A path that is
    missing or yields no file is a fault: asked to look at something, finding nothing is not a pass."""
    rep = Report()
    for p in paths:
        before = rep.js + rep.md + rep.text
        if os.path.isdir(p):
            sub = lint_root(p)
            rep.js, rep.md, rep.text, rep.calls = rep.js + sub.js, rep.md + sub.md, rep.text + sub.text, rep.calls + sub.calls
            rep.problems.extend(sub.problems)
        elif os.path.isfile(p) and p.endswith((".js", ".md")):
            rep.add_file(p)
        if rep.js + rep.md + rep.text == before:
            rep.problems.append((p, 0, "empty", "no workflow or agent file to look at"))
    return rep


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    paths = []
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--root" and args:
            root = args.pop(0)
        elif a in ("-h", "--help"):
            print((__doc__ or "").strip().split("\n\n")[-1])
            return 0
        else:
            paths.append(a)
    rep = lint_paths(paths) if paths else lint_root(root)
    for path, line, kind, msg in rep.problems:
        print("%s:%d: %s" % (path, line, msg))
    print("looked at %d workflow file(s), %d agent file(s), %d agent() call(s), %d other text file(s): %d fault(s)"
          % (rep.js, rep.md, rep.calls, rep.text, len(rep.problems)))
    return 1 if rep.problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
