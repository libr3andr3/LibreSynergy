"""Federation protocol endpoints — invite, accept, revoke, discover."""

import os
import httpx
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import FederationRelationship
from api.auth import require_admin

router = APIRouter()

FEDERATION_SECRET = os.getenv("FEDERATION_SECRET", "")
INSTANCE_UUID = os.getenv("INSTANCE_UUID", "")


# --- Schemas ---

class FederationInviteRequest(BaseModel):
    target_instance_uuid: str
    target_domain: str
    shared_rooms: list[str] = []
    shared_courses: bool = False
    shared_jitsi: bool = False
    message: str = ""


class FederationInviteResponse(BaseModel):
    invitation_id: str
    status: str


class FederationAcceptRequest(BaseModel):
    invitation_id: str


# --- Internal helpers ---

async def notify_partner(partner_domain: str, endpoint: str, payload: dict):
    """Send an HTTP request to a partner instance's federation API."""
    url = f"https://api.{partner_domain}{endpoint}"
    headers = {
        "Authorization": f"Bearer {FEDERATION_SECRET}",
        "Content-Type": "application/json",
        "X-Instance-UUID": INSTANCE_UUID,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# --- Endpoints ---

@router.post("/invite")
async def send_federation_invite(
    body: FederationInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Send a federation invitation to another instance."""
    # Create local record
    rel = FederationRelationship(
        partner_instance_uuid=body.target_instance_uuid,
        partner_domain=body.target_domain,
        status="pending",
        direction="outbound",
        shared_rooms=body.shared_rooms,
        shared_courses=body.shared_courses,
        shared_jitsi=body.shared_jitsi,
    )
    db.add(rel)

    # Notify partner instance
    try:
        await notify_partner(body.target_domain, "/federation/invite-received", {
            "invitation_id": rel.id,
            "from_instance_uuid": INSTANCE_UUID,
            "from_domain": request.headers.get("host", ""),
            "shared_rooms": body.shared_rooms,
            "shared_courses": body.shared_courses,
            "shared_jitsi": body.shared_jitsi,
            "message": body.message,
        })
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=502, detail="Partner instance unreachable")

    await db.commit()
    return FederationInviteResponse(invitation_id=rel.id, status="pending")


@router.post("/invite-received")
async def receive_federation_invite(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Called by a partner instance to deliver an invitation."""
    body = await request.json()

    # Verify federation secret
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {FEDERATION_SECRET}":
        raise HTTPException(status_code=403, detail="Invalid federation secret")

    rel = FederationRelationship(
        id=body["invitation_id"],
        partner_instance_uuid=body["from_instance_uuid"],
        partner_domain=body.get("from_domain", ""),
        partner_name=body.get("from_name", ""),
        status="accepted",
        direction="inbound",
        shared_rooms=body.get("shared_rooms", []),
        shared_courses=body.get("shared_courses", False),
        shared_jitsi=body.get("shared_jitsi", False),
    )
    db.add(rel)
    await db.commit()
    return {"status": "accepted", "invitation_id": rel.id}


@router.get("/pending")
async def list_pending_invitations(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """List pending inbound federation invitations."""
    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.status == "pending",
            FederationRelationship.direction == "inbound",
        )
    )
    relationships = result.scalars().all()
    return [
        {
            "id": r.id,
            "from": r.partner_instance_uuid,
            "domain": r.partner_domain,
            "shared_rooms": r.shared_rooms,
            "shared_courses": r.shared_courses,
            "shared_jitsi": r.shared_jitsi,
            "created_at": r.created_at.isoformat(),
        }
        for r in relationships
    ]


@router.post("/accept")
async def accept_federation(
    body: FederationAcceptRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Accept a pending federation invitation."""
    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.id == body.invitation_id,
            FederationRelationship.status == "pending",
        )
    )
    rel = result.scalar_one_or_none()
    if not rel:
        raise HTTPException(status_code=404, detail="Invitation not found")

    rel.status = "accepted"
    rel.updated_at = datetime.now(timezone.utc)

    # Notify the partner that we accepted
    try:
        await notify_partner(rel.partner_domain, "/federation/confirm", {
            "invitation_id": rel.id,
            "accepted_by": INSTANCE_UUID,
        })
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=502, detail="Failed to notify partner")

    await db.commit()
    return {"status": "accepted", "invitation_id": rel.id}


@router.post("/confirm")
async def confirm_federation(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Called by partner to confirm federation acceptance."""
    body = await request.json()
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {FEDERATION_SECRET}":
        raise HTTPException(status_code=403, detail="Invalid federation secret")

    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.id == body["invitation_id"],
        )
    )
    rel = result.scalar_one_or_none()
    if rel:
        rel.status = "active"
        rel.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {"status": "active"}


@router.post("/revoke/{partner_uuid}")
async def revoke_federation(
    partner_uuid: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Revoke federation with a partner."""
    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.partner_instance_uuid == partner_uuid,
            FederationRelationship.status.in_(["accepted", "active"]),
        )
    )
    rel = result.scalar_one_or_none()
    if not rel:
        raise HTTPException(status_code=404, detail="Active federation not found")

    rel.status = "revoked"
    rel.updated_at = datetime.now(timezone.utc)

    # Notify partner
    try:
        await notify_partner(rel.partner_domain, "/federation/revoked", {
            "revoked_by": INSTANCE_UUID,
        })
    except Exception:
        pass  # Best effort — revocation is local-first

    await db.commit()
    return {"status": "revoked", "partner": partner_uuid}


@router.post("/revoked")
async def partner_revoked(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Called by partner when they revoke federation."""
    body = await request.json()
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {FEDERATION_SECRET}":
        raise HTTPException(status_code=403, detail="Invalid federation secret")

    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.partner_instance_uuid == body["revoked_by"],
            FederationRelationship.status.in_(["accepted", "active"]),
        )
    )
    rel = result.scalar_one_or_none()
    if rel:
        rel.status = "revoked"
        rel.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {"status": "acknowledged"}


@router.get("/partners")
async def list_partners(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """List all active federation partners."""
    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.status == "active",
        )
    )
    relationships = result.scalars().all()
    return [
        {
            "id": r.id,
            "partner_uuid": r.partner_instance_uuid,
            "domain": r.partner_domain,
            "name": r.partner_name,
            "shared_rooms": r.shared_rooms,
            "shared_courses": r.shared_courses,
            "shared_jitsi": r.shared_jitsi,
        }
        for r in relationships
    ]


@router.get("/discover/{partner_uuid}/courses")
async def discover_partner_courses(
    partner_uuid: str,
    db: AsyncSession = Depends(get_db),
):
    """Proxy to pull course catalog from a federated partner."""
    result = await db.execute(
        select(FederationRelationship).where(
            FederationRelationship.partner_instance_uuid == partner_uuid,
            FederationRelationship.status == "active",
            FederationRelationship.shared_courses == True,
        )
    )
    rel = result.scalar_one_or_none()
    if not rel:
        raise HTTPException(status_code=404, detail="No course-sharing federation found")

    try:
        url = f"https://api.{rel.partner_domain}/courses/public"
        headers = {
            "Authorization": f"Bearer {FEDERATION_SECRET}",
            "X-Instance-UUID": INSTANCE_UUID,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch courses: {e}")
