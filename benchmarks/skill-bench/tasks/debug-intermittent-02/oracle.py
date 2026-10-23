"""Oracle for debug-intermittent-02: the dashboard's JSONDecodeError is a reader catching a half-written file.

save_rates() opens rates.json with "w", which truncates it before the new JSON is written, so a reader that
lands in that window reads "" or a fragment. A retry or a fallback in load_rates() only shrinks the window.
The oracle makes the race deterministic: it wraps every file opened for writing (open, io.open, os.open,
os.write) and, at each step of a save, runs load_rates() on the target from another thread. Every such
read must return the old or the new rates at once. It also checks that a genuinely corrupt file still
raises, that no temp file is left, and that any temp file sits beside the target (os.replace is atomic only
within one filesystem)."""
import json
import os
import subprocess
import sys

PROBE = r'''
import builtins, io, json, os, sys, tempfile, threading
repo, tmp = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo)
from rates import store

target = os.path.join(tmp, "rates.json")
OLD, NEW = {"USD": 1.08, "GBP": 0.85}, {"USD": 1.09, "GBP": 0.86, "JPY": 162.5}
store.save_rates(target, OLD)
assert store.load_rates(target) == OLD, "round trip of the first save failed"

probes, problems, write_dirs = [], [], set()
real_open, real_os_open, real_os_write = io.open, os.open, os.write
busy = []  # set while a probe runs, so the reader's own opens are not probed in turn

def probe(where):
    if busy:
        return
    busy.append(1)
    try:
        box = {}
        def read():
            try:
                box["v"] = store.load_rates(target)
            except BaseException as e:
                box["e"] = "%s: %s" % (type(e).__name__, e)
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(2)
        probes.append(where)
        if t.is_alive():
            problems.append("%s: the reader waited more than 2 s" % where)
        elif "e" in box:
            problems.append("%s: the reader got %s" % (where, box["e"]))
        elif box["v"] not in (OLD, NEW):
            problems.append("%s: the reader got %r" % (where, box["v"]))
    finally:
        busy.clear()

def real_path(fd, fallback):
    try:
        return os.path.realpath(os.readlink("/proc/self/fd/%d" % fd))
    except OSError:
        return os.path.realpath(str(fallback))

class Watched:
    def __init__(self, f, label):
        self._f, self._label, self._wrote = f, label, False
    def write(self, data):
        n = self._f.write(data)
        if not self._wrote:
            self._wrote = True
            self._f.flush()
            probe("after the first write to " + self._label)
        return n
    def writelines(self, lines):
        for line in lines:
            self.write(line)
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return self._f.__exit__(*exc)
    def __iter__(self):
        return iter(self._f)
    def __getattr__(self, name):
        return getattr(self._f, name)

def watched_open(file, mode="r", *a, **k):
    f = real_open(file, mode, *a, **k)
    if any(c in mode for c in "wax+"):
        p = real_path(f.fileno(), file)
        write_dirs.add(os.path.dirname(p))
        label = os.path.basename(p)
        probe("after open(%r, %r)" % (label, mode))
        return Watched(f, label)
    return f

def watched_os_open(p, flags, *a, **k):
    fd = real_os_open(p, flags, *a, **k)
    if flags & (os.O_WRONLY | os.O_RDWR):
        rp = real_path(fd, p)
        write_dirs.add(os.path.dirname(rp))
        probe("after os.open(%r)" % os.path.basename(rp))
    return fd

def watched_os_write(fd, data):
    n = real_os_write(fd, data)
    probe("after os.write")
    return n

builtins.open = io.open = watched_open
os.open, os.write = watched_os_open, watched_os_write
try:
    store.save_rates(target, NEW)
finally:
    builtins.open = io.open = real_open
    os.open, os.write = real_os_open, real_os_write

res = {"probes": probes, "problems": problems, "after": None, "left": sorted(os.listdir(tmp)),
       "foreign_dirs": sorted(d for d in write_dirs if d != os.path.realpath(tmp))}
try:
    res["after"] = store.load_rates(target)
except BaseException as e:
    res["after"] = "%s: %s" % (type(e).__name__, e)
res["after_ok"] = res["after"] == NEW

try:
    store.save_rates(target, {"USD": object()})
    res["failed_save"] = "save_rates accepted a value JSON cannot encode"
except TypeError:
    try:
        got = store.load_rates(target)
        res["failed_save"] = "ok" if got == NEW else "the file now holds %r" % (got,)
    except BaseException as e:
        res["failed_save"] = "the file no longer loads: %s: %s" % (type(e).__name__, e)
for name in os.listdir(tmp):
    if name != "rates.json":
        os.remove(os.path.join(tmp, name))

with real_open(target, "w") as fh:
    fh.write('{"updated": 1, "rates": {"USD": 1.0')
box = {}
def read_corrupt():
    try:
        box["v"] = store.load_rates(target)
    except BaseException as e:
        box["e"] = type(e).__name__
t = threading.Thread(target=read_corrupt, daemon=True)
t.start()
t.join(5)
res["corrupt"] = "still waiting after 5 s" if t.is_alive() else ("raised " + box["e"] if "e" in box else "returned %r" % (box["v"],))
print(json.dumps(res))
'''


def check(repo, message):
    import tempfile
    repo = os.path.abspath(repo)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, repo, tmp], capture_output=True, text=True,
                           timeout=40, cwd=repo)
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        err = (r.stderr.strip().splitlines() or ["no output"])[-1]
        return [{"id": cid, "passed": False, "evidence": "probe failed: " + err}
                for cid in ("reader-never-sees-partial-file", "save-then-load", "failed-save-keeps-old-file",
                            "corrupt-file-still-raises", "no-temp-file-left")]
    res = json.loads(lines[-1])
    ok = bool(res["probes"]) and not res["problems"] and not res["foreign_dirs"]
    if not res["probes"]:
        ev = "no write to any file was observed during save_rates, so the race could not be probed"
    elif res["problems"] or res["foreign_dirs"]:
        bits = res["problems"][:3]
        if res["foreign_dirs"]:
            bits.append("written outside the target's directory (os.replace across filesystems fails): %s"
                        % res["foreign_dirs"])
        ev = "; ".join(bits)
    else:
        ev = "%d reads during the save all got the old or new rates (%s)" % (len(res["probes"]), "; ".join(res["probes"][:4]))
    out.append({"id": "reader-never-sees-partial-file", "passed": ok, "evidence": ev})
    out.append({"id": "save-then-load", "passed": res["after_ok"], "evidence": "load after save: %r" % (res["after"],)})
    out.append({"id": "failed-save-keeps-old-file", "passed": res["failed_save"] == "ok",
                "evidence": "after a save that raised TypeError: %s" % res["failed_save"]})
    out.append({"id": "corrupt-file-still-raises", "passed": res["corrupt"].startswith("raised"),
                "evidence": "load_rates on a truncated file: %s" % res["corrupt"]})
    out.append({"id": "no-temp-file-left", "passed": res["left"] == ["rates.json"],
                "evidence": "directory after save: %s" % res["left"]})
    return out
