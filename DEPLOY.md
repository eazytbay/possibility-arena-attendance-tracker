# Deploy (VPS, Docker Compose)

1. `cp .env.example .env` and set SECRET_KEY, POSTGRES_PASSWORD (also inside DATABASE_URL),
   CHURCH_NAME and PUBLIC_BASE_URL.
2. `docker compose up -d --build`
3. Create the first admin:
   `docker compose exec app flask --app app:create_app create-user admin admin`
4. Put nginx (HTTPS) in front of 127.0.0.1:8300 for the subdomain, e.g. attendance.enobsai.com.
5. Back up the `pgdata` volume regularly (`pg_dump`).
