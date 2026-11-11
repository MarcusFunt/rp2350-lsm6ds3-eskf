# PR3 development factor pilots

## V5 factor pilot — current estimator candidate

**Classification: exploratory development-only diagnostic, not acceptance evidence.** This pilot uses the frozen v5 candidate `3efd3f89e244e152364773fb26cfb0c5749dce3d`, development seeds `4001–4004`, and protocol SHA-256 `1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800`. It ran all eight scenarios, three sampling modes, nominal/stress, and seven startup/sensor/calibration/runtime-aid profiles.

| Measure | Result |
|---|---:|
| Shared input streams | 192 |
| Estimator rows | 6,720 |
| Incomplete rows | 2,016 |
| Complete rows | 4,704 |
| ESKF nominal rows | 672 / 672 complete per gravity policy |
| ESKF stress rows | 0 / 672 complete per gravity policy |
| Mahony / gyro-only attitude rows | 1,344 / 1,344 complete for each reference |

All failed rows are ESKF stress cases with no valid outputs. The reference estimators provide attitude only, without navigation states, covariance, NEES/NIS or health. No thresholds or estimator settings were tuned. Four seeds do not support distributional or acceptance claims. This result keeps the stress-startup failure visible; it does not justify selecting a different stress threshold.

V5 artifacts: [trial rows](../benchmarks/reports/pr3_protocol_v5_factor_pilot_dev4_trials.csv), [summary](../benchmarks/reports/pr3_protocol_v5_factor_pilot_dev4_summary.json), [manifest](../benchmarks/manifests/pr3_protocol_v5_factor_pilot_dev4.json), and five aggregate [figures](../benchmarks/figures/pr3_protocol_v5_factor_pilot_dev4_availability.svg).

CSV SHA-256: `942ed5c2aba3c7d79a00b6b7d68f1d377c8d553408598e9f8d3387a9666d9b16`. Summary JSON SHA-256: `15d470edfe2857cc52879e3f96ac091e31ce51008f7a8ddc04f97048a72666f2`. The manifest records all per-stream input hashes, source hashes, figure hashes and the exact command. The 192 raw files total about 80.8 MB and are generated on demand rather than checked into Git.

The selected static, uniform-208-Hz, stress, seed-4001 baseline trace shows all three ESKF policies remain `Aligning` through all 3,328 samples (16 seconds); none propagates a state and no covariance failure occurs. Replaying the exact initialization predicate against the shared stream shows 659 adjacent-acceleration differences exceed the fixed `0.20 m/s²` step limit; the longest stable run is 35 samples, below the required 80. Acceleration-norm and gyro-norm gates pass on every sample. This isolates the trigger to the consecutive-sample step gate under the protocol's 3x white-noise transform. The [shared input](../benchmarks/inputs/pr3_protocol_v5_dev_static_stress_seed4001.bin), [sample trace](../benchmarks/reports/pr3_protocol_v5_dev_static_stress_seed4001_sample_diagnostics.csv), and [manifest](../benchmarks/manifests/pr3_protocol_v5_dev_static_stress_seed4001.json) preserve the reproducer. No threshold was changed; a robust correction and untouched confirmation data are still required.

## Superseded v3 factor pilot evidence

**Classification: exploratory development-only diagnostic.** This is not an acceptance or confirmation run and did not change estimator code or tune thresholds. It uses only the first four frozen development seeds (`4001–4004`); the held-out and final-confirmation seed ranges were not run for these added factors.

## Coverage and result

The pilot covered all eight protocol-v3 scenarios, all three sampling modes (`uniform_200hz`, `uniform_208hz`, `irregular_208hz`), both nominal and stress transforms, and all seven supported startup/sensor/calibration/runtime-aid profiles. It generated one shared input stream for every factor/scenario/seed combination and paired all three ESKF gravity policies over each stream.

| Measure | Result |
|---|---:|
| Shared input streams | 192 |
| Estimator trial rows | 4,032 |
| Incomplete or failed rows | 2,916 |
| Complete rows | 1,116 |

| Sampling/stress group | Rows | Complete | Mean output availability |
|---|---:|---:|---:|
| 200 Hz nominal | 672 | 380 | 87.52% |
| 208 Hz nominal | 672 | 377 | 87.97% |
| Irregular 208 Hz nominal | 672 | 359 | 88.48% |
| 200 Hz stress | 672 | 0 | 0% |
| 208 Hz stress | 672 | 0 | 0% |
| Irregular 208 Hz stress | 672 | 0 | 0% |

The stress result is a severe availability failure, not evidence that another stress threshold should be selected. Startup/aiding profile totals are retained in the machine-readable CSV and JSON. Four seeds are too few for distributional claims.

## Provenance and reproduction

- Source commit: `a9e58286eb320687ae53959052c466a5da18feaa`
- Protocol v3 SHA-256: `1fd3998d99a5d58ea8dd5b6149a38aad0ec90fa56a1d722ccf77280e9dc21cca`
- Trial summary CSV SHA-256: `2ed4fedd6f0b15378ed78dffb37d5f50286ddc2bdc30ab5bf541a402da926067`
- Summary JSON SHA-256: `5a8829dc3d406bf77bce75f3d3d9baafc2b85fdbe8021989564e60940a7dcede`
- Input hashes, compiler and generator/evaluator hashes: [pilot manifest](../benchmarks/manifests/pr3_factor_pilot_dev4_protocol_v3.json)

The shared raw input files were not committed; each is deterministic from the frozen protocol, seed, and factor keys. Their SHA-256 values are retained in the manifest for regenerated-stream verification.

```bash
python3 tools/run_pr3_benchmarks.py \
  --split development --first-seed 4001 --last-seed 4004 \
  --rate-modes uniform_200hz,uniform_208hz,irregular_208hz \
  --stress-modes nominal,stress \
  --profiles baseline,heading_sensor,external_static,truth_static,startup_bias,independent_heading,oracle_heading \
  --output-dir benchmarks/generated/pr3_factor_pilot_v3 \
  --source-commit a9e58286eb320687ae53959052c466a5da18feaa \
  --tree-dirty no
```

The report outputs are [trial rows](../benchmarks/reports/pr3_factor_pilot_dev4_protocol_v3.csv), [aggregate JSON](../benchmarks/reports/pr3_factor_pilot_dev4_protocol_v3.json), and [figure](../benchmarks/figures/pr3_factor_pilot_dev4_protocol_v3.svg). PR2 and PR3 acceptance gates remain open.
