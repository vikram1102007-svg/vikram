import hashlib

import pytest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import (
    _inventory_record_lock_query,
    app,
    freshness,
    persist_facility_inventory_update,
)
from app.schemas import InventoryUpsert
from app.models import (
    AvailabilityFeedback,
    Facility,
    FacilityAccessKey,
    InventoryAuditLog,
    InventoryRecord,
    Medicine,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def setup_record():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    facility = Facility(
        name="Test PHC",
        district="Test District",
        address="Test address",
        is_active=True,
    )
    medicine = Medicine(name="Paracetamol", strength="500 mg", form="tablet")
    db.add_all([facility, medicine])
    db.commit()
    db.refresh(facility)
    db.refresh(medicine)
    record = InventoryRecord(
        facility_id=facility.id,
        medicine_id=medicine.id,
        status="available",
        quantity=20,
        verified_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    ids = (facility.id, medicine.id, record.id)
    db.close()
    return ids


def add_facility_key(facility_id: int, token: str, revoked: bool = False):
    db = TestingSession()
    key = FacilityAccessKey(
        facility_id=facility_id,
        key_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db.add(key)
    db.commit()
    db.close()


def test_health():
    assert client.get("/health").status_code == 200


def test_availability_search_returns_freshness():
    setup_record()
    response = client.get("/api/v1/availability", params={"medicine": "Para"})
    assert response.status_code == 200
    assert response.json()[0]["confidence"] == "Recently Verified"


def test_api_responses_disable_caching_for_public_and_staff_data():
    facility_id, _, _ = setup_record()

    availability = client.get(
        "/api/v1/availability",
        params={"medicine": "Para"},
    )
    assert availability.status_code == 200
    assert availability.headers["cache-control"] == "no-store"
    assert availability.headers["pragma"] == "no-cache"

    unauthenticated = client.get("/api/v1/facilities/me/audit")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "no-store"

    token = "api-no-store-staff-response-test-key"
    add_facility_key(facility_id, token)
    staff_queue = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token},
    )
    assert staff_queue.status_code == 200
    assert staff_queue.json() == []
    assert staff_queue.headers["cache-control"] == "no-store"
    assert staff_queue.headers["pragma"] == "no-cache"


def test_feedback_does_not_change_inventory_and_creates_review_signal():
    _, _, record_id = setup_record()
    response = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_id, "outcome": "not_available"},
    )
    assert response.status_code == 201
    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    feedback = db.scalar(
        select(AvailabilityFeedback).where(
            AvailabilityFeedback.inventory_record_id == record_id
        )
    )
    assert record.status == "available" and record.quantity == 20
    assert feedback is not None and feedback.review_required is True
    db.close()


def test_facility_inventory_requires_credentials():
    _, medicine_id, _ = setup_record()
    response = client.put(
        "/api/v1/facilities/me/inventory",
        json={"medicine_id": medicine_id, "status": "available", "quantity": 5},
    )
    assert response.status_code == 401


def test_facility_inventory_update_is_scoped_and_audited():
    facility_id, medicine_id, record_id = setup_record()
    token = "test-facility-key-only-for-tests"
    add_facility_key(facility_id, token)
    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": "low_stock", "quantity": 7},
    )
    assert response.status_code == 200

    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    audit = db.scalar(
        select(InventoryAuditLog).where(
            InventoryAuditLog.inventory_record_id == record_id
        )
    )
    assert record.status == "low_stock" and record.quantity == 7
    assert audit is not None
    assert audit.action == "updated"
    assert audit.previous_status == "available"
    assert audit.new_status == "low_stock"
    assert audit.previous_quantity == 20 and audit.new_quantity == 7
    assert audit.facility_id == facility_id
    assert audit.access_key_id > 0
    db.close()



def test_new_inventory_record_is_created_and_audited():
    facility_id, medicine_id, record_id = setup_record()
    db = TestingSession()
    db.delete(db.get(InventoryRecord, record_id))
    db.commit()
    db.close()

    token = "test-facility-key-for-new-record"
    add_facility_key(facility_id, token)
    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": "available", "quantity": 12},
    )
    assert response.status_code == 200

    db = TestingSession()
    record = db.scalar(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
    )
    audit = db.scalar(
        select(InventoryAuditLog).where(
            InventoryAuditLog.inventory_record_id == record.id
        )
    )
    assert record is not None and record.quantity == 12
    assert audit is not None and audit.action == "created"
    assert audit.previous_status is None and audit.previous_quantity is None
    db.close()

