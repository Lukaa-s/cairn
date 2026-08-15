"""The ledger as text, so that git can be the shared database.

SQLite is the wrong thing to share: two contributors who both write get a binary
conflict nobody can resolve. So the source of truth is `ledger/`, and `cairn.db`
is a cache rebuilt from it.

  ledger/problems/<slug>.json    the problem, its fronts, results, strata, traps
  ledger/entries/<slug>.jsonl    one JSON object per line, append-only

JSON Lines for the entries is the whole trick: two agents appending different
lines to the same file merge without a conflict, and an entry is never rewritten
once it is written. A campaign is then a pull request, which is how the
mathematics community already reviews contributions, and the site rebuilds from
the merge.

Artifacts stay out of git. They are large, binary and content-addressed, and a
repository is the wrong place for a hundred megabytes of solver logs; the ledger
records their hash and size so a reader knows what exists and can ask its author.

Usage:
  python -m cairn.sync export      db  -> ledger/
  python -m cairn.sync import      ledger/ -> db   (rebuilds the cache)
  python -m cairn.sync status      what differs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .store import Store, utcnow

PROBLEM_FIELDS = ("slug", "title", "statement", "source_url", "status", "one_liner",
                  "state_of_the_art", "honest_estimate")


def _rows(db, sql: str, *args) -> list[dict]:
    return [dict(r) for r in db.execute(sql, args)]


def export(db_path: Path, ledger: Path, verbose: bool = True) -> int:
    st = Store(db_path)
    (ledger / "problems").mkdir(parents=True, exist_ok=True)
    (ledger / "entries").mkdir(parents=True, exist_ok=True)
    n = 0
    for p in st.db.execute("SELECT * FROM problems ORDER BY slug"):
        pid, slug = p["id"], p["slug"]
        doc: dict[str, Any] = {k: p[k] for k in PROBLEM_FIELDS}
        doc["fronts"] = _rows(st.db,
            "SELECT key,title,rationale,cost,gain,status,priority,closed_reason,closed_at "
            "FROM fronts WHERE problem_id=? ORDER BY priority,key", pid)
        doc["results"] = _rows(st.db,
            "SELECT key,name,statement,status,proof_location,scope "
            "FROM theorems WHERE problem_id=? ORDER BY key", pid)
        doc["strata"] = _rows(st.db,
            "SELECT label,status,detail,cpu_seconds FROM strata WHERE problem_id=? "
            "ORDER BY label", pid)
        doc["traps"] = _rows(st.db,
            "SELECT title,lesson,occurrences FROM pitfalls WHERE problem_id=? ORDER BY id", pid)
        (ledger / "problems" / f"{slug}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        lines = []
        for row in st.db.execute(
            "SELECT e.at,e.verdict,e.statut,e.summary,e.why,e.contributor,f.key AS front "
            "FROM entries e LEFT JOIN fronts f ON f.id=e.front_id "
            "WHERE e.problem_id=? ORDER BY e.at, e.id", (pid,)
        ):
            rec = {k: row[k] for k in ("at", "verdict", "statut", "summary", "why",
                                       "contributor", "front") if row[k] is not None}
            arts = [
                {"sha256": a["sha256"], "name": a["filename"], "bytes": a["size"],
                 "lines": a["lines"]}
                for a in st.db.execute(
                    "SELECT a.sha256,a.filename,a.size,a.lines FROM entry_artifacts ea "
                    "JOIN artifacts a ON a.sha256=ea.sha256 "
                    "JOIN entries e ON e.id=ea.entry_id "
                    "WHERE e.problem_id=? AND e.at=? AND e.summary=?",
                    (pid, row["at"], row["summary"]))
            ]
            if arts:
                rec["artifacts"] = arts
            lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True))
        (ledger / "entries" / f"{slug}.jsonl").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        n += 1
        if verbose:
            print(f"  {slug}: {len(doc['fronts'])} fronts · {len(doc['results'])} results "
                  f"· {len(lines)} entries")
    st.close()
    return n


def import_(ledger: Path, db_path: Path, verbose: bool = True) -> int:
    st = Store(db_path)
    n = 0
    for f in sorted((ledger / "problems").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        slug = doc["slug"]
        pid = st.upsert_problem(**{k: doc.get(k) for k in PROBLEM_FIELDS
                                   if k != "status"} | {"status": doc.get("status", "open")})
        for fr in doc.get("fronts", []):
            st.upsert_front(pid, slug, **fr)
        for t in doc.get("results", []):
            st.db.execute(
                "INSERT INTO theorems(problem_id,key,name,statement,status,proof_location,"
                "scope,created_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(problem_id,key) DO UPDATE SET name=excluded.name,"
                "statement=excluded.statement,status=excluded.status,"
                "proof_location=excluded.proof_location,scope=excluded.scope",
                (pid, t["key"], t["name"], t["statement"], t["status"],
                 t.get("proof_location"), t.get("scope"), utcnow()))
            tid = st.db.execute("SELECT id FROM theorems WHERE problem_id=? AND key=?",
                                (pid, t["key"])).fetchone()[0]
            st.index(f"theorem:{tid}", slug, "theorem", t["name"], t["statement"] or "")
        for s in doc.get("strata", []):
            st.db.execute(
                "INSERT INTO strata(problem_id,label,status,detail,cpu_seconds,updated_at) "
                "VALUES(?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(problem_id,label) DO UPDATE SET status=excluded.status,"
                "detail=excluded.detail,cpu_seconds=excluded.cpu_seconds",
                (pid, s["label"], s["status"], s.get("detail"), s.get("cpu_seconds")))
        for t in doc.get("traps", []):
            st.db.execute(
                "INSERT INTO pitfalls(problem_id,title,lesson,occurrences) VALUES(?,?,?,?) "
                "ON CONFLICT(problem_id,title) DO UPDATE SET lesson=excluded.lesson,"
                "occurrences=excluded.occurrences",
                (pid, t["title"], t["lesson"], t.get("occurrences")))
        st.db.commit()

        ef = ledger / "entries" / f"{slug}.jsonl"
        if ef.exists():
            fronts = {r["key"]: r["id"] for r in st.db.execute(
                "SELECT key,id FROM fronts WHERE problem_id=?", (pid,))}
            have = {(r["at"], r["summary"]) for r in st.db.execute(
                "SELECT at,summary FROM entries WHERE problem_id=?", (pid,))}
            added = 0
            for line in ef.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if (rec.get("at"), rec.get("summary")) in have:
                    continue
                shas = [a["sha256"] for a in rec.get("artifacts", [])
                        if st.artifact_meta(a["sha256"])]
                st.add_entry(pid, slug, front_id=fronts.get(rec.get("front") or ""),
                             verdict=rec["verdict"], statut=rec["statut"],
                             summary=rec["summary"], why=rec["why"], at=rec.get("at"),
                             contributor=rec.get("contributor"), artifacts=shas)
                added += 1
            if verbose:
                print(f"  {slug}: +{added} entries")
        n += 1
    st.close()
    return n


def ensure_db(db_path: Path, ledger: Path) -> None:
    """Build the cache from the ledger when it is missing or older than the text."""
    if not ledger.is_dir():
        return
    newest = max((p.stat().st_mtime for p in ledger.rglob("*") if p.is_file()), default=0)
    if db_path.exists() and db_path.stat().st_mtime >= newest:
        return
    import_(ledger, db_path, verbose=False)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Move the ledger between text and cache.")
    ap.add_argument("action", choices=["export", "import", "status"])
    ap.add_argument("--db", type=Path, default=root / "cairn.db")
    ap.add_argument("--ledger", type=Path, default=root / "ledger")
    a = ap.parse_args(argv)

    if a.action == "export":
        print(f"db -> {a.ledger}")
        print(f"  {export(a.db, a.ledger)} problems written")
    elif a.action == "import":
        print(f"{a.ledger} -> db")
        print(f"  {import_(a.ledger, a.db)} problems loaded")
    else:
        if not a.ledger.is_dir():
            print("no ledger/ directory yet — run `cairn-sync export` first")
            return 1
        n_p = len(list((a.ledger / "problems").glob("*.json")))
        n_e = sum(len([x for x in f.read_text().splitlines() if x.strip()])
                  for f in (a.ledger / "entries").glob("*.jsonl"))
        print(f"ledger: {n_p} problems · {n_e} entries")
        print(f"cache : {'present' if a.db.exists() else 'absent, will be rebuilt on first run'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
