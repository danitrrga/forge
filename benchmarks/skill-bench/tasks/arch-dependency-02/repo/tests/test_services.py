import unittest

import search
import services
import store


class ServicesTest(unittest.TestCase):
    def test_register_then_rename_updates_search(self):
        services.register("u1", "Ana Ruiz", "ana@example.test")
        self.assertEqual(search.find("ana"), ["u1"])
        services.rename_user("u1", "Ana Ortiz")
        self.assertEqual(search.find("ruiz"), [])
        self.assertEqual(search.find("ortiz"), ["u1"])
        self.assertEqual(store.get_user("u1")["name"], "Ana Ortiz")

    def test_register_twice_is_refused(self):
        services.register("u2", "Ben", "ben@example.test")
        with self.assertRaises(ValueError):
            services.register("u2", "Ben", "ben@example.test")


if __name__ == "__main__":
    unittest.main()
