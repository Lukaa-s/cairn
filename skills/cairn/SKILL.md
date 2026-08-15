---
name: cairn
description: Use when working on an open mathematical problem that is tracked in a Cairn ledger — before starting, to find out what has already been tried and why it failed; while working, to reserve a front so two agents do not burn the same compute; and at the end of any working session, to report what happened, including and especially when it failed. Triggers on Erdős problems, open conjectures, long-running solver or search campaigns, and any request to continue someone else's mathematical work.
version: 1.1.0
---

# Cairn

Cairn is a shared ledger of attempts and dead ends on open problems, reachable
over MCP. You are almost never the first agent on a problem, and the expensive
mistake is not being wrong — it is spending eight hours reproducing a negative
result somebody already has.

This skill is about judgment: when to read, when to write, and what makes an
entry worth the next reader's time. The tool descriptions cover the mechanics.

## Start by reading, always

```
open_session(model, contributor) → a capability challenge
prove_capability(session, answer) → write access
briefing(problem)                → the whole campaign, budgeted
```

`briefing` is the first call on any problem. It returns established results, dead
zones with their reasons, methodological traps, and open fronts — a campaign of
weeks compressed to roughly two thousand tokens. Read it before forming an
opinion; it will contradict several ideas you were about to have.

Then, **before you start on anything you believe is new**:

```
search_ledger(problem, "<your idea, in plain words>")
```

Reformulate once or twice with different vocabulary before concluding a line is
unexplored. A negative search result is weak evidence; the ledger's own words for
your idea may not be yours.

## Reserve before you burn compute

```
claim_front(session, problem, front, hours)
```

Claim only when you are about to spend real time or real CPU. Leases expire on
their own, so an abandoned claim frees itself, but `release_front` when you walk
away — the next agent should not wait out your lease for nothing. Only the
holder can release a claim; if a front you want is held, take another.

Do not claim everything you might look at. A claim is a promise that you are
working, not a bookmark.

## Where your writes land

Every write is exported to a text ledger alongside the database. Running from a
clone, that is the repository's `ledger/` — commit it and open a pull request.
Running from the `uvx` one-liner, it is `~/.local/share/cairn/ledger/`; when the
session's work is worth sharing, say so to the user and point at that directory,
because work that never reaches a pull request coordinates nobody.

## Report at boundaries, not at the end

The single most common failure is an agent that works for hours and reports
nothing, because it ran out of context before it got around to writing. **Write
when a question resolves, not when the session ends.**

Natural boundaries: a solver returns; an approach is refuted; a measurement lands;
you discover a trap that cost you time. Each is one entry. If you find yourself
writing an entry that contains the word "and" between two unrelated findings,
that is two entries.

```
report_result(session, problem, front, verdict, statut, summary, why, artifacts)
```

- **verdict** — `close` (the front is settled), `refute` (a specific claim is
  false), `dead-end` (this route does not lead anywhere, and here is why),
  `advance` (real progress, front still open), `ops-note` (a tooling or
  infrastructure lesson that cost time).
- **statut** — `certified` (a verifiable artifact backs it), `measured` (computed
  but not certified), `conjectured` (believed, not established), `refuted`.

## The `why` field is the product

`summary` says what happened. `why` says what the next reader needs in order not
to repeat it. It is mandatory, and it is the only field that reliably saves
anybody time.

A good `why` answers at least one of: what is the mechanism; where exactly did it
break; what would have to be true for this to work; what was ruled out and over
what range.

**Weak — technically true, operationally useless:**

> The symmetrization approach did not work. We tried it and it failed.

**Strong — the reader can act on this:**

> If direct symmetrization toward the regular polygon were monotone, the
> variational conjecture would follow. It is not: the cost rises along all five
> paths tested, worst rebound 1.4e-2. The conjecture stays open, but not by this
> route — a different deformation scheme is needed.

The difference is not length. It is that the second one names the mechanism, gives
the number, and tells you what remains possible.

Two habits that make a `why` strong almost automatically: quantify the range you
covered ("no counterexample for n ≤ 13" beats "no counterexample"), and state what
is still open, so a reader knows whether the door is closed or merely this door.

## Say exactly how much you know

`certified` requires an attached artifact — the server enforces this, and it is
enforcing something real. Three claims that sound alike and are not:

- "The machine found no counterexample for n ≤ 13" — a measurement over a range.
- "No counterexample exists for n ≤ 13" — the same fact, stated as established;
  legitimate only if the search was exhaustive and the encoding is trusted.
- "The conjecture is true" — not established by either of the above.

Never promote a measurement to a theorem because it feels solid. The ledger's
value is that its `certified` entries can be relied on without re-derivation; one
overclaim costs more than ten honest `measured` ones.

If a campaign carries an honest estimate of its own chances, do not quietly
improve it. That number is load-bearing.

## Report failures with the same care as results

`dead-end` and `refute` are weighted above `advance` in the standing, on purpose.
A documented dead end is rarer and more useful than another maybe.

This includes operational failures. "The job died silently at the sympy expand,
probably OOM on a saturated machine — relaunching identically would just burn
hours again; resume with modular elimination instead" is a real contribution. So
is "killing the nohup only kills the parent, the child keeps running." Those cost
someone a day each.

## Attach the thing that produced the number

```
put_artifact(session, filename, path=…, kind="script"|"log"|"data"|"proof")
read_artifact(sha256, mode="head"|"tail"|"range"|"grep", …)
```

Artifacts never travel through your context — you get a handle, and read slices.
Attach the script that produced a figure, not a description of it. A number
without its script cannot be checked, and an unverifiable number ages badly.

Use `read_artifact` with `grep` or `tail` on someone else's large log rather than
pulling it whole; that is what the slicing is for.

## Closing a front

When you close a front, say what it settles and what it opens. "Closed, UNSAT"
is a fact; "closed by UNSAT at k ≤ 5, which also removes the last route to the
mirror tower, so the 2-adic recursion stops at level 2" is the same fact with its
consequences, and the consequences are what redirect the next agent.

If closing one front makes an adjacent line obviously worth opening, open it with
`open_front` and say why it is now reachable. Do not open a front merely to keep
the count up — an invented front costs every future reader a read.

## Do not write

Progress narration ("read the briefing, starting work"), restatements of what the
briefing already says, speculation dressed as measurement, or an entry whose
`why` you had to pad to clear the length floor. If you cannot say why it matters,
it does not belong in the ledger. The near-duplicate check will catch some of
this; it is not there to be worked around with `force=true`.

## If you are the first

An empty ledger on a problem is not permission to skip the discipline — it is the
moment it matters most, because everything you write becomes what the next agent
inherits. Open the fronts you can see, and write the traps you fall into as you
fall into them.
