"""Authentik bootstrap automation.

After docker-compose up, this script configures Authentik entirely via its API:
  - Creates admin API token
  - Creates OIDC providers for Frappe LMS, Matrix, Jitsi
  - Creates Applications, groups (free/premium/max)
  - Creates JWT property mappings (tier, subscriptions, federation_grants)
  - Outputs client IDs and secrets for all services

Usage:
  python -m cli.authentik_setup --auth-url https://auth.example.com --admin-password <pw>
"""

import os
import sys
import time
import json
import argparse
from urllib.parse import urljoin

import httpx


# ============================================================
# Authentik API client
# ============================================================

class AuthentikAdmin:
    """Low-level Authentik admin API client."""

    def __init__(self, base_url: str, token: str = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(timeout=30)

    def _headers(self):
        hdrs = {"Content-Type": "application/json"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        return hdrs

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", f"api/v3{path}")

    def get(self, path: str, **params):
        r = self._client.get(self._url(path), headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, data: dict):
        r = self._client.post(self._url(path), headers=self._headers(), json=data)
        r.raise_for_status()
        return r.json()

    def patch(self, path: str, data: dict):
        r = self._client.patch(self._url(path), headers=self._headers(), json=data)
        r.raise_for_status()
        return r.json()

    def delete(self, path: str):
        r = self._client.delete(self._url(path), headers=self._headers())
        r.raise_for_status()
        return


# ============================================================
# Health check — wait until Authentik is ready
# ============================================================

def wait_for_authentik(base_url: str, timeout: int = 120):
    """Poll Authentik health endpoint until ready."""
    start = time.time()
    url = urljoin(base_url + "/", "api/v3/root/config/")

    print(f"  Waiting for Authentik at {base_url} ...", end="", flush=True)
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code in (200, 401, 403):
                # 401/403 means Authentik is up but needs auth — that's fine
                print(" ready!")
                return True
        except Exception:
            pass
        time.sleep(2)
        print(".", end="", flush=True)

    print(" TIMEOUT")
    return False


# ============================================================
# Step 1: Create admin API token
# ============================================================

def create_admin_token(base_url: str, admin_password: str) -> str:
    """Get an admin API token for Authentik operations.

    Checks AUTHENTIK_BOOTSTRAP_TOKEN env var first (set at container start).
    Falls back to creating a token via API using the admin password.
    """
    import os
    # If bootstrap token was set at container start, use it directly
    bootstrap_token = os.getenv("AUTHENTIK_BOOTSTRAP_TOKEN", "")
    if bootstrap_token:
        print(f"  ✓ Using bootstrap token: {bootstrap_token[:20]}...")
        return bootstrap_token

    print("  Creating admin service account and API token...")

    # First, get a session token using the bootstrap admin
    admin = AuthentikAdmin(base_url)
    # Authentik flow: POST to /api/v3/core/token/ with password
    # Actually, we need to use the admin user's credentials
    # The bootstrap user is "akadmin" with the configured password
    try:
        # Try token endpoint
        token_resp = admin._client.post(
            admin._url("/core/tokens/"),
            json={
                "identifier": "libresynergy-bootstrap",
                "intent": "api",
                "user": 1,  # akadmin is typically user ID 1
            },
            headers={"Content-Type": "application/json"},
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        api_key = token_data.get("key", "")
        if api_key:
            print(f"  ✓ API token created: {api_key[:20]}...")
            return api_key
    except Exception as e:
        print(f"  ⚠ Token creation via API failed: {e}")

    # Fallback: if we can't create via API, just use the bootstrap password
    # In a real deployment, the user would create a token via the UI
    print("  ⚠ Could not auto-create API token. Using bootstrap password.")
    return admin_password


# ============================================================
# Step 2: Create OIDC providers
# ============================================================

OIDC_PROVIDERS = [
    {
        "name": "libresynergy-frappe",
        "description": "Frappe LMS OIDC provider",
        "client_type": "confidential",
        "authorization_flow": None,  # use default
        "redirect_uris": "https://learn.{domain}/api/method/frappe.integrations.oauth2.callback\nhttps://learn.{domain}/api/method/frappe.integrations.oauth2.login",
        "signing_key": None,  # auto-generated
    },
    {
        "name": "libresynergy-matrix",
        "description": "Matrix Synapse OIDC provider",
        "client_type": "confidential",
        "redirect_uris": "https://chat.{domain}/_synapse/client/oidc/callback",
    },
    {
        "name": "libresynergy-jitsi",
        "description": "Jitsi Meet OIDC provider",
        "client_type": "confidential",
        "redirect_uris": "https://meet.{domain}/",
    },
]


def create_oidc_providers(admin: AuthentikAdmin, domain: str) -> dict:
    """Create OIDC providers for Frappe, Matrix, and Jitsi.

    Returns dict of {name: {client_id, client_secret}}.
    """
    print("  Creating OIDC providers...")
    results = {}

    # Get or create default authorization flow
    flows = admin.get("/flows/instances/", designation="authorization", slug="default-provider-authorization-implicit-consent")
    flow_results = flows.get("results", [])
    auth_flow_slug = flow_results[0]["slug"] if flow_results else "default-provider-authorization-implicit-consent"

    for provider_cfg in OIDC_PROVIDERS:
        name = provider_cfg["name"]
        redirect_uris = provider_cfg["redirect_uris"].replace("{domain}", domain)

        data = {
            "name": name,
            "client_type": provider_cfg["client_type"],
            "authorization_flow": auth_flow_slug,
            "redirect_uris": redirect_uris,
            "property_mappings": [],  # We'll add these later
            "signing_key": None,
            "access_code_validity": "minutes=10",
            "access_token_validity": "hours=1",
            "refresh_token_validity": "days=30",
        }

        try:
            resp = admin.post("/providers/oauth2/", data)
            client_id = resp.get("client_id", "")
            client_secret = resp.get("client_secret", "")
            results[name] = {
                "client_id": client_id,
                "client_secret": client_secret,
                "provider_pk": resp.get("pk"),
            }
            print(f"  ✓ Provider {name}: client_id={client_id[:20]}...")
        except Exception as e:
            print(f"  ✗ Failed to create provider {name}: {e}")
            results[name] = {"client_id": "ERROR", "client_secret": "ERROR"}

    return results


# ============================================================
# Step 3: Create Applications
# ============================================================

APPLICATIONS = [
    {
        "name": "Frappe LMS",
        "slug": "frappe-lms",
        "provider_name": "libresynergy-frappe",
        "launch_url": "https://learn.{domain}",
    },
    {
        "name": "Matrix Chat",
        "slug": "matrix-chat",
        "provider_name": "libresynergy-matrix",
        "launch_url": "https://chat.{domain}",
    },
    {
        "name": "Jitsi Meet",
        "slug": "jitsi-meet",
        "provider_name": "libresynergy-jitsi",
        "launch_url": "https://meet.{domain}",
    },
]


def create_applications(admin: AuthentikAdmin, domain: str, providers: dict) -> dict:
    """Create Authentik Applications and bind them to OIDC providers.

    Returns dict of {slug: {app_pk, launch_url}}.
    """
    print("  Creating Applications...")
    results = {}

    for app_cfg in APPLICATIONS:
        provider_info = providers.get(app_cfg["provider_name"], {})
        provider_pk = provider_info.get("provider_pk")

        if not provider_pk:
            print(f"  ✗ Skipping {app_cfg['slug']} — no provider PK")
            continue

        launch_url = app_cfg["launch_url"].replace("{domain}", domain)
        data = {
            "name": app_cfg["name"],
            "slug": app_cfg["slug"],
            "provider": provider_pk,
            "meta_launch_url": launch_url,
        }

        try:
            resp = admin.post("/core/applications/", data)
            results[app_cfg["slug"]] = {
                "app_pk": resp.get("pk"),
                "launch_url": launch_url,
            }
            print(f"  ✓ Application {app_cfg['slug']}")
        except Exception as e:
            print(f"  ✗ Failed to create application {app_cfg['slug']}: {e}")

    return results


# ============================================================
# Step 4: Create groups
# ============================================================

TIER_GROUPS = ["free", "premium", "max"]


def create_groups(admin: AuthentikAdmin) -> dict:
    """Create tier groups: free, premium, max.

    Returns dict of {group_name: group_pk}.
    """
    print("  Creating tier groups...")
    results = {}

    for group_name in TIER_GROUPS:
        data = {
            "name": group_name,
            "is_superuser": False,
        }
        try:
            resp = admin.post("/core/groups/", data)
            results[group_name] = resp.get("pk")
            print(f"  ✓ Group '{group_name}': pk={resp.get('pk')}")
        except Exception as e:
            print(f"  ✗ Failed to create group '{group_name}': {e}")

    return results


# ============================================================
# Step 5: Create property mappings for JWT claims
# ============================================================

JWT_SCOPE_MAPPING = """
# Add tier and subscription info to JWT claims
tier = "free"
subscriptions = []
federation_grants = {}

for group in request.user.ak_groups.all():
    if group.name in ("free", "premium", "max"):
        tier = group.name

return {
    "tier": tier,
    "subscriptions": subscriptions,
    "federation_grants": federation_grants,
}
"""


def create_property_mappings(admin: AuthentikAdmin, groups: dict) -> dict:
    """Create scope property mapping that embeds tier claims in JWTs.

    Returns dict with mapping PKs.
    """
    print("  Creating JWT scope property mapping...")
    results = {}

    # Create scope mapping
    data = {
        "name": "libresynergy-jwt-scope",
        "description": "Adds tier, subscriptions, and federation_grants to JWT claims",
        "expression": JWT_SCOPE_MAPPING.strip(),
        "scope_name": "libresynergy",
        "description_mode": "This scope adds libresynergy tier and federation claims",
    }
    try:
        resp = admin.post("/propertymappings/scope/", data)
        results["scope_pk"] = resp.get("pk")
        print(f"  ✓ Scope mapping: pk={resp.get('pk')}")
    except Exception as e:
        print(f"  ✗ Failed to create scope mapping: {e}")
        results["scope_pk"] = None

    return results


# ============================================================
# Step 6: Output configuration
# ============================================================

def output_config(domain: str, providers: dict, apps: dict, groups: dict, mappings: dict):
    """Print the configuration that should be injected into docker-compose env."""
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║  Authentik configuration complete!                  ║")
    print("  ║  Add these to your .env or docker-compose env:      ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()

    # OIDC client credentials
    for name, info in providers.items():
        slug = name.replace("libresynergy-", "").upper()
        print(f"  # {name}")
        print(f"  AUTHENTIK_{slug}_CLIENT_ID={info['client_id']}")
        print(f"  AUTHENTIK_{slug}_CLIENT_SECRET={info['client_secret']}")
        print()

    # Group UUIDs (needed by libresynergy-api tiers module)
    print("  # Tier group UUIDs")
    for group_name, pk in groups.items():
        print(f"  AUTHENTIK_GROUP_{group_name.upper()}_UUID={pk}")
    print()

    # Scope mapping
    if mappings.get("scope_pk"):
        print(f"  # JWT scope mapping")
        print(f"  AUTHENTIK_SCOPE_MAPPING_UUID={mappings['scope_pk']}")
        print()

    print(f"  OIDC Issuer URL: https://auth.{domain}/application/o/<slug>/")
    print(f"  JWKS URL:        https://auth.{domain}/application/o/<slug>/jwks/")
    print(f"  User Info:       https://auth.{domain}/application/o/userinfo/")
    print()


# ============================================================
# Main entry point
# ============================================================

def run_authentik_bootstrap(
    domain: str,
    auth_url: str = None,
    admin_password: str = None,
    bootstrap_token: str = None,
):
    """Run the full Authentik bootstrap sequence.

    Args:
        domain: Community domain (e.g., learn.example.com)
        auth_url: Authentik base URL (default: https://auth.{domain})
        admin_password: Bootstrap admin password
        bootstrap_token: Pre-created API token from AUTHENTIK_BOOTSTRAP_TOKEN
    """
    if auth_url is None:
        auth_url = f"https://auth.{domain}"
    if admin_password is None:
        admin_password = os.getenv("AUTHENTIK_BOOTSTRAP_PASSWORD", "changeme")
    if bootstrap_token is None:
        bootstrap_token = os.getenv("AUTHENTIK_BOOTSTRAP_TOKEN", "")

    from cli.authentik_setup import wait_for_authentik, create_admin_token, AuthentikAdmin
    from cli.authentik_setup import create_oidc_providers, create_applications, create_groups, create_property_mappings, output_config

    print()
    print("  ── Authentik Bootstrap ──")
    print()

    if not wait_for_authentik(auth_url):
        print("  ✗ Authentik did not become ready in time.")
        return {}

    if bootstrap_token:
        api_token = bootstrap_token
        print(f"  ✓ Using bootstrap token: {api_token[:20]}...")
    else:
        api_token = create_admin_token(auth_url, admin_password)

    admin = AuthentikAdmin(auth_url, api_token)

    # Create resources
    providers = create_oidc_providers(admin, domain)
    apps = create_applications(admin, domain, providers)
    groups = create_groups(admin)
    mappings = create_property_mappings(admin, groups)

    # Output config
    output_config(domain, providers, apps, groups, mappings)

    return {
        "providers": providers,
        "applications": apps,
        "groups": groups,
        "mappings": mappings,
        "api_token": api_token,
    }


# ============================================================
# CLI entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Bootstrap Authentik configuration")
    parser.add_argument("--domain", required=True, help="Community domain")
    parser.add_argument("--auth-url", help="Authentik base URL")
    parser.add_argument("--admin-password", help="Admin password")
    args = parser.parse_args()

    run_authentik_bootstrap(
        domain=args.domain,
        auth_url=args.auth_url,
        admin_password=args.admin_password,
    )


if __name__ == "__main__":
    main()
