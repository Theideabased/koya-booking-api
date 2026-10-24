import asyncio
import sys
from pathlib import Path

import pytest
from starlette.requests import Request
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import BookingInput, ResetInput, protect_api  # noqa: E402


def test_api_key_is_required_before_database_access(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret")
    request = Request({"type": "http", "method": "GET", "path": "/slots", "headers": [], "query_string": b""})
    response = asyncio.run(protect_api(request, lambda _: None))
    assert response.status_code == 401
    wrong = Request({"type": "http", "method": "POST", "path": "/reset", "headers": [(b"x-api-key", b"wrong")], "query_string": b""})
    response = asyncio.run(protect_api(wrong, lambda _: None))
    assert response.status_code == 401
    assert response.body.decode() == '{"error":"Missing or invalid API key"}'


def test_booking_details_are_validated():
    with pytest.raises(ValidationError):
        BookingInput(slot_id="s1", name=" ", email="ada@example.com")
    with pytest.raises(ValidationError):
        BookingInput(slot_id="s1", name="Ada Obi", email="not-an-email")
    booking = BookingInput(slot_id="s1", name="Ada Obi", email="ada@example.com")
    assert booking.slot_id == "s1"


def test_reset_allows_past_slots_but_rejects_backwards_times():
    past = ResetInput.model_validate({"slots": [{
        "id": "s1", "provider": "Dr Ade",
        "start": "2020-01-01T09:00:00Z", "end": "2020-01-01T09:30:00Z",
    }]})
    assert past.slots[0].id == "s1"
    with pytest.raises(ValidationError):
        ResetInput.model_validate({"slots": [{
            "id": "s1", "provider": "Dr Ade",
            "start": "2026-12-10T10:00:00Z", "end": "2026-12-10T09:00:00Z",
        }]})
