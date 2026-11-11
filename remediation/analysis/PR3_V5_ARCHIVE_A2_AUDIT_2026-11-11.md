# PR3 v5 archive audit — Prompt 02 (A2)

Audit date: 2026-11-11. Repository: `MarcusFunt/rp2350-lsm6ds3-eskf`. The audit worktree is `codex/verify-pr3-v5-archives-a2-20261111`, based on accepted A1 commit `985473f99c2a815f5e050c90e63b0f173b4a7d7a`. A fresh fetch verified `origin/main` still at `0d31c0e7c1f698122bf34d0e107334af225095e6`.

Only the new read-only audit script and this report are in scope. No compressed archive, generated input, protocol, manifest, report, or figure was changed. The full generated run directories were read from the existing registered PR3 worktree `C:\Users\marcu\rp2350-eskf-pr3` (branch `test/eskf-statistics-benchmarks`, HEAD `1c417f5ec5c74ed0313455f2fdea4130f4fe3ff5`). Each split already contained its 4,800 input binaries and 210 figures; no sweep or simulator was rerun.

## Immutable evidence inventory

| Split | Seeds | Compressed archive bytes | Archive SHA-256 | Uncompressed trial CSV SHA-256 | Packaged summary SHA-256 | Packaged manifest SHA-256 |
|---|---:|---:|---|---|---|---|
| Development | 4001–4100 | 4,847,522 | `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755` | `43fa2cafd0887bba51cb29c41d2fde2add8f66d29a9b95dbf716ee8f2705f793` | `b9baf199017ddae5e6be50740e1f021cdcdce7ff2cea447184cca3be8c6504dc` | `394278986dd83fad6f43799194d0ec4f3f407381eb5b761aa1ac5a22ffd2d22c` |
| Held-out | 9001–9100 | 4,851,436 | `c6d47a1b72036213abf12e66a1ef45a976ecb1fdc24b1083ef3381ad0ee72b9d` | `96cebf6ecf839ec0ab68d8efee9c26088180a2aafa79850ed307a61757d2eae3` | `b6320d093ca124741559602e6068213c281ff0e7c411110343e5986d2411c421` | `7a7279bf8734e7db484336fb40a245915c8e4196dd31c2295d3b843302baa520` |
| Final confirmation | 10001–10100 | 4,856,146 | `d67d9688f604349e2f7a260a4101c4713370764371b5654585a8b4c3275e3f2f` | `2399f460e89ff17a3132c9ac15df3f9e7998ddd6508a2481e0ff2043cbb6a1ff` | `e2cc1f54307358edff9f15f9893b26d57e3eb63e0fb685470275946e0dd8ad58` | `2b7c0735279bb3e16421f1fb3ca82d3885688e4ed2f452d28aec2ed9016e8f81` |

The compressed archive hashes match their packaged manifests. Decompressing each archive produced the manifest's `summary_csv_sha256`, byte-for-byte equal to the existing generated trial CSV. The packaged summary and manifest hashes above are the checked-in files; the verifier also reported separate generated-run summary/manifest hashes. Those generated metadata files intentionally differ because packaging rewrites summary figure/source paths and adds packaged archive metadata. The trial CSV content hash remains identical.

## Verification matrix

| Check | Development | Held-out | Final confirmation |
|---|---|---|---|
| Existing `verify_pr3_full_factor_evidence.py` | PASS | PASS | PASS |
| Archive SHA matches checked-in manifest | PASS | PASS | PASS |
| Decompressed archive matches manifest and generated CSV SHA | PASS | PASS | PASS |
| Protocol/source identity and clean-run provenance | PASS | PASS | PASS |
| Input-stream binaries rehashed against manifest | 4,800 / 4,800 PASS | 4,800 / 4,800 PASS | 4,800 / 4,800 PASS |
| Archived trial rows | 168,000 PASS | 168,000 PASS | 168,000 PASS |
| Factor groups / trials per group | 1,680 / 100 PASS | 1,680 / 100 PASS | 1,680 / 100 PASS |
| Declared profile combinations | 7 PASS | 7 PASS | 7 PASS |
| Incomplete rows | 0 PASS | 0 PASS | 0 PASS |
| Covariance checks, each ESKF policy | 96,622,400 / 96,622,400 PASS | 96,622,400 / 96,622,400 PASS | 96,622,400 / 96,622,400 PASS |
| Figure hashes | 210 / 210 PASS | 210 / 210 PASS | 210 / 210 PASS |
| Paired intervals | 3,360 PASS | 3,360 PASS | 3,360 PASS |
| Plan-published compressed archive SHA | **FAIL: malformed plan value** | PASS | PASS |

The full verifier also confirms 8 scenarios, 3 rate modes (`uniform_200hz`, `uniform_208hz`, `irregular_208hz`), 2 stress modes, 5 estimators, 100 seeds, and 35 estimator/profile rows per shared input stream. The 4,800 unique stream keys are `(scenario, rate_mode, stress_mode, seed)`; each CSV row's `input_sha256` agrees with its manifest entry. Across all splits this is 14,400 shared streams and 504,000 estimator rows. Covariance totals are 869,601,600 checks across the three ESKF policies and three splits.

