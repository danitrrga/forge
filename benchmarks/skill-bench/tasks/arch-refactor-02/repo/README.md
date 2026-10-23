# acme receivables

`report.py` builds the weekly receivables e-mail that `scheduler.py` (a long-running worker) sends
every Monday; `dunning.py` charges late fees from the same day count.

```bash
python3 -m unittest
```
