#!/usr/bin/env python3
"""
Attested-peering test suite — the friend/foe gate, proven case by case.

Mirrors the proven-in-tests discipline of content_sign.py: every attack the
handshake is supposed to catch has a test that shows it caught. Pure stdlib
(unittest); crypto runs through openssl exactly as production does, so these
exercise the real signing/verification paths, not a mock.

    python3 -m unittest discover -s mesh/tests        # from the repo root
    python3 mesh/tests/test_attest.py                 # or directly
"""
import base64, hashlib, json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.dirname(HERE)
sys.path.insert(0, MESH)
import content_sign as cs          # noqa: E402
import agentfacts as af            # noqa: E402
import hwroot                      # noqa: E402
import attest                      # noqa: E402


class TmpBase(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ls-attest-test-")
        self._cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self._cwd)


class TestEd25519Primitives(TmpBase):
    def test_sign_verify_roundtrip_and_tamper(self):
        cs.keygen("k")
        pub = cs.pub_der_of_key("k.key")
        msg = b"transcript:abc123"
        sig = cs.sign_bytes("k.key", msg)
        self.assertTrue(cs.verify_bytes(pub, msg, sig))
        self.assertFalse(cs.verify_bytes(pub, b"other", sig))     # tampered message
        cs.keygen("j")
        self.assertFalse(cs.verify_bytes(cs.pub_der_of_key("j.key"), msg, sig))  # wrong key

    def test_id_is_stable_and_binds_pubkey(self):
        cs.keygen("k")
        self.assertEqual(cs.id_of_key("k.key"), cs.id_of_pub_der(cs.pub_der_of_key("k.key")))


class TestAgentFacts(TmpBase):
    def _facts(self):
        cs.keygen("op"); cs.keygen("node")
        f = af.build("node.key", "node.x", "X Community", operator_key="op.key",
                     capabilities=["mesh.punch"])
        return f

    def test_build_verifies(self):
        ok, why = af.verify(self._facts())
        self.assertTrue(ok, why)

    def test_operator_on_roster_is_flagged_trusted(self):
        f = self._facts()
        oppub = cs.pub_der_of_key("op.key"); opid = cs.id_of_pub_der(oppub)
        ok, why = af.verify(f, trusted_operators={opid: oppub})
        self.assertTrue(ok)
        self.assertIn("trusted", why)

    def test_tampered_field_breaks_self_signature(self):
        f = self._facts(); f["label"] = "node.evil"
        ok, _ = af.verify(f)
        self.assertFalse(ok)

    def test_forged_agent_id_rejected(self):
        f = self._facts(); f["agent_id"] = "deadbeefdeadbeef"
        ok, why = af.verify(f)
        self.assertFalse(ok)
        self.assertIn("identity forgery", why)

    def test_forged_delegation_rejected(self):
        # attacker swaps in a different operator's pubkey but can't forge the sig
        f = self._facts()
        cs.keygen("attacker")
        atk_pub = cs.pub_der_of_key("attacker.key")
        f["principal"]["delegation"]["operator_pub"] = base64.b64encode(atk_pub).decode()
        f["principal"]["delegation"]["operator_id"] = cs.id_of_pub_der(atk_pub)
        # self-sig still fails first (delegation is inside the signed body); either
        # way verification must reject.
        ok, _ = af.verify(f)
        self.assertFalse(ok)


