"""Build dist/acme_dates-<version>.tar.gz from the working tree (local only, uploads nothing)."""
import os
import re
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "pyproject.toml")) as fh:
    version = re.search(r'^version = "(.+)"', fh.read(), re.M).group(1)
name = "acme_dates-%s" % version
os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
out = os.path.join(ROOT, "dist", name + ".tar.gz")
with tarfile.open(out, "w:gz") as tar:
    for rel in ("pyproject.toml", "README.md", "CHANGELOG.md", "acme_dates"):
        tar.add(os.path.join(ROOT, rel), arcname=os.path.join(name, rel),
                filter=lambda t: None if "__pycache__" in t.name else t)
with open(os.path.join(ROOT, "ops.log"), "a") as fh:
    fh.write("build %s.tar.gz\n" % name)
print("built", os.path.relpath(out, ROOT))
