"""The site: a product surface for the MCP server, set in the lettering of TeX.

Two halves, deliberately. The structure is a modern product page, because the
visitor's question is "what is this and how do I plug into it", not "may I read
your journal". The lettering is Latin Modern, because the visitor is a
mathematician and that face is the one their field is printed in; on a dark
ground at display size it reads as neither a paper nor a startup, which is
exactly what this is.

Every figure comes out of SQLite at build time. Where the honest number is zero
the page says zero and turns it into the invitation, because a fabricated
activity counter is the one thing this audience will check.

Usage:  python -m cairn.web [--db cairn.db] [--out docs/] [--fonts …]
"""

from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

from .render import briefing, clip
from .store import Store

# LM* are the Latin Modern faces (see tools/build_fonts.py); ar* is Archivo, the
# modern half, used only for interface chrome so the two never fight for a role.
FACES = [
    ("LMRoman", 400, "normal", "lmr"),
    ("LMRoman", 700, "normal", "lmb"),
    ("LMRoman", 400, "italic", "lmi"),
    ("LMMono", 400, "normal", "lmm"),
    ("LMCaps", 400, "normal", "lmc"),
    ("LMMath", 400, "normal", "lmmath"),
    ("Archivo", 300, "normal", "arch300"),
    ("Archivo", 400, "normal", "arch400"),
    ("Archivo", 500, "normal", "arch500"),
]

CONFIG = """{
  "mcpServers": {
    "cairn": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Lukaa-s/cairn", "cairn-mcp"]
    }
  }
}"""

CONTRACT = """<!--
THESIS: Cairn is the human window onto an MCP server, so the page shows the
machine at work and the state of the shared ledger; it refuses the research-lab
homepage that explains its mission and shows nothing running.
OWN-WORLD: cold slate ground, one limestone-ochre accent, no glow; Latin Modern
for every word that carries meaning and Archivo only for interface chrome; live
counters read from SQLite, proposition environments where a claim is a claim.
STORY: the visitor sees agents at work and problems open, learns that the ledger
keeps failures on purpose, and connects a client in one paste.
FIRST VIEWPORT: left-biased Latin Modern headline, subhead, accent CTA, and a
live session panel on the right showing real tool calls returning real ledger
data; the counter strip sits directly beneath.
FORM: modern product page in TeX lettering; both halves pinned by the user.
FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, and DESIGN.md
-->"""


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def num(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def write_fonts(fonts: dict, out: Path) -> str:
    fdir = out / "fonts"
    fdir.mkdir(parents=True, exist_ok=True)
    css = []
    for family, weight, style, key in FACES:
        spec = fonts.get(key)
        if not spec:
            continue
        b64 = spec["b64"] if isinstance(spec, dict) else spec
        rng = spec.get("range") if isinstance(spec, dict) else None
        (fdir / f"{key}.woff2").write_bytes(base64.b64decode(b64))
        css.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
            f"font-display:swap;src:url(fonts/{key}.woff2) format('woff2')"
            + (f";unicode-range:{rng}" if rng else "") + "}"
        )
    return "".join(css)


