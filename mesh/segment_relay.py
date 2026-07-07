#!/usr/bin/env python3
"""
LibreSynergy segment relay v0 — the two proven halves, joined.

Creator signs an HLS segment; an origin peer serves it over a hole-punched
UDP path; the viewer verifies the creator signature on arrival. No relay in
the data path, no trust in the serving peer. Times every stage and reports
the crypto (signing/verify) overhead separately from transport.

  # origin (serves a signed segment):
  segment_relay.py serve --id origin --swarm s1 --file seg.ts --key creator.key
  # viewer (punches, fetches, verifies):
  segment_relay.py fetch --id viewer --swarm s1 --from origin --creator <id> --out got.ts
"""
import argparse, base64, hashlib, json, socket, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_sign as cs

CHUNK = 1024

def _sock():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 0)); s.settimeout(1.0)
    return s

def _hello(s, srv, pid, swarm, send):
    send(srv, {"op": "hello", "peer": pid, "swarm": swarm})

def run(a):
    srv = (socket.gethostbyname(a.server), a.port)
    s = _sock()
    send = lambda addr, o: s.sendto(json.dumps(o).encode(), addr)
    raw = lambda addr, b: s.sendto(b, addr)
    _hello(s, srv, a.id, a.swarm, send)

    me = None
    targets, punched = {}, {}
    last_ping = last_connect = last_spray = 0
    t0 = time.time()

    # serve-side state
    seg = manifest = seg_frames = None
    stats = {}
    if a.cmd == "serve":
        t = time.time()
        m = cs.sign(a.file, a.key, media_type="video/mp2t", seq=a.seq)
        stats["sign_ms"] = (time.time() - t) * 1000
        seg = open(a.file, "rb").read()
        manifest = json.dumps(m).encode()
        # pre-frame the segment into numbered binary datagrams: 4-byte index + payload
        seg_frames = [(i, seg[i*CHUNK:(i+1)*CHUNK]) for i in range((len(seg)+CHUNK-1)//CHUNK)]
        print(f"[origin] signed {len(seg)}B segment | sign={stats['sign_ms']:.2f}ms | "
              f"sig+manifest={len(manifest)}B | frames={len(seg_frames)}", flush=True)

    # fetch-side state
    rx, rx_meta, fetch_t = {}, None, {}
    last_nack = 0
    # serve-side: remember who we're serving so we can honor NACK retransmits
    peer_addr = None

    def flush_frames(addr, indices):
        for idx in indices:
            raw(addr, b"SEG\x00" + idx.to_bytes(4, "big") + seg_frames[idx][1])
            time.sleep(0.0006)   # pace ~ line rate that home/campus links absorb

    while time.time() - t0 < a.timeout:
        now = time.time()
        if now - last_ping > 8:
            send(srv, {"op": "ping", "peer": a.id}); last_ping = now
        if a.cmd == "fetch" and me and a.frm not in punched and now - last_connect > 2:
            send(srv, {"op": "connect", "peer": a.id, "swarm": a.swarm, "to": a.frm}); last_connect = now
        if now - last_spray > 0.4:
            for pid, addr in targets.items():
                if pid not in punched: send(addr, {"op": "syn", "peer": a.id})
            last_spray = now
        # fetch side: periodically NACK still-missing frames until complete
        if a.cmd == "fetch" and rx_meta and len(rx) < rx_meta["n"] and now - last_nack > 0.5:
            missing = [i for i in range(rx_meta["n"]) if i not in rx][:400]
            send(punched[a.frm], {"op": "nack", "peer": a.id, "missing": missing})
            last_nack = now
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            continue
        if data[:4] == b"SEG\x00":
            idx = int.from_bytes(data[4:8], "big"); rx[idx] = data[8:]
            if rx_meta and len(rx) == rx_meta["n"]:
                fetch_t["recv_done"] = time.time()
                blob = b"".join(rx[i] for i in range(rx_meta["n"]))
                open(a.out, "wb").write(blob)
                tv = time.time()
                ok, detail = cs.verify(a.out, rx_meta["manifest"], a.creator)
                verify_ms = (time.time() - tv) * 1000
                dl = fetch_t["recv_done"] - fetch_t["recv_start"]
                mb = len(blob) / 1e6
                print(f"[viewer] received {len(blob)}B in {dl:.2f}s ({mb/dl:.2f} MB/s transport)", flush=True)
                print(f"[viewer] {'✅' if ok else '❌'} {detail} | verify={verify_ms:.2f}ms", flush=True)
                print("RESULT " + json.dumps({"segment_bytes": len(blob),
                      "manifest_bytes": rx_meta["manifest_bytes"], "verify_ms": round(verify_ms, 3),
                      "download_s": round(dl, 3), "authentic": ok}), flush=True)
                return 0 if ok else 1
            continue
        try:
            msg = json.loads(data.decode())
        except Exception:
            continue
        op = msg.get("op")
        if op == "welcome":
            me = msg["you"]; print(f"[{a.id}] reflexive {me[0]}:{me[1]}", flush=True)
        elif op == "punch":
            targets[msg["peer"]] = tuple(msg["addr"])
            for _ in range(6):
                send(tuple(msg["addr"]), {"op": "syn", "peer": a.id}); time.sleep(0.03)
        elif op == "syn":
            send(addr, {"op": "ack", "peer": a.id}); targets.setdefault(msg["peer"], addr)
        elif op == "ack":
            if msg["peer"] not in punched:
                punched[msg["peer"]] = addr
                print(f"[{a.id}] ✅ direct path to {msg['peer']} {addr[0]}:{addr[1]}", flush=True)
                if a.cmd == "fetch" and msg["peer"] == a.frm:
                    send(addr, {"op": "want", "peer": a.id})
        elif op == "want" and a.cmd == "serve":
            peer_addr = addr
            send(addr, {"op": "manifest", "peer": a.id, "n": len(seg_frames),
                        "manifest": base64.b64encode(manifest).decode()})
            flush_frames(addr, range(len(seg_frames)))
            print(f"[origin] served {len(seg)}B to {msg['peer']} ({len(seg_frames)} frames)", flush=True)
        elif op == "nack" and a.cmd == "serve" and peer_addr:
            flush_frames(peer_addr, msg.get("missing", []))
        elif op == "manifest" and a.cmd == "fetch":
            man = json.loads(base64.b64decode(msg["manifest"]))
            rx_meta = {"n": msg["n"], "manifest": man, "manifest_bytes": len(base64.b64decode(msg["manifest"]))}
            fetch_t["recv_start"] = time.time()
    print(f"[{a.id}] timeout (rx {len(rx)}/{rx_meta['n'] if rx_meta else '?'})", flush=True)
    return 1

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "fetch"):
        p = sub.add_parser(name)
        p.add_argument("--server", default="stun.example.com"); p.add_argument("--port", type=int, default=3478)
        p.add_argument("--id", required=True); p.add_argument("--swarm", default="s1")
        p.add_argument("--timeout", type=int, default=45)
        if name == "serve":
            p.add_argument("--file", required=True); p.add_argument("--key", required=True)
            p.add_argument("--seq", type=int, default=0)
        else:
            p.add_argument("--from", dest="frm", required=True); p.add_argument("--creator")
            p.add_argument("--out", default="/tmp/received-segment.ts")
    a = ap.parse_args()
    sys.exit(run(a))

if __name__ == "__main__":
    main()
