"""BTC PayServer auto-setup via Greenfield API.

No BTC PayServer source is modified. This module calls the Greenfield REST API
to create stores, products, webhooks, and enable plugins — everything a
non-technical creator needs after pasting their BTC PayServer URL + API key.

Usage:
  python -m cli.btcpay_setup --url https://btcpay.example.com --api-key <key> \\
      --domain learn.example.com --monero-wallet <addr>
"""

import sys
import argparse

import httpx


class BTCPayClient:
    """Minimal BTC PayServer Greenfield API client."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"token {api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json=None):
        url = f"{self.base_url}/api/v1{path}"
        resp = httpx.request(method, url, headers=self.headers, json=json)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # --- Stores ---

    def create_store(self, name: str) -> dict:
        """Create a new store."""
        return self._request("POST", "/stores", {"name": name})

    def get_stores(self) -> list:
        """List all stores."""
        return self._request("GET", "/stores")

    # --- Webhooks ---

    def create_webhook(self, store_id: str, url: str, events: list = None) -> dict:
        """Create a webhook for a store."""
        if events is None:
            events = ["InvoiceSettled", "InvoiceProcessing", "InvoiceExpired"]
        payload = {
            "url": url,
            "enabled": True,
            "automaticRedelivery": True,
            "authorizedEvents": {"everything": False, "specificEvents": events},
        }
        return self._request("POST", f"/stores/{store_id}/webhooks", payload)

    # --- Products (items) ---

    def create_product(
        self,
        store_id: str,
        name: str,
        price: float,
        currency: str = "USD",
    ) -> dict:
        """Create a product (invoice template) in the store."""
        payload = {
            "name": name,
            "price": price,
            "currency": currency,
            "description": f"{name} — libresynergy learning community",
            "requiresRefundEmail": False,
            "checkout": {
                "speedPolicy": "MediumSpeed",
                "expirationMinutes": 1440,  # 24 hours
                "monitoringMinutes": 1440,
                "paymentTolerance": 0.0,
            },
        }
        return self._request("POST", f"/stores/{store_id}/products", payload)

    def get_products(self, store_id: str) -> list:
        """List products in a store."""
        return self._request("GET", f"/stores/{store_id}/products")

    # --- Plugins ---

    def enable_monero(self, store_id: str, wallet_address: str) -> dict:
        """Enable the Monero payment method for a store."""
        payload = {
            "enabled": True,
            "walletAddress": wallet_address,
        }
        return self._request(
            "PUT",
            f"/stores/{store_id}/payment-methods/MoneroLike-Monero",
            payload,
        )

    # --- Invoices ---

    def create_invoice(
        self,
        store_id: str,
        product_id: str,
        user_metadata: dict = None,
    ) -> dict:
        """Create an invoice for a product purchase."""
        payload = {
            "productId": product_id,
        }
        if user_metadata:
            payload["metadata"] = user_metadata
        return self._request("POST", f"/stores/{store_id}/invoices", payload)


# --- Tier pricing ---

TIER_PRICES = {
    "free": 0,
    "premium": 29.99,
    "max": 99.99,
}


def setup_btcpay(
    btcpay_url: str,
    api_key: str,
    domain: str,
    monero_wallet: str = None,
) -> dict:
    """Full BTC PayServer bootstrap for a libresynergy community.

    Returns dict with store_id and product IDs for each tier.
    """
    client = BTCPayClient(btcpay_url, api_key)
    result = {"store_id": None, "products": {}, "webhook_id": None}

    # 1. Create store
    print(f"  Creating store...")
    store = client.create_store("libresynergy Community")
    store_id = store["id"]
    result["store_id"] = store_id
    print(f"  ✓ Store created: {store_id}")

    # 2. Create products for each tier
    for tier, price in TIER_PRICES.items():
        if price == 0:
            continue  # Free tier doesn't need a payment product
        print(f"  Creating {tier} tier product (${price:.2f})...")
        product = client.create_product(store_id, f"{tier.capitalize()} Plan", price)
        result["products"][tier] = product["id"]
        print(f"  ✓ {tier}: {product['id']}")

    # 3. Create webhook
    webhook_url = f"https://api.{domain}/payments/btcpay"
    print(f"  Creating webhook → {webhook_url}")
    webhook = client.create_webhook(store_id, webhook_url)
    result["webhook_id"] = webhook["id"]
    print(f"  ✓ Webhook created")

    # 4. Enable Monero if wallet provided
    if monero_wallet:
        print(f"  Enabling Monero payments...")
        try:
            client.enable_monero(store_id, monero_wallet)
            print(f"  ✓ Monero enabled")
            result["monero_enabled"] = True
        except Exception as e:
            print(f"  ⚠ Monero setup failed (non-fatal): {e}")
            result["monero_enabled"] = False

    return result


def main():
    parser = argparse.ArgumentParser(description="BTC PayServer auto-setup for libresynergy")
    parser.add_argument("--url", required=True, help="BTC PayServer base URL")
    parser.add_argument("--api-key", required=True, help="BTC PayServer API key")
    parser.add_argument("--domain", required=True, help="Community domain")
    parser.add_argument("--monero-wallet", help="Monero wallet address (optional)")
    args = parser.parse_args()

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║  libresynergy — BTC PayServer Setup  ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    try:
        result = setup_btcpay(
            btcpay_url=args.url,
            api_key=args.api_key,
            domain=args.domain,
            monero_wallet=args.monero_wallet,
        )
        print()
        print("  ✅ BTC PayServer configured!")
        print()
        print("  Payment links:")
        for tier, product_id in result["products"].items():
            print(f"    {tier}: {args.url}/apps/{result['store_id']}/pos")
        print()
        return 0
    except Exception as e:
        print(f"\n  ❌ Setup failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
