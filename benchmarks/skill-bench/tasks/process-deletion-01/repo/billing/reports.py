"""Month-end summary for the close:  python3 -m billing.reports"""
from billing.exports import ledger_rows, load_invoices


def monthly_summary():
    return "\n".join(" | ".join(row) for row in ledger_rows(load_invoices()))


if __name__ == "__main__":
    print(monthly_summary())
