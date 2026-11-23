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

## Production configuration safety

When `ENVIRONMENT=production` (or `prod`), configuration validation fails closed unless:

- `DATABASE_URL` is a PostgreSQL URL with a host and database. SQLite is rejected.
- `CORS_ORIGINS` contains one or more exact HTTPS origins. Wildcards, HTTP origins, paths, query strings and fragments are rejected.
- PostgreSQL URLs using `postgres://` or `postgresql://` are normalized to the installed `postgresql+psycopg` driver. The explicit `postgresql+psycopg://` form is also supported.

Keep the production database URL and any facility credentials in the hosting provider's secret manager. Never commit a real `.env` file. The example file contains placeholders only. Run migrations explicitly with `alembic upgrade head` before starting the API; the API does not create or modify tables automatically at startup.

## Public endpoints

- GET /api/v1/medicines?q= — medicine catalogue
- GET /api/v1/facilities?district= — active facilities
- GET /api/v1/availability?medicine=&district=&include_demo=false — availability and server-calculated freshness
- POST /api/v1/feedback — records a patient feedback review signal; never changes inventory

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

Alembic manages the schema for both local SQLite and production PostgreSQL. Run `alembic upgrade head` before starting the API. Check for model/migration drift with `alembic check` after applying migrations. Create new reviewed revisions with `alembic revision --autogenerate -m "describe change"`, inspect the generated SQL, and commit the revision. Never edit an already-applied migration; add a new revision instead.

Set `ENVIRONMENT=production`, `DATABASE_URL` to managed PostgreSQL, and `CORS_ORIGINS` to the exact HTTPS frontend origin(s). Do not deploy with a SQLite file or use a demo database for real inventory. Configure HTTPS, managed secrets, backups, monitoring, rate limiting, and an authorised facility inventory source before a pilot.

No real facilities or stock are fabricated by this API. Demo records are excluded from availability search by default. Feedback is a review signal and does not change stock. Do not store patient diagnoses, prescriptions, identity documents, or unnecessary sensitive health information. Users must confirm availability directly with the facility. MediReach does not diagnose, prescribe, or recommend medicine substitutions.
