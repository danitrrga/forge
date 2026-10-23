import unittest

import alerts
import mailer

ALERT = {"severity": "warning", "title": "Disk 85% full", "service": "db-1", "at": "2026-03-10T04:12:00Z"}


class NotifyTest(unittest.TestCase):
    def setUp(self):
        mailer.OUTBOX.clear()

    def test_emails_on_call(self):
        alerts.notify(ALERT)
        self.assertEqual(len(mailer.OUTBOX), 1)
        self.assertEqual(mailer.OUTBOX[0]["to"], "oncall@example.test")
        self.assertEqual(mailer.OUTBOX[0]["subject"], "[WARNING] db-1: Disk 85% full")


if __name__ == "__main__":
    unittest.main()
