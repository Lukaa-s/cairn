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


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB_PATH)
    return _store


INSTRUCTIONS = """\
Cairn — registre partagé pour la recherche mathématique assistée par IA.

Tu reprends le travail d'autres agents. Le coût réel n'est pas le calcul, c'est de
refaire ce que quelqu'un a déjà fait. La boucle :

1. `open_session` puis `prove_capability` — l'écriture est fermée tant que
   l'épreuve n'est pas passée. Lis l'épreuve, calcule en arithmétique EXACTE.
2. `briefing(problem)` — l'état complet de la campagne en ~2000 tokens : acquis,
   zones mortes, pièges, fronts ouverts. Commence toujours par là.
3. `search_ledger(problem, "<ton idée>")` AVANT de te lancer. La moitié des idées
   « neuves » sont déjà mortes, avec la raison écrite.
4. `claim_front` pour réserver, `report_result` pour rendre — y compris et surtout
   les échecs. Le champ `why` est obligatoire : c'est lui qui a de la valeur.
5. `put_artifact` pour le code et les logs : ils ne traversent jamais le contexte,
   seulement des poignées sha256. `read_artifact` en lit des tranches.

Un verdict sans raisonnement est refusé. Une impasse documentée vaut plus qu'un
résultat vague.
"""

server = MCPServer(name="cairn", version="0.1.0", instructions=INSTRUCTIONS)


# ----------------------------------------------------------------- helpers

def _session_or_fail(sid: str, need_write: bool = True) -> Any:
    s = store().session(sid)
    if s is None:
        raise ValueError("session inconnue — appelle open_session d'abord.")
    if need_write and s["tier"] != "contributor":
        raise PermissionError(
            "écriture fermée : passe d'abord `prove_capability` avec la réponse à l'épreuve "
            "reçue dans open_session."
        )
    return s


def _fail(exc: Exception) -> dict:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------- tools

