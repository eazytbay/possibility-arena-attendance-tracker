# Church Attendance

Mobile-first attendance system for a church of ~400 people: QR self-registration, media-team check-in,
automatic first-time-visitor detection, children's ministry drop-off and pickup codes, and CSV export.

## Design decisions
- **Flask + SQLAlchemy + PostgreSQL**, Alembic migrations, Docker Compose.
- **Idempotent check-in**: a unique (service, person) constraint makes double scans and retries safe.
- **Households**: children are linked to a guardian and carry no phone number or photo.
- **Child safety**: a per-service 4-digit pickup code; a child is released only against that code, once.
- **Roles**: owner, admin, media, children. Least privilege enforced server-side.
- **Security**: CSRF protection, login rate limiting, hashed passwords, CSV formula-injection guard,
  honeypot on the public form, audit log of check-ins, releases, exports and user changes.
- **Time zone**: services are dated in Africa/Lagos.

## Run locally
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements-dev.txt
    pytest
    export SECRET_KEY=dev; flask --app app:create_app db upgrade
    flask --app app:create_app create-user admin admin

## Deploy
See DEPLOY.md.

## Not yet built
Offline sync for poor connectivity, trend dashboards, SMS follow-up of visitors.
