"""Shared test fixtures for LibreSynergy."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_dir():
    """Temporary directory that cleans up after test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_config():
    """Minimal valid config dict for template rendering."""
    return {
        "domain": "test.example.org",
        "admin_email": "admin@test.example.org",
        "community_name": "Test Community",
        "secrets": {
            "authentik_secret": "test-secret-48-chars-" + "x" * 28,
            "postgres_password": "test-pg-password-" + "x" * 8,
            "redis_password": "test-redis-pw-" + "x" * 10,
            "instance_uuid": "a" * 32,
            "federation_secret": "test-fed-secret-" + "x" * 16,
            "jitsi_jwt_secret": "test-jitsi-sec-" + "x" * 16,
            "api_admin_key": "test-api-key-" + "x" * 20,
            "matrix_registration_secret": "test-matrix-reg-" + "x" * 8,
            "matrix_macaroon_secret": "test-matrix-mac-" + "x" * 8,
            "matrix_form_secret": "test-matrix-form-" + "x" * 8,
        },
        "authentik_frappe_client_id": "frappe-client-id",
        "authentik_frappe_client_secret": "frappe-client-secret",
        "authentik_matrix_client_id": "matrix-client-id",
        "authentik_matrix_client_secret": "matrix-client-secret",
        "authentik_jitsi_client_id": "jitsi-client-id",
        "authentik_jitsi_client_secret": "jitsi-client-secret",
    }


@pytest.fixture
def cli_runner():
    """Click CLI test runner."""
    from click.testing import CliRunner
    return CliRunner()
