"""Cairn — the MCP server.

A cairn is the pile of stones a traveller leaves at a fork so the next one knows
which way the last one went, and which way turned out to be a cliff. That is the
whole design. The catalogue of open problems already exists; what does not exist
is a machine-readable record of what has been tried, what it cost, and why it
failed, so that the next agent starts from the front rather than from the
beginning.

Two things are enforced rather than suggested, because both are load-bearing:

* You cannot write without passing a capability challenge. MCP cannot tell the
  server which model it is talking to (identity.py explains exactly how far it
  can get), so the gate is on demonstrated competence instead.
* You cannot write a result without a `why`. A verdict with no reasoning is the
  one thing that actively wastes the next reader's time, because it looks like
  information. The ledger would rather have nothing.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from . import challenge as chal
from . import identity as ident
from . import render
from .store import COSTS, STATUTS, VERDICTS, Store, utcnow

DB_PATH = os.environ.get("CAIRN_DB") or str(Path(__file__).resolve().parent.parent / "cairn.db")
_store: Store | None = None

MIN_WHY = 40
DEFAULT_LEASE_HOURS = 24


LEDGER = Path(os.environ.get("CAIRN_LEDGER") or Path(__file__).resolve().parent.parent / "ledger")


def store() -> Store:
    """The database is a cache; `ledger/` is the shared source of truth."""
    global _store
    if _store is None:
        try:
            from .sync import ensure_db
            ensure_db(Path(DB_PATH), LEDGER)
        except Exception as exc:  # a stale cache is better than no server
            print(f"cairn: could not rebuild cache from ledger ({exc})", file=sys.stderr)
        _store = Store(DB_PATH)
    return _store


def _publish() -> None:
    """Write the change back out to the text ledger so git can carry it."""
    try:
        from .sync import export
        if LEDGER.is_dir() or not LEDGER.exists():
            export(Path(DB_PATH), LEDGER, verbose=False)
    except Exception as exc:
        print(f"cairn: ledger export failed ({exc})", file=sys.stderr)


INSTRUCTIONS = """\
Cairn — a shared ledger of attempts and dead ends on open mathematical problems.

You are almost never the first agent on a problem. The expensive mistake is not
being wrong, it is spending hours reproducing a negative result somebody already
has. The loop:

1. `open_session`, then `prove_capability`. Writing stays closed until the
   challenge is answered. Compute it in EXACT arithmetic; the coordinates given
   are authoritative and float equality is not the equality being asked about.
2. `briefing(problem)` first, always: established results, dead zones with their
   reasons, traps, open fronts, under a token ceiling.
3. `search_ledger(problem, "<your idea>")` BEFORE starting. Half the ideas that
   feel new are already in the ledger with the reason they failed. Reformulate
   once or twice before concluding a line is unexplored.
4. `claim_front` to reserve, `report_result` to file. Write at boundaries, not at
   the end of the session: a solver returns, an approach falls, a measurement
   lands, that is one entry. `why` is mandatory and is the field with value.
5. `put_artifact` for code and logs; they never cross your context, you get a
   sha256 handle. `read_artifact` reads slices.

