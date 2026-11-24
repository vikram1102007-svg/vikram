from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AvailabilityFeedback, Facility, InventoryRecord, Medicine

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_feedback_does_not_persist_free_text_comments():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db: Session = TestSession()
    facility = Facility(
        name="Test PHC",
        district="Test District",
        address="Test address",
        is_active=True,
    )
    medicine = Medicine(name="Test medicine", strength="standard", form="tablet")
    db.add_all([facility, medicine])
    db.commit()
    db.refresh(facility)
    db.refresh(medicine)
    record = InventoryRecord(
        facility_id=facility.id,
        medicine_id=medicine.id,
        status="available",
        quantity=10,
        verified_at=datetime.now(timezone.utc),
        is_demo=False,
    )
    db.add(record)
    db.commit()
    record_id = record.id
    db.close()

    def override_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/feedback",
                json={
                    "inventory_record_id": record_id,
                    "outcome": "not_available",
                    "comment": "Unstructured personal details must not be retained",
                },
            )
        assert response.status_code == 201
        feedback_id = response.json()["id"]

        db = TestSession()
        feedback = db.get(AvailabilityFeedback, feedback_id)
        assert feedback is not None
        assert feedback.review_required is True
        assert feedback.comment is None
        inventory = db.get(InventoryRecord, record_id)
        assert inventory.status == "available"
        assert inventory.quantity == 10
        db.close()
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
