"""Regression tests from anonymized, standby-only DB/DC model verification."""

from unittest.mock import patch

import pytest

from midealan.const import ProtocolVersion
from midealan.device import MideaDeviceInitKwargs
from midealan.devices.db import MideaDBDevice
from midealan.devices.dc import MideaDCDevice
from midealan.devices.laundry import ControlAttributes as Attr
from midealan.exceptions import ValueWrongType
from midealan.message import MessageType

DB_BODY = bytes.fromhex(
    "030101001f0520010300030400400000204f0000db5933b10000002d0808000002"
    "ffff000000ffffffffffffffff140101ffffffff01ff200000080000",
)
DC_BODY = bytes.fromhex(
    "03000000020000000002000000000000015a0000dc37347300002000010100000000000001000000000001",
)
BASE_ARGS: MideaDeviceInitKwargs = {
    "name": "Test laundry appliance",
    "device_id": 1,
    "ip_address": "192.0.2.1",
    "port": 6444,
    "token": "00",
    "key": "00",
    "device_protocol": ProtocolVersion.V1,
    "model": "test",
    "subtype": 0,
}


def frame(
    body: bytes | bytearray,
    message_type: MessageType = MessageType.query,
) -> bytes:
    """Use an identity-free header; direct decoders do not validate its checksum."""
    return bytes([0xAA] + [0] * 7 + [ProtocolVersion.V1, message_type]) + body + b"\x00"


def washer(body: bytes | bytearray = DB_BODY) -> MideaDBDevice:
    """Create a verified model without opening a socket."""
    args = BASE_ARGS.copy()
    args["model"], args["subtype"] = "38131140", 13145
    device = MideaDBDevice(customize="", **args)
    device.process_message(frame(body))
    return device


def dryer(body: bytes | bytearray | None = None) -> MideaDCDevice:
    """Normalize operating state without altering the captured extended fields."""
    args = BASE_ARGS.copy()
    args["model"], args["subtype"] = "38208801", 13367
    device = MideaDCDevice(customize="", **args)
    if body is None:
        report = bytearray(DC_BODY)
        report[0:3] = bytes([3, 1, 1])
        report[4], report[9], report[11] = 43, 2, 1
        report[12] = report[12] & ~12 | 4
        report[13] = report[13] & ~12 | 4
        report[36] = 1
    else:
        report = bytearray(body)
    device.process_message(frame(report))
    return device


@pytest.mark.parametrize(
    ("cls", "model", "subtype"),
    [
        (MideaDBDevice, "38131140", 13145),
        (MideaDCDevice, "38208801", 13367),
    ],
)
def test_profile_identity_and_legacy_isolation(
    cls: type,
    model: str,
    subtype: int,
) -> None:
    """Require model and subtype; unrelated devices keep legacy behavior."""
    for wrong_model, wrong_subtype in [("other", subtype), (model, subtype + 1)]:
        device = cls(
            customize="",
            **dict(BASE_ARGS, model=wrong_model, subtype=wrong_subtype),
        )
        assert Attr.parameter_control_supported not in device.attributes
        assert device.get_parameter_options(Attr.program_control) == []
    device = cls(
        customize="",
        **dict(BASE_ARGS, model="marketing name", sn8=model, subtype=subtype),
    )
    assert device.get_attribute(Attr.parameter_control_supported) is True
    assert device.get_attribute(Attr.parameter_controls_available) is False
    with (
        patch.object(device, "build_send") as send,
        pytest.raises(ValueError, match=r"standby|unavailable|Timed extra"),
    ):
        device.set_attribute(Attr.program_control, "cotton")
    send.assert_not_called()


