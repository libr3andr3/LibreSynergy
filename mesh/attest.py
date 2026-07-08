#!/usr/bin/env python3
"""
LibreSynergy attest — attested peering: agents verify each other BEFORE they
connect. The missing fourth trust root of the sovereign mesh.

The mesh already lets two nodes find each other and punch a direct path
(rendezvous.py / peer.py / wg-punch.py) and lets a creator sign content so any
untrusted peer can serve it (content_sign.py). What it did NOT have — the
rendezvous even says so in its own comments — is a way for the two peers to
verify *each other* before a tunnel comes up. Today the punch is anonymous:
whoever claims a name at the coordinator gets talked to. This module closes
that gap with a mutual, replay-proof handshake that answers three questions
before a single byte of community data crosses the link:

     ┌─ FRIEND OR FOE?          → does this node hold the private key for the
     │                            identity it claims? (Ed25519 key possession,
     │                            bound to THIS session's transcript.)
     ├─ CAN I TRUST YOU         → what did this node actually boot? (a fresh,
     │  WITH MY DATA?             signed measured-boot / TPM quote — hwroot.py)
     └─ WHO DO YOU WORK FOR?    → a named operator delegated authority to it,
                                  and a human is present RIGHT NOW on a hardware
                                  token (YubiKey / passkey) — hwroot.py.

Trust is established END-TO-END between the two peers. The rendezvous stays
dumb: it never vouches for anyone, exactly like it never sees a stream byte.
"Tu dispositivo es tu casa, y nadie entra sin tu consentimiento." — MANIFESTO.

The handshake is three messages; the verifier is a pure function (evaluate());
run it with no network at all via `attest.py demo` (add --tamper to watch one
question go red), or over a socket via `serve` / `connect`.
"""
import argparse, base64, hashlib, json, os, socket, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_sign as cs
import agentfacts as af
import hwroot

PROTO = "ls-attest/1"
HANDSHAKE_TAG = b"ls-attest-handshake-v1"

def _b64(b): return base64.b64encode(b).decode()
def _ub64(s): return base64.b64decode(s)
def _now(): return int(time.time())

# ============================================================================
#  Identity a node loads once (its key, its passport, its hardware roots)
# ============================================================================

def load_identity(node_key, facts, human_token=None, ak_key=None, env_sources=None):
    """Bundle everything a node presents in a handshake.
      node_key     : path to this node's Ed25519 private key (its identity)
      facts        : this node's AgentFacts dict (agentfacts.build)
      human_token  : hwroot.soft_token()/real token — the operator's presence key
      ak_key       : attestation key for the environment (boot) quote
      env_sources  : {component: path} to measure (hwroot.measure_self)
    """
    return {"node_key": node_key, "facts": facts, "human_token": human_token,
            "ak_key": ak_key, "measurements": hwroot.measure_self(env_sources or {})}

def _transcript(nonce_a_hex, nonce_b_hex, facts_a, facts_b) -> bytes:
    """Identical on both sides after message 2; signing it binds key-possession
    to THIS exchange (not a replayable bare nonce) and defeats splicing/MITM."""
    blob = {
        "proto": PROTO,
        "a": {"nonce": nonce_a_hex, "id": facts_a["agent_id"],
              "facts": hashlib.sha256(af._canon(facts_a)).hexdigest()},
        "b": {"nonce": nonce_b_hex, "id": facts_b["agent_id"],
              "facts": hashlib.sha256(af._canon(facts_b)).hexdigest()},
    }
    return HANDSHAKE_TAG + json.dumps(blob, sort_keys=True, separators=(",", ":")).encode()

def _proofs(identity, my_priv_over_transcript_msg, peer_nonce: bytes):
    """The three proofs a side offers about itself, all freshly bound to the
    peer's nonce so none can be replayed from an earlier session."""
    out = {"sig": _b64(cs.sign_bytes(identity["node_key"], my_priv_over_transcript_msg))}
    if identity.get("human_token") is not None:
        out["human"] = hwroot.principal_assert(peer_nonce, identity["human_token"])
    if identity.get("ak_key"):
        out["env"] = hwroot.env_quote(peer_nonce, identity["ak_key"], identity["measurements"])
    return out

# ---- the three messages (pure; a transport just carries the dicts) -------------