class TestPrincipalHardwareRoot(TmpBase):
    def test_ed25519_passkey_assertion(self):
        tok = hwroot.soft_token("t", alg="ed25519")
        ch = os.urandom(16)
        a = hwroot.principal_assert(ch, tok)
        ok, _ = hwroot.verify_principal(a, ch)
        self.assertTrue(ok)
        self.assertFalse(hwroot.verify_principal(a, os.urandom(16))[0])   # replay/wrong challenge

    def test_ecdsa_piv_assertion(self):
        # the curve a YubiKey PIV slot / WebAuthn ES256 credential actually uses
        tok = hwroot.soft_token("t", alg="ecdsa-p256")
        ch = os.urandom(16)
        a = hwroot.principal_assert(ch, tok, kind="yubikey-piv")
        ok, why = hwroot.verify_principal(a, ch)
        self.assertTrue(ok, why)

    def test_tampered_signature_rejected(self):
        tok = hwroot.soft_token("t", alg="ed25519")
        ch = os.urandom(16)
        a = hwroot.principal_assert(ch, tok)
        a["sig"] = base64.b64encode(b"\x00" * 64).decode()
        self.assertFalse(hwroot.verify_principal(a, ch)[0])

    def test_real_webauthn_assertion_shape(self):
        # Build a genuine FIDO2/WebAuthn-shaped assertion (sig over
        # authenticatorData || SHA256(clientDataJSON)) and verify it.
        tok = hwroot.soft_token("wa", alg="ecdsa-p256")
        ch = os.urandom(16)
        client = {"type": "webauthn.get",
                  "challenge": base64.urlsafe_b64encode(ch).decode().rstrip("="),
                  "origin": "https://alice.example"}
        cdj = json.dumps(client).encode()
        authdata = os.urandom(37)                       # rpIdHash|flags|counter
        msg = authdata + hashlib.sha256(cdj).digest()
        sig = hwroot._sign_ecdsa(tok["key"], msg)
        pub = hwroot._pub_der(tok["key"])
        assertion = {
            "kind": "webauthn", "alg": "ecdsa-p256",
            "pubkey": base64.b64encode(pub).decode(),
            "principal_id": cs.id_of_pub_der(pub),
            "challenge": ch.hex(), "sig": base64.b64encode(sig).decode(),
            "authenticator_data": base64.b64encode(authdata).decode(),
            "client_data_json": base64.b64encode(cdj).decode(), "sim": False,
        }
        ok, why = hwroot.verify_principal(assertion, ch)
        self.assertTrue(ok, why)
        self.assertFalse(hwroot.verify_principal(assertion, os.urandom(16))[0])


class TestEnvironmentAttestation(TmpBase):
    def _quote(self, nonce, measurements=None):
        ak = hwroot.soft_token("ak")["key"]
        m = measurements or hwroot.measure_self({})
        return hwroot.env_quote(nonce, ak, m), m

    def test_good_quote_in_policy(self):
        n = os.urandom(16)
        q, m = self._quote(n)
        ok, _ = hwroot.verify_env(q, n, {"known_good": {q["boot_digest"]}})
        self.assertTrue(ok)

    def test_replayed_quote_rejected(self):
        q, m = self._quote(os.urandom(16))
        ok, why = hwroot.verify_env(q, os.urandom(16), {"known_good": {q["boot_digest"]}})
        self.assertFalse(ok)
        self.assertIn("stale", why)

    def test_unvetted_boot_state_rejected(self):
        n = os.urandom(16)
        q, m = self._quote(n)
        ok, why = hwroot.verify_env(q, n, {"known_good": {"some-other-digest"}})
        self.assertFalse(ok)
        self.assertIn("unrecognised", why)

    def test_tampered_measurements_rejected(self):
        n = os.urandom(16)
        q, m = self._quote(n)
        q["measurements"]["kernel"] = "swapped"           # digest no longer matches
        ok, _ = hwroot.verify_env(q, n, {"known_good": {q["boot_digest"]}})
        self.assertFalse(ok)

    def test_policy_can_require_hardware(self):
        n = os.urandom(16)
        q, m = self._quote(n)                              # sim quote
        ok, why = hwroot.verify_env(q, n, {"known_good": {q["boot_digest"]},
                                           "require_hardware": True})
        self.assertFalse(ok)
        self.assertIn("hardware", why)


