import datetime
import unittest

try:
    import acme_barcode
except ImportError:  # only installed on the packing-station image
    acme_barcode = None

from labels.dates import format_delivery_date
from labels.render import label_fields, render_label

SHIPMENT = {
    "ref": "ACME-000123",
    "address": ["Ana Lima", "1 Example Road", "Leeds"],
    "delivery_date": datetime.date(2026, 3, 9),
}


@unittest.skipIf(acme_barcode is None, "acme_barcode not installed")
class LabelTests(unittest.TestCase):
    def test_delivery_date_format(self):
        self.assertEqual(format_delivery_date(datetime.date(2026, 3, 9)), "09 Mar")

    def test_delivery_date_pads_the_day(self):
        self.assertEqual(format_delivery_date(datetime.date(2026, 11, 1)), "01 Nov")

    def test_label_fields(self):
        self.assertEqual(label_fields(SHIPMENT)["deliver"], "09 Mar")

    def test_render_encodes_the_reference(self):
        label = render_label(SHIPMENT)
        self.assertEqual(label.barcodes(), [(acme_barcode.CODE128, "ACME-000123")])


if __name__ == "__main__":
    unittest.main()
