"""SQLAlchemy models for libresynergy API."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Boolean, JSON, Integer, ForeignKey
from sqlalchemy.orm import relationship

from api.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class Subscription(Base):
    """Tracks a user's subscription tier and expiry."""

    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=new_uuid)
    user_sub = Column(String, nullable=False, index=True)  # Authentik user UUID
    tier = Column(String, nullable=False, default="free")   # free | premium | max
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    payment_provider = Column(String, nullable=True)  # btcpay | stripe
    payment_invoice_id = Column(String, nullable=True)


class FederationRelationship(Base):
    """Tracks federation between this instance and a partner."""

    __tablename__ = "federation_relationships"

    id = Column(String, primary_key=True, default=new_uuid)
    partner_instance_uuid = Column(String, nullable=False, index=True)
    partner_domain = Column(String, nullable=False)
    partner_name = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending | accepted | active | revoked
    direction = Column(String, default="outbound")  # outbound | inbound
    shared_rooms = Column(JSON, default=list)        # ["#expert", "#firmware-re"]
    shared_courses = Column(Boolean, default=False)
    shared_jitsi = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Bundle(Base):
    """Cross-creator subscription bundle spanning multiple communities."""

    __tablename__ = "bundles"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    price_monthly_cents = Column(Integer, default=0)  # in cents
    creator_instances = Column(JSON, default=list)     # [uuid-a, uuid-b, uuid-c]
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class PaymentEvent(Base):
    """Audit log of all payment events."""

    __tablename__ = "payment_events"

    id = Column(String, primary_key=True, default=new_uuid)
    provider = Column(String, nullable=False)     # btcpay | stripe
    event_type = Column(String, nullable=False)   # invoice.settled | checkout.session.completed
    user_sub = Column(String, nullable=True, index=True)
    raw_payload = Column(JSON, default=dict)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
