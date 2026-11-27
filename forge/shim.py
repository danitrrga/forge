"""`forge shim`: a shell function named `claude`, so that `claude @NAME` starts the session profile NAME of this directory's
project (`forge start @NAME ...`) and every other `claude` is the real one. `forge shim --check @NAME` is the probe the function
calls.

It is a function and not an executable: it exists only in an interactive shell, so a script, or another program's `claude -p`,
never meets it. Two rules fix what it does (in the data history: framework-discuss/research/profile-daily-measures.md):

- `claude @notes.md` is a prompt today (the binary reads `@name` as a file mention), so a first argument starting with `@` is
  taken for a profile only when the probe says the project offers it (or that it is its default label); otherwise everything goes
  to the real `claude`, untouched.
- The probe costs about 33 ms, 80 % of it the import of forge/cli.py, so a `claude` whose first argument does not start with `@`
  never calls forge. A plain `claude` in a project with profiles starts the default as it always did.

Nothing here writes a file: the user puts the output where their shell reads it (README.md, Commands)."""
import contextlib
import os
import sys

SHELLS = ("fish", "zsh", "bash")

_POSIX = """# forge shim: `claude @NAME` starts the profile NAME of this directory's project (forge start @NAME); any other claude is the real one.
# Remove this function and `claude` is the binary again.
claude() {
    case "$1" in
        @?*) forge shim --check "$1" 2>/dev/null && { forge start "$@"; return; } ;;
    esac
    command claude "$@"
}
"""

_FISH = """# forge shim: `claude @NAME` starts the profile NAME of this directory's project (forge start @NAME); any other claude is the real one.
# Remove this function and `claude` is the binary again.
function claude
    if string match -qr -- '^@.' -- "$argv[1]"
        and forge shim --check "$argv[1]" 2>/dev/null
        forge start $argv
        return
    end
    command claude $argv
end
"""

FUNCTIONS = {"fish": _FISH, "zsh": _POSIX, "bash": _POSIX}


def offered(cwd):
    """The profile names `claude @NAME` may take in `cwd`: the default label and every offered one, or [] when the directory's
    project declares no `profiles` (or is frozen, which receives none)."""
    from forge import profiles  # only when a probe runs: `forge shim --shell` needs none of it
    found = profiles.project_here(cwd)
    if not found:
        return []
    given = found[1].get("profiles")
    if not isinstance(given, dict) or found[1].get("frozen"):
        return []
    return [given["default"]] + list(given["offered"])


def is_profile(arg, cwd):
    """Whether `arg` (`@NAME`) names a profile of the project of `cwd`. Every doubt is False: a registry forge cannot read, a folder
    that is no project, a bare `@`. False hands the arguments to the real claude, which is what the user had before the shim."""
    from forge import profiles
    try:
        name = profiles.parse_at(arg)
    except ValueError:
        return False
    if not name:
        return False
    try:
        with open(os.devnull, "w") as null, contextlib.redirect_stdout(null), contextlib.redirect_stderr(null):
            return name in offered(cwd)
    except (Exception, SystemExit):  # lib exits with a message on a registry it cannot read; the probe prints nothing
        return False


def shell_from_env(env):
    """The shell `$SHELL` names (its file name), or None when it is not one of SHELLS."""
    name = os.path.basename(env.get("SHELL", ""))
    return name if name in SHELLS else None


def cmd(a):
    """forge shim --check @NAME: exit 0 it is a profile of this directory's project, 1 it is not, no output. forge shim [--shell S]:
    print the function (S from $SHELL when not given, said on stderr); exit 2 when S is none of SHELLS."""
    if a.check is not None:
        return 0 if is_profile(a.check, os.getcwd()) else 1
    shell = a.shell
    if shell is None:
        shell = shell_from_env(os.environ)
        if shell is None:
            print("forge shim: $SHELL is %r, which is none of %s: say --shell %s" % (os.environ.get("SHELL", ""), ", ".join(SHELLS),
                  "|".join(SHELLS)), file=sys.stderr)
            return 2
        print("forge shim: the %s function (from $SHELL, %s)" % (shell, os.environ["SHELL"]), file=sys.stderr)
    sys.stdout.write(FUNCTIONS[shell])
    return 0
