from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_users_seed_row(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT id, email, name, created_at FROM users"))
    rows = result.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == 1
    assert row.email == "user@local"
    assert row.name == "User"
    assert row.created_at is not None
