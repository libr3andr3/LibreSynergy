"""Payment webhook handlers — BTC PayServer and Stripe."""

import os
import json
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import PaymentEvent, Subscription
from api.tiers import set_user_tier

router = APIRouter()


# --- Helpers ---

async def get_or_create_subscription(db: AsyncSession, user_sub: str) -> Subscription:
    """Find active subscription or create a free-tier one."""
    from sqlalchemy import select

    result = await db.execute(
        select(Subscription).where(
            Subscription.user_sub == user_sub,
            Subscription.active == True,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        sub = Subscription(user_sub=user_sub, tier="free")
        db.add(sub)
        await db.flush()
    return sub


# --- BTC PayServer ---

@router.post("/btcpay")
async def btcpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle BTC PayServer webhook notifications."""
    raw_body = await request.body()
    payload = json.loads(raw_body)

    # Validate HMAC signature
    btcpay_key = os.getenv("BTCPAY_API_KEY", "")
    if btcpay_key:
        sig = request.headers.get("BTCPay-Sig", "")
        expected = hmac.new(
            btcpay_key.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if sig and not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=403, detail="Invalid signature")

    # Log event
    event = PaymentEvent(
        provider="btcpay",
        event_type=payload.get("type", "unknown"),
        raw_payload=payload,
    )
    db.add(event)

    # Process invoice settlement
    if payload.get("type") == "InvoiceSettled":
        invoice = payload.get("data", {})
        metadata = invoice.get("metadata", {})
        user_sub = metadata.get("user_sub")
        tier = metadata.get("tier", "premium")

        if user_sub:
            sub = await get_or_create_subscription(db, user_sub)
            sub.tier = tier
            sub.payment_provider = "btcpay"
            sub.payment_invoice_id = invoice.get("id", "")
            event.processed = True
            event.user_sub = user_sub

            # Update Authentik group
            try:
                await set_user_tier(user_sub, tier)
            except Exception:
                pass  # Logged but non-fatal; tier stored in DB

    await db.commit()
    return {"status": "ok"}


# --- Stripe ---

@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook notifications."""
    raw_body = await request.body()
    payload = json.loads(raw_body)

    # Validate Stripe signature
    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_sig = request.headers.get("Stripe-Signature", "")
    if stripe_key and stripe_sig:
        try:
            import stripe
            stripe.Webhook.construct_event(
                raw_body, stripe_sig, os.getenv("STRIPE_WEBHOOK_SECRET", "")
            )
        except Exception:
            raise HTTPException(status_code=403, detail="Invalid Stripe signature")

    event_type = payload.get("type", "unknown")
    event = PaymentEvent(
        provider="stripe",
        event_type=event_type,
        raw_payload=payload,
    )
    db.add(event)

    if event_type == "checkout.session.completed":
        session = payload.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        user_sub = metadata.get("user_sub")
        tier = metadata.get("tier", "premium")

        if user_sub:
            sub = await get_or_create_subscription(db, user_sub)
            sub.tier = tier
            sub.payment_provider = "stripe"
            sub.payment_invoice_id = session.get("id", "")
            event.processed = True
            event.user_sub = user_sub

            try:
                await set_user_tier(user_sub, tier)
            except Exception:
                pass

    elif event_type == "customer.subscription.deleted":
        subscription = payload.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        user_sub = metadata.get("user_sub")
        if user_sub:
            sub = await get_or_create_subscription(db, user_sub)
            sub.tier = "free"
            sub.active = True
            event.processed = True
            event.user_sub = user_sub

            try:
                await set_user_tier(user_sub, "free")
            except Exception:
                pass

    await db.commit()
    return {"status": "ok"}


# --- Bundle (cross-instance) ---

@router.post("/bundle/notify")
async def bundle_notification(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive cross-instance bundle purchase notification."""
    body = await request.json()
    auth = request.headers.get("Authorization", "")
    federation_secret = os.getenv("FEDERATION_SECRET", "")

    if auth != f"Bearer {federation_secret}":
        raise HTTPException(status_code=403, detail="Invalid federation secret")

    user_sub = body.get("user_sub")
    tier = body.get("tier", "max")
    from_instance = body.get("from_instance", "unknown")

    if user_sub:
        sub = await get_or_create_subscription(db, user_sub)
        sub.tier = tier
        sub.payment_provider = f"bundle:{from_instance}"

        try:
            await set_user_tier(user_sub, tier)
        except Exception:
            pass

    event = PaymentEvent(
        provider="bundle",
        event_type="cross_instance",
        user_sub=user_sub,
        raw_payload=body,
        processed=True,
    )
    db.add(event)
    await db.commit()

    return {"status": "ok"}
