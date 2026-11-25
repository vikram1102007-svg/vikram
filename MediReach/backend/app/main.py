from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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
    FeedbackReviewActionOut,
    FeedbackReviewOut,
    HealthOut,
    FacilityOut,
    InventoryAuditOut,
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
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["Content-Type", "X-Facility-Key"],
)

@app.middleware("http")
async def prevent_api_response_caching(request, call_next):
    """Prevent stale public availability and cached facility-staff responses."""
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


def _contains_literal(value: str) -> str:
    """Build a case-insensitive contains pattern without treating user input as SQL wildcards."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


def as_utc(value: datetime) -> datetime:
    """Normalise timestamps to UTC; naive database values are UTC from app writes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def freshness(verified_at: datetime, now: datetime | None = None) -> str:
    timestamp = as_utc(verified_at)
    current_time = as_utc(now) if now is not None else datetime.now(timezone.utc)
    age = current_time - timestamp
    if age < -CLOCK_SKEW_TOLERANCE:
        return "Needs Confirmation"

    age_hours = max(0.0, age.total_seconds() / 3600)
    if age_hours <= 24:
        return "Recently Verified"
    if age_hours <= 72:
        return "Needs Confirmation"
    return "Outdated"


def schema_is_current(db: Session) -> bool:
    """Check that the connected database is stamped at every packaged Alembic head."""
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_config = Config()
    alembic_config.set_main_option(
        "script_location",
        str(backend_dir / "migrations"),
    )
    script = ScriptDirectory.from_config(alembic_config)
    expected_heads = set(script.get_heads())
    current_heads = set(MigrationContext.configure(db.connection()).get_current_heads())
    return bool(expected_heads) and current_heads == expected_heads


@app.get("/health", response_model=MessageOut, tags=["system"])
def health():
    """Liveness probe: confirms that the API process is responding."""
    return {"message": "MediReach API is healthy"}


@app.get("/health/ready", response_model=HealthOut, tags=["system"])
def readiness(db: Session = Depends(get_db)):
    """Readiness probe: checks database connectivity and the packaged migration state."""
    try:
        db.execute(text("SELECT 1"))
        if not schema_is_current(db):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database schema is not up to date",
            )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    except Exception as exc:
        # Fail closed if packaged migration metadata cannot be inspected.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Readiness check is unavailable",
        ) from exc
    return {"status": "ready"}


@app.get("/api/v1/medicines", response_model=list[MedicineOut], tags=["catalog"])
def list_medicines(
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
):
    stmt = select(Medicine).order_by(Medicine.name)
    query = q.strip() if q is not None else ""
    if query:
        stmt = stmt.where(Medicine.name.ilike(_contains_literal(query), escape="\\"))
    return db.scalars(stmt.limit(100)).all()


@app.get("/api/v1/facilities", response_model=list[FacilityOut], tags=["facilities"])
def list_facilities(
    district: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
):
    stmt = select(Facility).where(Facility.is_active.is_(True)).order_by(Facility.name)
    district_filter = district.strip() if district is not None else ""
    if district_filter:
        stmt = stmt.where(
            Facility.district.ilike(_contains_literal(district_filter), escape="\\")
        )
    return db.scalars(stmt.limit(100)).all()


@app.get("/api/v1/availability", response_model=list[AvailabilityOut], tags=["availability"])
def search_availability(
    medicine: str = Query(min_length=2, max_length=160),
    district: str | None = Query(default=None, max_length=100),
    include_demo: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    medicine_term = medicine.strip()
    if len(medicine_term) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Medicine search must contain at least two non-whitespace characters",
        )

    stmt = (
        select(InventoryRecord)
        .options(
            joinedload(InventoryRecord.facility),
            joinedload(InventoryRecord.medicine),
        )
        .join(Medicine)
        .join(Facility)
        .where(
            Medicine.name.ilike(_contains_literal(medicine_term), escape="\\"),
            Facility.is_active.is_(True),
        )
    )
    district_filter = district.strip() if district is not None else ""
    if district_filter:
        stmt = stmt.where(
            Facility.district.ilike(_contains_literal(district_filter), escape="\\")
        )
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
            verified_at=as_utc(record.verified_at),
            confidence=freshness(record.verified_at),
            is_demo=record.is_demo,
        )
        for record in records
    ]


