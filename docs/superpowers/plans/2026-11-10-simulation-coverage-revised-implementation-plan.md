# Revised Implementation Plan — Synthetic IMU Simulation Coverage & Reporting

**Date:** 2026-11-10
**Status:** Implemented, independently reviewed, and verified
**Repository:** [`MarcusFunt/rp2350-lsm6ds3-eskf`](https://github.com/MarcusFunt/rp2350-lsm6ds3-eskf)
**Supersedes:** `2026-11-10-simulation-coverage-and-reporting.md`
**Design reference:** `2026-11-10-motion-scenario-expansion-design.md` (`docs/superpowers/specs/2026-11-10-motion-scenario-expansion-design.md` in the repository)

> **For implementation agents:** Execute tasks in order. Make small, independently testable commits. Keep a checklist of completed work and report exact commands and observed results. If the `superpowers` agent workflow is available, use its executing-plans or subagent-driven-development procedure; it is not a runtime dependency.

## 1. Objective and definition of done

Expand the host-only Bundle B synthetic IMU benchmark from **six to eight motion scenarios** and from **one to two sensor profiles**, then produce defensible, deterministic Monte Carlo comparisons of the three existing estimator variants. Fix existing *benchmark measurement* defects before regenerating performance evidence.

The deliverable is an auditable simulator and reporting pipeline, **not** a measured RP2350/LSM6DS3 accuracy or timing result.

**Definition of done:**

- [x] The attitude/tilt metric has explicit, correct frame semantics and analytical unit tests.
- [x] The initial stationary window is consistent at the exact 2.000 s boundary.
- [x] Eight scenarios run under `nominal` and `stress` profiles, without changing estimator algorithms.
- [x] Every estimator consumes exactly the same generated IMU stream for a given scenario/trial/profile.
- [x] The nominal model and legacy six-scenario noise sequences remain unchanged unless a deliberate, documented benchmark-version change is made.
- [x] Stress effects, clipping counters, and injected true bias are deterministic and testable separately.
- [x] Results include raw per-trial records, valid-output coverage, mean RMS, between-trial SD, 95% Student-t intervals, and *paired* estimator differences.
- [x] Missing/invalid trials never silently improve an estimator's apparent accuracy.
- [x] Markdown, strict JSON, and eight unambiguous SVG charts regenerate from the checked-in CSVs.
- [x] The complete validation suite passes, and source/report claims remain limited to synthetic uncalibrated evidence.

## 2. Non-negotiable scope and contracts

1. **No estimator changes:** Do not alter `eskf15.hpp`, Mahony gains, navigation state, aiding semantics, gravity policy, or how existing NEES/NIS diagnostics are interpreted merely to improve benchmark results. Any independent bug fix requires its own review.
2. **Known synthetic truth only:** Stationarity confirmation is derived from the *scenario definition*, not from an assumed IMU-only detector. Startup bias calibration stays opt-in (`--startup-bias`).
3. **Same samples for fair comparison:** Each profile/trial is generated once; the conservative ESKF, legacy ESKF, and Mahony consume the same ordered `Imu` objects, timestamps included. The reference trajectory is integrated independently of all estimators.
4. **Synthetic assumptions:** Noise, residual calibration, temperature, and saturation values are explicitly illustrative; they are not characterized LSM6DS3 behavior.
5. **No Python runtime dependencies:** C++17, Python 3 standard library, Bash, existing compiler. Generate SVG directly; no plotting packages.
6. **Backward compatibility:** Retain `--trials`, `--seed`, `--output`, `--startup-bias`. Add `--sensor-profile nominal|stress|both` (default `both`). The output schema is versioned; changing the default row count is documented.
7. **Reproducibility scope:** Require byte-identical CSV/JSON/SVG results for the same seed, CLI, code, and toolchain/environment. Do **not** promise byte identity across different standard-library, compiler, CPU or `libm` implementations without testing that claim.
8. **Performance independence:** Simulated timing-label jitter is not MCU interrupt-jitter evidence, and no synthetic result establishes controller safety or actual field accuracy.

### Existing code and files to work from

| File | Responsibility |
|---|---|
| `tools/benchmark_bundle_b.cpp` | Motion, true attitude, sensor noise and benchmark CSV generation |
| `tools/summarize_bundle_b.py` | Grouped descriptive/interval statistics, Markdown, JSON, SVG |
| `tests/test_bundle_b.cpp` | Existing ESKF/motion-aware regression checks; extend or add separate simulator unit tests |
| `tools/run_bundle_b_checks.sh` | Build, deterministic replay, validation and optional sanitizers |
| `README.md` / `BENCHMARK_B.md` | Commands, caveats and generated benchmark narrative |
| `benchmarks/` | Checked-in raw evidence, summaries, plots and run metadata |

**Observed code concerns (as reviewed on 2026-11-10):** `tilt_error()` compares world-frame body-Z directions; the `motion()` stationary condition uses `t < 2` whereas stationary confirmation uses `t <= 2`; the current summarizer groups only `(scenario, model)` and assumes numeric standard deviations; the existing noise seed offset uses *scenario-name length*, which can collide across scenario names. Preserve or deliberately version historical behavior instead of accidentally changing it.

---

## Task 0 — Benchmark correctness and metric contract **(new; blocking)**

**Goal:** Establish that the reported quantity called *tilt error* actually measures inclination error rather than accidentally counting world-heading error; remove startup truth-label ambiguity.

**Modify:** `tools/benchmark_bundle_b.cpp`; `tests/test_bundle_b.cpp` or a new `tests/test_bundle_b_sim.cpp`; document metric semantics in `README.md`.

### Implementation

- [x] Define `tilt_error_deg(q_est, q_truth)` as the angle between **predicted gravity/up directions expressed in the body/sensor frame**:

  ```text
  u = (0,0,1) in world frame
  g_est_body  = q_est.unrotate(u)
  g_true_body = q_truth.unrotate(u)
  tilt_deg = acos(clamp(dot(normalize(g_est_body),
                            normalize(g_true_body)), -1, 1)) * 180/pi
  ```

  The repository convention is body-to-world quaternions. This metric is invariant to an arbitrary common *world-yaw* gauge and tests sensed inclination, not world heading.
- [x] Explicitly distinguish this from the **previous** world-frame body-Z-axis deviation. Optionally expose that previous diagnostic under a transparent name such as `body_axis_world_error_rms_deg`; never silently call it `tilt_rms_deg` after the fix.
- [x] Keep `yaw_rms_deg` but explain that yaw is unobservable from gravity alone, evaluated relative to a chosen synthetic initial yaw gauge, and is not absolute heading accuracy.
- [x] Fix the exact startup boundary. Choose a single rule such as `t < 2.0f` for both true stationarity and external stationarity confirmation; assert that samples with `t >= 2.0f` are not flagged stationary when motion is nonzero. Static scenario is always physically stationary, but confirmation may still be restricted to startup intentionally.
- [x] Make the new eight-scenario `motion()` interface testable without executing the benchmark CLI (small pure helper or isolated test harness); avoid a sweeping refactor.
- [x] Add an explicit `metric_definition_version` in metadata/reporting; label previously checked-in summaries as historical **v1** evidence. New checked-in evidence must use **v2** definitions.
- [x] Do **not** modify the filter's gravity-derived NEES/NIS calculation in this task. Retain existing warnings about IMU-data reuse and lack of rigorous chi-square calibration.

### Unit tests

- [x] Identity vs identity → tilt 0°.
- [x] Pure world-yaw difference, with nonzero true roll/pitch → tilt ≈ 0°.
- [x] Known pure roll and pure pitch errors → expected angle within numeric tolerance.
- [x] Combined roll/pitch/yaw → compare with an independent geometric reference calculation.
- [x] Angle computation remains finite near parallel and anti-parallel vectors.
- [x] Boundary samples immediately below, at, and above 2.0 s have matching motion/truth/confirmation logic.

**Acceptance gate:** Metric tests pass before the new result files are generated. README explains why v2 RMS values are not directly comparable to the historical v1 column despite the similar name.

---

## Task 1 — Add physically coherent motion coverage

**Goal:** Retain the existing six scenarios and introduce `stop_start` and `compound_motion` with smooth, bounded dynamics and a demonstrably stationary start.

**Modify:** `tools/benchmark_bundle_b.cpp`; simulator tests from Task 0.

### Implementation

- [x] Keep the existing scenario names exactly: `static`, `slow_yaw`, `lateral_accel`, `maneuver`, `vibration`, `timing_jitter`.
- [x] Add `stop_start` with explicit phases after 2 s: smooth acceleration/ramp-up, finite constant-velocity or rate hold, smooth deceleration, and final rest. Derive acceleration from the specified translational velocity envelope; do not arbitrarily jump between acceleration values.
- [x] Use a `smoothstep5(x) = 6x^5 - 15x^4 + 10x^3` envelope (or documented equivalent) so endpoints and derivatives join cleanly. For rotation, design the angular-rate envelope with similar endpoint continuity.
- [x] Add `compound_motion`: simultaneous nonzero angular rates on all three axes and nonzero translational acceleration on multiple axes; modulate these with a smooth startup envelope, and ensure magnitudes stay bounded.
- [x] Preserve the 16 s, 200 Hz historical host benchmark timing by default. The RP2350 firmware's 208 Hz IMU configuration is **different**; do not conflate simulated 200 Hz with real 208 Hz hardware.
- [x] Maintain independently integrated quaternion truth; normalize and check for finite values on every step. If translation is modeled as an acceleration command without integrating position/velocity, document that limitation.
- [x] Test reference integration against a finer-time-step solution for representative trajectories; do not use the estimator under test as the truth oracle.
- [x] Unknown scenario values must still fail with exit status 2 and a clear error (where scenarios are user-selectable).

### Tests and acceptance

- [x] All eight cases produce finite, normalized truth throughout the simulation.
- [x] All motion components are exactly zero during the defined 2 s startup window (except the static scenario, which stays zero throughout).
- [x] No abrupt motion steps at phase boundaries; measured maximum velocity, acceleration, and angular rate satisfy documented bounds.
- [x] `stop_start` actually returns to rest; `compound_motion` actually excites x/y/z angular-rate components and nontrivial acceleration.
- [x] Verify the existing six scenario definitions remain numerically unchanged, apart from the deliberate startup-boundary correction where applicable.

**Acceptance gate:** Unit tests validate behavior, not just the presence of scenario strings.

---

## Task 2 — Add nominal/stress sensor profiles without contaminating truth

**Goal:** Introduce interpretable sensor stress while preserving the nominal model and paired estimator fairness.

**Modify:** `tools/benchmark_bundle_b.cpp`; simulator tests; optional compact benchmark-metadata JSON writer.

### Interfaces

- [x] Add `enum class SensorProfile { Nominal, Stress };` and a stable lowercase name helper.
- [x] Parse `--sensor-profile nominal|stress|both` (default `both`). Reject unknown/missing values, invalid integers, negative trials, and seed overflow with nonzero exit status and usage text.
- [x] Keep per-run identity fields: `scenario`, `trial_id`, `seed`, `sensor_profile`, `startup_bias`, `model`; include `schema_version` and `metric_definition_version` in companion metadata.
- [x] Add `accel_clip_samples`, `gyro_clip_samples` to CSV. Define them as counts of **time samples with at least one clipped axis**, before quantization, counted once for the sensor stream and repeated as stream provenance on model rows. Optionally add axis-event counts separately; never combine the two meanings.

### Model definition

- [x] Define named constants **with units** for residual 3×3 accelerometer and gyroscope scale/misalignment matrices, quantization steps (m/s² and rad/s), finite full-scale limits, synthetic temperature ramp (°C versus time), and temperature-to-bias coefficients (m/s²/°C, rad/s/°C).
- [x] Clearly separate *assumed stress constants* from calibrated/datasheet measurements. Avoid presenting an arbitrary clipping threshold as a physical LSM6DS3 limit.
- [x] Document the exact per-sample order:

  ```text
  ideal proper acceleration and angular rate
  -> deterministic scale/misalignment matrix in sensor axes
  -> initial bias + random-walk bias + thermal bias + white noise
  -> physical/synthetic full-scale clipping
  -> quantization
  -> identical Imu record dispatched to each estimator
  ```

- [x] Use the original nominal sensor equations and random-draw order for the historical six scenarios; changing profile order or selecting `both` must not perturb nominal output. Generate canonical common random draws once per trial/scene and apply deterministic per-profile transforms or use exactly equivalent reset RNG streams. **Never allow one profile's extra random draws to shift the other's sequence.**
- [x] Maintain a versioned, documented seed schedule. The legacy offset based on scenario-name length can collide for different scenario names; if replacing it with distinct stable scenario IDs, deliberately version the seed schedule and document that legacy nominal traces change. Prefer preservation for the historical six names for this revision.
- [x] Track effective true additive sensor bias including temperature drift, and compare estimated bias against the matching injected bias in sensor coordinates. Note that scale/misalignment is *not* itself an additive bias and may make simple bias-error interpretation incomplete.
- [x] Keep optional startup calibration using verified synthetic stationarity; do not implicitly turn it on for stress.
- [x] For realistic stress, choose clipping ranges intentionally and document whether normal scenarios clip. **Do not force clipping into an ordinary scenario solely to satisfy a test.** Add a dedicated extreme-input saturation unit test to exercise the counters and clipping order instead.

### Deterministic tests

- [x] Identity transforms, zero thermal coefficient and zero quantization recover nominal behavior.
- [x] Known scale/alignment vector yields independently calculated output.
- [x] Quantization ties, positive/negative limits, and multi-axis clipping count correctly.
- [x] Temperature ramp produces expected time-varying *true* bias and measured samples.
- [x] Profile `nominal` alone matches the nominal subset of `both`; `stress` alone matches the stress subset of `both` for the same seed and CLI settings.
- [x] All three estimators receive identical per-timestamp, per-axis input bytes within each scenario/trial/profile.
- [x] Counters are stable across repeated runs and never multiplied by the number of estimators.

**Acceptance gate:** Stress behavior is observable, deterministic, physically defined, and reported without claims of measured sensor realism.

---

## Task 3 — Statistical interpretation, failure coverage and SVG reporting

**Goal:** Make the output useful for *comparing estimators*, not merely displaying means.

**Modify:** `tools/summarize_bundle_b.py`; add Python unit tests (e.g. `tests/test_summarize_bundle_b.py`); optionally add shared-valid comparison accumulators in `tools/benchmark_bundle_b.cpp`.

### Aggregation and validity rules

- [x] Group by `(scenario, sensor_profile, startup_bias, model)` even if most inputs contain only one startup mode. Validate that expected scenario/profile/model groups are complete and that `(scenario, sensor_profile, startup_bias, trial_id, model)` keys are unique.
- [x] Parse numeric values defensively: empty, non-finite and absent measurements are not silently treated as zero. Reject malformed identifying fields and duplicate trial rows.
- [x] Preserve `valid` and `expected`; add invalid count, valid fraction, and a summary of degraded/faulted/uninitialized samples where instrumented data are available. Make validity a first-class report column.
- [x] Compute the **arithmetic mean of per-trial RMS values**, not the RMS of pooled samples. Compute sample between-trial SD and 95% two-sided Student-t CI for the mean from the `n_finite` trials for each metric.
- [x] Return JSON `null` for CI bounds when `n_finite < 2`; expose `n_finite` and `n_missing`. For `n_finite = 0`, also return `null` for mean and SD; for `n_finite = 1`, SD is unavailable (`null`, not zero).
- [x] Use correct finite-sample Student-t quantiles for the supported range (up to 200 trials), e.g. an audited complete lookup table for df=1..199 or an accurate validated numerical inverse. **Do not** switch to 1.96 at df>30. Test known quantiles such as df 1 ≈12.706, df 7 ≈2.365, df 30 ≈2.042 and df 199 ≈1.972.
- [x] Use `json.dumps(..., allow_nan=False)` and explicitly normalize non-finite/unavailable values to `None`. Ensure empty/partially missing metrics render as `N/A` in Markdown rather than raising format exceptions.
- [x] Keep NEES/NIS as *diagnostics* with the existing caveats, not probability-calibrated proof. Show sample coverage for any derived diagnostic when possible.

### Paired comparisons

- [x] Pair conservative ESKF vs legacy ESKF, conservative ESKF vs Mahony, and optionally legacy ESKF vs Mahony by matching `(scenario, sensor_profile, startup_bias, trial_id)`.
- [x] For each valid pair calculate `delta_rms_deg = rms_A - rms_B`; negative means estimator A has lower error. Report the **mean paired delta, SD, n pairs, 95% CI**. No p-value is necessary.
- [x] Also compare `stress - nominal` within each estimator and matched `(scenario, startup_bias, trial_id)` to quantify robustness cost; document the sign.
- [x] **Validity caveat:** Per-trial RMS values can be calculated from different time samples if an estimator becomes invalid. Preferred solution: calculate pairwise RMS on the **intersection of valid timestamps** in the C++ benchmark and report pairwise coverage. Minimum acceptable solution: explicitly withhold/invalidate comparative claims when coverage differs materially, and report the mismatch. Never label a comparison fair without aligned evaluation windows.
- [x] Do not turn missing/failed trials into zero error or drop an estimator from charts without an explicit visible missing-data indicator.

### SVG charts and report outputs

- [x] Keep `--markdown`, `--json`; add optional `--plots-dir DIR`. If supplied, generate `tilt_rms_{profile}.svg` and `yaw_rms_{profile}.svg` for each selected profile and the *specific startup mode*. Use **different output directories per mode**; never overwrite files referenced by the other report.
- [x] Provide title, scenario categories (eight), RMS units in degrees, estimator legend, mean point/bar, and 95% CI whiskers. Show `N/A` where CI/metric is unavailable. Include a textual note or labeling for valid fractions and the synthetic nature of results.
- [x] Escaping: XML-escape all text; ensure legibility for long scenario names and no invalid or missing SVG attributes. Set `viewBox`, preserve label space, and check visible axis/legend text with a parser.
- [x] Markdown includes the correct relative plot paths, caveats, per-profile statistics and paired comparison table. Strict JSON includes interval bounds, trial counts, validity information, and schema/metric version metadata.
- [x] Keep the 8-trial CI as descriptive and explicitly label it *preliminary*; its uncertainty concerns trial variability under the assumed simulator, not real-world accuracy.

### Statistical test fixtures

- [x] One trial → finite mean, unavailable SD/CI.
- [x] Two identical trials → zero SD, zero-width CI where mathematically valid.
- [x] Eight known trials → mean/SD/CI agree with independently calculated reference values.
- [x] Missing value, `nan`, `inf`, empty string → no invalid JSON; correct `n_finite`/`n_missing`.
- [x] Mismatched trial keys, duplicate rows or missing groups → fail with actionable diagnostics.
- [x] Synthetic paired example confirms delta sign, pairing, and CI.
- [x] SVG charts contain expected labels, estimator legend, CI graphical elements, and no overwriting across startup modes.

**Acceptance gate:** Reports never conceal lack of estimates, do not compare unmatched samples as if matched, and distinguish within-trial time-series error from between-trial sampling uncertainty.

---

## Task 4 — Regression coverage, evidence regeneration and documentation

**Goal:** Treat generated benchmark outputs as versioned reproducible evidence and make CI catch schema, profile, statistical and presentation regressions.

**Modify:** `tools/run_bundle_b_checks.sh`, `README.md`, `BENCHMARK_B.md`, benchmark CSV/JSON files, tests; create plots and metadata.

### Coverage and artifact layout

Expected checked-in rows **per startup mode**:

`8 scenarios × 2 sensor profiles × 3 estimators × 8 trials = 384 rows`

Both modes together: **768 data rows** (excluding headers). The existing 5-trial smoke test should therefore generate **240 rows per startup mode** under the default `both` profile.

```text
benchmarks/
├── bundle_b_no_startup_bias.csv
├── bundle_b_verified_startup_bias.csv
├── summary_no_startup_bias.json
├── summary_verified_startup_bias.json
├── metadata_no_startup_bias.json
├── metadata_verified_startup_bias.json
└── plots/
    ├── no_startup_bias/
    │   ├── tilt_rms_nominal.svg
    │   ├── tilt_rms_stress.svg
    │   ├── yaw_rms_nominal.svg
    │   └── yaw_rms_stress.svg
    └── verified_startup_bias/
        ├── tilt_rms_nominal.svg
        ├── tilt_rms_stress.svg
        ├── yaw_rms_nominal.svg
        └── yaw_rms_stress.svg
```

### Validation script updates

- [x] Compile existing Bundle B tests and new simulation/statistical tests with C++17 warnings-as-errors where applicable.
- [x] Run nominal-only, stress-only and default `both`; assert exact counts and every expected unique scenario/profile/model/trial key, not merely total row count.
- [x] Assert unknown profile, malformed numbers and invalid trial counts fail with appropriate exit status; retain legacy CLI argument behavior.
- [x] Run identical commands twice and use `cmp` for byte-identical CSV; compare `both` subsets with single-profile outputs after accounting for ordering.
- [x] Assert *nominal isolation*: legacy scenario sample generation still matches a saved golden fixture/hash if practical; retain source-controlled versioned evidence when benchmark metrics change.
- [x] Assert stress transform unit tests, clipping counters, and no counter multiplication across model rows.
- [x] Assert valid/expected bounds, finite truth, explicit invalid/fault samples, and that regression tests cannot pass because a failing estimator output disappeared.
- [x] Assert a one-trial summary has `null` intervals and `n_finite=1` for each present metric.
- [x] Assert standard-library SVG generation produces all **eight** files, with correct axes, legend, CI marks, and distinct correct relative links for both modes.
- [x] Assert Markdown/JSON means and CI bounds match the underlying CSV values to stated numerical tolerance.
- [x] Retain existing behavior-focused checks (startup-bias improvement, lateral acceleration rejection, timing jitter, etc.), but reassess their numeric thresholds after the *intentional v2 metric definition change*; do not relax thresholds merely to achieve passing status.
- [x] Keep optional AddressSanitizer/UndefinedBehaviorSanitizer passes and run Bundle A and Bundle C host checks for integration regression when available.

### Configuration provenance

- [x] Store: simulator/schema/metric version, scenario set, duration, sample rate (200 Hz), base seed, trial count and seed schedule, selected profiles, all stress constants with units, startup mode, compiler/toolchain where available, and current Git commit SHA or an explicit `unavailable` value.
- [x] Keep machine-generated artifacts stable: no wall-clock timestamp, machine-specific absolute path, or nondeterministic ordering in byte-reproducibility-tested output. Toolchain metadata may be separated from byte-stable output if necessary.
- [x] Include a profile-configuration hash or canonical serialized parameter block so the name `stress` cannot silently refer to a different set of constants on future runs.
- [x] Document synthetic-only interpretation and the 200 Hz host / 208 Hz target-hardware difference.

### Evidence generation commands

Assuming working directory is repository root and the implementation has added `--plots-dir`:

```bash
mkdir -p benchmarks/plots/no_startup_bias benchmarks/plots/verified_startup_bias

g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror \
  tools/benchmark_bundle_b.cpp -o benchmark_bundle_b

./tools/run_bundle_a_checks.sh
./tools/run_bundle_b_checks.sh
./tools/run_bundle_c_checks.sh

./benchmark_bundle_b --trials 8 --seed 20261110 --sensor-profile both \
  --output benchmarks/bundle_b_no_startup_bias.csv

./benchmark_bundle_b --trials 8 --seed 20261110 --sensor-profile both \
  --startup-bias --output benchmarks/bundle_b_verified_startup_bias.csv

python3 tools/summarize_bundle_b.py benchmarks/bundle_b_no_startup_bias.csv \
  --json benchmarks/summary_no_startup_bias.json \
  --plots-dir benchmarks/plots/no_startup_bias

python3 tools/summarize_bundle_b.py benchmarks/bundle_b_verified_startup_bias.csv \
  --markdown BENCHMARK_B.md \
  --json benchmarks/summary_verified_startup_bias.json \
  --plots-dir benchmarks/plots/verified_startup_bias

BUNDLE_B_SANITIZERS=1 ./tools/run_bundle_b_checks.sh
```

The metadata sidecars should be written by the updated benchmark or a deterministic helper during these runs. Do not add undocumented manual editing of generated results.

**Acceptance gate:** Fresh checkout → run the documented commands → exact expected artifact set and stable content within the documented environment; no stale plot links or historical v1/v2 confusion.

---

## 3. Suggested commit sequence and review gates

| Commit | Scope | Gate before proceeding |
|---|---|---|
| `test(bundle-b): verify tilt metric and startup truth` | Independent geometric/boundary tests | Demonstrate old failure, new pass |
| `fix(bundle-b): version corrected tilt measurement` | Correct semantic metric, preserve historical distinction | All metric tests pass |
| `feat(bundle-b): add bounded motion scenarios` | `stop_start`, `compound_motion` | Truth/boundary/motion tests pass |
| `feat(bundle-b): add deterministic stress profile` | Model, CLI, streaming counters | Profile isolation + transform tests pass |
| `feat(bundle-b): add paired statistics and reporting` | CI, validity, paired differences, SVG | Python numeric fixtures pass |
| `test(docs): strengthen regression and regenerate evidence` | Checks, README, CSV/JSON, 8 SVGs | Full check scripts and artifact audit pass |

If implementation discovers a failure in `eskf15.hpp`, capture a minimal reproducer and propose a separate estimator change; do not silently widen this benchmark-only PR.

## 4. Required report interpretation

The generated report should explicitly answer:

1. **Accuracy:** What is mean per-trial *inclination* RMS and synthetic-gauge yaw RMS by scenario/profile/estimator?
2. **Variability:** How much do these values change with trial noise seed? Show sample SD and 95% Student-t CI with `n`.
3. **Comparison:** What is the paired difference between estimators, with sign convention and uncertainty? Are evaluation time windows aligned?
4. **Robustness:** What changes from nominal to stress for the **same** trial noise draws?
5. **Availability:** How many estimates are valid, invalid, suppressed, degraded or faulted? Does any apparent accuracy advantage coincide with missing difficult samples?
6. **Limitations:** These are synthetic, uncalibrated, host-side results; no claims about actual IMU noise, SPI interrupt timing, closed-loop safety, physical attitude accuracy or absolute yaw observability.

## 5. Optional follow-on work (not required for this milestone)

- **Higher-power analytical suite:** 50–100 trials per group, retained separately from the eight-trial checked-in fast regression dataset.
- **Time-series diagnostics:** Save selected-trial attitude-error, bias, gravity-update, and health-state traces around high acceleration, startup/settling, and saturation events. Aggregate RMS alone hides failures localized in time.
- **Multi-rate tests:** Add an explicit 208 Hz software scenario after the 200 Hz baseline remains reproducible, to study sample-rate dependence without claiming hardware timing accuracy.
- **Hardware correlation:** Once actual RP2350 + LSM6DS3 data become available, fit noise/scale/bias parameters from calibration and rerun the benchmark with a distinct empirically calibrated profile. Do not relabel the illustrative stress profile as calibrated data.

## 6. Execution record

- Implemented in worktree `codex/simulation-coverage-and-reporting` from base `c397fec8f5df3fb612ea6aa92547d484e9e48c06`; source/test commit `85e6d22ca3475885a1958ac8f8669868e8c331ec`. Estimator algorithms in `eskf15.hpp` were not changed.
- Evidence regenerated against source commit `85e6d22ca3475885a1958ac8f8669868e8c331ec` with seed `20261110`, 8 trials, 8 scenarios, both sensor profiles, both startup modes, and all 3 estimator variants. Metadata records GCC 11.4.0, `libstdc++-20230528`, and the then-dirty worktree state.
- Passed: `bash tools/run_bundle_b_checks.sh`; `bash -lc 'BUNDLE_B_SANITIZERS=1 bash tools/run_bundle_b_checks.sh'`; `bash tools/run_bundle_a_checks.sh`; `bash tools/run_bundle_c_checks.sh`; and `git diff --check` (Git emitted only its LF-to-CRLF normalization notices).
- The Bundle B check script confirms deterministic repeated CSV/metadata, historical nominal Gaussian draw hashes on the matching toolchain, profile isolation, valid-mask pairing, metadata, strict JSON, and all eight SVGs. Sanitizers passed for the simulator unit test and benchmark executable. Latest simulator rebuilds reproduced both checked-in CSVs and metadata byte-for-byte.
- The final independent review resolved the deterministic vibration and timestamp-jitter regression gap; the reviewer found no remaining actionable issue. No pull request has been opened; the exact run record is kept here and in the worktree execution ledger.

## 7. Final handoff checklist

- [x] Worktree clean or intentional uncommitted changes enumerated; no accidental unrelated modifications.
- [x] All new tests execute through the repository's check script, not only manually.
- [x] Exact command results, warnings, seed, trial count, environment and known limitations recorded in this execution record; no PR is open.
- [x] Both startup modes, all eight scenarios, both profiles, all three estimators covered.
- [x] CSV, JSON, report and eight SVG files agree and link correctly.
- [x] The report states that synthetic ESKF results cannot certify hardware estimator performance or safety.
- [x] Explicit code review of metric conventions, temperature-bias truth bookkeeping, sample-validity handling, and Student-t CI calculations completed before merge.

**Recommended execution order:** Task 0 → Task 1 → Task 2 → Task 3 → Task 4. The highest-risk changes are metric semantics and the fairness of comparisons when estimators return different valid-sample sets; review those before spending effort on plot aesthetics.
