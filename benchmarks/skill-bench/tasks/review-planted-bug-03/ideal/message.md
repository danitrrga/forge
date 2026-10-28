Blocking: `is_admin` tests `role in ADMIN_ROLES`, but `ADMIN_ROLES` (roles.py) is a plain string, so this is a substring match and an empty or partial role counts as admin. Make it a tuple. Review is in REVIEW.md.

VERDICT: request changes
