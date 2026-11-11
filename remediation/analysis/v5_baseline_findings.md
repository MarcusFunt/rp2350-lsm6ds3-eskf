# PR3 v5 baseline archive analysis

Analysis schema version: `1`. The analyzer reads the three frozen compressed v5 trial CSVs and does not regenerate their sensor streams or rerun the benchmark sweeps. No hardware test was run.

## Archive and report checks

| Split | Archive SHA-256 | Streams | Rows | Groups | Published summary comparison |
|---|---|---:|---:|---:|---|
| development | `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755` | 4,800 | 168,000 | 1,680 | PASS: 1,680 groups, 31,248 values, 1,008 ESKF/Mahony pairs |
| held_out | `c6d47a1b72036213abf12e66a1ef45a976ecb1fdc24b1083ef3381ad0ee72b9d` | 4,800 | 168,000 | 1,680 | PASS: 1,680 groups, 31,248 values, 1,008 ESKF/Mahony pairs |
| final_confirmation | `d67d9688f604349e2f7a260a4101c4713370764371b5654585a8b4c3275e3f2f` | 4,800 | 168,000 | 1,680 | PASS: 1,680 groups, 31,248 values, 1,008 ESKF/Mahony pairs |

Each group in the CSV matrix has one row per seed (`n=100`); sensor samples are never treated as independent trials. The distribution quantile convention matches the frozen PR3 summarizer (`sorted[int(q * (n - 1))]`) so p90/p95 and lower median reproduce its reports. `tilt_rms_deg` and `yaw_rms_deg` are already trial-level RMS values in the source CSV.

## Profile-separated headline rollups

These rows average per-trial summaries across the 8 scenarios × 3 rate modes within one split, stress mode, and explicit profile. They are descriptive only; splits and profile classes remain separate. Positive ESKF-minus-Mahony tilt delta means higher ESKF tilt error.

| Split | Stress | Profile | n | Conservative ESKF tilt mean (°) | Mahony tilt mean (°) | Paired ESKF−Mahony (°) | ESKF minimum availability |
|---|---|---|---:|---:|---:|---:|---:|
| development | nominal | Unknown startup, six-axis/no aid | 2,400 | 1.9113 | 2.5555 | -0.6442 | 1.0000 |
| development | stress | Unknown startup, six-axis/no aid | 2,400 | 4.6389 | 2.5552 | 2.0836 | 1.0000 |
| development | nominal | Verified stationary startup + gyro calibration | 2,400 | 0.1960 | 2.3044 | -2.1085 | 1.0000 |
| development | stress | Verified stationary startup + gyro calibration | 2,400 | 0.7535 | 2.3070 | -1.5535 | 1.0000 |
| development | nominal | Synthetic independent heading aid | 2,400 | 0.9991 | 2.3044 | -1.3053 | 1.0000 |
| development | stress | Synthetic independent heading aid | 2,400 | 1.7901 | 2.3070 | -0.5168 | 1.0000 |
| development | nominal | Simulator-oracle heading | 2,400 | 0.1645 | 2.3044 | -2.1399 | 1.0000 |
| development | stress | Simulator-oracle heading | 2,400 | 0.6491 | 2.3070 | -1.6579 | 1.0000 |
| held_out | nominal | Unknown startup, six-axis/no aid | 2,400 | 1.9146 | 2.5554 | -0.6408 | 1.0000 |
| held_out | stress | Unknown startup, six-axis/no aid | 2,400 | 4.6374 | 2.5548 | 2.0826 | 1.0000 |
| held_out | nominal | Verified stationary startup + gyro calibration | 2,400 | 0.1932 | 2.3045 | -2.1112 | 1.0000 |
| held_out | stress | Verified stationary startup + gyro calibration | 2,400 | 0.7497 | 2.3063 | -1.5566 | 1.0000 |
| held_out | nominal | Synthetic independent heading aid | 2,400 | 0.9891 | 2.3045 | -1.3154 | 1.0000 |
| held_out | stress | Synthetic independent heading aid | 2,400 | 1.7631 | 2.3063 | -0.5432 | 1.0000 |
| held_out | nominal | Simulator-oracle heading | 2,400 | 0.1625 | 2.3045 | -2.1419 | 1.0000 |
| held_out | stress | Simulator-oracle heading | 2,400 | 0.6497 | 2.3063 | -1.6566 | 1.0000 |
| final_confirmation | nominal | Unknown startup, six-axis/no aid | 2,400 | 1.9109 | 2.5556 | -0.6446 | 1.0000 |
| final_confirmation | stress | Unknown startup, six-axis/no aid | 2,400 | 4.6315 | 2.5550 | 2.0766 | 1.0000 |
| final_confirmation | nominal | Verified stationary startup + gyro calibration | 2,400 | 0.1931 | 2.3045 | -2.1114 | 1.0000 |
| final_confirmation | stress | Verified stationary startup + gyro calibration | 2,400 | 0.7546 | 2.3067 | -1.5522 | 1.0000 |
| final_confirmation | nominal | Synthetic independent heading aid | 2,400 | 1.0077 | 2.3045 | -1.2967 | 1.0000 |
| final_confirmation | stress | Synthetic independent heading aid | 2,400 | 1.7837 | 2.3067 | -0.5231 | 1.0000 |
| final_confirmation | nominal | Simulator-oracle heading | 2,400 | 0.1618 | 2.3045 | -2.1427 | 1.0000 |
| final_confirmation | stress | Simulator-oracle heading | 2,400 | 0.6499 | 2.3067 | -1.6569 | 1.0000 |

