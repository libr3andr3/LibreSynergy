"""libresynergy.org Discovery Registry API.

Separate deployment — runs on libresynergy.org. Communities opt-in to be listed.
Sponsorship model: visibility in exchange for funding development.

No FOSS project source is modified. This is a standalone FastAPI service.
"""

import os
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import Column, String, DateTime, Boolean, JSON, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


# --- Database ---

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///discovery.db")

_engine = None
_async_session = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False)
    return _engine


def _get_sessionmaker():
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _async_session


async def get_db():
    """Dependency that yields a database session."""
    async with _get_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.close()


class Base(DeclarativeBase):
    pass


class Community(Base):
    __tablename__ = "communities"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    instance_uuid = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    description = Column(Text, default="")
    categories = Column(JSON, default=list)   # ["cybersecurity", "programming"]
    contact_email = Column(String, nullable=False)
    logo_url = Column(String, default="")
    active = Column(Boolean, default=True)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="libresynergy Discovery Registry", version="0.1.0", lifespan=lifespan)


# --- Schemas ---

class RegisterRequest(BaseModel):
    instance_uuid: str
    name: str
    domain: str
    description: str = ""
    categories: list[str] = []
    contact_email: str
    logo_url: str = ""


class CommunityResponse(BaseModel):
    id: str
    name: str
    domain: str
    description: str
    categories: list[str]
    logo_url: str
    verified: bool
    created_at: str


# --- Endpoints ---

@app.post("/api/register")
async def register_community(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a community for discovery. Opt-in from creators."""
    existing = await db.execute(
        select(Community).where(Community.instance_uuid == body.instance_uuid)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Instance already registered")

    community = Community(
        instance_uuid=body.instance_uuid,
        name=body.name,
        domain=body.domain,
        description=body.description,
        categories=body.categories,
        contact_email=body.contact_email,
        logo_url=body.logo_url,
    )
    db.add(community)
    await db.commit()
    return {"status": "registered", "id": community.id}


@app.put("/api/update/{instance_uuid}")
async def update_community(
    instance_uuid: str,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update community listing."""
    result = await db.execute(
        select(Community).where(Community.instance_uuid == instance_uuid)
    )
    community = result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")

    community.name = body.name
    community.domain = body.domain
    community.description = body.description
    community.categories = body.categories
    community.contact_email = body.contact_email
    community.logo_url = body.logo_url
    community.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "updated"}


@app.get("/api/communities")
async def list_communities(
    category: str = None,
    search: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Search and list registered communities."""
    query = select(Community).where(Community.active == True, Community.verified == True)

    if category:
        query = query.where(Community.categories.contains([category]))
    if search:
        query = query.where(
            (Community.name.ilike(f"%{search}%"))
            | (Community.description.ilike(f"%{search}%"))
        )

    query = query.order_by(Community.created_at.desc()).limit(limit)
    result = await db.execute(query)
    communities = result.scalars().all()

    return [
        CommunityResponse(
            id=c.id,
            name=c.name,
            domain=c.domain,
            description=c.description,
            categories=c.categories or [],
            logo_url=c.logo_url,
            verified=c.verified,
            created_at=c.created_at.isoformat(),
        )
        for c in communities
    ]


@app.get("/api/community/{instance_uuid}")
async def get_community(instance_uuid: str, db: AsyncSession = Depends(get_db)):
    """Get a single community by instance UUID."""
    result = await db.execute(
        select(Community).where(Community.instance_uuid == instance_uuid)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Community not found")

    return CommunityResponse(
        id=c.id,
        name=c.name,
        domain=c.domain,
        description=c.description,
        categories=c.categories or [],
        logo_url=c.logo_url,
        verified=c.verified,
        created_at=c.created_at.isoformat(),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "libresynergy-discovery"}
