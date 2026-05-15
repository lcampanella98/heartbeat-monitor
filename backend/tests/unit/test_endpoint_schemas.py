import pytest
from pydantic import ValidationError

from heartbeat.schemas.endpoint import EndpointCreate, EndpointUpdate


def test_valid_http_url() -> None:
    ep = EndpointCreate(name="x", url="http://example.com", check_interval_seconds=60)
    assert ep.url == "http://example.com"


def test_valid_https_url() -> None:
    ep = EndpointCreate(name="x", url="https://example.com/health", check_interval_seconds=300)
    assert ep.url == "https://example.com/health"


def test_defaults() -> None:
    ep = EndpointCreate(name="x", url="https://example.com", check_interval_seconds=30)
    assert ep.timeout_seconds == 10
    assert ep.enabled is True
    assert ep.sim_failure_rate == 0.0
    assert ep.sim_outage_windows == []


def test_invalid_url_scheme() -> None:
    with pytest.raises(ValidationError, match="url must start with http"):
        EndpointCreate(name="x", url="ftp://bad.com", check_interval_seconds=60)


def test_invalid_url_no_scheme() -> None:
    with pytest.raises(ValidationError, match="url must start with http"):
        EndpointCreate(name="x", url="example.com", check_interval_seconds=60)


def test_invalid_interval() -> None:
    with pytest.raises(ValidationError):
        EndpointCreate(name="x", url="https://ok.com", check_interval_seconds=45)


def test_valid_intervals() -> None:
    for interval in (30, 60, 300, 900):
        ep = EndpointCreate(name="x", url="https://ok.com", check_interval_seconds=interval)
        assert ep.check_interval_seconds == interval


def test_timeout_below_min() -> None:
    with pytest.raises(ValidationError):
        EndpointCreate(name="x", url="https://ok.com", check_interval_seconds=60, timeout_seconds=0)


def test_timeout_above_max() -> None:
    with pytest.raises(ValidationError):
        EndpointCreate(
            name="x", url="https://ok.com", check_interval_seconds=60, timeout_seconds=61
        )


def test_timeout_boundary_values() -> None:
    ep1 = EndpointCreate(
        name="x", url="https://ok.com", check_interval_seconds=60, timeout_seconds=1
    )
    ep2 = EndpointCreate(
        name="x", url="https://ok.com", check_interval_seconds=60, timeout_seconds=60
    )
    assert ep1.timeout_seconds == 1
    assert ep2.timeout_seconds == 60


def test_failure_rate_above_max() -> None:
    with pytest.raises(ValidationError):
        EndpointCreate(
            name="x", url="https://ok.com", check_interval_seconds=60, sim_failure_rate=1.1
        )


def test_failure_rate_below_min() -> None:
    with pytest.raises(ValidationError):
        EndpointCreate(
            name="x", url="https://ok.com", check_interval_seconds=60, sim_failure_rate=-0.1
        )


def test_update_all_none_is_valid() -> None:
    up = EndpointUpdate()
    assert up.name is None
    assert up.url is None


def test_update_partial_fields() -> None:
    up = EndpointUpdate(name="new name", timeout_seconds=30)
    dumped = up.model_dump(exclude_unset=True)
    assert dumped == {"name": "new name", "timeout_seconds": 30}


def test_update_invalid_url() -> None:
    with pytest.raises(ValidationError, match="url must start with http"):
        EndpointUpdate(url="ftp://bad.com")


def test_update_none_url_is_valid() -> None:
    up = EndpointUpdate(url=None)
    assert up.url is None


def test_empty_name_rejected() -> None:
    with pytest.raises(ValidationError, match="name must not be empty"):
        EndpointCreate(name="", url="https://ok.com", check_interval_seconds=60)


def test_whitespace_name_rejected() -> None:
    with pytest.raises(ValidationError, match="name must not be empty"):
        EndpointCreate(name="   ", url="https://ok.com", check_interval_seconds=60)


def test_update_empty_name_rejected() -> None:
    with pytest.raises(ValidationError, match="name must not be empty"):
        EndpointUpdate(name="")


def test_update_none_name_is_valid() -> None:
    up = EndpointUpdate(name=None)
    assert up.name is None


def test_inverted_latency_range_rejected() -> None:
    with pytest.raises(ValidationError, match="sim_latency_min_ms must be"):
        EndpointCreate(
            name="x",
            url="https://ok.com",
            check_interval_seconds=60,
            sim_latency_min_ms=500,
            sim_latency_max_ms=100,
        )


def test_equal_latency_range_is_valid() -> None:
    ep = EndpointCreate(
        name="x",
        url="https://ok.com",
        check_interval_seconds=60,
        sim_latency_min_ms=200,
        sim_latency_max_ms=200,
    )
    assert ep.sim_latency_min_ms == ep.sim_latency_max_ms


def test_update_inverted_latency_range_rejected() -> None:
    with pytest.raises(ValidationError, match="sim_latency_min_ms must be"):
        EndpointUpdate(sim_latency_min_ms=800, sim_latency_max_ms=200)


def test_update_partial_latency_range_not_validated() -> None:
    # Sending only one side of the range in a partial update should not raise.
    up = EndpointUpdate(sim_latency_min_ms=9999)
    assert up.sim_latency_min_ms == 9999