@pytest.mark.parametrize(
    ("attribute", "label", "offset", "raw"),
    [
        (Attr.program_control, "big", 4, 11),
        (Attr.program_control, "yoga", 4, 147),
        (Attr.program_control, "quick_drying_clothes", 4, 145),
        (Attr.temperature_control, "20", 7, 2),
        (Attr.spin_speed_control, "1000", 8, 4),
        (Attr.rinse_count, "3", 6, 0x3F),
        (Attr.water_level_control, "l2", 5, 2),
        (Attr.detergent_control, "l4", 11, 5),
        (Attr.detergent_control, "smart", 11, 4),
    ],
)
def test_washer_single_parameter_packets(
    attribute: str,
    label: str,
    offset: int,
    raw: int,
) -> None:
    """Use independently measured byte offsets and keep power/start/mode untouched."""
    device = washer()
    before = dict(device.attributes)
    with patch.object(device, "build_send") as send:
        device.set_attribute(attribute, label)
    expected = bytearray([2] + [255] * 21)
    expected[offset] = raw
    assert send.call_args_list[0].args[0].body == expected
    assert send.call_args_list[1].args[0].body == b"\x03"
    assert device.attributes == before, (
        "Only a real response may change displayed state"
    )
    assert len(device.get_parameter_options(Attr.program_control)) == 30


@pytest.mark.parametrize(
    ("minutes", "request_code"),
    [(42, 4), (45, 0), (50, 1), (55, 2), (60, 3)],
)
def test_wash_actual_minutes_and_non_linear_requests(
    minutes: int,
    request_code: int,
) -> None:
    """Wash requests encode minus three or increasing five-minute steps."""
    body = bytearray(DB_BODY)
    body[9], body[27] = 4, 42
    device = washer(body)
    assert device.get_parameter_options(Attr.wash_time_control) == [
        "42",
        "45",
        "50",
        "55",
        "60",
    ]
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.wash_time_control, str(minutes))
    assert send.call_args_list[0].args[0].body[9] == request_code
    body[7], body[9], body[27] = 3, 0, 14
    device.process_message(frame(body))
    assert device.get_parameter_options(Attr.wash_time_control) == [
        "11",
        "14",
        "19",
        "24",
        "29",
    ]


@pytest.mark.parametrize(
    ("minutes", "request_code"),
    [(8, 3), (9, 4), (10, 0), (11, 1), (12, 2)],
)
def test_spin_actual_minutes_and_non_linear_requests(
    minutes: int,
    request_code: int,
) -> None:
    """Spin request zero is ten minutes; it is not the shortest option."""
    device = washer()
    assert device.get_parameter_options(Attr.spin_time_control) == [
        "8",
        "9",
        "10",
        "11",
        "12",
    ]
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.spin_time_control, str(minutes))
    assert send.call_args_list[0].args[0].body[10] == request_code


@pytest.mark.parametrize(("enabled", "raw"), [(False, 0x3F), (True, 0x7F)])
def test_forget_free_preserves_custom_times_and_cloud_program(
    enabled: bool,
    raw: int,
) -> None:
    """Regression: FF cloud-cycle fields used to reset temperature and time presets."""
    report = bytearray(DB_BODY)
    report[9], report[10], report[27], report[28] = 3, 2, 60, 12
    device = washer(report)
    before = dict(device.attributes)
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.forget_free, enabled)
    body = send.call_args_list[0].args[0].body
    assert len(body) == 54
    assert body[1:3] == b"\xff\xff"
    assert body[3:16] == bytes.fromhex("001f0520010303020400400000")
    assert body[22] == 2
    assert body[24] == raw
    assert body[36:38] == b"\x00\x00"
    assert device.attributes == before


@pytest.mark.parametrize(
    ("attribute", "label", "offset", "raw"),
    [
        (Attr.program_control, "big_dry", 4, 43),
        (Attr.program_control, "hanfu_ming", 4, 88),
        (Attr.program_control, "pet_sterilize", 4, 114),
        (Attr.dryness_control, "ready_to_wear", 9, 2),
        (Attr.anti_wrinkle, False, 12, 0xF3),
        (Attr.anti_wrinkle, True, 12, 0xF7),
    ],
)
def test_dryer_parameter_packets(
    attribute: str,
    label: str | bool,
    offset: int,
    raw: int,
) -> None:
    """Program and feature writes preserve power and start."""
    device = dryer()
    with patch.object(device, "build_send") as send:
        device.set_attribute(attribute, label)
    expected = bytearray([2] + [255] * 21)
    expected[offset] = raw
    assert send.call_args_list[0].args[0].body == expected
    assert len(device.get_parameter_options(Attr.program_control)) == 36


