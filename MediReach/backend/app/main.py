from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .database import get_db
from .models import (
    AvailabilityFeedback,
    Facility,
    InventoryAuditLog,
    InventoryRecord,
    Medicine,
)
from .schemas import (
    AvailabilityOut,
    FeedbackCreate,
    FeedbackOut,
    HealthOut,
    FacilityOut,
    InventoryUpsert,
    MedicineOut,
    MessageOut,
)
from .security import FacilityStaff, require_facility_staff

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.1.0",
    description=(
        "Medicine availability information API. Availability is informational "
        "and must be confirmed with the facility."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Facility-Key"],
)


def freshness(verified_at: datetime) -> str:
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)
    age_hours = max(
        0.0,
        (datetime.now(timezone.utc) - verified_at.astimezone(timezone.utc)).total_seconds() / 3600,
    )
    if age_hours <= 24:
        return "Recently Verified"
    if age_hours <= 72:
        return "Needs Confirmation"
    return "Outdated"


@app.get("/health", response_model=MessageOut, tags=["system"])
def health():
    """Liveness probe: confirms the API process is responding."""
    return {"message": "MediReach API is healthy"}


@app.get("/health/ready", response_model=HealthOut, tags=["system"])
def readiness(db: Session = Depends(get_db)):
    """Readiness probe: confirms the configured database accepts a simple query."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    return {"status": "ready"}


@app.get("/api/v1/medicines", response_model=list[MedicineOut], tags=["catalog"])
def list_medicines(
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
):
    stmt = select(Medicine).order_by(Medicine.name)
    if q:
        stmt = stmt.where(Medicine.name.ilike(f"%{q.strip()}%"))
    return db.scalars(stmt.limit(100)).all()


@app.get("/api/v1/facilities", response_model=list[FacilityOut], tags=["facilities"])
def list_facilities(
    district: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
):
    stmt = select(Facility).where(Facility.is_active.is_(True)).order_by(Facility.name)
    if district:
        stmt = stmt.where(Facility.district.ilike(f"%{district.strip()}%"))
    return db.scalars(stmt.limit(100)).all()


@app.get("/api/v1/availability", response_model=list[AvailabilityOut], tags=["availability"])
def search_availability(
    medicine: str = Query(min_length=2, max_length=160),
    district: str | None = Query(default=None, max_length=100),
    include_demo: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    stmt = (
        select(InventoryRecord)
        .options(
            joinedload(InventoryRecord.facility),
            joinedload(InventoryRecord.medicine),
        )
        .join(Medicine)
        .join(Facility)
        .where(
            Medicine.name.ilike(f"%{medicine.strip()}%"),
            Facility.is_active.is_(True),
        )
    )
    if district:
        stmt = stmt.where(Facility.district.ilike(f"%{district.strip()}%"))
    if not include_demo:
        stmt = stmt.where(InventoryRecord.is_demo.is_(False))
    records = db.scalars(
        stmt.order_by(InventoryRecord.verified_at.desc()).limit(100)
    ).unique().all()
    return [
        AvailabilityOut(
            facility=record.facility,
            medicine=record.medicine,
            status=record.status,
            quantity=record.quantity,
            verified_at=record.verified_at,
            confidence=freshness(record.verified_at),
            is_demo=record.is_demo,
        )
        for record in records
    ]


@app.put(
    "/api/v1/facilities/me/inventory",
    response_model=MessageOut,
    tags=["facility staff"],
)
def upsert_facility_inventory(
    payload: InventoryUpsert,
    staff: FacilityStaff = Depends(require_facility_staff),
    db: Session = Depends(get_db),
):
    medicine = db.get(Medicine, payload.medicine_id)
    if medicine is None:
        raise HTTPException(status_code=404, detail="Medicine not found")

    record = db.scalar(
        select(InventoryRecord).where(
            InventoryRecord.facility_id == staff.facility_id,
            InventoryRecord.medicine_id == payload.medicine_id,
        )
    )
    if record is None:
        record = InventoryRecord(
            facility_id=staff.facility_id,
            medicine_id=payload.medicine_id,
            status=payload.status,
            quantity=payload.quantity,
            source="facility_staff_portal",
            is_demo=False,
        )
        db.add(record)
        db.flush()
        action = "created"
        previous_status = None
        previous_quantity = None
    else:
        action = "updated"
        previous_status = record.status
        previous_quantity = record.quantity
        record.status = payload.status
        record.quantity = payload.quantity
        record.source = "facility_staff_portal"
        record.verified_at = datetime.now(timezone.utc)

    db.add(
        InventoryAuditLog(
            facility_id=staff.facility_id,
            inventory_record_id=record.id,
            access_key_id=staff.access_key_id,
            action=action,
            previous_status=previous_status,
            new_status=payload.status,
            previous_quantity=previous_quantity,
            new_quantity=payload.quantity,
        )
    )
    db.commit()
    return {"message": "Facility inventory saved and audit event recorded"}


@app.post(
    "/api/v1/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    tags=["feedback"],
)
def submit_feedback(payload: FeedbackCreate, db: Session = Depends(get_db)):
    record = db.get(InventoryRecord, payload.inventory_record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Availability record not found")
    feedback = AvailabilityFeedback(
        inventory_record_id=record.id,
        outcome=payload.outcome,
        comment=payload.comment,
        review_required=True,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    # Feedback never changes stock; it creates a review signal only.
    return feedback
