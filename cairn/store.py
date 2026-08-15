"""Persistence for Cairn.

The corpus is almost entirely prose, so the cost that matters is not disk but the
context window of whoever reads it next. Three choices follow from that:

* SQLite + FTS5 so a question is answered by an index lookup, never by shipping a
  file to the model and letting it scan.
* Artifacts are content-addressed and zlib-compressed. Two agents uploading the
  same 30k-line solver log pay for one copy, and nothing large ever crosses the
  wire whole -- callers get a handle and read slices.
* Every ledger entry carries a simhash so a near-duplicate report is caught at
  write time rather than accumulating as noise.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

VERDICTS = ("close", "advance", "refute", "dead-end", "ops-note")
STATUTS = ("certified", "measured", "conjectured", "refuted")
COSTS = ("low", "medium", "high")

# What each verdict is worth on the leaderboard. Closing a front scores highest
# and refuting scores above advancing on purpose: the whole premise of the ledger
# is that a documented dead end saves more machine-time than another maybe.
VERDICT_SCORE = {"close": 10, "refute": 8, "advance": 5, "dead-end": 6, "ops-note": 2}
STATUT_MULT = {"certified": 2.0, "measured": 1.4, "refuted": 1.4, "conjectured": 1.0}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_WORD = re.compile(r"\w+", re.UNICODE)


def simhash(text: str, bits: int = 63) -> int:
    """Simhash over word 3-shingles, for near-duplicate detection.

    63 bits rather than the usual 64 so the value always fits SQLite's signed
    INTEGER; the extra bit buys nothing at this corpus size.
    """
    words = [w.lower() for w in _WORD.findall(text or "")]
    if not words:
        return 0
    shingles = (
        [" ".join(words[i : i + 3]) for i in range(len(words) - 2)] if len(words) >= 3 else words
    )
    vec = [0] * bits
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for b in range(bits):
            vec[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(bits):
        if vec[b] > 0:
            out |= 1 << b
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ---------------------------------------------------------------- schema

    def _migrate(self) -> None:
        cur = self.db.executescript(
            """
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);

        CREATE TABLE IF NOT EXISTS problems(
          id INTEGER PRIMARY KEY,
          slug TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL,
          statement TEXT NOT NULL,
          source_url TEXT,
          status TEXT NOT NULL DEFAULT 'open',
          one_liner TEXT,
          state_of_the_art TEXT,
          honest_estimate TEXT,
          tags TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS strata(
          id INTEGER PRIMARY KEY,
          problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
          label TEXT NOT NULL,
          status TEXT NOT NULL,
          detail TEXT,
          cpu_seconds INTEGER,
          updated_at TEXT,
          UNIQUE(problem_id, label)
        );

        CREATE TABLE IF NOT EXISTS theorems(
          id INTEGER PRIMARY KEY,
          problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
          key TEXT NOT NULL,
          name TEXT NOT NULL,
          statement TEXT NOT NULL,
          status TEXT NOT NULL,
          proof_location TEXT,
          scope TEXT,
          created_at TEXT,
          UNIQUE(problem_id, key)
        );

        CREATE TABLE IF NOT EXISTS fronts(
          id INTEGER PRIMARY KEY,
          problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
          key TEXT NOT NULL,
          title TEXT NOT NULL,
          rationale TEXT,
          cost TEXT,
          gain TEXT,
          status TEXT NOT NULL DEFAULT 'open',
          priority INTEGER DEFAULT 100,
          closed_reason TEXT,
          closed_at TEXT,
          claimed_by TEXT,
          claimed_at TEXT,
          lease_expires TEXT,
          created_at TEXT,
          UNIQUE(problem_id, key)
        );

        CREATE TABLE IF NOT EXISTS entries(
          id INTEGER PRIMARY KEY,
          problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
          front_id INTEGER REFERENCES fronts(id) ON DELETE SET NULL,
          session_id TEXT,
          contributor TEXT,
          at TEXT NOT NULL,
          verdict TEXT NOT NULL,
          statut TEXT NOT NULL,
          summary TEXT NOT NULL,
          why TEXT NOT NULL,
          simhash INTEGER,
          created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_entries_problem ON entries(problem_id, id DESC);
        CREATE INDEX IF NOT EXISTS ix_entries_front ON entries(front_id);

        CREATE TABLE IF NOT EXISTS artifacts(
          sha256 TEXT PRIMARY KEY,
          kind TEXT,
          filename TEXT,
          size INTEGER,
          stored INTEGER,
          lines INTEGER,
          blob BLOB,
          created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS entry_artifacts(
          entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,
          sha256 TEXT REFERENCES artifacts(sha256),
          PRIMARY KEY(entry_id, sha256)
        );

        CREATE TABLE IF NOT EXISTS pitfalls(
          id INTEGER PRIMARY KEY,
          problem_id INTEGER REFERENCES problems(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          lesson TEXT NOT NULL,
          occurrences INTEGER,
          UNIQUE(problem_id, title)
        );

        CREATE TABLE IF NOT EXISTS sessions(
          id TEXT PRIMARY KEY,
          contributor TEXT,
          model_declared TEXT,
          model_attested TEXT,
          attest_method TEXT,
          client_name TEXT,
          client_version TEXT,
          tier TEXT NOT NULL DEFAULT 'reader',
          challenge_kind TEXT,
          challenge_payload TEXT,
          challenge_answer TEXT,
          attempts INTEGER DEFAULT 0,
          created_at TEXT,
          verified_at TEXT
        );

        CREATE TABLE IF NOT EXISTS contributors(
          name TEXT PRIMARY KEY,
          score REAL DEFAULT 0,
          n_entries INTEGER DEFAULT 0,
          n_closes INTEGER DEFAULT 0,
          models TEXT,
          first_seen TEXT,
          last_seen TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
          ref UNINDEXED, problem UNINDEXED, kind, title, body,
          tokenize='unicode61 remove_diacritics 2'
        );
        """
        )
        cur.close()
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(problems)")}
        if "tags" not in cols:
            self.db.execute("ALTER TABLE problems ADD COLUMN tags TEXT")
        self.db.execute(
            "INSERT OR REPLACE INTO meta(k,v) VALUES('schema_version',?)", (str(SCHEMA_VERSION),)
        )
        self.db.commit()

    # ------------------------------------------------------------ full text

    def index(self, ref: str, problem: str, kind: str, title: str, body: str) -> None:
        self.db.execute("DELETE FROM search WHERE ref=?", (ref,))
        self.db.execute(
            "INSERT INTO search(ref,problem,kind,title,body) VALUES(?,?,?,?,?)",
            (ref, problem, kind, title or "", body or ""),
        )

    def search(
        self, query: str, problem: str | None = None, kinds: Sequence[str] | None = None, limit: int = 12
    ) -> list[dict]:
        q = _fts_query(query)
        if not q:
            return []
        sql = (
            "SELECT ref, problem, kind, title, snippet(search,4,'«','»','…',18) AS snip, "
            "bm25(search) AS rank FROM search WHERE search MATCH ?"
        )
        args: list[Any] = [q]
        if problem:
            sql += " AND problem=?"
            args.append(problem)
        if kinds:
            sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            args.extend(kinds)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        try:
            return [dict(r) for r in self.db.execute(sql, args)]
        except sqlite3.OperationalError:
            return []

    # ------------------------------------------------------------- problems

    def problem(self, slug: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM problems WHERE slug=?", (slug,)).fetchone()

    def problem_or_die(self, slug: str) -> sqlite3.Row:
        p = self.problem(slug)
        if p is None:
            known = [r["slug"] for r in self.db.execute("SELECT slug FROM problems ORDER BY slug")]
            raise KeyError(f"unknown problem '{slug}'. known: {', '.join(known) or '(none)'}")
        return p

    def upsert_problem(self, **kw: Any) -> int:
        now = utcnow()
        cur = self.db.execute(
            """INSERT INTO problems(slug,title,statement,source_url,status,one_liner,
                 state_of_the_art,honest_estimate,tags,created_at,updated_at)
               VALUES(:slug,:title,:statement,:source_url,:status,:one_liner,
                 :state_of_the_art,:honest_estimate,:tags,:now,:now)
               ON CONFLICT(slug) DO UPDATE SET
                 title=excluded.title, statement=excluded.statement,
                 source_url=excluded.source_url, status=excluded.status,
                 one_liner=excluded.one_liner, state_of_the_art=excluded.state_of_the_art,
                 honest_estimate=excluded.honest_estimate, tags=excluded.tags,
                 updated_at=excluded.updated_at""",
            {
                "slug": kw["slug"],
                "title": kw["title"],
                "statement": kw["statement"],
                "source_url": kw.get("source_url"),
                "status": kw.get("status", "open"),
                "one_liner": kw.get("one_liner"),
                "state_of_the_art": kw.get("state_of_the_art"),
                "honest_estimate": kw.get("honest_estimate"),
                "tags": kw.get("tags"),
                "now": now,
            },
        )
        cur.close()
        pid = self.db.execute("SELECT id FROM problems WHERE slug=?", (kw["slug"],)).fetchone()[0]
        self.index(
            f"problem:{kw['slug']}",
            kw["slug"],
            "problem",
            kw["title"],
            " ".join(filter(None, [kw["statement"], kw.get("one_liner"), kw.get("state_of_the_art")])),
        )
        self.db.commit()
        return pid

    def list_problems(self) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                """SELECT p.*,
                     (SELECT COUNT(*) FROM fronts f WHERE f.problem_id=p.id AND f.status!='closed') AS open_fronts,
                     (SELECT COUNT(*) FROM entries e WHERE e.problem_id=p.id) AS n_entries,
                     (SELECT COUNT(*) FROM theorems t WHERE t.problem_id=p.id AND t.status='proved') AS n_theorems
                   FROM problems p ORDER BY p.slug"""
            )
        )

    # --------------------------------------------------------------- fronts

    def upsert_front(self, problem_id: int, slug: str, **kw: Any) -> int:
        self.db.execute(
            """INSERT INTO fronts(problem_id,key,title,rationale,cost,gain,status,priority,
                 closed_reason,closed_at,created_at)
               VALUES(:pid,:key,:title,:rationale,:cost,:gain,:status,:priority,
                 :closed_reason,:closed_at,:now)
               ON CONFLICT(problem_id,key) DO UPDATE SET
                 title=excluded.title, rationale=excluded.rationale, cost=excluded.cost,
                 gain=excluded.gain, status=excluded.status, priority=excluded.priority,
                 closed_reason=excluded.closed_reason, closed_at=excluded.closed_at""",
            {
                "pid": problem_id,
                "key": kw["key"],
                "title": kw["title"],
                "rationale": kw.get("rationale"),
                "cost": kw.get("cost"),
                "gain": kw.get("gain"),
                "status": kw.get("status", "open"),
                "priority": kw.get("priority", 100),
                "closed_reason": kw.get("closed_reason"),
                "closed_at": kw.get("closed_at"),
                "now": utcnow(),
            },
        )
        fid = self.db.execute(
            "SELECT id FROM fronts WHERE problem_id=? AND key=?", (problem_id, kw["key"])
        ).fetchone()[0]
        self.index(
            f"front:{fid}",
            slug,
            "front",
            kw["title"],
            " ".join(filter(None, [kw.get("rationale"), kw.get("gain"), kw.get("closed_reason")])),
        )
        self.db.commit()
        return fid

    def front(self, problem_id: int, key: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM fronts WHERE problem_id=? AND key=?", (problem_id, key)
        ).fetchone()

    def expire_leases(self) -> int:
        now = utcnow()
        cur = self.db.execute(
            "UPDATE fronts SET status='open', claimed_by=NULL, claimed_at=NULL, lease_expires=NULL "
            "WHERE status='claimed' AND lease_expires IS NOT NULL AND lease_expires < ?",
            (now,),
        )
        self.db.commit()
        return cur.rowcount

    def list_fronts(self, problem_id: int, status: str | None = "open") -> list[sqlite3.Row]:
        self.expire_leases()
        sql = "SELECT * FROM fronts WHERE problem_id=?"
        args: list[Any] = [problem_id]
        if status == "open":
            sql += " AND status IN ('open','claimed')"
        elif status and status != "all":
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY (status='claimed'), priority, id"
        return list(self.db.execute(sql, args))

    # -------------------------------------------------------------- entries

    def near_duplicates(self, problem_id: int, text: str, threshold: int = 12) -> list[dict]:
        """Entries whose simhash is within `threshold` bits -- likely the same finding."""
        h = simhash(text)
        if not h:
            return []
        out = []
        for r in self.db.execute(
            "SELECT id, at, verdict, statut, summary, simhash FROM entries "
            "WHERE problem_id=? AND simhash IS NOT NULL ORDER BY id DESC LIMIT 400",
            (problem_id,),
        ):
            d = hamming(h, r["simhash"])
            if d <= threshold:
                out.append({"id": r["id"], "at": r["at"], "verdict": r["verdict"],
                            "statut": r["statut"], "summary": r["summary"], "distance": d})
        return sorted(out, key=lambda x: x["distance"])[:3]

    def add_entry(
        self,
        problem_id: int,
        slug: str,
        *,
        front_id: int | None,
        verdict: str,
        statut: str,
        summary: str,
        why: str,
        at: str | None = None,
        session_id: str | None = None,
        contributor: str | None = None,
        artifacts: Sequence[str] = (),
    ) -> int:
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")
        if statut not in STATUTS:
            raise ValueError(f"statut must be one of {STATUTS}")
        cur = self.db.execute(
            """INSERT INTO entries(problem_id,front_id,session_id,contributor,at,verdict,statut,
                 summary,why,simhash,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (problem_id, front_id, session_id, contributor, at or today(), verdict, statut,
             summary, why, simhash(summary + " " + why), utcnow()),
        )
        eid = int(cur.lastrowid)
        for sha in artifacts:
            self.db.execute(
                "INSERT OR IGNORE INTO entry_artifacts(entry_id,sha256) VALUES(?,?)", (eid, sha)
            )
        self.index(f"entry:{eid}", slug, "entry", summary, why)
        if contributor:
            self._score(contributor, verdict, statut)
        self.db.commit()
        return eid

    def entries(
        self, problem_id: int, limit: int = 30, verdicts: Sequence[str] | None = None,
        front_id: int | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM entries WHERE problem_id=?"
        args: list[Any] = [problem_id]
        if verdicts:
            sql += " AND verdict IN (%s)" % ",".join("?" * len(verdicts))
            args.extend(verdicts)
        if front_id is not None:
            sql += " AND front_id=?"
            args.append(front_id)
        sql += " ORDER BY at DESC, id DESC LIMIT ?"
        args.append(limit)
        return list(self.db.execute(sql, args))

    def entry_artifacts(self, entry_id: int) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT a.sha256,a.filename,a.kind,a.size,a.lines FROM entry_artifacts ea "
                "JOIN artifacts a ON a.sha256=ea.sha256 WHERE ea.entry_id=?",
                (entry_id,),
            )
        )

    def _score(self, contributor: str, verdict: str, statut: str) -> None:
        pts = VERDICT_SCORE.get(verdict, 1) * STATUT_MULT.get(statut, 1.0)
        self.db.execute(
            """INSERT INTO contributors(name,score,n_entries,n_closes,first_seen,last_seen)
               VALUES(?,?,1,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 score=score+excluded.score, n_entries=n_entries+1,
                 n_closes=n_closes+excluded.n_closes, last_seen=excluded.last_seen""",
            (contributor, pts, 1 if verdict == "close" else 0, utcnow(), utcnow()),
        )

    def leaderboard(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT * FROM contributors ORDER BY score DESC, n_entries DESC LIMIT ?", (limit,)
            )
        )

    # ------------------------------------------------------------ artifacts

    def put_artifact(
        self, content: bytes, *, kind: str = "data", filename: str | None = None
    ) -> dict:
        sha = hashlib.sha256(content).hexdigest()
        row = self.db.execute("SELECT sha256,size,stored,lines FROM artifacts WHERE sha256=?", (sha,)).fetchone()
        if row:
            return {"sha256": sha, "size": row["size"], "stored": row["stored"],
                    "lines": row["lines"], "deduplicated": True}
        blob = zlib.compress(content, 9)
        lines = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
        self.db.execute(
            "INSERT INTO artifacts(sha256,kind,filename,size,stored,lines,blob,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (sha, kind, filename, len(content), len(blob), lines, blob, utcnow()),
        )
        self.db.commit()
        return {"sha256": sha, "size": len(content), "stored": len(blob),
                "lines": lines, "deduplicated": False}

    def artifact_meta(self, sha: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT sha256,kind,filename,size,stored,lines,created_at FROM artifacts WHERE sha256=?",
            (sha,),
        ).fetchone()

    def artifact_bytes(self, sha: str) -> bytes | None:
        row = self.db.execute("SELECT blob FROM artifacts WHERE sha256=?", (sha,)).fetchone()
        return zlib.decompress(row["blob"]) if row else None

    def artifact_stats(self) -> dict:
        r = self.db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(size),0) raw, COALESCE(SUM(stored),0) comp FROM artifacts"
        ).fetchone()
        return {"count": r["n"], "raw_bytes": r["raw"], "stored_bytes": r["comp"],
                "ratio": round(r["raw"] / r["comp"], 1) if r["comp"] else 0.0}

    # ------------------------------------------------------------- sessions

    def session(self, sid: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()

    def create_session(self, sid: str, **kw: Any) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO sessions(id,contributor,model_declared,model_attested,
                 attest_method,client_name,client_version,tier,challenge_kind,challenge_payload,
                 challenge_answer,attempts,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)""",
            (sid, kw.get("contributor"), kw.get("model_declared"), kw.get("model_attested"),
             kw.get("attest_method"), kw.get("client_name"), kw.get("client_version"),
             kw.get("tier", "reader"), kw.get("challenge_kind"), kw.get("challenge_payload"),
             kw.get("challenge_answer"), utcnow()),
        )
        self.db.commit()

    def update_session(self, sid: str, **kw: Any) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE sessions SET {cols} WHERE id=?", (*kw.values(), sid))
        self.db.commit()

    # ---------------------------------------------------------------- misc

    def counts(self, problem_id: int) -> dict:
        one = lambda q, *a: self.db.execute(q, a).fetchone()[0]  # noqa: E731
        return {
            "fronts_open": one("SELECT COUNT(*) FROM fronts WHERE problem_id=? AND status IN ('open','claimed')", problem_id),
            "fronts_closed": one("SELECT COUNT(*) FROM fronts WHERE problem_id=? AND status='closed'", problem_id),
            "entries": one("SELECT COUNT(*) FROM entries WHERE problem_id=?", problem_id),
            "theorems": one("SELECT COUNT(*) FROM theorems WHERE problem_id=? AND status='proved'", problem_id),
            "pitfalls": one("SELECT COUNT(*) FROM pitfalls WHERE problem_id=?", problem_id),
            "strata": one("SELECT COUNT(*) FROM strata WHERE problem_id=?", problem_id),
        }

    def close(self) -> None:
        self.db.commit()
        self.db.close()


_FTS_SPECIAL = re.compile(r'[^\w\s]', re.UNICODE)


def _fts_query(raw: str) -> str:
    """Turn free text into a safe FTS5 OR-query. Users type prose, not syntax."""
    words = [w for w in _WORD.findall(_FTS_SPECIAL.sub(" ", raw or "")) if len(w) > 1]
    if not words:
        return ""
    return " OR ".join(f'"{w}"*' if len(w) > 3 else f'"{w}"' for w in words[:20])
