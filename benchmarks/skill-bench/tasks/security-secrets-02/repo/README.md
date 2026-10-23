# invoice-sync

Pulls invoices from Acme Billing every night. `billing/client.py` talks to the API,
`sync_invoices.py` is the job. Tests: `python3 -m unittest discover -s tests -t .`
