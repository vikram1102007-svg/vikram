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