def test_facility_key_cannot_submit_another_facility_id():
    facility_id, medicine_id, _ = setup_record()
    token = "test-facility-key-only-for-tests"
    add_facility_key(facility_id, token)
    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={
            "facility_id": facility_id + 999,
            "medicine_id": medicine_id,
            "status": "available",
            "quantity": 5,
        },
    )
    assert response.status_code == 422


def test_revoked_facility_key_is_rejected():
    facility_id, medicine_id, _ = setup_record()
    token = "revoked-facility-key-only-for-tests"
    add_facility_key(facility_id, token, revoked=True)
    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": "available", "quantity": 5},
    )
    assert response.status_code == 401


def test_invalid_inventory_quantity_is_rejected():
    facility_id, medicine_id, _ = setup_record()
    token = "test-facility-key-only-for-tests"
    add_facility_key(facility_id, token)
    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": "unavailable", "quantity": 10},
    )
    assert response.status_code == 422


def test_freshness_thresholds():
    now = datetime.now(timezone.utc)
    assert freshness(now - timedelta(hours=23, minutes=59), now) == "Recently Verified"
    assert freshness(now - timedelta(hours=24), now) == "Recently Verified"
    assert freshness(now - timedelta(hours=24, seconds=1), now) == "Needs Confirmation"
    assert freshness(now - timedelta(hours=48), now) == "Needs Confirmation"
    assert freshness(now - timedelta(hours=72), now) == "Needs Confirmation"
    assert freshness(now - timedelta(hours=72, seconds=1), now) == "Outdated"


def test_future_verification_timestamp_is_conservative():
    now = datetime.now(timezone.utc)
    assert freshness(now + timedelta(minutes=4), now) == "Recently Verified"
    assert freshness(now + timedelta(minutes=6), now) == "Needs Confirmation"


def test_sqlite_naive_timestamp_is_interpreted_as_utc():
    now = datetime.now(timezone.utc)
    naive_utc = now.replace(tzinfo=None)
    assert freshness(naive_utc, now) == "Recently Verified"


def test_availability_response_returns_timezone_aware_verification_time():
    setup_record()
    response = client.get("/api/v1/availability", params={"medicine": "Para"})
    assert response.status_code == 200
    verified_at = response.json()[0]["verified_at"]
    parsed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None

def test_facility_key_is_stored_as_hash_not_plaintext():
    facility_id, _, _ = setup_record()
    token = "high-entropy-test-token-never-store-plaintext"
    add_facility_key(facility_id, token)

    db = TestingSession()
    key = db.scalar(
        select(FacilityAccessKey).where(
            FacilityAccessKey.facility_id == facility_id
        )
    )
    assert key is not None
    assert key.key_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert key.key_hash != token
    db.close()


def test_inactive_facility_key_is_rejected():
    facility_id, medicine_id, _ = setup_record()
    token = "key-for-inactive-facility-test"
    add_facility_key(facility_id, token)

    db = TestingSession()
    facility = db.get(Facility, facility_id)
    facility.is_active = False
    db.commit()
    db.close()

    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": "available", "quantity": 5},
    )
    assert response.status_code == 401


def test_feedback_for_unknown_inventory_record_is_rejected():
    setup_record()
    response = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": 999999, "outcome": "not_available"},
    )
    assert response.status_code == 404


def test_feedback_comment_length_is_limited():
    _, _, record_id = setup_record()
    response = client.post(
        "/api/v1/feedback",
        json={
            "inventory_record_id": record_id,
            "outcome": "received",
            "comment": "x" * 501,
        },
    )
    assert response.status_code == 422


def test_feedback_for_fictional_demo_inventory_is_rejected_without_mutation():
    _, _, record_id = setup_record()
    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    record.is_demo = True
    original_status = record.status
    original_quantity = record.quantity
    db.commit()
    db.close()

    response = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_id, "outcome": "not_available"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Feedback is unavailable for fictional demo records"

    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    feedback = db.scalar(
        select(AvailabilityFeedback).where(
            AvailabilityFeedback.inventory_record_id == record_id
        )
    )
    assert record.status == original_status
    assert record.quantity == original_quantity
    assert feedback is None
    db.close()