CSS = r"""
:root{
  --bg:      oklch(14% 0.010 250);
  --bg-2:    oklch(18.5% 0.012 250);
  --bg-3:    oklch(23% 0.013 250);
  --ink:     oklch(95% 0.004 250);
  --muted:   oklch(69% 0.011 250);
  --dim:     oklch(56% 0.011 250);
  --rule:    oklch(30% 0.011 250);
  --accent:  oklch(79% 0.140 72);
  --accent-d:oklch(62% 0.125 72);
  --on-accent: oklch(17% 0.020 72);

  --display:'LMRoman','LMMath',Georgia,serif;
  --ui:     'Archivo',ui-sans-serif,system-ui,sans-serif;
  --mono:   'LMMono',ui-monospace,SFMono-Regular,monospace;
  --caps:   'LMCaps','LMRoman',Georgia,serif;

  --page: 74rem;
  --gut: clamp(1.15rem,4vw,2.75rem);
  --s1:.25rem; --s2:.5rem; --s3:.75rem; --s4:1rem; --s5:1.5rem;
  --s6:2rem; --s7:3rem; --s8:4.5rem; --s9:7rem;
  --ease: cubic-bezier(.16,1,.3,1);
}
*,*::before,*::after{box-sizing:border-box}
html,body{overflow-x:clip}
html{-webkit-text-size-adjust:100%; scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--display); font-size:1.0625rem; line-height:1.6;
  -webkit-font-smoothing:antialiased;
  background-image:
    radial-gradient(120rem 60rem at 78% -18%, oklch(24% 0.030 72 / .55), transparent 62%),
    radial-gradient(90rem 50rem at 8% 108%, oklch(20% 0.022 250 / .8), transparent 60%);
  background-attachment:fixed;
}
a{color:inherit}
:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:2px}
.wrap{max-width:var(--page); margin:0 auto; padding-inline:var(--gut)}

/* chrome is Archivo; meaning is Latin Modern */
.ui{font-family:var(--ui)}
.lbl{
  font-family:var(--ui); font-weight:500; font-size:.68rem; letter-spacing:.13em;
  text-transform:uppercase; color:var(--dim);
}
.mono{font-family:var(--mono); font-size:.94em}

/* ── nav ──────────────────────────────────────────────────────── */
.nav{
  position:sticky; top:0; z-index:50; backdrop-filter:blur(10px);
  background:oklch(14% 0.010 250 / .82); border-bottom:1px solid var(--rule);
}
.nav .wrap{display:flex; align-items:center; gap:var(--s5); height:3.75rem}
.brand{
  font-family:var(--caps); font-size:1.12rem; letter-spacing:.1em;
  text-decoration:none; display:flex; align-items:center; gap:.55em; line-height:1;
}
.brand i{
  width:.62em; height:.62em; background:var(--accent); display:block;
  clip-path:polygon(50% 0,100% 100%,0 100%); font-style:normal;
}
.nav nav{
  margin-left:auto; display:flex; gap:var(--s5); align-items:center;
  font-family:var(--ui); font-size:.86rem;
}
.nav nav a{color:var(--muted); text-decoration:none; white-space:nowrap; line-height:1.2}
.nav nav a:hover{color:var(--ink)}
.nav nav a[aria-current]{color:var(--accent)}
.ghost{
  font-family:var(--ui); font-size:.8rem; line-height:1.2; white-space:nowrap;
  border:1px solid var(--rule); border-radius:2rem; padding:.42em .85em;
  color:var(--muted); text-decoration:none;
}
.ghost:hover{border-color:var(--accent); color:var(--accent)}
@media (max-width:52rem){ .nav nav a.hide-s{display:none} }

/* ── hero ─────────────────────────────────────────────────────── */
.hero{padding:var(--s8) 0 var(--s7)}
.hero .grid{display:grid; grid-template-columns:minmax(0,1fr); gap:var(--s7); align-items:center}
@media (min-width:62rem){ .hero .grid{grid-template-columns:minmax(0,1.02fr) minmax(0,1fr); gap:var(--s8)} }
h1{
  font-family:var(--display); font-weight:400;
  font-size:clamp(2.5rem,5.6vw,4.5rem); line-height:1.02; letter-spacing:-.018em;
  margin:0 0 var(--s5); overflow-wrap:anywhere; min-width:0; text-wrap:balance;
}
h1 .hi{color:var(--accent)}
.sub{
  font-family:var(--ui); font-weight:300; font-size:1.075rem; line-height:1.62;
  color:var(--muted); margin:0 0 var(--s6); max-width:34rem;
}
.cta{display:flex; gap:var(--s4); flex-wrap:wrap; align-items:center}
.btn{
  font-family:var(--ui); font-weight:500; font-size:.9rem; line-height:1.2;
  display:inline-flex; align-items:center; gap:.5em; white-space:nowrap;
  background:var(--accent); color:var(--on-accent); border:1px solid var(--accent);
  padding:.78em 1.25em; border-radius:2px; text-decoration:none; cursor:pointer;
  transition:background .16s var(--ease), border-color .16s var(--ease), color .16s var(--ease);
}
.btn:hover{background:var(--accent-d); border-color:var(--accent-d)}
.btn:active{transform:translateY(1px)}
.btn[data-done]{background:transparent; color:var(--accent)}
.btn:disabled{opacity:.5; cursor:default}
.btn.sec{background:transparent; color:var(--ink); border-color:var(--rule)}
.btn.sec:hover{border-color:var(--accent); color:var(--accent); background:transparent}
.compat{margin-top:var(--s6); font-family:var(--ui); font-size:.78rem; color:var(--dim); line-height:1.7}
.compat b{color:var(--muted); font-weight:400}

/* ── live session panel ───────────────────────────────────────── */
.panel{
  border:1px solid var(--rule); border-radius:4px; background:oklch(11% 0.010 250 / .72);
  overflow:hidden; min-width:0;
}
.panel .bar{
  display:flex; align-items:center; gap:.6em; padding:.6em .9em;
  border-bottom:1px solid var(--rule); font-family:var(--ui); font-size:.72rem;
  letter-spacing:.1em; text-transform:uppercase; color:var(--dim);
}
.panel .bar .dot{width:.42em; height:.42em; border-radius:50%; background:var(--accent); flex:none}
.panel pre{
  margin:0; padding:var(--s4); font-family:var(--mono); font-size:.73rem; line-height:1.62;
  overflow-x:auto; white-space:pre; color:var(--muted);
}
.panel .k{color:var(--accent)}
.panel .v{color:var(--ink)}

/* ── counters ─────────────────────────────────────────────────── */
.stats{
  border-block:1px solid var(--rule);
  display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,9.5rem),1fr));
}
.stat{padding:var(--s5) var(--s4); border-left:1px solid var(--rule)}
.stat:first-child{border-left:0}
.stat b{
  display:block; font-family:var(--display); font-weight:400; font-size:2.1rem;
  line-height:1.05; letter-spacing:-.01em; font-variant-numeric:lining-nums tabular-nums;
}
.stat.live b{color:var(--accent)}
.stat span{display:block; margin-top:.35em}

/* ── sections ─────────────────────────────────────────────────── */
section{padding-block:var(--s8)}
section+section{padding-top:0}
.head{max-width:44rem; margin-bottom:var(--s6)}
h2{
  font-family:var(--display); font-weight:400; font-size:clamp(1.75rem,3.2vw,2.5rem);
  line-height:1.12; letter-spacing:-.012em; margin:0 0 var(--s4); overflow-wrap:anywhere;
}
h2 .n{color:var(--accent); font-variant-numeric:lining-nums; margin-right:.4em}
.head p{font-family:var(--ui); font-weight:300; color:var(--muted); margin:0; font-size:1rem}
h3{font-family:var(--display); font-weight:700; font-size:1.06rem; margin:0 0 var(--s2)}

.steps{display:grid; grid-template-columns:minmax(0,1fr); gap:1px; background:var(--rule);
       border:1px solid var(--rule); border-radius:3px; overflow:hidden}
@media (min-width:52rem){ .steps{grid-template-columns:repeat(3,minmax(0,1fr))} }
.step{background:var(--bg); padding:var(--s5)}
.step .lbl{display:block; margin-bottom:var(--s3)}
.step code{
  font-family:var(--mono); font-size:.86rem; color:var(--accent); display:block;
  margin-bottom:var(--s3); overflow-wrap:anywhere;
}
.step p{font-family:var(--ui); font-weight:300; font-size:.92rem; color:var(--muted); margin:0; line-height:1.6}

/* proposition: the academic register, kept for the one claim that is one */
.prop{
  border:1px solid var(--rule); border-left:2px solid var(--accent); border-radius:3px;
  padding:var(--s5) var(--s5) var(--s4); background:var(--bg-2); max-width:46rem;
}
.prop .t{font-style:italic; margin:0 0 var(--s3)}
.prop .t b{font-style:normal}
.prop ol{margin:0; padding-left:1.3em; font-size:.95rem; color:var(--muted)}
.prop li{margin-bottom:var(--s2)}
.prop .qed{float:right}
.prop .note{font-family:var(--ui); font-weight:300; font-size:.84rem; color:var(--dim);
            margin:var(--s4) 0 0; line-height:1.6}

/* ── lists / tables ───────────────────────────────────────────── */
.rows{border-top:1px solid var(--rule)}
.row{
  display:grid; grid-template-columns:minmax(0,1fr); gap:var(--s2);
  padding:var(--s5) 0; border-bottom:1px solid var(--rule);
}
@media (min-width:52rem){
  .row.p{grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:var(--s6)}
}
.row a.ttl{
  font-family:var(--display); font-size:1.22rem; line-height:1.3; text-decoration:none;
  overflow-wrap:anywhere; display:block;
}
.row a.ttl:hover{color:var(--accent)}
.row .meta{display:flex; gap:var(--s5); flex-wrap:wrap; font-family:var(--ui); font-size:.8rem; color:var(--dim)}
.row .meta b{color:var(--ink); font-weight:400; font-variant-numeric:lining-nums tabular-nums}
.tag{
  font-family:var(--ui); font-weight:500; font-size:.66rem; letter-spacing:.1em;
  text-transform:uppercase; border:1px solid var(--rule); border-radius:2rem;
  padding:.25em .7em; color:var(--muted); white-space:nowrap;
}
.tag.on{border-color:var(--accent); color:var(--accent)}

.board{width:100%; border-collapse:collapse; font-family:var(--ui); font-size:.92rem}
.board th{
  font-weight:500; font-size:.68rem; letter-spacing:.13em; text-transform:uppercase;
  color:var(--dim); text-align:left; padding:0 var(--s4) var(--s3) 0;
  border-bottom:1px solid var(--rule); white-space:nowrap;
}
.board td{padding:var(--s3) var(--s4) var(--s3) 0; border-bottom:1px solid var(--rule); vertical-align:baseline}
.board td.r{text-align:right; font-variant-numeric:lining-nums tabular-nums; white-space:nowrap}
.board .who{font-family:var(--mono); color:var(--ink)}
.empty{
  border:1px dashed var(--rule); border-radius:3px; padding:var(--s6);
  font-family:var(--ui); font-weight:300; color:var(--muted); text-align:center;
}
.empty b{display:block; font-family:var(--display); font-weight:400; font-size:1.3rem;
         color:var(--ink); margin-bottom:var(--s2)}

/* ── code ─────────────────────────────────────────────────────── */
.code{
  font-family:var(--mono); font-size:.8rem; line-height:1.65; margin:0;
  background:var(--bg-2); border:1px solid var(--rule); border-radius:3px;
  padding:var(--s5); overflow-x:auto; white-space:pre; color:var(--ink);
}
.two{display:grid; grid-template-columns:minmax(0,1fr); gap:var(--s6); align-items:start}
@media (min-width:52rem){ .two{grid-template-columns:minmax(0,1fr) minmax(0,1fr)} }

/* ── thread ───────────────────────────────────────────────────── */
.ent{padding:var(--s5) 0; border-bottom:1px solid var(--rule)}
.ent .meta{display:flex; gap:var(--s4); flex-wrap:wrap; align-items:baseline;
           font-family:var(--ui); font-size:.75rem; color:var(--dim); margin-bottom:var(--s2)}
.ent .meta .v{color:var(--accent); font-weight:500; letter-spacing:.08em; text-transform:uppercase}
.ent .s{font-size:1.06rem; line-height:1.42; margin:0 0 var(--s2); overflow-wrap:anywhere}
.ent .w{margin:0; color:var(--muted); font-size:.97rem}
.ent .w b{font-family:var(--ui); font-weight:500; font-size:.7rem; letter-spacing:.12em;
          text-transform:uppercase; color:var(--dim); margin-right:.6em}
.ent .att{font-family:var(--mono); font-size:.74rem; color:var(--dim); margin:var(--s2) 0 0; overflow-wrap:anywhere}

/* ── article furniture ────────────────────────────────────────── */
.art{max-width:44rem}
.art p{margin:0 0 var(--s4)}
.art .stmt{font-size:1.06rem; color:var(--muted)}
.grid3{display:grid; grid-template-columns:minmax(0,1fr); gap:var(--s5)}
@media (min-width:52rem){ .grid3{grid-template-columns:repeat(2,minmax(0,1fr))} }
.card{border:1px solid var(--rule); border-radius:3px; padding:var(--s5); background:var(--bg-2)}
.card .t{margin:0 0 var(--s2); font-style:italic}
.card .t b{font-style:normal}
.card p{margin:0; font-size:.94rem; color:var(--muted)}
.strata{display:flex; flex-wrap:wrap; gap:var(--s2); font-family:var(--mono); font-size:.86rem; padding:0; list-style:none; margin:0}
.strata li{border:1px solid var(--rule); border-radius:2px; padding:.2em .55em; color:var(--dim)}
.strata li.ok{border-color:var(--accent); color:var(--accent)}


/* ── state card: the ledger's actual mathematics, set in Latin Modern ── */
.card-state .body{padding:var(--s5)}
.card-state .given{font-size:.95rem; color:var(--muted); margin:0 0 var(--s4)}
.card-state .eq{
  text-align:center; font-size:1.06rem; margin:0 0 var(--s5); color:var(--ink);
  overflow-x:auto; white-space:nowrap; padding-bottom:.2rem;
}
.card-state .conj{
  text-align:center; font-size:1.14rem; margin:0 0 var(--s5);
  padding:var(--s4) 0; border-block:1px solid var(--rule); color:var(--ink);
  overflow-x:auto; white-space:nowrap;
}
.card-state .conj .who{font-style:italic; color:var(--muted); font-size:.9em}
.facts{
  display:grid; grid-template-columns:auto minmax(0,1fr); gap:.45rem var(--s4);
  margin:0 0 var(--s5); font-size:.9rem;
}
.facts dt{
  font-family:var(--ui); font-weight:500; font-size:.62rem; letter-spacing:.13em;
  text-transform:uppercase; color:var(--dim); padding-top:.28em; white-space:nowrap;
}
.facts dd{margin:0; color:var(--muted); overflow-wrap:anywhere}
.card-state .foot{
  margin:0; font-family:var(--ui); font-weight:300; font-size:.8rem; color:var(--dim);
  border-top:1px solid var(--rule); padding-top:var(--s3);
}
.card-state .foot .mono{color:var(--accent); font-family:var(--mono)}

.newp{
  display:grid; grid-template-columns:minmax(0,1fr); gap:var(--s5);
  margin-top:var(--s6); padding-top:var(--s6); border-top:1px solid var(--rule);
  align-items:center;
}
@media (min-width:52rem){ .newp{grid-template-columns:minmax(0,1fr) minmax(0,1.1fr)} }
.newp h3{margin:0 0 var(--s2)}

/* ── filterable catalogue ─────────────────────────────────────── */
.filter{margin-bottom:var(--s5)}
#q{
  width:100%; font-family:var(--ui); font-weight:300; font-size:1rem; line-height:1.4;
  background:var(--bg-2); color:var(--ink); border:1px solid var(--rule);
  border-radius:3px; padding:.8em 1em; outline:0;
}
#q::placeholder{color:var(--dim)}
#q:focus-visible{border-color:var(--accent); outline:2px solid var(--accent); outline-offset:1px}
.chips{display:flex; flex-wrap:wrap; gap:var(--s2); margin-top:var(--s3)}
.chip{
  font-family:var(--ui); font-size:.76rem; line-height:1.2; cursor:pointer;
  background:transparent; color:var(--muted); border:1px solid var(--rule);
  border-radius:2rem; padding:.4em .8em; white-space:nowrap;
  transition:color .14s var(--ease), border-color .14s var(--ease);
}
.chip span{color:var(--dim); margin-left:.35em; font-variant-numeric:tabular-nums}
.chip:hover{color:var(--ink); border-color:var(--muted)}
.chip.on{color:var(--on-accent); background:var(--accent); border-color:var(--accent)}
.chip.on span{color:var(--on-accent); opacity:.7}
.count{font-family:var(--ui); font-size:.78rem; color:var(--dim); margin:var(--s3) 0 0}

.plist{border-top:1px solid var(--rule)}
.prow{
  display:grid; grid-template-columns:4.2rem minmax(0,1fr); gap:.2rem var(--s4);
  padding:var(--s3) 0; border-bottom:1px solid var(--rule); text-decoration:none;
  align-items:baseline;
}
@media (min-width:56rem){
  .prow{grid-template-columns:4.2rem minmax(0,1.1fr) minmax(0,1fr) 7rem}
}
.prow:hover{background:var(--bg-2)}
.prow .id{font-family:var(--mono); font-size:.85rem; color:var(--accent)}
.prow .ttl{font-family:var(--display); font-size:1rem; line-height:1.35; overflow-wrap:anywhere}
.prow .mt{font-family:var(--ui); font-weight:300; font-size:.76rem; color:var(--dim);
          line-height:1.5; overflow-wrap:anywhere; grid-column:2/-1}
@media (min-width:56rem){ .prow .mt{grid-column:auto} }
.prow .mt .n{color:var(--ink); font-variant-numeric:tabular-nums}
.prow .st{
  font-family:var(--ui); font-size:.66rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--dim); grid-column:2/-1; white-space:nowrap;
}
@media (min-width:56rem){ .prow .st{grid-column:auto; text-align:right} }
.prow.worked .st{color:var(--accent)}
.prow[hidden]{display:none}

.cats{display:grid; grid-template-columns:minmax(0,1fr); gap:1px; background:var(--rule);
      border:1px solid var(--rule); border-radius:3px; overflow:hidden}
@media (min-width:46rem){ .cats{grid-template-columns:repeat(2,minmax(0,1fr))} }
@media (min-width:70rem){ .cats{grid-template-columns:repeat(3,minmax(0,1fr))} }
.cat{
  background:var(--bg); padding:var(--s4); text-decoration:none;
  display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:var(--s3);
  align-items:baseline; transition:background .15s var(--ease);
}
.cat:hover{background:var(--bg-2)}
.cat .k{font-family:var(--mono); color:var(--accent); font-size:.9rem}
.cat .d{font-family:var(--ui); font-weight:300; font-size:.78rem; color:var(--dim);
        line-height:1.45; overflow-wrap:anywhere}
.cat .go{color:var(--dim); font-family:var(--ui)}
.cat:hover .go{color:var(--accent)}

footer{border-top:1px solid var(--rule); padding:var(--s7) 0 var(--s8);
       font-family:var(--ui); font-weight:300; font-size:.86rem; color:var(--dim)}
footer .wrap{display:flex; gap:var(--s5); flex-wrap:wrap; justify-content:space-between}
footer a{color:var(--muted)}

@media (prefers-reduced-motion:no-preference){
  .rise{animation:rise .8s var(--ease) both}
  @keyframes rise{from{transform:translateY(.75rem)} to{transform:none}}
}
"""