def _inventory_record_lock_query(facility_id: int, medicine_id: int):
    """Build the facility-scoped row lock used by PostgreSQL inventory writes."""
    return (
        select(InventoryRecord)
        .where(
            InventoryRecord.facility_id == facility_id,
            InventoryRecord.medicine_id == medicine_id,
        )
        .with_for_update()
    )


def persist_facility_inventory_update(
    db: Session,
    facility_id: int,
    access_key_id: int,
    payload: InventoryUpsert,
) -> None:
    """Persist one inventory change and its audit event as a single transaction.

    Existing rows are locked on databases that support SELECT FOR UPDATE. If two
    staff requests race to create the same facility/medicine pair, the unique
    constraint chooses the first insert; the losing transaction rolls back,
    locks the winner's row, and records its request as a normal update.
    """
    if db.get(Medicine, payload.medicine_id) is None:
        raise HTTPException(status_code=404, detail="Medicine not found")

    record_stmt = _inventory_record_lock_query(facility_id, payload.medicine_id)
    record = db.scalar(record_stmt)

    if record is None:
        record = InventoryRecord(
            facility_id=facility_id,
            medicine_id=payload.medicine_id,
            status=payload.status,
            quantity=payload.quantity,
            source="facility_staff_portal",
            is_demo=False,
        )
        db.add(record)
        try:
            # Surface a concurrent unique-key insert before creating its audit row.
            db.flush()
            action = "created"
            previous_status = None
            previous_quantity = None
        except IntegrityError:
            db.rollback()
            # On PostgreSQL, the conflicting INSERT waits for the winning
            # transaction. After rollback its committed row can be locked here.
            record = db.scalar(record_stmt)
            if record is None:
                # The integrity failure was not a competing facility/medicine insert.
                raise
            if record.is_demo:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Fictional demo inventory must be replaced by an "
                        "administrator before staff updates"
                    ),
                )
            action = "updated"
            previous_status = record.status
            previous_quantity = record.quantity
            record.status = payload.status
            record.quantity = payload.quantity
            record.source = "facility_staff_portal"
            record.verified_at = datetime.now(timezone.utc)
    else:
        if record.is_demo:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Fictional demo inventory must be replaced by an "
                    "administrator before staff updates"
                ),
            )
        action = "updated"
        previous_status = record.status
        previous_quantity = record.quantity
        record.status = payload.status
        record.quantity = payload.quantity
        record.source = "facility_staff_portal"
        record.verified_at = datetime.now(timezone.utc)

    db.add(
        InventoryAuditLog(
            facility_id=facility_id,
            inventory_record_id=record.id,
            access_key_id=access_key_id,
            action=action,
            previous_status=previous_status,
            new_status=payload.status,
            previous_quantity=previous_quantity,
            new_quantity=payload.quantity,
        )
    )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


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
    persist_facility_inventory_update(
        db=db,
        facility_id=staff.facility_id,
        access_key_id=staff.access_key_id,
        payload=payload,
    )
    return {"message": "Facility inventory saved and audit event recorded"}


