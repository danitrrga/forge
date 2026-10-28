"""Authorisation helpers."""
from roles import ADMIN_ROLES


def is_admin(user):
    return user.get("role", "") in ADMIN_ROLES