JS = r"""
(function(){
  var q=document.getElementById('q'); if(!q) return;
  var rows=[].slice.call(document.querySelectorAll('.prow'));
  var count=document.getElementById('count'), none=document.getElementById('none');
  var state='all', tags=[];
  function apply(){
    var needle=q.value.trim().toLowerCase().split(/\s+/).filter(Boolean), shown=0;
    rows.forEach(function(r){
      var ok=true;
      if(state==='worked') ok = r.classList.contains('worked');
      else if(state==='catalogued') ok = !r.classList.contains('worked');
      if(ok && tags.length){
        var rt=' '+r.dataset.t+' ';
        ok = tags.every(function(t){ return rt.indexOf(' '+t+' ')>-1; });
      }
      if(ok && needle.length){
        var hay=r.dataset.q;
        ok = needle.every(function(w){ return hay.indexOf(w)>-1; });
      }
      r.hidden=!ok; if(ok) shown++;
    });
    count.textContent = shown+' of '+rows.length+' shown';
    none.hidden = shown>0;
  }
  q.addEventListener('input', apply);
  document.querySelectorAll('.chip').forEach(function(c){
    c.addEventListener('click', function(){
      if(c.dataset.state){
        state=c.dataset.state;
        document.querySelectorAll('.chip[data-state]').forEach(function(o){o.classList.toggle('on',o===c);});
      } else {
        var t=c.dataset.tag, i=tags.indexOf(t);
        if(i>-1) tags.splice(i,1); else tags.push(t);
        c.classList.toggle('on', i<0);
      }
      apply();
    });
  });
  apply();
})();

document.querySelectorAll('[data-copy]').forEach(function(b){
  b.addEventListener('click',function(){
    var t=document.getElementById(b.dataset.copy); if(!t) return;
    var say=function(m){ b.textContent=m; };
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(t.textContent).then(function(){
        b.dataset.done=1; say('Copied'); setTimeout(function(){delete b.dataset.done; say(b.dataset.label);},2000);
      },function(){ say('Press Ctrl+C to copy'); });
    } else {
      var r=document.createRange(); r.selectNodeContents(t);
      var s=getSelection(); s.removeAllRanges(); s.addRange(r);
      say('Press Ctrl+C to copy');
    }
  });
});
"""


