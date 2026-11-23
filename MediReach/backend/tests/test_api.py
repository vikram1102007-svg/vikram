import hashlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app, freshness
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
    assert freshness(now - timedelta(hours=23, minutes=59)) == "Recently Verified"
    assert freshness(now - timedelta(hours=48)) == "Needs Confirmation"
    assert freshness(now - timedelta(hours=73)) == "Outdated"

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


def test_facility_feedback_review_queue_is_authenticated_scoped_and_paginated():
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

    token_a = "facility-a-feedback-review-test-key"
    token_b = "facility-b-feedback-review-test-key"
    add_facility_key(facility_a_id, token_a)
    add_facility_key(facility_b_id, token_b)

    older_feedback = client.post(
        "/api/v1/feedback",
        json={
            "inventory_record_id": record_a_id,
            "outcome": "not_available",
            "comment": "This private free-text note must not be exposed in staff queue.",
        },
    )
    newer_feedback = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_a_id, "outcome": "received"},
    )
    reviewed_feedback = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_a_id, "outcome": "received"},
    )
    other_facility_feedback = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_b_id, "outcome": "not_available"},
    )
    assert older_feedback.status_code == 201
    assert newer_feedback.status_code == 201
    assert reviewed_feedback.status_code == 201
    assert other_facility_feedback.status_code == 201

    unauthenticated = client.get("/api/v1/facilities/me/feedback")
    assert unauthenticated.status_code == 401

    db = TestingSession()
    reviewed_signal = db.get(AvailabilityFeedback, reviewed_feedback.json()["id"])
    reviewed_signal.review_required = False
    db.commit()
    db.close()

    first_page = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
        params={"limit": 1},
    )
    assert first_page.status_code == 200
    first_events = first_page.json()
    assert len(first_events) == 1
    assert first_events[0]["id"] == newer_feedback.json()["id"]
    assert first_events[0]["inventory_record_id"] == record_a_id
    assert first_events[0]["medicine_name"] == "Paracetamol"
    assert first_events[0]["outcome"] == "received"
    assert "comment" not in first_events[0]

    second_page = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
        params={"limit": 10, "before_id": first_events[0]["id"]},
    )
    assert second_page.status_code == 200
    assert len(second_page.json()) == 1
    assert second_page.json()[0]["id"] == older_feedback.json()["id"]
    assert second_page.json()[0]["inventory_record_id"] == record_a_id

    facility_b_queue = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_b},
    )
    assert facility_b_queue.status_code == 200
    assert len(facility_b_queue.json()) == 1
    assert facility_b_queue.json()[0]["inventory_record_id"] == record_b_id


def test_facility_feedback_review_queue_rejects_invalid_pagination():
    facility_id, _, _ = setup_record()
    token = "facility-feedback-pagination-test-key"
    add_facility_key(facility_id, token)

    zero_limit = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token},
        params={"limit": 0},
    )
    zero_cursor = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token},
        params={"before_id": 0},
    )
    assert zero_limit.status_code == 422
    assert zero_cursor.status_code == 422


def test_feedback_rejects_unexpected_fields():
    _, _, record_id = setup_record()
    response = client.post(
        "/api/v1/feedback",
        json={
            "inventory_record_id": record_id,
            "outcome": "received",
            "facility_id": 999,
        },
    )
    assert response.status_code == 422


def test_feedback_review_queue_enforces_maximum_page_size():
    facility_id, _, _ = setup_record()
    token = "facility-feedback-max-page-test-key"
    add_facility_key(facility_id, token)
    response = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token},
        params={"limit": 101},
    )
    assert response.status_code == 422

def test_feedback_review_is_authenticated_facility_scoped_and_audited():
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
    facility_b_id = facility_b.id
    record_b = InventoryRecord(
        facility_id=facility_b_id,
        medicine_id=medicine_id,
        status="available",
        quantity=30,
        verified_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db.add(record_b)
    db.commit()
    record_b_id = record_b.id
    db.close()

    token_a = "facility-a-feedback-review-action-test-key"
    token_b = "facility-b-feedback-review-action-test-key"
    add_facility_key(facility_a_id, token_a)
    add_facility_key(facility_b_id, token_b)

    feedback_a = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_a_id, "outcome": "not_available"},
    )
    feedback_b = client.post(
        "/api/v1/feedback",
        json={"inventory_record_id": record_b_id, "outcome": "received"},
    )
    assert feedback_a.status_code == 201
    assert feedback_b.status_code == 201
    feedback_a_id = feedback_a.json()["id"]
    feedback_b_id = feedback_b.json()["id"]

    unauthenticated = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_a_id}/review"
    )
    assert unauthenticated.status_code == 401

    cross_facility = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_b_id}/review",
        headers={"X-Facility-Key": token_a},
    )
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
    assert feedback_row.review_required is False
    assert feedback_row.reviewed_at is not None
    assert reviewer_key.facility_id == facility_a_id
    assert record_row.status == "available" and record_row.quantity == 20
    db.close()

    queue_a = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_a},
    )
    queue_b = client.get(
        "/api/v1/facilities/me/feedback",
        headers={"X-Facility-Key": token_b},
    )
    assert queue_a.status_code == 200 and queue_a.json() == []
    assert queue_b.status_code == 200
    assert [item["id"] for item in queue_b.json()] == [feedback_b_id]

    repeated = client.patch(
        f"/api/v1/facilities/me/feedback/{feedback_a_id}/review",
        headers={"X-Facility-Key": token_a},
    )
    assert repeated.status_code == 200
    assert repeated.json()["reviewed_at"] == first_reviewed_at

    db = TestingSession()
    feedback_row = db.get(AvailabilityFeedback, feedback_a_id)
    assert feedback_row.reviewed_by_access_key_id == reviewer_key.id
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
