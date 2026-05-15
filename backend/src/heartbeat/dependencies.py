from fastapi import Request

from heartbeat.checker import Checker
from heartbeat.clock import Clock, RealClock


def get_clock() -> Clock:
    return RealClock()


def get_checker(request: Request) -> Checker:
    return request.app.state.checker
