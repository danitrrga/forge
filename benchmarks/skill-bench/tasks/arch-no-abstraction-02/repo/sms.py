"""SMS gateway client. (The HTTP part is stubbed here: messages land in OUTBOX.)"""

OUTBOX = []
MAX_LENGTH = 160


def send_sms(number, text):
    if len(text) > MAX_LENGTH:
        raise ValueError("SMS longer than %d characters" % MAX_LENGTH)
    OUTBOX.append({"to": number, "text": text})
