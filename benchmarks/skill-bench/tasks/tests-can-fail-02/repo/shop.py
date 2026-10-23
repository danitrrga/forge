"""Shop front: the price list shown on the catalogue page."""


def price_list(book, skus):
    return "\n".join("%-12s %8.2f" % (sku, cents / 100) for sku, cents in book.prices(skus).items())