@app.get(
    "/api/v1/facilities/me/audit",
    response_model=list[InventoryAuditOut],
    tags=["facility staff"],
)
def list_facility_audit_history(
    staff: FacilityStaff = Depends(require_facility_staff),
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    """Return only the authenticated facility's inventory audit events."""
    stmt = (
        select(InventoryAuditLog, Medicine)
        .join(
            InventoryRecord,
            InventoryAuditLog.inventory_record_id == InventoryRecord.id,
        )
        .join(Medicine, InventoryRecord.medicine_id == Medicine.id)
        .where(
            InventoryAuditLog.facility_id == staff.facility_id,
            InventoryRecord.facility_id == staff.facility_id,
        )
        .order_by(InventoryAuditLog.id.desc())
    )
    if before_id is not None:
        stmt = stmt.where(InventoryAuditLog.id < before_id)

    rows = db.execute(stmt.limit(limit)).all()
    return [
        InventoryAuditOut(
            id=audit.id,
            inventory_record_id=audit.inventory_record_id,
            medicine_name=medicine.name,
            medicine_strength=medicine.strength,
            action=audit.action,
            previous_status=audit.previous_status,
            new_status=audit.new_status,
            previous_quantity=audit.previous_quantity,
            new_quantity=audit.new_quantity,
            changed_at=as_utc(audit.changed_at),
        )
        for audit, medicine in rows
    ]


@app.get(
    "/api/v1/facilities/me/feedback",
    response_model=list[FeedbackReviewOut],
    tags=["facility staff"],
)
def list_facility_feedback_review_queue(
    staff: FacilityStaff = Depends(require_facility_staff),
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    """Return pending, non-demo feedback signals for the authenticated facility only."""
    stmt = (
        select(AvailabilityFeedback, InventoryRecord, Medicine)
        .join(
            InventoryRecord,
            AvailabilityFeedback.inventory_record_id == InventoryRecord.id,
        )
        .join(Medicine, InventoryRecord.medicine_id == Medicine.id)
        .where(
            InventoryRecord.facility_id == staff.facility_id,
            InventoryRecord.is_demo.is_(False),
            AvailabilityFeedback.review_required.is_(True),
        )
        .order_by(AvailabilityFeedback.id.desc())
    )
    if before_id is not None:
        stmt = stmt.where(AvailabilityFeedback.id < before_id)

    rows = db.execute(stmt.limit(limit)).all()
    return [
        FeedbackReviewOut(
            id=feedback.id,
            inventory_record_id=record.id,
            medicine_name=medicine.name,
            medicine_strength=medicine.strength,
            outcome=feedback.outcome,
            created_at=as_utc(feedback.created_at),
            review_required=feedback.review_required,
        )
        for feedback, record, medicine in rows
    ]


@app.patch(
    "/api/v1/facilities/me/feedback/{feedback_id}/review",
    response_model=FeedbackReviewActionOut,
    tags=["facility staff"],
)
def mark_facility_feedback_reviewed(
    feedback_id: int = PathParam(gt=0),
    staff: FacilityStaff = Depends(require_facility_staff),
    db: Session = Depends(get_db),
):
    """Atomically acknowledge one feedback signal for the authenticated facility.

    The conditional UPDATE lets only the first concurrent reviewer win. It
    changes review metadata only; inventory values and verification time stay
    untouched. Repeated requests return the original reviewer and timestamp.
    """
    authorised_inventory_ids = select(InventoryRecord.id).where(
        InventoryRecord.facility_id == staff.facility_id,
        InventoryRecord.is_demo.is_(False),
    )
    db.execute(
        update(AvailabilityFeedback)
        .where(
            AvailabilityFeedback.id == feedback_id,
            AvailabilityFeedback.review_required.is_(True),
            AvailabilityFeedback.inventory_record_id.in_(authorised_inventory_ids),
        )
        .values(
            review_required=False,
            reviewed_at=datetime.now(timezone.utc),
            reviewed_by_access_key_id=staff.access_key_id,
        )
    )
    db.commit()

    feedback = db.scalar(
        select(AvailabilityFeedback)
        .join(
            InventoryRecord,
            AvailabilityFeedback.inventory_record_id == InventoryRecord.id,
        )
        .where(
            AvailabilityFeedback.id == feedback_id,
            InventoryRecord.facility_id == staff.facility_id,
            InventoryRecord.is_demo.is_(False),
        )
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found")

    return FeedbackReviewActionOut(
        id=feedback.id,
        review_required=feedback.review_required,
        reviewed_at=as_utc(feedback.reviewed_at) if feedback.reviewed_at else None,
    )


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
    if record.is_demo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback is unavailable for fictional demo records",
        )

    facility = db.get(Facility, record.facility_id)
    if facility is None or not facility.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback is unavailable for inactive facilities",
        )

    feedback = AvailabilityFeedback(
        inventory_record_id=record.id,
        outcome=payload.outcome,
        # Do not persist free-text patient comments; structured outcomes are sufficient.
        comment=None,
        review_required=True,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    # Feedback never changes stock; it creates a review signal only.
    return feedback