def make_hail(identity_a):
    nonce_a = os.urandom(16)
    msg = {"proto": PROTO, "op": "hail", "nonce": nonce_a.hex(), "facts": identity_a["facts"]}
    return msg, {"nonce_a": nonce_a}

def make_vouch(identity_b, hail):
    nonce_a = bytes.fromhex(hail["nonce"]); facts_a = hail["facts"]
    nonce_b = os.urandom(16)
    transcript = _transcript(nonce_a.hex(), nonce_b.hex(), facts_a, identity_b["facts"])
    proofs = _proofs(identity_b, transcript, nonce_a)   # B proves itself to A's nonce
    msg = {"proto": PROTO, "op": "vouch", "nonce": nonce_b.hex(),
           "facts": identity_b["facts"], **proofs}
    ctx = {"nonce_a": nonce_a, "nonce_b": nonce_b, "facts_a": facts_a, "transcript": transcript}
    return msg, ctx

def make_seal(identity_a, hail_state, vouch):
    nonce_a = hail_state["nonce_a"]; nonce_b = bytes.fromhex(vouch["nonce"]); facts_b = vouch["facts"]
    transcript = _transcript(nonce_a.hex(), nonce_b.hex(), identity_a["facts"], facts_b)
    proofs = _proofs(identity_a, transcript, nonce_b)   # A proves itself to B's nonce
    msg = {"proto": PROTO, "op": "seal", **proofs}
    return msg, {"nonce_a": nonce_a, "nonce_b": nonce_b, "transcript": transcript, "facts_b": facts_b}

# ============================================================================
#  The verifier — pure function. This is what lifts into NANDA's "Trust" block.
# ============================================================================

def evaluate(policy, peer_facts, transcript, peer_sig_b64, peer_human, peer_env, my_nonce):
    """Judge a peer from its facts + three fresh proofs. Returns a Verdict."""
    checks = {}
    pub = _ub64(peer_facts["pubkey"]); pid = peer_facts.get("agent_id")

    # 1) FRIEND OR FOE — authentic passport AND key possession over this session
    fok, fdetail = af.verify(peer_facts, policy.get("trusted_operators"))
    sok = cs.verify_bytes(pub, transcript, _ub64(peer_sig_b64 or ""))
    roster = policy.get("roster")
    known = roster is None or pid in roster or policy.get("tofu")
    if not sok:
        d = "key possession NOT proven — bad signature over the session transcript (impostor)"
    elif not fok:
        d = fdetail
    elif not known:
        d = f"unknown peer {pid} — not on your roster and TOFU is off"
    else:
        seen = "known peer" if (roster and pid in roster) else "first contact (TOFU)"
        d = f"identity {pid} proven — {seen}"
    checks["friend_or_foe"] = {"ok": bool(sok and fok and known), "detail": d}

    # 2) CAN I TRUST YOU WITH MY DATA — environment / boot attestation
    if peer_env:
        eok, edetail = hwroot.verify_env(peer_env, my_nonce, policy.get("env_policy", {}))
    else:
        eok = not policy.get("require_hardware_env")
        edetail = "no environment quote offered" + ("" if eok else " (policy requires one)")
    checks["trust_my_data"] = {"ok": bool(eok), "detail": edetail}

    # 3) WHO DO YOU WORK FOR — live human on a hardware token + operator delegation
    principal = peer_facts.get("principal", {})
    op_id = principal.get("operator_id")
    if peer_human:
        hok, hdetail = hwroot.verify_principal(peer_human, my_nonce)
    else:
        hok = not policy.get("require_human")
        hdetail = "no live principal assertion offered" + ("" if hok else " (policy requires one)")
    if hok and policy.get("require_trusted_operator"):
        trusted = policy.get("trusted_operators") or {}
        if not op_id or op_id not in trusted:
            hok, hdetail = False, f"operator {op_id or '(none)'} is not on your trusted-operator roster"
    checks["who_you_work_for"] = {"ok": bool(hok), "detail": f"'{principal.get('name','?')}' — {hdetail}"}

    friend = all(c["ok"] for c in checks.values())
    return {"peer_id": pid, "peer_label": peer_facts.get("label"),
            "principal_name": principal.get("name"), "checks": checks,
            "friend": friend, "decision": "ALLOW" if friend else "DENY"}

