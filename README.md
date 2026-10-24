# Koya clinic booking challenge

Two independent Vercel projects share one repository:

- `backend/` — FastAPI and Neon PostgreSQL. The API is the source of truth.
- `frontend/` — Next.js booking page. Its server route forwards requests to the API, so the API key never appears in browser code.

The database enforces one confirmed booking per slot with a partial unique index. Each booking attempt runs in a transaction, so concurrent requests cannot both reserve the same slot. A unique idempotency key prevents duplicate bookings on retries. A database backed sliding window rate limit returns `429` with `Retry-After` after five booking attempts per email per minute.

## Run locally

1. At [Neon Console](https://console.neon.tech), create a project. Open **Connect**, enable **Pooled connection**, and copy the PostgreSQL URL (its host contains `-pooler`). Keep the database password private.
2. Copy `backend/.env.example` to `backend/.env` and set `DATABASE_URL` and a long random `API_KEY`.
3. Copy `frontend/.env.example` to `frontend/.env.local`. Set the same `API_KEY`; keep `BACKEND_URL=http://127.0.0.1:8000`.
4. Start the backend:

   ```bash
   cd backend
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app:app --reload
   ```

5. Start the frontend in another terminal:

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

Visit `http://localhost:3000`. Tables are created automatically on first use. On a fresh database, the first `GET /slots` creates two weeks of weekday sample appointments. `POST /reset` replaces those slots and deletes every booking, including when the supplied array is empty. After reset, sample appointments do not reappear.

Generate an API key with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Put that same value in both local environment files and later in both Vercel projects. Never commit either environment file.

For a disposable database with no existing bookings, run the live contract check with `pip install -r backend/requirements-dev.txt` followed by `python backend/tests/live_smoke.py`. It exercises `/reset` and restores the original slots when finished. It refuses to start if any bookings already exist.

## API

Send `X-API-Key: <secret>` on every booking endpoint, including `/reset`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/reset` | Replace slots with `{ "slots": [{ "id", "provider", "start", "end" }] }` |
| `GET` | `/slots?provider=...` | List slots and availability, optionally filtered by exact provider |
| `POST` | `/bookings` | Book with `{ "slot_id", "name", "email" }`; accepts `Idempotency-Key` |
| `GET` | `/bookings/{id}` | Look up a booking |
| `DELETE` | `/bookings/{id}` | Cancel a booking |
| `GET` | `/bookings?email=...&limit=10&cursor=...` | Page through a person's bookings |
| `GET` | `/health` | Database health check |

Interactive API documentation is at `/docs`. Errors have the shape `{ "error": "message" }`.

## Deploy to Vercel

1. Push the code to your Git repository, then [import it in Vercel](https://vercel.com/new) twice. Set the first project's root directory to `backend` and the second to `frontend`.
2. In the backend project, set `DATABASE_URL` to Neon's pooled connection string and set `API_KEY` to a strong random value. FastAPI's `app` is exported from `backend/app.py`, which Vercel detects automatically.
3. Deploy the backend and check `https://<backend-domain>/health`.
4. In the frontend project, set `BACKEND_URL=https://<backend-domain>` and the same `API_KEY`. Do not prefix the key with `NEXT_PUBLIC_`.
5. Deploy the frontend. Open the page, choose a slot, book it, and confirm that the booking still appears after a reload.

Do not use an ephemeral SQLite database on Vercel. Neon holds slots, bookings, rate counters, and idempotency keys across function invocations. Keep both Vercel projects and the Neon database active after submitting the URLs.

## Notes

The assessment screenshots in this repository document the response shapes and behavior. Pagination returns bookings oldest first with case insensitive email matching; pass `next_cursor` back as `cursor` for the next page.
