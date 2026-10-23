# acme orders

Layers, lowest first: `models` (plain data) -> `pricing` -> `report`. A module only imports from
layers below it.

```bash
python3 report.py
python3 -m unittest
```
