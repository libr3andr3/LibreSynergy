#!/usr/bin/env python3
"""
LibreSynergy content signing — provenance for the sovereign mesh.

The creator signs; any untrusted peer may serve; every viewer verifies.
This is what makes P2P distribution safe: you never trust the peer that
hands you bytes, you trust the creator's Ed25519 signature over those bytes.
It is the sovereign equivalent of an "NFT" — cryptographic provenance and
authenticity, with no blockchain and no rent. (You may optionally anchor a
manifest hash on-chain later for public timestamping; not required.)

Identity: a creator IS their Ed25519 public key. The creator_id is the
fingerprint sha256(pubkey_DER)[:16]. Losing the key loses the identity —
production uses a maintainer quorum (threshold sigs) for release keys.

Manifest (the "source of truth") is JSON:
  {v, alg:"ed25519", creator, pubkey (b64 DER), content_id, sha256, size,
   media_type, created, sig (b64 over the canonical signing string)}

CLI:
  content_sign.py keygen  <name>                       -> <name>.key / <name>.pub
  content_sign.py sign    <file> --key k.key [--media video/mp2t]
                                                        -> <file>.manifest.json
  content_sign.py verify  <file> --manifest m.json [--creator <id>]
  content_sign.py id      <name>.pub                    -> print creator_id

For livestreams, sign each HLS segment as it's produced; the ordered set of
segment manifests is the stream's verifiable source of truth. A rolling
playlist can additionally chain the previous segment's sig for tamper-evident
ordering (see sign_stream_segment()).
"""
import argparse, base64, hashlib, json, os, subprocess, sys, tempfile, time

SIG_PREFIX = "ls-content-sig-v1"

def _openssl(args, inp=None):
    r = subprocess.run(["openssl"] + args, input=inp, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("openssl: " + r.stderr.decode(errors="replace").strip())
    return r.stdout

def _pubkey_der(pub_pem_path):
    return _openssl(["pkey", "-pubin", "-in", pub_pem_path, "-pubout", "-outform", "DER"])

def _fingerprint(pub_der: bytes) -> str:
    return hashlib.sha256(pub_der).hexdigest()[:16]

def _signing_string(m: dict) -> bytes:
    # deterministic, field-order-independent — never sign raw JSON
    return ("\n".join([SIG_PREFIX, m["content_id"], m["sha256"],
                       str(m["size"]), m["media_type"], m["creator"],
                       str(m.get("prev_sig", "")), str(m.get("seq", ""))])).encode()

# ---------------- operations ----------------------------------------------------
def keygen(name):
    key, pub = f"{name}.key", f"{name}.pub"
    if os.path.exists(key):
        raise SystemExit(f"{key} exists — refusing to overwrite a creator key")
    _openssl(["genpkey", "-algorithm", "ed25519", "-out", key])
    os.chmod(key, 0o600)
    with open(pub, "wb") as f:
        f.write(_openssl(["pkey", "-in", key, "-pubout"]))
    cid = _fingerprint(_pubkey_der(pub))
    print(f"creator key : {key}  (keep secret, chmod 600)")
    print(f"public key  : {pub}")
    print(f"creator_id  : {cid}")
    return cid

def creator_id_of(pub_pem_path):
    return _fingerprint(_pubkey_der(pub_pem_path))

def sign(path, key, media_type="application/octet-stream", seq=None, prev_sig=None, created=None):
    data = open(path, "rb").read()
    pub_pem = _openssl(["pkey", "-in", key, "-pubout"])
    with tempfile.NamedTemporaryFile(suffix=".pub", delete=False) as tf:
        tf.write(pub_pem); pub_tmp = tf.name
    try:
        pub_der = _pubkey_der(pub_tmp)
    finally:
        os.unlink(pub_tmp)
    m = {
        "v": 1, "alg": "ed25519",
        "creator": _fingerprint(pub_der),
        "pubkey": base64.b64encode(pub_der).decode(),
        "content_id": hashlib.sha256(data).hexdigest()[:24],
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "media_type": media_type,
        "created": created if created is not None else int(time.time()),
    }
    if seq is not None: m["seq"] = seq
    if prev_sig is not None: m["prev_sig"] = prev_sig
    # Ed25519 one-shot needs the message as a real file (it must know the size
    # up front) — a stdin pipe fails with "unable to determine file size".
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tf:
        tf.write(_signing_string(m)); msg_tmp = tf.name
    try:
        sig = _openssl(["pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", msg_tmp])
    finally:
        os.unlink(msg_tmp)
    m["sig"] = base64.b64encode(sig).decode()
    return m

def verify(path, manifest, expected_creator=None):
    """Return (ok, detail). Verifies content hash, signature, and identity."""
    m = manifest
    data = open(path, "rb").read()
    # 1) content integrity
    actual = hashlib.sha256(data).hexdigest()
    if actual != m.get("sha256"):
        return False, f"content hash mismatch (tampered payload): {actual[:12]} != {m.get('sha256','')[:12]}"
    if len(data) != m.get("size"):
        return False, "size mismatch"
    # 2) creator identity binds to the embedded public key
    pub_der = base64.b64decode(m["pubkey"])
    if _fingerprint(pub_der) != m.get("creator"):
        return False, "creator_id does not match embedded pubkey (identity forgery)"
    if expected_creator and m["creator"] != expected_creator:
        return False, f"wrong creator: got {m['creator']}, expected {expected_creator}"
    # 3) signature over the canonical string
    with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as tf:
        tf.write(pub_der); der_tmp = tf.name
    with tempfile.NamedTemporaryFile(suffix=".pub", delete=False) as tf2:
        pub_pem = _openssl(["pkey", "-pubin", "-inform", "DER", "-in", der_tmp, "-pubout"])
        tf2.write(pub_pem); pem_tmp = tf2.name
    with tempfile.NamedTemporaryFile(suffix=".sig", delete=False) as tf3:
        tf3.write(base64.b64decode(m["sig"])); sig_tmp = tf3.name
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tf4:
        tf4.write(_signing_string(m)); msg_tmp = tf4.name
    try:
        r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pem_tmp,
                            "-rawin", "-sigfile", sig_tmp, "-in", msg_tmp],
                           capture_output=True)
        if r.returncode != 0:
            return False, "signature invalid (not signed by this creator)"
    finally:
        for p in (der_tmp, pem_tmp, sig_tmp, msg_tmp):
            os.unlink(p)
    return True, f"authentic — creator {m['creator']}, {m['size']}B, {m['media_type']}"

# ---------------- cli -----------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen"); g.add_argument("name")
    s = sub.add_parser("sign"); s.add_argument("file"); s.add_argument("--key", required=True)
    s.add_argument("--media", default="application/octet-stream")
    s.add_argument("--seq", type=int); s.add_argument("--prev-sig")
    v = sub.add_parser("verify"); v.add_argument("file"); v.add_argument("--manifest", required=True)
    v.add_argument("--creator")
    i = sub.add_parser("id"); i.add_argument("pub")
    a = ap.parse_args()

    if a.cmd == "keygen":
        keygen(a.name)
    elif a.cmd == "id":
        print(creator_id_of(a.pub))
    elif a.cmd == "sign":
        m = sign(a.file, a.key, a.media, seq=a.seq, prev_sig=a.prev_sig)
        out = a.file + ".manifest.json"
        json.dump(m, open(out, "w"), indent=1)
        print(f"signed -> {out}  (creator {m['creator']}, content_id {m['content_id']})")
    elif a.cmd == "verify":
        ok, detail = verify(a.file, json.load(open(a.manifest)), a.creator)
        print(("✅ " if ok else "❌ ") + detail)
        sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
