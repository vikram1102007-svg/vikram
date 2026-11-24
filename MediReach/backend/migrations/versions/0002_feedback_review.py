"""Track facility staff acknowledgement of feedback signals.

Revision ID: 0002_feedback_review
Revises: 0001_initial
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_feedback_review"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode supports SQLite CI/local tests and emits ALTER operations on PostgreSQL.
    with op.batch_alter_table("availability_feedback") as batch_op:
        batch_op.add_column(
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reviewed_by_access_key_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_availability_feedback_reviewed_by_access_key_id",
            "facility_access_keys",
            ["reviewed_by_access_key_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_availability_feedback_reviewed_by_access_key_id",
            ["reviewed_by_access_key_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("availability_feedback") as batch_op:
        batch_op.drop_index("ix_availability_feedback_reviewed_by_access_key_id")
        batch_op.drop_constraint(
            "fk_availability_feedback_reviewed_by_access_key_id",
            type_="foreignkey",
        )
        batch_op.drop_column("reviewed_by_access_key_id")
        batch_op.drop_column("reviewed_at")
