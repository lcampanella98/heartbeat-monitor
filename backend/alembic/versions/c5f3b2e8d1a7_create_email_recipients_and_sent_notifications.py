"""create_email_recipients_and_sent_notifications

Revision ID: c5f3b2e8d1a7
Revises: b2e8f7a6d3c9
Create Date: 2026-05-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c5f3b2e8d1a7"
down_revision: Union[str, Sequence[str], None] = "b2e8f7a6d3c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_recipients",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "address", name="uq_email_recipients_user_address"),
    )

    op.create_table(
        "sent_notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("incident_opened", "incident_closed", name="notification_kind"),
            nullable=False,
        ),
        sa.Column("incident_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sent_notifications")
    op.execute(sa.text("DROP TYPE IF EXISTS notification_kind"))
    op.drop_table("email_recipients")