The full group matrix also keeps the other three declared profiles separate: verified startup without calibration, simulator-oracle startup, and unknown startup with synthetic-heading data present but runtime aid disabled.

## Published cross-factor mean comparison

This historical arithmetic mean pools equal-weight per-trial rows across all v5 scenarios, rates, profiles, and splits solely to reproduce the aggregate in `remediation/PR3_STATUS.md`; it is not a profile-level conclusion or an independent validation set.

| Estimator | Stress mode | Trials | Recomputed tilt mean (°) | Published (°) | Match to 4 dp |
|---|---|---:|---:|---:|---|
| eskf_confirmed_only | nominal | 50,400 | 2.1981 | 2.1981 | PASS |
| eskf_confirmed_only | stress | 50,400 | 2.9615 | 2.9615 | PASS |
| eskf_conservative | nominal | 50,400 | 1.2814 | 1.2814 | PASS |
| eskf_conservative | stress | 50,400 | 2.9517 | 2.9517 | PASS |
| eskf_legacy | nominal | 50,400 | 2.5128 | 2.5128 | PASS |
| eskf_legacy | stress | 50,400 | 2.9824 | 2.9824 | PASS |
| gyro_only | nominal | 50,400 | 2.7848 | 2.7848 | PASS |
| gyro_only | stress | 50,400 | 2.8759 | 2.8759 | PASS |
| mahony | nominal | 50,400 | 2.4479 | 2.4479 | PASS |
| mahony | stress | 50,400 | 2.4486 | 2.4486 | PASS |

## Interpretation limits

- No runtime heading aid means yaw is reported as relative heading RMS in the shared zero-yaw startup gauge; it is not absolute north accuracy. Independent heading uses an independent **synthetic** measurement; simulator-oracle heading is explicitly an oracle case. The archived CSV contains only per-trial yaw RMS, so it cannot recover a per-sample drift rate or redo startup alignment.
- Bias values are trial-final norm errors versus simulator truth. Missing baseline bias fields remain blank/N/A rather than zero.
- `tilt_nees_mean` is a 2D tilt-subspace diagnostic. `nis_mean` pools the evaluator's accepted gravity and heading update NIS values where applicable; the CSV does not separate measurement families. Gravity corrections reuse accelerometer information, and temporal samples are correlated, so these columns do not establish ideal independent-sample chi-square coverage or calibrated uncertainty.
- Covariance-valid sample counts describe numerical validity, not uncertainty calibration. Availability, incompleteness, and recovery are reported alongside error to expose easy-sample-only effects.
- All results are synthetic host simulation evidence. Held-out and final-confirmation v5 data are exposed historical evidence, not untouched confirmation for future changes. This analysis does not close the estimator-quality or hardware-validation gates.

## Reproduction

Run from the repository root:

```text
python tools/analyze_pr3_archives.py --output-dir remediation/analysis
```

Verification commands run:

```text
python3 tests/test_pr3_archive_analysis.py
python3 tests/test_pr3_summary.py
python3 tools/analyze_pr3_archives.py --output-dir remediation/analysis
```

The existing summary regression test includes one temporary single-seed smoke fixture; it did not regenerate or replace any frozen v5 stream/archive.

Only these three deterministic derived artifacts are written (replaced on rerun); the source `.csv.gz`, manifests, published summaries, protocol, and figures are opened read-only.