class TestHandshake(TmpBase):
    """Drive the three-message handshake in-process and assert each verdict."""

    def _world(self):
        cs.keygen("opA"); cs.keygen("opB")
        A = attest._mk_identity("A", "node.alice", "Alice Community", "opA.key")
        B = attest._mk_identity("B", "node.bob", "Bob Collective", "opB.key")
        opB_pub = cs.pub_der_of_key("opB.key")
        policy_A = {
            "roster": {B["facts"]["agent_id"]: "node.bob"}, "tofu": False,
            "trusted_operators": {cs.id_of_pub_der(opB_pub): opB_pub},
            "require_human": True, "require_trusted_operator": True,
            "env_policy": {"known_good": {hwroot.boot_digest(B["measurements"])}},
        }
        return A, B, policy_A

    def _run(self, A, B, policy_A, tamper=None):
        hail, sA = attest.make_hail(A); sA["facts_a"] = A["facts"]
        vouch, cB = attest.make_vouch(B, hail)
        vouch = attest._apply_tamper(vouch, cB, B, tamper, sA["nonce_a"])
        return attest.initiator_evaluate(policy_A, sA, vouch)

    def test_honest_peer_is_friend(self):
        A, B, p = self._world()
        v = self._run(A, B, p)
        self.assertTrue(v["friend"], v["checks"])
        for k in ("friend_or_foe", "trust_my_data", "who_you_work_for"):
            self.assertTrue(v["checks"][k]["ok"], (k, v["checks"][k]))

    def test_impostor_fails_identity(self):
        A, B, p = self._world()
        v = self._run(A, B, p, tamper="impostor")
        self.assertFalse(v["friend"])
        self.assertFalse(v["checks"]["friend_or_foe"]["ok"])

    def test_forged_id_fails_identity(self):
        A, B, p = self._world()
        v = self._run(A, B, p, tamper="forge_id")
        self.assertFalse(v["checks"]["friend_or_foe"]["ok"])

    def test_bad_boot_fails_integrity(self):
        A, B, p = self._world()
        v = self._run(A, B, p, tamper="bad_boot")
        self.assertFalse(v["checks"]["trust_my_data"]["ok"])
        self.assertTrue(v["checks"]["friend_or_foe"]["ok"])       # identity still fine

    def test_replayed_env_fails_integrity(self):
        A, B, p = self._world()
        v = self._run(A, B, p, tamper="replay_env")
        self.assertFalse(v["checks"]["trust_my_data"]["ok"])

    def test_missing_human_fails_allegiance_when_required(self):
        A, B, p = self._world()
        v = self._run(A, B, p, tamper="no_human")
        self.assertFalse(v["checks"]["who_you_work_for"]["ok"])

    def test_replayed_human_fails_allegiance(self):
        A, B, p = self._world()
        v = self._run(A, B, p, tamper="replay_human")
        self.assertFalse(v["checks"]["who_you_work_for"]["ok"])

    def test_stranger_off_roster_fails_identity(self):
        A, B, p = self._world()
        p["roster"] = {"0000000000000000": "someone-else"}       # Bob not listed
        v = self._run(A, B, p)                                    # honest, but unknown
        self.assertFalse(v["checks"]["friend_or_foe"]["ok"])

    def test_untrusted_operator_fails_allegiance(self):
        A, B, p = self._world()
        p["trusted_operators"] = {}                               # nobody trusted
        v = self._run(A, B, p)
        self.assertFalse(v["checks"]["who_you_work_for"]["ok"])

    def test_mutual_both_sides_evaluate(self):
        A, B, p = self._world()
        hail, sA = attest.make_hail(A); sA["facts_a"] = A["facts"]
        vouch, cB = attest.make_vouch(B, hail)
        seal, _ = attest.make_seal(A, sA, vouch)
        v_ab = attest.initiator_evaluate(p, sA, vouch)
        policy_B = {"tofu": True, "require_human": True,
                    "env_policy": {"known_good": {hwroot.boot_digest(A["measurements"])}}}
        v_ba = attest.responder_evaluate(policy_B, cB, seal)
        self.assertTrue(v_ab["friend"] and v_ba["friend"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
