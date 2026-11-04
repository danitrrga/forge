---
{
  "size": {"tag": "small", "parts": 1, "agents": 1},
  "criteria": [
    {"id": "C1", "text": "`calc.py` evaluates an expression with the four operations, brackets and a leading minus, and prints sums as a person writes them.", "measure": "`python3 tests/test_calc.py` exits 0, and `python3 calc.py \"0.1 + 0.2\"` prints 0.3."},
    {"id": "C2", "text": "A division by zero prints a message and stops with exit code 1, with no traceback.", "measure": "`python3 calc.py \"1 / 0\"; echo $?` prints the message on stderr and then 1."},
    {"id": "C3", "text": "With no argument, `calc.py` reads one expression per line, prints each result, and stops at an empty line.", "measure": "`printf '2 + 3\n4 * 5\n\n' | python3 calc.py` prints 5 and then 20 and exits 0."}
  ],
  "tasks": [
    {
      "id": "T1",
      "part": 1,
      "type": "feature",
      "wave": 1,
      "files": ["calc.py", "tests/test_calc.py"],
      "depends_on": [],
      "tests": [
        {"run": "python3 tests/test_calc.py", "measures": "precedence, brackets, a leading minus and exact decimal results of `evaluate()`", "red": "against an `evaluate()` that returns plain floats: FAIL: 0.1 + 0.2: got 0.30000000000000004, want 0.3"}
      ],
      "size": "normal",
      "ui": false
    },
    {
      "id": "T2",
      "part": 1,
      "type": "feature",
      "wave": 2,
      "files": ["calc.py", "tests/test_calc_cli.py"],
      "depends_on": ["T1"],
      "tests": [
        {"run": "python3 tests/test_calc_cli.py", "measures": "the argument form, the line-by-line form and the exit code of a division by zero", "red": "against a `main()` that lets the ZeroDivisionError out: FAIL: 1 / 0: exit 1 expected, got a traceback"}
      ],
      "size": "small",
      "ui": false
    }
  ],
  "not_built": [
    {"what": "powers, functions and constants", "why": "D3 limits the calculator to the four operations and brackets."},
    {"what": "variables and a history inside the line-by-line mode", "why": "D2 rejected a REPL."}
  ],
  "later": []
}
---

## Goal
A one-file terminal calculator, `calc.py`, that evaluates one expression from its argument or one per line, and shows `0.1 + 0.2` as `0.3`.

## Approach
T1 writes `evaluate()`: a small recursive-descent parser over the standard library only (D1) that handles the four operations, brackets and a leading minus (D3). It computes with `fractions.Fraction` instead of floats, so the result of `0.1 + 0.2` is exactly 3/10 and prints as `0.3` (D4); a result that does not end is printed rounded to ten places. This is the less common route: `decimal.Decimal` would also work, but `Fraction` needs no precision setting and does exact division, so the parser stays free of context state.

T2 adds `main()`: one expression from the argument, or one per line until an empty line when there is none (D2). A division by zero is caught in `main()`, printed to stderr, and ends the run with exit code 1 (D3).

The owner runs the calculator on a hosted shell that stops any process after 10 seconds of CPU time; every expression here finishes in milliseconds, so no timeout handling is planned. C1 and C2 are measured by the two test files and the two commands named in them.

## Size
Small: two tasks in two waves, because T2 calls the function T1 writes. One part, one agent.
