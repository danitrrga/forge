---

# Output Discipline

Binds everything you emit: PLAN.md, STATE.md, RESEARCH.md, VERIFICATION.md, SUMMARY.md,
ROADMAP.md, gate prompts, checkpoint messages, questions to the user, commit messages, and
what you say back in chat. These documents are read by an AI before a human, so a repeated
token is paid on every read, and a bare identifier forces a second file open to decode it.

## Rule 1 — Name the thing, never the code alone

An identifier standing alone is a defect, not a style. Plain words first; the identifier
follows in parentheses, and only when it helps someone look it up.

Wrong: `ADR-15 is not satisfied.` / `Blocked on D-48.` / `must_have MH-3 failed.`

Right: `The requirement that we write no TypeScript (ADR-15) is not satisfied.` /
`Blocked on whether the T7 backup keeps encryption (D-48).` /
`The check that a logged-out user cannot reach /dashboard (MH-3) failed.`

Not optional when the identifier is "obvious from context" — context is exactly what the
next session does not have. If naming it plainly costs ten more words, spend them. Rule 2
may never delete the plain-language meaning of an identifier.

## Rule 2 — Cut redundancy, never cut content

Same information, fewer tokens. **Not** less information. There is no length target; a
document that needs to be long stays long. The metric is repetition, not size.

**Scope: prose and documents only.** This rule NEVER applies to code, code comments, tests,
or verification steps. It is not permission to thin out tests, merge test cases, or drop a
check or criterion to make a report read tighter.

**Cut:** the same fact in two sections; a recap of what the document just said; a preamble
announcing what comes next ("In this section we will…"); a restatement of the plan right
before executing it; ceremony filler; a table repeating in a grid what the paragraph beside
it already said (keep whichever carries more, delete the other, not both); evaluative
adjectives that change no decision ("robust", "comprehensive", "seamless").

**Never cut:** facts and measured figures; file paths, `path:line`, commands, exact error
strings; identifiers and their plain meaning; **the WHY of a decision** (what was decided is
derivable from the code, why is not); **the control record — that a check was proved able to
fail, which control ran, and what it returned**; unexpected findings; anything a future
reader cannot derive from the rest.

**The test for every cut:** if I delete this, do I lose information, or only a second copy of
information already present? Lose information — it stays. Unsure — it stays.

### Legitimate cut

Before:

> In this section we describe the work done on rate limiting. Rate limiting was added to the
> login endpoint. This was a significant and robust improvement to security.
> Rate limiting was implemented at `src/api/login.ts:88` using a fixed window of 5 attempts
> per 15 minutes per IP address.
> **Summary of Task 3:** To summarize, we successfully added rate limiting, 5 per 15 minutes.

After:

> Rate limiting on the login endpoint, `src/api/login.ts:88` — fixed window, 5 attempts per
> 15 minutes per IP.

The preamble announced the next sentence, the closing summary repeated the sentence above
it, and "significant and robust" changes no decision. Path, line, algorithm, every number
survive.

### Forbidden cut

Before:

> ### MH-2 — a logged-out user cannot reach /dashboard
> Verified. Ran `npm run test:e2e -- auth-redirect`, exit 0, 4 passed.
> Negative control: temporarily removed the guard at `src/middleware/auth.ts:31` and re-ran —
> the test failed as expected (1 failed, "expected redirect to /login, got 200"). Restored,
> re-ran, exit 0. The test can therefore actually fail, and its pass means something.
> Unexpected: the guard also fires on `/dashboard/public`, meant to be reachable logged out.
> Out of scope for this phase; filed as an issue.

Cut to `### MH-2 — Verified. Tests pass.`

Every clause deleted there was information, not repetition:

- **Which control ran and what it returned.** Without it, "verified" is an unsourced claim.
- **That the check was proved able to fail** — the negative control, the line whose removal
  broke it, the failure message. A test never seen to fail is not evidence. This is the
  highest-value paragraph in the document and the one that looks most like filler.
- **The unexpected finding.** Nobody can derive it from the code later; from the code it
  looks intentional.
- **The plain meaning of the identifier**, leaving a bare `MH-2` in violation of Rule 1.

The correct edit to that passage is no edit. It contains no second copy of anything.
