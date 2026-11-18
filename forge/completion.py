"""`forge completion fish|zsh|bash`: the script that completes `forge` (and the first argument of the shim's `claude`) in a shell.

The commands, their flags and the choices of a flag are read from the parser (cli.build_parser), so a new flag completes without
touching this file. Names that change are asked of `forge` at every tab, never stored in the script:

    forge list --names        the projects                        (forge config, list, sync, doctor, metrics, log, uninstall)
    forge list @ --names      this directory's profiles, after @  (forge start, switch, run, list, config; and `claude @`)
    forge config --names      the values of --on and --off        (skill:NAME, set:NAME, server:NAME, option:NAME)

A call costs about 30 ms (the import of forge.cli), and its errors are dropped: outside a project there is simply nothing to offer.
`claude` is completed only for a first argument that starts with `@`; every other word goes to whatever completed `claude` before
(fish: nothing of ours applies; bash and zsh: the function that was registered, or the shell's default).

Nothing here writes a file: the script goes to stdout and the owner puts it where the shell reads it (`forge completion --help`)."""
import argparse
import sys

SHELLS = ("fish", "zsh", "bash")
PROJECT_COMMANDS = ("sync", "doctor", "metrics", "log", "uninstall", "list", "config")  # their argument is a project's name
PROFILE_COMMANDS = ("start", "switch", "run", "list", "config")  # an argument that starts with @ is a profile of this directory's project
FIRST_PROFILE = ("start", "switch", "run")  # their first argument is a profile: offered without typing the @
VALUE_FLAGS = {"config": ("--on", "--off")}  # their values are `forge config --names`


def collect(parser):
    """({command: help}, {command: [(option string, takes a value, choices or None, help)]}, {command: choices of its positional})
    of every subcommand of `parser`. Looking at no command is a mistake, not an empty script."""
    subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {c.dest: c.help or "" for c in subs._choices_actions}
    flags, positional = {}, {}
    for name, sp in subs.choices.items():
        rows = []
        for act in sp._actions:
            if act.option_strings and act.dest != "help":
                text = (act.help or "").replace("%(default)s", str(act.default)).replace("%%", "%")
                for opt in act.option_strings:
                    rows.append((opt, act.nargs != 0, list(act.choices) if act.choices else None, text))
            elif not act.option_strings and act.choices and not isinstance(act, argparse._SubParsersAction):
                positional[name] = list(act.choices)
        flags[name] = rows
    if not helps:
        raise SystemExit("forge completion: the parser has no subcommands to complete")
    return helps, flags, positional


def short(text, width=70):
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 3].rstrip() + "..."


def quote(text):
    """One single-quoted word for fish."""
    return "'%s'" % text.replace("\\", "\\\\").replace("'", "\\'")


def fish(parser):
    helps, flags, positional = collect(parser)
    out = ["# forge completion for fish, printed by `forge completion fish`. Put it in ~/.config/fish/conf.d/ (not completions/): the",
           "# completion of `claude @` must exist before anyone completes `forge`. Commands and flags come from the parser; names are",
           "# asked of forge at every tab (forge list --names, forge list @ --names, forge config --names).",
           "complete -c forge -e",
           "function __forge_sub_is",
           "    set -l t (commandline -opc)",
           "    test (count $t) -ge 2; and contains -- $t[2] $argv",
           "end",
           "function __forge_at",
           "    set -l c (commandline -ct)",
           "    string match -q -- '@*' \"$c\"",
           "end",
           "function __forge_first_argument",
           "    test (count (commandline -opc)) -eq 2",
           "end",
           "function __forge_projects",
           "    forge list --names 2>/dev/null",
           "end",
           "function __forge_profiles",
           "    forge list @ --names 2>/dev/null | string replace -r '^' '@'",
           "end",
           "function __forge_values",
           "    forge config --names 2>/dev/null",
           "end",
           "function __forge_claude_at",
           "    test (count (commandline -opc)) -eq 1; and __forge_at",
           "end",
           ""]
    for name, text in helps.items():
        out.append("complete -c forge -f -n 'test (count (commandline -opc)) -eq 1' -a %s -d %s" % (name, quote(short(text))))
    for name, rows in flags.items():
        for opt, takes, choices, text in rows:
            line = "complete -c forge -n '__forge_sub_is %s' %s %s" % (
                name, "-s " + opt[1:] if len(opt) == 2 else "-l " + opt[2:], "-d " + quote(short(text)))
            if opt in VALUE_FLAGS.get(name, ()):
                line += " -x -a '(__forge_values)'"
            elif choices:
                line += " -x -a %s" % quote(" ".join(choices))
            elif takes:
                line += " -r"
            out.append(line)
    for name, choices in positional.items():
        out.append("complete -c forge -f -n '__forge_sub_is %s' -a %s" % (name, quote(" ".join(choices))))
    out += ["complete -c forge -f -n '__forge_sub_is %s; and not __forge_at' -a '(__forge_projects)'" % " ".join(PROJECT_COMMANDS),
            "complete -c forge -f -n '__forge_sub_is %s; and __forge_at' -a '(__forge_profiles)'" % " ".join(PROFILE_COMMANDS),
            "complete -c forge -f -n '__forge_sub_is %s; and __forge_first_argument' -a '(__forge_profiles)'" % " ".join(FIRST_PROFILE),
            "complete -c claude -f -n '__forge_claude_at' -a '(__forge_profiles)'"]
    return "\n".join(out) + "\n"


