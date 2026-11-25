"""Runtime concurrency checks against a real PostgreSQL service in CI."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models import (
    Facility,
    FacilityAccessKey,
    InventoryAuditLog,
    InventoryRecord,
    Medicine,
)

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("TEST_DATABASE_URL is only configured in the PostgreSQL CI job", allow_module_level=True)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
PgSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_postgres_db():
    db = PgSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_postgres_db
client = TestClient(app)


def create_staff_fixture():
    """Create uniquely named test records without deleting or modifying existing data."""
    suffix = uuid4().hex
    db = PgSession()
    facility = Facility(
        name=f"Concurrency Test Facility {suffix}",
        district="CI Test District",
        address="Synthetic CI-only address",
        is_active=True,
    )
    medicine = Medicine(
        name=f"Concurrency Test Medicine {suffix}",
        strength="test strength",
        form="tablet",
    )
    db.add_all([facility, medicine])
    db.flush()

    token = f"ci-test-facility-key-{suffix}"
    key = FacilityAccessKey(
        facility_id=facility.id,
        key_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
    )
    db.add(key)
    db.commit()
    facility_id, medicine_id, key_id = facility.id, medicine.id, key.id
    db.close()
    return facility_id, medicine_id, key_id, token


def update_inventory(token, medicine_id, status, quantity):
    return client.put(
        "/api/v1/facilities/me/inventory",
        headers={"X-Facility-Key": token},
        json={"medicine_id": medicine_id, "status": status, "quantity": quantity},
    )


def test_postgresql_concurrent_create_produces_one_record_and_two_audits():
    facility_id, medicine_id, key_id, token = create_staff_fixture()

    # Both workers start from the absent-record state. PostgreSQL's unique
    # constraint resolves the insert race; the loser must recover as an update.
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update_inventory, token, medicine_id, "available", 9)
        second = pool.submit(update_inventory, token, medicine_id, "low_stock", 4)
        responses = [first.result(timeout=30), second.result(timeout=30)]

    assert [response.status_code for response in responses] == [200, 200]

    db = PgSession()
    records = db.scalars(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
    ).all()
    assert len(records) == 1
    record = records[0]

    audits = db.scalars(
        select(InventoryAuditLog)
        .where(
            InventoryAuditLog.facility_id == facility_id,
            InventoryAuditLog.inventory_record_id == record.id,
        )
        .order_by(InventoryAuditLog.id)
    ).all()
    assert len(audits) == 2
    assert [audit.action for audit in audits] == ["created", "updated"]
    assert audits[0].previous_quantity is None
    assert audits[1].previous_quantity == audits[0].new_quantity
    assert audits[1].new_quantity == record.quantity
    assert all(audit.access_key_id == key_id for audit in audits)
    db.close()


def test_postgresql_concurrent_updates_lock_and_audit_each_previous_value():
    facility_id, medicine_id, key_id, token = create_staff_fixture()
    created = update_inventory(token, medicine_id, "available", 20)
    assert created.status_code == 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update_inventory, token, medicine_id, "low_stock", 11)
        second = pool.submit(update_inventory, token, medicine_id, "available", 12)
        responses = [first.result(timeout=30), second.result(timeout=30)]

    assert [response.status_code for response in responses] == [200, 200]

    db = PgSession()
    record = db.scalar(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
    )
    audits = db.scalars(
        select(InventoryAuditLog)
        .where(
            InventoryAuditLog.facility_id == facility_id,
            InventoryAuditLog.inventory_record_id == record.id,
        )
        .order_by(InventoryAuditLog.id)
    ).all()
    assert len(audits) == 3
    assert audits[0].action == "created"
    assert audits[1].action == audits[2].action == "updated"
    assert audits[1].previous_quantity == 20
    assert audits[2].previous_quantity == audits[1].new_quantity
    assert audits[2].new_quantity == record.quantity
    assert all(audit.access_key_id == key_id for audit in audits)
    db.close()
