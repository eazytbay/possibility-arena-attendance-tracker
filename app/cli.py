import click
from werkzeug.security import generate_password_hash

from .models import ROLES, User, db


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
