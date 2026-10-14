#!/usr/bin/env python3
"""A profile's claude-mem-lite store: its own project's by default, or the one `memory_lite_store`
names, so projects that are one body of work remember into one store (forge/memory.py).

Seen failing before the key existed: the profile with `memory_lite_store` still got its own
project's directory, so three Omarchy plugin repos kept three stores and shared nothing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from forge import memory  # noqa: E402

failures = []


def check(label, ok, got):
    if not ok:
        failures.append("%s: %s" % (label, got))


class Ctx:
    apply = False


def derive(prof):
    prof = dict(prof, plugins_keep=[memory.LITE_PLUGIN])
    errs = memory.derive_lite_env(Ctx(), prof, "toy.claude.json")
    return errs, prof.get("env", {}).get("CLAUDE_MEM_DIR")


root = memory.LITE_ROOT
errs, got = derive({"project": "alpha"})
check("own store by default", not errs and got == os.path.join(root, "alpha"), (errs, got))

errs, got = derive({"project": "alpha", "memory_lite_store": "omarchy-plugins"})
check("named store", not errs and got == os.path.join(root, "omarchy-plugins"), (errs, got))

for bad in ("", "../x", "a/b", "-x", 7, ["x"]):
    errs, got = derive({"project": "alpha", "memory_lite_store": bad})
    check("refuses %r" % (bad,), bool(errs) and got is None, (errs, got))

errs, got = derive({"project": "alpha", "memory_lite_store": "omarchy-plugins",
                    "env": {"CLAUDE_MEM_DIR": os.path.join(root, "alpha")}})
check("a hand-typed dir that disagrees is still refused", bool(errs), (errs, got))

errs, got = derive({"project": "alpha", "memory_lite_store": "omarchy-plugins",
                    "env": {"CLAUDE_MEM_DIR": os.path.join(root, "omarchy-plugins")}})
check("a hand-typed dir that agrees is accepted", not errs, errs)

if failures:
    print("FAIL")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
