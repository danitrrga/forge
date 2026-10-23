"""Bundle src/styles/*.css into dist/app.css, tokens first."""
import glob
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def sources():
    files = sorted(glob.glob(os.path.join(ROOT, "src", "styles", "*.css")))
    return sorted(files, key=lambda p: os.path.basename(p) != "tokens.css")


def bundle():
    return "\n".join(open(p, encoding="utf-8").read() for p in sources())


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    with open(os.path.join(ROOT, "dist", "app.css"), "w", encoding="utf-8") as fh:
        fh.write(bundle())
    print("dist/app.css written")
