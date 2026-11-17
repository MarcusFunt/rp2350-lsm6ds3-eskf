# B9 reference baseline — frozen

Frozen reference commit: `630e0d8c33ef1ee2bf744a1e84b80b1fafcde973`. This lock records the B9 matched-interval BROAD atlas (all 39 trials) and the six synthetic seed-4001 replay cells. Future changes should compare against these recorded hashes and per-trial/per-cell values; a future rebaseline must get a new version.

## BROAD matched-interval results

Dataset revision: `7e2f8189bb4a3ac91eae32c69b6bc87f08a6e2ad`; VQF `vqf_full_6d_causal_v2.1.2`; metrics use the same valid movement timestamps for VQF, ESKF, and the optical reference. BROAD’s 16 g / 2000 dps limits remain a BROAD-data replay profile. The firmware reference stays at the LSM6DS3 4 g / 245 dps profile.

| Trial | ESKF/VQF matched timestamps | Scored samples with optical reference | VQF tilt RMS (°) | ESKF tilt RMS (°) | Default-range fault |
|---|---:|---:|---:|---:|---|
| `01_undisturbed_slow_rotation_A` | 56699 | 35855 | 0.599 | 14.033 | gyro_range |
| `02_undisturbed_slow_rotation_B` | 51534 | 32280 | 0.429 | 3.827 | gyro_range |
| `03_undisturbed_slow_rotation_C` | 54326 | 34385 | 0.420 | 3.301 | gyro_range |
| `04_undisturbed_slow_rotation_with_breaks_A` | 60569 | 30403 | 0.787 | 12.532 | gyro_range |
| `05_undisturbed_slow_rotation_with_breaks_B` | 57203 | 29132 | 0.353 | 1.274 | gyro_range |
| `06_undisturbed_fast_rotation_A` | 55995 | 34882 | 0.804 | 3.727 | gyro_range |
| `07_undisturbed_fast_rotation_B` | 50924 | 33617 | 1.023 | 4.613 | gyro_range |
| `08_undisturbed_fast_rotation_with_breaks_A` | 55025 | 31417 | 1.763 | 24.460 | gyro_range |
| `09_undisturbed_fast_rotation_with_breaks_B` | 53010 | 30097 | 0.874 | 1.238 | gyro_range |
| `10_undisturbed_slow_translation_A` | 55288 | 34819 | 0.299 | 2.039 | none |
| `11_undisturbed_slow_translation_B` | 51538 | 34726 | 0.420 | 5.159 | none |
| `12_undisturbed_slow_translation_C` | 53826 | 36809 | 0.254 | 1.922 | none |
| `13_undisturbed_slow_translation_with_breaks_A` | 70602 | 41915 | 0.403 | 1.060 | none |
| `14_undisturbed_slow_translation_with_breaks_B` | 51535 | 26641 | 0.413 | 1.075 | none |
| `15_undisturbed_fast_translation_A` | 52391 | 30140 | 0.470 | 0.727 | gyro_range |
| `16_undisturbed_fast_translation_B` | 50124 | 32073 | 0.539 | 5.370 | gyro_range |
| `17_undisturbed_fast_translation_with_breaks_A` | 60149 | 31687 | 0.551 | 1.608 | gyro_range |
| `18_undisturbed_fast_translation_with_breaks_B` | 51480 | 25810 | 0.614 | 1.123 | gyro_range |
| `19_undisturbed_slow_combined_240s` | 85552 | 68951 | 0.392 | 2.157 | gyro_range |
| `20_undisturbed_slow_combined_360s` | 120090 | 102248 | 0.392 | 1.927 | gyro_range |
| `21_undisturbed_fast_combined` | 51386 | 33488 | 1.716 | 13.569 | gyro_range |
| `22_undisturbed_fast_combined_240s` | 85789 | 70240 | 1.004 | 1.924 | gyro_range |
| `23_undisturbed_fast_combined_360s` | 120054 | 102227 | 0.816 | 3.387 | gyro_range |
| `24_disturbed_tapping_A` | 30118 | 20915 | 0.538 | 3.874 | gyro_range |
| `25_disturbed_tapping_B` | 30315 | 21188 | 0.387 | 0.559 | accel_range |
| `26_disturbed_phone_vibration_A` | 53197 | 34233 | 0.561 | 4.348 | gyro_range |
| `27_disturbed_phone_vibration_B` | 51769 | 33531 | 0.370 | 1.228 | none |
| `28_disturbed_stationary_magnet_A` | 51184 | 30790 | 1.206 | 7.090 | gyro_range |
| `29_disturbed_stationary_magnet_B` | 50970 | 33852 | 1.063 | 3.747 | gyro_range |
| `30_disturbed_stationary_magnet_C` | 48712 | 27458 | 1.250 | 8.422 | gyro_range |
| `31_disturbed_stationary_magnet_D` | 48582 | 27045 | 1.141 | 4.165 | gyro_range |
| `32_disturbed_attached_magnet_1cm` | 45436 | 25147 | 0.560 | 0.605 | gyro_range |
| `33_disturbed_attached_magnet_2cm` | 44097 | 25736 | 0.599 | 1.140 | gyro_range |
| `34_disturbed_attached_magnet_3cm` | 44798 | 25716 | 0.646 | 0.818 | gyro_range |
| `35_disturbed_attached_magnet_4cm` | 42964 | 24270 | 0.658 | 1.503 | gyro_range |
| `36_disturbed_attached_magnet_5cm` | 42877 | 24686 | 0.877 | 1.859 | gyro_range |
| `37_disturbed_office_A` | 60096 | 44461 | 0.615 | 8.388 | gyro_range |
| `38_disturbed_office_B` | 77157 | 57936 | 0.550 | 5.236 | gyro_range |
| `39_disturbed_mixed` | 52192 | 32712 | 0.672 | 1.349 | accel_range |
## Synthetic replay cells

