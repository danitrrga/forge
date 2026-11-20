"""The account-scoped MCP servers `forge new --account-server SERVICE[=PIN]` gives a project.

An OAuth MCP server that logs in to one account or organisation must not be shared: the login token is keyed by the server's name and
URL, so with one registry entry for every project the last login wins everywhere. Each project gets its own `<service>-<project>`
entry instead. `pinned` is the documented URL that fixes the entry to one project on the service's side (PostHog and Supabase withhold
their switch tools, Neon fixes the grant to that project, Vercel scopes the session to it), or None where the service has none.
A service is listed here only when its authorization server advertises dynamic client registration, so Claude Code can register itself
at the first /mcp; add one after a login has succeeded."""
import datetime

SERVICES = {
    "posthog": {"url": "https://mcp.posthog.com/mcp", "pinned": "https://mcp.posthog.com/mcp?project_id={pin}"},
    "supabase": {"url": "https://mcp.supabase.com/mcp", "pinned": "https://mcp.supabase.com/mcp?project_ref={pin}"},
    "vercel": {"url": "https://mcp.vercel.com", "pinned": "https://mcp.vercel.com/{pin}"},  # pin = <team slug>/<project slug>
    "neon": {"url": "https://mcp.neon.tech/mcp", "pinned": "https://mcp.neon.tech/mcp?projectId={pin}"},
    "notion": {"url": "https://mcp.notion.com/mcp", "pinned": None},
    "linear": {"url": "https://mcp.linear.app/mcp", "pinned": None},
    "figma": {"url": "https://mcp.figma.com/mcp", "pinned": None},
    "canva": {"url": "https://mcp.canva.com/mcp", "pinned": None},
    "atlassian": {"url": "https://mcp.atlassian.com/v2/mcp", "pinned": None},
    "intercom": {"url": "https://mcp.intercom.com/mcp", "pinned": None},
}


def entry(spec, project):
    """(registry name, registry entry, unpinned) of `spec` (`posthog=286015`, or `notion`) for `project`. `unpinned`: the service has a
    pin form and none was given, so the pin has to be added before the first login. ValueError, with one line, for an unknown service
    or a pin the service cannot take."""
    service, _, pin = spec.partition("=")
    tpl = SERVICES.get(service)
    if tpl is None:
        raise ValueError("--account-server: unknown service %r (known: %s)" % (service, ", ".join(sorted(SERVICES))))
    if pin and not tpl["pinned"]:
        raise ValueError("--account-server: %s has no project pin; pass it bare" % service)
    url = tpl["pinned"].format(pin=pin) if pin else tpl["url"]
    doc = ("%s for %s only, created by forge new on %s. One entry per project so its OAuth token is its own; authorise it with /mcp "
           "from the browser profile of the account that owns it. The URL is part of the token key: changing it means a new login."
           % (service, project, datetime.date.today().isoformat()))
    return "%s-%s" % (service, project), {"_doc": doc, "type": "http", "url": url}, bool(tpl["pinned"]) and not pin


def plan(specs, project, registry):
    """([registry names, in the order given], {name: entry} still to add, [names that are UNPINNED]) for `specs`, against the registry's
    `servers` object. An entry the registry already has with the same URL is used as it is; with another URL it is a login that a new URL
    would replace, so ValueError (edit it by hand). The same service twice is one entry."""
    names, new, unpinned = [], {}, []
    for spec in specs:
        name, row, bare = entry(spec, project)
        current = registry.get(name)
        if current is None and name in new and new[name]["url"] != row["url"]:
            raise ValueError("--account-server: %s is given twice with two URLs" % name)
        if current is not None and current.get("url") != row["url"]:
            raise ValueError("--account-server: the registry already has %s with url %s; edit it by hand rather than let forge new "
                             "replace a login" % (name, current.get("url")))
        if current is None:
            new[name] = row
            if bare:
                unpinned.append(name)
        if name not in names:
            names.append(name)
    return names, new, unpinned