# ---- responder-side finish: B evaluates A from the seal --------------------------

def responder_evaluate(policy_b, ctx_b, seal):
    return evaluate(policy_b, ctx_b["facts_a"], ctx_b["transcript"],
                    seal.get("sig"), seal.get("human"), seal.get("env"), ctx_b["nonce_b"])

def initiator_evaluate(policy_a, hail_state, vouch):
    # A recomputes the transcript exactly as B did, then judges B
    facts_b = vouch["facts"]; nonce_a = hail_state["nonce_a"]; nonce_b = bytes.fromhex(vouch["nonce"])
    # NOTE: A needs facts_a to rebuild the transcript; carried via hail_state
    transcript = _transcript(nonce_a.hex(), nonce_b.hex(), hail_state["facts_a"], facts_b)
    return evaluate(policy_a, facts_b, transcript, vouch.get("sig"),
                    vouch.get("human"), vouch.get("env"), nonce_a)

# ============================================================================
#  Rendering — the panel that becomes the pitch slide
# ============================================================================

_Q = {"friend_or_foe": "friend or foe?",
      "trust_my_data": "trust you with my data?",
      "who_you_work_for": "who do you work for?"}

def render_verdict(v, me="me", peer=None):
    peer = peer or v.get("peer_label") or v.get("peer_id")
    rule = "  " + "─" * 66
    mark = lambda ok: "✅" if ok else "❌"
    lines = [rule, f"   ATTESTED PEERING   {me}  ⇄  {peer}", rule]
    for k in ("friend_or_foe", "trust_my_data", "who_you_work_for"):
        c = v["checks"][k]
        lines.append(f"   {mark(c['ok'])}  {_Q[k]:<24} {c['detail']}")
    lines.append(rule)
    verdict = "ALLOW — federation permitted" if v["friend"] else "DENY — connection refused"
    lines.append(f"   ▶ {mark(v['friend'])} {v['decision']}: {verdict}")
    lines.append(rule)
    return "\n".join(lines)

# ============================================================================
#  In-process demo (no network) — the star of the live pitch
# ============================================================================

def _mk_identity(prefix, label, principal, operator_key, *, human_alg="ed25519",
                 caps=None, env_sources=None):
    node_key = f"{prefix}.key"
    if not os.path.exists(node_key):
        cs.keygen(prefix)
    facts = af.build(node_key, label, principal, operator_key=operator_key,
                     capabilities=caps or ["mesh.punch", "stream.relay", "course.seed"])
    token = hwroot.soft_token(f"{prefix}_human", alg=human_alg)
    ak = hwroot.soft_token(f"{prefix}_ak")["key"]
    return load_identity(node_key, facts, human_token=token, ak_key=ak, env_sources=env_sources)

def _apply_tamper(vouch_msg, ctx_b, identity_b, mode, nonce_a):
    """Mutate B's vouch (as seen by A) to make exactly one question fail.
    ("stranger" needs no mutation — Bob is honest but off Alice's roster, which
    the caller expresses purely in policy.)"""
    if mode in (None, "none", "stranger"):
        return vouch_msg
    if mode == "impostor":
        # sign the transcript with a DIFFERENT key than facts advertise
        rogue = "rogue.key"
        if not os.path.exists(rogue):
            cs.keygen("rogue")
        vouch_msg["sig"] = _b64(cs.sign_bytes(rogue, ctx_b["transcript"]))
    elif mode == "forge_id":
        # claim an identity that doesn't match the embedded pubkey
        vouch_msg["facts"] = {**vouch_msg["facts"], "agent_id": "deadbeefdeadbeef"}
    elif mode == "bad_boot":
        vouch_msg["env"] = hwroot.env_quote(nonce_a, identity_b["ak_key"],
                                            {**identity_b["measurements"], "kernel": "unpatched-cve"})
    elif mode == "replay_env":
        vouch_msg["env"] = hwroot.env_quote(os.urandom(16), identity_b["ak_key"],
                                            identity_b["measurements"])  # quote for a stale nonce
    elif mode == "no_human":
        vouch_msg.pop("human", None)
    elif mode == "replay_human":
        vouch_msg["human"] = hwroot.principal_assert(os.urandom(16), identity_b["human_token"])
    else:
        raise SystemExit(f"unknown tamper mode: {mode}")
    return vouch_msg

