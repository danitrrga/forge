import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "store.json")


class DuplicateEmail(ValueError):
    pass


def load(path=STORE):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["customers"]


def save(customers, path=STORE):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"customers": customers}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def find(customers, email):
    email = email.strip().lower()
    return next((c for c in customers if c["email"] == email), None)


def add_customer(customers, name, email, phone=""):
    """Append a customer; raises DuplicateEmail if the email is already in the list."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValueError("not an email address: %r" % email)
    if find(customers, email):
        raise DuplicateEmail(email)
    customer = {"name": " ".join(name.split()), "email": email, "phone": phone.strip()}
    customers.append(customer)
    return customer
