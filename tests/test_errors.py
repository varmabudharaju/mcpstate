from mcpstate.errors import (
    BackendError,
    HandleExpired,
    HandleNotFound,
    McpStateError,
    PatchError,
    StaleWrite,
)


def test_payload_carries_code_message_and_details():
    err = StaleWrite("state changed", current={"version": 4}, expected_version=3)
    payload = err.to_payload()
    assert payload["code"] == "stale_write"
    assert payload["message"] == "state changed"
    assert payload["current"] == {"version": 4}
    assert payload["expected_version"] == 3


def test_all_errors_are_mcpstate_errors_with_distinct_codes():
    classes = [HandleNotFound, HandleExpired, StaleWrite, PatchError, BackendError]
    codes = {cls("x").code for cls in classes}
    assert len(codes) == 5
    assert all(issubclass(cls, McpStateError) for cls in classes)


def test_details_survive_as_attributes():
    err = HandleExpired("gone", expired_at="2026-07-20T00:00:00+00:00", ttl_days=7)
    assert err.details["ttl_days"] == 7