def _tables(helps, flags, positional):
    """(the flags per command, the (command, flag) -> choices per flag) as shell words."""
    per_command = {n: [opt for opt, *_ in rows] for n, rows in flags.items()}
    choices = {(n, opt): ch for n, rows in flags.items() for opt, takes, ch, _ in rows if ch and opt not in VALUE_FLAGS.get(n, ())}
    return per_command, choices


def fill(template, values):
    """The template with each @@key@@ replaced (shell code is full of % and braces, so no % or format here)."""
    for key, value in values.items():
        template = template.replace("@@%s@@" % key, value)
    return template


def bash(parser):
    helps, flags, positional = collect(parser)
    per_command, choices = _tables(helps, flags, positional)
    arms = "".join('            "%s %s") cands=(%s) ;;\n' % (n, opt, " ".join(ch)) for (n, opt), ch in choices.items())
    arms += "".join('            "%s %s") _forge_lines "" config --names ;;\n' % (n, f) for n, fs in VALUE_FLAGS.items() for f in fs)
    positionals = "".join('                        %s) cands=(%s) ;;\n' % (n, " ".join(ch)) for n, ch in positional.items())
    return fill('''# forge completion for bash, printed by `forge completion bash`. Source it from ~/.bashrc. Commands and flags come from the parser; names are
# asked of forge at every tab (forge list --names, forge list @ --names, forge config --names).

# _forge_lines PREFIX ARGS...: `forge ARGS` one name per line, each with PREFIX, into cands (an error is dropped)
_forge_lines() {
    local prefix=$1 l
    shift
    while IFS= read -r l; do cands+=("$prefix$l"); done < <(forge "$@" 2>/dev/null)
}

_forge_complete() {
    local cur=${COMP_WORDS[COMP_CWORD]} sub prev j=$COMP_CWORD colon="" w
    local -a cands=()
    # bash splits TYPE:NAME at the colon: put the word back together and give back only what follows the colon
    while (( j > 1 )) && [[ ${COMP_WORDS[j]} == : || ${COMP_WORDS[j-1]} == : ]]; do (( j-- )); done
    if (( j < COMP_CWORD )); then
        cur=""
        for (( w = j; w <= COMP_CWORD; w++ )); do cur+=${COMP_WORDS[w]}; done
    fi
    [[ $cur == *:* ]] && colon=${cur%"${cur##*:}"}
    sub=${COMP_WORDS[1]}
    prev=${COMP_WORDS[j-1]}
    if (( COMP_CWORD == 1 )); then
        cands=(@@commands@@)
    elif [[ $cur == -* ]]; then
        case $sub in
@@flags@@        esac
    else
        case "$sub $prev" in
@@arms@@            *)
                if [[ $cur == @* ]]; then
                    case $sub in
                        @@profile@@) _forge_lines @ list @ --names ;;
                    esac
                else
                    case $sub in
@@positionals@@                        @@project@@) _forge_lines "" list --names ;;
                    esac
                    case $sub in
                        @@first@@) (( COMP_CWORD == 2 )) && _forge_lines @ list @ --names ;;
                    esac
                fi ;;
        esac
    fi
    COMPREPLY=()
    for w in "${cands[@]}"; do
        [[ $w == "$cur"* ]] && COMPREPLY+=("${w#"$colon"}")
    done
}
complete -o default -F _forge_complete forge

# `claude @NAME`: the profiles of this directory's project after a first argument that starts with @; every other word goes to what
# completed claude before this file was sourced (readline's file completion when nothing did)
if [[ -z ${_forge_claude_orig+x} ]]; then
    _forge_claude_orig="" _forge_claude_opts=()
    if _forge_spec=$(complete -p claude 2>/dev/null); then
        _forge_prev=""
        for _forge_w in $_forge_spec; do
            [[ $_forge_prev == -F ]] && _forge_claude_orig=$_forge_w
            [[ $_forge_prev == -o ]] && _forge_claude_opts+=(-o "$_forge_w")
            _forge_prev=$_forge_w
        done
    fi
fi
_forge_claude_complete() {
    local cur=${COMP_WORDS[COMP_CWORD]} cands=() l
    COMPREPLY=()
    if (( COMP_CWORD == 1 )) && [[ $cur == @* ]]; then
        while IFS= read -r l; do [[ @$l == "$cur"* ]] && COMPREPLY+=("@$l"); done < <(forge list @ --names 2>/dev/null)
    fi
    if (( ${#COMPREPLY[@]} == 0 )) && [[ -n $_forge_claude_orig ]]; then
        "$_forge_claude_orig" "$@"
    fi
}
if [[ -n $_forge_claude_orig ]]; then
    complete "${_forge_claude_opts[@]}" -F _forge_claude_complete claude
else
    complete -o default -F _forge_claude_complete claude
fi
''', {"commands": " ".join(helps),
       "flags": "".join('            %s) cands=(%s) ;;\n' % (n, " ".join(fs)) for n, fs in per_command.items() if fs),
       "arms": arms, "positionals": positionals, "profile": "|".join(PROFILE_COMMANDS), "project": "|".join(PROJECT_COMMANDS),
       "first": "|".join(FIRST_PROFILE)})


