# Attested peering — friend or foe, before the tunnel

> *Tu dispositivo es tu casa, y nadie entra sin tu consentimiento.* — [MANIFESTO](../MANIFESTO.md)
>
> The sovereign mesh could already **find** a peer and **punch** a direct path
> to it, and a creator could **sign** content so any untrusted peer may serve
> it. What it could not do was let two peers verify *each other* before a
> tunnel comes up. This is that missing handshake.

Two LibreSynergy nodes about to federate — mesh a WireGuard link, seed each
other's swarms, subscribe to each other's feeds — first run a short, mutual,
replay-proof handshake that answers three questions with cryptography instead
of trust-me:

| The question | What proves it | Where it lives |
|---|---|---|
| **Are you friend or foe?** | the peer signs *this session's* transcript with the Ed25519 key its identity is derived from — key possession, not a claim | `attest.py` + `content_sign.py` |
| **Can I trust you with my data?** | a fresh, signed measured-boot / TPM quote of what the node actually booted (firmware → bootloader → kernel → agent) | `hwroot.py` (env) |
| **Who do you work for?** | a named operator *delegated* authority to the node, **and** a human is present *right now* on a hardware token (YubiKey / passkey) | `hwroot.py` (principal) + `agentfacts.py` |

Only if **both** sides answer all three to each other's satisfaction does the
connection proceed. Trust is established **end-to-end, peer↔peer**: the
rendezvous never vouches for anyone, exactly as it never sees a stream byte.

## The fourth trust root

[architecture-mesh.md](architecture-mesh.md) names three trust roots that keep
the mesh honest. Attested peering adds the fourth:

1. **Content authenticity** — the creator's Ed25519 key signs content/segments.
2. **Binary integrity** — a maintainer quorum signs every mesh client release.
3. **Transport** — TLS terminates on the community's own node.
4. **Peer identity (new)** — a node proves *who it is, what it booted, and who
   it works for* before another node connects to it.

The first three tell you the *bytes* and the *code* are trustworthy. The fourth
tells you the *peer on the other end of the socket* is.

## The handshake (three messages)

```
  A ──hail──►  B     A: nonce_a, AgentFacts_A
  A ◄─vouch──  B     B: nonce_b, AgentFacts_B, sig_B(transcript),
                        env_quote_B(nonce_a), principal_B(nonce_a)
  A ──seal──►  B     A: sig_A(transcript), env_quote_A(nonce_b), principal_A(nonce_b)

  transcript = H( proto | nonce_a | nonce_b | id_a | id_b | H(facts_a) | H(facts_b) )
```

- **Nonces** make every run unique — an old vouch/quote/assertion cannot be
  replayed into a new session.
- **Signing the transcript** (not a bare nonce) binds key-possession to the
  *whole* exchange, so a man-in-the-middle can't splice two conversations.
- Each side's environment quote and principal assertion are computed over the
  **peer's** nonce, so they are provably fresh, not recorded earlier.
- It is **mutual**: `A` judges `B` from the vouch, `B` judges `A` from the seal,
  each against its own local policy.

The verifier is a pure function — `attest.evaluate(policy, facts, transcript,
sig, human, env, my_nonce) → Verdict` — which is exactly why it is easy to test
and easy to lift into another registry (see *NANDA* below).

## Policy — you decide what "friend" means

`evaluate()` is driven by a policy dict, so each community sets its own bar:

```python
policy = {
  "roster": {agent_id: label, ...} | None,  # known-peer allow-list (friend/foe gate)
  "tofu": False,                            # trust unknown peers on first use?
  "trusted_operators": {operator_id: pubkey},
  "require_human": True,                    # demand a live hardware principal
  "require_hardware_env": False,            # demand a real TPM quote (not simulated)
  "require_trusted_operator": True,         # the principal must be one you trust
  "env_policy": {"known_good": {boot_digest, ...}, "require_hardware": False},
}
```

A closed community ships a `roster` and requires a live human; an open swarm can
run `tofu: True` and gate only on content signatures. Same code, different bar.

## The two hardware roots of trust

Software can lie about software, so the two questions that matter most are
anchored in hardware:

- **The human root — a token in your hand.** `who do you work for?` is answered
  by a signature over a fresh challenge from a device whose private key *cannot
  leave it* and that requires a physical touch: a **YubiKey**, a FIDO2 passkey,
  or a PIV smartcard. No touch, no signature; a stolen config file is worthless.
  `hwroot.py` verifies real FIDO2/WebAuthn assertions (signature over
  `authenticatorData ‖ SHA256(clientDataJSON)`, ES256 or EdDSA) and PIV/ECDSA
  signatures. Producing one:
  ```
  # WebAuthn (browser): navigator.credentials.get({publicKey:{challenge,…}})
  #   → pass authenticatorData, clientDataJSON, signature into the assertion.
  # YubiKey PIV: ykman piv keys generate 9a pub.pem   (then sign the challenge)
  ```