## Hash discrepancy and provenance

The plan's development archive digest is only 61 hexadecimal characters: `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14ee755`. It is missing `aee` before the final `e755`, so it cannot be a SHA-256 value. The actual archive, its checked-in manifest, and the development row in `remediation/PR3_STATUS.md` all agree on the 64-character value `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755`. Held-out and final-confirmation hashes in the plan match their actual archives. The typo does not break provenance because the full archive-to-manifest-to-uncompressed-CSV chain verifies, and the independent verifier rehashed all input binaries and figures.

All three manifests identify frozen source commit `02c61fe7c4b93d591b042c69b08cfe20a6277722`, marked clean, and protocol v5 SHA-256 `1318acff98ac2641383ef6a568986e912020a6d4c6debeb145a9abf0f8fa4800`. The source commit exists and is an ancestor of `origin/main`. Generator, evaluator, scenario-header generator, summarizer, and runner hashes match Git blobs at that commit. The verifier and packager hashes match their recorded manifest values. The protocol Git blob and LF-normalized working copy match the recorded protocol SHA; the raw Windows checkout hash differs because its text line endings are CRLF.

## Independent aggregate cross-check

`verify_pr3_v5_archive_package_a2.py` streams the compressed final-confirmation CSV and recomputes the plan's arithmetic means from 2,400 rows per estimator/profile (8 scenarios × 3 rates × 100 seeds). All 24 published values—three metrics for each of eight profiles—match when rounded to four decimals. Examples:

| Final-confirmation profile | Metric | Independently recomputed | Published |
|---|---|---:|---:|
| Unknown startup, no calibration/aid, nominal | Conservative tilt / Mahony tilt / ESKF yaw | 1.910923° / 2.555568° / 10.501859° | 1.9109° / 2.5556° / 10.5019° |
| Verified stationary startup + gyro-bias calibration, nominal | Conservative tilt / Mahony tilt / ESKF yaw | 0.193110° / 2.304463° / 0.945945° | 0.1931° / 2.3045° / 0.9459° |
| Calibrated startup + independent synthetic heading, stress | Conservative tilt / Mahony tilt / ESKF yaw | 1.783680° / 2.306743° / 1.742815° | 1.7837° / 2.3067° / 1.7428° |

These remain synthetic simulation scores, not hardware or motion-capture results.

## Bundle B stress vs PR3 stress

The labels are similar but the models and data are separate. Bundle B uses `sensor_profile` in `bundle_b_*.csv`, runs at 200 Hz for 16 seconds, retains its nominal noise and bias-walk equations, and adds synthetic axis scale/cross-axis errors, a 6 °C temperature ramp, clipping, and quantization. PR3 uses `stress_mode` in protocol-v5 archives across 200 Hz, 208 Hz, and irregular 208 Hz; its stress transform multiplies accelerometer and gyro white noise by 3, bias random walk by 2, measurement disturbance by 2, and timestamp jitter by 2 while leaving truth motion unchanged. `BENCHMARK_B.md` and `remediation/PR3_STATUS.md` retain separate source files, schemas, and reporting. No report or aggregate was found that pools Bundle B stress rows with PR3 stress rows.

## Commands and artifact preservation

Executed from the A2 worktree, with no simulation or sweep rerun:

```text
python tools/verify_pr3_full_factor_evidence.py C:\Users\marcu\rp2350-eskf-pr3\benchmarks\generated\pr3_protocol_v5_dev100_all_factors_postfix
python tools/verify_pr3_full_factor_evidence.py C:\Users\marcu\rp2350-eskf-pr3\benchmarks\generated\pr3_protocol_v5_heldout100_all_factors_postfix
python tools/verify_pr3_full_factor_evidence.py C:\Users\marcu\rp2350-eskf-pr3\benchmarks\generated\pr3_protocol_v5_final100_all_factors_postfix
python remediation/analysis/verify_pr3_v5_archive_package_a2.py --generated-root C:\Users\marcu\rp2350-eskf-pr3\benchmarks\generated --plan C:\Users\marcu\Downloads\ESKF_Improvement_Plan.md
```

All four commands passed their evidence assertions. The independent script reports the plan's malformed development hash as a discrepancy while correctly validating the archive against its manifest. The A2 changes are only this audit and its read-only checker; original compressed archives, generated runs, manifests, protocol, summaries, and figures remain untouched. A2 does not close the documented estimator-accuracy or hardware-validation gates.

**Next:** Prompt 03. No later step was started.

## Follow-up recheck — 2026-11-11

The read-only archive checker was rerun after the initial audit. The development archive SHA-256 recomputed from `benchmarks/reports/pr3_protocol_v5_dev100_all_factors_postfix_trials.csv.gz` is `ad73e542d57d43fc4a707a82b9011dfc5ece30a44313574b49dbea14eeaee755`; it matches the checked-in manifest and `remediation/PR3_STATUS.md`. This recheck caught and corrected a transposition in the development digest printed in the original A2 report. The plan still contains the malformed 61-character value above. Physical hardware validation was not run.