All six cells use development seed 4001 and protocol v5 at uniform 208 Hz. These exact input hashes define the frozen replay set.

| Scenario | Mode | Input SHA-256 | ESKF RMS (°) | Mahony RMS (°) |
|---|---|---|---:|---:|
| `maneuver` | nominal | `8228522f6206968fe8abfed2f4bc09e27ee3053eb1e7aff50ebbd152f50a9784` | 3.872 | 2.967 |
| `maneuver` | stress | `2e526984b3b48c1085c0c7a5f00fd9a5e949fc4a902ee31a99b5ce168250094b` | 3.199 | 2.973 |
| `timing_jitter` | nominal | `5b66905af1eb07e659acf9a2da0dd7113ff26ba10665793cf211cb0a6b7c4f53` | 3.725 | 2.962 |
| `timing_jitter` | stress | `359072afbd3d2a0fbe2e8e0ab7a77cd2d5a6d583beb02f25884d5f4a16a475cf` | 3.131 | 2.972 |
| `compound_motion` | nominal | `7e01cff8f26c3da6680340860d9f443e2603cd6eb088dadb6f98f76715cb5dd5` | 5.226 | 2.032 |
| `compound_motion` | stress | `bf06d6ebb58f6e7db38f381dc34f47b107076ea78dc9e21882f778ce0205341c` | 6.871 | 2.029 |

## Frozen source artifacts

| Artifact | SHA-256 |
|---|---|
| `remediation/analysis/b9_broad_failure_atlas/B9_BROAD_FAILURE_ATLAS.md` | `54ca6a19c04828729872b424512aa9968c0e0a5993f9b7af75f081fbbe051126` |
| `remediation/analysis/b9_broad_failure_atlas/b9_broad_results.json` | `746930b472a2af64802cbce09642411c1509c2de40068f6a8265070038f10e32` |
| `remediation/analysis/b9_broad_failure_atlas/b9_broad_summary.csv` | `646554dd3a5592153f6c76aa8d4236846be907ed5a67d117cc0c0a02b0c2c420` |
| `remediation/analysis/b9_broad_failure_atlas/evidence_manifest.json` | `a87e995deb9ae04bdbc7fa63aa0fda04aae4b588971b8de1a1cdf69462cffeee` |
| `remediation/analysis/pr3_synthetic_weaknesses_b9/PR3_SYNTHETIC_WEAKNESSES_B9.md` | `9fdd689030f9bb9db40e7ac98bdec241f6d2a2dd70103bd0da879f51143c1b2a` |
| `remediation/analysis/pr3_synthetic_weaknesses_b9/pr3_synthetic_weakness_results.json` | `702d604c24fb70f52eda1e37327ad8c27674ba89298a90fe1c41a97a55448866` |
| `remediation/analysis/pr3_synthetic_weaknesses_b9/pr3_synthetic_weakness_summary.csv` | `414bdb60b1d820aabb70a2be21c452401adfb33e327484195ddf2c00495fe990` |
| `remediation/analysis/pr3_synthetic_weaknesses_b9/traces/pr3_synthetic_weaknesses_seed4001.csv.gz` | `26cb5c641644ef8a69ecdea234fb70f028edb641b93de26510ba887cd4969aba` |
| `remediation/analysis/pr3_synthetic_weaknesses_b9/evidence_manifest.json` | `c488d56b4edc51476e995273c7deba0ff08e56f2b252040a89de767fc465832e` |

B9 reports, CSVs, traces, and figures remain unchanged. This directory is the reference lock and provenance record.
