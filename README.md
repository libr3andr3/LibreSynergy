# LibreSynergy

Federated learning community suite. One command to deploy your own online school with SSO, courses, chat, live video, and crypto+fiat payments.

Zero modifications to any FOSS project — all integration via generated config files and public REST APIs.

---

## Quick Start

Everything you need to go from zero to a running community in under 10 minutes.

### Prerequisites

```bash
# You need Docker, Python 3.11+, and git
docker --version      # >= 24.0
python3 --version     # >= 3.11
git --version
```

### 1. Clone and install

```bash
git clone git@github.com:libr3andr3/LibreSynergy.git
cd LibreSynergy

# Create virtual env and install
python3 -m venv .venv
.venv/bin/pip install click jinja2 pyyaml

# Verify CLI works
PYTHONPATH=. .venv/bin/python3 -m cli.main --help
```

### 2. Bootstrap your community

Generates docker-compose.yml, nginx.conf, and all service configs. You'll be prompted for your domain, admin email, community name, and optionally payment keys.

```bash
PYTHONPATH=. .venv/bin/python3 -m cli.main bootstrap
```

Or non-interactive for testing:

```bash
PYTHONPATH=. .venv/bin/python3 -m cli.main bootstrap \
  --domain learn.mycommunity.com \
  --output ./deploy \
  --non-interactive
```

What `bootstrap` generates (14 files in `./deploy/`):

```
deploy/
├── docker-compose.yml          # 13 services, ready to run
├── nginx.conf                  # Reverse proxy for all subdomains
├── homeserver.yaml             # Matrix Synapse with OIDC
├── prosody.cfg.lua             # Jitsi JWT auth
├── frappe-common-site-config.json  # Frappe LMS OIDC + roles
├── element-config.json         # Matrix web client
├── jitsi-config.js             # Jitsi Meet web config
├── jitsi-interface-config.js   # Jitsi branding
├── branding.yaml               # Your community colors/logo
├── setup-frappe.sh             # Post-deploy Frappe setup
├── setup-matrix.sh             # Post-deploy Matrix room creation
├── setup-jitsi.sh              # Post-deploy Jitsi verification
└── well-known/matrix/
    ├── server                  # Federation discovery
    └── client                  # Client discovery
```

### 3. Start the stack

```bash
cd deploy
docker compose up -d
```

Wait for services to be healthy (~60-90 seconds on first boot):

```bash
docker compose ps
# All services should show "healthy" or "running"
```

### 4. Configure Authentik (SSO)

After Authentik is running, auto-configure it via API. You'll need the admin password set during first Authentik boot (check Authentik logs if unsure: `docker compose logs authentik-server | grep "admin password"`).

```bash
PYTHONPATH=.. ../.venv/bin/python3 -m cli.main authentik-setup \
  --domain learn.mycommunity.com \
  --admin-password "your-authentik-admin-password"
```

This creates automatically:
- OIDC providers for Frappe LMS, Matrix, and Jitsi Meet
- Applications for each service
- Tier groups: `free`, `premium`, `max`
- JWT property mappings (tier, subscriptions, federation grants)

Copy the output client IDs/secrets and update your `docker-compose.yml` OIDC placeholders, then restart:

```bash
docker compose up -d --force-recreate frappe matrix jitsi-web prosody
```

### 5. Set up payments (optional)

```bash
# BTC PayServer (Bitcoin + Monero)
PYTHONPATH=.. ../.venv/bin/python3 -m cli.main payment-setup \
  --domain learn.mycommunity.com \
  --btcpay-url https://btcpay.yourserver.com \
  --btcpay-key "your-btcpay-api-key" \
  --monero-wallet "your-monero-address"

# Stripe (credit cards)
PYTHONPATH=.. ../.venv/bin/python3 -m cli.main payment-setup \
  --domain learn.mycommunity.com \
  --stripe-key "sk_live_..."
```

