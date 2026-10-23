"""Monitoring alerts to the on-call engineer.

An alert: {"severity": "info" | "warning" | "critical", "title": ..., "service": ..., "at": ISO time,
           "details": optional text}
"""
import config
import mailer


def subject(alert):
    return "[%s] %s: %s" % (alert["severity"].upper(), alert["service"], alert["title"])


def body(alert):
    return "%s\n\nService: %s\nAt: %s\n\n%s\n" % (alert["title"], alert["service"], alert["at"], alert.get("details", ""))


def notify(alert):
    """Tell on-call about an alert."""
    mailer.send_email(config.ONCALL_EMAIL, subject(alert), body(alert))
