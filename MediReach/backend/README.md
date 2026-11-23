# MediReach FastAPI backend

A FastAPI API foundation using SQLAlchemy 2, SQLite for local tests/development, and PostgreSQL when DATABASE_URL is configured.

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

## Facility staff inventory updates

- PUT /api/v1/facilities/me/inventory — updates only the facility bound to the supplied X-Facility-Key credential.
- GET /api/v1/facilities/me/feedback?limit=50 — authenticated, facility-scoped pending feedback review queue; supports `before_id` pagination and omits free-text comments from staff responses.

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

Alembic manages the schema for both local SQLite and production PostgreSQL. Run `alembic upgrade head` before starting the API; the application does not create or modify tables automatically at startup. Check for model/migration drift with `alembic check` after applying migrations. Create new reviewed revisions with `alembic revision --autogenerate -m \"describe change\"`, inspect the generated SQL, and commit the revision. Never edit an already-applied migration; add a new revision instead.

Set DATABASE_URL to managed PostgreSQL and CORS_ORIGINS to the exact frontend origin(s). Do not deploy with a SQLite file or use a demo database for real inventory. Configure HTTPS, managed secrets, backups, monitoring, rate limiting, and an authorised facility inventory source before a pilot.

No real facilities or stock are fabricated by this API. Demo records are excluded from availability search by default. Feedback is a review signal and does not change stock. Do not store patient diagnoses, prescriptions, identity documents, or unnecessary sensitive health information. Users must confirm availability directly with the facility. MediReach does not diagnose, prescribe, or recommend medicine substitutions.
