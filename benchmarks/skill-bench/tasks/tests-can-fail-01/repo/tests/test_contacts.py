import unittest

from contacts import merge_contacts


def row(email, name="", phone="", company=""):
    return {"email": email, "name": name, "phone": phone, "company": company}


class MergeContactsTest(unittest.TestCase):
    def test_distinct_people_are_kept_in_order(self):
        rows = [row("ana@example.test", "Ana"), row("cy@example.test", "Cy")]
        self.assertEqual([r["name"] for r in merge_contacts(rows)], ["Ana", "Cy"])

    def test_merges_same_email_ignoring_case(self):
        rows = [row("dee@example.test", "Dee"), row("DEE@example.test", "Dee R.")]
        merged = merge_contacts(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "Dee")

    def test_later_rows_fill_empty_fields(self):
        rows = [row("eve@example.test", "Eve"), row("eve@example.test", "", "555-0101", "Acme")]
        merged = merge_contacts(rows)
        self.assertEqual(merged[0]["phone"], "555-0101")
        self.assertEqual(merged[0]["company"], "Acme")

    def test_first_row_wins_on_conflict(self):
        rows = [row("fay@example.test", "Fay", "555-0102"), row("fay@example.test", "Faye", "555-0199")]
        merged = merge_contacts(rows)
        self.assertEqual((merged[0]["name"], merged[0]["phone"]), ("Fay", "555-0102"))


if __name__ == "__main__":
    unittest.main()
