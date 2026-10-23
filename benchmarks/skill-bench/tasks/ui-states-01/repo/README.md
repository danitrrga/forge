# Acme Shop: customer pages

Server-rendered pages for the shop's customer area, standard library only.

- `python3 -m shop.server` serves http://localhost:8000/orders?customer=c-1001
- `python3 -m unittest` runs the tests

The orders page reads from the orders service through `shop/api.py`.
