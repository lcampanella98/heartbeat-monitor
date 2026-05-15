from unittest.mock import AsyncMock, patch

import pytest

from heartbeat.main import app, lifespan


async def test_lifespan_raises_when_db_unreachable(db_engine) -> None:
    err = OSError("DB unreachable")
    with patch("heartbeat.main.check_db_connection", new_callable=AsyncMock, side_effect=err):
        with pytest.raises(OSError, match="DB unreachable"):
            async with lifespan(app):
                pass
