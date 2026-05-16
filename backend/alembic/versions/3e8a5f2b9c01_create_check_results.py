"""create_check_results

Revision ID: 3e8a5f2b9c01
Revises: 197ec6c37b39
Create Date: 2026-05-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3e8a5f2b9c01"
down_revision: Union[str, Sequence[str], None] = "197ec6c37b39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # error_category enum is created automatically by op.create_table via
    # SQLAlchemy's before_create event (same pattern as streak_outcome in endpoints).
    op.create_table(
        "check_results",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint_id", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("success", "failure", name="streak_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "error_category",
            sa.Enum(
                "timeout",
                "connection_refused",
                "dns",
                "tls",
                "non_2xx",
                "other",
                name="error_category",
            ),
            nullable=True,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_check_results_endpoint_checked_at "
            "ON check_results (endpoint_id, checked_at DESC)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_check_results_endpoint_checked_at", table_name="check_results")
    op.drop_table("check_results")
    op.execute(sa.text("DROP TYPE IF EXISTS error_category"))
