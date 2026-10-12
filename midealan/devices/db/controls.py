"""Verified parameter protocol for washer SN8 38131140, subtype 13145."""

from typing import ClassVar

from midealan.const import DeviceType
from midealan.devices.laundry import (
    APPOINTMENT_TIME_END,
    APPOINTMENT_TIME_OFFSET,
    PAUSE_COMMAND,
    PROGRAM_OFFSET,
    START_COMMAND,
    STATUS_OFFSET,
    ControlAttributes,
    ControlValue,
    LaundryControls,
    ParameterField,
    option_label,
    parameter_body,
)
from midealan.exceptions import ValueWrongType

PROFILE_MODEL = "38131140"
PROFILE_SUBTYPE = 13145
MINIMUM_STATUS_LENGTH = 31
STATUS_IDLE = 0
STATUS_STANDBY = 1
STATUS_END = 4
TEMPERATURE_OFFSET = 7
SPIN_SPEED_OFFSET = 8
WATER_LEVEL_OFFSET = 5
DETERGENT_OFFSET = 11
MODE_OFFSET = 3
NORMAL_MODE = 0
RINSE_OFFSET = 6
NIBBLE_SHIFT = 4
KEEP_DRYER_NIBBLE = 0x0F
WASH_REQUEST_OFFSET = 9
SPIN_REQUEST_OFFSET = 10
WASH_MINUTES_OFFSET = 27
SPIN_MINUTES_OFFSET = 28
MINUTE_SENTINEL = 254
WASH_MINUTE_OFFSETS = (0, 5, 10, 15, -3)
SPIN_MINUTE_OFFSETS = (0, 1, 2, -2, -1)
FRESH_STATUS_LENGTH = 56
FRESH_REPORT_OFFSET = 55
FRESH_REPORT_MASK = 0x20
FRESH_BODY_LENGTH = 54
V2_CONTROL_OFFSET = 22
V2_CONTROL_VERSION = 2
FRESH_CONTROL_OFFSET = 24
FRESH_OFF = 0x3F
FRESH_ON = 0x7F
BASIC_PARAMETER_START = 3
BASIC_PARAMETER_END = 16
CLOUD_PROGRAM_START = 36
CLOUD_PROGRAM_END = 38
STATUS_DELAY = 6
STATUS_DELAY_PAUSE = 8
APPOINTMENT_REPORT_OFFSET = 13
APPOINTMENT_REPORT_MASK = 0x02
APPOINTMENT_CONTROL_OFFSET = 35
APPOINTMENT_OFF = 0xF3
APPOINTMENT_ON = 0xF7

PROGRAMS = {
    31: "water_mixed_wash",
    2: "fast_wash",
    9: "single_dehytration",
    10: "rinsing_dehydration",
    23: "fast_wash_30",
    11: "big",
    100: "tub_clean",
    163: "deep_tub_clean",
    15: "down_jacket",
    30: "new_water_cotton",
    20: "baby_clothes",
    24: "shirt",
    103: "wool",
    34: "water_underwear",
    56: "silk",
    62: "jacket",
    55: "new_clothes_wash",
    54: "jean",
    32: "water_fiber",
    36: "water_eco",
    25: "water_intelligent",
    26: "water_steep",
    97: "water_cold_wash",
    6: "sterilization_wash",
    99: "water_remove_mite_wash",
    112: "disinfection_wash",
    132: "stain_wash",
    8: "sport_clothes",
    147: "yoga",
    145: "quick_drying_clothes",
}

TIME_FIELDS = {
    ControlAttributes.wash_time_control: (
        WASH_REQUEST_OFFSET,
        WASH_MINUTES_OFFSET,
        WASH_MINUTE_OFFSETS,
    ),
    ControlAttributes.spin_time_control: (
        SPIN_REQUEST_OFFSET,
        SPIN_MINUTES_OFFSET,
        SPIN_MINUTE_OFFSETS,
    ),
}


