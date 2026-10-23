import unittest

from crm.merge import merge_contacts


class MergeContactsTest(unittest.TestCase):
    def test_same_person_matched_ignoring_case_and_spaces(self):
        merged = merge_contacts(
            [{"email": "ana@example.test", "name": "Ana"}],
            [{"email": " ANA@example.test", "city": "Valencia"}],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "Ana")
        self.assertEqual(merged[0]["city"], "Valencia")

    def test_later_export_wins(self):
        merged = merge_contacts(
            [{"email": "ben@example.test", "city": "Bilbao"}],
            [{"email": "ben@example.test", "city": "Sevilla"}],
        )
        self.assertEqual(merged[0]["city"], "Sevilla")

    def test_order_of_first_appearance(self):
        merged = merge_contacts(
            [{"email": "cleo@example.test"}, {"email": "ana@example.test"}],
            [{"email": "ben@example.test"}, {"email": "cleo@example.test"}],
        )
        self.assertEqual([c["email"] for c in merged],
                         ["cleo@example.test", "ana@example.test", "ben@example.test"])


if __name__ == '__main__':
    unittest.main()
