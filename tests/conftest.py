import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import User, db


@pytest.fixture()
def app():
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "WTF_CSRF_ENABLED": False,
                      "SQLALCHEMY_DATABASE_URI": "sqlite://", "RATELIMIT_ENABLED": False,
                      "SERVICE_WEEKDAYS": "0,1,2,3,4,5,6"})  # most tests ignore the Sunday rule; test_sundays_only.py turns it on
    with app.app_context():
        db.create_all()
        for name, role in (("admin", "admin"), ("media", "media"), ("kids", "children")):
            db.session.add(User(username=name, role=role, password_hash=generate_password_hash("password123")))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user):
    return client.post("/login", data={"username": user, "password": "password123"})
