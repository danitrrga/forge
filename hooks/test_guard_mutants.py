#!/usr/bin/env python3
"""Mutation check for test_guard_tool_use.py: weakens guard_tool_use.py one rule at a
time and requires the suite to fail on every mutant. Runs under `forge test`.

Copied from a downstream project's .claude/hooks/mutate_guard.py at d923f2ce, renamed so
`forge test` runs it, less the downstream project's 6 mutants of rules the core does not carry (the
GUARD_BYPASS toggle and environment switch, LEFTHOOK_BIN set and nested, the pause
file's Write/Edit check and its lexical form; the core has the LEFTHOOK_BIN rule since a later round,
and the mutants numbered 10 are its own); docs/command-guard-design.md. Of the downstream project's
100 left, five search a text forge changed and are rewritten (marked); the mutants numbered
1 to 7 are forge's additions and the "config:" ones its per-project config file.

Why it exists: the independent review (harness-security.md M2) weakened
the guard 25 ways and 11 of those weakened guards still passed the suite of the time.
A suite that cannot tell a working guard from a broken one proves nothing. The mutants
below cover the review's 25 where the rule still exists, plus every rule added since.

Run: python3 hooks/test_guard_mutants.py
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "tests"))
import sandbox  # noqa: E402

SRC = open(os.path.join(HERE, "guard_tool_use.py"), encoding="utf-8").read()
TEST = os.path.join(HERE, "test_guard_tool_use.py")

MUTANTS = {
    # The review's mutants, mapped onto the current code.
    "segment naming a secret is never dangerous (the 13-leak version)":
        ("        if seg_names_secret(pat, seg) and not inert_segment(pat, seg):\n            return True\n", ""),
    "drop the indirect read ($_ after naming a secret)":
        # Rewritten in forge: an awk program that opens nothing is blanked first (8b).
        ("    return any(INDIRECT_READ.search(AWK_PROGRAM.sub(awk_fields, seg)) for seg in segs)", "    return False"),
    "inert_segment always true":
        ("def inert_segment(pat, seg):\n", "def inert_segment(pat, seg):\n    return True\n"),
    # Rewritten in forge: the destination's name is what counts (8b), not every path's.
    "relocate: the source keeps the secret name, not the destination":
        ("bool(re.search(pat, paths[-1]))", "bool(re.search(pat, paths[0]))"),
    "grep and rg always inert (content search of a secret)":
        ("        return not re.search(DUMP_COMMANDS, part) or only_pattern_names(pat, cmd, args, part)", "        return True"),
    "drop the process.env / import.meta.env lookbehind (over-block)":
        # Rewritten in forge: the env pattern carries ENV_TEMPLATE (addition 1).
        (r'r"(?<!process)(?<!meta)\.env(?!(?:', r'r"\.env(?!(?:'),
    "drop KEYRING_DUMP check":
        ("if KEYRING_DUMP.search(low) and not REDIRECT_TO_FILE.search(cmd):", "if False:"),
    "drop PROTECTED_FILES check (Read/Write/Edit)":
        # Rewritten in forge: the loop also takes the config's secret_paths.
        ("            for pat in PROTECTED_FILES + secrets:\n                if re.search(pat, p):\n                    deny(",
         "            for pat in PROTECTED_FILES + secrets:\n                if False:\n                    deny("),
    "drop harness write block":
        ("            if harness_write(pcmd):", "            if False:"),
    "drop DANGEROUS_SHELL loop":
        ("                    deny(reason)\n            for d in OOB_DOMAINS:", "                    pass\n            for d in OOB_DOMAINS:"),
    "drop out-of-band domains":
        # Rewritten in forge: the message says what to do instead.
        ('                    deny("out-of-band exfiltration domain matched (%s). Instead, send nothing "\n'
         '                         "there; ask the user if a collector is really needed" % d)', "                    pass"),
    "drop .pem from SECRET_FILES":
        (r'r"credentials\.json", *SSH_KEYS, r"\.pem\b",', r'r"credentials\.json", *SSH_KEYS,'),
    "drop id_ed25519 from SECRET_FILES":
        # Rewritten in forge: SSH_KEYS carries id_ecdsa and id_dsa after it (addition 4).
        (r'SSH_KEYS = (r"id_rsa\b", r"id_ed25519\b", ', r'SSH_KEYS = (r"id_rsa\b", '),
    "drop backslash-newline join":
        ('    low = re.sub(r"\\\\\\r?\\n", " ", low)\n    segs', "    segs"),
    # Rules added after the independent review.
    "drop the lefthook bypass checks":
        ("            reason = hook_bypass(pcmd)\n            if reason:", "            reason = None\n            if reason:"),
    "drop git commit -n":
        ('        if re.match(r"^-[a-zA-Z]+$", a) and "n" in a[1:]:', "        if False:"),
    "drop .env.example exclusion (over-block)":
        # Rewritten in forge: the exclusion is every template, not .env.example alone.
        (r'''\.env(?!(?:\.[\w-]+)*?\." + ENV_TEMPLATE + r"(?![\w.-]))\b"''', r'''\.env\b"'''),
    "drop the glob patterns":
        (r'r"\.en[*?\[]", r"\.\[e\]", r"\.e\{",', ""),
    "drop the name-fragment pattern":
        ("""    r"(?:^|[\\s=/'\\"])\\.en?(?=$|[\\s;&|'\\"}]|\\$)",\n""", ""),
    "drop .mcp.json and codex from SECRET_FILES":
        (r'r"\.mcp\.json", r"\.codex[\\/]config\.toml",', ""),
    "drop the user-level credential stores":
        (r'r"\.config/gh/hosts\.yml", r"\.npmrc\b", r"com\.vercel\.cli/auth\.json",', ""),
    "prose args lose their substitutions (-m \"$(cat secret)\" passes)":
        ('seg = seg[:a0] + (" ".join(subs) or "PROSE") + seg[b0:]', 'seg = seg[:a0] + "PROSE" + seg[b0:]'),
    "prose treatment for every command (ssh 'cat secret' passes)":
        ("tuple(strip_prefix(words)[:2]) in PROSE_BEARING:", "True:"),
    "prose split ignores pipes (gh pr list | sh -c '...' passes)":
        ('PROSE_SEP = re.compile(r"&&|\\|\\||[;&|\\n]")', 'PROSE_SEP = re.compile(r"&&|\\|\\||[;\\n]")'),
    "script heredocs treated as prose (cat > run.sh <<EOF passes)":
        (r'[^\s;&|<>`()]+\.(?:md|txt|rst)\s*" + _DELIM', r'[^\s;&|<>`()]+\s*" + _DELIM'),
    "unquoted prose heredocs lose their substitutions":
        ('            if not quoted and ("$(" in body', '            if False and ("$(" in body'),
    "a prose heredoc line may carry another command before the idiom":
        (r'_PLAIN = r"[^;&|<>`$()\n]*?"', r'_PLAIN = r".*?"'),
    "a prose heredoc line may start with any command":
        (r'_LEAD = r"^(?P<lead>(?:[^<\n]*?(?:&&|;))?)\s*"', r'_LEAD = r"^(?P<lead>.*?)"'),
    "gh release counts as a message verb (uploads a file)":
        (r'gh\s+(?:pr|issue)\s+(?:create|edit|comment|review|close)', r'gh\s+(?:pr|issue|release)\s+\w+'),
    "prose heredoc stripped without its closing delimiter (bash agrees, may survive)":
        ("        if end is None:\n            continue\n", "        if end is None:\n            end = len(lines)\n"),
    "prose idiom accepted inside an open quote":
        ('        if before.endswith("\\\\") or split_words(before) is None:',
         '        if before.endswith("\\\\"):'),
    "shell words not checked (quote-split names pass)":
        ("    return tokens is not None and any(re.search(pat, t) for t in tokens)", "    return False"),
    "drop pipe-to-exec (ls secret | xargs cat)":
        ('    if PIPE_TO_EXEC.search("|".join(rest)):\n        return False\n', ""),
    "cp/ln destination read as the first path, not the last":
        ("        dest, srcs = paths[-1:], paths[:-1]", "        dest, srcs = paths[:1], paths[1:]"),
    "drop cp -t":
        ('            if (a == "--target-directory" or (m and not m.group(1))) and i + 1 < len(args):', "            if False:"),
    "drop sed -i / perl -i":
        ("""    elif cmd in ("sed", "perl") and any(""", """    elif False and any("""),
    "drop redirect targets":
        # Rewritten in forge: a `>` in quotes is text unless the command runs quoted text (8f).
        # Rewritten in forge: each redirect word is expanded for braces (round 9).
        ("    out = [(t, WRITE) for m in REDIRECT_TARGET.finditer(seg)\n"
         "           for t in brace_words(m.group(1) + (\"(\" if m.group(1).endswith(\"$\") and seg[m.end():m.end() + 1] == \"(\" else \"\"))\n"
         "           if not any(a <= seg.find(\">\", m.start()) < b for a, b in spans)]", "    out = []"),
    "drop nested bash -c":
        ('    bodies = nested_bodies(words, NESTING_SHELLS + ("xargs",))\n    if not bodies:', '    bodies = []\n    if not bodies:'),
    "drop interpreter writes":
        ("        if WRITEISH.search(c) and any(", "        if False and any("),
    "ignore cd inside the command":
        ("                base = os.path.join(base, d)", "                pass"),
    "ignore variables when resolving write targets":
        ("                if harness_target(t2 if t2 is not None else t, level) or", "                if harness_target(t, level) or"),
    "an unknown cd target moves the directory away (bypass)":
        ("            if d is not None:\n                base = os.path.join(base, d)",
         "            base = os.path.join(base, d) if d is not None else '/nonexistent'"),
    "no prose stripping (commit messages block)":
        ("            pcmd = strip_prose(cmd)", "            pcmd = cmd"),
    "every mention of hooksPath counts as a set (over-block)":
        ('    if "hookspath" in low and hookspath_set(cmd):', '    if "hookspath" in low:'),
    "git config core.hooksPath <value> not seen":
        ("            if after or \"xargs\" in wrappers:\n                return True", "            pass"),
    "drop -c core.hooksPath= and GIT_CONFIG_* env":
        ('    if re.search(r"-c\\s*core\\.hookspath\\s*=|git_config_(?:key|parameters|count)", low):', "    if False:"),
    "drop .git/config from the harness paths":
        ('    r"|(?:^|/)\\.git/config$"\n', ""),
    "drop interpreter heredocs":
        ("+ [m.group(2) for m in HEREDOC_CODE.finditer(cmd)]", ""),
    "drop pipe split in harness writes":
        ("        for part in split_pipes(seg):", "        for part in [seg]:"),
    "harness scope: any path counts, scratch copies too (over-block)":
        ("    if not inside:\n        return False", "    if False:\n        return False"),
    "harness scope: nothing counts":
        ("    if not inside:\n        return False", "    if True:\n        return False"),
    "the hooks' bytecode cache is not the harness (a forged .pyc can be written)":
        ("    if not inside:\n        return False", '    if not inside or "/__pycache__" in real:\n        return False'),
    "drop git checkout/restore of harness files":
        ('        if sub and sub[0] in ("checkout", "restore"):', "        if False:"),
    "drop git rm / git mv of harness files":
        ('        elif sub and sub[0] in ("rm", "mv"):', "        elif False:"),
    "drop the Grep path check":
        (' or tool == "Grep":', ":"),
    # Rules added in the fix round after the break-it round on PR #23.
    "U11 log dir made outside the try (an unwritable log exits 1)":
        # Rewritten in forge: the variable is FORGE_GUARD_LOG_DIR.
        ('    try:\n        log_dir = os.environ.get("FORGE_GUARD_LOG_DIR") or os.path.join(ROOT, "logs")\n        os.makedirs(log_dir, exist_ok=True)\n',
         '    log_dir = os.environ.get("FORGE_GUARD_LOG_DIR") or os.path.join(ROOT, "logs")\n    os.makedirs(log_dir, exist_ok=True)\n    try:\n'),
    "U14 git global options not skipped":
        ('    while i < len(args) and args[i].startswith("-"):', "    while False:"),
    "U44 only the full --no-verify":
        (r'r"--no-v(?:e(?:r(?:i(?:f(?:y)?)?)?)?)?(?![\w-])"', r'r"--no-verify\b"'),
    "U46 -t only as its own word":
        ('m = re.match(r"^-[a-zA-Z]*t(.*)$", a) if cmd != "rsync" else None', 'm = re.match(r"^-t()$", a) if cmd != "rsync" else None'),
    "U47 the harness dirs do not count":
        ("    return (level >= WRITE and real in HARNESS_DIRS) or (level >= WHOLE and real == PROJECT)", "    return False"),
    "U47 the repo root counts for every write (cp x . blocked)":
        ("(level >= WHOLE and real == PROJECT)", "(real == PROJECT)"),
    "U47 deletes count like writes (rm -rf . passes)":
        ("        out += [(p, WHOLE) for p in paths]", "        out += [(p, WRITE) for p in paths]"),
    "U47 a copy's destination/<source name> not checked":
        ('                out.append((d, WHOLE) if whole else (os.path.join(d, name), WRITE))', "                pass"),
    "U47 a contents sync counts as a named copy":
        ('                whole = s.endswith("/") or s.endswith("/.") or not name', "                whole = False"),
    "U47 a move's sources not checked":
        ("        if cmd == \"mv\":\n            out += [(s, WHOLE) for s in srcs]", "        if cmd == \"mv\":\n            pass"),
    "U47 globs in a target not expanded":
        # Rewritten in forge: the answer is kept per target (round 9), so `return any(` moved.
        ("    if GLOB.search(p):\n        # Asked once", "    if False:\n        # Asked once"),
    "U47 no stand-in name for a glob":
        ('] + ["_g_"] if GLOB.search(part)', '] if GLOB.search(part)'),
    "U47 glob names matched anywhere, not where the harness is (over-block)":
        ("        hit = HARNESS_PATH.match(os.path.relpath(real, root))", "        hit = HARNESS_PATH.search(real)"),
    "U73 a link's source not checked":
        ("            out += [(s, WRITE) for s in srcs]", "            pass"),
    "U17 the Read tool may open the user-level stores":
        # Rewritten in forge: `\\b`, not `$`, after each name (round 9).
        ('    r"/\\.secrets\\b", r"/\\.config/gh/hosts\\.yml\\b", r"/\\.npmrc\\b", r"com\\.vercel\\.cli/auth\\.json\\b",\n', ""),
    "U17 the Read tool may open a test login":
        # Rewritten in forge: the first entry ends in `\\b`, not `$` (round 9).
        ('    r"credentials[^/]*\\.local\\b", r"/\\.dev-credentials[^/]*$",\n', ""),
    "a test login readable from Bash":
        ('    r"credentials[^/\\s\'\\"]*\\.local\\b", r"\\.dev-credentials\\b",\n', ""),
    "Hindsight's client config and control token readable from Bash":
        ('    r"coding-agent\\.json", r"control\\.token",\n', ""),
    "the Read tool may open the .bak copy of Hindsight's client config":
        # Rewritten in forge: control.token lost its `$` too (round 9), so only this one is put back.
        ('r"/coding-agent\\.json", r"/control\\.token",', 'r"/coding-agent\\.json$", r"/control\\.token",'),
    "U72 drop the aws, kube and docker stores":
        ('    r"\\.aws/credentials\\b", r"\\.kube/config\\b", r"\\.docker/config\\.json\\b",\n', ""),
    "pipeline judged by its first command (ls | cat secret passes)":
        ("    parts = [p for p in stages if seg_names_secret(pat, p)]\n    return bool(parts) and all(inert_command(pat, p) for p in parts)",
         "    return inert_command(pat, seg)"),
    "find always inert (find -exec cat passes)":
        ('        return not any(a in ("-exec", "-execdir", "-ok", "-okdir") for a in args)', "        return True"),
    "find never inert (over-block)":
        ('    if cmd == "find":', "    if False:"),
    "U13 a grep for a secret's name counts as a read (over-block)":
        (" or only_pattern_names(pat, cmd, args, part)", ""),
    "U13 every grep that names a secret is a search for its name":
        ("def only_pattern_names(pat, cmd, args, seg):\n", "def only_pattern_names(pat, cmd, args, seg):\n    return True\n"),
    "Python heredoc prose not blanked (over-block)":
        ("    text = _python_prose(_prose_heredocs(cmd))", "    text = _prose_heredocs(cmd)"),
    "a Python heredoc that starts a process is blanked too":
        ("    if any(t.type == tokenize.NAME and", "    if False and any(t.type == tokenize.NAME and"),
    "a one-word Python literal counts as prose":
        (r'and re.search(r"\S\s+\S", words):', r'and True:'),
    "an unquoted heredoc counts as Python prose":
        (r"""(?:(['\"])(\w+)\1|\\(\w+))""", r"""(?:(['\"]?)(\w+)\1|\\(\w+))"""),
    "U64 no public-key exemption (over-block)":
        ("    if (pat in SSH_KEYS and", "    if (False and"),
    "U13 an e inside a flag cluster read as -E (grep -ei <secret> passes)":
        ('"grep": set("abcghilnopqrstuvwxyz")', '"grep": set("abceghilnopqrstuvwxyz")'),
    "rm of a secret counts as a read (over-block)":
        ('"du", "wc", "file", "rm", "tree"}', '"du", "wc", "file", "tree"}'),
    "U64 a rebuilt name counts as a public key":
        ('            and not re.search(r"\\$\\{|\\$\\(|`", low) and not PIPE_TO_EXEC.search(low)):', "            ):"),
    "a pipe into the shell's `.` is not an exec (| . /dev/stdin passes)":
        (r"|parallel|while|source)\b|\.(?=\s|$))", r"|parallel|while|source)\b)"),
    # A nested shell whose body has a ; or a pipe.
    "harness writes: no quote-aware cut":
        ("    if _segments_write(split_unquoted(text, SEGMENT_SPLIT), pipeline, start):\n        return True\n", ""),
    "segments(): no quote-aware cut":
        ("    return blind + [s for s in split_unquoted(text, SEGMENT_SPLIT) if s not in seen]", "    return blind"),
    "pieces(): later commands of a pipe not checked":
        ("for p in [s] + pipeline(s)[1:]]", "for p in [s]]"),
    "git commit -n not looked for inside a nested shell":
        ("        return any(commit_n(p) for a in bodies for p in pieces(a))", "        return False"),
    # jq whose filter names `.env` as a JSON field.
    "jq always inert (jq -R . <secret> passes)":
        ("        return only_jq_path_names(pat, args, part)", "        return True"),
    "jq never inert (over-block)":
        ("        return only_jq_path_names(pat, args, part)", "        return False"),
    "jq file operands not checked":
        ("    return not any(re.search(pat, f) for f in files)", "    return True"),
    "jq string literal naming a secret not checked":
        ("    if any(re.search(pat, s) for s in JQ_STRING.findall(filt)):", "    if False:"),
    "jq accepts any long option (--from-file)":
        ("            if a not in JQ_BOOL_LONG:", "            if False:"),
    "jq accepts any short flag (-f)":
        ("            if not set(a[1:]) <= JQ_BOOL_SHORT:", "            if False:"),
    "jq ignores a substitution in the segment":
        ('    if re.search(r"\\$\\(|`|<", seg):\n        return False\n    positional = []', "    positional = []"),
    # forge's additions (docs/command-guard-design.md), one or more each.
    "1. .env.example is the only template":
        ('ENV_TEMPLATE = r"(?:example|sample|template|dist)"', 'ENV_TEMPLATE = r"(?:example)"'),
    "1. Bash: a template word anywhere makes a template (.env.sample.local passes)":
        (r'''+ ENV_TEMPLATE + r"(?![\w.-]))\b"''', r'''+ ENV_TEMPLATE + r"\b)\b"'''),
    "1. Read: a template word anywhere makes a template (.env.sample.local opens)":
        ('+ ENV_TEMPLATE + r"$)|$)"', '+ ENV_TEMPLATE + r")|$)"'),
    "1. Read: a template only right after .env (.env.tunnel.sample protected)":
        (r'''r"\.env(?:\.(?!(?:[^/]*\.)?" + ENV_TEMPLATE''', r'''r"\.env(?:\.(?!" + ENV_TEMPLATE'''),
    "2. base64: any pipe counts again (| base64 -d | head refused)":
        (r'''    r"(\|\s*(?:sudo''', r'''    r"(\||\|\s*(?:sudo'''),
    "2. base64: a pipe into an interpreter passes":
        (r'''|python[\d.]*|perl|ruby|node|php|deno|bun|source|eval|xargs)\b"''', r''')\b"'''),
    "2. base64: a pipe into the shell's `.` passes":
        (r'''    r"|\|\s*\.(?=\s|$)|\$\(''', r'''    r"|\$\('''),
    "2. base64: a decode inside a substitution passes":
        (r'''|\$\(|`|<\(|\bsh\b''', r'''|\bsh\b'''),
    "3. forge's hooks/ and config/guard/ are not harness":
        ('MACHINE_HARNESS = [os.path.join(FORGE, "hooks"), os.path.join(FORGE, "config", "guard"),', "MACHINE_HARNESS = ["),
    "3. forge's config/guard/ is not harness":
        (', os.path.join(FORGE, "config", "guard"),', ","),
    "3. the directories that hold forge's harness do not count":
        ("    if level >= WRITE and real in MACHINE_DIRS:", "    if False:"),
    "3. forge's harness checked only inside the project":
        ("    if any(real == b or real.startswith(b + \"/\") for b in MACHINE_HARNESS):\n        return True\n", ""),
    "3. a glob does not expand to guard/":
        ('"lefthook-local.yml", "guard", ', '"lefthook-local.yml", '),
    "4. Bash may print ~/.claude.json":
        (r'''    r"(?:^|[\s/=])\.claude\.json", r"\.aws/config\b", FORGE_CREDENTIALS,''', r'''    r"\.aws/config\b", FORGE_CREDENTIALS,'''),
    "4. .claude.json anywhere in a name (forge's profiles refused)":
        (r'''    r"(?:^|[\s/=])\.claude\.json", r"\.aws/config\b",''', r'''    r"\.claude\.json", r"\.aws/config\b",'''),
    "8d. a quote before .claude.json counts again (forge's profile code refused)":
        (r'''    r"(?:^|[\s/=])\.claude\.json", r"\.aws/config\b",''', r'''    r"(?:^|[\s/'\"=])\.claude\.json", r"\.aws/config\b",'''),
    "4. Bash may print ~/.aws/config":
        (r''', r"\.aws/config\b", FORGE_CREDENTIALS,''', r''', FORGE_CREDENTIALS,'''),
    "4. Bash may print forge's credentials/":
        (r''', r"\.aws/config\b", FORGE_CREDENTIALS,''', r''', r"\.aws/config\b",'''),
    "4. the Read tool may open the new stores":
        (r'''    r"/\.claude\.json", r"/\.aws/config\b", r"/id_ecdsa", r"/id_dsa", FORGE_CREDENTIALS_PATH,''', ""),
    "4. id_ecdsa and id_dsa are not keys in Bash":
        (r''', r"(?<!\w)id_ecdsa\b", r"(?<!\w)id_dsa\b")''', ")"),
    "4. the .pub exemption knows only rsa and ed25519 (cat id_ecdsa passes)":
        ("id_(?:rsa|ed25519|ecdsa|dsa)(?!", "id_(?:rsa|ed25519)(?!"),
    "4. key names unanchored (valid_dsa.py refused)":
        (r'''r"(?<!\w)id_ecdsa\b", r"(?<!\w)id_dsa\b"''', r'''r"id_ecdsa\b", r"id_dsa\b"'''),
    "4. forge's credentials/ only as an absolute path":
        (r'''FORGE_CREDENTIALS = r"(?:^|[\s/'\"=])" + _FORGE_NAME''', r'''FORGE_CREDENTIALS = r"/" + _FORGE_NAME'''),
    "5. HUSKY=0 passes":
        ('    if any(n == "husky" and SWITCH_OFF.match(v) for n, v in assigns):', "    if False:"),
    "5. LEFTHOOK=0 passes":
        ('    if any(n == "lefthook" and SWITCH_OFF.match(v) for n, v in assigns):', "    if False:"),
    "5. quotes are text, not the shell's (LEFTHOOK='0', 'LEFTHOOK'=0, \"HUSKY\"=0, 'LEFTHOOK_BIN'=x pass)":
        ('        words = split_words(REDIRECTION.sub(" ", seg))\n        if words is None:\n            found',
         '        words = REDIRECTION.sub(" ", seg).split()\n        if words is None:\n            found'),
    "5. .husky/ is not a harness path":
        ('    r"|(?:^|/)\\.husky(?:/|$)"\n', ""),
    "5. a glob does not expand to .husky":
        ('"guard", ".husky",', '"guard",'),
    "6. ~/.codex/hooks.json is not harness":
        (',\n                   os.path.join(HOME, ".codex", "hooks.json")]', "]"),
    "6. ~/.codex does not count as a directory that holds it":
        (', os.path.join(HOME, ".codex")}', "}"),
    "6. a glob does not expand to hooks.json":
        ('".husky",\n                 "hooks.json")', '".husky")'),
    "7. redirections read as values (git config core.hooksPath 2>&1 refused)":
        ('            words = split_words(REDIRECTION.sub(" ", stage))', "            words = split_words(stage)"),
    "7. a redirection's target read as a value (> /tmp/h refused)":
        (r'''|\s*[^\s;&|<>()'\"]+)")''', r'''|[^\s;&|<>()'\"]+)")'''),
    "7. a redirection eats the value after its target (> /tmp/h /x passes)":
        (r'''|\s*[^\s;&|<>()'\"]+)")''', r'''|\s*.*)")'''),
    # 8. The friction fixes from the replay of one project's recorded commands, each in both directions.
    "8b. cd and mkdir inert even with a substitution":
        ("        return not SUBSTITUTES.search(part)\n", "        return True\n"),
    "8b. cd, pushd and mkdir not inert (over-block)":
        ('NO_SUBSTITUTION = {"cd", "pushd", "mkdir"}', "NO_SUBSTITUTION = set()"),
    "8b. awk inert whatever its program opens":
        ("    return len(args) == i + 1 and not AWK_OPENS.search(args[i])", "    return len(args) == i + 1"),
    "8b. awk inert with a file operand":
        ("    return len(args) == i + 1 and not AWK_OPENS.search(args[i])",
         "    return len(args) >= i + 1 and not AWK_OPENS.search(args[i])"),
    "8b. awk never inert (over-block)":
        ("        return inert_awk(args, part)", "        return False"),
    "8b. an awk program blanked even when it can open":
        ("    return m.group(0) if AWK_OPENS.search(m.group(2)) else m.group(1)",
         "    return m.group(1)"),
    "8b. awk's $N read as the shell's arguments (over-block)":
        ("INDIRECT_READ.search(AWK_PROGRAM.sub(awk_fields, seg))", "INDIRECT_READ.search(seg)"),
    "8b. a grep flag with its number attached not understood (over-block)":
        ('            if not set(a[1:].rstrip("0123456789")) <= (bools | {"m"} if a[-1].isdigit() else bools):',
         "            if not set(a[1:]) <= bools:"),
    "8b. ssh inert whatever its remote command":
        ("                and not any(re.search(pat, a) for a in args[:-1]) and not secret_dump(pat, bodies[0]))",
         "                and not any(re.search(pat, a) for a in args[:-1]))"),
    "8b. a move into a secret name not inert (over-block)":
        ("bool(re.search(pat, paths[-1]))", "all(re.search(pat, p) for p in paths)"),
    "8c. a loop variable not replaced by the name it lists":
        ('        low = re.sub(r"\\$\\{%s\\}|\\$%s(?!\\w)" % (var, var), lambda _: name, low)', "        pass"),
    "8c. echo and printf inert however loud the command":
        ("    quiet = not LOUD.search(low)", "    quiet = True"),
    "8c. a redirect into a file is not loud":
        (r'''SUBSTITUTES.pattern + r"|>(?!\s*(?:&|/dev/null\b))|"''', r'''SUBSTITUTES.pattern + r"|"'''),
    "8c. a loop header with a substitution skipped":
        (r'''\s+in\s+([^`$<>()[\]{}:,]*?)\s*$")''', r'''\s+in\s+(.*?)\s*$")'''),
    "8c. a Python for loop read as a shell loop header":
        (r'''\s+in\s+([^`$<>()[\]{}:,]*?)\s*$")''', r'''\s+in\s+([^`$<>()]*?)\s*$")'''),
    "8c. echo and printf never inert (over-block)":
        ("        if seg in headers or (quiet and echoes(seg)):", "        if seg in headers:"),
    "8c. loop headers never skipped (over-block)":
        ("        if seg in headers or (quiet", "        if False or (quiet"),
    "8c. if is not a prefix (over-block)":
        ('"else", "if", "elif", "while"', '"else", "while"'),
    "8e. a file heredoc blanked even when the same call runs it":
        ('        if m.groupdict().get("t") and runs_later(m.group("t"), lines[end + 1:]):\n            continue\n', ""),
    "8e. a later glob cannot run the written file":
        ("        if not name or name in seg or GLOB.search(seg):", "        if not name or name in seg:"),
    "8e. every later command leaves the written file alone":
        ("        if words and (words[0] in LEAVES_FILE or", "        if words and (True or"),
    "8e. git add reads the written file back (over-block)":
        ('(words[0] == "git" and git_subcommand(words[1:])[1][:1] == ["add"])', "False"),
    "8e. text fed to grep is code (over-block)":
        ('    re.compile(_LEAD + r"(?:grep|rg)\\b" + _PLAIN + _DELIM),\n', ""),
    "8e. a file of any kind is code (over-block)":
        ('    re.compile(_LEAD + r"cat\\s*>>?\\s*(?P<t>[^\\s;&|<>`()]+)\\s*" + _DELIM),\n', ""),
    "8e. a pathspec after -F - makes the message code (over-block)":
        ('r"(?:-F|--file)\\s*-(?=\\s|<)" + _PLAIN + _DELIM', 'r"(?:-F|--file)\\s*-\\s*" + _DELIM'),
    "8f. a `>` in quotes is text even where quoted text runs as shell":
        ("            for t, level in write_targets(part, not RUNS_QUOTED.search(seg)):",
         "            for t, level in write_targets(part, True):"),
    "8f. awk's own redirect is not seen":
        ("|[gmn]?awk|perl|ruby)\\b\")", "|perl|ruby)\\b\")"),
    "8f. a `>` in quotes is a redirect again (over-block)":
        ("    spans = _quoted_spans(seg) if quoted_text else []", "    spans = []"),
    "8g. printf -v counts as printing a name":
        ('(words[0] == "printf" and not any(\n        w.startswith("-v") for w in words[1:]))', 'words[0] == "printf"'),
    "8g. an interpreter's spawn does not run quoted text":
        ("|exec\\w*|spawn\\w*|system|popen|subprocess|child_process|", "|exec|"),
    "8g. a shell startup file is not run by later calls":
        ("    if name in SHELL_STARTUP:\n        return True\n", ""),
    "9. a tool_name that is not a string crashes the guard":
        ("    if not tool or not isinstance(tool, str):", "    if not tool:"),
    "9. a one-word commit message is never prose (git commit -m .env refused)":
        ('        seg = ONE_WORD_MESSAGE.sub(r"\\1PROSE", seg)\n', ""),
    "9. a one-word message may be a word the shell expands (-m .env* passes)":
        ('_WORD = r"[^\\s\'\\"`$()<>*?\\[\\]{}\\\\;&|]+"', '_WORD = r"[^\\s\'\\"]+"'),
    "9. a one-word message may run on into the next word (-m .env* passes)":
        ('(?:%s|\'%s\'|\\"%s\\")(?=\\s|$)"', '(?:%s|\'%s\'|\\"%s\\")"'),
    "9. any word before -m (git commit --author -m .env passes)":
        ("(?:\\s+(?:-[aqsv]+|--(?:amend|no-edit|all|quiet|signoff|allow-empty|verbose)))*", "(?:\\s+\\S+)*"),
    "10. LEFTHOOK_BIN is not looked for (LEFTHOOK_BIN=/bin/true git commit passes)":
        ('    if any(n == "lefthook_bin" for n, v in assigns):', '    if False:'),
    "10. an assignment is looked for as text anywhere (echo \"LEFTHOOK_BIN=$LEFTHOOK_BIN\" refused)":
        ('        words = split_words(REDIRECTION.sub(" ", seg))\n        if words is None:', '        words = None\n        if words is None:'),
    "10. export, declare and typeset are not assignments (export LEFTHOOK_BIN=/bin/true passes)":
        ("        if rest and os.path.basename(rest[0]) in ENV_DECLARERS:", "        if False:"),
    "10. a nested shell's or eval's body is not read (bash -c 'LEFTHOOK_BIN=/bin/true git commit' passes)":
        ("        for body in bodies:\n            found += command_assignments(body, depth + 1)", "        for body in bodies:\n            pass"),
    "10. a command substitution's body is not read (echo \"$(HUSKY=0 git push)\" passes)":
        ("        bodies += [b for w in words if SUBSTITUTION_OPEN.search(w) for b in SUBSTITUTION_OPEN.split(w)[1:]]\n", ""),
    "10. a command the shell cannot parse is not read as text (an open quote passes)":
        ("            found += [(m.group(1), m.group(2)) for m in LOOSE_ASSIGNMENT.finditer(seg)]", "            found += []"),
    "10. a later command of a pipe is not a command (ls | LEFTHOOK_BIN=/bin/true git commit passes)":
        ("    for seg in pieces(text):\n        words = split_words(REDIRECTION", "    for seg in segments(text):\n        words = split_words(REDIRECTION"),
    "10. LEFTHOOK_BIN refused wherever it is named (unset, grep and echo refused)":
        ('    if "hookspath" in low and hookspath_set(cmd):\n        return "overriding',
         '    if "lefthook_bin" in low:\n        return "LEFTHOOK_BIN chooses the hooks binary"\n'
         '    if "hookspath" in low and hookspath_set(cmd):\n        return "overriding'),
    "11. a pipe's later command read as the value (git config core.hooksPath | head -1 refused)":
        ("        for stage in pipeline(seg):", "        for stage in [seg]:"),
    "11. a setter inside sh -c / eval is not looked for":
        ("                if any(hookspath_set(a) for a in bodies):\n                    return True\n", ""),
    "11. an unquoted eval's command is not read (eval git config core.hooksPath /x passes)":
        ('            if words and words[0] == "eval":\n                words = words[1:]\n', ""),
    "11. --unset of core.hooksPath allowed":
        ("            if any(w in GIT_CONFIG_UNSET for w in before):\n                return True\n", ""),
    "11. a read flag no longer lets core.hooksPath through (--get refused)":
        ("            if any(w in GIT_CONFIG_READ for w in before):\n                continue\n", ""),
    "12. ~/.hindsight/*.json|token|env not a credential store in Bash":
        ('FORGE_CREDENTIALS, HINDSIGHT_STORE,\n    FORGE_CONFIG_SECRETS,\n]', 'FORGE_CREDENTIALS,\n    FORGE_CONFIG_SECRETS,\n]'),
    "12. ~/.hindsight/*.json|token|env not a protected file":
        ('FORGE_CREDENTIALS_PATH,\n    HINDSIGHT_STORE, FORGE_CONFIG_SECRETS_PATH,\n]', 'FORGE_CREDENTIALS_PATH,\n    FORGE_CONFIG_SECRETS_PATH,\n]'),
    "12. ~/.hindsight/ subdirectories read as stores (over-block)":
        ("(?:profiles/[^/\\s'\\\"]*\\.env|[^/\\s'\\\"]*\\.(?:json|token|env))", "(?:profiles/[^/\\s'\\\"]*\\.env|.*\\.(?:json|token|env))"),
    "13. $PWD not expanded to the working directory":
        ('    env["PWD"] = start\n    groups = []', '    groups = []'),
    "13. $PWD not moved by a cd of the command":
        ('                env["PWD"] = base\n', ""),
    "14. git grep is never a name-only search (git grep -n '\\.env' -- docs refused)":
        ('    if cmd == "git grep":\n        return only_pattern_names(pat, cmd, args, part)\n', ""),
    "14. git grep's pathspecs after -- read as the pattern (-- .env passes)":
        ('            others.extend(args[i + 1:])\n            break\n', "            patterns.extend(args[i + 1:])\n            break\n"),
    "15. config/secrets* not a credential store in Bash (secrets.yaml)":
        ('FORGE_CREDENTIALS, HINDSIGHT_STORE,\n    FORGE_CONFIG_SECRETS,\n]', 'FORGE_CREDENTIALS, HINDSIGHT_STORE,\n]'),
    "15. config/secrets* not a protected file":
        ('    HINDSIGHT_STORE, FORGE_CONFIG_SECRETS_PATH,\n]', '    HINDSIGHT_STORE,\n]'),
    "16. the cd-resolved text is not checked":
        ("            texts = [plow, resolved]\n", "            texts = [plow]\n"),
    "16. a cd of the command is not followed":
        ('                bases = bases + [where] if i and seps[i - 1] == "||" else [where]\n', "                pass\n"),
    "16. a cd after || replaces the places the command may be in":
        ('bases = bases + [where] if i and seps[i - 1] == "||" else [where]', "bases = [where]"),
    "16. a relative word is not resolved against a cd to something unreadable":
        ("            if unsure and not os.path.isabs(e) and STORE_SHAPED_NAME.search(e.lower()):", "            if False:"),
    "16. an absolute cd leaves the guard unsure":
        ("                unsure = unsure and not os.path.isabs(d)\n", "                unsure = unsure\n"),
    "16. a glob or substitution in a cd's path is readable":
        ('UNREADABLE_DIR = re.compile(r"[$`*?\\[{(]")', 'UNREADABLE_DIR = re.compile(r"(?!)")'),
    "16. the event's cwd is not where the command starts":
        ("    bases, unsure, env, out = [CWD[0]], False,", "    bases, unsure, env, out = [os.sep], False,"),
    "16. a subshell's opening parenthesis hides its cd":
        ("        words = split_words(marked)\n", "        words = split_words(seg)\n"),
    "16. a word that is an option is resolved as a path":
        # Rewritten in forge: the character class lost `*?[`, which a glob branch reads (round 9).
        ('            if w.startswith("-") or re.search(r"[\\s{},;<>()|&`]", w):\n                continue\n', ""),
    "16. git's subcommand is resolved as a path (git log in credentials/ refused)":
        ('                subcommand = w == "git"\n', '                subcommand = False\n'),
    "16. a segment of only a closing parenthesis crashes cd_resolved":
        ("        if not words:\n            out.append(seg)\n            continue\n        env[\"PWD\"]", "        env[\"PWD\"]"),
    # The per-project config file, one or more per key and per refusal.
    "config: secret_paths left out of the Bash check":
        ("            for pat in SECRET_FILES + secrets:", "            for pat in SECRET_FILES:"),
    "config: secret_paths left out of the protected-file check":
        ("            for pat in PROTECTED_FILES + secrets:", "            for pat in PROTECTED_FILES:"),
    "config: secret_paths matched case-sensitively":
        ('        secrets.append("(?i)" + pat)', "        secrets.append(pat)"),
    "config: harness_paths ignored":
        ("    for b in PROJECT_HARNESS:\n        if real == b or real.startswith(b + \"/\"):\n            return True\n",
         "    for b in PROJECT_HARNESS:\n"),
    "config: the directories that hold a harness_path do not count":
        ('        if level >= WRITE and real.startswith(PROJECT + "/") and b.startswith(real + "/"):', "        if False:"),
    "config: a harness_path's parent counts up to the filesystem root (git restore . refused)":
        ('        if level >= WRITE and real.startswith(PROJECT + "/") and b.startswith(real + "/"):',
         '        if level >= WRITE and b.startswith(real.rstrip("/") + "/"):'),
    "config: a glob does not expand to a harness_path's name":
        ("    known = HARNESS_NAMES + tuple(os.path.basename(b) for b in PROJECT_HARNESS)", "    known = HARNESS_NAMES"),
    "config: a file that does not parse runs the core alone":
        ('        raise ValueError("%s does not parse (%s)" % (path, e))', "        return [], []"),
    "config: unknown keys accepted":
        ("    if unknown:\n        raise ValueError(", "    if False:\n        raise ValueError("),
    "config: an entry without its why accepted":
        ("set(e) != set(ENTRY_KEYS[key])", "not set(e) >= {field}"),
    "config: an invalid regex accepted":
        ('            raise ValueError("%s: secret_paths pattern %r is not a regex (%s)" % (path, pat, e))', "            continue"),
    "config: the project name not checked (../ reaches out of config/guard/)":
        ('    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", name):', "    if False:"),
    "config: other arguments ignored":
        ('    if len(argv) != 2 or argv[0] != "--project":', "    if False:"),
    "config: a refusal of the config lets the call through":
        # Rewritten in forge: the message says what to do instead.
        ('        deny("guard config: %s. Every call is refused until it is fixed; instead of retrying, "\n'
         '             "fix that file in forge or ask the user." % e)', "        return"),
    # Round 9: a directory that holds a store (FORGE_BLOCK and FORGE_ALLOW 17).
    "directory operands: no command reads the directory it is given":
        ("if not hit and cmdname in DIR_READERS:", "if False:"),
    "directory operands: every command reads the directory (over-block)":
        ("if not hit and cmdname in DIR_READERS:", "if not hit and cmdname:"),
    "directory operands: ~/.hindsight/profiles is not a store directory":
        ('    if low == home + "/.hindsight/profiles":', "    if False:"),
    "directory operands: ~/.hindsight is not a store directory":
        ('    if low == home + "/.hindsight":', "    if False:"),
    "directory operands: forge's config/ is not a store directory":
        ('    if low.endswith("/" + _FORGE_BASE + "/config"):', "    if False:"),
    "directory operands: the repository root is a store directory (over-block)":
        ('    if low.endswith("/" + _FORGE_BASE + "/config"):',
         '    if low.endswith("/" + _FORGE_BASE + "/config") or low == PROJECT.lower():'),
    # Round 9: Read refuses a store's renamed copy (FORGE_FILE_CASES 13), which the `$` anchors let through.
    "Read: .npmrc anchored again":
        (r'r"/\.npmrc\b"', r'r"/\.npmrc$"'),
    "Read: ovcli.conf anchored again":
        (r'r"ovcli\.conf", r"/claude-code\.json"', r'r"ovcli\.conf$", r"/claude-code\.json"'),
    "Read: gate.token anchored again":
        (r'r"gate\.token", r"secrets\.(?:json|env)",', r'r"gate\.token$", r"secrets\.(?:json|env)",'),
    "Read: secrets.json and secrets.env anchored again":
        (r'r"secrets\.(?:json|env)",', r'r"secrets\.(?:json|env)$",'),
    "Read: control.token anchored again":
        (r'r"/coding-agent\.json", r"/control\.token",', r'r"/coding-agent\.json", r"/control\.token$",'),
    "Read: .envrc anchored again":
        (r'r"\.envrc\b", r"credentials\.json",', r'r"\.envrc$", r"credentials\.json",'),
    "Read: .pem anchored again":
        (r'r"\.pem\b", r"\.key\b"', r'r"\.pem$", r"\.key\b"'),
    "Read: .key anchored again":
        (r'r"\.pem\b", r"\.key\b"', r'r"\.pem\b", r"\.key$"'),
    "Read: .secrets anchored again":
        (r'r"/\.secrets\b"', r'r"/\.secrets$"'),
    "Read: gh hosts.yml anchored again":
        (r'r"/\.config/gh/hosts\.yml\b"', r'r"/\.config/gh/hosts\.yml$"'),
    "Read: vercel cli auth.json anchored again":
        (r'r"com\.vercel\.cli/auth\.json\b"', r'r"com\.vercel\.cli/auth\.json$"'),
    "Read: .git-credentials anchored again":
        (r'r"/\.git-credentials\b"', r'r"/\.git-credentials$"'),
    "Read: supabase access-token anchored again":
        (r'r"/\.supabase/access-token\b"', r'r"/\.supabase/access-token$"'),
    "Read: vercel auth.json anchored again":
        (r'r"/\.vercel/auth\.json\b"', r'r"/\.vercel/auth\.json$"'),
    "Read: aws credentials anchored again":
        (r'r"/\.aws/credentials\b", r"/\.kube', r'r"/\.aws/credentials$", r"/\.kube'),
    "Read: aws config anchored again":
        (r'r"/\.aws/config\b", r"/id_ecdsa"', r'r"/\.aws/config$", r"/id_ecdsa"'),
    "Read: kube config anchored again":
        (r'r"/\.kube/config\b"', r'r"/\.kube/config$"'),
    "Read: docker config anchored again":
        (r'r"/\.docker/config\.json\b",', r'r"/\.docker/config\.json$",'),
    "Read: a test login's copy anchored again":
        (r'r"credentials[^/]*\.local\b", r"/\.dev-credentials[^/]*$",', r'r"credentials[^/]*\.local$", r"/\.dev-credentials[^/]*$",'),
    # Round 9: `.env_prod` and `.env2` are env files (FORGE_BLOCK and FORGE_ALLOW 19, FORGE_FILE_CASES 14).
    "Bash: .env_prod and .env2 pass again":
        (r'''    r"(?:^|[\s/'\"=])\.env(?=[_\d])(?!(?:[\w-]*[._])?" + ENV_TEMPLATE + r"(?![\w.-]))",''', ""),
    "Bash: .env_example is no template (over-block)":
        (r'''\.env(?=[_\d])(?!(?:[\w-]*[._])?" + ENV_TEMPLATE + r"(?![\w.-]))",''', r'''\.env(?=[_\d])",'''),
    "Bash: `cfg.env_file` in code is an env file (over-block)":
        (r'''r"(?:^|[\s/'\"=])\.env(?=[_\d])''', r'''r"\.env(?=[_\d])'''),
    "Read: .env_prod and .env2 pass again":
        (r'''    r"(?:^|/)\.env(?:[_-](?!(?:[^/]*[._-])?" + ENV_TEMPLATE + r"$)|\d)",''', ""),
    "Read: .env_example is no template (over-block)":
        (r'''(?:^|/)\.env(?:[_-](?!(?:[^/]*[._-])?" + ENV_TEMPLATE + r"$)|\d)''', r'''(?:^|/)\.env(?:[_-]|\d)'''),
    "Read: .env2 passes again":
        (r'''ENV_TEMPLATE + r"$)|\d)",''', r'''ENV_TEMPLATE + r"$))",'''),
    "Read: .env-prod passes again":
        (r'''(?:^|/)\.env(?:[_-](?!''', r'''(?:^|/)\.env(?:[_](?!'''),
    "Read: `src/cfg.env_file.ts` is an env file (over-block)":
        (r'''r"(?:^|/)\.env(?:[_-](?!''', r'''r"\.env(?:[_-](?!'''),
    # Round 9: the glob candidates are lazy and share one budget (FAST_CASES; they run in real
    # subprocesses with a 10 s limit even here, so a mutant that hangs fails fast instead of stalling).
    "glob candidates: no budget (a bare-star glob of six parts hangs)":
        ("for c in counted(glob_candidates(p)))", "for c in glob_candidates(p))"),
    "glob candidates: the same target is asked once per cut (the budget runs out at three stars)":
        ("        if key not in GLOB_SEEN:\n", "        if True:\n"),
    "glob candidates: past the budget the write goes through (fail open)":
        ("    except OverBudget:\n        OVER_BUDGET[0] = True\n        return True\n",
         "    except OverBudget:\n        OVER_BUDGET[0] = True\n        return False\n"),
    "glob candidates: the budget never runs out":
        ("        if BUDGET[0] < 0:\n            raise OverBudget", "        if False:\n            raise OverBudget"),
    "glob candidates: the budget is not renewed for the next call":
        ("    BUDGET[0], OVER_BUDGET[0] = CANDIDATE_BUDGET, False\n", "    pass\n"),
    "glob candidates: a refusal past the budget says it wrote a harness path":
        ("                if OVER_BUDGET[0]:\n", "                if False:\n"),
    # Round 9: brace expansion in a write target (FORGE_BLOCK and FORGE_ALLOW 21, FAST_CASES).
    "braces: a redirect target is not expanded":
        ('for t in brace_words(m.group(1) + (', 'for t in [m.group(1) + ('),
    "braces: the words of a command are not expanded":
        ("for w in brace_words(word)]", "for w in [word]]"),
    "braces: a brace without a comma is a group (over-block)":
        ("            if commas and (best is None or start < best[0]):", "            if best is None or start < best[0]:"),
    "braces: only the first alternative of a group is read":
        ("    for part in parts:\n        yield from brace_expansions", "    for part in parts[:1]:\n        yield from brace_expansions"),
    "braces: an empty alternative is dropped":
        ("    for part in parts:\n        yield from brace_expansions(word[:start] + part",
         "    for part in [p for p in parts if p]:\n        yield from brace_expansions(word[:start] + part"),
    "braces: nested groups are not expanded":
        ("        yield from brace_expansions(word[:start] + part + word[end + 1:])",
         "        yield word[:start] + part + word[end + 1:]"),
    "braces: the alternatives are not counted against the budget":
        ("    return list(counted(brace_expansions(word)))", "    return list(brace_expansions(word))"),
    "braces: a word with a space or a quote is a name too (over-block)":
        ('''    if "{" not in word or "," not in word or re.search(r"[\\s'\\"]", word):''',
         '''    if "{" not in word or "," not in word:'''),
    "braces: a word too long to expand is let through":
        ("    if len(word) > 2000:", "    if False:"),
    # Round 9: a cd inside a group (FORGE_BLOCK and FORGE_ALLOW 20).
    "groups: a subshell's cd is not followed (the group is not opened)":
        ('        if s.startswith("("):\n            opens.append("(")', '        if False:\n            opens.append("(")'),
    "groups: a brace group's cd is not followed (the group is not opened)":
        ('        elif s.startswith("{") and s[1:2].isspace():', "        elif False:"),
    "groups: the group's closing parenthesis stays on its last word":
        ("        if s.endswith(\")\"):\n            s = s[:-1]", "        if False:\n            s = s[:-1]"),
    "groups: a subshell's cd outlives it":
        ('                if kind == "(" and closer == ")":', "                if False:"),
    "groups: a brace group's cd ends with it (over-block)":
        ('                if kind == "(" and closer == ")":', "                if True:"),
    "groups: a group's cd is not undone because the group is not recorded":
        ("        groups += [(kind, base, dict(env)) for kind in opens]\n", ""),
    "groups: a hooksPath set inside a group is not seen":
        ("for w in ungroup(words)]", "for w in words]"),
    "groups: a hooksPath's `)` stays on its value":
        ("    if opened and words:\n        last = words[-1]", "    if False:\n        last = words[-1]"),
    # Round 9: a glob over a store name (FORGE_BLOCK and FORGE_ALLOW 18).
    "store globs: a glob is not matched against the store names":
        ('            if e is not None and GLOB.search(e) and not re.search(r"[$`]", e):', "            if False:"),
    "store globs: any glob that fnmatches a bare store name counts (over-block)":
        ("        if not dirs and pin < GLOB_PIN:", "        if False:"),
    "store globs: a glob must pin more than the names have (under-block)":
        ("GLOB_PIN = 3", "GLOB_PIN = 99"),
    "store globs: forge's names are matched in every project (over-block)":
        ("        dirs = [_FORGE_BASE if d == _FORGE_DIR else d for d in names[:-1]]",
         "        dirs = [d for d in names[:-1] if d != _FORGE_DIR]"),
    "store globs: forge's names never match":
        ("        dirs = [_FORGE_BASE if d == _FORGE_DIR else d for d in names[:-1]]",
         "        dirs = [d for d in names[:-1]]"),
    "store globs: a store's backup is not a store":
        ('or fnmatch.fnmatchcase(name + ".bak", last)', ""),
    "store globs: `*` as a file name is the string, not any name":
        ('        if name != "*" and not (fnmatch', '        if not (fnmatch'),
    "store globs: a glob after a cd is not resolved against the directory it moved to":
        ("store_glob(os.path.normpath(os.path.join(b, e))) for b in bases)", "store_glob(os.path.normpath(os.path.join(PROJECT, e))) for b in bases)"),
    # Round 9b.
    "nested shells: the body is not walked as a command of its own (cd, variables)":
        ("            if _nested_write(part, base, env):\n                return True\n", ""),
    "nested shells: the body starts from the repository, not from the directory the command is in":
        ("        where = _run_dir(base, chdir, env)\n        for a in bodies:\n", "        where = PROJECT\n        for a in bodies:\n"),
    "wrappers: a leading NAME=value is not handed to a nested shell":
        ('            assigns.append(tuple(w.split("=", 1)))\n', "            pass\n"),
    "wrappers: what env sets is not handed to a nested shell":
        ('            elif name == "env" and ASSIGNMENT.match(a):\n                assigns.append(tuple(a.split("=", 1)))\n',
         '            elif name == "env" and ASSIGNMENT.match(a):\n                pass\n'),
    "wrappers: nice, timeout and stdbuf are commands, not wrappers":
        ('"nice": "n", "timeout": "sk", "exec": "a", "stdbuf": "ioe",', '"exec": "a",'),
    "wrappers: xargs is a command, not a wrapper":
        ('    "xargs": "InPdLaEs", ', "    "),
    "wrappers: timeout's duration is read as the command":
        ('        i += 1 if name == "timeout" and i < len(words) else 0', "        i += 0"),
    "wrappers: an option's value is read as the command (env -u NAME)":
        ('"sudo": "ughpCDRTU", "env": "uCS",', '"sudo": "ughpCDRTU", "env": "CS",'),
    "wrappers: env -C and sudo -D do not move the command":
        ('                        if (name, c) in (("env", "C"), ("sudo", "D")):\n                            chdir = value',
         '                        if (name, c) in (("env", "C"), ("sudo", "D")):\n                            pass'),
    "wrappers: env --chdir does not move the command":
        ('                if a.split("=", 1)[0] == "--chdir":\n                    chdir = value', '                if a.split("=", 1)[0] == "--chdir":\n                    pass'),
    "wrappers: env -S is not split into a command":
        ('                            spliced = split_words(value) or []\n                        break', '                            spliced = []\n                        break'),
    "braces in a read: the expanded text is not checked":
        ("            if braced != pcmd:\n", "            if False:\n"),
    "braces in a read: the expanded text is not resolved against a cd":
        ("cd_resolved(braced, SECRET_FILES + secrets).lower()]", "braced.lower()]"),
    "braces in a read: running out of the budget crashes (exit 1 is not a block)":
        ("            except OverBudget:\n                deny(\"this command names more brace", "            except ZeroDivisionError:\n                deny(\"this command names more brace"),
    "braces in a read: the budget is what the write check left":
        ("            BUDGET[0] = CANDIDATE_BUDGET\n            try:\n                braced", "            try:\n                braced"),
    "braces in a read: `${...}` is expanded":
        ('        elif word.startswith("${", i):', "        elif False:"),
    "braces in a read: a quote does not keep a brace from expanding":
        ("        elif c in \"'\\\"\":\n            j = i + 1\n            while j < n and word[j] != c:", "        elif False:\n            j = i + 1\n            while j < n and word[j] != c:"),
    "braces in a read: a backslash does not keep a brace from expanding":
        ('        if c == "\\\\":\n            out.append(_mask(word[i:i + 2]))', '        if False:\n            out.append(_mask(word[i:i + 2]))'),
    "braces in a read: ; & | do not end a word":
        ('WORD_END = " \\t\\r\\n;&|()<>"', 'WORD_END = " \\t\\r\\n()<>"'),
    "ancestors: a directory above a store is not walked":
        ("                if not hit and recursive_reader(cmdname, stage):", "                if False:"),
    "ancestors: any reader of a directory above a store, recursive or not (grep foo ~)":
        ("                if not hit and recursive_reader(cmdname, stage):", "                if not hit and True:"),
    "ancestors: the repository root and `.` there are refused":
        ("a not in (PROJECT, start_cwd) and (f := store_below(a))", "(f := store_below(a))"),
    "ancestors: cp -r is not a recursive reader":
        ('set("rRa") & set(short)) or any(w in ("--recursive", "--archive") for w in words)\n    if cmdname == "rsync"', 'set("") & set(short)) or any(w in ("--recursive", "--archive") for w in words)\n    if cmdname == "rsync"'),
    "ancestors: rsync -a is not a recursive reader":
        ('bool(set("ra") & set(short))', 'bool(set("") & set(short))'),
    "name listings: rg --files reads the files":
        ('"--quiet", "--files")', '"--quiet")'),
    "name listings: tree reads the files":
        ('"file", "rm", "tree"}', '"file", "rm"}'),
    "read cd: a subshell's cd outlives it":
        ('                if kind == "(" and closer == ")":\n                    bases, unsure, env = saved[0]', '                if False:\n                    bases, unsure, env = saved[0]'),
    "read cd: a brace group's cd ends with it":
        ('                if kind == "(" and closer == ")":\n                    bases, unsure, env = saved[0]', '                if closer in ")}":\n                    bases, unsure, env = saved[0]'),
    "read cd: the groups a segment opens are not remembered":
        ("        groups += [(kind, (bases, unsure, dict(env))) for kind in opens]\n", ""),
    "glob prune: every glob is expanded, whatever its literal prefix":
        ("            GLOB_SEEN[key] = glob_reaches_harness(p) and any(", "            GLOB_SEEN[key] = True and any("),
    "glob prune: a part that climbs out with .. does not count":
        ('    if ".." in parts[k:]:\n        return True\n', ""),
    "glob prune: a directory above the harness is pruned":
        ("or r.startswith(low + \"/\") for r in roots)", "for r in roots)"),
    "glob prune: a directory inside the harness is pruned":
        ("return any(low == r or low.startswith(r + \"/\") or r.startswith", "return any(low == r or r.startswith"),
    "glob prune: husky is not a root":
        ('\n             + [os.path.join(PROJECT, ".husky")]]', "]"),
    "glob prune: the literal prefix of an absolute path is the working directory":
        ('"/" if p.startswith("/") else ""', '""'),
    "substitution targets: a command substitution under a harness directory is a write elsewhere":
        (" or substitution_in_harness(t2 or t):", ":"),
    "substitution targets: a redirect target cut at the `(` of a substitution is the whole target":
        ('("(" if m.group(1).endswith("$") and seg[m.end():m.end() + 1] == "(" else "")', '""'),
    "substitution targets: the blanks inside a substitution split the word":
        ("split_words(fuse_substitutions(seg))", "split_words(seg)"),
    "substitution targets: a substitution at the start is judged by no directory":
        ('before[:before.rfind("/") + 1] or "."', 'before[:before.rfind("/") + 1] or ""'),
    "git config: a word after the key that starts with - is an option":
        ("            if after or \"xargs\" in wrappers:", "            if any(not w.startswith(\"-\") for w in after) or \"xargs\" in wrappers:"),
    "git config: a read mode after the key makes the call a read":
        ("            if any(w in GIT_CONFIG_READ for w in before):", "            if any(w in GIT_CONFIG_READ for w in rest):"),
    "git config: xargs does not hand the key a value":
        ('            if after or "xargs" in wrappers:', "            if after:"),
    "git config: only a command named git exactly is git":
        ('if not words or os.path.basename(words[0]) != "git" or "config" not in words:', 'if not words or words[0] != "git" or "config" not in words:'),
    "git commit -n: only a command named git exactly is git":
        ('    if len(words) < 2 or os.path.basename(words[0]) != "git":', '    if len(words) < 2 or words[0] != "git":'),
    "pipe into a shell: core.hooksPath in its input is not looked for":
        ('        if any("hookspath" in before.lower() for before in piped_shell_inputs(seg)):', "        if False:"),
    "pipe into a shell: a harness path in its input is not looked for":
        ("        if any(names_harness(before) for seg in cut for before in piped_shell_inputs(seg)):", "        if False:"),
    "pipe into a shell: sh script.sh reads its input too":
        ('    return (name in STDIN_SHELLS and "-s" in words[1:]) or all(a == "-" or a.startswith("-") for a in words[1:])', "    return True"),
    "pipe into a shell: only a bare sh reads its input (bash -s, sh -e do not)":
        ('    return (name in STDIN_SHELLS and "-s" in words[1:]) or all(a == "-" or a.startswith("-") for a in words[1:])', "    return not words[1:]"),
    "pipe into an interpreter: none is one (printf 'tee .claude/settings.json' | python3 passes)":
        ("    if name not in STDIN_SHELLS and not STDIN_INTERPRETERS.match(name):", "    if name not in STDIN_SHELLS and True:"),
    "pipe into an interpreter: an operand is no program (python3 -m json.tool refused)":
        ('    return (name in STDIN_SHELLS and "-s" in words[1:]) or all(a == "-" or a.startswith("-") for a in words[1:])',
         '    return (name in STDIN_SHELLS and "-s" in words[1:]) or True'),
    "pipe into an interpreter: -s is a shell's switch only (python3 -s script.py refused)":
        ('    return (name in STDIN_SHELLS and "-s" in words[1:]) or all(', '    return ("-s" in words[1:]) or all('),
    "pipe into an interpreter: python with a version (python3.12) is not one":
        ("^(?:python[\\d.]*|perl", "^(?:python3?|perl"),
    "pipe into an interpreter: perl is not one": ("python[\\d.]*|perl|ruby|node|php|lua", "python[\\d.]*|ruby|node|php|lua"),
    "pipe into an interpreter: ruby is not one": ("python[\\d.]*|perl|ruby|node|php|lua", "python[\\d.]*|perl|node|php|lua"),
    "pipe into an interpreter: node is not one": ("python[\\d.]*|perl|ruby|node|php|lua", "python[\\d.]*|perl|ruby|php|lua"),
    "pipe into an interpreter: php is not one": ("python[\\d.]*|perl|ruby|node|php|lua", "python[\\d.]*|perl|ruby|node|lua"),
    "pipe into an interpreter: lua is not one": ("|lua|luajit|", "|luajit|"),
    "pipe into an interpreter: luajit is not one": ("|lua|luajit|", "|lua|"),
    "pipe into an interpreter: tclsh is not one": ("|luajit|tclsh)$", "|luajit)$"),
    "pipe into an awk: awk is not looked at": ('AWKS = ("awk", "gawk", "mawk", "nawk")', 'AWKS = ()'),
    "pipe into an awk: gawk is not one": ('AWKS = ("awk", "gawk", "mawk", "nawk")', 'AWKS = ("awk", "mawk", "nawk")'),
    "pipe into an awk: mawk is not one": ('AWKS = ("awk", "gawk", "mawk", "nawk")', 'AWKS = ("awk", "gawk", "nawk")'),
    "pipe into an awk: nawk is not one": ('AWKS = ("awk", "gawk", "mawk", "nawk")', 'AWKS = ("awk", "gawk", "mawk")'),
    "pipe into an awk: -f - is not a program from stdin": ('in (["-"], ["/dev/stdin"])', 'in (["/dev/stdin"],)'),
    "pipe into an awk: -f /dev/stdin is not a program from stdin": ('in (["-"], ["/dev/stdin"])', 'in (["-"],)'),
    "pipe into an awk: any word before a dash is -f (awk '{print}' - refused)":
        ('any(a == "-f" and args[i + 1:i + 2]', 'any(args[i + 1:i + 2]'),
    "pipe into an awk: system() in the program is not a shell":
        ('AWK_SYSTEM = re.compile(r"\\bsystem\\s*\\(")', 'AWK_SYSTEM = re.compile(r"\\bsystem_\\s*\\(")'),
    "base64 decode: lua, tclsh and an awk that runs its input are not interpreters":
        ('                            and not any(piped_shell_inputs(seg) for seg in segments(low))):',
         '                            ):'),
    "name-only readers: an xargs of a name-only grep is an executor":
        ('rest = [" true " if xargs_names_only(st) else st for st in stages]', "rest = [st for st in stages]"),
    "name-only readers: the long forms are not name-only":
        ("        if a in NAME_ONLY_LONG:\n            return True\n", ""),
    "name-only readers: -C (lowercased -c) with a number is a count":
        ('            if "c" in a and not set(a) & set("lq") and i + 1 < len(args) and args[i + 1].isdigit():\n                continue\n', ""),
    "name-only readers: --json prints lines even with -l":
        ('or "--json" in args:', ":"),
    "name-only readers: any command with -c, -l or -q is name-only":
        ('    if cmd not in ("grep", "egrep", "fgrep", "rg") or', "    if False or"),
    "name-only readers: a -l after other options is not seen":
        ('        if re.match(r"^-[a-z]*[lcq][a-z]*$", a):', '        if i == 0 and re.match(r"^-[a-z]*[lcq][a-z]*$", a):'),
}
# A mutant no realistic command tells apart from the real guard: bash also reads an
# unterminated heredoc to the end, so nothing after it runs either way. The backslash-
# newline join was on this list too, with the reason "it only makes the guard stricter";
# `cat \<newline>ls <secret>` shows it does not, and a case now kills it (break-it, U65).
MAY_SURVIVE = {"prose heredoc stripped without its closing delimiter (bash agrees, may survive)"}


def place(tmp, label, text):
    """Writes text as <tmp>/<label>/hooks/guard_tool_use.py, the layout of a forge checkout:
    the guard finds forge's hooks/ and config/guard/ from its own location, so a mutant
    written anywhere else would fail every case that depends on them and count as killed."""
    d = os.path.join(tmp, label, "hooks")
    os.makedirs(d)
    path = os.path.join(d, "guard_tool_use.py")
    open(path, "w", encoding="utf-8").write(text)
    return path


def run_mutant(item):
    """Writes one mutant and runs the suite against it, stopping at its first failure."""
    i, name, old, new, tmp = item
    return name, suite_fails(place(tmp, "m%03d" % i, SRC.replace(old, new, 1)))


def suite_fails(guard_path):
    """Runs the suite in-process and fail-fast against guard_path; True when it fails. Its
    temp dirs go beside the mutant's dir, never inside the checkout the guard protects, so a
    fail-fast exit leaves nothing the harness does not remove."""
    tmpdir = os.path.dirname(os.path.dirname(guard_path)) + "-tmp"
    os.makedirs(tmpdir)
    r = subprocess.run([sys.executable, TEST], capture_output=True, text=True,
                       env=dict(os.environ, GUARD_UNDER_TEST=guard_path, TMPDIR=tmpdir,
                                GUARD_TEST_FAIL_FAST="1", GUARD_TEST_INPROC="1"))
    return r.returncode != 0


def main():
    tmp = sandbox.mkdtemp("guard-mut-")
    # The in-process mode must pass against the real guard first, in the same layout as the
    # mutants. Otherwise a mode or a location that fails everything would count every mutant
    # as killed.
    if suite_fails(place(tmp, "unmutated", SRC)):
        print("the suite fails against the unmutated guard in the in-process mode; "
              "no mutant result would mean anything")
        sandbox.cleanup(["unmutated"])
        return 1
    survived, missing, work = [], [], []
    for i, (name, (old, new)) in enumerate(MUTANTS.items()):
        if old not in SRC:
            missing.append(name)
        else:
            work.append((i, name, old, new, tmp))
    # Mutants run side by side; each suite stops at its first failing case. Run one
    # after another with the full suite each, this took 377 s on the downstream project's CI runner.
    with ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2)) as pool:
        for name, killed in pool.map(run_mutant, work):
            print("  %s  %s" % ("killed  " if killed else "SURVIVED", name))
            if not killed and name not in MAY_SURVIVE:
                survived.append(name)
    print("mutants: %d, not applied: %d, survived: %d" % (len(MUTANTS), len(missing), len(survived)))
    for n in missing:
        print("  NOT APPLIED (the code it mutates moved): %s" % n)
    failed = not MUTANTS or missing or survived
    sandbox.cleanup(failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
