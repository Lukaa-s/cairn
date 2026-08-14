"""Load a campaign into the ledger.

Written for the retro-conversion of erdos982, which is both the first real corpus
and the honest test of the schema: if eighteen days of z3 strata, mpmath
certifications and refuted approaches do not fit, the schema is wrong and better
to learn that from a campaign that already happened than from a live one.

Usage:  python -m cairn.seed <seed.json> [--artifacts DIR] [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .store import Store

ARTIFACT_KINDS = {".py": "script", ".log": "log", ".jsonl": "data", ".json": "data",
                  ".pkl": "data", ".txt": "note", ".md": "note"}
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def ingest_artifacts(st: Store, directory: Path, verbose: bool = True) -> dict[str, str]:
    """Store every recognised file, returning {filename: sha256}."""
    index: dict[str, str] = {}
    raw = comp = 0
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in ARTIFACT_KINDS:
            continue
        if path.stat().st_size > MAX_ARTIFACT_BYTES or path.stat().st_size == 0:
            continue
        meta = st.put_artifact(
            path.read_bytes(), kind=ARTIFACT_KINDS[path.suffix], filename=path.name
        )
        index[path.name] = meta["sha256"]
        raw += meta["size"]
        comp += meta["stored"]
    if verbose:
        ratio = raw / comp if comp else 0
        print(f"  artefacts : {len(index)} fichiers, {raw/1024:.0f} Kio → {comp/1024:.0f} Kio "
              f"(×{ratio:.1f})")
    return index


def load(seed_path: Path, db_path: Path, artifacts_dir: Path | None) -> None:
    data = json.loads(seed_path.read_text())
    st = Store(db_path)

    art_index: dict[str, str] = {}
    if artifacts_dir and artifacts_dir.is_dir():
        art_index = ingest_artifacts(st, artifacts_dir)

    p = data["problem"]
    pid = st.upsert_problem(**p)
    slug = p["slug"]
    print(f"  problème  : {slug}")

    for s in data.get("strata", []):
        st.db.execute(
            """INSERT INTO strata(problem_id,label,status,detail,cpu_seconds,updated_at)
               VALUES(?,?,?,?,?,datetime('now'))
               ON CONFLICT(problem_id,label) DO UPDATE SET
                 status=excluded.status, detail=excluded.detail, cpu_seconds=excluded.cpu_seconds""",
            (pid, s.get("label") or f"n={s.get('n')}", s["status"], s.get("detail"),
             s.get("cpu_seconds")),
        )
    st.db.commit()

    for t in data.get("theorems", []):
        st.db.execute(
            """INSERT INTO theorems(problem_id,key,name,statement,status,proof_location,scope,created_at)
               VALUES(?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(problem_id,key) DO UPDATE SET
                 name=excluded.name, statement=excluded.statement, status=excluded.status,
                 proof_location=excluded.proof_location, scope=excluded.scope""",
            (pid, t["key"], t["name"], t["statement"], t["status"], t.get("proof_location"),
             t.get("scope")),
        )
        tid = st.db.execute(
            "SELECT id FROM theorems WHERE problem_id=? AND key=?", (pid, t["key"])
        ).fetchone()[0]
        st.index(f"theorem:{tid}", slug, "theorem", t["name"],
                 " ".join(filter(None, [t["statement"], t.get("scope")])))
    st.db.commit()

    fronts: dict[str, int] = {}
    for f in data.get("fronts", []):
        fid = st.upsert_front(
            pid, slug, key=f["key"], title=f["title"], rationale=f.get("rationale"),
            cost=f.get("cost"), gain=f.get("gain"), status=f.get("status", "open"),
            priority=f.get("priority", 100), closed_reason=f.get("closed_reason"),
            closed_at=f.get("closed_at"),
        )
        fronts[f["key"]] = fid

    for e in data.get("ledger", []):
        shas = [art_index[a] for a in e.get("artifacts", []) if a in art_index]
        st.add_entry(
            pid, slug,
            front_id=fronts.get(e.get("front_key") or ""),
            verdict=e["verdict"], statut=e["statut"], summary=e["summary"], why=e["why"],
            at=e.get("date"), contributor=e.get("contributor", "campagne-2026-07"),
            artifacts=shas,
        )

    for pf in data.get("pitfalls", []):
        st.db.execute(
            """INSERT INTO pitfalls(problem_id,title,lesson,occurrences) VALUES(?,?,?,?)
               ON CONFLICT(problem_id,title) DO UPDATE SET
                 lesson=excluded.lesson, occurrences=excluded.occurrences""",
            (pid, pf["title"], pf["lesson"], pf.get("occurrences")),
        )
    st.db.commit()

    c = st.counts(pid)
    print(f"  chargé    : {c['theorems']} théorèmes · {c['fronts_open']} fronts ouverts "
          f"({c['fronts_closed']} clos) · {c['entries']} entrées · {c['pitfalls']} pièges "
          f"· {c['strata']} strates")
    st.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Charger une campagne dans le registre Cairn.")
    ap.add_argument("seed", type=Path)
    ap.add_argument("--db", type=Path, default=Path(__file__).resolve().parent.parent / "cairn.db")
    ap.add_argument("--artifacts", type=Path, default=None)
    a = ap.parse_args(argv)
    if not a.seed.exists():
        print(f"seed introuvable : {a.seed}", file=sys.stderr)
        return 1
    load(a.seed, a.db, a.artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
