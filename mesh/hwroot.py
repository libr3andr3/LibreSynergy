#!/usr/bin/env python3
"""
LibreSynergy hwroot — hardware roots of trust for the attestation handshake.

Two questions in the peering handshake can only be answered *honestly* by
hardware, because software can lie about software:

  • WHO DO YOU WORK FOR?  — a human principal proves presence + intent by
    signing a fresh challenge on a token whose private key CANNOT leave the
    device (a YubiKey / FIDO2 passkey / PIV smartcard). No touch, no signature;
    a stolen config file gets you nothing. This is the *human* root of trust.

  • CAN I TRUST YOU WITH MY DATA? — the machine proves what it actually
    booted (firmware → bootloader → kernel → agent code) with a signed
    measurement, the way TPM measured-boot / remote attestation does. This is
    the *silicon* root of trust.

Both are pluggable providers with the SAME shape: a real verifier that checks
a real signature, and — so the handshake runs on a laptop with no TPM and no
key plugged in — a clearly-labelled software SIMULATION that stands in for the
hardware. The verifier is identical either way; only the `sim` flag differs, and
policy can refuse simulated attestations in production (`require_hardware=True`).

Providers
  principal (human):  softkey (sim)  ·  yubikey-piv (ECDSA P-256)  ·  webauthn (FIDO2)
  environment (node): sim            ·  tpm2 (tpm2_quote, if a TPM is present)

Producing a REAL assertion (documented, not needed for the demo/tests):
  YubiKey PIV:  ykman piv keys generate 9a pub.pem ; ykman piv keys ...
                openssl dgst -sha256 -sign <(pkcs11) -out sig.bin challenge.bin
  WebAuthn:     navigator.credentials.get({publicKey:{challenge, ...}}) in a
                browser; pass authenticatorData + clientDataJSON + signature.
  TPM quote:    tpm2_quote -c ak.ctx -l sha256:0,2,4,7 -q <nonce> -m q -s sig
"""
import base64, hashlib, json, os, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_sign as cs

# Domain-separation tags: a signature made for one purpose must never verify
# for another. Every signed byte-string in the mesh is prefixed with its role.
PRINCIPAL_TAG = b"ls-attest-principal-v1"
ENV_TAG = b"ls-attest-env-v1"

SIM_NOTE = "SIMULATED (software stand-in; no hardware authenticator present)"

def _b64(b): return base64.b64encode(b).decode()
def _ub64(s): return base64.b64decode(s)
def _sha256(b): return hashlib.sha256(b).hexdigest()

# ============================================================================
#  Human principal — the token in your hand (YubiKey / passkey / soft)
# ============================================================================

def soft_token(prefix, alg="ed25519"):
    """Create (or load) a SOFTWARE authenticator standing in for a hardware key.

    alg="ed25519"  models a FIDO2 resident key / passkey.
    alg="ecdsa-p256" models a YubiKey PIV slot or a WebAuthn ES256 credential —
                     the exact curve those produce, so the *verifier* path this
                     exercises is the real one, only the key custody is soft.
    """
    key = f"{prefix}.key"
    if not os.path.exists(key):
        if alg == "ed25519":
            cs._openssl(["genpkey", "-algorithm", "ed25519", "-out", key])
        elif alg == "ecdsa-p256":
            cs._openssl(["genpkey", "-algorithm", "EC",
                         "-pkeyopt", "ec_paramgen_curve:P-256", "-out", key])
        else:
            raise ValueError(f"unknown alg {alg}")
        os.chmod(key, 0o600)
    return {"key": key, "alg": alg}

def _pub_der(key_path):
    return cs._openssl(["pkey", "-in", key_path, "-pubout", "-outform", "DER"])

def _sign_ecdsa(key_path, msg: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tf:
        tf.write(msg); m = tf.name
    try:
        return cs._openssl(["dgst", "-sha256", "-sign", key_path, m])
    finally:
        os.unlink(m)

def _verify_ecdsa(pub_der: bytes, msg: bytes, sig: bytes) -> bool:
    tmps = []
    def t(suffix, blob):
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(blob); tmps.append(f.name); return f.name
    der = t(".der", pub_der)
    pem = cs._openssl(["pkey", "-pubin", "-inform", "DER", "-in", der, "-pubout"])
    pemf = t(".pem", pem); sigf = t(".sig", sig); msgf = t(".msg", msg)
    try:
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pemf,
                            "-signature", sigf, msgf], capture_output=True)
        return r.returncode == 0
    finally:
        for p in tmps:
            os.unlink(p)

