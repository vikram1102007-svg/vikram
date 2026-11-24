# MediReach FastAPI backend

A FastAPI API foundation using SQLAlchemy 2, SQLite for local tests/development, and PostgreSQL for production.

## Local run

```bash
cd MediReach/backend
python -m venv .venv
# activate the environment
pip install -r requirements.txt
cp .env.example .env
# For local development set DATABASE_URL=sqlite:///./medireach.db
alembic upgrade head
uvicorn app.main:app --reload
```

API docs: http://127.0.0.1:8000/docs. Health: /health.

## Public endpoints

- GET /api/v1/medicines?q= — medicine catalogue
- GET /api/v1/facilities?district= — active facilities
- GET /api/v1/availability?medicine=&district=&include_demo=false — availability and server-calculated freshness
- POST /api/v1/feedback — records a patient feedback review signal; never changes inventory

Feedback accepts only an inventory record ID and a structured outcome (`received` or `not_available`). Free-text fields are rejected at the API boundary to avoid collecting unnecessary personal or health information. Feedback is a review signal only and never changes inventory.

## Availability freshness

The API calculates confidence from the stored `verified_at` timestamp:

- Up to and including 24 hours old: `Recently Verified`
- More than 24 and up to 72 hours old: `Needs Confirmation`
- More than 72 hours old: `Outdated`
- More than five minutes in the future: `Needs Confirmation`

A five-minute future-clock tolerance accounts for small clock skew only. SQLite may return timezone-naive values for `DateTime(timezone=True)` columns; the API interprets these as UTC because all application writes use UTC and returns timezone-aware UTC timestamps to clients.

## Facility staff inventory updates

- PUT /api/v1/facilities/me/inventory — updates only the facility bound to the supplied X-Facility-Key credential.

Facility keys are stored as SHA-256 hashes, never as plaintext. Generate a key from a trusted server/administrative shell after the facility has been provisioned:

```bash
python -m app.issue_facility_key --facility-id 1
```

The command prints the new key once. Store it in a managed secret store and provide it only to the authorised facility operator. To revoke a key:

```bash
python -m app.issue_facility_key --revoke-key-id 1
```

A facility key cannot submit a facility ID; the API derives the facility scope from the key. Revoked keys and keys belonging to inactive facilities are rejected. Each inventory create/update writes an audit event with previous and new status/quantity.

## Database migrations and production deployment

Alembic manages the schema for local SQLite and production PostgreSQL. Run `alembic upgrade head` before starting the API; the application does not create or modify tables automatically at startup. Check for model/migration drift with `alembic check` after applying migrations. Create new reviewed revisions with `alembic revision --autogenerate -m "describe change"`, inspect the generated SQL, and commit the revision. Never edit an already-applied migration; add a new revision instead.

### Production environment

Production startup fails closed unless all of the following are configured:

- `ENVIRONMENT=production` (or `prod`)
- `DATABASE_URL` is a valid PostgreSQL URL with a hostname and database name
- `CORS_ORIGINS` contains one or more exact HTTPS origins, separated by commas; do not include paths, query strings, fragments, credentials, or wildcard origins

Example shape (placeholders only; never commit real credentials):

```env
ENVIRONMENT=production
DATABASE_URL=postgresql://<db-user>:<db-password>@<db-host>:5432/<db-name>
CORS_ORIGINS=https://medireach-platform.embarko.app
SEED_DEMO_DATA=false
```

The application normalises `postgres://` and `postgresql://` to the installed `postgresql+psycopg://` driver. SQLAlchemy and Alembic use the same normalised URL. SQLite remains supported for local development and CI only.

Store the real database URL in the backend host's secret manager. Do not place it in frontend files, Docker build arguments, committed `.env` files, or logs. No database or backend host is provisioned by this repository. Do not deploy with a SQLite file or use a demo database for real inventory.

Before a pilot, configure HTTPS, managed secrets, backups, monitoring, rate limiting, and an authorised facility inventory source. Confirm migrations against the actual managed PostgreSQL service before routing traffic.

No real facilities or stock are fabricated by this API. Demo records are excluded from availability search by default. Feedback is a review signal and does not change stock. Do not store patient diagnoses, prescriptions, identity documents, or unnecessary sensitive health information. Users must confirm availability directly with the facility. MediReach does not diagnose, prescribe, or recommend medicine substitutions.
