# MediReach

Medicine-availability information project with a static responsive frontend demo and a FastAPI backend foundation.

## Project structure

- `index.html`, `styles.css`, `app.js` — static frontend demo
- `backend/` — FastAPI API, SQLAlchemy models, facility-scoped inventory credentials, audit logging, and API tests

## Run the frontend

Open `index.html` in a browser. The current frontend still uses fictional sample records and is not connected to the API.

## Run the backend locally

See [backend README](backend/README.md). The backend supports PostgreSQL through SQLAlchemy and SQLite for local development/tests.

## Safety and production status

Facility names, addresses, stock levels and timestamps in the frontend are fictional sample data. Google Maps links search sample address text and are not verified facility locations. The backend is not yet deployed or connected to a production database. No government inventory system, SMS/IVR service or authorised facility data source is connected.

Availability is informational and must be confirmed with the facility. Patient feedback creates a review signal and never changes stock. MediReach does not diagnose, prescribe or recommend medicine substitutions. Do not enter personal health information in feedback.
