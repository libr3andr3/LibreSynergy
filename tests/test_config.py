"""Tests for config generation and template rendering."""


class TestSecrets:
    """Secret generation tests."""

    def test_generate_secrets_count(self):
        from cli.config import generate_secrets
        secrets = generate_secrets()
        assert len(secrets) == 10
        assert "authentik_secret" in secrets
        assert "postgres_password" in secrets
        assert "instance_uuid" in secrets
        assert "federation_secret" in secrets

    def test_secrets_are_unique(self):
        from cli.config import generate_secrets
        s1 = generate_secrets()
        s2 = generate_secrets()
        for key in s1:
            assert s1[key] != s2[key], f"Secret '{key}' is not unique across calls"

    def test_instance_uuid_is_hex(self):
        from cli.config import generate_secrets
        secrets = generate_secrets()
        uuid = secrets["instance_uuid"]
        assert len(uuid) == 32  # 16 bytes = 32 hex chars
        assert all(c in "0123456789abcdef" for c in uuid)

    def test_authentik_secret_length(self):
        from cli.config import generate_secrets
        secrets = generate_secrets()
        # 48 bytes → 64 base64 chars
        assert len(secrets["authentik_secret"]) == 64

    def test_oidc_placeholders_count(self):
        from cli.config import generate_oidc_placeholders
        oidc = generate_oidc_placeholders()
        assert len(oidc) == 6
        assert "authentik_frappe_client_id" in oidc
        assert "authentik_matrix_client_id" in oidc
        assert "authentik_jitsi_client_id" in oidc


class TestWizard:
    """Configuration wizard tests."""

    def test_non_interactive_defaults(self):
        from cli.config import run_wizard
        config = run_wizard(non_interactive=True)
        assert config["domain"] == "learn.example.com"
        assert config["admin_email"] == "admin@example.com"
        assert config["community_name"] == "My Learning Community"
        assert "secrets" in config
        assert "authentik_frappe_client_id" in config

    def test_domain_override(self):
        from cli.config import run_wizard
        config = run_wizard(domain="my.school.org", non_interactive=True)
        assert config["domain"] == "my.school.org"


class TestTemplates:
    """Template rendering tests."""

    def test_all_templates_render(self, temp_dir, sample_config):
        from cli.config import render_templates
        count = render_templates(sample_config, str(temp_dir))
        assert count == 14
        assert (temp_dir / "docker-compose.yml").exists()
        assert (temp_dir / "nginx.conf").exists()
        assert (temp_dir / "homeserver.yaml").exists()
        assert (temp_dir / "prosody.cfg.lua").exists()
        assert (temp_dir / "branding.yaml").exists()

    def test_docker_compose_has_services(self, temp_dir, sample_config):
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        compose = (temp_dir / "docker-compose.yml").read_text()
        assert "postgres:" in compose
        assert "authentik-server:" in compose
        assert "matrix:" in compose
        assert "frappe:" in compose
        assert "jitsi-web:" in compose
        assert "api:" in compose
        assert "nginx:" in compose

    def test_docker_compose_no_placeholders(self, temp_dir, sample_config):
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        compose = (temp_dir / "docker-compose.yml").read_text()
        # No Jinja2 leftovers
        assert "{{" not in compose
        assert "{%" not in compose

    def test_nginx_has_all_subdomains(self, temp_dir, sample_config):
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        nginx = (temp_dir / "nginx.conf").read_text()
        assert "auth.test.example.org" in nginx
        assert "learn.test.example.org" in nginx
        assert "chat.test.example.org" in nginx
        assert "meet.test.example.org" in nginx
        assert "api.test.example.org" in nginx

    def test_well_known_files_in_subdir(self, temp_dir, sample_config):
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        assert (temp_dir / "well-known" / "matrix" / "server").exists()
        assert (temp_dir / "well-known" / "matrix" / "client").exists()

        # Should contain domain substitution
        server = (temp_dir / "well-known" / "matrix" / "server").read_text()
        assert "test.example.org" in server

    def test_setup_scripts_are_executable(self, temp_dir, sample_config):
        import stat
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        for script in ["setup-frappe.sh", "setup-matrix.sh", "setup-jitsi.sh"]:
            path = temp_dir / script
            assert path.exists()
            st = path.stat()
            assert st.st_mode & stat.S_IXUSR, f"{script} is not executable"

    def test_homeserver_yaml_has_oidc(self, temp_dir, sample_config):
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        homeserver = (temp_dir / "homeserver.yaml").read_text()
        assert "oidc_providers:" in homeserver
        assert "authentik" in homeserver
        assert "matrix-client-id" in homeserver

    def test_prosody_config_has_jwt(self, temp_dir, sample_config):
        from cli.config import render_templates
        render_templates(sample_config, str(temp_dir))
        prosody = (temp_dir / "prosody.cfg.lua").read_text()
        assert "token" in prosody.lower()
        assert "libresynergy" in prosody