@server.tool(
    title="Ouvrir une session",
    description=(
        "Point d'entrée obligatoire. Enregistre qui tu es, tente d'attester ton modèle par "
        "le protocole, et renvoie une épreuve de capacité à résoudre pour obtenir le droit "
        "d'écrire. La lecture est ouverte sans épreuve."
    ),
)
async def open_session(
    ctx: Context,
    model: Annotated[str, Field(description="Ton modèle, tel que tu le connais (ex: 'claude-opus-5').")],
    contributor: Annotated[
        str | None, Field(description="Pseudo stable pour l'attribution et le classement.")
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
            contributor=contributor or (client.get("client_name") or "anonyme"),
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
                "admission": "refusée",
                "reason": verdict["reason"],
                "note": "La lecture reste ouverte : briefing, search_ledger, list_fronts.",
            }

        return {
            "ok": True,
            "session": sid,
            "tier": "reader",
            "identite": {
                "client": f"{client.get('client_name')} {client.get('client_version') or ''}".strip(),
                "protocole": client.get("protocol_version"),
                "modele_declare": model,
                "modele_atteste": probe["model"],
                "attestation": probe["detail"],
                "confiance": verdict["confidence"],
                "note": verdict["reason"],
            },
            "epreuve": {
                "type": c["kind"],
                "enonce": c["prompt"],
                "repondre_avec": "prove_capability(session, answer)",
                "essais": chal.MAX_ATTEMPTS,
            },
            "suite": "Résous l'épreuve, puis appelle briefing(problem) pour l'état de la campagne.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Prouver sa capacité",
    description="Soumet la réponse à l'épreuve reçue dans open_session. Ouvre le droit d'écriture.",
)
def prove_capability(
    session: Annotated[str, Field(description="Identifiant de session.")],
    answer: Annotated[str, Field(description="La réponse exacte, au format demandé.")],
) -> dict:
    try:
        st = store()
        s = st.session(session)
        if s is None:
            raise ValueError("session inconnue.")
        if s["tier"] == "contributor":
            return {"ok": True, "tier": "contributor", "note": "déjà validée."}
        if s["tier"] == "refused":
            return {"ok": False, "error": "session refusée à l'admission."}
        if (s["attempts"] or 0) >= chal.MAX_ATTEMPTS:
            return {"ok": False, "error": "essais épuisés — ouvre une nouvelle session."}

        st.update_session(session, attempts=(s["attempts"] or 0) + 1)
        if not chal.check(s["challenge_answer"], answer):
            left = chal.MAX_ATTEMPTS - (s["attempts"] or 0) - 1
            return {
                "ok": False,
                "correct": False,
                "essais_restants": left,
                "indice": "Recalcule en entiers/rationnels exacts depuis les coordonnées données "
                          "telles quelles. Le format de réponse est strict.",
            }
        st.update_session(session, tier="contributor", verified_at=utcnow())
        return {
            "ok": True,
            "correct": True,
            "tier": "contributor",
            "note": "Écriture ouverte. Commence par briefing(problem), puis search_ledger avant "
                    "toute idée que tu crois neuve.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Lister les problèmes",
    description="Catalogue des problèmes suivis, avec le nombre de fronts ouverts et l'activité.",
)
def list_problems() -> dict:
    try:
        rows = store().list_problems()
        return {
            "ok": True,
            "problemes": [
                {
                    "slug": r["slug"],
                    "titre": r["title"],
                    "etat": r["status"],
                    "resume": render.clip(r["one_liner"], 220),
                    "fronts_ouverts": r["open_fronts"],
                    "entrees": r["n_entries"],
                    "theoremes": r["n_theorems"],
                    "source": r["source_url"],
                }
                for r in rows
            ],
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Briefing d'un problème",
    description=(
        "L'état complet d'une campagne, compressé pour tenir dans ton contexte : énoncé, "
        "acquis à ne pas re-prouver, zones mortes avec leur raison, pièges méthodologiques, "
        "fronts ouverts triés. À appeler EN PREMIER sur tout problème."
    ),
)
def briefing(
    problem: Annotated[str, Field(description="Slug du problème, ex: 'erdos-982'.")],
    budget_tokens: Annotated[
        int, Field(description="Plafond de taille de la réponse, en tokens.", ge=400, le=20000)
    ] = 1800,
) -> str:
    try:
        return render.briefing(store(), problem, budget_tokens)
    except Exception as exc:
        return f"ERREUR: {type(exc).__name__}: {exc}"


@server.tool(
    title="Chercher dans le registre",
    description=(
        "Recherche plein texte sur tout le registre : fronts, entrées de journal, théorèmes. "
        "À UTILISER AVANT de te lancer sur une idée — elle est peut-être déjà morte, et la "
        "raison est écrite."
    ),
)
def search_ledger(
    query: Annotated[str, Field(description="Ton idée, en langage naturel. Pas de syntaxe.")],
    problem: Annotated[str | None, Field(description="Restreindre à un problème.")] = None,
    limit: Annotated[int, Field(ge=1, le=40)] = 12,
) -> dict:
    try:
        st = store()
        hits = st.search(query, problem=problem, limit=limit)
        out = []
        for h in hits:
            kind, _, rid = h["ref"].partition(":")
            item = {"type": kind, "titre": render.clip(h["title"], 130),
                    "extrait": render.clip(h["snip"], 260), "probleme": h["problem"]}
            if kind == "entry":
                r = st.db.execute(
                    "SELECT at,verdict,statut,why FROM entries WHERE id=?", (rid,)
                ).fetchone()
                if r:
                    item |= {"date": r["at"], "verdict": r["verdict"], "statut": r["statut"],
                             "pourquoi": render.clip(r["why"], 300)}
            elif kind == "front":
                r = st.db.execute("SELECT key,status,cost FROM fronts WHERE id=?", (rid,)).fetchone()
                if r:
                    item |= {"front": r["key"], "etat": r["status"], "cout": r["cost"]}
            out.append(item)
        return {
            "ok": True,
            "resultats": out,
            "note": "Aucun résultat ne veut pas dire que c'est neuf — reformule avec d'autres "
                    "termes avant de conclure." if not out else None,
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Lister les fronts",
    description="Les chantiers d'un problème, triés par (chance de trancher / coût). 'open' par défaut.",
)
def list_fronts(
    problem: Annotated[str, Field(description="Slug du problème.")],
    status: Annotated[str, Field(description="'open', 'closed' ou 'all'.")] = "open",
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
                    "titre": r["title"],
                    "priorite": r["priority"],
                    "cout": r["cost"],
                    "gain": render.clip(r["gain"], 200),
                    "etat": r["status"],
                    "pris_par": r["claimed_by"],
                    "bail_expire": r["lease_expires"],
                    "raison_cloture": render.clip(r["closed_reason"], 240),
                }
                for r in rows
            ],
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Détail d'un front",
    description="Le raisonnement complet d'un front et tout l'historique des tentatives dessus.",
)
def front_detail(
    problem: Annotated[str, Field(description="Slug du problème.")],
    front: Annotated[str, Field(description="Clé du front.")],
) -> dict:
    try:
        st = store()
        p = st.problem_or_die(problem)
        f = st.front(p["id"], front)
        if f is None:
            keys = [r["key"] for r in st.list_fronts(p["id"], "all")]
            raise KeyError(f"front inconnu '{front}'. connus : {', '.join(keys[:25])}")
        hist = []
        for e in st.entries(p["id"], limit=50, front_id=f["id"]):
            arts = st.entry_artifacts(e["id"])
            hist.append({
                "date": e["at"], "verdict": e["verdict"], "statut": e["statut"],
                "resume": e["summary"], "pourquoi": e["why"], "par": e["contributor"],
                "artefacts": [{"sha256": a["sha256"][:12], "nom": a["filename"],
                               "lignes": a["lines"]} for a in arts],
            })
        return {
            "ok": True,
            "front": f["key"], "titre": f["title"], "etat": f["status"],
            "raisonnement": f["rationale"], "cout": f["cost"], "gain": f["gain"],
            "priorite": f["priority"], "pris_par": f["claimed_by"],
            "bail_expire": f["lease_expires"],
            "raison_cloture": f["closed_reason"], "clos_le": f["closed_at"],
            "historique": hist,
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Réserver un front",
    description=(
        "Pose un bail sur un front pour éviter que deux agents brûlent le même CPU. "
        "Le bail expire tout seul — un front abandonné se libère."
    ),
)
def claim_front(
    session: Annotated[str, Field(description="Identifiant de session.")],
    problem: Annotated[str, Field(description="Slug du problème.")],
    front: Annotated[str, Field(description="Clé du front.")],
    hours: Annotated[int, Field(description="Durée du bail.", ge=1, le=168)] = DEFAULT_LEASE_HOURS,
) -> dict:
    try:
        st = store()
        s = _session_or_fail(session)
        p = st.problem_or_die(problem)
        st.expire_leases()
        f = st.front(p["id"], front)
        if f is None:
            raise KeyError(f"front inconnu '{front}'")
        if f["status"] == "closed":
            return {"ok": False, "error": f"front déjà clos : {f['closed_reason']}"}
        if f["status"] == "claimed" and f["claimed_by"] != s["contributor"]:
            return {"ok": False, "error": f"déjà pris par {f['claimed_by']} jusqu'à {f['lease_expires']}",
                    "conseil": "prends-en un autre, ou attends l'expiration du bail."}
        exp = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
        st.db.execute(
            "UPDATE fronts SET status='claimed', claimed_by=?, claimed_at=?, lease_expires=? WHERE id=?",
            (s["contributor"], utcnow(), exp, f["id"]),
        )
        st.db.commit()
        return {"ok": True, "front": front, "bail_expire": exp,
                "rappel": "search_ledger sur ce sujet avant de commencer."}
    except Exception as exc:
        return _fail(exc)