def test_feedback_for_inactive_facility_is_rejected_without_mutation():
    facility_id, _, record_id = setup_record()
    db = TestingSession()
    facility = db.get(Facility, facility_id)
    facility.is_active = False
    db.commit()
    db.close()

    response = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_id, "outcome": "not_available"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Feedback is unavailable for inactive facilities"

    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    feedback = db.scalar(
        select(AvailabilityFeedback).where(
            AvailabilityFeedback.inventory_record_id == record_id
        )
    )
    assert record.status == "available"
    assert record.quantity == 20
    assert feedback is None
    db.close()


def test_facility_staff_cannot_overwrite_fictional_demo_inventory():
    facility_id, medicine_id, record_id = setup_record()
    token = "staff-key-for-demo-inventory-protection"
    add_facility_key(facility_id, token)

    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    record.is_demo = True
    db.commit()
    db.close()

    response = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": "low_stock", "quantity": 4},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Fictional demo inventory must be replaced by an administrator before staff updates"
    )

    db = TestingSession()
    record = db.get(InventoryRecord, record_id)
    audit = db.scalar(
        select(InventoryAuditLog).where(
            InventoryAuditLog.inventory_record_id == record_id
        )
    )
    assert record.is_demo is True
    assert record.status == "available"
    assert record.quantity == 20
    assert audit is None
    db.close()


def test_facility_audit_history_is_authenticated_scoped_and_paginated():
    facility_a_id, medicine_id, record_a_id = setup_record()
    db = TestingSession()
    facility_b = Facility(
        name="Second Test PHC",
        district="Other District",
        address="Other test address",
        is_active=True,
    )
    db.add(facility_b)
    db.commit()
    db.refresh(facility_b)
    record_b = InventoryRecord(
        facility_id=facility_b.id,
        medicine_id=medicine_id,
        status="available",
        quantity=30,
        verified_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db.add(record_b)
    db.commit()
    facility_b_id = facility_b.id
    record_b_id = record_b.id
    db.close()

    token_a = "facility-a-audit-history-test-key"
    token_b = "facility-b-audit-history-test-key"
    add_facility_key(facility_a_id, token_a)
    add_facility_key(facility_b_id, token_b)

    update_a1 = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token_a},
        json={"medicine_id": medicine_id, "status": "low_stock", "quantity": 7},
    )
    update_a2 = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token_a},
        json={"medicine_id": medicine_id, "status": "available", "quantity": 15},
    )
    update_b = client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token_b},
        json={"medicine_id": medicine_id, "status": "low_stock", "quantity": 5},
    )
    assert update_a1.status_code == update_a2.status_code == update_b.status_code == 200

    unauthenticated = client.get("/api/v1/facilities/me/audit")
    assert unauthenticated.status_code == 401

    first_page = client.get(
        "/api/v1/facilities/me/audit",
        headers={"X-Facility-Key": token_a},
        params={"limit": 1},
    )
    assert first_page.status_code == 200
    first = first_page.json()
    assert len(first) == 1
    assert first[0]["inventory_record_id"] == record_a_id
    assert first[0]["medicine_name"] == "Paracetamol"
    assert first[0]["action"] == "updated"
    assert first[0]["previous_quantity"] == 7
    assert first[0]["new_quantity"] == 15

    second_page = client.get(
        "/api/v1/facilities/me/audit",
        headers={"X-Facility-Key": token_a},
        params={"limit": 10, "before_id": first[0]["id"]},
    )
    assert second_page.status_code == 200
    assert len(second_page.json()) == 1
    assert second_page.json()[0]["inventory_record_id"] == record_a_id
    assert second_page.json()[0]["new_quantity"] == 7

    facility_b_history = client.get(
        "/api/v1/facilities/me/audit",
        headers={"X-Facility-Key": token_b},
    )
    assert facility_b_history.status_code == 200
    assert len(facility_b_history.json()) == 1
    assert facility_b_history.json()[0]["inventory_record_id"] == record_b_id

    invalid_limit = client.get(
        "/api/v1/facilities/me/audit",
        headers={"X-Facility-Key": token_a},
        params={"limit": 101},
    )
    invalid_cursor = client.get(
        "/api/v1/facilities/me/audit",
        headers={"X-Facility-Key": token_a},
        params={"before_id": 0},
    )
    assert invalid_limit.status_code == 422
    assert invalid_cursor.status_code == 422


