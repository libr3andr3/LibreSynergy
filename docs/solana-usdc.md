# USDC-on-Solana checkout (optional)

Accept **USDC on Solana** for premium membership — the fastest-growing crypto
payment rail — non-custodially, alongside Stripe (card) and BTCPay (BTC/Monero).
All three settle to the same Authentik `premium` group.

## How it works (Solana Pay, non-custodial)

One merchant address receives every payment. Each invoice gets a unique
**reference** public key (a read-only marker the payer's wallet includes in the
transaction). A background watcher polls a hosted Solana RPC for transactions
referencing it and confirms the USDC amount landed in your account. **No private
keys ever touch the server** — only your public receiving address.

```
buyer taps "Pay with USDC" → wallet sends USDC to merchant, tagged with reference
                                   │
      payments-bridge watcher ─────┴─ getSignaturesForAddress(reference)
                                      getTransaction → verify owner+mint+amount
                                      → grant premium (same path as Stripe/BTCPay)
```

## Enable it

1. **Get a hosted RPC endpoint.** Public endpoints (`api.mainnet-beta.solana.com`)
   are rate-limited and unreliable for a watcher — use a keyed provider
   (Helius / Alchemy / QuickNode), e.g. `https://mainnet.helius-rpc.com/?api-key=…`.
2. **Set your receiving address.** A Solana wallet you control. For safety, this
   can be a watch-only-published address; spend keys stay offline.
3. Fill `${LS_SECRETS_DIR}/solana.env` (created by `./bin/ls init` from the
   example):
   ```
   SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
   SOLANA_NETWORK=mainnet-beta
   SOLANA_MERCHANT_ADDRESS=<your Solana wallet address>
   SOLANA_USDC_MINT=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
   ```
4. Recreate the bridge: `./bin/ls up payments` (or
   `docker compose -p payments_bridge up -d --force-recreate`).
   `GET /healthz` should show `"solana": true`; the upgrade page shows
   **Pay with USDC (Solana)**.

Leaving any of RPC_URL / MERCHANT_ADDRESS / USDC_MINT empty keeps the feature
**off** — the button is hidden and the watcher idles.

## Money safety (hard rule)

Verify on **devnet first**: set `SOLANA_NETWORK=devnet`, a devnet RPC, and a
devnet USDC mint, and confirm a test payment grants premium — **then** switch to
mainnet with a human watching the first real payment. The pay page shows a
`⚠ test network` banner whenever `SOLANA_NETWORK` isn't `mainnet-beta`.

## Notes

- USDC has 6 decimals; the watcher matches the exact base-unit amount (overpayment
  is accepted, underpayment is not).
- The pay page renders a scan-to-pay QR when the pure-python `segno` package is
  present (the payments unit installs it at boot); without it, the deep-link
  button + copyable address/reference still work.
- Adding another SPL token (e.g. a stablecoin on another chain) is the same
  pattern: a new mint + watcher — see `apps/payments_bridge/app.py`.