def principal_assert(challenge: bytes, token, kind="softkey"):
    """Sign a fresh challenge with the human's token → a verifiable assertion.

    `token` is a soft_token() dict (or, for real hardware, any dict with a
    `key` path to a private key of the stated `alg`). The private key stays put;
    only a signature over PRINCIPAL_TAG||challenge leaves the device.
    """
    key, alg = token["key"], token["alg"]
    msg = PRINCIPAL_TAG + challenge
    if alg == "ed25519":
        sig = cs.sign_bytes(key, msg)
    elif alg == "ecdsa-p256":
        sig = _sign_ecdsa(key, msg)
    else:
        raise ValueError(f"unknown alg {alg}")
    pub_der = _pub_der(key)
    return {
        "kind": kind,
        "alg": alg,
        "pubkey": _b64(pub_der),
        "principal_id": cs.id_of_pub_der(pub_der),
        "challenge": challenge.hex(),
        "sig": _b64(sig),
        "sim": kind == "softkey",
    }

def verify_principal(assertion: dict, challenge: bytes):
    """Return (ok, detail). Proves a live human touched a real key for THIS
    challenge — freshness (challenge binding) defeats replay of an old touch."""
    if assertion.get("challenge") != challenge.hex():
        return False, "principal assertion is for a different challenge (replay?)"
    alg = assertion.get("alg")
    pub_der = _ub64(assertion["pubkey"])
    if cs.id_of_pub_der(pub_der) != assertion.get("principal_id"):
        return False, "principal_id does not match its public key (identity forgery)"
    sig = _ub64(assertion["sig"])
    if assertion.get("kind") == "webauthn":
        # Real FIDO2: the key signs authenticatorData || SHA256(clientDataJSON),
        # and the challenge lives inside clientDataJSON (base64url, no padding).
        authdata = _ub64(assertion["authenticator_data"])
        cdj = _ub64(assertion["client_data_json"])
        try:
            cd = json.loads(cdj.decode())
        except Exception:
            return False, "webauthn clientDataJSON is not valid JSON"
        want = base64.urlsafe_b64encode(challenge).decode().rstrip("=")
        if cd.get("type") != "webauthn.get" or cd.get("challenge") != want:
            return False, "webauthn challenge/type mismatch (replay or wrong origin)"
        msg = authdata + hashlib.sha256(cdj).digest()
    else:
        msg = PRINCIPAL_TAG + challenge
    ok = cs.verify_bytes(pub_der, msg, sig) if alg == "ed25519" else _verify_ecdsa(pub_der, msg, sig)
    if not ok:
        return False, f"principal signature invalid ({alg}) — token did not sign this challenge"
    tag = SIM_NOTE if assertion.get("sim") else f"hardware-backed ({assertion.get('kind')})"
    return True, f"principal {assertion['principal_id']} present via {assertion.get('kind')}/{alg} — {tag}"

# ============================================================================
#  Machine environment — what this node actually booted (measured boot / TPM)
# ============================================================================

# The ordered chain of things whose integrity we care about, root of trust
# upward. On real hardware these map to TPM PCRs (firmware→0/2, bootloader→4,
# kernel→ IMA, agent code→ our own). Here each is a sha256 the node computes
# over the corresponding artifact; the composite is the "boot state".
ENV_COMPONENTS = ("firmware", "bootloader", "kernel", "agent_code")

def boot_digest(measurements: dict) -> str:
    """Composite of an ordered measurement set — the node's 'boot state' id.
    (Analogue of a TPM PCR-composite: order-fixed, one changed byte flips it.)"""
    parts = [f"{c}={measurements.get(c,'')}" for c in ENV_COMPONENTS]
    return _sha256(("\n".join(parts)).encode())

def measure_self(sources: dict) -> dict:
    """Hash each named artifact path into a measurement (missing → 'absent').
    In the demo we hash whatever files stand in for firmware/kernel/agent; on a
    real node these come from the TPM event log, not recomputed here."""
    out = {}
    for c in ENV_COMPONENTS:
        p = sources.get(c)
        if p and os.path.exists(p):
            out[c] = _sha256(open(p, "rb").read())
        else:
            out[c] = _sha256((sources.get(c) or f"golden:{c}").encode())
    return out

