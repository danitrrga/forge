"""Validate the serializer's output for the sample orders against every schema we share with the mobile team.

Supports the subset of JSON Schema our schemas use: type, required, properties, additionalProperties."""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orders.api import order_to_json  # noqa: E402
from tests.fixtures import sample_orders  # noqa: E402

TYPES = {"string": str, "integer": int, "array": list, "object": dict}


def errors(doc, schema):
    out = []
    if not isinstance(doc, TYPES[schema.get("type", "object")]):
        return ["not a %s" % schema.get("type")]
    for key in schema.get("required", []):
        if key not in doc:
            out.append("missing required key %r" % key)
    props = schema.get("properties", {})
    for key, value in doc.items():
        if key not in props:
            if schema.get("additionalProperties") is False:
                out.append("unexpected key %r" % key)
            continue
        want = TYPES[props[key]["type"]]
        if not isinstance(value, want) or (want is int and isinstance(value, bool)):
            out.append("%r is not %s" % (key, props[key]["type"]))
    return out


def main():
    with open(os.path.join(ROOT, "gate.log"), "a") as fh:
        fh.write("schema\n")
    bad = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "schemas", "*.schema.json"))):
        with open(path) as fh:
            schema = json.load(fh)
        for order in sample_orders():
            for e in errors(order_to_json(order), schema):
                print("%s: order %s: %s" % (os.path.basename(path), order.id, e))
                bad += 1
    if bad:
        sys.exit(1)
    print("schema ok")


if __name__ == "__main__":
    main()
