FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps
COPY pyproject.toml /app/
RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy[asyncio] \
    asyncpg httpx python-jose[cryptography] pydantic psycopg2-binary alembic

# Copy application code
COPY api/ /app/api/
COPY cli/ /app/cli/

# Create non-root user
RUN useradd --create-home --shell /bin/bash libresynergy
USER libresynergy

EXPOSE 5000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "5000"]
