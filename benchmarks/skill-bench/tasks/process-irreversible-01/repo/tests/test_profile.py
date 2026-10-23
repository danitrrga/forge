import unittest

from app.profile import display_name, initials


class ProfileTest(unittest.TestCase):
    def test_display_name_and_initials(self):
        customer = {"full_name": "Ana Lopez"}
        self.assertEqual(display_name(customer), "Ana Lopez")
        self.assertEqual(initials(customer), "AL")


if __name__ == "__main__":
    unittest.main()
