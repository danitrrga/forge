"""Oracle for logic-transform-01 (Exercism word-count).

Runs the Exercism Python track's test file for word-count unchanged except for the import line
(exercism/python@6105f6d9d3ef66ce3d5c8f529d2882af3d76b706 exercises/practice/word-count/word_count_test.py, MIT,
generated from exercism/problem-specifications canonical-data.json), one check per test, then the project's own tests."""
import json
import re
import subprocess
import sys

EXERCISM_TESTS = '# These tests are auto-generated with test data from:\n# https://github.com/exercism/problem-specifications/tree/main/exercises/word-count/canonical-data.json\n# File last updated on 2023-07-19\n\nimport unittest\n\nfrom subtitles.wordcount import count_words\n\n\nclass WordCountTest(unittest.TestCase):\n    def test_count_one_word(self):\n        self.assertEqual(count_words("word"), {"word": 1})\n\n    def test_count_one_of_each_word(self):\n        self.assertEqual(count_words("one of each"), {"one": 1, "of": 1, "each": 1})\n\n    def test_multiple_occurrences_of_a_word(self):\n        self.assertEqual(\n            count_words("one fish two fish red fish blue fish"),\n            {"one": 1, "fish": 4, "two": 1, "red": 1, "blue": 1},\n        )\n\n    def test_handles_cramped_lists(self):\n        self.assertEqual(count_words("one,two,three"), {"one": 1, "two": 1, "three": 1})\n\n    def test_handles_expanded_lists(self):\n        self.assertEqual(\n            count_words("one,\\ntwo,\\nthree"), {"one": 1, "two": 1, "three": 1}\n        )\n\n    def test_ignore_punctuation(self):\n        self.assertEqual(\n            count_words("car: carpet as java: javascript!!&@$%^&"),\n            {"car": 1, "carpet": 1, "as": 1, "java": 1, "javascript": 1},\n        )\n\n    def test_include_numbers(self):\n        self.assertEqual(\n            count_words("testing, 1, 2 testing"), {"testing": 2, "1": 1, "2": 1}\n        )\n\n    def test_normalize_case(self):\n        self.assertEqual(count_words("go Go GO Stop stop"), {"go": 3, "stop": 2})\n\n    def test_with_apostrophes(self):\n        self.assertEqual(\n            count_words("\'First: don\'t laugh. Then: don\'t cry. You\'re getting it.\'"),\n            {\n                "first": 1,\n                "don\'t": 2,\n                "laugh": 1,\n                "then": 1,\n                "cry": 1,\n                "you\'re": 1,\n                "getting": 1,\n                "it": 1,\n            },\n        )\n\n    def test_with_quotations(self):\n        self.assertEqual(\n            count_words("Joe can\'t tell between \'large\' and large."),\n            {"joe": 1, "can\'t": 1, "tell": 1, "between": 1, "large": 2, "and": 1},\n        )\n\n    def test_substrings_from_the_beginning(self):\n        self.assertEqual(\n            count_words("Joe can\'t tell between app, apple and a."),\n            {\n                "joe": 1,\n                "can\'t": 1,\n                "tell": 1,\n                "between": 1,\n                "app": 1,\n                "apple": 1,\n                "and": 1,\n                "a": 1,\n            },\n        )\n\n    def test_multiple_spaces_not_detected_as_a_word(self):\n        self.assertEqual(\n            count_words(" multiple   whitespaces"), {"multiple": 1, "whitespaces": 1}\n        )\n\n    def test_alternating_word_separators_not_detected_as_a_word(self):\n        self.assertEqual(\n            count_words(",\\n,one,\\n ,two \\n \'three\'"), {"one": 1, "two": 1, "three": 1}\n        )\n\n    def test_quotation_for_word_with_apostrophe(self):\n        self.assertEqual(count_words("can, can\'t, \'can\'t\'"), {"can": 1, "can\'t": 2})\n\n    # Additional tests for this track\n\n    def test_tabs(self):\n        self.assertEqual(\n            count_words(\n                "rah rah ah ah ah\troma roma ma\tga ga oh la la\twant your bad romance"\n            ),\n            {\n                "rah": 2,\n                "ah": 3,\n                "roma": 2,\n                "ma": 1,\n                "ga": 2,\n                "oh": 1,\n                "la": 2,\n                "want": 1,\n                "your": 1,\n                "bad": 1,\n                "romance": 1,\n            },\n        )\n\n    def test_non_alphanumeric(self):\n        self.assertEqual(\n            count_words("hey,my_spacebar_is_broken"),\n            {"hey": 1, "my": 1, "spacebar": 1, "is": 1, "broken": 1},\n        )\n\n    def test_multiple_apostrophes_ignored(self):\n        self.assertEqual(count_words("\'\'hey\'\'"), {"hey": 1})\n'

RUN = r'''
import json, re, unittest
ns = {"__name__": "exercism_word_count_tests"}
exec(compile(TESTS, "word_count_test.py", "exec"), ns)
case = ns["WordCountTest"]
out = {}
for name in sorted(n for n in dir(case) if n.startswith("test_")):
    r = unittest.TestResult()
    case(name).run(r)
    bad = r.failures + r.errors
    if not bad:
        out[name] = "ok"
    else:
        tb = bad[0][1].strip().splitlines()
        exc = [l for l in tb if re.match(r"^[A-Za-z_.]*(Error|Exception)\b", l)]
        out[name] = (exc or tb)[-1][:200]
print(json.dumps(out))
'''

EXPECTED_TESTS = 17


def _py(repo, code, timeout=40):
    prog = "import sys\nsys.path.insert(0, %r)\n" % repo + code
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", prog], cwd=repo, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    lines = r.stdout.strip().splitlines()
    if r.returncode or not lines:
        return None, (r.stderr.strip().splitlines() or ["exit %d" % r.returncode])[-1][:300]
    try:
        return json.loads(lines[-1]), None
    except ValueError:
        return None, "unparseable output: " + lines[-1][:200]


def _repo_tests(repo):
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=repo, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    ran = re.search(r"Ran (\d+) test", r.stderr)
    n = int(ran.group(1)) if ran else 0
    return r.returncode == 0 and n > 0, "%d test(s) ran, exit %d: %s" % (n, r.returncode, r.stderr.strip().splitlines()[-1:])


def check(repo, message):
    res, err = _py(repo, "TESTS = %r\n" % EXERCISM_TESTS + RUN)
    out = []
    if res is None or len(res) != EXPECTED_TESTS:
        out.append({"id": "exercism-tests-ran", "passed": False,
                    "evidence": err or "%d of %d tests found" % (len(res), EXPECTED_TESTS)})
    for name in sorted(res or {}):
        out.append({"id": "exercism-" + name, "passed": res[name] == "ok", "evidence": res[name]})
    ok, ev = _repo_tests(repo)
    out.append({"id": "project-tests-pass", "passed": ok, "evidence": ev})
    return out
