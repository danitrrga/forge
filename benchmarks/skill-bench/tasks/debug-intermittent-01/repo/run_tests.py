"""Run the suite in a random order, as CI does: python3 run_tests.py [--seed N]"""
import argparse
import random
import sys
import unittest


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=random.randrange(10**6))
    seed = parser.parse_args().seed
    tests = list(flatten(unittest.defaultTestLoader.discover("tests", top_level_dir=".")))
    random.Random(seed).shuffle(tests)
    print("test order seed: %d" % seed)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
