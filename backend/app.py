"""Clinic booking API. PostgreSQL constraints are the final concurrency guard."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

TZ = ZoneInfo("Africa/Lagos")
load_dotenv(Path(__file__).with_name(".env"))
SCHEMA = Path(__file__).with_name("schema.sql").read_text()
SLOT_HOURS = (9, 10, 11, 14, 15)
RATE_LIMIT = 5

app = FastAPI(title="Koya Clinic Booking API", version="1.0.0")


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    issue = exc.errors()[0]
    return JSONResponse({"error": f"Invalid {issue['loc'][-1]}: {issue['msg']}"}, status_code=400)


@app.middleware("http")
async def protect_api(request: Request, call_next):
    if request.url.path in ("/slots", "/reset") or request.url.path.startswith("/bookings"):
        expected = os.getenv("API_KEY")
        supplied = request.headers.get("x-api-key")
        if not expected:
            return JSONResponse({"error": "API key is not configured"}, status_code=503)
        if not supplied or not hmac.compare_digest(supplied, expected):
            return JSONResponse({"error": "Missing or invalid API key"}, status_code=401)
        if request.url.path == "/bookings" and request.method == "POST":
            try:
                raw = await request.json()
                email = raw.get("email") if isinstance(raw, dict) else None
                if isinstance(email, str) and email.strip():
                    initialize_database()
                    with psycopg.connect(database_url(), row_factory=dict_row, prepare_threshold=None) as conn:
                        actor = hashlib.sha256(email.strip().lower().encode()).hexdigest()
                        check_rate_limit(conn, actor)
            except psycopg.OperationalError:
                return JSONResponse({"error": "Database temporarily unavailable"}, status_code=503)
            except HTTPException as exc:
                return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            except ValueError:
                pass  # FastAPI reports malformed JSON as a 400 below.
    return await call_next(request)


class BookingInput(BaseModel):
    slot_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def trim_email(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a valid patient name")
        return value



class ResetSlot(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=200)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def valid_time(self):
        if not self.start.tzinfo or not self.end.tzinfo or self.end <= self.start:
            raise ValueError("Slot requires valid timezone-aware start and end")
        return self


class ResetInput(BaseModel):
    slots: list[ResetSlot]


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise HTTPException(503, "Database is not configured")
    return value


@lru_cache(maxsize=1)
def initialize_database() -> bool:
    with psycopg.connect(database_url(), prepare_threshold=None) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(1865905521)")
        conn.execute(SCHEMA)
    return True


def connection():
    try:
        initialize_database()
        with psycopg.connect(database_url(), row_factory=dict_row, prepare_threshold=None) as conn:
            yield conn
    except psycopg.OperationalError as exc:
        raise HTTPException(503, "Database temporarily unavailable") from exc


def require_key(x_api_key: str | None = Header(default=None)) -> str:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "API key is not configured")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Missing or invalid API key")
    return x_api_key


def check_rate_limit(conn: psycopg.Connection, actor: str) -> None:
    # Transaction-level advisory lock keeps the check and insert atomic across functions.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (actor,))
    row = conn.execute(
        """SELECT count(*) AS request_count,
                  ceil(extract(epoch FROM (min(attempted_at) + interval '1 minute' - now())))::int AS retry_after
           FROM booking_attempts
           WHERE email_hash = %s AND attempted_at > now() - interval '1 minute'""",
        (actor,),
    ).fetchone()
    if row["request_count"] >= RATE_LIMIT:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": str(max(1, row["retry_after"]))})
    conn.execute("INSERT INTO booking_attempts(email_hash) VALUES (%s)", (actor,))


def slot_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "start": iso(row["starts_at"]),
        "end": iso(row["ends_at"]),
        "available": row["available"],
    }


def booking_dict(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "slot_id": row["slot_id"],
        "name": row["patient_name"],
        "email": row["patient_email"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
    }


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def seed_slots(conn: psycopg.Connection) -> None:
    conn.execute("INSERT INTO app_state(key, value) VALUES ('bootstrapped', 'false') ON CONFLICT DO NOTHING")
    state = conn.execute("SELECT value FROM app_state WHERE key = 'bootstrapped' FOR UPDATE").fetchone()
    if state["value"] == "true":
        return
    today = datetime.now(TZ).date()
    values = []
    for offset in range(14):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for hour in SLOT_HOURS:
            start = datetime(day.year, day.month, day.day, hour, tzinfo=TZ)
            if start <= datetime.now(TZ):
                continue
            end = start + timedelta(hours=1)
            slot_id = uuid5(NAMESPACE_URL, f"koya-clinic:{start.isoformat()}")
            values.append((str(slot_id), "Koya Clinic", start, end))
    if values:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO slots(id, provider, starts_at, ends_at) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                values,
            )
    conn.execute("UPDATE app_state SET value = 'true' WHERE key = 'bootstrapped'")


@app.post("/reset")
def reset(body: ResetInput, conn=Depends(connection), api_key: str = Depends(require_key)):
    if len({slot.id for slot in body.slots}) != len(body.slots):
        raise HTTPException(400, "Duplicate slot id")
    # A single transaction makes reset atomic for concurrent requests.
    conn.execute("DELETE FROM bookings")
    conn.execute("DELETE FROM slots")
    conn.execute("DELETE FROM booking_attempts")
    for slot in body.slots:
        conn.execute(
            "INSERT INTO slots(id, provider, starts_at, ends_at) VALUES (%s, %s, %s, %s)",
            (slot.id, slot.provider, slot.start, slot.end),
        )
    conn.execute("INSERT INTO app_state(key, value) VALUES ('bootstrapped', 'true') ON CONFLICT (key) DO UPDATE SET value = 'true'")
    return {"ok": True}


@app.get("/health")
def health(conn=Depends(connection)):
    conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/slots")
def list_slots(request: Request, conn=Depends(connection), api_key: str = Depends(require_key)):
    seed_slots(conn)
    provider = request.query_params.get("provider")
    query = """SELECT s.*, (b.id IS NULL AND s.starts_at > now()) AS available
               FROM slots s LEFT JOIN bookings b
                 ON b.slot_id = s.id AND b.status = 'confirmed'"""
    if provider is None:
        rows = conn.execute(query + " ORDER BY s.starts_at").fetchall()
    else:
        rows = conn.execute(query + " WHERE s.provider = %s ORDER BY s.starts_at", (provider,)).fetchall()
    return {"slots": [slot_dict(row) for row in rows]}


@app.post("/bookings", status_code=201)
def create_booking(
    body: BookingInput,
    request: Request,
    conn=Depends(connection),
    api_key: str = Depends(require_key),
    idempotency_key: str | None = Header(default=None),
):
    if idempotency_key is not None and not (1 <= len(idempotency_key) <= 200):
        raise HTTPException(400, "Invalid Idempotency-Key")
    email = str(body.email).lower()
    fingerprint = hashlib.sha256(
        f"{body.slot_id}|{body.name}|{email}".encode()
    ).hexdigest()
    if idempotency_key:
        existing = conn.execute("SELECT * FROM bookings WHERE idempotency_key = %s", (idempotency_key,)).fetchone()
        if existing:
            if existing["request_hash"] != fingerprint:
                raise HTTPException(422, "Idempotency-Key was used with different details")
            replay = booking_dict(existing)
            replay["status"] = "confirmed"
            return JSONResponse(replay, status_code=201)
    slot = conn.execute("SELECT id, starts_at FROM slots WHERE id = %s", (body.slot_id,)).fetchone()
    if slot is None:
        raise HTTPException(404, "slot not found")
    if slot["starts_at"] <= datetime.now(slot["starts_at"].tzinfo):
        raise HTTPException(400, "slot has already started")
    booking = conn.execute(
        """INSERT INTO bookings
           (id, slot_id, patient_name, patient_email, idempotency_key, request_hash)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING *""",
        (uuid4(), body.slot_id, body.name, email, idempotency_key, fingerprint),
    ).fetchone()
    if booking is None:
        if idempotency_key:
            existing = conn.execute("SELECT * FROM bookings WHERE idempotency_key = %s", (idempotency_key,)).fetchone()
            if existing:
                if existing["request_hash"] != fingerprint:
                    raise HTTPException(422, "Idempotency-Key was used with different details")
                replay = booking_dict(existing)
                replay["status"] = "confirmed"
                return JSONResponse(replay, status_code=201)
        raise HTTPException(409, "Slot is already booked")
    return booking_dict(booking)


@app.get("/bookings/{booking_id}")
def get_booking(booking_id: str, conn=Depends(connection), api_key: str = Depends(require_key)):
    try:
        parsed_id = UUID(booking_id)
    except ValueError as exc:
        raise HTTPException(404, "Booking not found") from exc
    row = conn.execute("SELECT * FROM bookings WHERE id = %s", (parsed_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Booking not found")
    return booking_dict(row)


@app.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: str, conn=Depends(connection), api_key: str = Depends(require_key)):
    try:
        parsed_id = UUID(booking_id)
    except ValueError as exc:
        raise HTTPException(404, "Booking not found") from exc
    row = conn.execute(
        """UPDATE bookings SET status = 'cancelled', cancelled_at = now()
           WHERE id = %s AND status = 'confirmed' RETURNING *""",
        (parsed_id,),
    ).fetchone()
    if row:
        return booking_dict(row)
    existing = conn.execute("SELECT id FROM bookings WHERE id = %s", (parsed_id,)).fetchone()
    if not existing:
        raise HTTPException(404, "Booking not found")
    raise HTTPException(409, "Booking is already cancelled")


@app.get("/bookings")
def list_bookings(
    email: EmailStr,
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = None,
    conn=Depends(connection),
    api_key: str = Depends(require_key),
):
    after = None
    if cursor:
        try:
            stamp, uid = cursor.split("|", 1)
            after = (datetime.fromisoformat(stamp), UUID(uid))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Invalid cursor") from exc
    if after:
        rows = conn.execute(
            """SELECT * FROM bookings WHERE patient_email = %s
               AND (created_at, id) > (%s, %s)
               ORDER BY created_at ASC, id ASC LIMIT %s""",
            (str(email).lower(), after[0], after[1], limit + 1),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM bookings WHERE patient_email = %s
               ORDER BY created_at ASC, id ASC LIMIT %s""",
            (str(email).lower(), limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = f"{rows[-1]['created_at'].isoformat()}|{rows[-1]['id']}" if has_more else None
    return {"bookings": [booking_dict(row) for row in rows], "next_cursor": next_cursor}
