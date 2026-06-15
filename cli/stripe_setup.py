"""Stripe auto-setup via Stripe API.

No Stripe source is modified. This module creates Products, Prices, and
webhooks so creators just paste their Stripe secret key and everything
is configured automatically.

Usage:
  python -m cli.stripe_setup --api-key sk_xxx --domain learn.example.com
"""

import sys
import argparse

import httpx


class StripeClient:
    """Minimal Stripe API client (no stripe-python dependency needed)."""

    BASE = "https://api.stripe.com/v1"

    def __init__(self, api_key: str):
        self.auth = (api_key, "")  # Basic auth with empty password

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        url = f"{self.BASE}{path}"
        resp = httpx.request(method, url, auth=self.auth, data=data)
        resp.raise_for_status()
        return resp.json()

    # --- Products ---

    def create_product(self, name: str, metadata: dict = None) -> dict:
        """Create a product."""
        data = {"name": name}
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = v
        return self._request("POST", "/products", data)

    # --- Prices ---

    def create_price(
        self,
        product_id: str,
        unit_amount: int,  # cents
        currency: str = "usd",
        recurring: dict = None,
        metadata: dict = None,
    ) -> dict:
        """Create a price for a product."""
        data = {
            "product": product_id,
            "unit_amount": str(unit_amount),
            "currency": currency,
        }
        if recurring:
            data["recurring[interval]"] = recurring.get("interval", "month")
            data["recurring[interval_count]"] = str(recurring.get("interval_count", 1))
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = v
        return self._request("POST", "/prices", data)

    # --- Webhooks ---

    def create_webhook(self, url: str, events: list = None) -> dict:
        """Create a webhook endpoint."""
        if events is None:
            events = [
                "checkout.session.completed",
                "customer.subscription.deleted",
                "customer.subscription.updated",
                "invoice.payment_succeeded",
                "invoice.payment_failed",
            ]
        data = {
            "url": url,
            "enabled_events[]": events,
        }
        return self._request("POST", "/webhook_endpoints", data)

    # --- Checkout ---

    def create_checkout_session(
        self,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict = None,
        mode: str = "subscription",
    ) -> dict:
        """Create a Stripe Checkout session."""
        data = {
            "mode": mode,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = v
        return self._request("POST", "/checkout/sessions", data)


# --- Tier pricing ---

TIER_PRICES_CENTS = {
    "free": 0,
    "premium": 2999,
    "max": 9999,
}


def setup_stripe(api_key: str, domain: str) -> dict:
    """Full Stripe bootstrap for a libresynergy community.

    Returns dict with product IDs, price IDs, and webhook signing secret.
    """
    client = StripeClient(api_key)
    result = {"products": {}, "prices": {}, "webhook_id": None}

    # 1. Create products + prices for each tier
    for tier, cents in TIER_PRICES_CENTS.items():
        if cents == 0:
            continue

        print(f"  Creating {tier} tier...")

        # Create product
        product = client.create_product(
            f"{tier.capitalize()} Plan — libresynergy",
            metadata={"tier": tier, "type": "libresynergy_subscription"},
        )
        product_id = product["id"]
        result["products"][tier] = product_id
        print(f"    Product: {product_id}")

        # Create recurring price
        price = client.create_price(
            product_id=product_id,
            unit_amount=cents,
            recurring={"interval": "month"},
            metadata={"tier": tier},
        )
        result["prices"][tier] = price["id"]
        print(f"    Price: {price['id']} (${cents / 100:.2f}/mo)")

    # 2. Create webhook
    webhook_url = f"https://api.{domain}/payments/stripe"
    print(f"  Creating webhook → {webhook_url}")
    webhook = client.create_webhook(webhook_url)
    result["webhook_id"] = webhook["id"]
    result["webhook_secret"] = webhook.get("secret", "")
    print(f"  ✓ Webhook created")

    return result


def generate_checkout_snippet(
    api_key: str,
    price_id: str,
    tier: str,
    domain: str,
    user_sub: str = "USER_SUB_PLACEHOLDER",
) -> str:
    """Generate a Stripe Checkout HTML snippet for embedding."""
    client = StripeClient(api_key)

    session = client.create_checkout_session(
        price_id=price_id,
        success_url=f"https://learn.{domain}/payment/success?session={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"https://learn.{domain}/payment/cancel",
        metadata={"tier": tier, "user_sub": user_sub},
    )

    return session.get("url", "")


def main():
    parser = argparse.ArgumentParser(description="Stripe auto-setup for libresynergy")
    parser.add_argument("--api-key", required=True, help="Stripe secret key (sk_xxx)")
    parser.add_argument("--domain", required=True, help="Community domain")
    args = parser.parse_args()

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║    libresynergy — Stripe Setup        ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    try:
        result = setup_stripe(api_key=args.api_key, domain=args.domain)
        print()
        print("  ✅ Stripe configured!")
        print()
        print("  Add to your .env:")
        print(f"    STRIPE_WEBHOOK_SECRET={result['webhook_secret']}")
        print()
        print("  Price IDs:")
        for tier, price_id in result["prices"].items():
            print(f"    STRIPE_PRICE_{tier.upper()}={price_id}")
        print()
        return 0
    except Exception as e:
        print(f"\n  ❌ Setup failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
