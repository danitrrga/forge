"""Read and write the Linear issues of this project: fwx linear [--project NAME] {list|comment|label|create|waiting} ...

  list --label L [--json]       the issues of the project with the neutral label L (state with its type, labels, updatedAt)
  waiting [--json]              the issues waiting for the owner, and how many; --json is {"count": N, "issues": [...]}
  comment ISSUE --kind K        stdin is the body; the comment starts with `<!-- fwx:K -->`; a repeat creates nothing
  label ISSUE +L -L ...         add and remove neutral labels (never `factory` or `review` off, never a label that is not ours)
  create --template T           stdin is JSON: one issue {title, context, expected, ...} or a list of them; `factory` is
                                put on every issue, and the keys are the ones lib/fwx/linear.py lists in FIELDS plus
                                `title` and `labels`

The project is `project.linear_project` of .claude/fwx.json; `--project` is needed only without it, and with it must say
the same. The key is `LINEAR_API_KEY` in the environment. `FWX_LINEAR_ENDPOINT` points the client at a fake server and
is accepted only on 127.0.0.1 (the client refuses any other address, so the key never leaves for one).

Exit 0 done, 2 usage or refusal (another project's issue, a label that is not ours, an unknown template, a project not
named), 1 any other failure (Linear unreachable or refusing), 77 no `LINEAR_API_KEY`: `NOT RUN, NOT ARMED`, no request.
"""
import json
import os
import sys

from fwx import config, linear

USAGE = ("usage: fwx linear [--project NAME] list --label L [--json]\n"
         "       fwx linear [--project NAME] waiting [--json]\n"
         "       fwx linear [--project NAME] comment ISSUE --kind K   (body on stdin)\n"
         "       fwx linear [--project NAME] label ISSUE +LABEL -LABEL ...\n"
         "       fwx linear [--project NAME] create --template T      (JSON on stdin: one issue or a list)\n")
KEY = "LINEAR_API_KEY"
ENDPOINT = "FWX_LINEAR_ENDPOINT"
NO_KEY = 77
REFUSED = ("forbidden", "usage", "no_template", "missing_label", "not_found")  # the request cannot be done: exit 2


class Usage(Exception):
    pass


def take_value(args, flag):
    """Remove `flag VALUE` or `flag=VALUE` from args and return the value (None when absent)."""
    for i, a in enumerate(args):
        if a == flag:
            if i + 1 >= len(args):
                raise Usage("%s needs a value" % flag)
            value = args[i + 1]
            del args[i:i + 2]
            return value
        if a.startswith(flag + "="):
            del args[i]
            return a[len(flag) + 1:]
    return None


def take_flag(args, flag):
    if flag in args:
        args.remove(flag)
        return True
    return False


def project_name(cfg, asked):
    """The Linear project: the configured one, which `--project` may only repeat, or `--project` alone when the
    configuration names none."""
    configured = cfg["project"].get("linear_project")
    if configured:
        if asked is not None and asked != configured:
            raise Usage("--project %s is not this project's Linear project (%s): the client is fixed to that one"
                        % (asked, configured))
        return configured
    if not asked:
        raise Usage("no Linear project: name it with --project NAME, or set project.linear_project in .claude/fwx.json")
    return asked


def read_stdin(what):
    text = sys.stdin.read()
    if not text.strip():
        raise Usage("%s: nothing on stdin" % what)
    return text


def line(issue):
    return "%s  %s  [%s]  %s" % (issue["identifier"], issue["state"]["name"], ", ".join(issue["labels"]), issue["title"])


def show(issues, as_json):
    if as_json:
        print(json.dumps(issues, indent=2))
    else:
        for i in issues:
            print(line(i))


def run(client, sub, args):
    if sub == "list":
        label, as_json = take_value(args, "--label"), take_flag(args, "--json")
        if not label or args:
            raise Usage("list needs --label L and takes nothing else")
        show(client.issues(label), as_json)
    elif sub == "waiting":
        as_json = take_flag(args, "--json")
        if args:
            raise Usage("waiting takes only --json")
        issues = client.waiting()
        if as_json:
            print(json.dumps({"count": len(issues), "issues": issues}, indent=2))
        else:
            print("%d waiting" % len(issues))
            show(issues, False)
    elif sub == "comment":
        kind = take_value(args, "--kind")
        if not kind or len(args) != 1:
            raise Usage("comment needs ISSUE and --kind K")
        got = client.comment(args[0], kind, read_stdin("comment"))
        print("%s %s %s" % ("commented" if got["created"] else "already commented", args[0], got["id"]))
    elif sub == "label":
        if not args or any(a[0] not in "+-" or len(a) < 2 for a in args[1:]) or len(args) < 2:
            raise Usage("label needs ISSUE and at least one +LABEL or -LABEL")
        add = [a[1:] for a in args[1:] if a[0] == "+"]
        remove = [a[1:] for a in args[1:] if a[0] == "-"]
        got = client.label(args[0], add, remove)
        print("%s: added %s, removed %s" % (args[0], ", ".join(got["added"]) or "none", ", ".join(got["removed"]) or "none"))
    elif sub == "create":
        template = take_value(args, "--template")
        if not template or args:
            raise Usage("create needs --template T and takes nothing else")
        try:
            items = json.loads(read_stdin("create"))
        except ValueError as e:
            raise Usage("create: stdin is not JSON (%s): one issue as an object, or a list of them" % e)
        items = [items] if isinstance(items, dict) else items
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise Usage("create: stdin is an issue (an object) or a list of issues")
        for i in items:  # every issue enters the factory: the label needs no flag
            labels = i.get("labels") or []
            i["labels"] = labels if not isinstance(labels, list) or "factory" in labels else ["factory"] + labels
        for got in client.create(template, items):
            print("%s  %s  %s" % (got["identifier"], got["url"], "created" if got["created"] else "already there"))
    else:
        raise Usage("unknown subcommand %r" % sub)


def main(argv):
    args = list(argv)
    try:
        asked = take_value(args, "--project")
        if not args:
            sys.stderr.write(USAGE)
            return 2
        if args[0] in ("-h", "--help", "help"):
            sys.stdout.write(USAGE)
            return 0
        sub = args.pop(0)
        if sub not in ("list", "waiting", "comment", "label", "create"):
            raise Usage("unknown subcommand %r" % sub)
        try:
            cfg = config.load()
        except config.ConfigError as e:
            sys.stderr.write("fwx linear: %s\n" % e)
            return 2
        project = project_name(cfg, asked)
        key = os.environ.get(KEY)
        if not key:
            sys.stderr.write("NOT RUN, NOT ARMED: no %s\n  forge puts it in the environment of a project with the framework; "
                             "without forge, export your own personal API key as %s. Nothing was sent.\n" % (KEY, KEY))
            return NO_KEY
        client = linear.Client(key, project, cfg, endpoint=os.environ.get(ENDPOINT) or linear.ENDPOINT)
        run(client, sub, args)
    except Usage as e:
        sys.stderr.write("fwx linear: %s\n%s" % (e, USAGE))
        return 2
    except linear.LinearError as e:
        sys.stderr.write("fwx linear: %s\n" % e)
        for done in getattr(e, "created", []):  # a create that stopped part way says what it already made
            print("%s  %s  %s" % (done["identifier"], done["url"], "created" if done["created"] else "already there"))
        return 2 if e.code in REFUSED else 1
    return 0
