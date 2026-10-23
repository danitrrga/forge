"""In-memory data for the shop demo. A real deployment swaps this for the database layer."""

USERS = {
    1: {"id": 1, "name": "Ana"},
    2: {"id": 2, "name": "Ben"},
    3: {"id": 3, "name": "Cleo"},
}

# session token (the value of the `session` cookie) -> user id
SESSIONS = {
    "s-ana-6b1f": 1,
    "s-ben-93c2": 2,
    "s-cleo-0d7e": 3,
}

ORDERS = [
    {"id": 101, "user_id": 1, "item": "Reading lamp", "total_cents": 3900},
    {"id": 102, "user_id": 2, "item": "Camping tent", "total_cents": 18900},
    {"id": 103, "user_id": 1, "item": "Desk mat", "total_cents": 1500},
    {"id": 104, "user_id": 2, "item": "Hiking boots", "total_cents": 12900},
]


def user_for_session(token):
    user_id = SESSIONS.get(token)
    return USERS.get(user_id)


def orders_for(user_id):
    return [o for o in ORDERS if o["user_id"] == user_id]
