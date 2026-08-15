"""Turning the ledger into text that fits in someone else's context window.

Every read tool takes a token budget and honours it. That constraint is the
product: an eighteen-day campaign is a few megabytes of notes, logs and solver
output, and the whole point of Cairn is that the next agent should become
productive after reading roughly two thousand tokens of it, not after reading all
of it. So sections get weighted allocations, lists degrade gracefully, and
anything dropped is announced rather than silently cut -- a truncated briefing
that looks complete is worse than no briefing.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

# Deliberately pessimistic. French prose with LaTeX runs ~3.5 chars/token; we
# assume 3.0 so a stated budget is a ceiling we stay under, not one we overshoot.
CHARS_PER_TOKEN = 3.0


def est_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN + 0.5)


def clip(text: str | None, max_chars: int) -> str:
    """Collapse internal whitespace to one line, keeping any leading indent.

    The indent is structural here -- it is what makes a briefing section read as a
    list -- so it survives the normalisation that folds embedded newlines away.
    """
    if not text:
        return ""
    raw = str(text)
    indent = raw[: len(raw) - len(raw.lstrip(" "))]
    body = " ".join(raw.split())
    if len(indent) + len(body) <= max_chars:
        return indent + body
    cut = body[: max(1, max_chars - len(indent) - 1)]
    sp = cut.rfind(" ")
    if sp > (max_chars - len(indent)) * 0.6:
        cut = cut[:sp]
    return indent + cut.rstrip(" ,;:.") + "…"


class Section:
    """A named block of lines with a budget weight and a minimum it always keeps."""

    def __init__(self, title: str, weight: float = 1.0, keep_min: int = 0, note: str = "",
                 show_count: bool = True):
        self.title = title
        self.weight = weight
        self.keep_min = keep_min
        self.note = note
        self.show_count = show_count
        self.lines: list[str] = []
        self.total = 0

    def add(self, line: str) -> None:
        self.lines.append(line)

    def set_total(self, n: int) -> None:
        self.total = n


def compose(header: str, sections: Sequence[Section], budget_tokens: int, footer: str = "") -> str:
    """Fit sections into the budget, dropping list tails and saying so."""
    fixed = est_tokens(header) + est_tokens(footer) + sum(est_tokens(s.title) + 2 for s in sections if s.lines)
    room = max(200, budget_tokens - fixed)
    live = [s for s in sections if s.lines]
    wsum = sum(s.weight for s in live) or 1.0

    out = [header.rstrip()]
    for s in live:
        allow = max(s.keep_min, int(room * s.weight / wsum))
        kept: list[str] = []
        used = 0
        for ln in s.lines:
            t = est_tokens(ln)
            if used + t > allow and len(kept) >= s.keep_min:
                break
            kept.append(ln)
            used += t
        head = s.title
        shown, total = len(kept), s.total or len(s.lines)
        if shown < total:
            head += f"  ({shown}/{total} shown — narrow with search_ledger / list_fronts)"
        elif total and s.show_count:
            head += f"  ({total})"
        out.append("")
        out.append(head)
        if s.note:
            out.append(f"  {s.note}")
        out.extend(kept)
    if footer:
        out.append("")
        out.append(footer.rstrip())
    return "\n".join(out)


# --------------------------------------------------------------------- pieces

_VERDICT_TAG = {
    "close": "CLOSED",
    "refute": "REFUTED",
    "advance": "ADVANCE",
    "dead-end": "DEAD-END",
    "ops-note": "OPS",
}
_STATUT_TAG = {
    "certified": "certified",
    "measured": "measured",
    "conjectured": "conjectured",
    "refuted": "refuted",
}
_STARS = {1: "***", 2: "**", 3: "*"}


def front_line(f: Any, *, width: int = 150, with_key: bool = True) -> str:
    star = _STARS.get(int(f["priority"] or 100), "")
    # Campaign notes often carry their own stars in the title; priority already
    # says the same thing, so keep one source of emphasis rather than two.
    title = clip(f["title"], 90).lstrip("★ ").strip()
    bits = []
    if with_key:
        bits.append(f"[{f['key']}]")
    if star:
        bits.append(star)
    bits.append(title)
    tail = []
    if f["cost"]:
        tail.append(f"cost {f['cost']}")
    if f["status"] == "claimed" and f["claimed_by"]:
        tail.append(f"HELD by {f['claimed_by']} until {(f['lease_expires'] or '')[:16]}")
    if f["status"] == "closed":
        tail.append("CLOSED")
    line = "  • " + " ".join(bits)
    if tail:
        line += "  — " + " · ".join(tail)
    return clip(line, width)


def entry_line(e: Any, *, width: int = 190) -> str:
    tag = _VERDICT_TAG.get(e["verdict"], e["verdict"].upper())
    st = _STATUT_TAG.get(e["statut"], e["statut"])
    body = clip(e["summary"], 110)
    why = clip(e["why"], 90)
    line = f"  {e['at']} · {tag}/{st} · {body}"
    if why:
        line += f" — {why}"
    return clip(line, width)


def theorem_line(t: Any, *, width: int = 170) -> str:
    mark = {"proved": "+", "conjectured": "?", "refuted": "x"}.get(t["status"], "-")
    line = f"  {mark} {t['name']} — {clip(t['statement'], 120)}"
    if t["status"] == "proved" and t["proof_location"]:
        line += f"  [{clip(t['proof_location'], 40)}]"
    return clip(line, width)


def strata_line(rows: Iterable[Any]) -> str:
    bits = []
    for r in rows:
        mark = {"closed": "+", "partial": "~", "open": "-"}.get(r["status"], "-")
        bits.append(f"{r['label']}{mark}")
    return "  " + " ".join(bits) + "     (+ closed · ~ partial · - open)"


def briefing(store, slug: str, budget_tokens: int = 1800) -> str:
    """The tool that justifies the whole project: campaign state, compressed."""
    p = store.problem_or_die(slug)
    pid = p["id"]
    c = store.counts(pid)
    store.expire_leases()

    header = (
        f"CAIRN — BRIEFING {p['slug']}   (budget ~{budget_tokens} tok)\n"
        f"{p['title']}\n"
        f"{clip(p['statement'], 700)}\n"
        + (f"\nSTATE IN ONE SENTENCE\n  {clip(p['one_liner'], 500)}\n" if p["one_liner"] else "")
        + (f"\nHONEST ESTIMATE\n  {clip(p['honest_estimate'], 420)}\n" if p["honest_estimate"] else "")
        + f"\nCounters: {c['theorems']} results · {c['fronts_open']} fronts open "
        f"({c['fronts_closed']}  closed) · {c['entries']} entries · {c['pitfalls']} traps"
    )

    secs: list[Section] = []

    strata = list(store.db.execute(
        "SELECT * FROM strata WHERE problem_id=? ORDER BY CAST(REPLACE(label,'n=','') AS INTEGER), label",
        (pid,),
    ))
    if strata:
        n_closed = sum(1 for r in strata if r["status"] == "closed")
        s = Section(f"MACHINE-VERIFIED — {n_closed}/{len(strata)} strata closed",
                    weight=0.7, keep_min=1, show_count=False)
        s.add(strata_line(strata))
        for r in strata:
            if r["status"] != "closed" and r["detail"]:
                s.add(clip(f"    {r['label']} : {r['detail']}", 150))
        secs.append(s)

    th = list(store.db.execute(
        "SELECT * FROM theorems WHERE problem_id=? ORDER BY (status!='proved'), key", (pid,)
    ))
    if th:
        s = Section("ESTABLISHED — do not re-prove", weight=1.6, keep_min=2)
        for t in th:
            s.add(theorem_line(t))
        s.set_total(len(th))
        secs.append(s)

    dead = store.entries(pid, limit=40, verdicts=("close", "refute", "dead-end"))
    if dead:
        s = Section(
            "DEAD ZONES — do not redo",
            weight=2.2,
            keep_min=3,
            note="(the field after the dash is the WHY: that is what saves you time)",
        )
        for e in dead:
            s.add(entry_line(e))
        s.set_total(len(dead))
        secs.append(s)

    pit = list(store.db.execute(
        "SELECT * FROM pitfalls WHERE problem_id=? ORDER BY COALESCE(occurrences,0) DESC, id", (pid,)
    ))
    if pit:
        s = Section("TRAPS — already paid for by somebody", weight=1.0, keep_min=2)
        for r in pit:
            occ = f" ({r['occurrences']}×)" if r["occurrences"] else ""
            s.add(clip(f"  ! {r['title']}{occ} -> {r['lesson']}", 190))
        s.set_total(len(pit))
        secs.append(s)

    fronts = store.list_fronts(pid, "open")
    if fronts:
        s = Section("OPEN FRONTS — ranked by chance of settling over cost", weight=2.4, keep_min=3)
        for f in fronts:
            s.add(front_line(f))
        s.set_total(len(fronts))
        secs.append(s)

    footer = (
        "PROTOCOL\n"
        "  1. search_ledger(problem, \"<your idea>\") BEFORE starting. Half the ideas that\n"
        "     feel new are already in the dead zones, with the reason.\n"
        "  2. claim_front(problem, front) so two agents do not burn the same compute.\n"
        "  3. report_result(...) at boundaries, not at the end, and especially when it\n"
        "     failed: verdict + statut + the WHY. A documented dead end is worth more\n"
        "     than a vague result.\n"
        "  4. put_artifact(...) for code and logs; they never cross your context, only\n"
        "     handles do."
    )
    return compose(header, secs, budget_tokens, footer)
