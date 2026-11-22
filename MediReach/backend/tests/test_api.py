from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app, freshness
from app.models import Facility, InventoryRecord, Medicine

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    facility = Facility(name="Test PHC", district="Test District", address="Test address", is_active=True)
    medicine = Medicine(name="Paracetamol", strength="500 mg", form="tablet")
    db.add_all([facility, medicine]); db.commit(); db.refresh(facility); db.refresh(medicine)
    record = InventoryRecord(facility_id=facility.id, medicine_id=medicine.id, status="available", quantity=20, verified_at=datetime.now(timezone.utc), is_demo=False)
    db.add(record); db.commit(); db.refresh(record)
    ids = (facility.id, medicine.id, record.id)
    db.close()
    return ids

def test_health():
    assert client.get("/health").status_code == 200

def test_availability_search_returns_freshness():
    setup_record()
    response = client.get("/api/v1/availability", params={"medicine": "Para"})
    assert response.status_code == 200
    assert response.json()[0]["confidence"] == "Recently Verified"

def test_feedback_does_not_change_inventory():
    _, _, record_id = setup_record()
    response = client.post("/api/v1/feedback", json={"inventory_record_id": record_id, "outcome": "not_available"})
    assert response.status_code == 201
    db = TestingSession(); record = db.get(InventoryRecord, record_id)
    assert record.status == "available" and record.quantity == 20
    db.close()

def test_freshness_thresholds():
    now = datetime.now(timezone.utc)
    assert freshness(now - timedelta(hours=23, minutes=59)) == "Recently Verified"
    assert freshness(now - timedelta(hours=48)) == "Needs Confirmation"
    assert freshness(now - timedelta(hours=73)) == "Outdated"