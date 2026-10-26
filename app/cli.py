import click
from werkzeug.security import generate_password_hash

from datetime import date

from .models import ROLES, Person, User, db


def register_cli(app):
    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("role", type=click.Choice(ROLES))
    @click.option("--email", default=None, help="Optional email, can also be used to log in.")
    @click.password_option()
    def create_user(username, role, email, password):
        """Create a login. Each person should have their own."""
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters")
        username = username.strip().lower()
        email = email.strip().lower() if email else None
        if User.query.filter(db.or_(User.username == username, User.email == (email or username))).first():
            raise click.ClickException("That username or email already exists")
        db.session.add(User(username=username, email=email, role=role,
                            password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo(f"Created {role} '{username}'")

    @app.cli.command("list-users")
    def list_users():
        """List all logins."""
        for u in User.query.order_by(User.username):
            click.echo(f"{u.username:20} {u.role:10} {u.email or ''}")

    @app.cli.command("reset-password")
    @click.argument("identifier")
    @click.password_option()
    def reset_password(identifier, password):
        """Set a new password for a username or email."""
        ident = identifier.strip().lower()
        user = User.query.filter(db.or_(User.username == ident, User.email == ident)).first()
        if not user:
            raise click.ClickException("No such user")
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters")
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        click.echo(f"Password updated for '{user.username}'")

    @app.cli.command("delete-user")
    @click.argument("identifier")
    @click.confirmation_option(prompt="Delete this login?")
    def delete_user(identifier):
        """Delete a login by username or email."""
        ident = identifier.strip().lower()
        user = User.query.filter(db.or_(User.username == ident, User.email == ident)).first()
        if not user:
            raise click.ClickException("No such user")
        if user.role == "owner":
            raise click.ClickException("The owner login cannot be deleted")
        db.session.delete(user)
        db.session.commit()
        click.echo(f"Deleted '{user.username}'")

    @app.cli.command("send-greetings")
    @click.option("--dry-run", is_flag=True, help="Print what would be sent. Sends nothing.")
    @click.option("--date", "on_date", default=None, help="Pretend today is YYYY-MM-DD (dry run only).")
    def send_greetings(dry_run, on_date):
        """Send today's birthday and new-month SMS greetings (safe to run hourly)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from .services.greetings import run_greetings
        from .services.sms import provider_from_config

        provider = provider_from_config(app.config)
        now = None
        if on_date:
            if not dry_run:
                raise click.ClickException("--date only works together with --dry-run")
            now = datetime.combine(date.fromisoformat(on_date), datetime.min.time(),
                                   tzinfo=ZoneInfo(app.config["TIMEZONE"]))
        if provider is None and not dry_run:
            click.echo("SMS is off or not configured (SMS_ENABLED, SMS_API_TOKEN, SMS_SENDER_ID). Nothing sent.")
            return
        r = run_greetings(provider, now=now, dry_run=dry_run)
        for line in r.dry_lines:
            click.echo(line)
        if r.outside_hours:
            click.echo("Outside 08:00-20:00 Lagos time. Nothing sent.")
        click.echo(f"sent={r.sent} failed={r.failed} already_done={r.skipped_done}"
                   + (f" STOPPED: {r.stopped_early}" if r.stopped_early else ""))

    @app.cli.command("sms-optout")
    @click.argument("phone")
    def sms_optout(phone):
        """Stop greetings for a phone number (08012345678)."""
        from .services.phone import normalize_phone
        p = Person.query.filter_by(phone=normalize_phone(phone)).first()
        if not p:
            raise click.ClickException("No one on record with that number")
        p.sms_opt_in = False
        db.session.commit()
        click.echo(f"Greetings stopped for {p.full_name}")
