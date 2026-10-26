import logging

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .models import db

csrf = CSRFProtect()
migrate = Migrate()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app(overrides: dict | None = None) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY must be set")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    from .blueprints import admin, auth, public, staff
    for module in (auth, public, staff, admin):
        app.register_blueprint(module.bp)

    from .cli import register_cli
    register_cli(app)

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    @app.context_processor
    def inject_globals():
        return {"church_name": app.config["CHURCH_NAME"]}

    return app
