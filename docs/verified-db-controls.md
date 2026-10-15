# Verified DB washer 38131140 / subtype 13145 controls

This profile requires both the exact model (from `model` or `sn8`) and subtype. Other devices retain legacy power/start and sensor behavior. Original sensor identifiers remain unchanged. Additional controls use separate attributes, with program labels corrected only for this profile.

`parameter_control_supported` and `appointment_control_supported` let HA skip the new entities on older SDKs without changing its dependency pin. `parameter_controls_available` follows real powered, editable status. Unknown fields remain `None`; running, reservation and fault states reject ordinary parameter writes.

Washer writes also reject non-normal operating modes.

## Public API

`get_parameter_options(attribute)` returns canonical option identifiers, including
dynamic actual-minute options. `set_attribute(attribute, value)` validates the
option and current state, sends a parameter frame, then queries status over the
existing connection. It never assigns optimistic state. Power and start bytes
remain `FF` in ordinary parameter frames; completion reservations are described
separately below because they explicitly register or cancel a future cycle.

DB selects: `program_control`, `temperature_control`, `spin_speed_control`,
`rinse_count`, `water_level_control`, `detergent_control`, `wash_time_control`,
`spin_time_control`; switch: `forget_free`.

## Verified protocol details

- Washer rinse count occupies the upper nibble of body byte 6; the lower nibble
  is written as `F` to preserve the drying flag.
- Washer wash request codes 0/1/2/3/4 mean default, +5, +10, +15, -3 minutes.
  In mixed wash, cold water reports 42/45/50/55/60 minutes; 30°C reports
  11/14/19/24/29. The default is inferred from the effective minutes and current
  request code, rather than interpreting the request itself as minutes.
- Washer spin request codes 0/1/2/3/4 mean default, +1, +2, -2, -1 minutes.
  The measured 8/9/10/11/12-minute options map to 3/4/0/1/2.
- Washer smart detergent is code 4; level L4 is code 5.
- Forget-free care is `fresh_anion_switch`, report byte 55 mask `20`, **not** the
  old `wind_dispel` flag. The 54-byte V2 command uses byte 22 = 2 and byte 24
  = `3F`/`7F`. It copies current basic bytes 3–15 and cloud cycle bytes 36–37;
  setting the latter to `FF` resets program presets on this model. Both default
  and custom 60/12-minute wash/spin selections were preserved during on/off tests.
  Hardware verification used standby and distant reservations, followed by cancellation and restoration of the original power state; no wash or dry cycle was executed. Fixtures contain anonymous status bodies without transport identities, serials or credentials. Manufacturer Lua was read, never executed or vendored.

Protocol references: [DB V2 manufacturer Lua](https://github.com/Cyborg2017/midea_smart_home/issues/49).

## Completion-time reservations

The profile additionally exposes `appointment_control_supported`,
`appointment_controls_available`, `appointment` and `appointment_finish`.
Reservations have a separate state guard so they can be edited or cancelled while
ordinary program parameters remain read-only.

`set_attribute("appointment_finish", timezone_bearing_iso_datetime)` registers a
**future automatic cycle**. It requires a whole-minute deadline in the next 24
hours and subtracts the current device-reported program duration to calculate
waiting minutes. A missing duration, past/over-24-hour deadline or non-positive
wait is rejected. The timestamp reported in `appointment_finish` is an estimate
based on the current wait plus program duration, cleared when the flag is off.

`set_attribute("appointment", False)` cancels: the command explicitly pauses and
clears both the reservation flag and waiting-minute request. It preserves the
selected program and other parameters. Setting `appointment=True` alone is
rejected; use the completion deadline to supply a valid positive wait.

- DB reports the flag at body byte 13 mask `02` and the little-endian wait at
  bytes 14-15. Its complete 54-byte V2 setter preserves basic and cloud-cycle
  fields, writes both the legacy flag and byte 35's two-bit field (`F7`/`F3`).

Program duration is a little-endian count of minutes.

## Other DB models awaiting verification

Model `38132386 / subtype 0` (MF201W110WB/GK-01) was reported in [the companion PR](https://github.com/wuwentao/midea_ac_lan/pull/1106#issuecomment-6181549300) with the same `T_0000_DB_41.lua` as the public protocol repository. A shared Lua encoder describes possible fields; it does not confirm that both models share the same program list, V2 cloud selector, minute-option rules or forget-free extension.

Before enabling a separate profile, compare anonymized, complete query/notify bodies while powered on in standby with the app's program and parameter values. Capture before/after reports for one parameter at a time (program, temperature, spin, rinse), the options offered by the app, and the status-body length/version. Omit account credentials, serials, device IDs, tokens, keys and transport headers. The current profile stays disabled for this identity until those mappings are verified; do not change the subtype to impersonate the tested model.
