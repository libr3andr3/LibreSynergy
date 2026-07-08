#!/usr/bin/env python3
"""
LibreSynergy wg-punch — hole-punch a direct UDP path for WireGuard.

Binds the WireGuard listen port itself, coordinates via the community
rendezvous (mesh/rendezvous.py on the sovereign VPS), confirms a direct
peer-to-peer path, prints the peer's working endpoint, and exits leaving
the NAT mapping hot. Bring WireGuard up on the same port immediately after:

    wg-punch.py --server 203.0.113.10 --id node --peer studio \
                --swarm wgmesh --wg-port 51888
    -> stdout: PUNCHED <peer-ip> <peer-port>

The interface must be DOWN while punching (the port must be free).
"""
import argparse, json, socket, sys, time

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--port", type=int, default=3478)
    ap.add_argument("--id", required=True)
    ap.add_argument("--peer", required=True)
    ap.add_argument("--swarm", default="wgmesh")
    ap.add_argument("--wg-port", type=int, required=True)
    ap.add_argument("--timeout", type=int, default=60)
    a = ap.parse_args()

    srv = (socket.gethostbyname(a.server), a.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", a.wg_port))
    sock.settimeout(0.5)
    send = lambda addr, obj: sock.sendto(json.dumps(obj).encode(), addr)

    me = None
    target = None          # reflexive addr the server told us to punch
    confirmed = None       # addr we actually heard the peer from
    last_hello = last_connect = last_spray = 0.0
    t0 = time.time()

    while time.time() - t0 < a.timeout:
        now = time.time()
        if now - last_hello > 3:
            send(srv, {"op": "hello", "peer": a.id, "swarm": a.swarm})
            last_hello = now
        if me and not confirmed and now - last_connect > 2:
            send(srv, {"op": "connect", "peer": a.id, "swarm": a.swarm, "to": a.peer})
            last_connect = now
        if target and now - last_spray > 0.3:
            send(target, {"op": "syn", "peer": a.id})
            last_spray = now
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data.decode())
        except socket.timeout:
            continue
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        op = msg.get("op")
        if op == "welcome":
            if not me:
                me = msg["you"]
                print(f"# reflexive: {me[0]}:{me[1]}", file=sys.stderr, flush=True)
        elif op == "punch" and msg.get("peer") == a.peer:
            target = tuple(msg["addr"])
            for _ in range(6):
                send(target, {"op": "syn", "peer": a.id}); time.sleep(0.02)
        elif op == "syn" and msg.get("peer") == a.peer:
            send(addr, {"op": "ack", "peer": a.id})
            target = target or addr
            confirmed = confirmed or addr    # peer's packets reach us here
        elif op == "ack" and msg.get("peer") == a.peer:
            confirmed = addr
        if confirmed:
            # a few extra acks so the other side confirms too, then done
            for _ in range(6):
                send(confirmed, {"op": "ack", "peer": a.id}); time.sleep(0.05)
            print(f"PUNCHED {confirmed[0]} {confirmed[1]}", flush=True)
            return 0

    print("FAILED no direct path (symmetric NAT?)", flush=True)
    return 1

if __name__ == "__main__":
    sys.exit(main())
