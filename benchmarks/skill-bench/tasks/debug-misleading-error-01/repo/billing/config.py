"""Load the [billing] section of settings.ini (the format is in README.md)."""
import configparser

SCHEMA = {
    "currency": str,
    "tax_rate": float,
    "late_fee_rate": float,
    "net_days": int,
}


def load_config(path):
    parser = configparser.ConfigParser()
    with open(path, encoding="utf-8") as fh:
        parser.read_file(fh)
    section = parser["billing"]
    cfg = {}
    for key, kind in SCHEMA.items():
        raw = section.get(key)
        try:
            cfg[key] = kind(raw)
        except (TypeError, ValueError):
            cfg[key] = raw  # unusual value: keep it as written
    return cfg