def test_facility_feedback_review_queue_is_scoped_and_hides_comments():
    facility_a_id, medicine_id, record_a_id = setup_record()
    db = TestingSession()
    facility_b = Facility(
        name="Second Test PHC",
        district="Other District",
        address="Other test address",
        is_active=True,
    )
    db.add(facility_b)
    db.commit()
    db.refresh(facility_b)
    record_b = InventoryRecord(
        facility_id=facility_b.id,
        medicine_id=medicine_id,
        status="available",
        quantity=30,
        verified_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db.add(record_b)
    db.commit()
    record_b_id = record_b.id
    facility_b_id = facility_b.id
    db.close()

    token_a = "facility-a-feedback-queue-test-key"
    token_b = "facility-b-feedback-queue-test-key"
    add_facility_key(facility_a_id, token_a)
    add_facility_key(facility_b_id, token_b)

    feedback_a1 = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_a_id, "outcome": "not_available"},
    )
    feedback_a2 = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_a_id, "outcome": "received"},
    )
    feedback_b = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_b_id, "outcome": "not_available"},
    )
    assert feedback_a1.status_code == feedback_a2.status_code == feedback_b.status_code == 201

    unauthenticated = client.get("/api/v1/facilities/me/feedback")
    assert unauthenticated.status_code == 401

    first_page = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
        params={"limit": 1},
    )
    assert first_page.status_code == 200
    first = first_page.json()
    assert len(first) == 1
    assert first[0]["id"] == feedback_a2.json()["id"]
    assert first[0]["inventory_record_id"] == record_a_id
    assert first[0]["outcome"] == "received"
    assert "comment" not in first[0]

    second_page = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
        params={"before_id": first[0]["id"]},
    )
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()] == [feedback_a1.json()["id"]]

    facility_b_queue = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_b},
    )
    assert facility_b_queue.status_code == 200
    assert [item["inventory_record_id"] for item in facility_b_queue.json()] == [record_b_id]

    invalid_limit = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
        params={"limit": 101},
    )
    invalid_cursor = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
        params={"before_id": 0},
    )
    assert invalid_limit.status_code == 422
    assert invalid_cursor.status_code == 422


def test_feedback_review_is_facility_scoped_idempotent_and_never_changes_inventory():
    facility_a_id, medicine_id, record_a_id = setup_record()
    db = TestingSession()
    facility_b = Facility(
        name="Second Test PHC",
        district="Other District",
        address="Other test address",
        is_active=True,
    )
    db.add(facility_b)
    db.commit()
    db.refresh(facility_b)
    record_b = InventoryRecord(
        facility_id=facility_b.id,
        medicine_id=medicine_id,
        status="available",
        quantity=30,
        verified_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db.add(record_b)
    db.commit()
    record_b_id = record_b.id
    facility_b_id = facility_b.id
    db.close()

    token_a = "facility-a-feedback-review-action-key"
    token_a_second = "facility-a-second-reviewer-key"
    token_b = "facility-b-feedback-review-action-key"
    add_facility_key(facility_a_id, token_a)
    add_facility_key(facility_a_id, token_a_second)
    add_facility_key(facility_b_id, token_b)

    feedback_a = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_a_id, "outcome": "not_available"},
    )
    feedback_b = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_b_id, "outcome": "received"},
    )
    assert feedback_a.status_code == feedback_b.status_code == 201
    feedback_a_id = feedback_a.json()["id"]
    feedback_b_id = feedback_b.json()["id"]

    unauthenticated = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_a_id}/review"
    )
    cross_facility = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_b_id}/review",
        headers={"X-Facility-Key": token_a},
    )
    assert unauthenticated.status_code == 401
    assert cross_facility.status_code == 404

    reviewed = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_a_id}/review",
        headers={"X-Facility-Key": token_a},
    )
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["id"] == feedback_a_id
    assert body["review_required"] is False
    assert body["reviewed_at"] is not None
    first_reviewed_at = body["reviewed_at"]

    db = TestingSession()
    feedback_row = db.get(AvailabilityFeedback, feedback_a_id)
    record_row = db.get(InventoryRecord, record_a_id)
    reviewer_key = db.get(FacilityAccessKey, feedback_row.reviewed_by_access_key_id)
    assert feedback_row.reviewed_at is not None
    assert reviewer_key.facility_id == facility_a_id
    assert record_row.status == "available"
    assert record_row.quantity == 20
    db.close()

    queue_a = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
    )
    queue_b = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_b},
    )
    assert queue_a.status_code == queue_b.status_code == 200
    assert queue_a.json() == []
    assert [item["id"] for item in queue_b.json()] == [feedback_b_id]

    repeated = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_a_id}/review",
        headers={"X-Facility-Key": token_a_second},
    )
    assert repeated.status_code == 200
    assert repeated.json()["reviewed_at"] == first_reviewed_at

    db = TestingSession()
    feedback_row = db.get(AvailabilityFeedback, feedback_a_id)
    second_key_hash = hashlib.sha256(token_a_second.encode("utf-8")).hexdigest()
    second_key = db.scalar(
        select(FacilityAccessKey).where(FacilityAccessKey.key_hash == second_key_hash)
    )
    assert feedback_row.reviewed_by_access_key_id == reviewer_key.id
    assert second_key is not None and second_key.id != reviewer_key.id
    db.close()


