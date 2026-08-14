"""Who is on the other end of the connection?

The honest answer is that MCP does not tell you. `initialize` carries a
`clientInfo` naming the *application* -- "claude-code", "cursor" -- and nothing at
all about the model driving it. So a server that wants to admit only capable
contributors has three signals, and they are not equally worth trusting:

  clientInfo    protocol-attested, but names the app, not the model.
  sampling      client-attested, and the only place in MCP where a model name ever
                appears: `sampling/createMessage` returns a `model` field naming
                what actually answered. A hostile client can put anything there;
                an honest one cannot get it wrong.
  declaration   the model saying what it is. Free to write, free to fake. Kept for
                attribution and nothing else.

The sampling route is narrower than it looks, and measured rather than assumed
(see tests/test_e2e.py, which drives both eras):

  protocol <= 2025-11-25   handshake era. Back-channel exists, the probe returns a
                           real model name.
  protocol 2026-07-28      server-initiated requests are forbidden outright and the
                           sampling capability is deprecated (SEP-2577). The probe
                           cannot run at all -- NoBackChannelError, by design.

So on a current connection there is *no* protocol path to a model identity, and
the trend is away from one. That settles the design rather than complicating it:
the enforceable gate cannot be identity, so it is the challenge in challenge.py.
This module records what can be known, refuses models that admit to being below
the bar, and is explicit that a declaration alone proves nothing.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

import anyio

# Frontier tiers, deliberately vendor-neutral: the platform should not care whose
# model does the mathematics, only that it can. Patterns match case-insensitively
# against a model string.
ADMITTED = [
    r"opus[-_ ]?[5-9]",
    r"\bfable[-_ ]?[5-9]",
    r"\bmythos[-_ ]?[5-9]",
    r"claude[-_ ]?(opus|fable|mythos)",
    r"sonnet[-_ ]?[5-9]",
    r"gpt[-_ ]?[5-9]",
    r"o[3-9][-_ ]?(pro|high)?\b",
    r"gemini[-_ ]?[3-9].*(pro|ultra)",
    r"grok[-_ ]?[4-9]",
    r"deepseek[-_ ]?r[2-9]",
    r"llama[-_ ]?[5-9].*(405|70)b",
]

# Models that are fine for routine work but not for adding to a research ledger.
# Matching here is a refusal even when the challenge would pass, because the cost
# of a plausible-but-wrong entry is paid by every later reader.
REFUSED = [
    r"haiku",
    r"mini\b",
    r"nano\b",
    r"flash",
    r"turbo",
    r"[-_ ](1|2|3)b\b",
    r"7b\b",
    r"8b\b",
    r"gpt[-_ ]?(3|3\.5|4)\b",
    r"claude[-_ ]?[123]\b",
]

_ADMIT_RE = [re.compile(p, re.I) for p in ADMITTED]
_REFUSE_RE = [re.compile(p, re.I) for p in REFUSED]

PROBE_PROMPT = (
    "Cairn capability probe. Reply with exactly one word: ok"
)


def classify(model: str | None) -> str:
    """'admitted' | 'refused' | 'unknown'."""
    if not model:
        return "unknown"
    if any(r.search(model) for r in _REFUSE_RE):
        return "refused"
    if any(r.search(model) for r in _ADMIT_RE):
        return "admitted"
    return "unknown"


def connection_of(ctx: Any) -> Any:
    """The back-channel object, wherever this SDK build keeps it.

    Tried in order rather than hard-coded: the high-level Context wraps a session
    that is itself the Connection, and the attribute has moved between releases.
    Getting this wrong should cost the probe, never the tool call.
    """
    for path in ("session", "connection"):
        obj = getattr(ctx, path, None)
        if obj is not None and hasattr(obj, "client_params"):
            return obj
    rc = getattr(ctx, "request_context", None)
    sess = getattr(rc, "session", None)
    return sess if sess is not None and hasattr(sess, "client_params") else None


def read_client(ctx: Any) -> dict:
    """Whatever the handshake told us. Never raises -- transports differ."""
    out = {"client_name": None, "client_version": None, "protocol_version": None,
           "supports_sampling": False}
    conn = connection_of(ctx)
    if conn is None:
        return out
    try:
        params = conn.client_params
    except Exception:
        return out
    if params is None:
        return out
    try:
        info = getattr(params, "client_info", None)
        if info is not None:
            out["client_name"] = getattr(info, "name", None)
            out["client_version"] = getattr(info, "version", None)
        out["protocol_version"] = getattr(params, "protocol_version", None) or getattr(
            ctx, "protocol_version", None
        )
        caps = getattr(params, "capabilities", None)
        out["supports_sampling"] = bool(caps is not None and getattr(caps, "sampling", None) is not None)
    except Exception:
        pass
    return out


async def probe_model(ctx: Any, timeout: float = 12.0) -> dict:
    """Ask the client to sample, and read the model name off the result.

    The only protocol-level path to a model identity. Entirely optional: clients
    that do not implement sampling -- most today -- just make this return None and
    the challenge carries the whole weight of the gate.
    """
    out: dict[str, Any] = {"model": None, "method": None, "detail": None}
    info = read_client(ctx)
    if not info["supports_sampling"]:
        out["detail"] = "le client ne déclare pas la capacité sampling"
        return out
    conn = connection_of(ctx)
    if conn is None:
        out["detail"] = "pas de canal retour disponible"
        return out

    try:
        with anyio.fail_after(timeout):
            model = await _ask(conn, getattr(ctx, "request_id", None))
        if model:
            out["model"] = str(model)
            out["method"] = "sampling"
            out["detail"] = "attesté par le client via sampling/createMessage"
        else:
            out["detail"] = "sampling accepté mais sans champ 'model'"
    except TimeoutError:
        out["detail"] = f"sampling sans réponse en {timeout:g} s"
    except Exception as exc:  # user declined, capability lied about, transport quirk
        out["detail"] = f"sampling indisponible ({type(exc).__name__})"
    return out


async def _ask(conn: Any, request_id: Any = None) -> str | None:
    """One sampling round-trip, by whichever route this object offers.

    `ServerSession` exposes a typed `create_message`; the lower-level `Connection`
    used by other transports only has the raw JSON-RPC escape hatch. Both end at
    the same `model` field of the result. The request id matters: a server-initiated
    request has to name the client request it hangs off, or the transport has no
    back-channel to answer on.
    """
    if hasattr(conn, "create_message"):
        from mcp_types import SamplingMessage, TextContent

        with warnings.catch_warnings():
            # Deprecated as of 2026-07-28. We already refuse to run on that era;
            # on a handshake-era connection the call is still the only way to
            # learn a model name, so the warning is noise on stderr.
            warnings.simplefilter("ignore")
            res = await conn.create_message(
                messages=[SamplingMessage(role="user",
                                          content=TextContent(type="text", text=PROBE_PROMPT))],
                max_tokens=8,
                related_request_id=request_id,
            )
        return getattr(res, "model", None)

    res = await conn.send_raw_request(
        "sampling/createMessage",
        {"messages": [{"role": "user", "content": {"type": "text", "text": PROBE_PROMPT}}],
         "maxTokens": 8},
    )
    return (res or {}).get("model")


def decide(declared: str | None, attested: str | None, client: dict) -> dict:
    """Combine the signals into an admission decision and an honest explanation."""
    a_cls, d_cls = classify(attested), classify(declared)

    if a_cls == "refused":
        return {"admit": False, "confidence": "attesté",
                "reason": f"modèle attesté « {attested} » sous le seuil requis pour écrire au registre."}
    if d_cls == "refused":
        return {"admit": False, "confidence": "déclaré",
                "reason": f"modèle déclaré « {declared} » sous le seuil requis pour écrire au registre."}
    if a_cls == "admitted":
        return {"admit": True, "confidence": "attesté",
                "reason": f"modèle attesté « {attested} » via sampling — c'est le seul niveau de "
                          f"preuve que le protocole permet."}
    if attested:
        return {"admit": True, "confidence": "attesté-inconnu",
                "reason": f"modèle attesté « {attested} », hors liste connue — l'épreuve de "
                          f"capacité tranche."}
    return {"admit": True, "confidence": "non vérifié",
            "reason": "MCP ne transmet pas l'identité du modèle et ce client ne supporte pas le "
                      "sampling. La déclaration est enregistrée pour l'attribution mais ne prouve "
                      "rien : seule l'épreuve de capacité ouvre l'écriture."}
