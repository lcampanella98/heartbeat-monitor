from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from heartbeat.checker import Checker
from heartbeat.clock import Clock, RealClock

if TYPE_CHECKING:
    from heartbeat.rollup import RollupJob


def get_clock() -> Clock:
    return RealClock()


def get_checker(request: Request) -> Checker:
    return request.app.state.checker


def get_rollup_job(request: Request) -> "RollupJob":
    return request.app.state.rollup_job
