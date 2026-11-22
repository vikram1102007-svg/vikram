from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

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
    facility_id: int = Field(gt=0)
    medicine_id: int = Field(gt=0)
    status: Literal["available", "low_stock", "unavailable", "not_reported"]
    quantity: int | None = Field(default=None, ge=0)
    source: str = Field(default="facility_report", max_length=80)
    is_demo: bool = False

class FeedbackCreate(BaseModel):
    inventory_record_id: int = Field(gt=0)
    outcome: Literal["received", "not_available"]
    comment: str | None = Field(default=None, max_length=500)

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