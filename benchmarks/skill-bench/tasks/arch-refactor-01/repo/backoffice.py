"""Nightly export job: writes the three files finance picks up."""
import json
import os
import sys

from reports import payouts_csv, refunds_csv, sales_csv


def export(data, outdir):
    for name, fn in (("sales", sales_csv), ("refunds", refunds_csv), ("payouts", payouts_csv)):
        with open(os.path.join(outdir, name + ".csv"), "w", newline="", encoding="utf-8") as fh:
            fh.write(fn(data[name]))


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        export(json.load(fh), sys.argv[2])
