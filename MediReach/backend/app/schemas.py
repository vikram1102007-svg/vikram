from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MedicineOut(BaseModel):
    id: int
    name: str
    strength: str | None = None
    form: str | None = None
    model_config = ConfigDict(from_attributes=True)


class FacilityOut(BaseModel):
    id: int
    name: str
    district: str
    address: str
    phone: str | None = None
    model_config = ConfigDict(from_attributes=True)


class InventoryUpsert(BaseModel):
    medicine_id: int = Field(gt=0)
    status: Literal["available", "low_stock", "unavailable", "not_reported"]
    quantity: int | None = Field(default=None, ge=0)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_stock_state(self):
        if self.status == "not_reported" and self.quantity is not None:
            raise ValueError("Quantity must be omitted when stock is not reported")
        if self.status == "unavailable" and self.quantity not in (None, 0):
            raise ValueError("Unavailable stock cannot have a positive quantity")
        if self.status in ("available", "low_stock") and self.quantity == 0:
            raise ValueError("Available or low stock cannot have a zero quantity")
        return self


class FeedbackCreate(BaseModel):
    inventory_record_id: int = Field(gt=0)
    outcome: Literal["received", "not_available"]
    comment: str | None = Field(default=None, max_length=500)
    model_config = ConfigDict(extra="forbid")


class FeedbackOut(BaseModel):
    id: int
    review_required: bool
    model_config = ConfigDict(from_attributes=True)


class AvailabilityOut(BaseModel):
    facility: FacilityOut
    medicine: MedicineOut
    status: str
    quantity: int | None
    verified_at: datetime
    confidence: Literal["Recently Verified", "Needs Confirmation", "Outdated"]
    is_demo: bool


class MessageOut(BaseModel):
    message: str


class FeedbackReviewOut(BaseModel):
    id: int
    inventory_record_id: int
    medicine_name: str
    medicine_strength: str | None = None
    outcome: Literal["received", "not_available"]
    created_at: datetime
    review_required: bool


class FeedbackReviewActionOut(BaseModel):
    id: int
    review_required: bool
    reviewed_at: datetime | None = None
