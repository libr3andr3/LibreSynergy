#!/usr/bin/env python3
"""
LibreSynergy peer — v0 mesh client: register at the rendezvous, hole-punch
to another peer, exchange a test payload directly (no relay in the path).

  peer.py --id alice --swarm test                       # wait for punches
  peer.py --id bob --swarm test --connect alice         # punch to alice
  peer.py ... --payload /path/file                      # serve file after punch

After a successful punch both sides have a working UDP path; --connect side
requests the payload and measures direct transfer. This is the seed of the
livestream segment relay: replace 'payload' with HLS segments.
"""
import argparse, json, os, socket, sys, time

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="stun.example.com")
    ap.add_argument("--port", type=int, default=3478)
    ap.add_argument("--id", required=True)
    ap.add_argument("--swarm", default="test")
    ap.add_argument("--connect", help="peer id to punch to")
    ap.add_argument("--payload", help="file to serve to punched peers")
    ap.add_argument("--timeout", type=int, default=45)
    # attested peering (opt-in): verify WHO the peer is before serving/fetching.
    ap.add_argument("--attest", action="store_true",
                    help="run the mutual attestation handshake before any payload")
    ap.add_argument("--key", help="this node's Ed25519 identity key (mesh/attest.py keygen)")
    ap.add_argument("--facts", help="this node's AgentFacts json (mesh/agentfacts.py build)")
    ap.add_argument("--roster", help="file of trusted peer agent_ids (one per line); "
                                     "absent = trust-on-first-use")
    ap.add_argument("--human-key", help="present a hardware-principal (soft) key: who I work for")
    ap.add_argument("--ak-key", help="present a boot-attestation key: what I booted")
    ap.add_argument("--require-human", action="store_true", help="demand a live principal from the peer")
    ap.add_argument("--require-env", action="store_true", help="demand a boot quote from the peer")
    a = ap.parse_args()

    # Optional attestation gate. Trust is established END-TO-END here, peer↔peer;
    # the rendezvous never vouches for anyone. Everything below is inert unless
    # --attest is passed, so the un-attested path is byte-for-byte unchanged.
    identity = policy = attn = None
    attested = {}      # connect side: peer id  -> Verdict
    allow_serve = {}   # serve side:   peer addr -> bool (attested friend?)
    my_label = a.id
    if a.attest:
        if not (a.key and a.facts):
            print("--attest requires --key and --facts", file=sys.stderr); return 2
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import attest as attn, hwroot
        facts = json.load(open(a.facts)); my_label = facts.get("label", a.id)
        human = {"key": a.human_key, "alg": "ed25519"} if a.human_key else None
        identity = attn.load_identity(a.key, facts, human_token=human, ak_key=a.ak_key)
        roster = attn.load_roster(a.roster) if a.roster else None
        policy = {"roster": roster, "tofu": roster is None,
                  "require_human": a.require_human, "require_hardware_env": a.require_env,
                  "env_policy": {"known_good": {hwroot.boot_digest(identity["measurements"])},
                                 "require_hardware": False}}

    srv = (socket.gethostbyname(a.server), a.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(1.0)
    send = lambda addr, obj: sock.sendto(json.dumps(obj).encode(), addr)

    send(srv, {"op": "hello", "peer": a.id, "swarm": a.swarm})
    me, peer_dir = None, {}
    punched = {}          # peer id -> addr once path is confirmed
    targets = {}          # peer id -> reflexive addr the server told us to punch
    got = set()           # peers we've already fetched the payload from
    payload = open(a.payload, "rb").read() if a.payload else b"HELLO-FROM-" + a.id.encode()
    chunks = [payload[i:i+600] for i in range(0, len(payload), 600)] or [b""]
    rx = {}
    last_ping = last_connect = last_spray = last_get = 0
    t0 = time.time()

    while time.time() - t0 < a.timeout:
        now = time.time()
        if now - last_ping > 8:
            send(srv, {"op": "ping", "peer": a.id}); last_ping = now
        # retry the connect request until we have a path — the punch is lossy
        if a.connect and me and a.connect not in punched and now - last_connect > 2:
            send(srv, {"op": "connect", "peer": a.id, "swarm": a.swarm, "to": a.connect})
            last_connect = now
        # keep spraying syn to every known target until the path confirms
        if now - last_spray > 0.4:
            for pid, addr in targets.items():
                if pid not in punched:
                    send(addr, {"op": "syn", "peer": a.id})
            last_spray = now
        # attested fetch: once the peer is verified FRIEND, ask for the payload
        # (retried, so it survives a datagram lost during the handshake window)
        if (a.attest and a.connect in punched and a.connect not in got
                and attested.get(a.connect) and attested[a.connect]["friend"]
                and now - last_get > 0.5):
            send(punched[a.connect], {"op": "get", "peer": a.id}); last_get = now
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        try:
            msg = json.loads(data.decode())
        except Exception:
            continue
        op = msg.get("op")

        if op == "welcome":
            me = msg["you"]
            print(f"[{a.id}] reflexive address: {me[0]}:{me[1]} | swarm peers: {list(msg['peers'])}", flush=True)
        elif op == "punch":
            target = tuple(msg["addr"])
            if msg["peer"] not in targets:
                print(f"[{a.id}] punching {msg['peer']} at {target[0]}:{target[1]}", flush=True)
            targets[msg["peer"]] = target
            for _ in range(6):                      # opening burst
                send(target, {"op": "syn", "peer": a.id}); time.sleep(0.03)
        elif op == "syn":
            send(addr, {"op": "ack", "peer": a.id})
            targets.setdefault(msg["peer"], addr)   # learn the path from the syn too
        elif op == "ack":
            if msg["peer"] not in punched:
                punched[msg["peer"]] = addr
                print(f"[{a.id}] ✅ DIRECT PATH to {msg['peer']} via {addr[0]}:{addr[1]}", flush=True)
            if a.connect == msg["peer"] and msg["peer"] not in got:
                if a.attest:
                    if msg["peer"] not in attested:      # verify the peer, once
                        v = attn.gate_initiator(sock, addr, identity, policy)
                        sock.settimeout(1.0)
                        attested[msg["peer"]] = v
                        print(attn.render_verdict(v, me=my_label, peer=msg["peer"]) if v
                              else f"[{a.id}] ❌ attestation timed out with {msg['peer']}", flush=True)
                        if not (v and v["friend"]):
                            print(f"[{a.id}] ❌ REFUSING to fetch from unverified peer "
                                  f"{msg['peer']}", flush=True)
                            return 1
                    # a verified FRIEND: the periodic sender issues the 'get'
                else:
                    send(addr, {"op": "get", "peer": a.id})
        elif op == "hail" and a.attest:
            # serve side: a peer wants to talk — verify it before we serve a byte
            v = attn.gate_responder(sock, addr, identity, policy, msg)
            sock.settimeout(1.0)
            allow_serve[addr] = bool(v and v["friend"])
            peer_label = (msg.get("facts") or {}).get("label", "peer")
            print(attn.render_verdict(v, me=my_label, peer=peer_label) if v
                  else f"[{a.id}] ❌ attestation timed out with a hailing peer", flush=True)
        elif op == "get":
            if a.attest and not allow_serve.get(addr):
                print(f"[{a.id}] ❌ REFUSING to serve unverified peer at "
                      f"{addr[0]}:{addr[1]}", flush=True)
                continue
            print(f"[{a.id}] serving {len(payload)} bytes to {msg['peer']} directly", flush=True)
            for i, c in enumerate(chunks):
                sock.sendto(json.dumps({"op": "seg", "i": i, "n": len(chunks),
                                        "peer": a.id, "b": c.hex()}).encode(), addr)
                time.sleep(0.002)
        elif op == "seg":
            rx[msg["i"]] = bytes.fromhex(msg["b"])
            if len(rx) == msg["n"]:
                blob = b"".join(rx[i] for i in range(msg["n"]))
                import hashlib
                got.add(msg["peer"])
                print(f"[{a.id}] ✅ RECEIVED {len(blob)} bytes peer-to-peer from {msg['peer']} "
                      f"| md5 {hashlib.md5(blob).hexdigest()[:8]}", flush=True)
                return 0
    if a.connect and not punched:
        print(f"[{a.id}] ❌ no direct path established (symmetric NAT? needs TURN fallback)", flush=True)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
