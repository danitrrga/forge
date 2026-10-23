"""Lint src/styles: balanced braces, no !important, hex colours only in tokens.css."""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "gate.log"), "a") as fh:
    fh.write("css\n")
bad = []
for p in sorted(glob.glob(os.path.join(ROOT, "src", "styles", "*.css"))):
    name = os.path.basename(p)
    text = re.sub(r"/\*.*?\*/", "", open(p, encoding="utf-8").read(), flags=re.S)
    if text.count("{") != text.count("}"):
        bad.append("%s: unbalanced braces" % name)
    if "!important" in text:
        bad.append("%s: !important" % name)
    if name != "tokens.css" and re.search(r"#[0-9a-fA-F]{3,8}\b", text):
        bad.append("%s: hard-coded colour, use a token from tokens.css" % name)
for b in bad:
    print(b)
if bad:
    sys.exit(1)
print("css ok")
