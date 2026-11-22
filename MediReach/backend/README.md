# MediReach FastAPI backend

A production-oriented API foundation using FastAPI, SQLAlchemy 2, SQLite for local development, and PostgreSQL when DATABASE_URL is configured.

## Local run
```bash
cd MediReach/backend
python -m venv .venv
# activate the environment
pip install -r requirements.txt
cp .env.example .env
# For local development set DATABASE_URL=sqlite:///./medireach.db
uvicorn app.main:app --reload
```
API docs: http://127.0.0.1:8000/docs. Health: /health.

## Endpoints
- GET /api/v1/medicines?q= — medicine catalogue
- GET /api/v1/facilities?district= — active facilities
- GET /api/v1/availability?medicine=&district=&include_demo=false — availability and server-calculated freshness
- POST /api/v1/feedback — records a patient feedback review signal; never changes inventory
- PUT /api/v1/admin/inventory — admin-only update using X-Admin-Key

## Before production
Set DATABASE_URL to managed PostgreSQL, ADMIN_API_KEY to a long random secret, and CORS_ORIGINS to the exact frontend origins. Do not use the example key. Add Alembic migrations, managed secrets, HTTPS, backups, monitoring, rate limiting, and an authorised facility inventory source. No real facilities or stock are fabricated by this API.

## Data safeguards
Only authorised facility operators should update inventory. Feedback is a review signal and does not change stock. Demo records are excluded by default. Confirm availability with the facility. Do not store patient diagnoses, prescriptions, identity documents, or unnecessary sensitive health information.