TAMPERS = ["none", "impostor", "forge_id", "bad_boot", "replay_env", "no_human", "replay_human", "stranger"]

def demo(tamper=None):
    import tempfile
    d = tempfile.mkdtemp(prefix="ls-attest-demo-")
    os.chdir(d)
    print(f"# in-process attested-peering demo  (workdir {d})\n")
    cs.keygen("operatorA"); cs.keygen("operatorB")
    A = _mk_identity("nodeA", "node.alice", "Alice Community", "operatorA.key")
    B = _mk_identity("nodeB", "node.bob", "Bob Collective", "operatorB.key")

    # Alice's policy: she knows Bob's node and trusts Bob's operator, and demands
    # a live human + a vetted boot state. (Bob's mirror policy is permissive here.)
    known_good = {hwroot.boot_digest(B["measurements"])}
    opB_pub = cs.pub_der_of_key("operatorB.key"); opB_id = cs.id_of_pub_der(opB_pub)
    # "stranger": Alice has a roster, but Bob's id isn't on it (and TOFU is off)
    roster = ({"0000000000000000": "some-other-node"} if tamper == "stranger"
              else {B["facts"]["agent_id"]: B["facts"]["label"]})
    policy_A = {
        "roster": roster, "tofu": False,
        "trusted_operators": {opB_id: opB_pub},
        "require_human": True, "require_hardware_env": False,
        "require_trusted_operator": True,
        "env_policy": {"known_good": known_good, "require_hardware": False},
    }
    policy_B = {"tofu": True, "require_human": True,
                "env_policy": {"known_good": {hwroot.boot_digest(A["measurements"])}}}

    # message 1: Alice hails Bob
    hail, sA = make_hail(A); sA["facts_a"] = A["facts"]
    # message 2: Bob vouches (then we optionally tamper his vouch in flight)
    vouch, cB = make_vouch(B, hail)
    vouch = _apply_tamper(vouch, cB, B, tamper, sA["nonce_a"])
    # message 3: Alice seals + both evaluate
    seal, _ = make_seal(A, sA, vouch)
    verdict_A_of_B = initiator_evaluate(policy_A, sA, vouch)
    verdict_B_of_A = responder_evaluate(policy_B, cB, seal)

    label = tamper if tamper and tamper != "none" else "honest peers"
    print(f"## Alice evaluates Bob   [scenario: {label}]")
    print(render_verdict(verdict_A_of_B, me="node.alice", peer="node.bob"))
    print(f"\n## Bob evaluates Alice   [mutual — both sides must pass]")
    print(render_verdict(verdict_B_of_A, me="node.bob", peer="node.alice"))
    mutual = verdict_A_of_B["friend"] and verdict_B_of_A["friend"]
    print(f"\n==> MUTUAL DECISION: {'✅ FEDERATE' if mutual else '❌ NO FEDERATION'}"
          f"  (the tunnel comes up only if BOTH say ALLOW)")
    return 0 if (mutual == (tamper in (None, 'none'))) else 1

# ============================================================================
#  Live over a socket — two real processes (localhost or a punched endpoint)
# ============================================================================

def _send(sock, addr, obj): sock.sendto(json.dumps(obj).encode(), addr)

def _recv(sock, timeout=10):
    sock.settimeout(timeout)
    data, addr = sock.recvfrom(65535)
    return json.loads(data.decode()), addr

def serve(identity, policy, host="127.0.0.1", port=54545):
    """Responder: wait for a hail, vouch, receive the seal, render the verdict."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((host, port))
    print(f"[serve] attest responder on udp/{host}:{port} — waiting for a hail…", flush=True)
    hail, addr = _recv(s, timeout=120)
    vouch, cB = make_vouch(identity, hail)
    _send(s, addr, vouch)
    seal, _ = _recv(s, timeout=30)
    v = responder_evaluate(policy, cB, seal)
    print(render_verdict(v, me=identity["facts"]["label"]))
    return 0 if v["friend"] else 1

def connect(identity, policy, host="127.0.0.1", port=54545):
    """Initiator: hail the responder, receive the vouch, seal, render the verdict."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (socket.gethostbyname(host), port)
    hail, sA = make_hail(identity); sA["facts_a"] = identity["facts"]
    _send(s, addr, hail)
    vouch, _ = _recv(s, timeout=30)
    seal, _ = make_seal(identity, sA, vouch)
    _send(s, addr, seal)
    v = initiator_evaluate(policy, sA, vouch)
    print(render_verdict(v, me=identity["facts"]["label"]))
    return 0 if v["friend"] else 1

