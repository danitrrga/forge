# billing.py - order totals for the checkout (written 2019, "temporarily")


def compute_total(lines, code=None, country="ES", member=False):
    # lines = list of (sku, qty, unit_cents)
    t = 0
    n = 0
    for l in lines:
        if l[1] > 0:
            t = t + l[1] * l[2]
            n = n + l[1]
        else:
            if l[1] < 0:
                pass  # returns go through refunds.py, not here
    d = 0
    if code != None:
        c = code.strip().upper()
        if c == "WELCOME10":
            if t >= 3000:
                d = t * 10 // 100
        elif c == "BULK":
            if n >= 10:
                d = t * 15 // 100
            else:
                if n >= 5:
                    d = t * 5 // 100
    if member:
        if d == 0:
            d = t * 5 // 100  # members get 5% unless a code already gave something
    s = 0
    if country == "ES":
        if t < 5000:  # NB free shipping looks at the amount before discounts
            s = 490
    else:
        if country == "PT" or country == "FR":
            s = 890
        else:
            s = 1500
    taxable = t - d
    if country == "ES" or country == "PT" or country == "FR":
        x = taxable * 21
        tax = x // 100
        if x % 100 >= 50:
            tax = tax + 1
    else:
        tax = 0
    return {"subtotal": t, "discount": d, "shipping": s, "tax": tax, "total": t - d + s + tax}
