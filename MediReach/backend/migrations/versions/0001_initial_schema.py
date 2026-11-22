"""Create initial MediReach schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "facilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("district", sa.String(length=100), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_facilities_name", "facilities", ["name"], unique=False)
    op.create_index("ix_facilities_district", "facilities", ["district"], unique=False)

    op.create_table(
        "medicines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("strength", sa.String(length=80), nullable=True),
        sa.Column("form", sa.String(length=80), nullable=True),
    )
    op.create_index("ix_medicines_name", "medicines", ["name"], unique=True)

    op.create_table(
        "facility_access_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_facility_access_keys_facility_id", "facility_access_keys", ["facility_id"], unique=False)
    op.create_index("ix_facility_access_keys_key_hash", "facility_access_keys", ["key_hash"], unique=True)

    op.create_table(
        "inventory_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("medicine_id", sa.Integer(), sa.ForeignKey("medicines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("facility_id", "medicine_id", name="uq_facility_medicine"),
    )
    op.create_index("ix_inventory_records_facility_id", "inventory_records", ["facility_id"], unique=False)
    op.create_index("ix_inventory_records_medicine_id", "inventory_records", ["medicine_id"], unique=False)
    op.create_index("ix_inventory_records_verified_at", "inventory_records", ["verified_at"], unique=False)

    op.create_table(
        "inventory_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_record_id", sa.Integer(), sa.ForeignKey("inventory_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_key_id", sa.Integer(), sa.ForeignKey("facility_access_keys.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("previous_quantity", sa.Integer(), nullable=True),
        sa.Column("new_quantity", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inventory_audit_logs_facility_id", "inventory_audit_logs", ["facility_id"], unique=False)
    op.create_index("ix_inventory_audit_logs_inventory_record_id", "inventory_audit_logs", ["inventory_record_id"], unique=False)
    op.create_index("ix_inventory_audit_logs_access_key_id", "inventory_audit_logs", ["access_key_id"], unique=False)

    op.create_table(
        "availability_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_record_id", sa.Integer(), sa.ForeignKey("inventory_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_availability_feedback_inventory_record_id", "availability_feedback", ["inventory_record_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_availability_feedback_inventory_record_id", table_name="availability_feedback")
    op.drop_table("availability_feedback")

    op.drop_index("ix_inventory_audit_logs_access_key_id", table_name="inventory_audit_logs")
    op.drop_index("ix_inventory_audit_logs_inventory_record_id", table_name="inventory_audit_logs")
    op.drop_index("ix_inventory_audit_logs_facility_id", table_name="inventory_audit_logs")
    op.drop_table("inventory_audit_logs")

    op.drop_index("ix_inventory_records_verified_at", table_name="inventory_records")
    op.drop_index("ix_inventory_records_medicine_id", table_name="inventory_records")
    op.drop_index("ix_inventory_records_facility_id", table_name="inventory_records")
    op.drop_table("inventory_records")

    op.drop_index("ix_facility_access_keys_key_hash", table_name="facility_access_keys")
    op.drop_index("ix_facility_access_keys_facility_id", table_name="facility_access_keys")
    op.drop_table("facility_access_keys")

    op.drop_index("ix_medicines_name", table_name="medicines")
    op.drop_table("medicines")

    op.drop_index("ix_facilities_district", table_name="facilities")
    op.drop_index("ix_facilities_name", table_name="facilities")
    op.drop_table("facilities")
