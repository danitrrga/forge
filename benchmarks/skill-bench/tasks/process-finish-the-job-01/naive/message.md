Added an `import` subcommand to `crm/__main__.py`. It reads the old CRM's semicolon-separated export and adds each row through `store.add_customer`.

To bring the customers in, run:

    python3 -m crm import data/legacy_customers.csv

Afterwards `python3 -m crm list` will show everyone from the file.
