"""Build the site's Latin Modern subsets from the pristine CTAN sources.

The trap this script exists to avoid: Latin Modern Roman is a *text* font. In the
TeX architecture the mathematical signs, the Greek alphabet and the sub/superscript
figures live in a separate math font, exactly as Computer Modern split them. Subset
a text face against a character set containing ∈, ⌊, ℝ or π and the glyphs are not
dropped with a warning — they were never there, so the page silently falls out of
Latin Modern into whatever the system offers, and the mathematics on a mathematics
journal ends up set in DejaVu.

So the roles are computed, not assumed: every character the built pages actually
use is tested against each source face, and whatever the text faces cannot carry is
routed to Latin Modern Math under an explicit unicode-range.

Verbatim blocks are deliberately not routed to the math face: a proportional glyph
inside a monospaced solver log breaks the column alignment that made the log worth
reading. Those fall to a monospaced system fallback instead.

Usage:  python tools/build_fonts.py [--html docs] [--out .impeccable/lmfonts.json]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

CTAN_TEXT = "https://mirrors.ctan.org/fonts/lm/fonts/opentype/public/lm"
CTAN_MATH = "https://mirrors.ctan.org/fonts/lm-math/opentype"

SOURCES = {
    "lmr": (CTAN_TEXT, "lmroman10-regular"),
    "lmb": (CTAN_TEXT, "lmroman10-bold"),
    "lmi": (CTAN_TEXT, "lmroman10-italic"),
    "lmm": (CTAN_TEXT, "lmmono10-regular"),
    "lmc": (CTAN_TEXT, "lmromancaps10-regular"),
    "lmmath": (CTAN_MATH, "latinmodern-math"),
}

# Always carried even when a given build happens not to use them, so that adding a
# ledger entry does not silently produce a tofu.
ALWAYS = (
    "".join(chr(c) for c in range(0x20, 0x7F))
    + "".join(chr(c) for c in range(0xA0, 0x180))
    + "—–…‘’“”«»‰†‡§¶×·•‹›′″  "
    + "≤≥≠≈≡≪≫⌊⌋⌈⌉∈∉∋⊂⊆⊃⊇∑∏∫√∞±∓∀∃∄¬∧∨→←↔↦⟹⟺∅∪∩∖∂∇∎□■⊕⊗≅∼∝∠∥⊥"
    + "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
    + "ℝℤℕℚℂℓ℘ℵ"
    + "αβγδεζηθικλμνξοπρςστυφχψω"
    + "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    + "ϑϕϖϱϵ"
)


def fetch(cache: Path, base: str, stem: str) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / f"{stem}.otf"
    if dst.exists() and dst.stat().st_size > 10_000:
        return dst
    url = f"{base}/{stem}.otf"
    print(f"    téléchargement {stem}.otf")
    dst.write_bytes(urllib.request.urlopen(url, timeout=60).read())
    return dst


_TAG = re.compile(r"<[^>]+>")
_ENT = re.compile(r"&(#x?[0-9a-fA-F]+|[a-z]+);")


def page_chars(html_dir: Path) -> set[str]:
    """Every character the built pages set, markup and CSS excluded."""
    import html as htmlmod

    chars: set[str] = set()
    for f in sorted(html_dir.glob("*.html")):
        text = f.read_text(encoding="utf-8")
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.S)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        chars |= set(htmlmod.unescape(_TAG.sub(" ", text)))
    return {c for c in chars if c.isprintable() or c == " "}


def subset_face(src: Path, chars: str) -> bytes:
    font = TTFont(src)
    opts = subset.Options(layout_features=["*"], notdef_outline=True,
                          desubroutinize=True, drop_tables=["DSIG"], recalc_bounds=True)
    s = subset.Subsetter(options=opts)
    s.populate(text=chars)
    s.subset(font)
    font.flavor = "woff2"
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def unicode_range(chars: set[str]) -> str:
    cps = sorted(ord(c) for c in chars)
    out, i = [], 0
    while i < len(cps):
        j = i
        while j + 1 < len(cps) and cps[j + 1] == cps[j] + 1:
            j += 1
        out.append(f"U+{cps[i]:04X}" if i == j else f"U+{cps[i]:04X}-{cps[j]:04X}")
        i = j + 1
    return ", ".join(out)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", type=Path, default=root / "docs")
    ap.add_argument("--out", type=Path, default=root / "assets" / "fonts-lm.json")
    ap.add_argument("--cache", type=Path, default=root / ".impeccable" / "ctan")
    a = ap.parse_args(argv)

    if not a.html.is_dir() or not list(a.html.glob("*.html")):
        print(f"aucune page dans {a.html} — lancer d'abord `python -m cairn.journal`", file=sys.stderr)
        return 1

    used = page_chars(a.html) | set(ALWAYS)
    print(f"  {len(used)} caractères employés par les pages")

    srcs = {k: fetch(a.cache, base, stem) for k, (base, stem) in SOURCES.items()}
    cmaps = {k: set(TTFont(p).getBestCmap().keys()) for k, p in srcs.items()}

    # What the roman text face cannot carry is what the math face must.
    text_cov = {c for c in used if ord(c) in cmaps["lmr"]}
    math_need = {c for c in used - text_cov if ord(c) in cmaps["lmmath"]}
    orphan = used - text_cov - math_need
    print(f"  texte : {len(text_cov)} · maths : {len(math_need)} · sans fonte : {len(orphan)}")
    if orphan:
        print(f"    non couverts (repli système) : {''.join(sorted(orphan))[:80]}")

    out: dict[str, dict] = {}
    total = 0
    for key in ("lmr", "lmb", "lmi", "lmm", "lmc"):
        cov = "".join(c for c in used if ord(c) in cmaps[key])
        data = subset_face(srcs[key], cov)
        out[key] = {"b64": base64.b64encode(data).decode()}
        total += len(data)
        print(f"    {key}: {len(cov):4d} glyphes → {len(data)/1024:6.1f} Kio")

    data = subset_face(srcs["lmmath"], "".join(sorted(math_need)))
    out["lmmath"] = {"b64": base64.b64encode(data).decode(),
                     "range": unicode_range(math_need)}
    total += len(data)
    print(f"    lmmath: {len(math_need):3d} glyphes → {len(data)/1024:6.1f} Kio")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out))
    print(f"  total {total/1024:.0f} Kio → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
