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

API docs: http://127.0.0.1:8000/docs.

- `GET /health` is a liveness probe and does not require the database.
- `GET /health/ready` executes `SELECT 1` and confirms the connected database is stamped at every Alembic migration head packaged with this API. It returns a generic HTTP 503 if the database is unavailable, has no migration history, or is behind/ahead of the packaged migration graph. It never returns connection details.
- Run reviewed migrations as a release step before routing traffic to a new API version.

## Public endpoints

- GET /api/v1/medicines?q= — medicine catalogue
- GET /api/v1/facilities?district= — active facilities
- GET /api/v1/availability?medicine=&district=&include_demo=false — availability and server-calculated freshness
- POST /api/v1/feedback — records a patient feedback review signal; never changes inventory
- GET /api/v1/facilities/me/audit — authenticated, facility-scoped inventory audit history with cursor pagination
- GET /api/v1/facilities/me/feedback — authenticated, facility-scoped pending feedback queue with cursor pagination
- PATCH /api/v1/facilities/me/feedback/{feedback_id}/review — acknowledges a feedback signal without changing stock

Feedback accepts only an inventory record ID and a structured outcome (`received` or `not_available`). Free-text fields are rejected at the API boundary to avoid collecting unnecessary personal or health information. Feedback is a review signal only and never changes inventory.

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

Inventory updates lock an existing facility/medicine row with `SELECT ... FOR UPDATE` so concurrent PostgreSQL updates are serialized and each audit event records the immediately preceding committed values. When two staff requests create the same pair simultaneously, the database's `uq_facility_medicine` constraint selects one insert; the losing request rolls back, locks the newly created row, and records its own payload as an update. The inventory change and its audit event commit in the same transaction. SQLite is used for local tests only and does not provide the same row-locking guarantee; production concurrency behaviour must be verified against the managed PostgreSQL service before a pilot.

## Container image

The backend image includes the application, Alembic configuration, and migration scripts. It runs as an unprivileged `app` user. The `.dockerignore` file excludes environment files, local databases, virtual environments, and Git metadata from the build context.

From `MediReach/backend`:

```bash
docker build -t medireach-api .
# Apply reviewed migrations as a separate release step:
docker run --rm --env-file .env medireach-api alembic upgrade head
# Start the API with the same managed environment:
docker run --rm -p 8000:8000 --env-file .env medireach-api
```

Do not bake production secrets or a `.env` file into the image. Configure production environment variables through the hosting platform's secret manager. The Dockerfile packaging is covered by CI contract tests; an actual image build must still be performed in a Docker-capable environment before deployment.

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


## Availability freshness

The API calculates confidence from the stored `verified_at` timestamp:

- Up to and including 24 hours old: `Recently Verified`
- More than 24 and up to 72 hours old: `Needs Confirmation`
- More than 72 hours old: `Outdated`
- More than five minutes in the future: `Needs Confirmation`

A five-minute future-clock tolerance accounts for small clock skew only. SQLite may return timezone-naive values for timezone-aware columns; MediReach treats these as UTC because application writes use UTC and returns timezone-aware UTC timestamps to clients.

## Facility audit history and feedback review

All facility staff endpoints derive their facility scope from the authenticated `X-Facility-Key`; clients cannot supply a facility ID to select another facility.

- The audit history returns only audit events whose audit row and inventory record both belong to the authenticated facility.
- Audit and feedback queues use descending ID cursors (`before_id`) and a bounded page size of 1–100.
- The feedback queue returns only pending signals for non-demo inventory. It omits free-text fields.
- `PATCH /api/v1/facilities/me/feedback/{feedback_id}/review` records the first review timestamp and the access-key record that acknowledged it. Repeated acknowledgements are idempotent.
- Acknowledgement changes only review metadata. Inventory status, quantity and verification time remain unchanged.
- The additive `0002_feedback_review` migration keeps existing feedback rows and leaves their review metadata null until staff review them. Apply `alembic upgrade head` before deploying the updated API.
