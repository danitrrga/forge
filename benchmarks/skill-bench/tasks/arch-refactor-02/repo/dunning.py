"""Late fees, charged by the nightly billing run."""
from report import days_late

FEE_PER_WEEK_CENTS = 500


def late_fee(invoice):
    return 0 if invoice["paid"] else (days_late(invoice) // 7) * FEE_PER_WEEK_CENTS
