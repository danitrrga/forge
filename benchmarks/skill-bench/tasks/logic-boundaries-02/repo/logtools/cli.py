import sys

from logtools.latest import latest_log


def main(argv):
    if not 2 <= len(argv) <= 3:
        print("usage: python3 -m logtools.cli PATTERN [LOG_DIR]", file=sys.stderr)
        return 2
    path = latest_log(*argv[1:])
    if path is None:
        print("no matching log", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
