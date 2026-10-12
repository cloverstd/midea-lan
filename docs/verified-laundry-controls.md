# Verified DB/DC laundry parameter controls

These profiles are deliberately limited to the tested SN8 **and** subtype pairs:

| Type      | SN8      | Subtype | Programs | Controls                                                                                                         |
| --------- | -------- | ------- | -------- | ---------------------------------------------------------------------------------------------------------------- |
| DB washer | 38131140 | 13145   | 30       | Program, water temperature, spin speed, rinse count, water level, detergent, wash/spin minutes, forget-free care |
| DC dryer  | 38208801 | 13367   | 36       | Program, dryness, temperature, sterilization, anti-wrinkle, timed extension                                      |

Identity may come from `model` or `sn8`, with a matching subtype required. Other
models retain their previous attributes and power/start behavior. Original sensor
attributes stay available; additional controls have separate identifiers. The
verified profiles also correct program names where the generic map describes a
different cycle, and add the previously unknown program codes.

`parameter_control_supported` is exposed only for these profiles. The HA layer
can use it as a capability guard without requiring a dependency pin change.
`parameter_controls_available` reflects the latest real powered, editable status.
Missing or unsupported per-program fields remain `None`. Parameter writes reject
running, delayed or fault states; DB also rejects non-normal operating modes.
DC permits pause in addition to standby/end states.

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

DC selects: `program_control`, `dryness_control`, `temperature_control`; switches:
`sterilize`, `anti_wrinkle`; number: `timed_extra`.

## Protocol details verified on the devices

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

Hardware verification used standby and distant reservations, then cancelled
reservations and restored the original power state; no washing or drying cycle
was executed. Regression fixtures
contain anonymous status bodies, without transport identities, SNs or credentials.
The complete native control migration is additionally tested offline.

Protocol references: [DB V2 manufacturer Lua reference](https://github.com/Cyborg2017/midea_smart_home/issues/49),
[DC extended temperature reference](https://github.com/sususweet/midea_auto_cloud/issues/247),
[another DC encoder](https://github.com/sususweet/midea_auto_cloud/issues/259).
The downloaded Lua was inspected, not executed or vendored.

## Completion-time reservations

Both profiles additionally expose `appointment_control_supported`,
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
- DC reports the flag in byte 12's low two bits and the wait at bytes 14-15.
  The setter uses `FD`/`FC` for that field, leaving adjacent anti-wrinkle bits
  unchanged. Start is on for actual operation (2) and active reservation wait
  (8), off for reservation selection (6) and reservation pause (9). Reservation
  selection still permits deadline editing/cancellation. Start/resume preserves
  the wait's high byte. This behavior applies only to the verified profile.
- Both verified profiles report program duration as little-endian minute counts.
  The verified dryer overrides the legacy hours/minutes calculation.

App-created reservations confirmed that waiting time excludes program duration.
Regression fixtures cover active/paused/selected reservations, cancellation,
complete parameter preservation, timezone-bearing deadlines and invalid inputs.
Ordinary parameter frames retain unchanged power/start bytes; reservation frames
explicitly register a future cycle or pause/cancel it.
