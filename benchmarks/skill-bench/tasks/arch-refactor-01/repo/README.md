# acme back office exports

`backoffice.py` writes sales.csv, refunds.csv and payouts.csv every night; finance imports
them (payouts.csv goes on to the bank).

```bash
python3 backoffice.py data.json outdir/
python3 -m unittest
```
