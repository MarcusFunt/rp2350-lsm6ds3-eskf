#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${BUNDLE_B_BUILD_DIR:-${TMPDIR:-/tmp}/rp2350_bundle_b_checks}"
mkdir -p "$OUT"
CXX="${CXX:-g++}"
FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror)
"$CXX" "${FLAGS[@]}" tests/test_bundle_b.cpp -o "$OUT/test_bundle_b"
"$OUT/test_bundle_b"
"$CXX" "${FLAGS[@]}" tools/benchmark_bundle_b.cpp -o "$OUT/benchmark_bundle_b"
"$OUT/benchmark_bundle_b" --trials 5 --seed 20261110 --output "$OUT/no_bias.csv"
"$OUT/benchmark_bundle_b" --trials 5 --seed 20261110 --startup-bias --output "$OUT/with_bias.csv"
"$OUT/benchmark_bundle_b" --trials 5 --seed 20261110 --startup-bias --output "$OUT/repeated.csv"
cmp "$OUT/with_bias.csv" "$OUT/repeated.csv"
python3 - "$OUT/no_bias.csv" "$OUT/with_bias.csv" <<'PY'
import csv,math,statistics,sys

def collect(p):
    with open(p,newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==90,(p,len(rows)) # 5 trials x 6 scenarios x 3 estimators
    for r in rows:
        assert int(r['expected'])>=2500 and int(r['valid'])>=2500,r
        assert 0<=float(r['tilt_rms_deg'])<90 and math.isfinite(float(r['yaw_rms_deg'])),r
    def metric(scene,model,key='tilt_rms_deg'):
        return statistics.mean(float(r[key]) for r in rows if r['scenario']==scene and r['model']==model)
    return metric

no=collect(sys.argv[1]);with_bias=collect(sys.argv[2]);
assert with_bias('lateral_accel','eskf_conservative')<with_bias('lateral_accel','eskf_legacy')*.5
assert with_bias('lateral_accel','eskf_conservative')<with_bias('lateral_accel','mahony')*.5
assert with_bias('static','eskf_conservative','yaw_rms_deg')<no('static','eskf_conservative','yaw_rms_deg')*.3
assert with_bias('maneuver','eskf_conservative')<1.5
print('PASS matched Monte Carlo regression, truth metrics and deterministic replay')
PY
if [[ "${BUNDLE_B_SANITIZERS:-0}" == "1" ]]; then
  "$CXX" -std=c++17 -UNDEBUG -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=address,undefined tests/test_bundle_b.cpp -o "$OUT/test_bundle_b_san"
  ASAN_OPTIONS=detect_leaks=1 "$OUT/test_bundle_b_san"
  "$CXX" -std=c++17 -UNDEBUG -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=undefined tools/benchmark_bundle_b.cpp -o "$OUT/benchmark_bundle_b_ubsan"
  "$OUT/benchmark_bundle_b_ubsan" --trials 2 --startup-bias --output "$OUT/ubsan.csv"
  echo 'PASS Bundle B sanitizers'
fi