def test_feedback_review_rejects_invalid_and_unknown_ids():
    facility_id, _, _ = setup_record()
    token = "feedback-review-invalid-id-test-key"
    add_facility_key(facility_id, token)

    invalid = client.patch(
        "/api/v1/facilities/me/feedback/0/review",
        headers={"X-Facility-Key": token},
    )
    unknown = client.patch(
        "/api/v1/facilities/me/feedback/999999/review",
        headers={"X-Facility-Key": token},
    )
    assert invalid.status_code == 422
    assert unknown.status_code == 404



def test_concurrent_inventory_create_recovers_as_audited_update(monkeypatch):
    facility_id, medicine_id, record_id = setup_record()
    db = TestingSession()
    db.delete(db.get(InventoryRecord, record_id))
    db.commit()
    db.close()

    token = "concurrent-inventory-create-test-key"
    add_facility_key(facility_id, token)
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    key_db = TestingSession()
    access_key = key_db.scalar(
        select(FacilityAccessKey).where(FacilityAccessKey.key_hash == key_hash)
    )
    access_key_id = access_key.id
    key_db.close()

    request_db = TestingSession()
    original_flush = request_db.flush
    conflict_state = {"raised": False}

    def simulate_another_request_winning_the_insert(*args, **kwargs):
        pending_inventory = any(
            isinstance(item, InventoryRecord) for item in request_db.new
        )
        if pending_inventory and not conflict_state["raised"]:
            conflict_state["raised"] = True
            request_db.rollback()

            competing_db = TestingSession()
            competing_record = InventoryRecord(
                facility_id=facility_id,
                medicine_id=medicine_id,
                status="available",
                quantity=9,
                verified_at=datetime.now(timezone.utc),
                source="facility_staff_portal",
                is_demo=False,
            )
            competing_db.add(competing_record)
            competing_db.flush()
            competing_db.add(
                InventoryAuditLog(
                    facility_id=facility_id,
                    inventory_record_id=competing_record.id,
                    access_key_id=access_key_id,
                    action="created",
                    previous_status=None,
                    new_status="available",
                    previous_quantity=None,
                    new_quantity=9,
                )
            )
            competing_db.commit()
            competing_db.close()
            raise IntegrityError(
                "INSERT inventory_records",
                {},
                Exception("uq_facility_medicine"),
            )
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(request_db, "flush", simulate_another_request_winning_the_insert)
    persist_facility_inventory_update(
        db=request_db,
        facility_id=facility_id,
        access_key_id=access_key_id,
        payload=InventoryUpsert(
            medicine_id=medicine_id,
            status="low_stock",
            quantity=4,
        ),
    )
    request_db.close()

    verify_db = TestingSession()
    record = verify_db.scalar(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
    )
    audits = verify_db.scalars(
        select(InventoryAuditLog)
        .where(InventoryAuditLog.inventory_record_id == record.id)
        .order_by(InventoryAuditLog.id)
    ).all()
    assert conflict_state["raised"] is True
    assert record.status == "low_stock"
    assert record.quantity == 4
    assert len(audits) == 2
    assert audits[0].action == "created"
    assert audits[1].action == "updated"
    assert audits[1].previous_status == "available"
    assert audits[1].previous_quantity == 9
    assert audits[1].new_status == "low_stock"
    assert audits[1].new_quantity == 4
    verify_db.close()


