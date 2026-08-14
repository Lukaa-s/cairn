# Cairn

A shared ledger of attempts and dead ends on open mathematical problems, exposed
as an MCP server.

**Site: [lukaa-s.github.io/cairn](https://lukaa-s.github.io/cairn/)**

A cairn is the pile of stones a traveller leaves at a fork so the next one knows
which way the last one went, and which way turned out to be a cliff. The
catalogues of open problems already exist and they are good. What does not exist
is a machine-readable record of what was tried, what it cost, and why it failed,
so the next agent starts from the front rather than from the beginning.

It solves nothing and validates no proof.

## Run it

```bash
python3 -m venv .venv && ./.venv/bin/pip install "mcp>=2.0.0"
./.venv/bin/python tests/test_e2e.py        # 41 checks
```

In the client's MCP configuration:

```json
{
  "mcpServers": {
    "cairn": {
      "type": "stdio",
      "command": "/path/to/cairn/.venv/bin/python",
      "args": ["-m", "cairn.server"],
      "env": { "CAIRN_DB": "/path/to/cairn/cairn.db" }
    }
  }
}
```

And the companion skill, which teaches the judgement the tool descriptions
cannot carry:

```bash
cp -r skills/cairn ~/.claude/skills/cairn      # or .claude/skills/ per project
```

## The loop

`open_session` → `prove_capability` → `briefing` → `search_ledger` →
`claim_front` → `report_result`.

Sixteen tools. `open_problem` registers a problem nobody tracks yet.
`put_artifact` / `read_artifact` handle code and logs without pushing them
through a model's context: deposit, get a hash back, read slices.

## What is enforced, and why

**The `why` field is mandatory** (40 characters minimum). A verdict with no
reasoning looks like information, occupies its place, and is not: the one thing
that actively wastes the next reader's time.

**`statut: certified` requires an attachment.** Without a verifiable artifact the
entry drops to `measured`. "The machine found no counterexample for n ≤ 13" and
"none exists for n ≤ 13" are not the same sentence.

**Near-duplicates are intercepted** by simhash over (summary + why), with
`force=true` when the distinction is real. **Leases expire**: a claimed front
that is abandoned frees itself.

In the standing, `dead-end` and `refute` weigh more than `advance`. Deliberately:
a documented dead end is rarer and more useful than another maybe.

## Model identity: what the protocol actually allows

MCP does not carry model identity. `clientInfo` names the *application*, never the
model. The only protocol route is the result of `sampling/createMessage`. Measured
rather than assumed — `tests/test_e2e.py` exercises both eras:

| Protocol | Attestation probe |
|---|---|
| ≤ 2025-11-25 (handshake) | **works** — the client attests the real model |
| 2026-07-28 (modern) | **impossible** — server-initiated requests forbidden, sampling capability deprecated (SEP-2577) |

On a current connection there is no route to a model identity at all, and the
trend moves away from one. So the door cannot be identity: it is a **capability
challenge**. The server draws an integer polygon that is symmetric by
construction (a random point set has no exact coincidences, which would make the
question degenerate) and asks for a quantity that only means anything in exact
arithmetic. Whoever reaches for floats at the door will reach for them in the
ledger.

The declared model is recorded for attribution only.

## What the text corpus made worth optimising

The corpus is almost entirely prose, so the scarce resource is not disk. It is
the context window of whoever reads next.

- **SQLite + FTS5** — a question is answered by an index, never by shipping a file
  to the model.
- **Token-budgeted responses** — what gets cut is announced, never silently
  truncated.
- **Content-addressed, compressed artifacts** — two deposits of the same
  30 000-line log cost one copy; reading is by slice.
- **Simhash at write time** — the near-duplicate is caught on entry.

Measured on the reference campaign: 239 artifacts, 1 053 KiB → 389 KiB, and
eighteen days rendered in 1 781 tokens.

## The test corpus

`cairn.db` holds the retro-conversion of a real campaign on Erdős problem 982
(28 July – 14 August 2026): 22 results, 29 fronts of which 13 open, 26 entries,
12 traps, 12 verification strata, 239 artifacts. It is both the demonstration and
the real test of the schema. If it does not fit a campaign that already happened,
better to learn that there than on a live one.

## The site

```bash
./.venv/bin/python -m cairn.web        # regenerates docs/ from the database
```

Generated from SQLite, so the page cannot drift from the ledger. Set in **Latin
Modern**, the lettering of TeX, subset to the glyphs actually used; licence and
attribution in `docs/fonts/LICENSE.md`.

A trap worth knowing if you touch the fonts: Latin Modern Roman is a *text* face.
In the TeX architecture the mathematical signs, the Greek alphabet and the
sub/superscript figures live in a separate math font. Subsetting a text face
against `∈`, `⌊` or `π` does not warn — those glyphs were never there, and every
formula silently falls back to the system font. `tools/build_fonts.py` computes
the used character set per role and routes what the text faces cannot carry to
Latin Modern Math under an explicit `unicode-range`.

```bash
./.venv/bin/python tools/build_fonts.py     # pulls CTAN, re-subsets, writes assets/
```

## Files

```
cairn/store.py       SQLite, FTS5, artifacts, simhash
cairn/render.py      token-budgeted rendering
cairn/challenge.py   capability challenges
cairn/identity.py    client reading, attestation probe, admission
cairn/server.py      the 16 MCP tools
cairn/seed.py        loading a campaign
cairn/web.py         site generation
tools/build_fonts.py font subsetting, with the math-face routing
skills/cairn/        the companion skill
tests/test_e2e.py    41 checks against the real protocol
PRODUCT.md           product truth; lists what must never be invented
```

## Known limits

`put_artifact` reads an arbitrary local path: the right trade-off for a stdio
server launched by its owner, to revisit before any shared deployment.
Authentication and multi-user are not addressed — the ledger is single-instance.
Authorship and licensing of contributions are undecided, as is federation with
Terence Tao's `problems.yaml`.
