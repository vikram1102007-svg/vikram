from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    inventory: Mapped[list["InventoryRecord"]] = relationship(
        back_populates="facility", cascade="all, delete-orphan"
    )


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    strength: Mapped[str | None] = mapped_column(String(80))
    form: Mapped[str | None] = mapped_column(String(80))
    inventory: Mapped[list["InventoryRecord"]] = relationship(
        back_populates="medicine", cascade="all, delete-orphan"
    )


class FacilityAccessKey(Base):
    __tablename__ = "facility_access_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facility_id: Mapped[int] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryRecord(Base):
    __tablename__ = "inventory_records"
    __table_args__ = (
        UniqueConstraint("facility_id", "medicine_id", name="uq_facility_medicine"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facility_id: Mapped[int] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    medicine_id: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(80), default="facility_report", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    facility: Mapped[Facility] = relationship(back_populates="inventory")
    medicine: Mapped[Medicine] = relationship(back_populates="inventory")


class InventoryAuditLog(Base):
    __tablename__ = "inventory_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facility_id: Mapped[int] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_record_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    access_key_id: Mapped[int] = mapped_column(
        ForeignKey("facility_access_keys.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_quantity: Mapped[int | None] = mapped_column(Integer)
    new_quantity: Mapped[int | None] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AvailabilityFeedback(Base):
    __tablename__ = "availability_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inventory_record_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_access_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("facility_access_keys.id", ondelete="RESTRICT"), nullable=True, index=True
    )
