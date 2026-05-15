"""create_endpoints

Revision ID: 197ec6c37b39
Revises: 1e697fab1bb8
Create Date: 2026-05-15 18:31:23.622814

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op  # noqa: E402

# revision identifiers, used by Alembic.
revision: str = "197ec6c37b39"
down_revision: Union[str, Sequence[str], None] = "1e697fab1bb8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "endpoints",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("check_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_streak_outcome",
            sa.Enum("success", "failure", name="streak_outcome"),
            nullable=True,
        ),
        sa.Column("current_streak_count", sa.Integer(), nullable=False),
        sa.Column("streak_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sim_failure_rate", sa.Float(), nullable=False),
        sa.Column("sim_latency_min_ms", sa.Integer(), nullable=False),
        sa.Column("sim_latency_max_ms", sa.Integer(), nullable=False),
        sa.Column(
            "sim_outage_windows",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_endpoints_next_due_at_enabled",
        "endpoints",
        ["next_due_at"],
        unique=False,
        postgresql_where=sa.text("enabled = true"),
    )
    op.create_index("ix_endpoints_user_id", "endpoints", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_endpoints_user_id", table_name="endpoints")
    op.drop_index(
        "ix_endpoints_next_due_at_enabled",
        table_name="endpoints",
        postgresql_where=sa.text("enabled = true"),
    )
    op.drop_table("endpoints")
    op.execute(sa.text("DROP TYPE IF EXISTS streak_outcome"))
