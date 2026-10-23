# acme-ship

Shipping labels for the packing stations.

- `labels/dates.py`, `labels/address.py`: the text that goes on a label.
- `labels/render.py`: lays the label out and encodes the barcode with `acme_barcode`, the printer vendor's SDK.
  The SDK is not on PyPI: it ships as a wheel inside the packing-station image (`requirements-station.txt`),
  so it is only installed there.

## Checks

```
make lint
make test     # unit tests; the label-rendering tests need acme_barcode
```
