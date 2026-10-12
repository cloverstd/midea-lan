"""Verified parameter protocol for dryer SN8 38208801, subtype 13367."""

from typing import ClassVar

from midealan.const import DeviceType
from midealan.devices.laundry import (
    PROGRAM_OFFSET,
    ControlAttributes,
    ControlValue,
    LaundryControls,
    ParameterField,
    option_label,
    parameter_body,
)
from midealan.exceptions import ValueWrongType

PROFILE_MODEL = "38208801"
PROFILE_SUBTYPE = 13367
MINIMUM_STATUS_LENGTH = 30
STATUS_IDLE = 0
STATUS_STANDBY = 1
STATUS_PAUSE = 3
STATUS_END = 4
STATUS_PREVENT_WRINKLE_END = 5
DRY_TIME_OFFSET = 5
DRY_TIME_END = 7
DRYNESS_OFFSET = 9
DRYNESS_READY_TO_WEAR = 2
DRYNESS_STORAGE = 3
STERILIZE_MODE_OFFSET = 11
ANTI_WRINKLE_OFFSET = 12
STERILIZE_FLAG_OFFSET = 13
FEATURE_SHIFT = 2
FEATURE_MASK = 0x03
FEATURE_OFF = 0xF3
FEATURE_ON = 0xF7
EXTENDED_STATUS_LENGTH = 43
TEMPERATURE_REPORT_OFFSET = 36
SEASON_REPORT_OFFSET = 42
TEMPERATURE_BODY_LENGTH = 33
TEMPERATURE_CONTROL_OFFSET = 24
RESERVED_CONTROL_OFFSET = 28
SEASON_CONTROL_OFFSET = 29
TIMED_PROGRAM = 26
TIMED_EXTRA_MAX = 170
TIMED_EXTRA_STEP = 10
UNKNOWN_CODE = 0xFF

PROGRAMS = {
    2: "mixed_wash",
    8: "wool",
    27: "night_dry",
    43: "big_dry",
    42: "small_piece_dry",
    14: "baby_clothes",
    6: "down_jacket",
    17: "quick_dry",
    0: "cotton",
    15: "shirt",
    3: "jean",
    13: "underwear",
    64: "school_uniform",
    48: "silk",
    22: "towel",
    100: "chiffon",
    97: "polar_fleece",
    62: "hanfu",
    85: "hanfu_tang",
    86: "hanfu_song",
    88: "hanfu_ming",
    87: "hanfu_modern",
    45: "sun_quilt",
    47: "bucket_self_clean",
    24: "steam_care",
    26: "fixed_time_dry",
    33: "warm_clothes",
    10: "cold_air_fresh_air",
    83: "sterilize_mite",
    28: "bracket_dry",
    114: "pet_sterilize",
    12: "sport_clothes",
    5: "outdoor",
    98: "quick_drying_clothes",
    99: "yoga",
    39: "air_wash",
}
TEMPERATURE_OPTIONS = {1: "standard", 2: "low"}