# ============================================================================
#  Gate helpers — run the handshake over a socket peer.py already owns
# ============================================================================
# peer.py hole-punches a direct UDP path, then (with --attest) calls these to
# verify the peer BEFORE serving or fetching a payload. They briefly "own" the
# shared socket and ignore non-handshake datagrams (punch syn/ack) meanwhile.

def _await_op(sock, want, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock.settimeout(0.5)
        try:
            data, src = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            continue
        try:
            m = json.loads(data.decode())
        except Exception:
            continue
        if m.get("op") == want:
            return m, src
    return None, None

def gate_initiator(sock, addr, identity, policy, timeout=8):
    """Run the handshake as the dialing side over an established path.
    Returns a Verdict, or None on timeout."""
    hail, sA = make_hail(identity); sA["facts_a"] = identity["facts"]
    deadline = time.time() + timeout; last = 0.0; vouch = None
    while time.time() < deadline and vouch is None:
        if time.time() - last > 0.6:
            _send(sock, addr, hail); last = time.time()
        m, _ = _await_op(sock, "vouch", 0.6)
        if m:
            vouch = m
    if vouch is None:
        return None
    seal, _ = make_seal(identity, sA, vouch)
    _send(sock, addr, seal)
    _send(sock, addr, seal)   # belt-and-suspenders: seal is the last packet
    return initiator_evaluate(policy, sA, vouch)

def gate_responder(sock, addr, identity, policy, hail, timeout=8):
    """Run the handshake as the listening side, given the hail already received."""
    vouch, cB = make_vouch(identity, hail)
    _send(sock, addr, vouch)
    seal, _ = _await_op(sock, "seal", timeout)
    if seal is None:
        return None
    return responder_evaluate(policy, cB, seal)

def load_roster(path):
    """A roster file: one trusted agent_id (16 hex) per line, '#' comments."""
    r = {}
    if path and os.path.exists(path):
        for line in open(path):
            t = line.split("#", 1)[0].strip()
            if t:
                r[t.split()[0]] = " ".join(t.split()[1:]) or True
    return r

# ---------------- cli -----------------------------------------------------------
def _load_cli_identity(a):
    facts = json.load(open(a.facts))
    token = hwroot.soft_token(f"{a.facts}.human") if a.human else None
    ak = hwroot.soft_token(f"{a.facts}.ak")["key"] if a.attest_env else None
    return load_identity(a.key, facts, human_token=token, ak_key=ak)

def main():
    ap = argparse.ArgumentParser(description="attested peering — verify a peer before you connect")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="in-process handshake (no network)")
    d.add_argument("--tamper", choices=TAMPERS, default="none",
                   help="make one question fail to show the gate working")
    d.add_argument("--all", action="store_true", help="run every scenario in sequence")

    for name, helptext in (("serve", "responder over UDP"), ("connect", "initiator over UDP")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--key", required=True); p.add_argument("--facts", required=True)
        p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=54545)
        p.add_argument("--human", action="store_true", help="offer a hardware principal assertion")
        p.add_argument("--attest-env", action="store_true", help="offer a boot quote")

    a = ap.parse_args()
    if a.cmd == "demo":
        if a.all:
            rc = 0
            for t in TAMPERS:
                print("\n" + "═" * 70)
                rc |= demo(None if t == "none" else t)
            return sys.exit(rc)
        return sys.exit(demo(None if a.tamper == "none" else a.tamper))
    # serve/connect use a permissive TOFU policy by default (roster/operators
    # are wired in real deployments via peer.py); this is a connectivity demo.
    identity = _load_cli_identity(a)
    policy = {"tofu": True, "require_human": a.human,
              "env_policy": {"known_good": {hwroot.boot_digest(identity["measurements"])}}}
    fn = serve if a.cmd == "serve" else connect
    sys.exit(fn(identity, policy, host=a.host, port=a.port))

if __name__ == "__main__":
    main()
