# MediReach

Medicine-availability information project with a responsive static frontend and a FastAPI backend foundation.

## Project structure

- `index.html`, `styles.css`, `app.js` — static bilingual frontend
- `freshness.js` — timestamp-based, rule-based freshness labels
- `locales.js` — English and Tamil interface translations
- `api.js` — optional read-only availability API client
- `results.js` — client-side filtering by reported stock/freshness and verification-time sorting
- `backend/` — FastAPI API, SQLAlchemy models, facility-scoped inventory credentials, audit logging, migrations, and tests
- `tests/frontend.test.cjs` — frontend unit tests run through the backend pytest suite

## Run the frontend

Open `index.html` in a browser. With the API base URL left blank, the frontend displays clearly labelled fictional sample records only.

To connect a deployed API, set the `content` value of this meta tag in `index.html` to the API's HTTPS origin:

```html
<meta name="medireach-api-base" content="https://your-api.example">
```

The frontend calls the public read-only endpoint `GET /api/v1/availability?medicine=...` and optionally sends `district=...`. The API must allow the exact Embarko frontend origin in its CORS configuration. Do not put database URLs, facility keys, or any other secrets in frontend files.

If the API URL is configured but the request fails, the UI shows an error and does **not** silently substitute fictional demo results. Remote API URLs must use HTTPS; plain HTTP is accepted only for localhost development.

## Interactive search

After a search, the results can be filtered by reported stock status and verification freshness, then sorted by last-verified time. These controls operate on the current response in the browser and do not make another API request. Changing filters never changes inventory or the API's confidence label. Invalid or missing timestamps remain in the confirmation category and sort after valid timestamps.

## Vercel deployment architecture

The current frontend is a static, interactive website and can be deployed as a Vercel project from the `MediReach` directory. The FastAPI backend and PostgreSQL database are separate services until a supported serverless entrypoint, database connection, migrations, and health checks are configured. Do not deploy facility keys or database credentials to the frontend. Configure a public HTTPS API origin only after the backend is deployed and `/health/ready` is verified.

## Freshness and safety behaviour

Freshness is calculated from the actual `verified_at` timestamp, not a hardcoded age:

- Up to 24 hours: Recently verified
- More than 24 and up to 72 hours: Needs confirmation
- More than 72 hours: Outdated
- Missing, invalid, timezone-less, or materially future timestamps: Needs confirmation

The UI displays the last-verified time and labels all sample records as fictional. Sample timestamps are fixed examples and become less fresh as time passes. The API's `is_demo` flag is also displayed on any demo record returned by a configured API.

The frontend uses DOM text nodes for API content rather than injecting API strings as HTML. Availability requests are read-only, omit credentials, and do not collect patient identity or health information.

## Run the backend locally

See [backend README](backend/README.md). The backend supports PostgreSQL through SQLAlchemy and SQLite for local development/tests.

## Tests

From `MediReach/backend`:

```bash
pytest -q
```

The pytest suite invokes the Node.js frontend tests when Node.js is available. Run the frontend tests directly from the `MediReach` directory with:

```bash
node --test tests/frontend.test.cjs
```

## Production status

The backend is not yet deployed or connected to a production database. No government inventory system, SMS/IVR service, or authorised facility data source is connected. The current static frontend uses fictional demo data unless an API URL is explicitly configured and successfully responds.

Availability is informational and must be confirmed with the facility. Patient feedback creates a review signal and never changes stock. MediReach does not diagnose, prescribe, or recommend medicine substitutions. Do not enter personal health information in feedback.

## API connection readiness

When the HTTPS API origin is configured in the `medireach-api-base` meta tag, the page initialises a bilingual connection indicator. It makes a read-only `GET /health/ready` request with an 8-second timeout, `credentials: omit`, and `cache: no-store`. If the request fails or the response does not report `status: "ready"`, the indicator shows the API/database as unavailable and offers a retry. It never replaces failed API results with fictional sample inventory.

The readiness endpoint checks database connectivity and that the deployed database is at the packaged Alembic migration head. A ready response **does not mean that a facility has verified a medicine or that any stock is available**. Availability records still show their own verification timestamp and rule-based freshness label, and must be confirmed with the facility.

The indicator is hidden when the API origin is blank (demo mode) or invalid. For a production connection, configure the backend's `CORS_ORIGINS` with the exact origin `https://medireach-platform.embarko.app` (no path or trailing slash). Keep the API origin public and non-secret; never put a facility key or database credential in the static frontend.
