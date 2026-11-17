# RP2350 Estimator Module — Product Requirements Register

Status: **OPEN — pre-production discovery**
Scope selected by the user: **two stages** — qualify the estimator module first, then qualify any downstream controller/actuator system separately.

This register separates repository facts from acceptance requirements. Existing implementation values are not automatically product requirements. Do not tune the estimator or claim a production pass while required thresholds remain open.

## Product boundary

| Item | Current evidence / proposed boundary | Status / owner |
|---|---|---|
| Stage 1 product | RP2350/Pico 2 firmware with an original LSM6DS3, publishing an IMU-derived attitude estimate and health/freshness metadata. | Scope selected; product owner to confirm market/use environment. |
| Stage 2 product | Any system that consumes the estimate in a controller or actuates hardware. Requires its own end-to-end safety and deadline gate. | Conditional; system owner required if applicable. |
| Exact hardware | Code expects Pico 2/RP2350 and original LSM6DS3 `WHO_AM_I=0x69`; the physical board revision and sensor marking have not been verified on a device. | Open; hardware owner. |
| Operating envelope | Current code configures 208 Hz, ±4 g, and ±245°/s. These are implementation settings, not validated operating limits. | Open; verify against the production sensor and use case. |
| Deployment environment | Temperature, vibration, supply, mounting, enclosure, and service/replacement conditions are not specified. | Open; product owner. |

## Output contract

| Output | Current behavior | Production requirement |
|---|---|---|
| Orientation | Quaternion and roll/pitch/yaw are published. Gravity tilt is observable with six-axis IMU input; absolute yaw is not. | Numeric error limits and startup yaw convention are open. Do not claim absolute heading without an independent heading aid. |
| Position / velocity | ESKF fields exist, but no independent aiding is connected and the firmware reports them unobservable. | Decide whether to remove these fields or retain them explicitly as unavailable diagnostics. Do not present them as production navigation output. |
| Health / freshness | Runtime availability requires fresh sensor/output timestamps, verified calibration, nominal estimator health, and no reset latch. The 100 ms age value is diagnostic. | Consumer deadline and behavior for each health/fault state are open. |
| Calibration | Identity calibration is active with `calibration_id=0`; runtime availability is therefore unverified. | Versioned, measured calibration and a nonzero ID are required before Stage 1 production availability. |
| Recovery | A latched fault requires explicit reset and re-alignment; reset does not preserve prior pose. | Maximum recovery/alignment time and consumer-visible reset behavior are open. |

## Numeric acceptance requirements

Values marked `OPEN` must be set by the product owner or supported by measurements and formally accepted before they become release limits. Do not infer limits from synthetic scores, BROAD data, the current sensor settings, or the 100 ms diagnostic threshold.

| Requirement | Current value/evidence | Release limit | Owner/status |
|---|---|---|---|
| Sample rate and allowed jitter | Configured 208 Hz; physical rate not measured. | `OPEN` | Product owner / hardware owner |
| Tilt error RMS, p95, and maximum by scenario | Existing host evidence only; no accepted product limits. | `OPEN` | Product owner |
| Relative heading drift / absolute-yaw claim | Absolute yaw unobservable without external heading. | `OPEN` (scope/claim) | Product owner |
| Output age and missed-deadline budget | 100 ms is a diagnostic threshold, not a control deadline. | `OPEN` | Product/system owner |
| Startup alignment and recovery duration | Algorithm behavior is tested in host cases; physical duration/limits not specified. | `OPEN` | Product owner |
| Supported gyro/accel range and clipping margin | Current settings ±245°/s, ±4 g; physical operating envelope unverified. | `OPEN` | Hardware owner / product owner |
| Temperature and bias/noise stability | No production sensor characterization recorded. | `OPEN` | Hardware owner |
| Uptime, reset rate, and soak duration | No production target or on-device soak evidence recorded. | `OPEN` | Product owner |
| Flash/RAM/stack/timing margin | Prior build estimates exist; complete call-chain and device high-water are unmeasured. | `OPEN` | Firmware owner / product owner |

## Approval record

| Approval | Name / date | Status |
|---|---|---|
| Product/use-case owner | Not identified | `OPEN` |
| Numeric limits and operating envelope | Not approved | `OPEN` |
| Independent reviewer | Not assigned | `OPEN` |

Stage 1 remains **NOT PRODUCTION-READY** until all applicable open requirements have an approved value or an explicit, reviewable exclusion. Stage 2 remains a separate gate.
