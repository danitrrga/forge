import sys

from tab.split import split_evenly


def main(argv):
    if len(argv) < 3:
        print("usage: python3 -m tab.cli TOTAL NAME [NAME...]", file=sys.stderr)
        return 2
    for name, share in split_evenly(argv[1], argv[2:]).items():
        print("%-12s %10s" % (name, share))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
