import unittest

from labels.address import format_address


class AddressTests(unittest.TestCase):
    def test_upper_cases(self):
        self.assertEqual(format_address(["Ana Lima", "1 Example Road"]), ["ANA LIMA", "1 EXAMPLE ROAD"])

    def test_drops_blank_lines(self):
        self.assertEqual(format_address(["Ben", "", "  ", "Leeds"]), ["BEN", "LEEDS"])

    def test_collapses_spaces(self):
        self.assertEqual(format_address(["Flat  2,   Acme House"]), ["FLAT 2, ACME HOUSE"])

    def test_too_many_lines(self):
        with self.assertRaises(ValueError):
            format_address(["a", "b", "c", "d", "e"])

    def test_line_too_long(self):
        with self.assertRaises(ValueError):
            format_address(["x" * 33])


if __name__ == "__main__":
    unittest.main()
