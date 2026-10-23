import os
import tempfile
import unittest

from crm import store


class StoreTests(unittest.TestCase):
    def test_add_normalises(self):
        customers = []
        c = store.add_customer(customers, "  Ana   Lima ", " Ana@Example.test ", "+44 113 496 0001")
        self.assertEqual(c, {"name": "Ana Lima", "email": "ana@example.test", "phone": "+44 113 496 0001"})

    def test_duplicate_email_is_rejected_case_insensitively(self):
        customers = []
        store.add_customer(customers, "Ana", "ana@example.test")
        with self.assertRaises(store.DuplicateEmail):
            store.add_customer(customers, "Ana L", "ANA@example.test")

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            store.save([{"name": "João", "email": "joao@example.test", "phone": ""}], path)
            self.assertEqual(store.load(path)[0]["name"], "João")


if __name__ == "__main__":
    unittest.main()
