# Baseline audit — Prompt 01 (A1)

Audit date: 2026-11-11. Repository: `MarcusFunt/rp2350-lsm6ds3-eskf` (`https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf.git`). Scope: inventory, current remote provenance, and existing host/CI checks only. No estimator, generated benchmark, or frozen v1-v5 evidence files were changed.

## Authoritative checkout and preserved user work

A fresh `git fetch origin --prune` followed by `git ls-remote origin` verified `origin/main` at `0d31c0e7c1f698122bf34d0e107334af225095e6`. The primary checkout is `C:\Users\marcu\rp2350-lsm6ds3-eskf`, on `main` at that exact SHA with no tracked modifications. Its untracked user files were preserved:

- `docs/superpowers/plans/2026-11-10-simulation-coverage-and-reporting.md`
- `docs/superpowers/specs/2026-11-10-motion-scenario-expansion-design.md`

The separate checkout `C:\Users\marcu\Projects\rp2350-lsm6ds3-eskf` is stale: branch `main` at `e90c80eb47e5002738f4a16450714b3149798e28`, clean, 80 commits behind its fetched `origin/main` and not ahead. It was not changed.

The new isolated worktree is `C:\Users\marcu\.codex\worktrees\eskf-baseline-audit-20261111\rp2350-lsm6ds3-eskf`, branch `codex/baseline-audit-20261111`, created from verified `origin/main` at `0d31c0e7c1f698122bf34d0e107334af225095e6`. Tests generated the ignored `fixtures/stationary_then_yaw.csv` inside this worktree; its SHA-256 matches the pre-existing primary-checkout fixture (`325A8479849EFB3EDA2EAF396A2C090D7BC0F2A83933D4C2561A0E1E46B468A8`). No generated fixture or benchmark output is committed.

## Registered worktrees and branch SHAs

| Checkout / branch | HEAD | State |
|---|---|---|
| Primary `main` | `0d31c0e7c1f698122bf34d0e107334af225095e6` | Clean tracked tree; two untracked notes listed above |
| `codex/publish-simulation-coverage` | `0d31c0e7c1f698122bf34d0e107334af225095e6` | Clean |
| `codex/simulation-coverage-and-reporting` | `84c107dbc72bf425971547751a0e486938552ea5` | One untracked `simulation_figures_2026-11-10.zip`; preserved |
| `test/eskf-remediation-pr1` | `b749a8aa0e40718ab7b163cad29d9c550b088265` | Clean |
| `fix/eskf-math-recovery` | `4d023d0c2b425b008ecd0a486966fa696814acdd` | Clean |
| `test/eskf-statistics-benchmarks` | `1c417f5ec5c74ed0313455f2fdea4130f4fe3ff5` | Clean |
| `fix/eskf-fifo-timing` | `bb846bd3f5b58e3eabb862166ec0ee13e1b1d827` | Clean |
| `fix/eskf-calibration-aiding-health` | `b705a83d0f52fe39c263f4dbdf09f5dec7c9253d` | Clean |
| `fix/eskf-logging-resources-report` | `54637759e9cc7bf2ef1deb7dec7d485d9310b8be` | Clean |
| New A1 worktree `codex/baseline-audit-20261111` | Based on `0d31c0e7c1f698122bf34d0e107334af225095e6` | Isolated; audit artifact only |

GitHub's current remote branch list contains these exact branch SHAs:

| Remote branch | SHA |
|---|---|
| `main` | `0d31c0e7c1f698122bf34d0e107334af225095e6` |
| `test/eskf-remediation-pr1` | `b749a8aa0e40718ab7b163cad29d9c550b088265` |
| `fix/eskf-math-recovery` | `4d023d0c2b425b008ecd0a486966fa696814acdd` |
| `test/eskf-statistics-benchmarks` | `1c417f5ec5c74ed0313455f2fdea4130f4fe3ff5` |
| `fix/eskf-fifo-timing` | `bb846bd3f5b58e3eabb862166ec0ee13e1b1d827` |
| `fix/eskf-calibration-aiding-health` | `b705a83d0f52fe39c263f4dbdf09f5dec7c9253d` |
| `fix/eskf-logging-resources-report` | `54637759e9cc7bf2ef1deb7dec7d485d9310b8be` |

The two `codex/*` simulation branches are local-only. GitHub issue and pull-request searches for this repository returned no open issues and no open pull requests.

## Toolchain and matching GitHub Actions run

