# PR 1 evidence index

Canonical final suite logs are pinned to source commit `c43c52671fa350cf8d095e93fa3b012331cd62f5`:

| Check | Result log |
|---|---|
| Baseline Bundle A/B/C host checks at the pinned base | `bundle_a.log`, `bundle_b.log`, `bundle_c.log` |
| Final Bundle A host checks, evaluator oracle, CSV replay | `bundle_a_final_c43.log` |
| Final Bundle B host checks, protocol-v1 rejection, deterministic benchmark | `bundle_b_final_c43.log` |
| Final Bundle C host checks and binary replay | `bundle_c_final_c43.log` |
| Clean-clone Bundle A/B regression reproduction at PR 1 commit `9bb16a0` | `clean_clone_pr1_final.log` |
| Bundle A sanitizers | `bundle_a_sanitizers_final_c43.log` |
| Bundle B sanitizers | `bundle_b_sanitizers_final_c43.log` |
| Bundle C sanitizers | `bundle_c_sanitizers_final_c43.log` |
| Protocol-v2 baseline generation and validation | `pr1_baseline_generation_final.log` |
| Historical default core replay | `pr1_historical_replay_final.log` |
| Final manifest validation and artifact hashes | `pr1_manifest_finalization.log` |
| Tilt evaluator test-first failure | `tilt_metric_red.log` |
| Tilt evaluator corrected pass | `tilt_metric_green.log` |
| Protocol guard test-first failure | `summarizer_protocol_red.log` |
| Protocol guard corrected pass | `summarizer_protocol_green.log` |

One initial parallel Bundle A sanitizer attempt hit a temporary `/tmp` executable collision (`Text file busy`), captured in `bundle_a_sanitizers.log`. The affected suites were rerun serially and passed in the canonical logs above. That collision was a harness concurrency issue, not a reported source failure.

`pr1_baseline_protocol_v2.json` pins generated artifact hashes and every raw input stream hash. The historical replay summary is `benchmarks/reports/pr1_historical_default_protocol_v2.csv`; the run command is `bash ./tools/run_pr1_legacy_compare.sh` and the old core header is extracted from commit `e90c80e` at build time.
