import unittest

from inbox.panel import Panel

ITEMS = [{"id": "n1", "text": "Ben replied to ticket #412", "when": "2 min ago"}]


class PanelTest(unittest.TestCase):
    def open_with(self, fetch):
        painted = []
        Panel(fetch, painted.append).open()
        return painted

    def test_shows_notifications(self):
        painted = self.open_with(lambda: ITEMS)
        self.assertIn("Ben replied to ticket #412", painted[-1])

    def test_caught_up_when_there_are_none(self):
        painted = self.open_with(lambda: [])
        self.assertIn("all caught up", painted[-1])


if __name__ == "__main__":
    unittest.main()
