import click
from werkzeug.security import generate_password_hash

from .models import ROLES, User, db


def register_cli(app):
    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("role", type=click.Choice(ROLES))
    @click.password_option()
    def create_user(username, role, password):
        """Create a staff login (admin, usher or children)."""
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters")
        db.session.add(User(username=username.strip().lower(), role=role,
                            password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo(f"Created {role} '{username}'")
