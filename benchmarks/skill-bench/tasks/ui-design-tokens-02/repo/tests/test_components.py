import unittest

from ui.components import alert, button


class ComponentsTest(unittest.TestCase):
    def test_alert_escapes_and_links(self):
        html = alert("Use <b> wisely", tone="warning", title="Heads up", action=("Fix it", "/fix?a=1&b=2"))
        self.assertIn("alert--warning", html)
        self.assertIn("&lt;b&gt;", html)
        self.assertIn('href="/fix?a=1&amp;b=2"', html)

    def test_alert_rejects_unknown_tone(self):
        with self.assertRaises(ValueError):
            alert("x", tone="loud")

    def test_button_as_link(self):
        self.assertEqual(button("Go", href="/x"), '<a class="btn btn--primary" href="/x">Go</a>')


if __name__ == "__main__":
    unittest.main()
