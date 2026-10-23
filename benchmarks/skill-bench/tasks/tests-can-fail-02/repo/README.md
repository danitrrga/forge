# acme-shop prices

`pricebook.py` caches prices for the shop front (`shop.py`); staff change them in the back office
(`admin.py`). Shop and admin run in the same process and share one `PriceBook`.

```bash
python3 -m unittest
```
