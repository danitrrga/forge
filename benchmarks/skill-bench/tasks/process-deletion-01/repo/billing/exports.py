import csv
import json
import os

from billing.invoices import build_invoice

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_invoices():
    with open(os.path.join(HERE, "data", "invoices.json")) as fh:
        return [build_invoice(raw) for raw in json.load(fh)]


def _eur(cents):
    return "%d.%02d" % divmod(cents, 100)


def ledger_rows(invoices):
    return [[i["number"], i["customer"], _eur(i["net_cents"]), _eur(i["vat_cents"]), _eur(i["gross_cents"])]
            for i in invoices]


def export_ledger_csv(out_dir):
    """Write ledger.csv for the accountants' import; returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "ledger.csv")
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["invoice", "customer", "net", "vat", "gross"])
        writer.writerows(ledger_rows(load_invoices()))
    return path
