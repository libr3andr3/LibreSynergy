#!/usr/bin/env python3
"""
LibreSynergy AgentFacts — a node's signed, self-describing passport.

Before two nodes federate (mesh a tunnel, seed each other's swarms, subscribe
to each other's feeds) each hands over an *AgentFacts* document: a small,
self-signed JSON that says who it is, who it works for, and what it can do.
It is the mesh equivalent of a passport you present at the border — and, like
`content_sign.py` for content, the trust lives in the signature, not in the
peer that hands it to you.

The naming (`AgentFacts`, `agent_id`, capabilities, endpoints) is deliberately
native to NANDA's "Internet of Agents": the same document that gates a
LibreSynergy federation is what a NANDA Index / registry would resolve.

Three trust claims, each independently checkable:

  agent_id / pubkey  — the node's Ed25519 identity (== sha256(pubkey)[:16]),
                       the SAME self that signs its content in content_sign.py.
  principal          — WHO IT WORKS FOR: a named operator (human/community)
                       whose own key *delegates* authority to this node. If you
                       trust the operator (their key is on your roster) you can
                       verify the delegation; otherwise you at least know the
                       claim and that it is internally consistent.
  capabilities/eps   — what it offers and where, so a peer knows what it is
                       agreeing to talk to.

The whole document is self-signed by the node key; the delegation inside it is
signed by the operator key. Tamper with either and verification fails.
"""
import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_sign as cs

SPEC = "nanda/agentfacts@1"
DELEGATION_TAG = b"ls-agent-delegation-v1"

def _b64(b): return base64.b64encode(b).decode()
def _ub64(s): return base64.b64decode(s)

def _canon(facts: dict) -> bytes:
    """Deterministic bytes for signing — everything except the signature.
    Never sign raw JSON; sign a canonical (sorted-key, compact) encoding."""
    body = {k: v for k, v in facts.items() if k != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

def _delegation_msg(operator_id: str, agent_id: str, label: str) -> bytes:
    return DELEGATION_TAG + f"|{operator_id}|{agent_id}|{label}".encode()

def delegate(operator_key: str, agent_id: str, label: str) -> dict:
    """An operator authorises a node to act in its name. Returns the delegation
    block to embed in the node's AgentFacts."""
    op_pub = cs.pub_der_of_key(operator_key)
    op_id = cs.id_of_pub_der(op_pub)
    sig = cs.sign_bytes(operator_key, _delegation_msg(op_id, agent_id, label))
    return {"operator_id": op_id, "operator_pub": _b64(op_pub), "sig": _b64(sig)}

def build(agent_key: str, label: str, principal_name: str,
          operator_key: str = None, capabilities=None, endpoints=None,
          attestation: dict = None, issued: int = None) -> dict:
    """Build and self-sign an AgentFacts document for this node.

    If `operator_key` is given, the operator delegates authority to this node
    (the strong 'who do you work for' proof). `attestation` may carry a boot
    quote (hwroot.env_quote) captured at facts-build time; the live handshake
    re-attests with a fresh nonce, so this is informational."""
    agent_pub = cs.pub_der_of_key(agent_key)
    agent_id = cs.id_of_pub_der(agent_pub)
    facts = {
        "v": 1,
        "spec": SPEC,
        "agent_id": agent_id,
        "pubkey": _b64(agent_pub),
        "label": label,
        "principal": {"name": principal_name},
        "capabilities": sorted(capabilities or []),
        "endpoints": endpoints or {},
        "issued": int(issued if issued is not None else time.time()),
    }
    if operator_key:
        facts["principal"]["delegation"] = delegate(operator_key, agent_id, label)
        facts["principal"]["operator_id"] = facts["principal"]["delegation"]["operator_id"]
    if attestation:
        facts["attestation"] = attestation
    facts["sig"] = _b64(cs.sign_bytes(agent_key, _canon(facts)))
    return facts

def verify(facts: dict, trusted_operators=None):
    """Return (ok, detail). Checks identity, self-signature, and — when the
    named operator is on your roster — the delegation.

    trusted_operators: optional {operator_id: pub_der_bytes} you already trust.
    """
    try:
        agent_pub = _ub64(facts["pubkey"])
    except Exception:
        return False, "malformed AgentFacts (no pubkey)"
    if cs.id_of_pub_der(agent_pub) != facts.get("agent_id"):
        return False, "agent_id does not match its public key (identity forgery)"
    if not cs.verify_bytes(agent_pub, _canon(facts), _ub64(facts.get("sig", ""))):
        return False, "AgentFacts self-signature invalid (forged or tampered)"
    principal = facts.get("principal", {})
    deleg = principal.get("delegation")
    if deleg:
        op_pub = _ub64(deleg["operator_pub"])
        if cs.id_of_pub_der(op_pub) != deleg.get("operator_id"):
            return False, "operator_id does not match its public key"
        msg = _delegation_msg(deleg["operator_id"], facts["agent_id"], facts["label"])
        if not cs.verify_bytes(op_pub, msg, _ub64(deleg["sig"])):
            return False, "operator delegation signature invalid (node not authorised)"
        op_id = deleg["operator_id"]
        if trusted_operators is not None:
            if op_id not in trusted_operators:
                return True, (f"authentic; works for '{principal.get('name')}' "
                              f"(operator {op_id}) — operator NOT on your roster")
            if cs.id_of_pub_der(trusted_operators[op_id]) != op_id:
                return False, "rostered operator key mismatch"
            return True, (f"authentic; works for '{principal.get('name')}' "
                          f"(operator {op_id}) — delegation verified, operator trusted")
        return True, (f"authentic; works for '{principal.get('name')}' "
                      f"(operator {op_id}) — delegation verified")
    return True, f"authentic; self-asserted principal '{principal.get('name')}' (no operator delegation)"

# ---------------- cli -----------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="build / verify AgentFacts passports")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--key", required=True); b.add_argument("--label", required=True)
    b.add_argument("--principal", required=True); b.add_argument("--operator-key")
    b.add_argument("--cap", action="append", default=[]); b.add_argument("--out")
    v = sub.add_parser("verify"); v.add_argument("--facts", required=True)
    a = ap.parse_args()
    if a.cmd == "build":
        f = build(a.key, a.label, a.principal, operator_key=a.operator_key,
                  capabilities=a.cap,
                  endpoints={"rendezvous": os.environ.get("MESH_RENDEZVOUS", "")})
        out = a.out or f"{a.label}.facts.json"
        json.dump(f, open(out, "w"), indent=1)
        print(f"built AgentFacts -> {out}  (agent_id {f['agent_id']})")
    elif a.cmd == "verify":
        ok, why = verify(json.load(open(a.facts)))
        print(("✅ " if ok else "❌ ") + why)
        sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
