"""libresynergy CLI — bootstrap and manage your learning community."""

import click


@click.group()
@click.version_option()
def cli():
    """libresynergy — Federated Learning Community Suite.

    One command to deploy your own online school with SSO, courses,
    federated chat, live video, and crypto + fiat payments.
    """
    pass


@cli.command()
@click.option("--domain", help="Public domain for this community (e.g., learn.myorg.com)")
@click.option("--output", "-o", default=".", help="Output directory for generated config")
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts, use defaults")
def bootstrap(domain, output, non_interactive):
    """Bootstrap a new libresynergy community.

    Generates docker-compose.yml, nginx.conf, and all required
    environment files. Runs interactively by default — asks for
    domain, admin email, payment keys, and branding preferences.
    """
    from cli.config import run_wizard, render_templates

    click.echo("")
    click.echo("  ╔══════════════════════════════════════════╗")
    click.echo("  ║       libresynergy — Bootstrap            ║")
    click.echo("  ║   Federated Learning Community Suite      ║")
    click.echo("  ╚══════════════════════════════════════════╝")
    click.echo("")

    config = run_wizard(domain=domain, non_interactive=non_interactive)
    render_templates(config, output)

    click.echo("")
    click.echo("  ✅ Bootstrap complete!")
    click.echo(f"  📁 Output directory: {output}")
    click.echo("")
    click.echo("  Next steps:")
    click.echo(f"    1. cd {output}")
    click.echo("    2. docker compose up -d")
    click.echo("    3. Wait ~60s for Authentik to start")
    click.echo("    4. Configure SSO:")
    click.echo(f"       PYTHONPATH=.. ../.venv/bin/python3 -m cli.main authentik-setup \\")
    click.echo(f"         --domain {config.get('domain', 'your-domain.com')} \\")
    click.echo("         --admin-password <your-password>")
    click.echo("")
    click.echo("  See README.md for the full quick start guide.")
    click.echo("")


@cli.command()
@click.option("--domain", required=True, help="Community domain (e.g., learn.myorg.com)")
@click.option("--auth-url", help="Authentik URL (default: https://auth.<domain>)")
@click.option("--admin-password", help="Authentik admin password (prompts if omitted)")
def authentik_setup(domain, auth_url, admin_password):
    """Configure Authentik: OIDC providers, apps, groups, JWT claims.

    Run this AFTER docker compose up -d and after Authentik is healthy.
    Creates OIDC providers for Frappe LMS, Matrix, and Jitsi Meet,
    tier groups (free/premium/max), and JWT property mappings.
    Outputs client IDs/secrets to update your docker-compose.yml.
    """
    from cli.authentik_setup import run_authentik_bootstrap

    if not auth_url:
        auth_url = f"https://auth.{domain}"

    if not admin_password:
        admin_password = click.prompt(
            "Authentik admin password", hide_input=True, type=str
        )

    click.echo("")
    click.echo("  ⚙  Configuring Authentik...")
    click.echo("")

    result = run_authentik_bootstrap(
        domain=domain,
        auth_url=auth_url,
        admin_password=admin_password,
    )

    if result:
        click.echo("")
        click.echo("  ✅ Authentik configured successfully!")
        click.echo("")
        click.echo("  Update your docker-compose.yml with these values:")
        click.echo("")
        for key, value in sorted(result.items()):
            if key.startswith("authentik_"):
                click.echo(f"    {key}: {value}")
        click.echo("")
        click.echo("  Or run: libresynergy bootstrap --reconfigure")
    else:
        click.echo("")
        click.echo("  ❌ Authentik setup failed. Check that Authentik is running and healthy.")
        click.echo(f"     Try: curl {auth_url}/-/health/")


@cli.command()
@click.option("--domain", required=True, help="Community domain")
@click.option("--btcpay-url", help="BTC PayServer URL")
@click.option("--btcpay-key", help="BTC PayServer API key")
@click.option("--stripe-key", help="Stripe secret key")
@click.option("--monero-wallet", help="Monero wallet address (optional)")
def payment_setup(domain, btcpay_url, btcpay_key, stripe_key, monero_wallet):
    """Auto-configure payment providers: BTC PayServer + Stripe.

    Paste your API keys and this command creates stores, products,
    webhooks, and payment links — no manual configuration needed.
    """
    click.echo("")
    click.echo("  ╔══════════════════════════════════════╗")
    click.echo("  ║  libresynergy — Payment Setup         ║")
    click.echo("  ╚══════════════════════════════════════╝")
    click.echo("")

    results = {}

    if btcpay_url and btcpay_key:
        click.echo("  ── BTC PayServer ──")
        click.echo("")
        from cli.btcpay_setup import setup_btcpay
        try:
            results["btcpay"] = setup_btcpay(
                btcpay_url=btcpay_url,
                api_key=btcpay_key,
                domain=domain,
                monero_wallet=monero_wallet,
            )
            click.echo("")
        except Exception as e:
            click.echo(f"  ❌ BTC PayServer setup failed: {e}")
            click.echo("")

    if stripe_key:
        click.echo("  ── Stripe ──")
        click.echo("")
        from cli.stripe_setup import setup_stripe
        try:
            results["stripe"] = setup_stripe(
                api_key=stripe_key,
                domain=domain,
            )
            click.echo("")
        except Exception as e:
            click.echo(f"  ❌ Stripe setup failed: {e}")
            click.echo("")

    if results:
        click.echo("  ✅ Payment providers configured!")
        click.echo("")
        click.echo("  Update your .env or docker-compose.yml with the")
        click.echo("  product/webhook IDs shown above.")
    elif not btcpay_url and not stripe_key:
        click.echo("  ℹ  No payment provider configured.")
        click.echo("  Use --btcpay-url/--btcpay-key and/or --stripe-key")
        click.echo("  to auto-configure your payment providers.")
        click.echo("")
    else:
        click.echo("  ⚠  Some providers failed. Check the errors above.")


@cli.command()
@click.option("--config", default="branding.yaml", help="Path to branding.yaml")
@click.option("--domain", help="Community domain")
def branding(config, domain):
    """Apply branding (name, logo, colors) to all services."""
    from cli.branding import apply_branding
    apply_branding(config, domain)
