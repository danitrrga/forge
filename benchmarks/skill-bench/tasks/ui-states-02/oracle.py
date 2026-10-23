"""Oracle for ui-states-02 (authored). Drives the panel through its public glue, inbox.panel.Panel(fetch, paint), with
scripted fetch functions, and reads the HTML painted while a fetch is in flight and after it ends: first open with
items, with an empty list and with a failure; a retry that succeeds after a failure; a refresh that fails after a
success; and the paint during a refresh. Loading must never read as "all caught up", a failure must show an error
(and no spinner), a successful retry must clear the error, and an empty list must still say "all caught up". The repo's
own tests must still pass. It does not depend on the shape of the state, so any reducer and render design passes.

States are recognised in the HTML: loading by aria-busy="true", role="status"/"progressbar", <progress>, a
loading/spinner/skeleton class, or words like "loading", "checking", "fetching"; an error by role="alert" or words like "couldn't", "unable",
"failed", "error", "unavailable", "try again"; caught-up by the existing "all caught up" wording; the list by the item
texts. What it cannot see: how it looks or animates, focus and screen-reader announcements beyond those attributes,
timing, and wording outside those lists (an error message using none of the words and no role="alert" is missed).
"""
import html
import os
import re
import subprocess
import sys
import traceback

ITEMS = [{"id": "n7", "text": "Ana assigned ticket #388 to you", "when": "just now"},
         {"id": "n6", "text": "Ben replied to ticket #412", "when": "5 min ago"}]
LOADING_WORDS = re.compile(r"\bloading\b|\bfetching\b|\bchecking\b|\bupdating\b|\brefreshing\b|please wait|\bsyncing\b", re.I)
ERROR_WORDS = re.compile(r"couldn.?t|could not|can.?t|cannot|unable|fail|error|problem|went wrong|unavailable|"
                         r"not available|try again|retry", re.I)


def _states(markup):
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).replace("’", "'").strip()
    found = set()
    if (re.search(r"""aria-busy\s*=\s*["']?true""", markup, re.I)
            or re.search(r"""role\s*=\s*["']?(status|progressbar)""", markup, re.I)
            or re.search(r"""class\s*=\s*["'][^"']*(loading|spinner|skeleton|busy)""", markup, re.I)
            or re.search(r"<progress\b", markup, re.I)
            or LOADING_WORDS.search(text)):
        found.add("loading")
    if re.search(r"""role\s*=\s*["']?alert""", markup, re.I) or ERROR_WORDS.search(text):
        found.add("error")
    if re.search(r"all caught up", text, re.I):
        found.add("caught-up")
    if all(i["text"] in text for i in ITEMS):
        found.add("list")
    return found, text


class _Run:
    """Opens a Panel once per scripted answer; records the paints made while each fetch is in flight and after."""

    def __init__(self, Panel, answers):
        self.paints, self.during, self.after = [], [], []
        self.answers = list(answers)
        panel = Panel(self._fetch, self.paints.append)
        for _ in answers:
            start = len(self.paints)
            panel.open()
            self.after.append(self.paints[-1] if len(self.paints) > start else None)

    def _fetch(self):
        self.during.append(list(self.paints[-1:]))
        answer = self.answers.pop(0)
        if answer == "fail":
            raise ConnectionError("notifications service down")
        return [dict(i) for i in answer]


def _show(markup):
    if markup is None:
        return "nothing painted"
    st, text = _states(markup)
    return "%s: %s" % (sorted(st) or "no recognisable state", text[:90])


def check(repo, message):
    sys.path.insert(0, repo)
    try:
        from inbox.panel import Panel
    except Exception as e:  # noqa: BLE001
        return [{"id": "imports", "passed": False, "evidence": "inbox.panel does not import: %r" % e}]
    out = []

    def run(answers):
        try:
            return _Run(Panel, answers), None
        except Exception as e:  # noqa: BLE001
            return None, "the panel raised %s: %s" % (type(e).__name__, e)

    def add(cid, ok, evidence):
        out.append({"id": cid, "passed": bool(ok), "evidence": evidence})

    r, err = run([[]])
    loading = r.during[0][0] if r and r.during and r.during[0] else None
    st = _states(loading)[0] if loading else set()
    add("loading-is-not-caught-up", not err and "loading" in st and not st & {"caught-up", "error"},
        err or "painted while the first fetch runs: %s" % _show(loading))
    st = _states(r.after[0])[0] if r and r.after[0] else set()
    add("empty-list-is-caught-up", not err and st == {"caught-up"},
        err or "after an empty answer: %s" % _show(r.after[0]))

    r, err = run([ITEMS])
    st = _states(r.after[0])[0] if r and r.after[0] else set()
    add("items-listed", not err and st == {"list"}, err or "after items arrive: %s" % _show(r.after[0]))

    r, err = run(["fail"])
    st = _states(r.after[0])[0] if r and r.after[0] else set()
    add("failure-is-an-error", not err and "error" in st and not st & {"caught-up", "loading"},
        err or "after the fetch fails: %s" % _show(r.after[0]))

    r, err = run(["fail", ITEMS])
    retry_loading = r.during[1][0] if r and len(r.during) > 1 and r.during[1] else None
    st_l = _states(retry_loading)[0] if retry_loading else set()
    st = _states(r.after[1])[0] if r and r.after[1] else set()
    add("retry-shows-loading", not err and "loading" in st_l and "caught-up" not in st_l,
        err or "painted while the retry runs: %s" % _show(retry_loading))
    add("successful-retry-clears-error", not err and st == {"list"},
        err or "after the retry succeeds: %s" % _show(r.after[1]))

    r, err = run([ITEMS, "fail"])
    st = _states(r.after[1])[0] if r and r.after[1] else set()
    add("failed-refresh-is-an-error", not err and "error" in st and not st & {"caught-up", "loading"},
        err or "after a refresh fails: %s" % _show(r.after[1]))

    r, err = run([ITEMS, ITEMS])
    mid = r.during[1][0] if r and len(r.during) > 1 and r.during[1] else None
    st = _states(mid)[0] if mid else set()
    add("refresh-is-not-caught-up", not err and mid is not None and "caught-up" not in st and "error" not in st,
        err or "painted while a refresh runs: %s" % _show(mid))

    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-t", "."], cwd=repo, capture_output=True,
                           text=True, timeout=40, env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")})
        tail = (p.stderr.strip().splitlines() or ["no output"])[-1]
        ran = re.search(r"Ran (\d+) test", p.stderr)
        add("repo-tests-pass", p.returncode == 0 and ran and int(ran.group(1)) > 0,
            "python3 -m unittest: %s (%s)" % (tail, ran.group(0) if ran else "no tests ran"))
    except subprocess.TimeoutExpired:
        add("repo-tests-pass", False, "the test run timed out")
    except Exception:  # noqa: BLE001
        add("repo-tests-pass", False, traceback.format_exc(limit=1))
    return out
