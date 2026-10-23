import unittest

from notify.render import render


class RenderTests(unittest.TestCase):
    def test_subject_and_body_split(self):
        subject, body = render("welcome", first_name="Ben", login_url="https://acme.example.test/login",
                               email="ben@example.test")
        self.assertEqual(subject, "Welcome to Acme, Ben")
        self.assertTrue(body.startswith("Hi Ben,"))

    def test_missing_placeholder_raises(self):
        with self.assertRaises(KeyError):
            render("welcome", first_name="Ben")


if __name__ == "__main__":
    unittest.main()
