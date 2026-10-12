"""Shared framing and state guards for verified laundry parameter controls."""

from enum import StrEnum
from typing import ClassVar, NamedTuple

from midealan.const import DeviceType
from midealan.exceptions import ValueWrongType
from midealan.message import ListTypes, MessageRequest, MessageType

UNCHANGED = 0xFF
PARAMETER_BODY_LENGTH = 22
POWER_OFFSET = 1
STATUS_OFFSET = 2
PROGRAM_OFFSET = 4
STATUS_BODY_TYPES = (0x03, 0x04)

type ControlValue = bool | int | str | None


class ControlAttributes(StrEnum):
    """Opt-in attributes, separate from existing laundry sensor identifiers."""

    parameter_control_supported = "parameter_control_supported"
    parameter_controls_available = "parameter_controls_available"
    program_control = "program_control"
    temperature_control = "temperature_control"
    spin_speed_control = "spin_speed_control"
    water_level_control = "water_level_control"
    detergent_control = "detergent_control"
    rinse_count = "rinse_count"
    wash_time_control = "wash_time_control"
    spin_time_control = "spin_time_control"
    forget_free = "forget_free"
    dryness_control = "dryness_control"
    sterilize = "sterilize"
    anti_wrinkle = "anti_wrinkle"
    timed_extra = "timed_extra"


class ParameterField(NamedTuple):
    """Body offset and the verified raw-code to option-label mapping."""

    offset: int
    options: dict[int, str]


class LaundryParameterMessage(MessageRequest):
    """Frame a complete parameter body without appending a message ID."""

    def __init__(
        self,
        device_type: DeviceType,
        protocol_version: int,
        body: bytearray,
    ) -> None:
        """Copy a verified body; normal transport supplies header and checksum."""
        super().__init__(
            device_type=device_type,
            protocol_version=protocol_version,
            message_type=MessageType.set,
            body_type=ListTypes.X02,
        )
        self._parameters = body[1:]

    @property
    def _body(self) -> bytearray:
        """Return parameters following the body type byte."""
        return self._parameters


def parameter_body(length: int = PARAMETER_BODY_LENGTH) -> bytearray:
    """Build a no-change body, including no change to power and start."""
    return bytearray([ListTypes.X02] + [UNCHANGED] * (length - 1))


def option_label(value: bool | float | str) -> str:
    """Normalize integer option values without accepting booleans as numbers."""
    if isinstance(value, bool):
        raise ValueWrongType("Laundry select parameters require an option, not bool")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class LaundryControls:
    """Keep confirmed controls read-only until a real editable status arrives."""

    device_type: ClassVar[DeviceType]
    fields: ClassVar[dict[ControlAttributes, ParameterField]]
    attribute_keys: ClassVar[tuple[ControlAttributes, ...]]
    editable_statuses: ClassVar[tuple[int, ...]]
    minimum_status_length: ClassVar[int]

    def __init__(self) -> None:
        """Start without a fabricated parameter or operational state."""
        self.body = b""
        self.attributes: dict[ControlAttributes, ControlValue] = dict.fromkeys(
            self.attribute_keys,
        )
        self.attributes[ControlAttributes.parameter_control_supported] = True
        self.attributes[ControlAttributes.parameter_controls_available] = False

    def supports(self, attr: str) -> bool:
        """Return whether an attribute is a writable parameter."""
        return attr in self.attribute_keys

    def update(self, body: bytearray) -> dict[ControlAttributes, ControlValue]:
        """Replace the snapshot only from complete status/query bodies."""
        if len(body) < self.minimum_status_length or body[0] not in STATUS_BODY_TYPES:
            return {}
        self.body = bytes(body)
        self.attributes.update(dict.fromkeys(self.attribute_keys))
        self.attributes.update(self.decode())
        self.attributes[ControlAttributes.parameter_controls_available] = (
            self.is_editable()
        )
        return dict(self.attributes)

    def is_editable(self) -> bool:
        """Return whether the latest real status permits parameter editing."""
        return bool(
            self.body
            and self.body[POWER_OFFSET] == 1
            and self.body[STATUS_OFFSET] in self.editable_statuses,
        )

    def decode(self) -> dict[ControlAttributes, ControlValue]:
        """Read only verified codes; unsupported fields remain absent."""
        return {
            attr: field.options.get(self.body[field.offset])
            for attr, field in self.fields.items()
        }

    def options(self, attr: str) -> list[str]:
        """List verified options for the currently supported parameter."""
        key = ControlAttributes(attr)
        if key not in self.fields or (
            key != ControlAttributes.program_control
            and self.attributes.get(key) is None
        ):
            return []
        return list(self.fields[key].options.values())

    def make_message(
        self,
        attr: str,
        value: bool | float | str,
        protocol_version: int,
    ) -> LaundryParameterMessage:
        """Validate current state and return a frame without optimistic updates."""
        key = ControlAttributes(attr)
        if not self.is_editable():
            raise ValueError("Keep the appliance powered on and in standby")
        if (
            key != ControlAttributes.program_control
            and self.attributes.get(key) is None
        ):
            raise ValueError("This parameter is unavailable in the current program")
        return LaundryParameterMessage(
            self.device_type,
            protocol_version,
            self.encode(key, value),
        )

    def encode(self, attr: ControlAttributes, value: bool | float | str) -> bytearray:
        """Encode a verified select option, preserving all other fields."""
        label = option_label(value)
        if label not in self.options(attr):
            raise ValueError(f"Unsupported laundry option: {label}")
        field = self.fields[attr]
        code = next(code for code, option in field.options.items() if option == label)
        body = parameter_body()
        body[field.offset] = code
        return body
