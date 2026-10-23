import argparse
import sys

from crm import store


def main(argv=None):
    p = argparse.ArgumentParser(prog="crm")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="print every customer")
    a = sub.add_parser("add", help="add one customer")
    a.add_argument("name")
    a.add_argument("email")
    a.add_argument("--phone", default="")
    args = p.parse_args(argv)

    customers = store.load()
    if args.cmd == "list":
        for c in sorted(customers, key=lambda c: c["name"].lower()):
            print("%-22s %-28s %s" % (c["name"], c["email"], c["phone"]))
        print("%d customers" % len(customers))
    elif args.cmd == "add":
        try:
            store.add_customer(customers, args.name, args.email, args.phone)
        except store.DuplicateEmail as e:
            sys.exit("crm: %s is already a customer" % e)
        store.save(customers)
        print("added %s" % args.email)


if __name__ == "__main__":
    main()
