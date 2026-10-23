"""Outgoing e-mail. (The SMTP part is stubbed here: messages land in OUTBOX.)"""

OUTBOX = []


def send_email(to, subject, body):
    OUTBOX.append({"to": to, "subject": subject, "body": body})