class DBControls(LaundryControls):
    """Decode confirmed options and preserve the washer's unrelated parameters."""

    device_type = DeviceType.DB
    minimum_status_length = MINIMUM_STATUS_LENGTH
    editable_statuses = (STATUS_IDLE, STATUS_STANDBY, STATUS_END)
    appointment_statuses = (STATUS_DELAY, STATUS_DELAY_PAUSE)
    fields: ClassVar[dict[ControlAttributes, ParameterField]] = {
        ControlAttributes.program_control: ParameterField(PROGRAM_OFFSET, PROGRAMS),
        ControlAttributes.temperature_control: ParameterField(
            TEMPERATURE_OFFSET,
            {1: "cold", 2: "20", 3: "30", 4: "40", 5: "60", 6: "95"},
        ),
        ControlAttributes.spin_speed_control: ParameterField(
            SPIN_SPEED_OFFSET,
            {0: "0", 1: "400", 2: "600", 3: "800", 4: "1000", 5: "1200", 6: "1400"},
        ),
        ControlAttributes.water_level_control: ParameterField(
            WATER_LEVEL_OFFSET,
            {5: "auto", 1: "l1", 2: "l2", 3: "l3", 4: "l4"},
        ),
        ControlAttributes.detergent_control: ParameterField(
            DETERGENT_OFFSET,
            {4: "smart", 0: "off", 1: "l1", 2: "l2", 3: "l3", 5: "l4"},
        ),
        ControlAttributes.rinse_count: ParameterField(
            RINSE_OFFSET,
            {1: "1", 2: "2", 3: "3", 4: "4"},
        ),
    }
    attribute_keys = (
        *fields,
        ControlAttributes.wash_time_control,
        ControlAttributes.spin_time_control,
        ControlAttributes.forget_free,
    )

    def is_editable(self) -> bool:
        """Only edit a standby washer in normal operating mode."""
        return super().is_editable() and self.body[MODE_OFFSET] == NORMAL_MODE

    def appointment_enabled(self) -> bool:
        """Read the washer's single-bit reservation flag."""
        return bool(self.body[APPOINTMENT_REPORT_OFFSET] & APPOINTMENT_REPORT_MASK)

    def appointment_available(self) -> bool:
        """Require the V2 cloud-cycle fields and normal operating mode."""
        return (
            super().appointment_available()
            and len(self.body) >= CLOUD_PROGRAM_END
            and self.body[MODE_OFFSET] == NORMAL_MODE
        )

    def encode_appointment(self, *, enabled: bool, wait: int) -> bytearray:
        """Register/cancel atomically, preserving the complete cloud program."""
        body = parameter_body(FRESH_BODY_LENGTH)
        body[BASIC_PARAMETER_START:BASIC_PARAMETER_END] = self.body[
            BASIC_PARAMETER_START:BASIC_PARAMETER_END
        ]
        body[STATUS_OFFSET] = START_COMMAND if enabled else PAUSE_COMMAND
        body[APPOINTMENT_REPORT_OFFSET] = self.body[
            APPOINTMENT_REPORT_OFFSET
        ] & ~APPOINTMENT_REPORT_MASK | (APPOINTMENT_REPORT_MASK if enabled else 0)
        body[APPOINTMENT_TIME_OFFSET:APPOINTMENT_TIME_END] = wait.to_bytes(2, "little")
        body[V2_CONTROL_OFFSET] = V2_CONTROL_VERSION
        body[APPOINTMENT_CONTROL_OFFSET] = (
            APPOINTMENT_ON if enabled else APPOINTMENT_OFF
        )
        body[CLOUD_PROGRAM_START:CLOUD_PROGRAM_END] = self.body[
            CLOUD_PROGRAM_START:CLOUD_PROGRAM_END
        ]
        return body

    def minute_codes(self, attr: ControlAttributes) -> dict[str, int]:
        """Calculate options from effective minutes and the request level."""
        if not self.body:
            return {}
        request_offset, minutes_offset, offsets = TIME_FIELDS[attr]
        request, actual = self.body[request_offset], self.body[minutes_offset]
        if request >= len(offsets) or not 0 < actual < MINUTE_SENTINEL:
            return {}
        base = actual - offsets[request]
        if base + min(offsets) <= 0:
            return {}
        return {
            str(base + offsets[code]): code
            for code in sorted(range(len(offsets)), key=lambda code: offsets[code])
            if 0 < base + offsets[code] < MINUTE_SENTINEL
        }

    def decode(self) -> dict[ControlAttributes, ControlValue]:
        """Keep unsupported fields unknown and request codes separate from minutes."""
        values = super().decode()
        values[ControlAttributes.rinse_count] = self.fields[
            ControlAttributes.rinse_count
        ].options.get(self.body[RINSE_OFFSET] >> NIBBLE_SHIFT)
        for attr, (_, minutes_offset, _) in TIME_FIELDS.items():
            values[attr] = (
                str(self.body[minutes_offset]) if self.minute_codes(attr) else None
            )
        values[ControlAttributes.forget_free] = (
            bool(self.body[FRESH_REPORT_OFFSET] & FRESH_REPORT_MASK)
            if len(self.body) >= FRESH_STATUS_LENGTH
            else None
        )
        return values

    def options(self, attr: str) -> list[str]:
        """Return dynamic actual-minute options where the report supports them."""
        key = ControlAttributes(attr)
        if key in TIME_FIELDS:
            return list(self.minute_codes(key))
        return super().options(attr)

    def encode(self, attr: ControlAttributes, value: bool | float | str) -> bytearray:
        """Write one parameter without powering or starting the appliance."""
        if attr == ControlAttributes.forget_free:
            return self.encode_fresh(value)
        if attr in TIME_FIELDS:
            codes = self.minute_codes(attr)
            label = option_label(value)
            if label not in codes:
                raise ValueError(f"Unsupported time for the current program: {label}")
            body = parameter_body()
            body[TIME_FIELDS[attr][0]] = codes[label]
            return body
        body = super().encode(attr, value)
        if attr == ControlAttributes.rinse_count:
            body[RINSE_OFFSET] = body[RINSE_OFFSET] << NIBBLE_SHIFT | KEEP_DRYER_NIBBLE
        return body

    def encode_fresh(self, value: bool | float | str) -> bytearray:
        """Use fresh_anion_switch, retaining complete parameters and cloud cycle."""
        if not isinstance(value, bool):
            raise ValueWrongType("Forget-free requires bool")
        body = parameter_body(FRESH_BODY_LENGTH)
        body[BASIC_PARAMETER_START:BASIC_PARAMETER_END] = self.body[
            BASIC_PARAMETER_START:BASIC_PARAMETER_END
        ]
        body[V2_CONTROL_OFFSET] = V2_CONTROL_VERSION
        body[FRESH_CONTROL_OFFSET] = FRESH_ON if value else FRESH_OFF
        # Unlike ordinary parameter bytes, FF here changes the selected cycle
        # and resets temperature/time defaults on this model.
        body[CLOUD_PROGRAM_START:CLOUD_PROGRAM_END] = self.body[
            CLOUD_PROGRAM_START:CLOUD_PROGRAM_END
        ]
        return body