@pytest.mark.parametrize(
    ("enabled", "mode", "flag"),
    [(False, 0, 0xF3), (True, 1, 0xF7)],
)
def test_sterilize_mode_and_flag_are_written_together(
    enabled: bool,
    mode: int,
    flag: int,
) -> None:
    """Write both fields; the old flag alone did not change the app state."""
    device = dryer()
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.sterilize, enabled)
    expected = bytearray([2] + [255] * 21)
    expected[11], expected[13] = mode, flag
    if enabled:
        expected[9] = 2
    assert send.call_args_list[0].args[0].body == expected
    assert device.get_parameter_options(Attr.dryness_control) == ["ready_to_wear"]


def test_extended_temperature_preserves_anti_wrinkle_and_season() -> None:
    """The short temperature command reset anti-wrinkle; body[11] is sterilization."""
    device = dryer()
    before = dict(device.attributes)
    assert device.get_attribute(Attr.temperature_control) == "standard"
    assert device.get_attribute(Attr.sterilize) is True
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.temperature_control, "low")
    body = send.call_args_list[0].args[0].body
    assert len(body) == 33
    assert body[1:3] == b"\xff\xff"
    assert body[11] == 255
    assert (body[12], body[24], body[28], body[29]) == (0xF7, 2, 0, DC_BODY[42])
    assert device.attributes == before


@pytest.mark.parametrize("extra", [0, 170])
def test_timed_extra_is_additional_time_not_total_duration(extra: int) -> None:
    """The device adds ten minutes to the requested 0..170 minute extension."""
    device = dryer()
    report = bytearray(DC_BODY)
    report[0:3] = bytes([3, 1, 1])
    report[4], report[5], report[6] = 26, 0, 0
    device.process_message(frame(report))
    with patch.object(device, "build_send") as send:
        device.set_attribute(Attr.timed_extra, extra)
    assert send.call_args_list[0].args[0].body[5:7] == extra.to_bytes(2, "little")
    with (
        patch.object(device, "build_send") as send,
        pytest.raises(ValueError, match=r"standby|unavailable|Timed extra"),
    ):
        device.set_attribute(Attr.timed_extra, 180)
    send.assert_not_called()


@pytest.mark.parametrize(
    ("status", "power", "mode"),
    [(2, 1, 0), (3, 1, 0), (6, 1, 0), (1, 0, 0), (1, 1, 1)],
)
def test_washer_rejects_running_off_or_service_mode(
    status: int,
    power: int,
    mode: int,
) -> None:
    """Parameter writes must not implicitly stop or start an appliance."""
    report = bytearray(DB_BODY)
    report[1], report[2], report[3] = power, status, mode
    device = washer(report)
    with (
        patch.object(device, "build_send") as send,
        pytest.raises(ValueError, match=r"standby|unavailable|Timed extra"),
    ):
        device.set_attribute(Attr.temperature_control, "20")
    send.assert_not_called()


def test_missing_extended_fields_and_short_acknowledgements() -> None:
    """Missing fields must not become defaults or keep stale writable state."""
    device = washer()
    device.process_message(frame(DB_BODY[:31]))
    assert device.get_attribute(Attr.forget_free) is None
    with (
        patch.object(device, "build_send") as send,
        pytest.raises(ValueError, match=r"standby|unavailable|Timed extra"),
    ):
        device.set_attribute(Attr.forget_free, True)
    send.assert_not_called()
    device_dc = dryer()
    before = dict(device_dc.attributes)
    device_dc.process_message(frame(bytes([2] + [255] * 32), MessageType.set))
    assert device_dc.attributes == before
    device_dc.process_message(frame(DC_BODY[:30]))
    assert device_dc.get_attribute(Attr.temperature_control) is None


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        (Attr.temperature_control, True),
        (Attr.rinse_count, "0"),
        (Attr.spin_speed_control, "1600"),
        (Attr.wash_time_control, "99"),
        (Attr.forget_free, "on"),
    ],
)
def test_invalid_washer_options_never_send(attribute: str, value: str | bool) -> None:
    """Reject unsupported or incorrectly typed options before constructing any frame."""
    device = washer()
    with (
        patch.object(device, "build_send") as send,
        pytest.raises((ValueError, ValueWrongType)),
    ):
        device.set_attribute(attribute, value)
    send.assert_not_called()
