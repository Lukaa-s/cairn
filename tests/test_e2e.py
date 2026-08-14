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

DB = Path(tempfile.mkdtemp(prefix="cairn-e2e-")) / "test.db"
os.environ["CAIRN_DB"] = str(DB)

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
        ok("les 15 outils sont exposés", len(tools) == 15, f"{len(tools)}")

        r = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                       "contributor": "testeur"}))
        ok("open_session accepte", r.get("ok") is True, str(r)[:200])
        sid = r["session"]
        ok("aucune attestation sans sampling", r["identite"]["modele_atteste"] is None)
        ok("la confiance est annoncée non vérifiée", r["identite"]["confiance"] == "non vérifié")
        ok("le client est identifié par le protocole", bool(r["identite"]["client"]),
           r["identite"]["client"])

        chall = r["epreuve"]
        print(f"    épreuve tirée : {chall['type']}")

        bad = payload(await c.call_tool("prove_capability", {"session": sid, "answer": "0"}))
        ok("mauvaise réponse refusée", bad.get("correct") is False)

        w = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "tentative d'écriture sans droit",
            "why": "ceci ne doit pas passer car la session n'a pas prouvé sa capacité du tout."}))
        ok("écriture fermée avant l'épreuve", w.get("ok") is False and "PermissionError" in w.get("error", ""))

        answer = solve(chall["type"], chall["enonce"])
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
        ok("la recherche retrouve l'impasse", any("symétrisation" in str(x) for x in s["resultats"]))
        ok("la recherche renvoie le pourquoi",
           any(x.get("pourquoi") for x in s["resultats"] if x["type"] == "entry"))

        # --- claim / lease
        cl = payload(await c.call_tool("claim_front", {"session": sid, "problem": "test-42",
                                                       "front": "front-a"}))
        ok("front réservé", cl.get("ok") is True, str(cl)[:150])
        lf = payload(await c.call_tool("list_fronts", {"problem": "test-42"}))
        ok("la réservation est visible",
           any(f["front"] == "front-a" and f["pris_par"] == "testeur" for f in lf["fronts"]))

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
        ok("lecture par préfixe et par tranche", rd.get("ok") and "ligne 4999" in rd["contenu"])
        g = payload(await c.call_tool("read_artifact", {"sha256": sha, "mode": "grep",
                                                         "pattern": "ligne 4242", "lines": 5}))
        ok("grep dans un artefact", g.get("ok") and "4242" in g["contenu"])

        # --- the real write
        w = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "front": "front-a", "verdict": "close",
            "statut": "certified",
            "summary": "front-a clos : la borne tient sur toute la boîte",
            "why": "Le plancher mesuré vaut 5,3e-3 sur la boîte entière, certifié en "
                   "arithmétique exacte à 40 décimales après re-polissage des argmins.",
            "artifacts": [sha]}))
        ok("écriture acceptée", w.get("ok") is True, str(w)[:200])
        ok("le front est clos par le verdict", w.get("front_clos") is True)

        dup = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "front-a clos : la borne tient sur toute la boîte",
            "why": "Le plancher mesuré vaut 5,3e-3 sur la boîte entière, certifié en "
                   "arithmétique exacte à 40 décimales après re-polissage des argmins."}))
        ok("quasi-doublon intercepté", dup.get("ok") is False and "quasi_doublon" in dup)

        forced = payload(await c.call_tool("report_result", {
            "session": sid, "problem": "test-42", "verdict": "advance", "statut": "measured",
            "summary": "front-a clos : la borne tient sur toute la boîte",
            "why": "Le plancher mesuré vaut 5,3e-3 sur la boîte entière, certifié en "
                   "arithmétique exacte à 40 décimales après re-polissage des argmins.",
            "force": True}))
        ok("force=true passe outre", forced.get("ok") is True)

        fd = payload(await c.call_tool("front_detail", {"problem": "test-42", "front": "front-a"}))
        ok("le détail du front porte son historique", len(fd["historique"]) >= 1)
        ok("l'artefact est rattaché à l'entrée",
           any(h["artefacts"] for h in fd["historique"]))

        nf = payload(await c.call_tool("open_front", {
            "session": sid, "problem": "test-42", "key": "front-c", "title": "Chantier suivant",
            "rationale": "Une piste ouverte pour remplacer celle qui vient de se fermer, "
                         "conformément à la règle une fermée une ouverte.",
            "cost": "medium", "gain": "continuité", "priority": 3}))
        ok("ouverture d'un nouveau front", nf.get("ok") is True)

        lb = payload(await c.call_tool("leaderboard", {}))
        ok("le classement compte le contributeur",
           any(x["contributeur"] == "testeur" for x in lb["classement"]))

        stt = payload(await c.call_tool("server_status", {}))
        ok("état du serveur cohérent", stt.get("ok") and stt["artefacts"]["nombre"] >= 1)

    print("\n▸ Protocole 2026-07-28 : la sonde est interdite par la spec")
    async with make_client(srv, "claude-opus-5-20260101", mode="auto") as c:
        r = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                       "contributor": "moderne"}))
        idt = r["identite"]
        ok("le protocole moderne est bien négocié", idt["protocole"] == "2026-07-28",
           str(idt["protocole"]))
        ok("aucune attestation possible sur protocole moderne",
           idt["modele_atteste"] is None and "NoBackChannel" in (idt["attestation"] or ""),
           str(idt)[:220])
        ok("la dégradation est silencieuse et la session reste utilisable", r.get("ok") is True)

    print("\n▸ Protocole ≤2025-11-25 : la sonde fonctionne")
    async with make_client(srv, "claude-opus-5-20260101", mode="legacy") as c:
        r = payload(await c.call_tool("open_session", {"model": "je-mens", "contributor": "attesté"}))
        idt = r["identite"]
        ok("le modèle est attesté par le protocole",
           r.get("ok") and idt["modele_atteste"] == "claude-opus-5-20260101", str(idt)[:250])
        ok("la confiance monte à 'attesté'", idt["confiance"] == "attesté")
        ok("l'attestation l'emporte sur la déclaration mensongère",
           idt["modele_declare"] == "je-mens" and idt["modele_atteste"].startswith("claude-opus"))

    print("\n▸ Protocole ≤2025-11-25 : modèle sous le seuil, déclaration flatteuse")
    async with make_client(srv, "claude-haiku-4-5-20251001", mode="legacy") as c:
        r = payload(await c.call_tool("open_session", {"model": "claude-opus-5",
                                                       "contributor": "menteur"}))
        ok("un modèle faible attesté est refusé malgré une déclaration flatteuse",
           r.get("ok") is False and "attesté" in r.get("reason", ""), str(r)[:250])

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
