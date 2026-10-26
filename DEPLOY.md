# Deploy (VPS, Docker Compose)

1. `cp .env.example .env` and set SECRET_KEY, POSTGRES_PASSWORD (also inside DATABASE_URL),
   CHURCH_NAME and PUBLIC_BASE_URL.
2. `docker compose up -d --build`
3. Create the first admin:
   `docker compose exec app flask --app app:create_app create-user admin admin`
4. Put nginx (HTTPS) in front of 127.0.0.1:8300 for the subdomain, e.g. attendance.enobsai.com.
5. Back up the `pgdata` volume regularly (`pg_dump`).

## SMS greetings (birthday and new month)

1. Open a Bulk SMS Nigeria account, request a sender ID (max 11 characters) and top up.
2. On the server, edit `.env`: set `SMS_ENABLED=true`, `SMS_API_TOKEN=...`, `SMS_SENDER_ID=...`. Never commit this file.
3. `docker compose up -d --build` (runs the migration).
4. Preview: `docker compose exec -T app flask send-greetings --dry-run --date 2026-11-05`
5. Cron, every hour (the app itself only sends 8am to 8pm Lagos time): `0 * * * * cd ~/possibility-arena-attendance-tracker && docker compose exec -T app flask send-greetings >> ~/greetings.log 2>&1`
   Safe to repeat: each person gets each greeting once; failures retry up to 3 times.
6. Stop a person: `docker compose exec -T app flask sms-optout 08012345678`
