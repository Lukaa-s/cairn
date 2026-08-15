"""Import the open Erdős problems as a catalogue anyone can start work on.

The public dataset at teorth/erdosproblems carries the metadata (number, status,
tags, prize, OEIS links) but not the statements, which live on erdosproblems.com.
That split is the right one and this importer keeps it: Cairn tracks *attempts*,
the canonical statement stays with the people who maintain the catalogue, and each
imported problem links out to it.

So an imported problem arrives with status `catalogued`: listed, linked, and
untouched. It becomes `open` the moment somebody files the first entry. That
distinction is the honest answer to "why is only one problem here" — hundreds are
listed, one has work in it.

Usage:  python tools/import_erdos.py [--limit 60] [--prized-only]
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cairn.store import Store  # noqa: E402

SOURCE = "https://raw.githubusercontent.com/teorth/erdosproblems/main/data/problems.yaml"
SITE = "https://www.erdosproblems.com"


def parse(text: str) -> list[dict]:
    """A deliberately small reader for this one file's shape, no YAML dependency."""
    out, cur = [], None
    for raw in text.splitlines():
        if raw.startswith("- number:"):
            if cur:
                out.append(cur)
            cur = {"number": raw.split(":", 1)[1].strip().strip('"')}
        elif cur is None:
            continue
        elif raw.startswith("  prize:"):
            cur["prize"] = raw.split(":", 1)[1].strip().strip('"')
        elif raw.startswith("  tags:"):
            cur["tags"] = re.findall(r'"([^"]+)"', raw)
        elif raw.startswith("  oeis:"):
            cur["oeis"] = re.findall(r'"([^"]+)"', raw)
        elif raw.startswith("  status:"):
            cur["_in_status"] = True
        elif raw.startswith("    state:") and cur.pop("_in_status", False):
            cur["state"] = raw.split(":", 1)[1].strip().strip('"')
        elif raw.startswith("  ") and not raw.startswith("    "):
            cur.pop("_in_status", None)
    if cur:
        out.append(cur)
    return out


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=root / "cairn.db")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--prized-only", action="store_true",
                    help="only problems carrying an Erdős prize")
    a = ap.parse_args(argv)

    print(f"  fetching {SOURCE}")
    text = urllib.request.urlopen(SOURCE, timeout=60).read().decode("utf-8", "replace")
    probs = parse(text)
    print(f"  {len(probs)} problems in the dataset")

    openish = [p for p in probs if p.get("state") == "open"]
    if a.prized_only:
        openish = [p for p in openish if p.get("prize")]

    def rank(p):
        money = int(re.sub(r"\D", "", p.get("prize") or "0") or 0)
        return (-money, int(p["number"]))

    openish.sort(key=rank)
    chosen = openish[: a.limit]
    print(f"  {len(openish)} open · importing {len(chosen)}")

    st = Store(a.db)
    added = skipped = 0
    for p in chosen:
        slug = f"erdos-{p['number']}"
        if st.problem(slug) is not None:
            skipped += 1
            continue
        bits = []
        if p.get("prize"):
            bits.append(f"Erdős prize {p['prize']}")
        if p.get("tags"):
            bits.append(", ".join(p["tags"]))
        seqs = [o for o in p.get("oeis", []) if o and o.upper() not in ("N/A", "NONE")]
        if seqs:
            bits.append("OEIS " + ", ".join(seqs))
        st.upsert_problem(
            slug=slug,
            title=f"Erdős problem {p['number']}",
            statement="",  # the canonical statement stays at the source, linked below
            source_url=f"{SITE}/{p['number']}",
            status="catalogued",
            one_liner=" · ".join(bits) or None,
        )
        added += 1
    st.close()
    print(f"  added {added}, already present {skipped}")
    print("  run `python -m cairn.sync export` to write them into ledger/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
