"""Run against a disposable Neon database: python tests/live_smoke.py.

This script calls /reset and restores the original slots when it finishes.
It refuses to start if the database already contains bookings.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, database_url  # noqa: E402
import os  # noqa: E402


def main():
    key = os.environ["API_KEY"]
    headers = {"X-API-Key": key}
    with psycopg.connect(database_url(), connect_timeout=5, prepare_threshold=None) as conn:
        count = conn.execute("SELECT count(*) FROM bookings").fetchone()[0]
    if count:
        raise SystemExit("Refusing to reset a database with existing bookings")

    with TestClient(app) as client:
        assert client.get("/slots").status_code == 401
        original = client.get("/slots", headers=headers).json()["slots"]
        original = [{key: slot[key] for key in ("id", "provider", "start", "end")} for slot in original]

        def slot(slot_id, provider, hours):
            start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
            return {"id": slot_id, "provider": provider, "start": start.isoformat(),
                    "end": (start + timedelta(minutes=30)).isoformat()}

        slots = [slot(f"test-{i}", "Dr Ade" if i % 2 else "Dr Obi", 48 + i) for i in range(1, 6)]
        slots.append(slot("test-past", "Dr Ade", -24))
        try:
            assert client.post("/reset", headers=headers, json={"slots": slots}).status_code == 200
            listed = client.get("/slots", headers=headers).json()["slots"]
            assert [item["id"] for item in listed] == ["test-past", "test-1", "test-2", "test-3", "test-4", "test-5"]
            assert len(client.get("/slots?provider=Dr%20Ade", headers=headers).json()["slots"]) == 4
            assert listed[0]["available"] is False

            assert client.post("/bookings", headers=headers, json={"name": "Ada", "email": "missing@example.com"}).status_code == 400
            assert client.post("/bookings", headers=headers, json={"slot_id": "test-1", "name": "Ada", "email": "bad"}).status_code == 400
            assert client.post("/bookings", headers=headers, json={"slot_id": "test-past", "name": "Ada", "email": "past@example.com"}).status_code == 400
            assert client.post("/bookings", headers=headers, json={"slot_id": "unknown", "name": "Ada", "email": "unknown@example.com"}).status_code == 404

            body = {"slot_id": "test-1", "name": " Ada Obi ", "email": " Ada@Example.com "}
            with_key = {**headers, "Idempotency-Key": "smoke-" + str(uuid4())}
            first = client.post("/bookings", headers=with_key, json=body)
            assert first.status_code == 201, first.text
            booked = first.json()
            assert booked["name"] == "Ada Obi" and booked["email"] == "ada@example.com"
            replay = client.post("/bookings", headers=with_key, json=body)
            assert replay.status_code == 201 and replay.json() == booked
            different = client.post("/bookings", headers=with_key, json={**body, "name": "Different"})
            assert different.status_code == 422
            conflict = client.post("/bookings", headers=headers, json={"slot_id": "test-1", "name": "Other", "email": "other@example.com"})
            assert conflict.status_code == 409
            assert client.get(f"/bookings/{booked['id']}", headers=headers).json() == booked
            cancelled = client.delete(f"/bookings/{booked['id']}", headers=headers)
            assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
            assert client.delete(f"/bookings/{booked['id']}", headers=headers).status_code == 409
            assert client.post("/bookings", headers=headers, json={"slot_id": "test-1", "name": "Other", "email": "other@example.com"}).status_code == 201

            for i in (2, 3, 4):
                assert client.post("/bookings", headers=headers, json={"slot_id": f"test-{i}", "name": "Page", "email": "PAGE@example.com"}).status_code == 201
            page1 = client.get("/bookings", headers=headers, params={"email": "page@EXAMPLE.com", "limit": 2}).json()
            assert len(page1["bookings"]) == 2 and page1["next_cursor"]
            page2 = client.get("/bookings", headers=headers, params={"email": "page@example.com", "limit": 2, "cursor": page1["next_cursor"]}).json()
            assert len(page2["bookings"]) == 1 and page2["next_cursor"] is None
            assert client.get("/bookings", headers=headers, params={"email": "page@example.com", "limit": 51}).status_code == 400

            for _ in range(5):
                assert client.post("/bookings", headers=headers, json={"slot_id": "missing", "name": "Rate", "email": "rate@example.com"}).status_code == 404
            limited = client.post("/bookings", headers=headers, json={"slot_id": "missing", "name": "Rate", "email": "rate@example.com"})
            assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
            assert client.post("/bookings", headers=headers, json={"slot_id": "missing", "name": "Other", "email": "different@example.com"}).status_code == 404

            assert client.post("/reset", headers=headers, json={"slots": [slot("race", "Dr Ade", 72)]}).status_code == 200
            def race(email):
                return client.post("/bookings", headers=headers, json={"slot_id": "race", "name": "Race", "email": email}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(race, ["race1@example.com", "race2@example.com"]))
            assert sorted(results) == [201, 409], results
            print("Live API smoke test passed")
        finally:
            restored = client.post("/reset", headers=headers, json={"slots": original})
            assert restored.status_code == 200, restored.text


if __name__ == "__main__":
    main()
