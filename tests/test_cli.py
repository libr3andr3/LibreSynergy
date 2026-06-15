"""Tests for the CLI commands."""


class TestBootstrap:
    """bootstrap command tests."""

    def test_help(self, cli_runner):
        from cli.main import cli
        result = cli_runner.invoke(cli, ["bootstrap", "--help"])
        assert result.exit_code == 0
        assert "Bootstrap" in result.output
        assert "--domain" in result.output
        assert "--non-interactive" in result.output

    def test_non_interactive_generates_files(self, cli_runner, temp_dir):
        from cli.main import cli
        result = cli_runner.invoke(cli, [
            "bootstrap",
            "--domain", "test.example.org",
            "--output", str(temp_dir),
            "--non-interactive",
        ])
        assert result.exit_code == 0
        assert "Bootstrap complete" in result.output

        # Check all 14 files generated
        expected_files = [
            "branding.yaml",
            "docker-compose.yml",
            "nginx.conf",
            "homeserver.yaml",
            "prosody.cfg.lua",
            "frappe-common-site-config.json",
            "element-config.json",
            "jitsi-config.js",
            "jitsi-interface-config.js",
            "setup-frappe.sh",
            "setup-matrix.sh",
            "setup-jitsi.sh",
            "well-known/matrix/server",
            "well-known/matrix/client",
        ]
        for f in expected_files:
            assert (temp_dir / f).exists(), f"Missing: {f}"

    def test_output_files_have_substitutions(self, cli_runner, temp_dir):
        from cli.main import cli
        result = cli_runner.invoke(cli, [
            "bootstrap",
            "--domain", "test.example.org",
            "--output", str(temp_dir),
            "--non-interactive",
        ])
        assert result.exit_code == 0

        # Verify domain substitution in key files
        compose = (temp_dir / "docker-compose.yml").read_text()
        assert "test.example.org" in compose
        # No raw Jinja2 syntax should remain
        assert "{{" not in compose
        assert "{%" not in compose

        # Nginx should have subdomain references
        nginx = (temp_dir / "nginx.conf").read_text()
        assert "auth.test.example.org" in nginx
        assert "learn.test.example.org" in nginx
        assert "chat.test.example.org" in nginx
        assert "meet.test.example.org" in nginx


class TestAuthentikSetup:
    """authentik-setup command tests."""

    def test_help(self, cli_runner):
        from cli.main import cli
        result = cli_runner.invoke(cli, ["authentik-setup", "--help"])
        assert result.exit_code == 0
        assert "--domain" in result.output
        assert "--admin-password" in result.output


class TestPaymentSetup:
    """payment-setup command tests."""

    def test_help(self, cli_runner):
        from cli.main import cli
        result = cli_runner.invoke(cli, ["payment-setup", "--help"])
        assert result.exit_code == 0
        assert "--domain" in result.output
        assert "--btcpay-url" in result.output
        assert "--stripe-key" in result.output


class TestBranding:
    """branding command tests."""

    def test_help(self, cli_runner):
        from cli.main import cli
        result = cli_runner.invoke(cli, ["branding", "--help"])
        assert result.exit_code == 0
        assert "branding" in result.output.lower()

    def test_branding_defaults(self):
        from cli.branding import BRANDING_DEFAULTS
        assert BRANDING_DEFAULTS["primary_color"] == "#4F46E5"
        assert "community_name" in BRANDING_DEFAULTS


class TestCLIRoot:
    """Root CLI tests."""

    def test_help_lists_all_commands(self, cli_runner):
        from cli.main import cli
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "bootstrap" in result.output
        assert "authentik-setup" in result.output
        assert "payment-setup" in result.output
        assert "branding" in result.output
