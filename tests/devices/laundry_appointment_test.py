"""Reservations from anonymized app replies and guarded command encoding."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from midealan.devices.db import MideaDBDevice
from midealan.devices.dc import MideaDCDevice
from midealan.devices.laundry import ControlAttributes as Attr
from midealan.exceptions import ValueWrongType
from tests.devices.laundry_controls_test import (
    BASE_ARGS,
    DB_BODY,
    DC_BODY,
    dryer,
    frame,
    washer,
)

DB_RESERVED = bytes.fromhex(
    "040106001f0540060303020400427a01208a0000db5933b10000003f0c08000002"
    "ffff000000ffffffffffffffff140101ffffffff01ff200000080000",
)
DC_RESERVED = bytes.fromhex(
    "0401080002000000000200000100a601015a0000dc37347300002000010100000000000001000000000001",
)
NOW = datetime(2026, 10, 12, 15, 24, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("factory", "report", "wait", "duration", "status"),
    [(washer, DB_RESERVED, 378, 138, "delay"), (dryer, DC_RESERVED, 422, 90, "delay")],
)
def test_app_reservations_and_start_state(
    factory: Callable[..., MideaDBDevice | MideaDCDevice],
    report: bytes,
    wait: int,
    duration: int,
    status: str,
) -> None:
    """Real app reservations count as active and retain independent editing guards."""
    with patch("midealan.devices.laundry.datetime") as clock:
        clock.now.return_value = NOW
        device = factory(report)
    assert device.get_attribute(Attr.appointment) is True
    assert device.get_attribute("start") is True
    assert device.get_attribute("status") == status
    assert device.get_attribute("time_remaining") == duration
    assert device.get_attribute(Attr.parameter_controls_available) is False
    assert device.get_attribute(Attr.appointment_controls_available) is True
    finish_value = device.get_attribute(Attr.appointment_finish)
    assert isinstance(finish_value, str)
    finish = datetime.fromisoformat(finish_value)
    assert finish == NOW.replace(second=0) + timedelta(minutes=wait + duration)


@pytest.mark.parametrize("factory", [washer, dryer])
def test_finish_time_subtracts_program_duration_and_is_not_optimistic(
    factory: Callable[..., MideaDBDevice | MideaDCDevice],
) -> None:
    """Use a timezone-bearing deadline, not total minutes until completion."""
    device = factory()
    assert device._controls is not None
    before = dict(device.attributes)
    target = (NOW.replace(second=0) + timedelta(hours=10)).isoformat()
    duration = device.get_attribute("time_remaining")
    assert isinstance(duration, int)
    with (
        patch("midealan.devices.laundry.datetime") as clock,
        patch.object(device, "build_send") as send,
    ):
        clock.now.return_value = NOW
        clock.fromisoformat.side_effect = datetime.fromisoformat
        device.set_attribute(Attr.appointment_finish, target)
    body = send.call_args_list[0].args[0].body
    assert body[1] == 255
    assert body[2] == 1
    assert int.from_bytes(body[14:16], "little") == 600 - duration
    assert body[3:12] == (DB_BODY if factory is washer else device._controls.body)[3:12]
    assert device.attributes == before
    assert send.call_args_list[1].args[0].body == b"\x03"
    if factory is washer:
        assert len(body) == 54
        assert body[13] == DB_BODY[13] | 2
        assert body[22] == 2
        assert body[35] == 0xF7
        assert body[36:38] == DB_BODY[36:38]
    else:
        assert len(body) == 22
        assert body[12] == 0xFD
        assert body[13] == device._controls.body[13]


@pytest.mark.parametrize(
    ("factory", "report"),
    [(washer, DB_RESERVED), (dryer, DC_RESERVED)],
)
def test_cancel_pauses_and_clears_both_fields_without_starting(
    factory: Callable[..., MideaDBDevice | MideaDCDevice],
    report: bytes,
) -> None:
    """Cancel pauses explicitly; clearing only the wait could start immediately."""
    device = factory(report)
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.appointment, False)
    body = send.call_args_list[0].args[0].body
    assert body[1:3] == bytes([255, 0])
    assert body[14:16] == bytes(2)
    assert body[3:12] == report[3:12]
    if factory is washer:
        assert body[13] == report[13] & ~2
        assert body[22] == 2
        assert body[35] == 0xF3
        assert body[36:38] == report[36:38]
    else:
        assert body[12] == 0xFC
        assert body[13] == report[13]
    assert device.get_attribute(Attr.appointment) is True
    cancelled = bytearray(report)
    cancelled[2], cancelled[14], cancelled[15] = 1, 0, 0
    cancelled[13 if factory is washer else 12] &= ~2 if factory is washer else ~3
    device.process_message(frame(cancelled))
    assert device.get_attribute(Attr.appointment) is False
    assert device.get_attribute(Attr.appointment_finish) is None
    assert device.get_attribute("start") is False


@pytest.mark.parametrize("factory", [washer, dryer])
@pytest.mark.parametrize("value", [True, False, 0, 170.5, "bad", "2026-10-13T08:00:00"])
def test_invalid_completion_values_never_send(
    factory: Callable[..., MideaDBDevice | MideaDCDevice],
    value: bool | float | str,
) -> None:
    """Reject invalid types, syntax and naive local timestamps before sending."""
    device = factory()
    assert device._controls is not None
    with (
        patch.object(device, "build_send") as send,
        pytest.raises((ValueError, ValueWrongType)),
    ):
        device.set_attribute(Attr.appointment_finish, value)
    send.assert_not_called()


@pytest.mark.parametrize("factory", [washer, dryer])
@pytest.mark.parametrize("offset", [-1, 0, 1, 60, 1500])
def test_too_early_past_and_over_24h_targets_never_send(
    factory: Callable[..., MideaDBDevice | MideaDCDevice],
    offset: int,
) -> None:
    """Reject deadlines that cannot leave a positive safe wait."""
    device = factory()
    assert device._controls is not None
    target = (NOW.replace(second=0) + timedelta(minutes=offset)).isoformat()
    with (
        patch("midealan.devices.laundry.datetime") as clock,
        patch.object(device, "build_send") as send,
    ):
        clock.now.return_value = NOW
        clock.fromisoformat.side_effect = datetime.fromisoformat
        with pytest.raises(ValueError, match="Completion time"):
            device.set_attribute(Attr.appointment_finish, target)
    send.assert_not_called()


@pytest.mark.parametrize("factory", [washer, dryer])
@pytest.mark.parametrize(("power", "status"), [(0, 1), (1, 2), (1, 3), (1, 7)])
def test_reservation_cannot_interrupt_running_paused_or_faulted_cycle(
    factory: Callable[..., MideaDBDevice | MideaDCDevice],
    power: int,
    status: int,
) -> None:
    """Reservations cannot change a running or paused actual cycle."""
    device = factory()
    assert device._controls is not None
    report = bytearray(device._controls.body)
    report[1], report[2] = power, status
    device.process_message(frame(report))
    assert device.get_attribute(Attr.appointment_controls_available) is False
    with (
        patch.object(device, "build_send") as send,
        pytest.raises(ValueError, match="standby"),
    ):
        device.set_attribute(Attr.appointment, False)
    send.assert_not_called()


@pytest.mark.parametrize(
    ("status", "active"),
    [(1, False), (2, True), (3, False), (6, False), (8, True), (9, False)],
)
def test_dryer_start_reflects_running_and_active_reservation_only(
    status: int,
    active: bool,
) -> None:
    """Scope the corrected start state to the verified dryer only."""
    report = bytearray(DC_RESERVED)
    report[2] = status
    assert dryer(report).get_attribute("start") is active
    legacy = MideaDCDevice(customize="", **BASE_ARGS)
    legacy.process_message(frame(report))
    assert legacy.get_attribute("start") is (status in (2, 6))


def test_dryer_resuming_reservation_keeps_wait_high_byte() -> None:
    """Resume preserves all sixteen bits of the queued delay."""
    device = dryer(DC_RESERVED)
    with patch.object(device, "build_send") as send:
        device.set_attribute("start", True)
    assert send.call_args.args[0].body[3:16] == DC_RESERVED[3:16]
    assert send.call_args.args[0].body[14:16] == (422).to_bytes(2, "little")


def test_dryer_can_edit_or_cancel_a_selected_but_not_started_reservation() -> None:
    """Status 6 occurs after setting only the flag/wait with start unchanged."""
    report = bytearray(DC_RESERVED)
    report[2] = 6
    device = dryer(report)
    assert device.get_attribute("start") is False
    assert device.get_attribute(Attr.parameter_controls_available) is False
    assert device.get_attribute(Attr.appointment_controls_available) is True
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.appointment, False)
    assert send.call_args_list[0].args[0].body[2] == 0
    assert send.call_args_list[0].args[0].body[12] == 0xFC


def test_dryer_verified_duration_above_255_uses_minutes_not_hours() -> None:
    """Verified dryers report a sixteen-bit minute duration."""
    report = bytearray(DC_RESERVED)
    report[17:19] = (300).to_bytes(2, "little")
    assert dryer(report).get_attribute("time_remaining") == 300


def test_unsupported_reservation_flag_and_short_v2_report_are_read_only() -> None:
    """Unknown flags and missing extended fields disable reservation writes."""
    report = bytearray(DC_BODY)
    report[1:3] = bytes([1, 1])
    report[12] = 3
    device = dryer(report)
    assert device.get_attribute(Attr.appointment) is None
    assert device.get_attribute(Attr.appointment_controls_available) is False
    device_db = washer(DB_BODY[:31])
    assert device_db.get_attribute(Attr.appointment_controls_available) is False
    with (
        patch.object(device_db, "build_send") as send,
        pytest.raises(ValueError, match="standby"),
    ):
        device_db.set_attribute(Attr.appointment, False)
    send.assert_not_called()