def test_inventory_create_integrity_failure_without_matching_row_is_not_swallowed(monkeypatch):
    facility_id, medicine_id, record_id = setup_record()
    db = TestingSession()
    db.delete(db.get(InventoryRecord, record_id))
    db.commit()
    db.close()

    token = "inventory-create-failure-test-key"
    add_facility_key(facility_id, token)
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    key_db = TestingSession()
    access_key = key_db.scalar(
        select(FacilityAccessKey).where(FacilityAccessKey.key_hash == key_hash)
    )
    access_key_id = access_key.id
    key_db.close()

    request_db = TestingSession()
    original_flush = request_db.flush

    def fail_without_a_competing_insert(*args, **kwargs):
        if any(isinstance(item, InventoryRecord) for item in request_db.new):
            raise IntegrityError("INSERT inventory_records", {}, Exception("foreign key"))
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(request_db, "flush", fail_without_a_competing_insert)
    try:
        with pytest.raises(IntegrityError):
            persist_facility_inventory_update(
                db=request_db,
                facility_id=facility_id,
                access_key_id=access_key_id,
                payload=InventoryUpsert(
                    medicine_id=medicine_id,
                    status="available",
                    quantity=6,
                ),
            )
    finally:
        request_db.close()

    verify_db = TestingSession()
    assert verify_db.scalar(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
    ) is None
    assert verify_db.scalar(select(InventoryAuditLog)) is None
    verify_db.close()


def test_inventory_create_conflict_does_not_promote_competing_demo_record(monkeypatch):
    facility_id, medicine_id, record_id = setup_record()
    db = TestingSession()
    db.delete(db.get(InventoryRecord, record_id))
    db.commit()
    db.close()

    token = "inventory-demo-race-test-key"
    add_facility_key(facility_id, token)
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    key_db = TestingSession()
    access_key = key_db.scalar(
        select(FacilityAccessKey).where(FacilityAccessKey.key_hash == key_hash)
    )
    access_key_id = access_key.id
    key_db.close()

    request_db = TestingSession()
    original_flush = request_db.flush
    state = {"raised": False}

    def simulate_demo_record_winning(*args, **kwargs):
        if any(isinstance(item, InventoryRecord) for item in request_db.new) and not state["raised"]:
            state["raised"] = True
            request_db.rollback()
            competing_db = TestingSession()
            competing_db.add(
                InventoryRecord(
                    facility_id=facility_id,
                    medicine_id=medicine_id,
                    status="available",
                    quantity=20,
                    verified_at=datetime.now(timezone.utc),
                    is_demo=True,
                )
            )
            competing_db.commit()
            competing_db.close()
            raise IntegrityError(
                "INSERT inventory_records",
                {},
                Exception("uq_facility_medicine"),
            )
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(request_db, "flush", simulate_demo_record_winning)
    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            persist_facility_inventory_update(
                db=request_db,
                facility_id=facility_id,
                access_key_id=access_key_id,
                payload=InventoryUpsert(
                    medicine_id=medicine_id,
                    status="low_stock",
                    quantity=3,
                ),
            )
        assert error.value.status_code == 409
    finally:
        request_db.close()

    verify_db = TestingSession()
    record = verify_db.scalar(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
    )
    assert record is not None and record.is_demo is True
    assert record.status == "available" and record.quantity == 20
    assert verify_db.scalar(select(InventoryAuditLog)) is None
    verify_db.close()



def test_inventory_row_lock_query_compiles_to_postgresql_for_update():
    statement = _inventory_record_lock_query(facility_id=12, medicine_id=34)
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled.upper()
    assert "facility_id" in compiled
    assert "medicine_id" in compiled
