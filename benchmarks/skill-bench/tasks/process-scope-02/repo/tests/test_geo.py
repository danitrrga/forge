import unittest

from fake_http import patch_urlopen
from shipping import geo


class GeoTest(unittest.TestCase):
    def test_geocode_returns_first_hit(self):
        patcher, calls = patch_urlopen([{"lat": 0.5, "lon": 0.25}])
        with patcher:
            self.assertEqual(geo.geocode("1 Example Road"), (0.5, 0.25))
        self.assertIn("q=1+Example+Road", calls[0][0])


if __name__ == "__main__":
    unittest.main()