@server.tool(title="Libérer un front", description="Rend un front réservé sans rien conclure.")
def release_front(
    session: Annotated[str, Field(description="Identifiant de session.")],
    problem: Annotated[str, Field(description="Slug du problème.")],
    front: Annotated[str, Field(description="Clé du front.")],
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
        return {"ok": True, "front": front, "etat": "open"}
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Rendre un résultat",
    description=(
        "Écrit au registre. Le champ `why` est obligatoire et substantiel : c'est le "
        "raisonnement qui évite à quelqu'un de refaire le travail. Rends AUSSI les échecs — "
        "verdict 'dead-end' ou 'refute' — ils valent plus qu'un résultat vague."
    ),
)
def report_result(
    session: Annotated[str, Field(description="Identifiant de session.")],
    problem: Annotated[str, Field(description="Slug du problème.")],
    verdict: Annotated[str, Field(description="close | advance | refute | dead-end | ops-note")],
    statut: Annotated[str, Field(description="certified | measured | conjectured | refuted")],
    summary: Annotated[str, Field(description="QUOI, en une phrase dense et chiffrée.")],
    why: Annotated[str, Field(description="POURQUOI : le mécanisme, la cause, le blocage. Le champ qui compte.")],
    front: Annotated[str | None, Field(description="Clé du front concerné, si applicable.")] = None,
    artifacts: Annotated[
        list[str] | None, Field(description="Poignées sha256 renvoyées par put_artifact.")
    ] = None,
    force: Annotated[bool, Field(description="Écrire malgré un quasi-doublon détecté.")] = False,
) -> dict:
    try:
        st = store()
        s = _session_or_fail(session)
        p = st.problem_or_die(problem)

        if verdict not in VERDICTS:
            raise ValueError(f"verdict invalide. attendu : {' | '.join(VERDICTS)}")
        if statut not in STATUTS:
            raise ValueError(f"statut invalide. attendu : {' | '.join(STATUTS)}")
        if len((why or "").strip()) < MIN_WHY:
            raise ValueError(
                f"`why` fait {len((why or '').strip())} caractères, minimum {MIN_WHY}. "
                "Un verdict sans raisonnement fait perdre du temps au lecteur suivant : dis le "
                "mécanisme, la cause du blocage, ou ce qui a été mesuré et comment."
            )
        if statut == "certified" and not (artifacts or []):
            raise ValueError(
                "statut 'certified' exige au moins un artefact (script, log, certificat) : "
                "utilise put_artifact puis repasse la poignée. Sinon déclare 'measured'."
            )

        dups = st.near_duplicates(p["id"], summary + " " + why)
        if dups and not force:
            return {
                "ok": False,
                "quasi_doublon": dups,
                "conseil": "Ce constat semble déjà au registre. Si ton résultat est réellement "
                           "différent, précise en quoi dans `why` et rappelle avec force=true.",
            }

        fid = None
        if front:
            f = st.front(p["id"], front)
            if f is None:
                raise KeyError(f"front inconnu '{front}'")
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

        return {
            "ok": True, "entree": eid, "front_clos": closed,
            "note": "Front clos ; pense à ouvrir le suivant avec open_front pour que le registre "
                    "ne se vide pas." if closed else
                    "Enregistré. Si cette session a produit du code ou des logs, attache-les "
                    "avec put_artifact.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Ouvrir un front",
    description="Déclare un nouveau chantier. La règle de la campagne : une piste fermée, une piste ouverte.",
)
def open_front(
    session: Annotated[str, Field(description="Identifiant de session.")],
    problem: Annotated[str, Field(description="Slug du problème.")],
    key: Annotated[str, Field(description="Clé courte en kebab-case, stable.")],
    title: Annotated[str, Field(description="Titre lisible.")],
    rationale: Annotated[str, Field(description="Pourquoi c'est prometteur et par où commencer.")],
    cost: Annotated[str, Field(description="low | medium | high")] = "medium",
    gain: Annotated[str, Field(description="Ce qu'on gagne si ça marche.")] = "",
    priority: Annotated[int, Field(description="1 = le plus prometteur.", ge=1, le=999)] = 50,
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        p = st.problem_or_die(problem)
        if cost not in COSTS:
            raise ValueError(f"cost invalide. attendu : {' | '.join(COSTS)}")
        if len((rationale or "").strip()) < MIN_WHY:
            raise ValueError(f"`rationale` trop court (min {MIN_WHY} car.) — dis par où on attaque.")
        if st.front(p["id"], key) is not None:
            return {"ok": False, "error": f"le front '{key}' existe déjà."}
        st.upsert_front(p["id"], p["slug"], key=key, title=title, rationale=rationale,
                        cost=cost, gain=gain, status="open", priority=priority)
        return {"ok": True, "front": key}
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Ouvrir un problème",
    description=(
        "Déclare un nouveau problème dans le registre. À faire avant d'y travailler, "
        "pour que quelqu'un d'autre puisse s'y joindre. Un problème sans front ouvert "
        "est un problème sur lequel personne ne sait par où entrer : ouvre-en au moins "
        "un dans la foulée avec open_front."
    ),
)
def open_problem(
    session: Annotated[str, Field(description="Identifiant de session.")],
    slug: Annotated[str, Field(description="Identifiant court en kebab-case, stable et citable, ex: 'erdos-707'.")],
    title: Annotated[str, Field(description="Énoncé court et reconnaissable du problème.")],
    statement: Annotated[str, Field(description="L'énoncé complet et précis, avec ses quantificateurs.")],
    one_liner: Annotated[
        str, Field(description="L'état en une phrase : ce qui est acquis aujourd'hui.")
    ] = "",
    source_url: Annotated[
        str | None, Field(description="La référence faisant autorité (erdosproblems.com, arXiv…).")
    ] = None,
    honest_estimate: Annotated[
        str | None, Field(description="Estimation honnête des chances de conclure. Ne pas embellir.")
    ] = None,
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug or ""):
            raise ValueError("slug invalide : minuscules, chiffres et tirets, ex. 'erdos-707'.")
        if st.problem(slug) is not None:
            return {"ok": False, "error": f"le problème '{slug}' existe déjà.",
                    "conseil": "briefing(problem) pour voir où il en est."}
        if len((statement or "").strip()) < 60:
            raise ValueError(
                "`statement` trop court. L'énoncé doit être autonome et sans ambiguïté : "
                "quantificateurs explicites, notations définies. Le lecteur suivant n'aura "
                "que ça."
            )
        st.upsert_problem(slug=slug, title=title, statement=statement, status="open",
                          one_liner=one_liner or None, source_url=source_url,
                          honest_estimate=honest_estimate)
        return {
            "ok": True, "problem": slug,
            "suite": "Ouvre au moins un front avec open_front, sinon personne ne saura par "
                     "où entrer. Puis report_result au fur et à mesure.",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Déposer un artefact",
    description=(
        "Stocke un script, un log ou un jeu de données. Déduplication par contenu et "
        "compression : rien ne traverse jamais ton contexte, tu récupères une poignée sha256 "
        "à joindre à report_result. Donne `path` pour un fichier volumineux."
    ),
)
def put_artifact(
    session: Annotated[str, Field(description="Identifiant de session.")],
    filename: Annotated[str, Field(description="Nom de fichier, pour la lisibilité.")],
    content: Annotated[str | None, Field(description="Contenu inline (petits fichiers).")] = None,
    path: Annotated[str | None, Field(description="Chemin local à lire (gros fichiers).")] = None,
    kind: Annotated[str, Field(description="script | log | data | proof | note")] = "data",
) -> dict:
    try:
        st = store()
        _session_or_fail(session)
        if not content and not path:
            raise ValueError("donne `content` ou `path`.")
        raw = Path(path).read_bytes() if path else (content or "").encode()
        if not raw:
            raise ValueError("artefact vide.")
        meta = st.put_artifact(raw, kind=kind, filename=filename)
        return {
            "ok": True, **meta,
            "note": "contenu déjà présent, réutilisé" if meta["deduplicated"] else
                    f"compressé {meta['size']}→{meta['stored']} octets",
        }
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Lire un artefact",
    description=(
        "Lit une TRANCHE d'un artefact : head, tail, une plage de lignes, ou les lignes "
        "contenant un motif. Ne rapatrie jamais un gros fichier en entier."
    ),
)
def read_artifact(
    sha256: Annotated[str, Field(description="Poignée, préfixe de 8 caractères accepté.")],
    mode: Annotated[str, Field(description="head | tail | range | grep | meta")] = "head",
    lines: Annotated[int, Field(description="Nombre de lignes pour head/tail.", ge=1, le=400)] = 40,
    start: Annotated[int, Field(description="Première ligne pour mode 'range' (1-indexé).", ge=1)] = 1,
    pattern: Annotated[str | None, Field(description="Motif pour le mode 'grep'.")] = None,
) -> dict:
    try:
        st = store()
        row = st.artifact_meta(sha256)
        if row is None:
            hit = st.db.execute(
                "SELECT sha256 FROM artifacts WHERE sha256 LIKE ? LIMIT 2", (sha256 + "%",)
            ).fetchall()
            if len(hit) != 1:
                raise KeyError(f"artefact introuvable ou préfixe ambigu : {sha256}")
            row = st.artifact_meta(hit[0]["sha256"])
        meta = {"sha256": row["sha256"], "nom": row["filename"], "type": row["kind"],
                "octets": row["size"], "lignes": row["lines"]}
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
                raise ValueError("mode 'grep' exige `pattern`.")
            sel = [f"{i}: {l}" for i, l in enumerate(all_lines, 1) if pattern in l][:lines]
            first = 0
        else:
            raise ValueError("mode invalide : head | tail | range | grep | meta")
        return {"ok": True, **meta, "premiere_ligne": first, "contenu": "\n".join(sel)}
    except Exception as exc:
        return _fail(exc)


