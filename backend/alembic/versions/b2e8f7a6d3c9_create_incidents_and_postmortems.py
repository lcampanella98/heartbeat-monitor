"""create_incidents_and_postmortems

Revision ID: b2e8f7a6d3c9
Revises: 3e8a5f2b9c01
Create Date: 2026-05-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2e8f7a6d3c9"
down_revision: Union[str, Sequence[str], None] = "3e8a5f2b9c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "frozen_timeline",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incidents_endpoint_started_at",
        "incidents",
        ["endpoint_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "uix_incidents_endpoint_open",
        "incidents",
        ["endpoint_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "postmortems",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id", name="uq_postmortems_incident_id"),
    )


def downgrade() -> None:
    op.drop_table("postmortems")
    op.drop_index("uix_incidents_endpoint_open", table_name="incidents")
    op.drop_index("ix_incidents_endpoint_started_at", table_name="incidents")
    op.drop_table("incidents")
