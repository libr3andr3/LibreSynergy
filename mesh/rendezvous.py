#!/usr/bin/env python3
"""
LibreSynergy rendezvous — STUN-style UDP tracker for the community mesh.

Runs on the public VPS. Never touches stream bytes: it only observes each
peer's NAT-reflexive address and coordinates simultaneous UDP hole punches.
The sovereign-relay philosophy, applied to P2P: the middle stays dumb.

Datagram protocol (JSON, one message per packet):
  peer -> server
    {"op":"hello","peer":"<id>","swarm":"<name>"}   register + discover
    {"op":"ping","peer":"<id>"}                      NAT keepalive (~15s)
    {"op":"connect","peer":"<id>","to":"<other>"}    request a punch
  server -> peer
    {"op":"welcome","you":[ip,port],"peers":{id:[ip,port],..}}
    {"op":"pong"}
    {"op":"punch","peer":"<id>","addr":[ip,port]}    sent to BOTH sides
    {"op":"error","msg":"..."}

Peers expire after EXPIRY seconds without a ping. v0 is unauthenticated —
production peers get quorum-signed identities (see protocol decisions).
"""
import json, socket, sys, time

HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3478
EXPIRY = 60

peers = {}   # (swarm, id) -> {"addr": (ip, port), "seen": ts}

def swarm_view(swarm, exclude=None):
    now = time.time()
    return {pid: list(rec["addr"]) for (sw, pid), rec in peers.items()
            if sw == swarm and pid != exclude and now - rec["seen"] < EXPIRY}

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"rendezvous listening on udp/{PORT}", flush=True)
    send = lambda addr, obj: sock.sendto(json.dumps(obj).encode(), addr)
    last_sweep = time.time()
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        except OSError:
            continue
        op = msg.get("op")
        pid = str(msg.get("peer", ""))[:64]
        swarm = str(msg.get("swarm", "default"))[:64]

        if op == "hello" and pid:
            peers[(swarm, pid)] = {"addr": addr, "seen": time.time()}
            send(addr, {"op": "welcome", "you": list(addr),
                        "peers": swarm_view(swarm, exclude=pid)})
            print(f"hello {swarm}/{pid} @ {addr[0]}:{addr[1]} "
                  f"({len(swarm_view(swarm))+0} peers in swarm)", flush=True)

        elif op == "ping" and pid:
            for key in list(peers):
                if key[1] == pid and peers[key]["addr"][0] == addr[0]:
                    peers[key]["addr"] = addr
                    peers[key]["seen"] = time.time()
            send(addr, {"op": "pong"})

        elif op == "connect" and pid:
            target = str(msg.get("to", ""))[:64]
            a = peers.get((swarm, pid))
            b = peers.get((swarm, target))
            if not (a and b):
                send(addr, {"op": "error", "msg": f"peer {target} not in swarm"})
                continue
            # simultaneous punch: tell each side the other's reflexive address
            send(a["addr"], {"op": "punch", "peer": target, "addr": list(b["addr"])})
            send(b["addr"], {"op": "punch", "peer": pid, "addr": list(a["addr"])})
            print(f"punch {swarm}: {pid}({a['addr'][0]}:{a['addr'][1]}) <-> "
                  f"{target}({b['addr'][0]}:{b['addr'][1]})", flush=True)

        # periodic sweep
        if time.time() - last_sweep > EXPIRY:
            cutoff = time.time() - EXPIRY
            for key in [k for k, v in peers.items() if v["seen"] < cutoff]:
                del peers[key]
            last_sweep = time.time()

if __name__ == "__main__":
    main()
