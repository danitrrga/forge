# acme-shop notifications

Every shop event in `shop/events.py` sends the customer one email. `shop.emails.render(event)` returns
`(subject, body)`; each email has its own module in `shop/emails/`.

```bash
make test
```
