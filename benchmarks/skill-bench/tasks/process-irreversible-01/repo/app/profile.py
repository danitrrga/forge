def display_name(customer):
    return customer["full_name"]


def initials(customer):
    return "".join(part[0].upper() for part in customer["full_name"].split()[:2])