def zsh(parser):
    helps, flags, positional = collect(parser)
    per_command, choices = _tables(helps, flags, positional)
    arms = "".join('        "%s %s") cands=(%s) ;;\n' % (n, opt, " ".join(ch)) for (n, opt), ch in choices.items())
    arms += "".join('        "%s %s") cands=(${(f)"$(forge config --names 2>/dev/null)"}) ;;\n' % (n, f) for n, fs in VALUE_FLAGS.items() for f in fs)
    positionals = "".join('                    %s) cands=(%s) ;;\n' % (n, " ".join(ch)) for n, ch in positional.items())
    return fill('''# forge completion for zsh, printed by `forge completion zsh`. Source it after compinit (from ~/.zshrc). Commands and flags come from the
# parser; names are asked of forge at every tab (forge list --names, forge list @ --names, forge config --names).

# _forge_profiles: this directory's profiles with their @, into cands
_forge_profiles() {
    cands=(${(f)"$(forge list @ --names 2>/dev/null)"})
    (( $#cands )) && cands=(@${^cands})
}

_forge() {
    local cur=$words[CURRENT] sub=$words[2] prev=$words[CURRENT-1]
    local -a cands
    if (( CURRENT == 2 )); then
        cands=(@@commands@@)
    elif [[ $cur == -* ]]; then
        case $sub in
@@flags@@        esac
    else
        case "$sub $prev" in
@@arms@@        *)
            if [[ $cur == @* ]]; then
                case $sub in
                    @@profile@@) _forge_profiles ;;
                esac
            else
                case $sub in
@@positionals@@                    @@project@@) cands=(${(f)"$(forge list --names 2>/dev/null)"}) ;;
                esac
                case $sub in
                    @@first@@) (( CURRENT == 3 )) && _forge_profiles ;;
                esac
            fi ;;
        esac
    fi
    compadd -- ${(M)cands:#"${cur}"*}
    (( $#cands )) || { [[ $sub == (new|commit|lint) ]] && (( $+functions[_files] )) && _files }
}

# `claude @NAME`: the profiles of this directory's project after a first argument that starts with @; every other word goes to what
# completed claude before this file was sourced (zsh's default when nothing did)
if [[ -z ${_forge_claude_orig+x} ]]; then
    typeset -g _forge_claude_orig=${_comps[claude]-}
fi
_forge_claude() {
    local cur=$words[CURRENT]
    local -a cands
    if (( CURRENT == 2 )) && [[ $cur == @* ]]; then
        _forge_profiles
        if (( $#cands )); then
            compadd -- ${(M)cands:#"${cur}"*}
            return 0
        fi
    fi
    if [[ -n $_forge_claude_orig ]]; then
        $_forge_claude_orig "$@"
    elif (( $+functions[_default] )); then
        _default "$@"
    fi
}
if (( $+functions[compdef] )); then
    compdef _forge forge
    compdef _forge_claude claude
fi
''', {"commands": " ".join(helps),
       "flags": "".join('            %s) cands=(%s) ;;\n' % (n, " ".join(fs)) for n, fs in per_command.items() if fs),
       "arms": arms, "positionals": positionals, "profile": "|".join(PROFILE_COMMANDS), "project": "|".join(PROJECT_COMMANDS),
       "first": "|".join(FIRST_PROFILE)})


PRINT = {"fish": fish, "zsh": zsh, "bash": bash}


def cmd(a, parser):
    """forge completion SHELL: the script on stdout."""
    sys.stdout.write(PRINT[a.shell](parser))
    return 0
