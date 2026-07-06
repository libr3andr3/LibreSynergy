# Operations

The honest promise of LibreSynergy is that operating it takes minutes per
month — *if* you do the three boring things: back up, update, and run
`ls doctor` after any change. This page is those three things, plus the two
gotchas everyone hits once.

## Daily driving

```bash
ls up               # start / apply compose changes
ls down             # stop everything (data is untouched)
ls doctor           # end-to-end health check; run after ANY change
ls logs <service>   # follow logs, e.g. ls logs synapse
```

`ls` is a thin wrapper around `docker compose` with the right env file and
compose file list. Anything it does not cover, do directly with
`docker compose --env-file libresynergy.env ...` from the repo root.

## Backups

Three things constitute your community, and all three must be backed up:

1. `libresynergy.env` — the configuration
2. `${LS_SECRETS_DIR}` — the credentials
3. `${LS_DATA_DIR}` — the data

**The simple, always-correct way (cold backup, ~2 min of downtime):**

```bash
ls down
tar -czf /backup/libresynergy-$(date +%F).tar.gz \
    libresynergy.env "${LS_SECRETS_DIR}" "${LS_DATA_DIR}"
ls up
```

**The no-downtime way:** dump the databases live, then archive the rest.
Databases must be dumped, not file-copied, while running — copying a live
database directory produces a corrupt backup. For example, for Authentik's
Postgres:

```bash
docker compose exec -T authentik-postgres \
  pg_dump -U authentik authentik > /backup/authentik-$(date +%F).sql
```

Repeat for each database container (Synapse's Postgres, the LMS database),
then tar `${LS_DATA_DIR}` excluding the live database directories.

**Get it off the machine, encrypted.** A backup on the same disk protects
against nothing that matters. Encrypt (the archive contains every secret and
every private message) and ship it elsewhere — `restic` with an encrypted
repository on any cheap object storage is a good fit. Schedule it with cron,
weekly at minimum, and **test a restore once** before you trust it.

## Restore

On a fresh node:

1. Install the OS, clone the repo, run `scripts/bootstrap-node.sh`.
2. Restore `libresynergy.env` to the repo root, and the secrets and data
   directories to the paths named inside it. Check ownership and that
   secrets files are mode 600.
3. If the VPS also changed, run `scripts/bootstrap-vps.sh` against the new
   one and update DNS to its IP.
4. `ls up`, then `ls doctor`.

Because the data subpaths under `${LS_DATA_DIR}` are stable, the containers
find everything exactly where they left it.

## Updates

```bash
git pull                       # get the new release
less CHANGELOG.md              # read what changed BEFORE applying it
docker compose pull            # fetch updated images
ls up                          # recreates only what changed
ls doctor                      # verify
```

Take a backup before any update that touches databases (the changelog will
say). Update on a quiet day, not five minutes before the community webinar.

## Secrets rotation

All secrets live in `${LS_SECRETS_DIR}/*.env`. Rotating one is: change the
value, restart the services that consume it, run `ls doctor`. But not all
secrets are equal:

| Class | Examples | Effect of rotating |
|---|---|---|
| Safe to rotate | SMTP password, LiteLLM/API keys, BTCPay API token | none beyond a restart |
| Rotate with care | Authentik secret key, session/cookie secrets | everyone is signed out; they just sign in again |
| Rotate in two places | database passwords | change in the secrets file **and** in the database itself, then restart both sides |
| Never rotate casually | Synapse signing key, WireGuard keys | Synapse's key is its cryptographic identity — rotating it breaks message verification. Leave it alone unless you know exactly why. |

If you suspect a secret leaked, rotate everything in the first two rows
immediately — it costs one mass re-login and nothing else.

## Gotcha 1: the Caddy reload that silently does nothing

**Symptom:** you added or changed a vhost, `caddy reload` exited without
error, but the site still 404s or serves the old behavior. The config file
on disk is right; the running Caddy just is not using it.

**Fix and standing policy:** do not troubleshoot the reload — restart:

```bash
docker compose restart caddy
```

The restart takes a few seconds, always loads the on-disk config, and either
works or fails loudly in the logs. Every runbook in these docs says
"restart caddy" instead of "reload caddy" for exactly this reason.

## Gotcha 2: the SNI map (works on the node, dead from the internet)

**Symptom:** a new subdomain resolves in DNS, Caddy on the node is
configured and has a certificate, `curl` against the loopback port works —
but from the internet, browsers get a connection reset or a certificate for
the wrong hostname.

**Cause:** the relay's nginx routes by an *explicit* SNI map. A hostname the
map has never heard of is not forwarded to your node, no matter how correct
the node is. This split is by design (the relay only touches hostnames it is
told about) — but it means every new web hostname is a **two-machine change**.

**Fix:**

```bash
ls-route push      # regenerate + install the SNI map on the VPS, reload nginx
ls doctor          # confirms map coverage for every hostname
```

**Diagnosis one-liner** — ask the relay directly what certificate comes back
for the hostname:

```bash
openssl s_client -connect <VPS_IP>:443 -servername new.example.org </dev/null \
  | openssl x509 -noout -subject
```

Wrong or no certificate → the map is stale → `ls-route push`.

## Housekeeping

- Disk: `df -h` monthly; Synapse media and BTCPay grow the fastest under
  `${LS_DATA_DIR}`.
- Reclaim space with `docker image prune` after updates. Never use
  `docker system prune --volumes` — parts of the stack use named volumes.
- A weekly cron running `ls doctor` and mailing you on failure is cheap
  insurance; you find out about a broken cert renewal before the community
  does.