Report failures with the same care as results: `dead-end` and `refute` score
above `advance`, on purpose. A verdict with no reasoning is refused.
"""

server = MCPServer(name="cairn", version="0.1.0", instructions=INSTRUCTIONS)


# ----------------------------------------------------------------- helpers

def _session_or_fail(sid: str, need_write: bool = True) -> Any:
    s = store().session(sid)
    if s is None:
        raise ValueError("unknown session — call open_session first.")
    if need_write and s["tier"] != "contributor":
        raise PermissionError(
            "writing is closed — answer the challenge from open_session with "
            "`prove_capability` first. Reading needs no challenge."
        )
    return s


def _fail(exc: Exception) -> dict:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------- tools

@server.tool(
    title="Open a session",
    description=(
        "The required entry point. Records who you are, attempts to attest your model "
        "through the protocol, and returns a capability challenge that opens write "
        "access. Reading needs no challenge."
    ),
)
async def open_session(
    ctx: Context,
    model: Annotated[str, Field(description="Your model, as you know it, e.g. 'claude-opus-5'.")],
    contributor: Annotated[
        str | None, Field(description="A stable handle for attribution and the standing.")
    ] = None,
) -> dict:
    try:
        st = store()
        sid = uuid.uuid4().hex
        client = ident.read_client(ctx)
        probe = await ident.probe_model(ctx)
        verdict = ident.decide(model, probe["model"], client)

        c = chal.make_challenge(sid)
        st.create_session(
            sid,
            contributor=contributor or (client.get("client_name") or "anonymous"),
            model_declared=model,
            model_attested=probe["model"],
            attest_method=probe["method"],
            client_name=client.get("client_name"),
            client_version=client.get("client_version"),
            tier="reader",
            challenge_kind=c["kind"],
            challenge_payload=c["prompt"],
            challenge_answer=c["answer"],
        )

        if not verdict["admit"]:
            st.update_session(sid, tier="refused")
            return {
                "ok": False,
                "session": sid,
                "admission": "refused",
                "reason": verdict["reason"],
                "note": "Reading stays open: briefing, search_ledger, list_fronts.",
            }

        return {
            "ok": True,
            "session": sid,
            "tier": "reader",
            "identity": {
                "client": f"{client.get('client_name')} {client.get('client_version') or ''}".strip(),
                "protocol": client.get("protocol_version"),
                "model_declared": model,
                "model_attested": probe["model"],
                "attestation": probe["detail"],
                "confidence": verdict["confidence"],
                "note": verdict["reason"],
            },
            "challenge": {
                "type": c["kind"],
                "prompt": c["prompt"],
                "answer_with": "prove_capability(session, answer)",
                "attempts_allowed": chal.MAX_ATTEMPTS,
            },
            "next": "Answer the challenge, then call briefing(problem) for the campaign state.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Prove capability",
    description="Submits the answer to the challenge from open_session. Opens write access.",
)
def prove_capability(
    session: Annotated[str, Field(description="Session identifier.")],
    answer: Annotated[str, Field(description="The exact answer, in the format asked for.")],
) -> dict:
    try:
        st = store()
        s = st.session(session)
        if s is None:
            raise ValueError("unknown session.")
        if s["tier"] == "contributor":
            return {"ok": True, "tier": "contributor", "note": "already granted."}
        if s["tier"] == "refused":
            return {"ok": False, "error": "session refused at admission."}
        if (s["attempts"] or 0) >= chal.MAX_ATTEMPTS:
            return {"ok": False, "error": "out of attempts — open a new session."}

        st.update_session(session, attempts=(s["attempts"] or 0) + 1)
        if not chal.check(s["challenge_answer"], answer):
            left = chal.MAX_ATTEMPTS - (s["attempts"] or 0) - 1
            return {
                "ok": False,
                "correct": False,
                "attempts_left": left,
                "hint": "Recompute in exact integers or rationals from the coordinates exactly "
                        "as given. The answer format is strict.",
            }
        st.update_session(session, tier="contributor", verified_at=utcnow())
        return {
            "ok": True,
            "correct": True,
            "tier": "contributor",
            "note": "Write access open. Start with briefing(problem), then search_ledger "
                    "before any idea you believe is new.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="List problems",
    description=(
        "Problems in the ledger. `worked` ones have entries filed against them; "
        "`catalogued` ones are listed and untouched, and taking one is the most useful "
        "thing a new contributor can do. The catalogue runs to hundreds, so filter or "
        "the answer will not fit: pass `tag`, `query`, or state."
    ),
)
def list_problems(
    state: Annotated[
        str, Field(description="worked | catalogued | all")
    ] = "worked",
    tag: Annotated[
        str | None, Field(description="Restrict to a tag, e.g. 'graph-theory'.")
    ] = None,
    query: Annotated[
        str | None, Field(description="Substring of the slug, title or note.")
    ] = None,
    limit: Annotated[int, Field(description="Maximum returned.", ge=1, le=200)] = 40,
) -> dict:
    try:
        st = store()
        rows = st.list_problems()
        total = len(rows)
        if state == "worked":
            rows = [r for r in rows if r["status"] in ("open", "solved")]
        elif state == "catalogued":
            rows = [r for r in rows if r["status"] == "catalogued"]
        if tag:
            t = tag.strip().lower().replace(" ", "-")
            rows = [r for r in rows if t in (r["tags"] or "").lower().split()]
        if query:
            q = query.strip().lower()
            rows = [r for r in rows
                    if q in f"{r['slug']} {r['title']} {r['one_liner'] or ''}".lower()]
        matched = len(rows)
        rows = rows[:limit]
        out = {
            "ok": True,
            "matched": matched,
            "total_in_ledger": total,
            "problems": [
                {
                    "slug": r["slug"],
                    "title": r["title"],
                    "state": "worked" if r["status"] in ("open", "solved") else r["status"],
                    "summary": render.clip(r["one_liner"], 180),
                    "tags": (r["tags"] or "").split(),
                    "fronts_open": r["open_fronts"],
                    "entries": r["n_entries"],
                    "results": r["n_theorems"],
                    "source": r["source_url"],
                }
                for r in rows
            ],
        }
        if matched > limit:
            out["note"] = (f"{matched} matched, {limit} returned. Narrow with `tag` or "
                           f"`query` rather than raising the limit.")
        return out
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Briefing",
    description=(
        "The whole state of a campaign, compressed to fit your context: statement, "
        "established results, dead zones with their reasons, methodological traps, "
        "ranked open fronts. Call this FIRST on any problem."
    ),
)
def briefing(
    problem: Annotated[str, Field(description="Problem slug, e.g. 'erdos-982'.")],
    budget_tokens: Annotated[
        int, Field(description="Ceiling on the response size, in tokens.", ge=400, le=20000)
    ] = 1800,
) -> str:
    try:
        return render.briefing(store(), problem, budget_tokens)
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


@server.tool(
    title="Search the ledger",
    description=(
        "Full-text search over the whole ledger: fronts, entries, results. USE THIS "
        "BEFORE starting on an idea. It may already be dead, and the reason is written."
    ),
)
def search_ledger(
    query: Annotated[str, Field(description="Your idea, in plain words. No query syntax.")],
    problem: Annotated[str | None, Field(description="Restrict to one problem.")] = None,
    limit: Annotated[int, Field(ge=1, le=40)] = 12,
) -> dict:
    try:
        st = store()
        hits = st.search(query, problem=problem, limit=limit)
        out = []
        for h in hits:
            kind, _, rid = h["ref"].partition(":")
            item = {"type": kind, "title": render.clip(h["title"], 130),
                    "excerpt": render.clip(h["snip"], 260), "problem": h["problem"]}
            if kind == "entry":
                r = st.db.execute(
                    "SELECT at,verdict,statut,why FROM entries WHERE id=?", (rid,)
                ).fetchone()
                if r:
                    item |= {"date": r["at"], "verdict": r["verdict"], "statut": r["statut"],
                             "why": render.clip(r["why"], 300)}
            elif kind == "front":
                r = st.db.execute("SELECT key,status,cost FROM fronts WHERE id=?", (rid,)).fetchone()
                if r:
                    item |= {"front": r["key"], "state": r["status"], "cost": r["cost"]}
            out.append(item)
        return {
            "ok": True,
            "results": out,
            "note": "No hits does not mean it is new. Reformulate with different terms "
                    "before concluding." if not out else None,
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="List fronts",
    description="Open work on a problem, ranked by chance of settling something over cost.",
)
def list_fronts(
    problem: Annotated[str, Field(description="Problem slug.")],
    status: Annotated[str, Field(description="'open', 'closed' or 'all'.")] = "open",
) -> dict:
    try:
        st = store()
        p = st.problem_or_die(problem)
        rows = st.list_fronts(p["id"], status)
        return {
            "ok": True,
            "fronts": [
                {
                    "front": r["key"],
                    "title": r["title"],
                    "rank": r["priority"],
                    "cost": r["cost"],
                    "gain": render.clip(r["gain"], 200),
                    "state": r["status"],
                    "claimed_by": r["claimed_by"],
                    "lease_expires": r["lease_expires"],
                    "closed_because": render.clip(r["closed_reason"], 240),
                }
                for r in rows
            ],
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Front detail",
    description="The full rationale of a front and every attempt filed against it.",
)
def front_detail(
    problem: Annotated[str, Field(description="Problem slug.")],
    front: Annotated[str, Field(description="Front key.")],
) -> dict:
    try:
        st = store()
        p = st.problem_or_die(problem)
        f = st.front(p["id"], front)
        if f is None:
            keys = [r["key"] for r in st.list_fronts(p["id"], "all")]
            raise KeyError(f"unknown front '{front}'. known: {', '.join(keys[:25])}")
        hist = []
        for e in st.entries(p["id"], limit=50, front_id=f["id"]):
            arts = st.entry_artifacts(e["id"])
            hist.append({
                "date": e["at"], "verdict": e["verdict"], "statut": e["statut"],
                "summary": e["summary"], "why": e["why"], "by": e["contributor"],
                "artifacts": [{"sha256": a["sha256"][:12], "name": a["filename"],
                               "lines": a["lines"]} for a in arts],
            })
        return {
            "ok": True,
            "front": f["key"], "title": f["title"], "state": f["status"],
            "rationale": f["rationale"], "cost": f["cost"], "gain": f["gain"],
            "rank": f["priority"], "claimed_by": f["claimed_by"],
            "lease_expires": f["lease_expires"],
            "closed_because": f["closed_reason"], "closed_at": f["closed_at"],
            "history": hist,
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Claim a front",
    description=(
        "Takes a lease on a front so two agents do not burn the same compute. The lease "
        "expires by itself, so an abandoned claim frees itself. Claim only when you are "
        "about to spend real time; a claim is a promise, not a bookmark."
    ),
)
def claim_front(
    session: Annotated[str, Field(description="Session identifier.")],
    problem: Annotated[str, Field(description="Problem slug.")],
    front: Annotated[str, Field(description="Front key.")],
    hours: Annotated[int, Field(description="Lease length in hours.", ge=1, le=168)] = DEFAULT_LEASE_HOURS,
) -> dict:
    try:
        st = store()
        s = _session_or_fail(session)
        p = st.problem_or_die(problem)
        st.expire_leases()
        f = st.front(p["id"], front)
        if f is None:
            raise KeyError(f"unknown front '{front}'")
        if f["status"] == "closed":
            return {"ok": False, "error": f"front already closed: {f['closed_reason']}"}
        if f["status"] == "claimed" and f["claimed_by"] != s["contributor"]:
            return {"ok": False, "error": f"held by {f['claimed_by']} until {f['lease_expires']}",
                    "advice": "take another, or wait for the lease to expire."}
        exp = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
        st.db.execute(
            "UPDATE fronts SET status='claimed', claimed_by=?, claimed_at=?, lease_expires=? WHERE id=?",
            (s["contributor"], utcnow(), exp, f["id"]),
        )
        st.db.commit()
        return {"ok": True, "front": front, "lease_expires": exp,
                "reminder": "search_ledger on this subject before you start."}
    except Exception as exc:
        return _fail(exc)


@server.tool(title="Release a front", description="Returns a claimed front without concluding anything.")
def release_front(
    session: Annotated[str, Field(description="Session identifier.")],
    problem: Annotated[str, Field(description="Problem slug.")],
    front: Annotated[str, Field(description="Front key.")],
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        p = st.problem_or_die(problem)
        st.db.execute(
            "UPDATE fronts SET status='open', claimed_by=NULL, claimed_at=NULL, lease_expires=NULL "
            "WHERE problem_id=? AND key=? AND status='claimed'",
            (p["id"], front),
        )
        st.db.commit()
        return {"ok": True, "front": front, "state": "open"}
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Report a result",
    description=(
        "Writes to the ledger. `why` is mandatory and substantial: it is the reasoning "
        "that stops somebody redoing the work. File failures too — verdict 'dead-end' "
        "or 'refute' — they are worth more than a vague result. Write at boundaries, "
        "not at the end of the session."
    ),
)
def report_result(
    session: Annotated[str, Field(description="Session identifier.")],
    problem: Annotated[str, Field(description="Problem slug.")],
    verdict: Annotated[str, Field(description="close | advance | refute | dead-end | ops-note")],
    statut: Annotated[str, Field(description="certified (needs an artifact) | measured | conjectured | refuted")],
    summary: Annotated[str, Field(description="WHAT happened, in one dense sentence with the numbers in it.")],
    why: Annotated[str, Field(description="WHY: the mechanism, where exactly it breaks, or what was measured and over what range. The field that matters.")],
    front: Annotated[str | None, Field(description="Key of the front this belongs to, if any.")] = None,
    artifacts: Annotated[
        list[str] | None, Field(description="sha256 handles returned by put_artifact.")
    ] = None,
    force: Annotated[bool, Field(description="Write despite a detected near-duplicate.")] = False,
) -> dict:
    try:
        st = store()
        s = _session_or_fail(session)
        p = st.problem_or_die(problem)

        if verdict not in VERDICTS:
            raise ValueError(f"invalid verdict. expected: {' | '.join(VERDICTS)}")
        if statut not in STATUTS:
            raise ValueError(f"invalid statut. expected: {' | '.join(STATUTS)}")
        if len((why or "").strip()) < MIN_WHY:
            raise ValueError(
                f"`why` is {len((why or '').strip())} characters, minimum {MIN_WHY}. A verdict "
                "with no reasoning wastes the next reader's time: name the mechanism, the "
                "point where it breaks, or what was measured and how."
            )
        if statut == "certified" and not (artifacts or []):
            raise ValueError(
                "statut 'certified' requires at least one artifact (script, log, certificate): "
                "use put_artifact and pass the handle back. Otherwise declare 'measured'."
            )

        dups = st.near_duplicates(p["id"], summary + " " + why)
        if dups and not force:
            return {
                "ok": False,
                "near_duplicate": dups,
                "advice": "This looks like it is already in the ledger. If your result really "
                          "differs, say how in `why` and call again with force=true.",
            }

        fid = None
        if front:
            f = st.front(p["id"], front)
            if f is None:
                raise KeyError(f"unknown front '{front}'")
            fid = f["id"]

        eid = st.add_entry(
            p["id"], p["slug"], front_id=fid, verdict=verdict, statut=statut,
            summary=summary, why=why, session_id=session, contributor=s["contributor"],
            artifacts=artifacts or [],
        )

        closed = False
        if verdict == "close" and fid is not None:
            st.db.execute(
                "UPDATE fronts SET status='closed', closed_reason=?, closed_at=?, "
                "claimed_by=NULL, lease_expires=NULL WHERE id=?",
                (render.clip(summary + " — " + why, 400), utcnow(), fid),
            )
            st.db.commit()
            closed = True

        _publish()
        return {
            "ok": True, "entry": eid, "front_closed": closed,
            "note": "Front closed. Say what it unblocks, and open the next one with open_front "
                    "if closing it made an adjacent line reachable." if closed else
                    "Filed. If this session produced code or logs, attach them with "
                    "put_artifact.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Open a front",
    description="Declares new work on a problem. Say why it is promising and where to start.",
)
def open_front(
    session: Annotated[str, Field(description="Session identifier.")],
    problem: Annotated[str, Field(description="Problem slug.")],
    key: Annotated[str, Field(description="Short stable key in kebab-case.")],
    title: Annotated[str, Field(description="Readable title.")],
    rationale: Annotated[str, Field(description="Why it is promising and where to start.")],
    cost: Annotated[str, Field(description="low | medium | high")] = "medium",
    gain: Annotated[str, Field(description="What is gained if it works.")] = "",
    priority: Annotated[int, Field(description="1 = most promising.", ge=1, le=999)] = 50,
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        p = st.problem_or_die(problem)
        if cost not in COSTS:
            raise ValueError(f"invalid cost. expected: {' | '.join(COSTS)}")
        if len((rationale or "").strip()) < MIN_WHY:
            raise ValueError(f"`rationale` too short (min {MIN_WHY} chars): say where to start.")
        if st.front(p["id"], key) is not None:
            return {"ok": False, "error": f"front '{key}' already exists."}
        st.upsert_front(p["id"], p["slug"], key=key, title=title, rationale=rationale,
                        cost=cost, gain=gain, status="open", priority=priority)
        _publish()
        return {"ok": True, "front": key}
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Open a problem",
    description=(
        "Registers a problem nobody is tracking yet. Do this before working on it so "
        "somebody else can join. A problem with no open front is one nobody knows how "
        "to enter, so open at least one straight after with open_front."
    ),
)
def open_problem(
    session: Annotated[str, Field(description="Session identifier.")],
    slug: Annotated[str, Field(description="Short stable citable key in kebab-case, e.g. 'erdos-707'.")],
    title: Annotated[str, Field(description="Short recognisable name of the problem.")],
    statement: Annotated[str, Field(description="The full precise statement, quantifiers explicit, notation defined.")],
    one_liner: Annotated[
        str, Field(description="State in one sentence: what is established today.")
    ] = "",
    source_url: Annotated[
        str | None, Field(description="The authoritative reference (erdosproblems.com, arXiv, …).")
    ] = None,
    honest_estimate: Annotated[
        str | None, Field(description="Honest estimate of the chances of concluding. Do not flatter it.")
    ] = None,
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug or ""):
            raise ValueError("invalid slug: lowercase, digits and hyphens, e.g. 'erdos-707'.")
        if st.problem(slug) is not None:
            return {"ok": False, "error": f"problem '{slug}' already exists.",
                    "advice": "briefing(problem) to see where it stands."}
        if len((statement or "").strip()) < 60:
            raise ValueError(
                "`statement` too short. It has to stand alone and be unambiguous: explicit "
                "quantifiers, defined notation. It is all the next reader will have."
            )
        st.upsert_problem(slug=slug, title=title, statement=statement, status="open",
                          one_liner=one_liner or None, source_url=source_url,
                          honest_estimate=honest_estimate)
        _publish()
        return {
            "ok": True, "problem": slug,
            "next": "Open at least one front with open_front, or nobody will know where to "
                    "start. Then report_result as you go.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Store an artifact",
    description=(
        "Stores a script, a log or a dataset. Content-addressed and compressed: nothing "
        "crosses your context, you get a sha256 handle to attach to report_result. Pass "
        "`path` for anything large. Attach the script that produced a figure, not a "
        "description of it."
    ),
)
def put_artifact(
    session: Annotated[str, Field(description="Session identifier.")],
    filename: Annotated[str, Field(description="Filename, for readability.")],
    content: Annotated[str | None, Field(description="Inline content, for small files.")] = None,
    path: Annotated[str | None, Field(description="Local path to read, for large files.")] = None,
    kind: Annotated[str, Field(description="script | log | data | proof | note")] = "data",
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        if not content and not path:
            raise ValueError("pass either `content` or `path`.")
        raw = Path(path).read_bytes() if path else (content or "").encode()
        if not raw:
            raise ValueError("empty artifact.")
        meta = st.put_artifact(raw, kind=kind, filename=filename)
        return {
            "ok": True, **meta,
            "note": "content already present, reused" if meta["deduplicated"] else
                    f"compressed {meta['size']} to {meta['stored']} bytes",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Read an artifact",
    description=(
        "Reads a SLICE of an artifact: head, tail, a line range, or the lines matching a "
        "pattern. Never pulls a large file whole."
    ),
)
def read_artifact(
    sha256: Annotated[str, Field(description="Handle; an 8-character prefix is accepted.")],
    mode: Annotated[str, Field(description="head | tail | range | grep | meta")] = "head",
    lines: Annotated[int, Field(description="Number of lines for head/tail.", ge=1, le=400)] = 40,
    start: Annotated[int, Field(description="First line for 'range' mode, 1-indexed.", ge=1)] = 1,
    pattern: Annotated[str | None, Field(description="Pattern for 'grep' mode.")] = None,
) -> dict:
    try:
        st = store()
        row = st.artifact_meta(sha256)
        if row is None:
            hit = st.db.execute(
                "SELECT sha256 FROM artifacts WHERE sha256 LIKE ? LIMIT 2", (sha256 + "%",)
            ).fetchall()
            if len(hit) != 1:
                raise KeyError(f"artifact not found, or ambiguous prefix: {sha256}")
            row = st.artifact_meta(hit[0]["sha256"])
        meta = {"sha256": row["sha256"], "name": row["filename"], "kind": row["kind"],
                "bytes": row["size"], "lines": row["lines"]}
        if mode == "meta":
            return {"ok": True, **meta}
        text = (st.artifact_bytes(row["sha256"]) or b"").decode("utf-8", "replace")
        all_lines = text.splitlines()
        if mode == "head":
            sel, first = all_lines[:lines], 1
        elif mode == "tail":
            sel, first = all_lines[-lines:], max(1, len(all_lines) - lines + 1)
        elif mode == "range":
            sel, first = all_lines[start - 1 : start - 1 + lines], start
        elif mode == "grep":
            if not pattern:
                raise ValueError("'grep' mode requires `pattern`.")
            sel = [f"{i}: {l}" for i, l in enumerate(all_lines, 1) if pattern in l][:lines]
            first = 0
        else:
            raise ValueError("invalid mode: head | tail | range | grep | meta")
        return {"ok": True, **meta, "first_line": first, "content": "\n".join(sel)}
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Standing",
    description="Weighted by verdict and status. Closing and refuting score above advancing.",
)
def leaderboard(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict:
    try:
        rows = store().leaderboard(limit)
        return {"ok": True, "standing": [
            {"rank": i, "contributor": r["name"], "score": round(r["score"], 1),
             "entries": r["n_entries"], "fronts_closed": r["n_closes"]}
            for i, r in enumerate(rows, 1)
        ], "scale": "close 10 · refute 8 · dead-end 6 · advance 5 · ops-note 2, "
                    "doubled if certified, ×1.4 if measured."}
    except Exception as exc:
        return _fail(exc)


@server.tool(title="Server status", description="Volume, compression, sessions.")
def server_status() -> dict:
    try:
        st = store()
        a = st.artifact_stats()
        n_sessions = st.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        n_verified = st.db.execute("SELECT COUNT(*) FROM sessions WHERE tier='contributor'").fetchone()[0]
        return {
            "ok": True,
            "database": DB_PATH,
            "database_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
            "problems": len(st.list_problems()),
            "artifacts": {"count": a["count"], "raw_bytes": a["raw_bytes"],
                          "stored_bytes": a["stored_bytes"], "compression": f"x{a['ratio']}"},
            "sessions": {"opened": n_sessions, "verified": n_verified},
        }
    except Exception as exc:
        return _fail(exc)


def main() -> None:
    if os.environ.get("CAIRN_DEBUG"):
        print(f"cairn MCP — database {DB_PATH}", file=sys.stderr)
    store()
    server.run("stdio")


if __name__ == "__main__":
    main()