### 6. Apply branding

```bash
# Edit deploy/branding.yaml with your colors and logo, then:
PYTHONPATH=.. ../.venv/bin/python3 -m cli.main branding \
  --config deploy/branding.yaml \
  --domain learn.mycommunity.com
```

### 7. Access your community

| Service | URL | What |
|---------|-----|------|
| SSO Login | `https://auth.learn.mycommunity.com` | Authentik — users sign in here |
| Courses | `https://learn.learn.mycommunity.com` | Frappe LMS — courses and certificates |
| Chat | `https://chat.learn.mycommunity.com` | Element + Matrix — federated rooms |
| Meetings | `https://meet.learn.mycommunity.com` | Jitsi Meet — live video sessions |
| API | `https://api.learn.mycommunity.com/docs` | LibreSynergy API — federation + payments |

### 8. Run post-deploy scripts

```bash
chmod +x setup-*.sh
./setup-frappe.sh    # Creates OIDC social login in Frappe
./setup-matrix.sh    # Creates default tier rooms in Matrix
./setup-jitsi.sh     # Verifies Jitsi is healthy
```

### 9. Verify everything

```bash
# API health check
curl https://api.learn.mycommunity.com/health

# Matrix federation check
curl https://chat.learn.mycommunity.com/_matrix/federation/v1/version

# Run test suite
cd ..
PYTHONPATH=. .venv/bin/python3 -m pytest tests/ -v
```

---

## Federation

Once two communities are running, they can federate — sharing rooms, course catalogs, and live sessions.

**Creator A invites Creator B:**

```bash
curl -X POST https://api.community-a.com/federation/invite \
  -H "Authorization: Bearer <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "target_instance_uuid": "<instance-b-uuid>",
    "target_domain": "community-b.com",
    "shared_rooms": ["#expert-qa", "#firmware-re"],
    "shared_courses": true,
    "shared_jitsi": false
  }'
```

**Creator B accepts:**

```bash
curl -X POST https://api.community-b.com/federation/accept \
  -H "Authorization: Bearer <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"invitation_id": "<invitation-id-from-a>"}'
```

Federation is mutual, opt-in, and instantly revocable. See the API docs at `/docs` for all endpoints.

---

## Tiers & Payments

| Tier | Price | Includes |
|------|-------|----------|
| **Free** | $0 | #general chat, free courses (no certificate) |
| **Premium** | $29.99/mo | All creator courses + certificates, premium rooms, live sessions |
| **Max** | $99.99/mo | Everything above + cross-creator bundles, expert Q&A, partner rooms |

When a user pays, the webhook updates their Authentik group. All services read tier from JWT claims — no service ever talks to the payment provider directly.

---

## Architecture

```
Community Instance
├── Authentik ─── SSO, OIDC, JWT issuer
├── Frappe LMS ── Courses + certificates (OIDC client)
├── Matrix ───── Federated chat (OIDC + built-in federation)
├── Element ──── Matrix web client
├── Jitsi Meet ── Live video (JWT auth)
├── BTC PayServer ─ Crypto payments (Bitcoin + Monero)
├── Stripe ────── Fiat payments
├── LibreSynergy API ─ Federation protocol, tier sync, webhooks
├── PostgreSQL ── Shared database
├── Redis ─────── Cache + sessions
└── Nginx ─────── Reverse proxy + TLS
```

No forks. No source patches. All integration is config files + APIs.

---

## Development

```bash
# Run tests
PYTHONPATH=. .venv/bin/python3 -m pytest tests/ -v

# Bootstrap for testing
PYTHONPATH=. .venv/bin/python3 -m cli.main bootstrap \
  --domain test.local --output /tmp/ls-test --non-interactive

# Validate compose
docker compose -f /tmp/ls-test/docker-compose.yml config --services
```

CI runs on every push: pytest matrix (3.11-3.13), compose validation, syntax check.

---

## License

MIT
