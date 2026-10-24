CREATE TABLE IF NOT EXISTS slots (
    id text PRIMARY KEY,
    provider text NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    CHECK (ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS bookings (
    id uuid PRIMARY KEY,
    slot_id text NOT NULL REFERENCES slots(id),
    patient_name text NOT NULL,
    patient_email text NOT NULL,
    patient_phone text,
    status text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    idempotency_key text UNIQUE,
    request_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS one_confirmed_booking_per_slot
    ON bookings(slot_id) WHERE status = 'confirmed';
CREATE INDEX IF NOT EXISTS bookings_email_page
    ON bookings(patient_email, created_at ASC, id ASC);

CREATE TABLE IF NOT EXISTS booking_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email_hash text NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS booking_attempts_email_time ON booking_attempts(email_hash, attempted_at);

CREATE TABLE IF NOT EXISTS app_state (
    key text PRIMARY KEY,
    value text NOT NULL
);
