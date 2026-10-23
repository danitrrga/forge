import unittest
from datetime import date
from unittest import mock

import reminders
from reminders import days_until_due, due_soon, reminder_text, send_reminders

TODAY = date(2026, 3, 10)
INVOICES = [
    {"number": "A-1", "email": "ana@example.test", "amount_cents": 12000, "due": "2026-03-11", "paid_at": None},
    {"number": "A-2", "email": "ben@example.test", "amount_cents": 4550, "due": "2026-03-13", "paid_at": None},
    {"number": "A-3", "email": "cy@example.test", "amount_cents": 990, "due": "2026-03-20", "paid_at": None},
    {"number": "A-4", "email": "dee@example.test", "amount_cents": 3000, "due": "2026-03-12", "paid_at": "2026-03-01"},
    {"number": "A-5", "email": "eve@example.test", "amount_cents": 700, "due": "2026-03-08", "paid_at": None},
]


class DueSoonTest(unittest.TestCase):
    def test_picks_invoices_due_within_three_days(self):
        for inv in due_soon(INVOICES, TODAY):
            self.assertGreaterEqual(days_until_due(inv, TODAY), 0)
            self.assertLessEqual(days_until_due(inv, TODAY), 3)

    def test_skips_paid_invoices(self):
        numbers = [inv["number"] for inv in due_soon(INVOICES, TODAY)]
        self.assertNotIn("A-4", numbers)


class ReminderTextTest(unittest.TestCase):
    def test_text(self):
        self.assertEqual(reminder_text(INVOICES[1], TODAY), "Invoice A-2 for 45.50 EUR is due in 3 days.")

    def test_due_tomorrow_and_today(self):
        self.assertTrue(reminder_text(INVOICES[0], TODAY).endswith("due in 1 day."))
        self.assertTrue(reminder_text(INVOICES[0], date(2026, 3, 11)).endswith("due today."))


class SendRemindersTest(unittest.TestCase):
    def test_sends_one_mail_per_due_invoice(self):
        send = mock.Mock()
        # due_soon depends on the date; pin it so the test does not change from day to day
        with mock.patch.object(reminders, "due_soon", return_value=INVOICES[:2]):
            count = send_reminders(INVOICES, send, today=TODAY)
        self.assertEqual(count, 2)
        self.assertEqual([c.args[0] for c in send.call_args_list], ["ana@example.test", "ben@example.test"])


if __name__ == "__main__":
    unittest.main()