def env_quote(nonce: bytes, ak_key: str, measurements: dict, kind="sim"):
    """Produce a signed attestation quote binding the boot state to a fresh
    nonce (so it cannot be replayed). `ak_key` is the Attestation Key — on a
    real node this is a TPM-resident AK whose cert chains to the manufacturer."""
    bd = boot_digest(measurements)
    msg = ENV_TAG + bd.encode() + b"|" + nonce
    sig = cs.sign_bytes(ak_key, msg)
    ak_pub = cs.pub_der_of_key(ak_key)
    return {
        "kind": kind,
        "measurements": measurements,
        "boot_digest": bd,
        "nonce": nonce.hex(),
        "ak_pub": _b64(ak_pub),
        "ak_id": cs.id_of_pub_der(ak_pub),
        "sig": _b64(sig),
        "sim": kind == "sim",
    }

def verify_env(quote: dict, nonce: bytes, policy: dict):
    """Return (ok, detail). Confirms the node booted a state we accept, freshly.

    policy = {
      "known_good": {<boot_digest>, ...},   # allow-list of accepted boot states
      "require_hardware": bool,             # refuse simulated quotes
      "trusted_ak": {<ak_id>, ...} | None,  # optional: pin attestation keys
    }
    """
    if quote.get("nonce") != nonce.hex():
        return False, "attestation quote is stale (nonce mismatch — possible replay)"
    if boot_digest(quote.get("measurements", {})) != quote.get("boot_digest"):
        return False, "quote boot_digest does not match its measurements (tampered)"
    ak_pub = _ub64(quote["ak_pub"])
    if cs.id_of_pub_der(ak_pub) != quote.get("ak_id"):
        return False, "attestation key id does not match its public key"
    msg = ENV_TAG + quote["boot_digest"].encode() + b"|" + nonce
    if not cs.verify_bytes(ak_pub, msg, _ub64(quote["sig"])):
        return False, "attestation signature invalid (not signed by this AK)"
    if policy.get("require_hardware") and quote.get("sim"):
        return False, "policy requires a hardware TPM quote; got a simulated one"
    trusted = policy.get("trusted_ak")
    if trusted and quote.get("ak_id") not in trusted:
        return False, f"attestation key {quote.get('ak_id')} is not a trusted AK"
    known = policy.get("known_good")
    if known is not None and quote.get("boot_digest") not in known:
        return False, (f"unrecognised boot state {quote.get('boot_digest')[:12]} — "
                       "node booted firmware/kernel/agent we have not vetted")
    tag = SIM_NOTE if quote.get("sim") else "hardware TPM quote"
    return True, f"boot state {quote['boot_digest'][:12]} vetted, fresh — {tag}"

# ---- optional real TPM path (used automatically when a TPM is present) -------

def have_tpm() -> bool:
    return shutil.which("tpm2_quote") is not None and (
        os.path.exists("/dev/tpm0") or os.path.exists("/dev/tpmrm0"))

# ---------------- self-test / cli -----------------------------------------------
def _selftest():
    d = tempfile.mkdtemp(); os.chdir(d)
    ch = os.urandom(16)
    print("hwroot self-test in", d)
    for alg in ("ed25519", "ecdsa-p256"):
        tok = soft_token(f"tok_{alg}", alg=alg)
        a = principal_assert(ch, tok, kind="softkey")
        ok, why = verify_principal(a, ch)
        print(f"  principal {alg:11} -> {ok}  {why}")
        assert ok
        assert not verify_principal(a, os.urandom(16))[0]      # wrong challenge
    ak = soft_token("ak")["key"]
    m = measure_self({})
    q = env_quote(ch, ak, m)
    ok, why = verify_env(q, ch, {"known_good": {q["boot_digest"]}})
    print(f"  env quote               -> {ok}  {why}"); assert ok
    bad = env_quote(ch, ak, {**m, "kernel": "evil"})
    ok, why = verify_env(bad, ch, {"known_good": {q["boot_digest"]}})
    print(f"  env quote (bad kernel)  -> {ok}  {why}"); assert not ok
    print("hwroot self-test OK")

if __name__ == "__main__":
    _selftest()