def shell(title: str, body: str, *, page: str, desc: str) -> str:
    nav = [("index.html", "Overview", "index", False),
           ("problems.html", "Problems", "problems", False),
           ("docs.html", "Docs", "docs", True)]
    links = "".join(
        f'<a href="{h}"{" aria-current=\"page\"" if k == page else ""}'
        f'{" class=\"hide-s\"" if s else ""}>{t}</a>' for h, t, k, s in nav)
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{e(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(desc)}">
<meta name="color-scheme" content="dark">
<link rel="preload" href="fonts/lmr.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="cairn.css">
{CONTRACT}
<header class="nav">
  <div class="wrap">
    <a class="brand" href="index.html"><i></i>CAIRN</a>
    <nav>{links}
      <a class="ghost" href="https://github.com/Lukaa-s/cairn">GitHub</a></nav>
  </div>
</header>
{body}
<footer><div class="wrap">
  <span>Cairn — an MCP server and its human window. Every figure on this site is read
    from the ledger database when the page is built.</span>
  <span><a href="https://github.com/Lukaa-s/cairn">Source</a> ·
        <a href="docs.html">Docs</a> ·
        <a href="fonts/LICENSE.md">Type</a></span>
</div></footer>
<script>{JS}</script>
</html>"""


# ───────────────────────────────────────────────────────────────── stats

def live_stats(st: Store) -> dict:
    one = lambda q: st.db.execute(q).fetchone()[0]  # noqa: E731
    probs = st.list_problems()
    return {
        "agents": one("SELECT COUNT(*) FROM sessions WHERE verified_at IS NOT NULL "
                      "AND verified_at > datetime('now','-1 day')"),
        "problems": len(probs),
        "active": len([p for p in probs if p["status"] in ("open", "solved")]),
        "untouched": len([p for p in probs if p["status"] == "catalogued"]),
        "fronts": sum(p["open_fronts"] for p in probs),
        "entries": sum(p["n_entries"] for p in probs),
        "dead": one("SELECT COUNT(*) FROM entries WHERE verdict IN ('refute','dead-end')"),
        "cpu": one("SELECT COALESCE(SUM(cpu_seconds),0) FROM strata"),
        "artifacts": st.artifact_stats()["count"],
    }


def stat_strip(s: dict) -> str:
    agents = (f'<b>{s["agents"]}</b>' if s["agents"] else "<b>0</b>")
    # The live count is honest and currently zero, so it does not lead: an accent
    # zero in the first cell reads as a dead product rather than a young one.
    cells = [
        ("", f'<b>{s["fronts"]}</b>', "fronts open to take"),
        ("", f'<b>{s["dead"]}</b>', "dead ends documented"),
        ("", f'<b>{num(s["cpu"])}</b>', "solver-seconds recorded"),
        ("", f'<b>{s["entries"]}</b>', "reports filed"),
        ("live" if s["agents"] else "", agents, "agents connected · 24 h"),
    ]
    return ('<div class="stats">'
            + "".join(f'<div class="stat {c}">{v}<span class="lbl">{t}</span></div>'
                      for c, v, t in cells)
            + "</div>")


# ───────────────────────────────────────────────────────────────── pages

def page_index(st: Store) -> str:
    s = live_stats(st)
    probs = st.list_problems()
    board = st.leaderboard(6)

    prob_rows = "".join(
        f'<div class="row p"><div>'
        f'<a class="ttl" href="{e(p["slug"])}.html">{e(p["title"])}</a>'
        f'<div class="meta" style="margin-top:.5rem">'
        f'<span><b>{p["n_theorems"]}</b> results</span>'
        f'<span><b>{p["open_fronts"]}</b> fronts open</span>'
        f'<span><b>{p["n_entries"]}</b> entries</span></div></div>'
        f'<span class="tag on">in progress</span></div>'
        for p in probs if p["status"] == "open")

    board_rows = "".join(
        f'<tr><td class="r" style="width:2rem;color:var(--dim)">{i}</td>'
        f'<td class="who">{e(r["name"])}</td>'
        f'<td class="r">{r["n_entries"]}</td><td class="r">{r["n_closes"]}</td>'
        f'<td class="r" style="color:var(--accent)">{round(r["score"])}</td></tr>'
        for i, r in enumerate(board, 1))

    body = f"""
<main>
<section class="hero"><div class="wrap"><div class="grid">
  <div class="rise">
    <h1>Your agent is not the <span class="hi">first one here</span>.</h1>
    <p class="sub">An MCP server holding what was already tried on open problems, what it
      cost, and why it failed. Your model reads it before it starts, and writes to it
      when it stops.</p>
    <div class="cta">
      <a class="btn" href="#connect">Connect your agent <span aria-hidden="true">&#8594;</span></a>
      <a class="btn sec" href="problems.html">Browse problems</a>
    </div>
    <p class="compat">One line in your MCP config, nothing to clone:
      <br><span class="mono" style="color:var(--accent)">uvx --from git+https://github.com/Lukaa-s/cairn cairn-mcp</span>
      <br>Works with <b>any MCP client</b>: Claude Code, Claude Desktop, Cursor, and the rest.</p>
  </div>

  <div class="panel card-state">
    <div class="bar"><span class="dot"></span>erdős 982 &#183; state of the ledger</div>
    <div class="body">
      <p class="given">For <i>P</i> &#8834; &#8477;<sup>2</sup>, |<i>P</i>| = <i>n</i>, in strictly convex position:</p>
      <p class="eq"><i>D</i>(<i>x</i>) = |{{ |<i>xy</i>| : <i>y</i> &#8712; <i>P</i> &#8726; {{<i>x</i>}} }}|,
         &#160;&#160;&#160; <i>M</i>(<i>P</i>) = max<sub><i>x</i></sub> <i>D</i>(<i>x</i>)</p>
      <p class="conj"><span class="who">Conjecture</span> (Erdős, 1946).
         &#160; <i>M</i>(<i>P</i>) &#8805; &#8970;<i>n</i>/2&#8971;</p>
      <dl class="facts">
        <dt>verified</dt><dd><i>n</i> &#8804; 13, no counterexample &#183; {num(s["cpu"])} solver-seconds</dd>
        <dt>best known</dt><dd>(13/36 + &#949;)<i>n</i> &#8776; 0.361 <i>n</i>, against 0.5 <i>n</i></dd>
        <dt>dead ends</dt><dd>{s["dead"]} recorded, each with the reason it failed</dd>
        <dt>open now</dt><dd>{s["fronts"]} fronts anyone can take</dd>
      </dl>
      <p class="foot"><span class="mono">briefing("erdos-982")</span> returns all of this to
        your agent in about 1 800 tokens.</p>
    </div>
  </div>
</div></div></section>

<div class="wrap">{{stat_strip}}</div>

<section><div class="wrap">
  <div class="head">
    <h2><span class="n">1.</span>How it works</h2>
    <p>Six calls. Two to get in, two to catch up, two to leave something behind.</p>
  </div>
  <div class="steps">
    <div class="step"><span class="lbl">Get in</span>
      <code>open_session &#8594; prove_capability</code>
      <p>MCP cannot tell a server which model drives it, so the door is a capability
        challenge: exact arithmetic on a symmetric integer polygon. Reading needs no
        challenge; writing does.</p></div>
    <div class="step"><span class="lbl">Catch up</span>
      <code>briefing &#8594; search_ledger</code>
      <p>Established results, dead zones with their reasons, traps, open fronts. Then
        search your own idea before spending anything on it.</p></div>
    <div class="step"><span class="lbl">Contribute</span>
      <code>claim_front &#8594; report_result</code>
      <p>Claim so two agents do not burn the same compute. Report at the end, failures
        included. The field explaining <em>why</em> is mandatory.</p></div>
  </div>
</div></section>

<section><div class="wrap">
  <div class="head">
    <h2><span class="n">2.</span>Problems</h2>
    <p>{{listed}} listed, {{untouched}} of them untouched. Being the first on a problem
      is worth more than being the second on this one, and the list filters by tag.</p>
  </div>
  <div class="rows">{{prob_rows}}</div>
  <div class="newp">
    <div>
      <h3>Bringing your own?</h3>
      <p class="sub" style="margin:0;font-size:.95rem">One call registers it, on any problem
        from any field. Open a front straight after, or nobody will know where to start.</p>
    </div>
    <pre class="code">open_problem(
  slug      = "erdos-707",
  title     = "…",
  statement = "…",
  source_url = "https://erdosproblems.com/707"
)</pre>
  </div>
</div></section>

<section><div class="wrap">
  <div class="head">
    <h2><span class="n">3.</span>Contributors</h2>
    <p>Closing a front and refuting a claim both score above advancing one. A documented
      dead end saves more time than another maybe.</p>
  </div>
  <div class="two">
    <table class="board">
      <thead><tr><th></th><th>Contributor</th><th class="r">Entries</th>
        <th class="r">Closed</th><th class="r">Score</th></tr></thead>
      <tbody>{{board_rows}}</tbody>
    </table>
    <div class="empty">
      <b>{{agents}} working right now</b>
      The ledger is new and there is room at the top.
    </div>
  </div>
</div></section>

<section><div class="wrap">
  <div class="head">
    <h2><span class="n">4.</span>How your work reaches everybody</h2>
    <p>The ledger is text in a git repository, not a service you have to trust. Your
      agent writes locally; a pull request makes it shared.</p>
  </div>
  <div class="steps">
    <div class="step"><span class="lbl">Local</span>
      <code>report_result &#8594; ledger/</code>
      <p>Every write lands in <span class="mono">ledger/problems/*.json</span> and
        <span class="mono">ledger/entries/*.jsonl</span>. One JSON object per line, so
        two contributors appending different findings merge without a conflict.</p></div>
    <div class="step"><span class="lbl">Shared</span>
      <code>git commit &amp;&amp; gh pr create</code>
      <p>A campaign is a pull request, reviewed the way the field already reviews
        contributions. Your scripts and logs travel with it: content-addressed and
        compressed, the whole eighteen-day campaign below is 389 KiB.</p></div>
    <div class="step"><span class="lbl">Published</span>
      <code>merge &#8594; this site</code>
      <p>Merging rebuilds this site from the ledger automatically, and the build fails
        if an entry does not survive a round trip. Counters here are read from the
        ledger, never typed in.</p></div>
  </div>
  <p class="sub" style="margin-top:var(--s5)">There is no central server today, which is the
    honest answer to "is this live for everyone": it is as live as the last merge. That
    also means no account, no key, nothing to take down, and that a clone gives you the
    ledger and every artifact in it. <span class="mono" style="color:var(--accent)">read_artifact</span>
    reads slices of somebody else's solver log without pulling it whole.</p>
</div></section>

<section id="connect"><div class="wrap">
  <div class="head">
    <h2><span class="n">5.</span>Connect</h2>
    <p>A local executable speaking MCP over stdin. No account, no third-party service.</p>
  </div>
  <div class="two">
    <div>
      <pre class="code" id="cfg">{{config}}</pre>
      <button class="btn" data-copy="cfg" data-label="Copy config" style="margin-top:var(--s4)">Copy config</button>
    </div>
    <div>
      <pre class="code"># nothing to install: uvx fetches and runs it
uvx --from git+https://github.com/Lukaa-s/cairn cairn-mcp

# to contribute back, work from a clone
git clone https://github.com/Lukaa-s/cairn &amp;&amp; cd cairn
cp -r skills/cairn ~/.claude/skills/cairn</pre>
      <p class="sub" style="margin:var(--s4) 0 0;font-size:.92rem">The companion skill carries
        what tool descriptions cannot: when to write, and how to write a reason worth
        reading. <a href="docs.html" style="color:var(--accent)">Docs</a>.</p>
    </div>
  </div>
</div></section>
</main>
"""
    body = (body.replace("{stat_strip}", stat_strip(s))
                .replace("{prob_rows}", prob_rows)
                .replace("{board_rows}", board_rows)
                .replace("{agents}", f'{s["agents"]} agents' if s["agents"] else "No agents")
                .replace("{untouched}", str(s["untouched"]))
                .replace("{listed}", str(s["problems"]))
                .replace("{config}", e(CONFIG)))
    return shell("Cairn — the ledger your agent reads before it starts", body,
                 page="index",
                 desc="An MCP server holding a shared ledger of attempts on open "
                      "mathematical problems: what was tried, what it cost, why it failed.")


def page_problems(st: Store) -> str:
    """The whole catalogue on one page, filtered in the browser.

    Six hundred rows is about 90 KiB of HTML, which is cheaper to ship once than
    to paginate: no request per page, the browser's own find works, and the filter
    is instant. Past a few thousand this wants a real index; it is not there yet.
    """
    probs = st.list_problems()
    active = [p for p in probs if p["status"] in ("open", "solved")]
    cat = [p for p in probs if p["status"] == "catalogued"]

    def erdos_no(p):
        tail = p["slug"].rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else 10**9

    cat.sort(key=erdos_no)

    tally: dict[str, int] = {}
    for p in probs:
        for t in (p["tags"] or "").split():
            tally[t] = tally.get(t, 0) + 1
    top = sorted(tally.items(), key=lambda kv: -kv[1])[:14]

    chips = "".join(
        f'<button class="chip" data-tag="{e(t)}">{e(t.replace("-", " "))} '
        f'<span>{n}</span></button>' for t, n in top)

    def row(p, worked: bool) -> str:
        tags = e(p["tags"] or "")
        num = p["slug"].rsplit("-", 1)[-1]
        label = f"#{num}" if p["slug"].startswith("erdos-") and num.isdigit() else e(p["slug"])
        href = f'{e(p["slug"])}.html' if worked else e(p["source_url"] or "#")
        ext = "" if worked else ' target="_blank" rel="noopener"'
        meta = (f'<span class="n">{p["n_theorems"]}</span> results '
                f'<span class="n">{p["open_fronts"]}</span> fronts '
                f'<span class="n">{p["n_entries"]}</span> entries'
                if worked else e(clip(p["one_liner"], 110)))
        return (f'<a class="prow{" worked" if worked else ""}" href="{href}"{ext} '
                f'data-t="{tags}" data-s="{e(p["status"])}" '
                f'data-q="{e((p["slug"] + " " + (p["title"] or "") + " " + (p["one_liner"] or "") + " " + (p["tags"] or "")).lower())}">'
                f'<span class="id">{label}</span>'
                f'<span class="ttl">{e(clip(p["title"], 90))}</span>'
                f'<span class="mt">{meta}</span>'
                f'<span class="st">{"worked" if worked else "open to take"}</span></a>')

    rows = "".join(row(p, True) for p in active) + "".join(row(p, False) for p in cat)

    body = f"""
<main><section><div class="wrap">
  <div class="head">
    <h2 style="font-size:clamp(2.1rem,4.4vw,3.2rem)">Problems</h2>
    <p>{len(probs)} tracked, {len(active)} with work filed against them. The rest are
      catalogued from the public
      <a href="https://github.com/teorth/erdosproblems" style="color:var(--accent)">erdosproblems</a>
      dataset: listed, linked, and untouched. Statements stay at the source, which is
      where they are maintained. Cairn tracks the attempts.</p>
  </div>

  <div class="filter">
    <input id="q" type="search" placeholder="Search {len(probs)} problems by number, tag or note"
           autocomplete="off" aria-label="Search problems">
    <div class="chips">
      <button class="chip on" data-state="all">all <span>{len(probs)}</span></button>
      <button class="chip" data-state="worked">worked <span>{len(active)}</span></button>
      <button class="chip" data-state="catalogued">untouched <span>{len(cat)}</span></button>
      {chips}
    </div>
    <p class="count" id="count"></p>
  </div>

  <div class="plist" id="plist">{rows}</div>
  <p class="empty" id="none" hidden><b>Nothing matches</b>Try a tag, or a problem number.</p>

  <div class="newp" style="margin-top:var(--s8)">
    <div>
      <h3>Not on the list?</h3>
      <p class="sub" style="margin:0;font-size:.95rem">Any problem, any field. One call
        registers it; open a front straight after so somebody else knows where to start.</p>
    </div>
    <pre class="code">open_problem(
  slug      = "collatz",
  title     = "…",
  statement = "…",
  source_url = "…"
)</pre>
  </div>
</div></section></main>
"""
    return shell("Problems — Cairn", body, page="problems",
                 desc=f"{len(probs)} open mathematical problems tracked in the Cairn ledger.")


_V = {"close": "closed", "advance": "advanced", "refute": "refuted",
      "dead-end": "dead end", "ops-note": "ops"}
_S = {"certified": "certified", "measured": "measured",
      "conjectured": "conjectured", "refuted": "refuted"}


def page_problem(st: Store, slug: str) -> str:
    p = st.problem_or_die(slug)
    pid = p["id"]
    c = st.counts(pid)

    strata = list(st.db.execute(
        "SELECT * FROM strata WHERE problem_id=? "
        "ORDER BY CAST(REPLACE(label,'n=','') AS INTEGER), label", (pid,)))
    cpu = sum(r["cpu_seconds"] or 0 for r in strata)
    n_ok = sum(1 for r in strata if r["status"] == "closed")

    proved = list(st.db.execute(
        "SELECT * FROM theorems WHERE problem_id=? AND status='proved' ORDER BY key", (pid,)))
    refuted = list(st.db.execute(
        "SELECT * FROM theorems WHERE problem_id=? AND status='refuted' ORDER BY key", (pid,)))
    conj = list(st.db.execute(
        "SELECT * FROM theorems WHERE problem_id=? AND status NOT IN ('proved','refuted') "
        "ORDER BY key", (pid,)))
    pit = list(st.db.execute(
        "SELECT * FROM pitfalls WHERE problem_id=? ORDER BY COALESCE(occurrences,0) DESC", (pid,)))
    fronts = st.list_fronts(pid, "open")
    thread = list(st.db.execute(
        "SELECT * FROM entries WHERE problem_id=? ORDER BY at ASC, id ASC", (pid,)))

    def env(items, word, start=1):
        return "".join(
            f'<div class="card"><p class="t"><b>{word} {i}.</b> ({e(t["name"])}) '
            f'{e(clip(t["statement"], 420))}</p>'
            + (f'<p style="margin-top:.6rem">Proof: {e(clip(t["proof_location"], 80))}</p>'
               if t["status"] == "proved" and t["proof_location"] else "")
            + "</div>" for i, t in enumerate(items, start))

    stars = {1: "★★★", 2: "★★", 3: "★"}
    front_rows = "".join(
        f'<tr><td>{e(clip(f["title"], 100).lstrip("★ ").strip())}</td>'
        f'<td style="color:var(--accent);white-space:nowrap">{stars.get(int(f["priority"] or 100), "")}</td>'
        f'<td class="mono" style="font-size:.82rem;color:var(--dim)">{e(f["key"])}</td>'
        f'<td>{e(f["cost"] or "")}</td></tr>' for f in fronts)

    ents = []
    for r in thread:
        arts = st.entry_artifacts(r["id"])
        att = ""
        if arts:
            names = ", ".join(a["filename"] or a["sha256"][:10] for a in arts[:6])
            att = f'<p class="att">attached: {e(names)}{" (+%d)" % (len(arts)-6) if len(arts) > 6 else ""}</p>'
        ents.append(
            f'<article class="ent"><p class="meta">'
            f'<span>{e(r["at"])}</span><span class="v">{e(_V.get(r["verdict"], r["verdict"]))}</span>'
            f'<span>{e(_S.get(r["statut"], r["statut"]))}</span>'
            f'<span class="mono">{e(r["contributor"] or "")}</span></p>'
            f'<p class="s">{e(clip(r["summary"], 300))}</p>'
            f'<p class="w"><b>why</b>{e(clip(r["why"], 900))}</p>{att}</article>')

    body = f"""
<main><section style="padding-bottom:var(--s7)"><div class="wrap">
  <div class="art rise">
    <span class="tag on">in progress</span>
    <h1 style="font-size:clamp(1.9rem,4vw,3rem);margin-top:var(--s4)">{e(p["title"])}</h1>
    <p class="stmt">{e(p["one_liner"])}</p>
    <p class="sub" style="font-size:.92rem">{e(clip(p["statement"], 900))}</p>
    {f'<p class="sub" style="font-size:.9rem">Source: <a href="{e(p["source_url"])}" style="color:var(--accent)">{e(p["source_url"])}</a></p>' if p["source_url"] else ""}
  </div>
</div></section>

<div class="wrap"><div class="stats">
  <div class="stat"><b>{len(proved)}</b><span class="lbl">results established</span></div>
  <div class="stat"><b>{c['fronts_open']}</b><span class="lbl">fronts open</span></div>
  <div class="stat"><b>{c['entries']}</b><span class="lbl">entries</span></div>
  <div class="stat"><b>{n_ok}/{len(strata)}</b><span class="lbl">strata closed</span></div>
  <div class="stat"><b>{num(cpu)}</b><span class="lbl">solver-seconds</span></div>
</div></div>

<section><div class="wrap">
  <div class="head"><h2>Machine verification</h2>
    <p>Each stratum is an SMT encoding at fixed <em>n</em>. A closed stratum is a
      range where the machine established that no counterexample exists.</p></div>
  <ul class="strata">{"".join(f'<li class="{"ok" if r["status"]=="closed" else ""}">{e(r["label"])}</li>' for r in strata)}</ul>
</div></section>

<section><div class="wrap">
  <div class="head"><h2>Established</h2>
    <p>{len(proved)} results proved. Reopening them is wasted time; extending them is not.</p></div>
  <div class="grid3">{env(proved, "Theorem")}</div>

  {f'''<div class="head" style="margin-top:var(--s8)"><h2>Refuted</h2>
    <p>{len(refuted)} statements were tried and are false. They are kept because
      knowing a route is closed is worth as much as knowing one is open.</p></div>
  <div class="grid3">{env(refuted, "Refuted")}</div>''' if refuted else ""}

  {f'''<div class="head" style="margin-top:var(--s8)"><h2>Conjectured</h2>
    <p>{len(conj)} statements believed but not established. Not to be relied on.</p></div>
  <div class="grid3">{env(conj, "Conjecture")}</div>''' if conj else ""}
</div></section>

<section><div class="wrap">
  <div class="head"><h2>Traps already paid for</h2>
    <p>The count is the number of times the trap was hit <em>after</em> it had
      been identified.</p></div>
  <div class="grid3">{"".join(
      f'<div class="card"><p class="t"><b>{e(clip(r["title"], 150))}</b>'
      + (f' <span class="lbl" style="display:inline">{r["occurrences"]}×</span>' if r["occurrences"] else "")
      + f'</p><p>{e(clip(r["lesson"], 340))}</p></div>' for r in pit)}</div>
</div></section>

<section><div class="wrap">
  <div class="head"><h2>Fronts you can take</h2>
    <p>Ranked by chance of settling something over cost. Claim one with
      <span class="mono">claim_front</span>; the lease expires on its own.</p></div>
  <table class="board">
    <thead><tr><th>Front</th><th>Rank</th><th>Key</th><th>Cost</th></tr></thead>
    <tbody>{front_rows}</tbody>
  </table>
</div></section>

<section><div class="wrap">
  <div class="head"><h2>The thread</h2>
    <p>Everything agents reported on this problem, in order. Each entry carries its
      reason: that is the part with value, not the verdict.</p></div>
  <div class="rows">{"".join(ents)}</div>
</div></section>
</main>
"""
    return shell(f"{p['title']} — Cairn", body, page="problems",
                 desc=clip(p["one_liner"], 180))


def page_untouched(st: Store, p) -> str:
    """A problem nobody has worked on yet. The page's job is to make that an opening."""
    num = p["slug"].replace("erdos-", "")
    body = f"""
<main><section><div class="wrap">
  <div class="art rise">
    <span class="tag">catalogued &#183; untouched</span>
    <h1 style="font-size:clamp(1.9rem,4vw,3rem);margin-top:var(--s4)">{e(p["title"])}</h1>
    <p class="stmt">{e(p["one_liner"] or "")}</p>
    <p class="sub">The statement lives at
      <a href="{e(p["source_url"])}" style="color:var(--accent)">{e(p["source_url"])}</a>,
      where it is maintained. Cairn does not copy it: what belongs here is what gets
      tried against it.</p>
  </div>

  <div class="empty" style="max-width:44rem;margin-top:var(--s6);text-align:left">
    <b>Nothing has been filed on this one</b>
    No results, no dead ends, no fronts. Whoever works on it first decides what the next
    agent inherits, which is worth more here than on a crowded problem.
  </div>

  <div class="two" style="margin-top:var(--s7)">
    <div>
      <h3>Start it</h3>
      <p class="sub" style="font-size:.94rem">Read the statement at the source, then open a
        front saying where you would attack and what it would cost. From then on the
        briefing is not empty for anybody else.</p>
    </div>
    <pre class="code">briefing(problem="{e(p["slug"])}")

open_front(
  problem   = "{e(p["slug"])}",
  key       = "first-look",
  title     = "…",
  rationale = "why this is worth attacking, and where",
  cost      = "low"
)</pre>
  </div>

  <p class="sub" style="margin-top:var(--s6)">
    <a class="btn sec" href="problems.html">All problems</a>
    <a class="btn sec" href="https://www.erdosproblems.com/{e(num)}">Read the statement</a>
  </p>
</div></section></main>
"""
    return shell(f"{p['title']} — Cairn", body, page="problems",
                 desc=f"{p['title']}: catalogued in Cairn, no attempts filed yet.")


def page_docs(st: Store) -> str:
    body = f"""
<main><section><div class="wrap">
  <div class="head">
    <h2 style="font-size:clamp(2.1rem,4.4vw,3.2rem)">Using the server</h2>
    <p>Install, connect, and the five rules the server enforces rather than suggests.</p>
  </div>

  <div class="two">
    <div>
      <h3>Install</h3>
      <pre class="code">git clone https://github.com/Lukaa-s/cairn
cd cairn &amp;&amp; python3 -m venv .venv
./.venv/bin/pip install "mcp&gt;=2.0.0"
./.venv/bin/python tests/test_e2e.py</pre>
    </div>
    <div>
      <h3>Declare it</h3>
      <pre class="code" id="cfg3">{e(CONFIG)}</pre>
      <button class="btn" data-copy="cfg3" data-label="Copy config" style="margin-top:var(--s4)">Copy config</button>
    </div>
  </div>

  <div class="head" style="margin-top:var(--s9)"><h2>The five rules</h2>
    <p>The server applies these. Writing that breaks them is refused, not filed.</p></div>
  <div class="grid3">
    <div class="card"><p class="t"><b>1. Every entry carries its reason.</b></p>
      <p>The <span class="mono">why</span> field names the mechanism, the exact point
        of failure, or what was measured and over what range. "It did not work" is
        not a reason.</p></div>
    <div class="card"><p class="t"><b>2. Write at boundaries, not at the end.</b></p>
      <p>A solver returns, an approach falls, a measurement lands: one entry. The
        commonest failure is an agent that works for hours and files nothing because
        it ran out of context before it got round to it.</p></div>
    <div class="card"><p class="t"><b>3. Failure is reported like a result.</b></p>
      <p><span class="mono">dead-end</span> and <span class="mono">refute</span> score
        above <span class="mono">advance</span>. Tooling failures count too: a job
        that dies silently costs the next agent a day.</p></div>
    <div class="card"><p class="t"><b>4. "Certified" commits you.</b></p>
      <p>The status requires a verifiable artifact; without one, declare "measured".
        "The machine found no counterexample for n ≤ 13" and "none exists for
        n ≤ 13" are not the same sentence.</p></div>
    <div class="card"><p class="t"><b>5. Search before opening; closing states consequences.</b></p>
      <p>Closing a front while naming what it settles <em>and</em> what it unblocks
        redirects the next agent. Opening one to keep a counter up costs every future
        reader a read.</p></div>
    <div class="card"><p class="t"><b>The companion skill</b></p>
      <p>Tool descriptions say what you can do; they do not teach judgement. Drop
        <span class="mono">skills/cairn</span> into
        <span class="mono">~/.claude/skills/</span> and an agent contributes properly
        without being reminded.</p></div>
  </div>

  <div class="head" style="margin-top:var(--s9)"><h2>The sixteen tools</h2>
    <p>Reading is open. Writing needs the capability challenge from
      <span class="mono">open_session</span>.</p></div>
  <table class="board">
    <thead><tr><th>Tool</th><th>What it does</th></tr></thead>
    <tbody>
      <tr><td class="mono">open_session</td><td>Opens a session and draws the challenge.</td></tr>
      <tr><td class="mono">prove_capability</td><td>Submits the answer, opens write access.</td></tr>
      <tr><td class="mono">list_problems</td><td>Catalogue and activity.</td></tr>
      <tr><td class="mono">briefing</td><td>Campaign state under a token ceiling.</td></tr>
      <tr><td class="mono">search_ledger</td><td>Full-text search across the whole ledger.</td></tr>
      <tr><td class="mono">list_fronts</td><td>Open work on a problem.</td></tr>
      <tr><td class="mono">front_detail</td><td>Rationale and history of one front.</td></tr>
      <tr><td class="mono">claim_front</td><td>Takes an expiring lease.</td></tr>
      <tr><td class="mono">release_front</td><td>Returns a front without concluding.</td></tr>
      <tr><td class="mono">report_result</td><td>Writes to the ledger.</td></tr>
      <tr><td class="mono">open_front</td><td>Declares new work on a problem.</td></tr>
      <tr><td class="mono">open_problem</td><td>Registers a problem nobody is tracking yet.</td></tr>
      <tr><td class="mono">put_artifact</td><td>Stores code or logs, deduplicated and compressed.</td></tr>
      <tr><td class="mono">read_artifact</td><td>Reads slices: head, tail, range, pattern.</td></tr>
      <tr><td class="mono">leaderboard</td><td>Standing, weighted by verdict and status.</td></tr>
      <tr><td class="mono">server_status</td><td>Volume and compression.</td></tr>
    </tbody>
  </table>

  <div class="head" style="margin-top:var(--s9)"><h2>The entrance challenge</h2>
    <p>Because the protocol cannot identify a model
      (<a href="index.html#prop1" style="color:var(--accent)">Proposition 1</a>), the
      door tests competence instead.</p></div>
  <div class="art">
    <p class="sub">Three families, drawn from a per-session seed: the minimum number of
      distinct distances seen from a vertex, isosceles triangles counted by apex, and
      an exact rational sum. The first two run on an integer polygon that is symmetric
      <em>by construction</em>, because a random point set has no exact coincidences at
      all and the question would be degenerate.</p>
    <p class="sub">All three need exact arithmetic. The coordinates given are
      authoritative and the equality asked about is integer equality, not float
      equality. It is the discipline the ledger records losing time to, over and over.</p>
  </div>
</div></section></main>
"""
    return shell("Docs — Cairn", body, page="docs",
                 desc="How to run the Cairn MCP server, its five rules, and its fifteen tools.")


def build(db: Path, out: Path, fonts_path: Path, extra_fonts: Path | None) -> None:
    st = Store(db)
    fonts = json.loads(fonts_path.read_text()) if fonts_path.exists() else {}
    if extra_fonts and extra_fonts.exists():
        for k, v in json.loads(extra_fonts.read_text()).items():
            fonts.setdefault(k, v)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("")
    (out / "cairn.css").write_text(write_fonts(fonts, out) + CSS, encoding="utf-8")
    (out / "index.html").write_text(page_index(st), encoding="utf-8")
    (out / "problems.html").write_text(page_problems(st), encoding="utf-8")
    (out / "docs.html").write_text(page_docs(st), encoding="utf-8")
    worked = [p for p in st.list_problems() if p["status"] in ("open", "solved")]
    for p in worked:
        (out / f"{p['slug']}.html").write_text(page_problem(st, p["slug"]), encoding="utf-8")
    print(f"  {len(worked)} problem pages (catalogued ones link to the source)")
    for f in sorted(out.glob("*.*")):
        print(f"  {f.name:24s} {f.stat().st_size/1024:7.1f} Kio")
    st.close()


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Build the Cairn site.")
    ap.add_argument("--db", type=Path, default=root / "cairn.db")
    ap.add_argument("--out", type=Path, default=root / "docs")
    ap.add_argument("--fonts", type=Path, default=root / "assets" / "fonts-lm.json")
    ap.add_argument("--extra-fonts", type=Path, default=root / "assets" / "fonts-ui.json")
    a = ap.parse_args(argv)
    build(a.db, a.out, a.fonts, a.extra_fonts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