Local host checks ran in Ubuntu 22.04.5 LTS under WSL: `g++ 11.4.0`, Python `3.10.12`. The Windows shell has Python `3.11.4` and CMake `3.31.4`, but no local GCC/Clang, Ninja, ARM compiler, or configured `PICO_SDK_PATH`. Host tests do not require the Pico SDK.

The matching current-main Actions run is [42993619989](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf/actions/runs/42993619989), push event on SHA `0d31c0e7c1f698122bf34d0e107334af225095e6`, completed successfully on 2026-11-11. Both `host-tests` and `pico2-cross-build` passed. The host job ran Bundles A/B/C, their sanitizer variants, protocol v1-v5 checks and PR3 smoke validation. The target job built direct-register, FIFO, and binary-FIFO configurations for Pico 2. Its environment was Ubuntu 24.04, Python `3.12.3`, ARM GCC package `13.2.Rel1` (`gcc-arm-none-eabi` package `15:13.2.rel1-2`), and Pico SDK `2.2.0` (workflow pins tag `2.2.0`). This is cross-build evidence only, not hardware validation.

## Local test outcomes and measured results

All six requested local commands passed from the isolated worktree using WSL Bash. No test failure or unresolved test blocker occurred.

| Command | Outcome | Measured evidence |
|---|---|---|
| `bash tools/run_bundle_a_checks.sh` | PASS | Replay accepted 1,200 records, propagated 1,120, with 0 malformed/gap/saturation events. Replay checker: 56 output rows; yaw `1.963498 rad` vs `1.963495 rad` target. Finite-difference audit: 7,200 dynamics entries; max A/gravity-H/yaw-H errors `0.002601` / `0.000844` / `0.001023`. Process Qd quadrature: 42 entries, max absolute error `1.53813e-9`. |
| `BUNDLE_A_SANITIZERS=1 bash tools/run_bundle_a_checks.sh` | PASS | ASan/UBSan estimator and UBSan replay paths passed; same replay and numerical checks as above. |
| `bash tools/run_bundle_b_checks.sh` | PASS | 5 trials × 8 scenarios × 3 estimator variants × 2 sensor profiles; repeated output and metadata byte comparisons passed; paired coverage, intervals and eight SVGs validated. Slow-yaw diagnostic: max error `0.0300 rad` IMU-only vs `0.0013 rad` with 120 heading aids. |
| `BUNDLE_B_SANITIZERS=1 bash tools/run_bundle_b_checks.sh` | PASS | ASan/UBSan simulation tests and UBSan two-trial benchmark passed. |
| `bash tools/run_bundle_c_checks.sh` | PASS | Calibration/FIFO/log/aiding tests passed. Binary replay: 1,200 records, 1,120 propagated, one sequence gap and one explicit drop; v1/v2 replay compatibility passed. |
| `BUNDLE_C_SANITIZERS=1 bash tools/run_bundle_c_checks.sh` | PASS | Sanitized Bundle C test and binary-log replay passed with the same counts. |

The run scripts wrote benchmark outputs under `/tmp` and used only the worktree's ignored fixture. No tracked benchmark, protocol, `eskf15.hpp`, or historical evidence file changed.

## Existing unresolved root causes and limits

These are current documented findings, not failures of the six checks above:

- PR3 accuracy/consistency acceptance remains open. In the baseline stress profile, conservative ESKF mean per-trial RMS is about `4.64-4.66 deg` tilt and `10.30 deg` yaw despite complete trials and covariance checks.
- PR2 `LegacyHeuristic` yaw/bias regressions and the synthetic heading-aid degradation remain unexplained. The root-cause matrix records a disjoint pure-roll confirmation of IMU-only `0.1832/0.9145 deg` mean tilt/yaw RMS vs `3.0899/1.7326 deg` when aided, with 176/176 aids accepted.
- False-runtime-hint and zero-dwell guards have targeted passing regressions, but matching held-out frozen-matrix coverage is still missing. A constant in-tolerance acceleration remains physically ambiguous to a six-axis IMU.
- The previously observed long single-precision covariance positive-definiteness defect and stress startup availability defect are documented fixed for tested synthetic cases. These fixes do not establish estimator accuracy or physical behavior.
- No independent review or Pico 2 + original LSM6DS3 capture is recorded. Physical accuracy, FIFO loss/timing, whole-call-chain stack headroom, deadline behavior, and control suitability remain `BLOCKED_HARDWARE`; firmware remains experimental.

## Handoff

A1 baseline audit is complete. The next authorized work is Prompt 02 when supplied; no later prompt was started here.