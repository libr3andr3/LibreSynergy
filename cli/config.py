"""Interactive configuration wizard and template renderer for libresynergy."""

import os
import secrets
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader


REQUIRED_CONFIG = {
    "domain": "Public domain (e.g., learn.mycommunity.com)",
    "admin_email": "Admin email address",
    "community_name": "Community display name",
}

OPTIONAL_CONFIG = {
    "btcpay_url": "BTC PayServer URL (or leave blank to skip)",
    "btcpay_key": "BTC PayServer API key",
    "stripe_key": "Stripe secret key (or leave blank to skip)",
    "monero_wallet": "Monero wallet address (or leave blank)",
}


def generate_secrets():
    """Generate all cryptographic secrets needed by the stack."""
    return {
        "authentik_secret": secrets.token_urlsafe(48),
        "matrix_registration_secret": secrets.token_urlsafe(32),
        "matrix_macaroon_secret": secrets.token_urlsafe(32),
        "matrix_form_secret": secrets.token_urlsafe(32),
        "jitsi_jwt_secret": secrets.token_urlsafe(32),
        "api_admin_key": secrets.token_urlsafe(32),
        "postgres_password": secrets.token_urlsafe(24),
        "redis_password": secrets.token_urlsafe(24),
        "instance_uuid": secrets.token_hex(16),
        "federation_secret": secrets.token_urlsafe(32),
    }


def generate_oidc_placeholders():
    """Placeholder OIDC client IDs/secrets — replaced by Authentik bootstrap."""
    return {
        "authentik_frappe_client_id": "PLACEHOLDER_frappe",
        "authentik_frappe_client_secret": "PLACEHOLDER_frappe_secret",
        "authentik_matrix_client_id": "PLACEHOLDER_matrix",
        "authentik_matrix_client_secret": "PLACEHOLDER_matrix_secret",
        "authentik_jitsi_client_id": "PLACEHOLDER_jitsi",
        "authentik_jitsi_client_secret": "PLACEHOLDER_jitsi_secret",
    }


def run_wizard(domain=None, non_interactive=False):
    """Run interactive config wizard, return config dict.

    Args:
        domain: Pre-set domain (from --domain flag).
        non_interactive: If True, skip prompts and use defaults.

    Returns:
        dict with keys: domain, admin_email, community_name, secrets,
                        btcpay_url, btcpay_key, stripe_key, monero_wallet
    """
    config = {
        "secrets": generate_secrets(),
    }
    # Add OIDC placeholders — replaced by Authentik bootstrap after first deploy
    config.update(generate_oidc_placeholders())

    if domain:
        config["domain"] = domain

    click.echo("")

    if non_interactive:
        config.setdefault("domain", "learn.example.com")
        config.setdefault("admin_email", "admin@example.com")
        config.setdefault("community_name", "My Learning Community")
        click.echo("  ⚡ Non-interactive mode — using defaults")
        return config

    # --- Required fields ---
    click.echo("  ── Required ──")
    click.echo("")
    for key, prompt in REQUIRED_CONFIG.items():
        if key in config:
            continue
        value = click.prompt(f"  {prompt}", default="").strip()
        while not value:
            value = click.prompt(f"  {prompt} (required)", default="").strip()
        config[key] = value

    # --- Payment setup ---
    click.echo("")
    click.echo("  ── Payments (optional) ──")
    click.echo("")
    for key, prompt in OPTIONAL_CONFIG.items():
        value = click.prompt(f"  {prompt}", default="").strip()
        if value:
            config[key] = value

    return config


def render_templates(config, output_dir):
    """Render all Jinja2 templates to the output directory.

    Special handling:
      - well-known-matrix-<name>.json.j2 → well-known/matrix/<name>
      - Dockerfile.frappe.j2 → docker/frappe/Dockerfile
      - setup-<service>.sh.j2 → setup-<service>.sh (executable)

    Args:
        config: Config dict from run_wizard().
        output_dir: Path to write generated files.
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    output_path = Path(output_dir).resolve()
    os.makedirs(output_path, exist_ok=True)

    rendered = 0
    for template_file in sorted(template_dir.glob("*.j2")):
        template = env.get_template(template_file.name)
        output_name = template_file.name.replace(".j2", "")

        # Route .well-known files to the correct subdirectory
        if output_name.startswith("well-known-matrix-"):
            well_known_name = output_name.replace("well-known-matrix-", "")
            target_dir = output_path / "well-known" / "matrix"
            os.makedirs(target_dir, exist_ok=True)
            target = target_dir / well_known_name.replace(".json", "")
        elif output_name == "Dockerfile.frappe":
            target_dir = output_path / "docker" / "frappe"
            os.makedirs(target_dir, exist_ok=True)
            target = target_dir / "Dockerfile"
        elif output_name == "Dockerfile.api":
            target_dir = output_path / "docker" / "api"
            os.makedirs(target_dir, exist_ok=True)
            target = target_dir / "Dockerfile"
        else:
            target = output_path / output_name

        target.write_text(template.render(**config))

        # Make shell scripts executable
        if output_name.startswith("setup-") and output_name.endswith(".sh"):
            target.chmod(0o755)

        rendered += 1

        # Show relative path for nested files
        display_name = str(target.relative_to(output_path)) if target.parent != output_path else output_name
        click.echo(f"  ✓ {display_name}")

    if rendered == 0:
        click.echo("  ⚠ No templates found in cli/templates/")

    # Copy project source files needed by Docker builds
    _copy_project_source(output_path)

    return rendered


def _copy_project_source(output_dir: Path):
    """Copy api/, cli/, pyproject.toml to output dir for Docker builds."""
    project_root = Path(__file__).parent.parent
    import shutil

    for item in ["api", "cli", "pyproject.toml"]:
        src = project_root / item
        dst = output_dir / item
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif src.is_file():
            shutil.copy2(src, dst)
