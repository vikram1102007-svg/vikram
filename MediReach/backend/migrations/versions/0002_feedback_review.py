"""Track facility staff acknowledgement of feedback signals.

Revision ID: 0002_feedback_review
Revises: 0001_initial
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_feedback_review"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "availability_feedback",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "availability_feedback",
        sa.Column(
            "reviewed_by_access_key_id",
            sa.Integer(),
            sa.ForeignKey(
                "facility_access_keys.id",
                ondelete="RESTRICT",
                name="fk_availability_feedback_reviewed_by_access_key_id",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_availability_feedback_reviewed_by_access_key_id",
        "availability_feedback",
        ["reviewed_by_access_key_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_availability_feedback_reviewed_by_access_key_id",
        table_name="availability_feedback",
    )
    op.drop_column("availability_feedback", "reviewed_by_access_key_id")
    op.drop_column("availability_feedback", "reviewed_at")
