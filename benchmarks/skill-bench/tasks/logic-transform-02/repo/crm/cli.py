import json
import sys

from crm.merge import merge_contacts


def main(paths):
    exports = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            exports.append(json.load(fh))
    json.dump(merge_contacts(*exports), sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
