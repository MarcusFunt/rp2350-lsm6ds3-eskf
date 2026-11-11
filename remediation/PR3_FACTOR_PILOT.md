# PR3 development factor pilot

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
