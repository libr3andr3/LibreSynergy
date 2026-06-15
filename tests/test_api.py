"""Tests for the API microservice."""


class TestAPIImports:
    """Verify all API modules import cleanly."""

    def test_database_imports(self):
        from api.database import Base, get_db, _get_engine
        assert Base is not None
        assert callable(get_db)

    def test_models_imports(self):
        from api.models import (
            Subscription,
            FederationRelationship,
            Bundle,
            PaymentEvent,
        )
        # Verify table names
        assert Subscription.__tablename__ == "subscriptions"
        assert FederationRelationship.__tablename__ == "federation_relationships"
        assert Bundle.__tablename__ == "bundles"
        assert PaymentEvent.__tablename__ == "payment_events"

    def test_auth_imports(self):
        from api.auth import AuthentikClient, require_admin, require_user
        assert AuthentikClient is not None
        assert callable(require_admin)

    def test_tiers_imports(self):
        from api.tiers import set_user_tier, get_user_tier, set_group_uuids
        assert callable(set_user_tier)
        assert callable(get_user_tier)

    def test_matrix_rooms_imports(self):
        from api.matrix_rooms import MatrixAdmin, TIER_ROOMS, sync_user_rooms
        assert "free" in TIER_ROOMS
        assert "premium" in TIER_ROOMS
        assert "max" in TIER_ROOMS
        assert len(TIER_ROOMS["max"]) > len(TIER_ROOMS["free"])

    def test_app_creates(self):
        from api.app import app
        assert app.title == "libresynergy API"
        assert app.version == "0.1.0"


class TestFederationRoutes:
    """Federation router has all required endpoints."""

    def test_all_endpoints_present(self):
        from api.federation import router
        paths = {r.path for r in router.routes}
        expected = {
            "/invite",
            "/invite-received",
            "/pending",
            "/accept",
            "/confirm",
            "/revoke/{partner_uuid}",
            "/revoked",
            "/partners",
            "/discover/{partner_uuid}/courses",
        }
        assert paths == expected

    def test_endpoint_count(self):
        from api.federation import router
        assert len(router.routes) == 9


class TestPaymentRoutes:
    """Payment router has all required webhook endpoints."""

    def test_all_endpoints_present(self):
        from api.payments import router
        paths = {r.path for r in router.routes}
        expected = {"/btcpay", "/stripe", "/bundle/notify"}
        assert paths == expected

    def test_endpoint_count(self):
        from api.payments import router
        assert len(router.routes) == 3


class TestAppRoutes:
    """App has health + root endpoints."""

    def test_health_endpoint(self):
        from api.app import app

        routes = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/health" in routes
        assert "/" in routes


class TestModelsSchema:
    """Verify model fields."""

    def test_subscription_fields(self):
        from api.models import Subscription
        cols = {c.name for c in Subscription.__table__.columns}
        assert "user_sub" in cols
        assert "tier" in cols
        assert "active" in cols
        assert "payment_provider" in cols

    def test_federation_relationship_fields(self):
        from api.models import FederationRelationship
        cols = {c.name for c in FederationRelationship.__table__.columns}
        assert "partner_instance_uuid" in cols
        assert "status" in cols
        assert "shared_rooms" in cols
        assert "shared_courses" in cols
        assert "shared_jitsi" in cols

    def test_bundle_fields(self):
        from api.models import Bundle
        cols = {c.name for c in Bundle.__table__.columns}
        assert "name" in cols
        assert "price_monthly_cents" in cols
        assert "creator_instances" in cols
