# Monero (XMR) — private payments on your own node — profile: `xmr`

Card payments tell a processor who supports you. Bitcoin tells the whole
world, forever — every donation to your community is public chain data,
linkable to the sender. Monero is the option for members who want to support
you **privately**: amounts, senders, and receivers are shielded by default,
and with this profile the entire path — P2P node, wallet, invoice — runs on
hardware you own. No processor, no chain analytics, no third party at all.

```
member's wallet ──(Monero network)──► your monerod (pruned node, ~95 GB)
                                            │ RPC, compose-network only
                                     monero-wallet-rpc (VIEW-ONLY wallet)
                                            │
                                     BTCPay Server ──settled──► invoice paid
```

## What you need

- The `btcpay` profile running (Monero rides on BTCPay — see the btcpay
  notes in [compose/55-btcpay.yml](../compose/55-btcpay.yml)).
- **~95 GB of disk** for the pruned Monero chain, and patience: initial sync
  takes days on a home connection. Start it early; Stripe and Bitcoin keep
  working meanwhile.

## Enable

```bash
./bin/ls up btcpay xmr
```

Then, in the BTCPay UI (`https://btcpay.<your-domain>`):

1. **Server Settings → Plugins → Monero → install**, restart when prompted
   (`./bin/ls restart btcpayserver`).
2. In your store: **Wallets → Monero → Set up**. The plugin talks to your
   `monero-wallet-rpc` (already wired via `BTCPAY_XMR_*`) and creates the
   store wallet in `${LS_DATA_DIR}/btcpay/monero/wallet`.
3. Create an invoice and pay it from any Monero wallet to verify.

## Funds safety

The wallet-rpc holds a **view-only wallet**: it can watch payments arrive,
it cannot spend them. Keep the seed offline (write it down when the plugin
shows it — it is shown once). Sweep funds periodically to a wallet whose
keys have never touched this server, same discipline as the Bitcoin
watch-only xpub.

## Honest limits

- **Sync time is real.** Days, not minutes. `docker logs -f` the `monerod`
  service to watch progress; BTCPay shows the node as unavailable until
  synced.
- **Refunds are manual.** Monero payments carry no return address by design;
  collect a refund address from the member if you ever need one.
- **Your node is your uptime.** If monerod is down, Monero checkout is down
  — the payments bridge and Stripe are unaffected.