- **The silicon root — what the machine booted.** `can I trust you with my
  data?` is answered by a signed measurement of the boot chain, the way TPM
  remote attestation works: an ordered set of digests (firmware, bootloader,
  kernel, agent code) composited into a `boot_digest`, signed by an attestation
  key, checked against a policy allow-list of vetted boot states. On a machine
  with a TPM, `tpm2_quote` produces the real thing; `hwroot.have_tpm()` detects
  it. This is the natural home for firmware-liberation work (coreboot/Heads
  measured boot): *trust rooted in a bootloader you own, not a cloud you rent.*

### Honestly: what's real and what's simulated

Following [security.md](security.md)'s two-halves discipline:

- **Real, today:** the identity proof (Ed25519 key possession over the session
  transcript), the AgentFacts passport + operator delegation, the nonce/replay
  protection, the transcript binding, and the **verifiers** for FIDO2/WebAuthn,
  PIV/ECDSA, and TPM-style quotes. These run through openssl exactly as
  production does — proven in `mesh/tests/test_attest.py` (26 cases).
- **Simulated when hardware is absent:** if no YubiKey is plugged in and no TPM
  is present, a clearly-labelled **software key** stands in for the token and a
  **software attestation key** stands in for the TPM, so the handshake runs on a
  bare laptop. Every simulated attestation carries `"sim": true` and prints
  `SIMULATED`, and policy can refuse them (`require_hardware: true`,
  `require_hardware_env: true`). Nothing pretends to be hardware that isn't.
- **Not yet:** identity **revocation** (a compromised key is trusted until it
  ages out of your roster), threshold/quorum operator keys (designed in
  content_sign.py, not wired here), and a shared registry of `known_good` boot
  digests (today each operator curates its own).

## What each check catches (proven in tests)

| Attack | Caught by |
|--------|-----------|
| Impostor claims a peer's identity but can't sign with its key | transcript signature invalid → **friend-or-foe ❌** |
| Forged identity (claim a pubkey that isn't yours) | `agent_id` must equal `sha256(embedded pubkey)` → **❌** |
| Unknown peer talks its way in | not on the roster and TOFU disabled → **❌** |
| Node booted tampered firmware / an unpatched kernel | `boot_digest` not in `known_good` → **trust-my-data ❌** |
| Replay of an old attestation quote | quote nonce ≠ this session's nonce → **❌** |
| Agent with no human behind it | no live principal assertion, `require_human` → **who-do-you-work-for ❌** |
| Replayed human touch from an earlier session | principal assertion challenge mismatch → **❌** |
| Node working for an operator you don't trust | operator not in `trusted_operators` → **❌** |

## Try it

```bash
# the whole story in one command — no network, no hardware:
python3 mesh/attest.py demo --all
# watch one question go red on cue:
python3 mesh/attest.py demo --tamper impostor      # friend-or-foe fails
python3 mesh/attest.py demo --tamper bad_boot       # trust-my-data fails
python3 mesh/attest.py demo --tamper no_human       # who-do-you-work-for fails

# the tests (26 cases, stdlib only):
python3 -m unittest discover -s mesh/tests

# over a real hole-punched path: gate peer.py so it federates only with a
# verified peer (see the two-node walkthrough below).
```

### Gating the real mesh (`peer.py --attest`)

```bash
# once: give each node an identity and a passport
python3 mesh/attest.py keygen node             # or content_sign.py keygen
python3 mesh/agentfacts.py build --key node.key --label node.alice \
        --principal "Alice Community" --operator-key operator.key --out alice.facts.json

# server side — verifies whoever dials before serving a byte:
python3 mesh/peer.py --server stun.example.com --id node.bob --swarm s1 \
        --payload seg.ts --attest --key bob.key --facts bob.facts.json --roster bob.roster

# dialer — verifies the server before fetching:
python3 mesh/peer.py --server stun.example.com --id node.alice --swarm s1 \
        --connect node.bob --attest --key alice.key --facts alice.facts.json --roster alice.roster
```

A `roster` is one trusted `agent_id` per line (`#` comments allowed). Omit it
for trust-on-first-use. Without `--attest`, `peer.py` behaves exactly as before.

## Native to NANDA's Internet of Agents

The naming is deliberate. NANDA (MIT's "Networked Agents and Decentralized AI")
frames an agentic web where agents **discover, verify, and collaborate** across
decentralized networks — and its building blocks include *Identity, Trust, Auth,
Privacy*. Attested peering is those blocks for a real, running P2P community:

- **AgentFacts** here is a signed, self-describing passport — the same document a
  NANDA Index / registry would resolve to find and vet an agent.
- **`evaluate()`** is a self-contained trust verifier; it drops into a registry's
  "Trust" block or stands up as a hosted attestation service other agents call.
- The three questions are the questions any agent should answer before it acts
  on your behalf or touches your data — asked here between community nodes, but
  identical between autonomous agents.

Content integrity ([content_sign.py](../mesh/content_sign.py)) proves the
*bytes*; attested peering proves the *peer*. Together they are what makes a
decentralized network safe to actually connect to.
