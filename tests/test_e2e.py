"""End-to-end exercise of the Cairn server over the real MCP protocol.

Two things here are worth more than coverage:

* The challenge is solved from its statement alone, by a parser that has never
  seen the generator's answer. If that stops working, the gate has become either
  ambiguous or unsolvable, and both are silent failures in production.
* The sampling probe is driven by a client that actually implements sampling, so
  the one protocol path to a model identity is tested rather than assumed --
  including the case where the attested model is below the bar and must be
  refused despite a valid session.

Run:  .venv/bin/python tests/test_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="cairn-e2e-"))
DB = _TMP / "test.db"
os.environ["CAIRN_DB"] = str(DB)
# The server exports to the text ledger after every write. Point that at the
# temp directory too, or a test run silently appends test-42 to the real one.
os.environ["CAIRN_LEDGER"] = str(_TMP / "ledger")

import mcp.types as types  # noqa: E402
from mcp import Client  # noqa: E402

PASS, FAIL = [], []


def ok(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✔' if cond else '✘'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def payload(res) -> dict | str:
    """Unwrap a tool result into the value the tool returned."""
    if getattr(res, "structured_content", None):
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    blocks = getattr(res, "content", []) or []
    text = "\n".join(getattr(b, "text", "") for b in blocks)
    try:
        return json.loads(text)
    except Exception:
        return text


# ------------------------------------------------------- solving the challenge

_PT = re.compile(r"\((-?\d+),(-?\d+)\)")


def solve(kind: str, prompt: str) -> str:
    if kind in ("min_distinct_distances", "isosceles_count"):
        pts = [(int(a), int(b)) for a, b in _PT.findall(prompt)]
        assert len(pts) >= 8, f"parsed only {len(pts)} points"
        n = len(pts)
        if kind == "min_distinct_distances":
            counts = []
            for i, (xi, yi) in enumerate(pts):
                counts.append(len({(xi - x) ** 2 + (yi - y) ** 2
                                   for j, (x, y) in enumerate(pts) if j != i}))
            m = min(counts)
            return f"{m},{counts.count(m)}"
        total = 0
        for i, (xi, yi) in enumerate(pts):
            buckets: dict[int, int] = {}
            for j, (x, y) in enumerate(pts):
                if j == i:
                    continue
                d = (xi - x) ** 2 + (yi - y) ** 2
                buckets[d] = buckets.get(d, 0) + 1
            total += sum(c * (c - 1) // 2 for c in buckets.values())
        return str(total)

    if kind == "exact_rational":
        m = re.search(r"k=1\}\^\{(\d+)\}.*?k².*?\+\s*(\d+)·k\s*\+\s*(\d+)", prompt, re.S)
        assert m, "could not parse the rational challenge"
        N, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        s = sum(Fraction(1, k * k + a * k + b) for k in range(1, N + 1))
        return f"{s.numerator}/{s.denominator}"

    raise AssertionError(f"unknown challenge kind {kind}")


# ------------------------------------------------------------- sampling client

def sampler(model_name: str):
    async def cb(context, params):
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="ok"),
            model=model_name,
            stopReason="endTurn",
        )
    return cb


def make_client(server, model: str | None, mode: str = "auto"):
    if model is None:
        return Client(server, raise_exceptions=True, mode=mode)
    return Client(
        server,
        raise_exceptions=True,
        mode=mode,
        sampling_callback=sampler(model),
        sampling_capabilities=types.SamplingCapability(),
    )


# ---------------------------------------------------------------------- flows

async def run() -> None:
    from cairn.server import server as srv
    from cairn.store import Store

    # A minimal campaign so the read tools have something to chew on.
    st = Store(DB)
    pid = st.upsert_problem(
        slug="test-42", title="Problème de test",
        statement="Un énoncé de test pour valider le registre.",
        one_liner="État: en cours de validation.", status="open",
    )
    st.upsert_front(pid, "test-42", key="front-a", title="Premier chantier",
                    rationale="Une piste à explorer sérieusement pour valider le stockage.",
                    cost="low", gain="validation", priority=1)
    st.upsert_front(pid, "test-42", key="front-b", title="Second chantier",
                    rationale="Une autre piste, pour tester la réservation concurrente.",
                    cost="high", gain="validation", priority=2)
    st.add_entry(pid, "test-42", front_id=None, verdict="refute", statut="refuted",
                 summary="La symétrisation naïve ne marche pas",
                 why="Cinq chemins sur cinq sont non monotones en coût de collapse, "
                     "remontée maximale 1,4e-2.", contributor="seed")
    st.close()

    print("\n▸ Session sans sampling (cas Claude Code aujourd'hui)")
    async with make_client(srv, None) as c:
        listed = await c.list_tools()
        tools = {t.name for t in getattr(listed, "tools", listed)}
        ok("the 16 tools are exposed", len(tools) == 16, f"{len(tools)}")

        r = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                       "contributor": "testeur"}))
        ok("open_session accepte", r.get("ok") is True, str(r)[:200])
        sid = r["session"]
        ok("aucune attestation sans sampling", r["identity"]["model_attested"] is None)
        ok("la confiance est annoncée non vérifiée", r["identity"]["confidence"] == "unverified")
        ok("le client est identifié par le protocole", bool(r["identity"]["client"]),
           r["identity"]["client"])

        chall = r["challenge"]
        print(f"    épreuve tirée : {chall['type']}")

        bad = payload(await c.call_tool("prove_capability", {"session": sid, "answer": "0"}))
        ok("mauvaise réponse refusée", bad.get("correct") is False)

        w = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "tentative d'écriture sans droit",
            "why": "ceci ne doit pas passer car la session n'a pas prouvé sa capacité du tout."}))
        ok("écriture fermée avant l'épreuve", w.get("ok") is False and "PermissionError" in w.get("error", ""))

        answer = solve(chall["type"], chall["prompt"])
        good = payload(await c.call_tool("prove_capability", {"session": sid, "answer": answer}))
        ok("épreuve résolue depuis son seul énoncé", good.get("correct") is True, str(good)[:200])
        ok("le rang passe à contributeur", good.get("tier") == "contributor")

        # --- reads
        for budget in (600, 1800, 6000):
            b = payload(await c.call_tool("briefing", {"problem": "test-42",
                                                       "budget_tokens": budget}))
            est = len(b) / 3.0
            ok(f"briefing tient dans {budget} tok", est <= budget, f"~{est:.0f}")

        s = payload(await c.call_tool("search_ledger", {"problem": "test-42",
                                                        "query": "symétrisation monotone"}))
        ok("la recherche retrouve l'impasse", any("symétrisation" in str(x) for x in s["results"]))
        ok("la recherche renvoie le pourquoi",
           any(x.get("why") for x in s["results"] if x["type"] == "entry"))

        # --- claim / lease
        cl = payload(await c.call_tool("claim_front", {"session": sid, "problem": "test-42",
                                                       "front": "front-a"}))
        ok("front réservé", cl.get("ok") is True, str(cl)[:150])
        lf = payload(await c.call_tool("list_fronts", {"problem": "test-42"}))
        ok("la réservation est visible",
           any(f["front"] == "front-a" and f["claimed_by"] == "testeur" for f in lf["fronts"]))

        # --- write discipline
        short = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "un résultat", "why": "trop court"}))
        ok("un `why` maigre est refusé", short.get("ok") is False and "why" in short.get("error", ""))

        nocert = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "certified",
            "summary": "un résultat certifié sans preuve jointe",
            "why": "on prétend certifier sans joindre le moindre artefact vérifiable, "
                   "ce que le registre doit refuser."}))
        ok("'certified' sans artefact est refusé", nocert.get("ok") is False)

        # --- artifacts
        big = "\n".join(f"ligne {i} :: résidu {i*0.001:.6f}" for i in range(5000))
        a = payload(await c.call_tool("put_artifact", {
            "session": sid, "filename": "run.log", "content": big, "kind": "log"}))
        ok("artefact stocké et compressé", a.get("ok") and a["stored"] < a["size"] / 5,
           f"{a.get('size')}→{a.get('stored')}")
        a2 = payload(await c.call_tool("put_artifact", {
            "session": sid, "filename": "copie.log", "content": big, "kind": "log"}))
        ok("contenu identique dédupliqué", a2.get("deduplicated") is True)

        sha = a["sha256"]
        rd = payload(await c.call_tool("read_artifact", {"sha256": sha[:8], "mode": "tail",
                                                          "lines": 3}))
        ok("lecture par préfixe et par tranche", rd.get("ok") and "ligne 4999" in rd["content"])
        g = payload(await c.call_tool("read_artifact", {"sha256": sha, "mode": "grep",
                                                         "pattern": "ligne 4242", "lines": 5}))
        ok("grep dans un artefact", g.get("ok") and "4242" in g["content"])

        # --- the real write
        w = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "front": "front-a", "verdict": "close",
            "statut": "certified",
            "summary": "front-a clos : la borne tient sur toute la boîte",
            "why": "Le plancher mesuré vaut 5,3e-3 sur la boîte entière, certifié en "
                   "arithmétique exacte à 40 décimales après re-polissage des argmins.",
            "artifacts": [sha]}))
        ok("écriture acceptée", w.get("ok") is True, str(w)[:200])
        ok("le front est clos par le verdict", w.get("front_closed") is True)

        dup = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "front-a clos : la borne tient sur toute la boîte",
            "why": "Le plancher mesuré vaut 5,3e-3 sur la boîte entière, certifié en "
                   "arithmétique exacte à 40 décimales après re-polissage des argmins."}))
        ok("quasi-doublon intercepté", dup.get("ok") is False and "near_duplicate" in dup)

        forced = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "front-a clos : la borne tient sur toute la boîte",
            "why": "Le plancher mesuré vaut 5,3e-3 sur la boîte entière, certifié en "
                   "arithmétique exacte à 40 décimales après re-polissage des argmins.",
            "force": True}))
        ok("force=true passe outre", forced.get("ok") is True)

        fd = payload(await c.call_tool("front_detail", {"problem": "test-42", "front": "front-a"}))
        ok("le détail du front porte son historique", len(fd["history"]) >= 1)
        ok("l'artefact est rattaché à l'entrée",
           any(h["artifacts"] for h in fd["history"]))

        nf = payload(await c.call_tool("open_front", {
            "session": sid, "problem": "test-42", "key": "front-c", "title": "Chantier suivant",
            "rationale": "Une piste ouverte pour remplacer celle qui vient de se fermer, "
                         "conformément à la règle une fermée une ouverte.",
            "cost": "medium", "gain": "continuité", "priority": 3}))
        ok("ouverture d'un nouveau front", nf.get("ok") is True)

        lb = payload(await c.call_tool("leaderboard", {}))
        ok("le classement compte le contributeur",
           any(x["contributor"] == "testeur" for x in lb.get("standing", [])))

        stt = payload(await c.call_tool("server_status", {}))
        ok("état du serveur cohérent", stt.get("ok") and stt["artifacts"]["count"] >= 1)

        # --- discipline des artefacts : une poignée fausse ne laisse rien derrière
        from cairn.store import Store as _S
        n_before = _S(DB).db.execute(
            "SELECT COUNT(*) FROM entries").fetchone()[0]
        badh = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "résultat avec une pièce jointe inexistante",
            "why": "la poignée d'artefact est inventée et l'écriture doit être refusée "
                   "proprement, sans demi-ligne fantôme dans la table.",
            "artifacts": ["deadbeefdeadbeef"]}))
        n_after = _S(DB).db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        ok("poignée d'artefact inconnue refusée", badh.get("ok") is False
           and "artifact" in badh.get("error", ""))
        ok("aucune demi-écriture ne subsiste", n_after == n_before, f"{n_before}→{n_after}")

        pfx = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "front": "front-c", "verdict": "advance",
            "statut": "certified",
            "summary": "mesure rattachée par un préfixe de hachage",
            "why": "les outils affichent des hachages raccourcis ; un modèle qui en recopie "
                   "un doit soit réussir soit échouer bruyamment, jamais joindre le mauvais fichier.",
            "artifacts": [sha[:12]]}))
        ok("préfixe de hachage résolu à l'écriture", pfx.get("ok") is True, str(pfx)[:200])

        # --- le bail appartient à qui l'a pris
        cl2 = payload(await c.call_tool("claim_front", {"session": sid, "problem": "test-42",
                                                        "front": "front-b"}))
        ok("second front réservé", cl2.get("ok") is True)

        r2 = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                        "contributor": "voleur"}))
        sid2 = r2["session"]
        ans2 = solve(r2["challenge"]["type"], r2["challenge"]["prompt"])
        payload(await c.call_tool("prove_capability", {"session": sid2, "answer": ans2}))
        steal = payload(await c.call_tool("release_front", {"session": sid2,
                                                            "problem": "test-42",
                                                            "front": "front-b"}))
        ok("un tiers ne libère pas le bail d'un autre", steal.get("ok") is False
           and "holder" in steal.get("error", ""), str(steal)[:200])

        bad_state = payload(await c.call_tool("list_problems", {"state": "n'importe quoi"}))
        ok("état de filtre invalide refusé", bad_state.get("ok") is False)

        # --- un problème catalogué se réveille à la première écriture
        _S(DB).upsert_problem(slug="cat-1", title="Un problème catalogué",
                              statement="", status="catalogued",
                              one_liner="tags seulement", tags="test-tag",
                              source_url="https://example.org/cat-1")
        wake = payload(await c.call_tool("open_front", {
            "session": sid, "problem": "cat-1", "key": "premier-regard",
            "title": "Premier regard",
            "rationale": "Ouvrir une entrée sur un problème catalogué doit le faire passer "
                         "de listé à travaillé, comme l'importeur le promet."}))
        ok("écriture acceptée sur un catalogué", wake.get("ok") is True, str(wake)[:200])
        lp = payload(await c.call_tool("list_problems", {"state": "worked", "query": "cat-1"}))
        ok("le catalogué réveillé devient travaillé",
           any(x["slug"] == "cat-1" for x in lp.get("problems", [])))

        _S(DB).upsert_problem(slug="cat-2", title="Un second catalogué",
                              statement="", status="catalogued", tags="garde-moi",
                              source_url="https://example.org/cat-2")
        upg = payload(await c.call_tool("open_problem", {
            "session": sid, "slug": "cat-2", "title": "Un second catalogué, énoncé apporté",
            "statement": "Pour tout n suffisamment grand, l'énoncé précis tient avec "
                         "quantificateurs explicites et notation définie."}))
        ok("un stub catalogué s'upgrade avec son énoncé",
           upg.get("ok") is True and upg.get("upgraded_from_catalogue") is True, str(upg)[:200])
        row = _S(DB).problem("cat-2")
        ok("l'upgrade préserve tags et source",
           row["tags"] == "garde-moi" and row["source_url"] == "https://example.org/cat-2")

    print("\n▸ Le registre texte : baux, identités, allers-retours")
    from cairn.store import Store as _S
    from cairn.sync import default_paths, import_

    ledger = Path(os.environ["CAIRN_LEDGER"])
    pj = json.loads((ledger / "problems" / "test-42.json").read_text(encoding="utf-8"))
    fb = next(f for f in pj["fronts"] if f["key"] == "front-b")
    ok("le bail voyage dans le registre texte",
       fb.get("claimed_by") == "testeur" and bool(fb.get("lease_expires")), str(fb)[:200])
    unclaimed = [f for f in pj["fronts"] if f["key"] != "front-b"]
    ok("les fronts libres ne portent pas de champs de bail",
       all("claimed_by" not in f for f in unclaimed))

    lines = [json.loads(x) for x in
             (ledger / "entries" / "test-42.jsonl").read_text(encoding="utf-8").splitlines()]
    with_uid = [x for x in lines if x.get("uid")]
    ok("les entrées neuves portent un uid", len(with_uid) >= 3, f"{len(with_uid)}")
    ok("le doublon forcé garde une identité propre",
       len({x["uid"] for x in with_uid}) == len(with_uid))

    db2 = _TMP / "reimport.db"
    import_(ledger, db2, verbose=False)
    st2 = _S(db2)
    n1 = _S(DB).db.execute("SELECT COUNT(*) FROM entries WHERE problem_id="
                           "(SELECT id FROM problems WHERE slug='test-42')").fetchone()[0]
    n2 = st2.db.execute("SELECT COUNT(*) FROM entries WHERE problem_id="
                        "(SELECT id FROM problems WHERE slug='test-42')").fetchone()[0]
    ok("l'aller-retour préserve chaque entrée, doublon forcé compris", n1 == n2, f"{n1}≠{n2}")
    fb2 = st2.db.execute("SELECT * FROM fronts WHERE key='front-b'").fetchone()
    ok("le bail survit à l'aller-retour", fb2["claimed_by"] == "testeur"
       and fb2["status"] == "claimed")
    n2b = st2.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    import_(ledger, db2, verbose=False)
    n2c = st2.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    ok("réimporter est idempotent", n2b == n2c, f"{n2b}→{n2c}")
    ok("un problème sans entrée n'a pas de fichier d'entrées",
       not (ledger / "entries" / "cat-2.jsonl").exists())

    print("\n▸ Chemins d'installation : dépôt contre roue installée")
    xc, xd = _TMP / "xdg-cache", _TMP / "xdg-data"
    os.environ["XDG_CACHE_HOME"], os.environ["XDG_DATA_HOME"] = str(xc), str(xd)
    fake_pkg = _TMP / "site-packages" / "cairn"
    (fake_pkg / "_ledger").mkdir(parents=True, exist_ok=True)
    db_w, led_w, seed_w = default_paths(fake_pkg)
    ok("mode roue : cache et données sous XDG, graine embarquée détectée",
       db_w == xc / "cairn" / "cairn.db" and led_w == xd / "cairn" / "ledger"
       and seed_w == fake_pkg / "_ledger", f"{db_w} {led_w} {seed_w}")
    repo = _TMP / "repo"
    (repo / "ledger").mkdir(parents=True, exist_ok=True)
    (repo / "cairn").mkdir(exist_ok=True)
    db_r, led_r, seed_r = default_paths(repo / "cairn")
    ok("mode dépôt : tout à la racine, pas de graine",
       db_r == repo / "cairn.db" and led_r == repo / "ledger" and seed_r is None)

    print("\n▸ Le site se construit depuis la même base")
    from cairn.web import build, verified_prefix
    vp = _S(_TMP / "vp.db")
    vpid = vp.upsert_problem(slug="vp", title="t", statement="un énoncé de test "
                             "suffisamment long pour la validation du schéma.")
    for n, s_ in ((10, "closed"), (11, "closed"), (12, "partial"), (14, "closed")):
        vp.db.execute("INSERT INTO strata(problem_id,label,status) VALUES(?,?,?)",
                      (vpid, f"n={n}", s_))
    vp.db.commit()
    ok("la borne vérifiée est calculée, jamais saisie", verified_prefix(vp, "vp") == 11,
       str(verified_prefix(vp, "vp")))
    vp.close()

    _S(DB).upsert_problem(slug="cat-3", title="Encore catalogué", statement="",
                          status="catalogued", one_liner="intact",
                          source_url="https://example.org/cat-3")
    site = _TMP / "docs"
    build(DB, site, _TMP / "absent.json", None)
    idx = (site / "index.html").read_text(encoding="utf-8")
    ok("index construit avec favicon et lien d'évitement",
       "data:image/svg+xml" in idx and "Skip to content" in idx)
    ok("la page d'un catalogué intact existe et invite",
       (site / "cat-3.html").exists()
       and "untouched" in (site / "cat-3.html").read_text(encoding="utf-8"))
    ok("le plan du site couvre chaque page",
       (site / "sitemap.xml").read_text().count("<loc>")
       == len(list(site.glob("*.html"))))

    print("\n▸ Protocole 2026-07-28 : la sonde est interdite par la spec")
    async with make_client(srv, "claude-opus-5-20260101", mode="auto") as c:
        r = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                       "contributor": "moderne"}))
        idt = r["identity"]
        ok("le protocole moderne est bien négocié", idt["protocol"] == "2026-07-28",
           str(idt["protocol"]))
        ok("aucune attestation possible sur protocole moderne",
           idt["model_attested"] is None and "NoBackChannel" in (idt["attestation"] or ""),
           str(idt)[:220])
        ok("la dégradation est silencieuse et la session reste utilisable", r.get("ok") is True)

    print("\n▸ Protocole ≤2025-11-25 : la sonde fonctionne")
    async with make_client(srv, "claude-opus-5-20260101", mode="legacy") as c:
        r = payload(await c.call_tool("open_session", {"model": "je-mens", "contributor": "attesté"}))
        idt = r["identity"]
        ok("le modèle est attesté par le protocole",
           r.get("ok") and idt["model_attested"] == "claude-opus-5-20260101", str(idt)[:250])
        ok("la confiance monte à 'attesté'", idt["confidence"] == "attested")
        ok("l'attestation l'emporte sur la déclaration mensongère",
           idt["model_declared"] == "je-mens" and idt["model_attested"].startswith("claude-opus"))

    print("\n▸ Protocole ≤2025-11-25 : modèle sous le seuil, déclaration flatteuse")
    async with make_client(srv, "claude-haiku-4-5-20251001", mode="legacy") as c:
        r = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                       "contributor": "menteur"}))
        ok("un modèle faible attesté est refusé malgré une déclaration flatteuse",
           r.get("ok") is False and "attested model" in r.get("reason", ""), str(r)[:250])

    print("\n▸ Déclaration honnête d'un modèle sous le seuil")
    async with make_client(srv, None) as c:
        r = payload(await c.call_tool("open_session", {"model": "claude-haiku-4-5",
                                                       "contributor": "honnête"}))
        ok("un modèle faible qui se déclare est refusé", r.get("ok") is False,
           str(r)[:200])

    print("\n▸ Le serveur démarre vraiment en sous-processus stdio")
    proc = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-m", "cairn.server"],
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2026-07-28", "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"}}}) + "\n",
        capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        env={**os.environ, "CAIRN_DB": str(DB)},
    )
    ok("initialize répond sur stdio", '"protocolVersion"' in proc.stdout,
       (proc.stdout or proc.stderr)[:200])
    ok("le nom du serveur est annoncé", '"cairn"' in proc.stdout)


if __name__ == "__main__":
    asyncio.run(run())
    print(f"\n{len(PASS)} passés, {len(FAIL)} échoués")
    if FAIL:
        print("ÉCHECS : " + ", ".join(FAIL))
    sys.exit(1 if FAIL else 0)
