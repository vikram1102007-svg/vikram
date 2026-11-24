import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Facility, InventoryRecord, Medicine


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def api_client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSession()
    facility = Facility(
        name="Search Test PHC",
        district="Test District",
        address="Fictional test address",
        is_active=True,
    )
    medicine = Medicine(name="Paracetamol", strength="500 mg", form="tablet")
    db.add_all([facility, medicine])
    db.commit()
    db.refresh(facility)
    db.refresh(medicine)
    db.add(
        InventoryRecord(
            facility_id=facility.id,
            medicine_id=medicine.id,
            status="available",
            quantity=10,
            verified_at=datetime.now(timezone.utc),
            is_demo=False,
        )
    )
    db.commit()
    db.close()

    def override_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


def test_availability_rejects_whitespace_only_medicine_search(api_client):
    response = api_client.get(
        "/api/v1/availability",
        params={"medicine": "   "},
    )

    assert response.status_code == 422
    assert "non-whitespace characters" in response.json()["detail"]


def test_availability_trims_valid_medicine_search(api_client):
    response = api_client.get(
        "/api/v1/availability",
        params={"medicine": "  Para  "},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["medicine"]["name"] == "Paracetamol"


@pytest.mark.parametrize("medicine_query", ["%%", "__"])
def test_availability_treats_sql_wildcards_as_literal_search_text(
    api_client, medicine_query
):
    response = api_client.get(
        "/api/v1/availability",
        params={"medicine": medicine_query},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_availability_treats_wildcard_district_as_literal(api_client):
    response = api_client.get(
        "/api/v1/availability",
        params={"medicine": "Para", "district": "%"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_whitespace_only_district_is_ignored(api_client):
    response = api_client.get(
        "/api/v1/availability",
        params={"medicine": "Para", "district": "   "},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_medicine_catalog_search_treats_wildcards_as_literal(api_client):
    response = api_client.get(
        "/api/v1/medicines",
        params={"q": "%%"},
    )

    assert response.status_code == 200
    assert response.json() == []
