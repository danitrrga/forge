"""The billing page."""
from ui import routes
from ui.components import badge, button, card, stat


def _day(d):
    return "%d %s" % (d.day, d.strftime("%b %Y"))


def render(account, today):
    """Billing page for an account: {"name", "plan", "seats", "plan_expires": date, "monthly_total"}."""
    expired = account["plan_expires"] < today
    status = badge("Expired", "danger") if expired else badge("Active", "success")
    plan = card(
        "Plan",
        '<dl>%s%s%s%s</dl>' % (
            stat("Plan", account["plan"]),
            stat("Seats", str(account["seats"])),
            stat("Monthly total", account["monthly_total"]),
            stat("Renews on", _day(account["plan_expires"])),
        ),
        button("Change plan", href=routes.PLANS, variant="secondary"),
    )
    invoices = card(
        "Invoices",
        '<p class="muted">Invoices are emailed to the account owner on the 1st of each month.</p>',
        button("View invoices", href=routes.INVOICES, variant="secondary"),
    )
    return '<main class="page"><h1 class="page__title">Billing %s</h1>%s%s</main>' % (status, plan, invoices)
