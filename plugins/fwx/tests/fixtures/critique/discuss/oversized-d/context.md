# Context: 01-calculator

## Intent
"I want a calculator I can run from the terminal. One file, nothing to install. I will mostly use it over SSH on a hosted shell, so it has to work with whatever Python is already there."

## What success means
Typing `python3 calc.py "2 + 3 * 4"` prints `14`. With no argument it reads one expression per line until an empty line. Brackets and a minus sign in front of a number work. `0.1 + 0.2` prints `0.3`, as a person would write it. Dividing by zero prints a short message and stops with exit code 1, no traceback.

## Surfaces
None.

## Approved UI
None.

## Research
None.
