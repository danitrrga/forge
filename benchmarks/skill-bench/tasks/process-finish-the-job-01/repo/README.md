# acme-crm

The support team's customer list. Customers live in `data/store.json`, tracked in git like the code.

```
python3 -m crm list                          # everyone, sorted by name
python3 -m crm add "Ana Lima" ana@example.test --phone "+44 113 496 0001"
python3 -m unittest discover -s tests -t .
```

Emails are unique (compared case-insensitively); adding one that already exists is an error.
