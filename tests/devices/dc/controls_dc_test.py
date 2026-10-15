"""DC parameter controls regression tests from anonymous status bodies."""

from unittest.mock import patch

import pytest

from midealan.const import ProtocolVersion
from midealan.device import MideaDeviceInitKwargs
from midealan.devices.dc import MideaDCDevice
from midealan.devices.dc.message import ControlAttributes as Attr
from midealan.message import MessageType

DC_BODY = bytes.fromhex(
    "03000000020000000002000000000000015a0000dc3734730000200001010000"
    "0000000001000000000001",
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
    return bytes([170] + [0] * 7 + [ProtocolVersion.V1, message_type]) + body + b"\x00"


def dryer(body: bytes | bytearray | None = None) -> MideaDCDevice:
    """Normalize operating state without altering the captured extended fields."""
    args = BASE_ARGS.copy()
    args["model"], args["subtype"] = ("38208801", 13367)
    device = MideaDCDevice(customize="", **args)
    if body is None:
        report = bytearray(DC_BODY)
        report[0:3] = bytes([3, 1, 1])
        report[4], report[9], report[11] = (43, 2, 1)
        report[12] = report[12] & ~12 | 4
        report[13] = report[13] & ~12 | 4
        report[36] = 1
    else:
        report = bytearray(body)
    device.process_message(frame(report))
    return device


@pytest.mark.parametrize(
    ("cls", "model", "subtype"),
    [(MideaDCDevice, "38208801", 13367)],
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
        (Attr.program_control, "big_dry", 4, 43),
        (Attr.program_control, "hanfu_ming", 4, 88),
        (Attr.program_control, "pet_sterilize", 4, 114),
        (Attr.dryness_control, "ready_to_wear", 9, 2),
        (Attr.anti_wrinkle, False, 12, 243),
        (Attr.anti_wrinkle, True, 12, 247),
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


@pytest.mark.parametrize(("enabled", "mode", "flag"), [(False, 0, 243), (True, 1, 247)])
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
    expected[11], expected[13] = (mode, flag)
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
    assert (body[12], body[24], body[28], body[29]) == (247, 2, 0, DC_BODY[42])
    assert device.attributes == before


@pytest.mark.parametrize("extra", [0, 170])
def test_timed_extra_is_additional_time_not_total_duration(extra: int) -> None:
    """The device adds ten minutes to the requested 0..170 minute extension."""
    device = dryer()
    report = bytearray(DC_BODY)
    report[0:3] = bytes([3, 1, 1])
    report[4], report[5], report[6] = (26, 0, 0)
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


def test_missing_extended_fields_and_short_acknowledgements() -> None:
    """Acks preserve state; missing temperature fields disable writes."""
    device = dryer()
    before = dict(device.attributes)
    device.process_message(frame(bytes([2] + [255] * 32), MessageType.set))
    assert device.attributes == before
    device.process_message(frame(DC_BODY[:30]))
    assert device.get_attribute(Attr.temperature_control) is None
