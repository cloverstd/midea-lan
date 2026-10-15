# Verified DC dryer 38208801 / subtype 13367 controls

This profile requires both the exact model (from `model` or `sn8`) and subtype. Other devices retain legacy power/start and sensor behavior. Original sensor identifiers remain unchanged. Additional controls use separate attributes, with program labels corrected only for this profile.

`parameter_control_supported` and `appointment_control_supported` let HA skip the new entities on older SDKs without changing its dependency pin. `parameter_controls_available` follows real powered, editable status. Unknown fields remain `None`; running, reservation and fault states reject ordinary parameter writes.

Dryer pause permits ordinary parameter editing.

## Public API

`get_parameter_options(attribute)` returns canonical option identifiers, including
dynamic actual-minute options. `set_attribute(attribute, value)` validates the
option and current state, sends a parameter frame, then queries status over the
existing connection. It never assigns optimistic state. Power and start bytes
remain `FF` in ordinary parameter frames; completion reservations are described
separately below because they explicitly register or cancel a future cycle.

DC selects: `program_control`, `dryness_control`, `temperature_control`; switches:
`sterilize`, `anti_wrinkle`; number: `timed_extra`.

## Verified protocol details

- Dryer ready-to-wear is code 2 and storage is code 3. Code 0 is not adjustable.
  Sterilization restricts the dryness options to ready-to-wear.
- Dryer sterilization requires both mode byte 11 and the two-bit flag in byte 13. Enabling also requests ready-to-wear where dryness is supported.
- Real dryer temperature is report byte 36 (standard 1, low 2), independent of
  sterilization mode. The **33-byte** command writes byte 24 and preserves
  anti-wrinkle at byte 12 and season at byte 29, with reserved byte 28 = 0.
  A shorter extended command reset anti-wrinkle during verification.
- Dryer timed extension is 0–170 minutes, step 10, only on timed program 26.
  The device reports total duration 10–180 minutes; the library does not replace
  the actual remaining-time report with a calculated duration.
- DIY/pollen-allergy drying is omitted: there is no confirmed dedicated program
  code or write protocol. Hanfu™ program names have distinct canonical options.

Hardware verification used standby and distant reservations, followed by cancellation and restoration of the original power state; no wash or dry cycle was executed. Fixtures contain anonymous status bodies without transport identities, serials or credentials. Manufacturer Lua was read, never executed or vendored.

Protocol references: [extended temperature Lua](https://github.com/sususweet/midea_auto_cloud/issues/247), [another encoder](https://github.com/sususweet/midea_auto_cloud/issues/259).

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

- DC cancellation sends pause first, then a parameter command with start
  unchanged that clears the reservation flag/wait request. Combining pause and
  clear in one frame only pauses the active reservation. After cancellation the
  device returns to standby with the flag off; it retains the inactive wait
  counter until powered off. That counter does not produce a completion
  estimate while the flag is off.
- DC reports the flag in byte 12's low two bits and the wait at bytes 14-15.
  The setter uses `FD`/`FC` for that field, leaving adjacent anti-wrinkle bits
  unchanged. Start is on for actual operation (2) and active reservation wait
  (8), off for reservation selection (6) and reservation pause (9). Reservation
  selection still permits deadline editing/cancellation. Start/resume preserves
  the wait's high byte. This behavior applies only to the verified profile.

Program duration is a little-endian count of minutes.
The verified dryer overrides the legacy hours/minutes calculation.
