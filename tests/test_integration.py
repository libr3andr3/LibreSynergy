"""Integration tests for the payment, branding, and discovery modules."""


class TestBTCPayServer:
    """BTC PayServer module tests."""

    def test_client_creates(self):
        from cli.btcpay_setup import BTCPayClient
        client = BTCPayClient("https://btcpay.example.com", "test-key")
        assert client.base_url == "https://btcpay.example.com"
        assert "test-key" in client.headers["Authorization"]

    def test_tier_prices(self):
        from cli.btcpay_setup import TIER_PRICES
        assert TIER_PRICES == {"free": 0, "premium": 29.99, "max": 99.99}

    def test_setup_function_exists(self):
        from cli.btcpay_setup import setup_btcpay
        assert callable(setup_btcpay)


class TestStripe:
    """Stripe module tests."""

    def test_setup_function_exists(self):
        from cli.stripe_setup import setup_stripe
        assert callable(setup_stripe)


class TestBranding:
    """Branding module tests."""

    def test_defaults(self):
        from cli.branding import BRANDING_DEFAULTS, load_branding
        assert BRANDING_DEFAULTS["primary_color"] == "#4F46E5"
        assert BRANDING_DEFAULTS["secondary_color"] == "#7C3AED"
        assert BRANDING_DEFAULTS["background_color"] == "#0F172A"

        # load_branding returns defaults when no file exists
        defaults = load_branding("/nonexistent/branding.yaml")
        assert defaults["primary_color"] == "#4F46E5"


class TestDiscovery:
    """Discovery registry tests."""

    def test_app_creates(self):
        from discovery.app import app
        assert app.title == "libresynergy Discovery Registry"
        assert app.version == "0.1.0"

    def test_models_exist(self):
        from discovery.app import Community, CommunityResponse, RegisterRequest
        assert Community.__tablename__ == "communities"
        # Pydantic v2 uses model_fields instead of __dict__ attributes
        assert "instance_uuid" in RegisterRequest.model_fields
        assert "name" in CommunityResponse.model_fields

    def test_routes_registered(self):
        from discovery.app import app
        paths = set()
        for r in app.routes:
            if hasattr(r, "path"):
                paths.add(r.path)
        assert "/api/register" in paths
        assert "/api/communities" in paths
        assert "/health" in paths


class TestAuthentikSetup:
    """Authentik bootstrap module tests."""

    def test_admin_client_methods(self):
        from cli.authentik_setup import AuthentikAdmin
        methods = [m for m in dir(AuthentikAdmin) if not m.startswith("_")]
        assert "post" in methods
        assert "get" in methods
        assert "patch" in methods
        assert "delete" in methods

    def test_functions_exist(self):
        from cli.authentik_setup import (
            wait_for_authentik,
            create_admin_token,
            create_oidc_providers,
            create_applications,
            create_groups,
            create_property_mappings,
            output_config,
            run_authentik_bootstrap,
        )
        for fn in [
            wait_for_authentik,
            create_admin_token,
            create_oidc_providers,
            create_applications,
            create_groups,
            create_property_mappings,
            output_config,
            run_authentik_bootstrap,
        ]:
            assert callable(fn)
