def money(cents):
    return "EUR %d.%02d" % divmod(cents, 100)


def greeting(order):
    return "Hi %s," % order.customer_name.split()[0]


def footer():
    return "Questions? Just reply to this email or visit https://shop.example.test/help\n-- The Acme Shop team"
