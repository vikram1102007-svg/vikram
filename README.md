# MediReach

MediReach is a medicine-availability information platform designed to help people check reported stock at health centres before travelling.

## Project
- Frontend demo: [MediReach](./MediReach/)
- FastAPI backend: [backend README](./MediReach/backend/README.md)
- API documentation when running locally: http://127.0.0.1:8000/docs

## Safety and data integrity
Availability is informational, time-sensitive, and must be confirmed directly with the facility. Demo data must remain clearly labelled. Patient feedback creates a review signal and never silently changes inventory. MediReach does not diagnose, prescribe, or recommend medicine substitutions.

## Current status
The repository contains a static frontend demo and a FastAPI backend foundation. A real production deployment still requires a managed database, secure secrets, authenticated facility staff, an authorised facility inventory source, migrations, backups, monitoring, and frontend-to-API integration.
