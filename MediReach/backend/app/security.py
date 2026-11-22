import hashlib
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Facility, FacilityAccessKey


@dataclass(frozen=True)
class FacilityStaff:
    facility_id: int
    access_key_id: int


def require_facility_staff(
    x_facility_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> FacilityStaff:
    if not x_facility_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Facility credentials are required",
        )

    key_hash = hashlib.sha256(x_facility_key.encode("utf-8")).hexdigest()
    access_key = db.scalar(
        select(FacilityAccessKey)
        .join(Facility, Facility.id == FacilityAccessKey.facility_id)
        .where(
            FacilityAccessKey.key_hash == key_hash,
            FacilityAccessKey.revoked_at.is_(None),
            Facility.is_active.is_(True),
        )
    )
    if access_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked facility credentials",
        )

    return FacilityStaff(
        facility_id=access_key.facility_id,
        access_key_id=access_key.id,
    )
