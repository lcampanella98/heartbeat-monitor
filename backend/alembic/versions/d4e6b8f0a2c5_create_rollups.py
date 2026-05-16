"""create_hourly_and_daily_rollups

Revision ID: d4e6b8f0a2c5
Revises: c5f3b2e8d1a7
Create Date: 2026-05-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d4e6b8f0a2c5"
down_revision: Union[str, Sequence[str], None] = "c5f3b2e8d1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hourly_rollups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint_id", sa.BigInteger(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_checks", sa.Integer(), nullable=False),
        sa.Column("successful_checks", sa.Integer(), nullable=False),
        sa.Column("failed_checks", sa.Integer(), nullable=False),
        sa.Column("uptime_pct", sa.Numeric(5, 2), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "endpoint_id", "bucket_start", name="uq_hourly_rollups_endpoint_bucket"
        ),
    )

    op.create_table(
        "daily_rollups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint_id", sa.BigInteger(), nullable=False),
        sa.Column("bucket_date", sa.Date(), nullable=False),
        sa.Column("total_checks", sa.Integer(), nullable=False),
        sa.Column("successful_checks", sa.Integer(), nullable=False),
        sa.Column("failed_checks", sa.Integer(), nullable=False),
        sa.Column("uptime_pct", sa.Numeric(5, 2), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "endpoint_id", "bucket_date", name="uq_daily_rollups_endpoint_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_rollups")
    op.drop_table("hourly_rollups")
