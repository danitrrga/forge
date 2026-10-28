The diff is one line; the problem is what `ADMIN_ROLES` is (a string). Substring semantics: the empty default role is 'in' it. Security issue.

VERDICT: request changes