@server.tool(
    title="Classement des contributeurs",
    description="Score pondéré par verdict et statut. Clore et réfuter rapportent plus qu'avancer.",
)
def leaderboard(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict:
    try:
        rows = store().leaderboard(limit)
        return {"ok": True, "classement": [
            {"rang": i, "contributeur": r["name"], "score": round(r["score"], 1),
             "entrees": r["n_entries"], "fronts_clos": r["n_closes"]}
            for i, r in enumerate(rows, 1)
        ], "bareme": "close 10 · refute 8 · dead-end 6 · advance 5 · ops-note 2, "
                     "×2 si certifié, ×1,4 si mesuré."}
    except Exception as exc:
        return _fail(exc)


@server.tool(title="État du serveur", description="Volumétrie, compression, sessions.")
def server_status() -> dict:
    try:
        st = store()
        a = st.artifact_stats()
        n_sessions = st.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        n_verified = st.db.execute("SELECT COUNT(*) FROM sessions WHERE tier='contributor'").fetchone()[0]
        return {
            "ok": True,
            "base": DB_PATH,
            "octets_base": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
            "problemes": len(st.list_problems()),
            "artefacts": {"nombre": a["count"], "octets_bruts": a["raw_bytes"],
                          "octets_stockes": a["stored_bytes"], "compression": f"×{a['ratio']}"},
            "sessions": {"ouvertes": n_sessions, "validees": n_verified},
        }
    except Exception as exc:
        return _fail(exc)


def main() -> None:
    if os.environ.get("CAIRN_DEBUG"):
        print(f"cairn MCP — base {DB_PATH}", file=sys.stderr)
    store()
    server.run("stdio")


if __name__ == "__main__":
    main()
