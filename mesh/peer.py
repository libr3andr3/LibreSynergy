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
    a = ap.parse_args()

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
    last_ping = last_connect = last_spray = 0
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
                send(addr, {"op": "get", "peer": a.id})
        elif op == "get":
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
