"""libresynergy API — FastAPI application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.database import Base, _get_engine
from api.federation import router as federation_router
from api.payments import router as payments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup."""
    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="libresynergy API",
    description="Federation, payment, and tier management for libresynergy communities",
    version="0.1.0",
    lifespan=lifespan,
)

# Include sub-routers
app.include_router(federation_router, prefix="/federation", tags=["federation"])
app.include_router(payments_router, prefix="/payments", tags=["payments"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "instance": os.getenv("INSTANCE_UUID", "unknown"),
        "version": "0.1.0",
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "libresynergy API",
        "docs": "/docs",
        "health": "/health",
    }
