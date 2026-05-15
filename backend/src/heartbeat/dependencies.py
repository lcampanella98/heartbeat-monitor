from heartbeat.clock import Clock, RealClock


def get_clock() -> Clock:
    return RealClock()