class DCControls(LaundryControls):
    """Keep real temperature, sterilization and drying intensity independent."""

    device_type = DeviceType.DC
    minimum_status_length = MINIMUM_STATUS_LENGTH
    editable_statuses = (
        STATUS_IDLE,
        STATUS_STANDBY,
        STATUS_PAUSE,
        STATUS_END,
        STATUS_PREVENT_WRINKLE_END,
    )
    fields: ClassVar[dict[ControlAttributes, ParameterField]] = {
        ControlAttributes.program_control: ParameterField(PROGRAM_OFFSET, PROGRAMS),
        ControlAttributes.dryness_control: ParameterField(
            DRYNESS_OFFSET,
            {DRYNESS_READY_TO_WEAR: "ready_to_wear", DRYNESS_STORAGE: "storage"},
        ),
    }
    attribute_keys = (
        *fields,
        ControlAttributes.temperature_control,
        ControlAttributes.sterilize,
        ControlAttributes.anti_wrinkle,
        ControlAttributes.timed_extra,
    )

    def feature(self, offset: int) -> bool | None:
        """Decode the two-bit field without turning unavailable into off."""
        code = self.body[offset] >> FEATURE_SHIFT & FEATURE_MASK
        return bool(code) if code in (0, 1) else None

    def decode(self) -> dict[ControlAttributes, ControlValue]:
        """Read actual options, including extended temperature and season data."""
        values = super().decode()
        values[ControlAttributes.anti_wrinkle] = self.feature(ANTI_WRINKLE_OFFSET)
        flag = self.feature(STERILIZE_FLAG_OFFSET)
        mode = self.body[STERILIZE_MODE_OFFSET]
        values[ControlAttributes.sterilize] = (
            flag if flag is not None and mode == int(flag) else None
        )
        values[ControlAttributes.temperature_control] = (
            TEMPERATURE_OPTIONS.get(self.body[TEMPERATURE_REPORT_OFFSET])
            if len(self.body) >= EXTENDED_STATUS_LENGTH
            and self.body[SEASON_REPORT_OFFSET] != UNKNOWN_CODE
            and values[ControlAttributes.anti_wrinkle] is not None
            else None
        )
        extra = int.from_bytes(self.body[DRY_TIME_OFFSET:DRY_TIME_END], "little")
        values[ControlAttributes.timed_extra] = (
            extra
            if self.body[PROGRAM_OFFSET] == TIMED_PROGRAM
            and 0 <= extra <= TIMED_EXTRA_MAX
            and extra % TIMED_EXTRA_STEP == 0
            else None
        )
        return values

    def options(self, attr: str) -> list[str]:
        """Reflect the real instant-wear constraint when sterilization is on."""
        key = ControlAttributes(attr)
        if key == ControlAttributes.temperature_control:
            return list(TEMPERATURE_OPTIONS.values()) if self.attributes[key] else []
        if key == ControlAttributes.dryness_control:
            if self.attributes.get(key) is None:
                return []
            if self.attributes.get(ControlAttributes.sterilize):
                return ["ready_to_wear"]
        return super().options(attr)

    def encode(self, attr: ControlAttributes, value: bool | float | str) -> bytearray:
        """Use the independently verified body layout for each parameter."""
        if attr == ControlAttributes.temperature_control:
            return self.encode_temperature(value)
        if attr in (ControlAttributes.sterilize, ControlAttributes.anti_wrinkle):
            return self.encode_feature(attr, value)
        if attr == ControlAttributes.timed_extra:
            label = option_label(value)
            if not label.isdecimal():
                raise ValueError("Timed extra must be an integer number of minutes")
            extra = int(label)
            if not 0 <= extra <= TIMED_EXTRA_MAX or extra % TIMED_EXTRA_STEP:
                raise ValueError("Timed extra must be 0..170 minutes in steps of 10")
            body = parameter_body()
            body[DRY_TIME_OFFSET:DRY_TIME_END] = extra.to_bytes(2, "little")
            return body
        return super().encode(attr, value)

    def encode_temperature(self, value: bool | float | str) -> bytearray:
        """Preserve anti-wrinkle and season with the complete extended command."""
        label = option_label(value)
        if label not in self.options(ControlAttributes.temperature_control):
            raise ValueError(f"Unsupported dryer temperature: {label}")
        code = next(
            code for code, option in TEMPERATURE_OPTIONS.items() if option == label
        )
        body = parameter_body(TEMPERATURE_BODY_LENGTH)
        body[ANTI_WRINKLE_OFFSET] = (
            FEATURE_ON
            if self.attributes[ControlAttributes.anti_wrinkle]
            else FEATURE_OFF
        )
        body[TEMPERATURE_CONTROL_OFFSET] = code
        body[RESERVED_CONTROL_OFFSET] = 0
        body[SEASON_CONTROL_OFFSET] = self.body[SEASON_REPORT_OFFSET]
        return body

    def encode_feature(
        self,
        attr: ControlAttributes,
        value: bool | float | str,
    ) -> bytearray:
        """Set both sterilization fields and enforce instant-wear when supported."""
        if not isinstance(value, bool):
            raise ValueWrongType("Dryer feature switches require bool")
        body = parameter_body()
        offset = (
            STERILIZE_FLAG_OFFSET
            if attr == ControlAttributes.sterilize
            else ANTI_WRINKLE_OFFSET
        )
        body[offset] = FEATURE_ON if value else FEATURE_OFF
        if attr == ControlAttributes.sterilize:
            body[STERILIZE_MODE_OFFSET] = int(value)
            if value and self.body[DRYNESS_OFFSET] in (
                DRYNESS_READY_TO_WEAR,
                DRYNESS_STORAGE,
            ):
                body[DRYNESS_OFFSET] = DRYNESS_READY_TO_WEAR
        return body
