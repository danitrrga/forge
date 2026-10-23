"""In-memory store for the notes service. Swapped for the database in production."""
import copy

USERS = {
    "u-ana": {"id": "u-ana", "name": "Ana"},
    "u-ben": {"id": "u-ben", "name": "Ben"},
    "u-cleo": {"id": "u-cleo", "name": "Cleo"},
}

# API token -> user id
TOKENS = {"t-ana-51c0": "u-ana", "t-ben-7aa2": "u-ben", "t-cleo-e94d": "u-cleo"}

_SEED = {
    1: {"id": 1, "owner": "u-ben", "shared_with": [], "title": "Salary bands 2027",
        "body": "Draft salary bands for the platform team. Do not forward."},
    2: {"id": 2, "owner": "u-ben", "shared_with": ["u-cleo"], "title": "Offsite agenda",
        "body": "Day one: roadmap review. Day two: hiking trip."},
    3: {"id": 3, "owner": "u-ana", "shared_with": [], "title": "Reading list",
        "body": "Designing Data-Intensive Applications; The Pragmatic Programmer."},
}
DOCS = copy.deepcopy(_SEED)


def reset():
    DOCS.clear()
    DOCS.update(copy.deepcopy(_SEED))


def get_doc(doc_id):
    return DOCS.get(doc_id)
