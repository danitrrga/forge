import os
import tempfile
import unittest

from rates.store import load_rates, save_rates


class StoreTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rates.json")
            save_rates(path, {"USD": 1.08, "GBP": 0.85})
            self.assertEqual(load_rates(path), {"USD": 1.08, "GBP": 0.85})

    def test_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rates.json")
            save_rates(path, {"USD": 1.08})
            save_rates(path, {"USD": 1.09})
            self.assertEqual(load_rates(path), {"USD": 1.09})


if __name__ == "__main__":
    unittest.main()
