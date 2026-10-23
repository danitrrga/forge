"""Write site/billing.html for the demo account."""
import datetime
import os

from pages import billing

DEMO = {"name": "Northwind", "plan": "Team", "seats": 12, "plan_expires": datetime.date(2026, 11, 30),
        "monthly_total": "€96.00"}
HEAD = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Billing · Acme Console</title>'
        '<link rel="stylesheet" href="../ui/tokens.css"><link rel="stylesheet" href="../ui/components.css">')

if __name__ == "__main__":
    os.makedirs("site", exist_ok=True)
    with open("site/billing.html", "w", encoding="utf-8") as fh:
        fh.write(HEAD + billing.render(DEMO, datetime.date.today()))
    print("wrote site/billing.html")
