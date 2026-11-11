#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CXX="${CXX:-g++}"
OUT="${BUNDLE_A_BUILD_DIR:-${TMPDIR:-/tmp}/rp2350_bundle_a_checks}"
mkdir -p "$OUT"
FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic -Werror)
for test in test_eskf15 test_math test_noise; do
  "$CXX" "${FLAGS[@]}" "tests/${test}.cpp" -o "$OUT/$test"
  "$OUT/$test"
done
"$CXX" "${FLAGS[@]}" tests/test_benchmark_tilt_metric.cpp -o "$OUT/test_benchmark_tilt_metric"
"$OUT/test_benchmark_tilt_metric"
"$CXX" "${FLAGS[@]}" tests/test_eskf_reset_oracle.cpp -o "$OUT/test_eskf_reset_oracle"
"$OUT/test_eskf_reset_oracle"
"$CXX" "${FLAGS[@]}" tools/replay_imu_csv.cpp -o "$OUT/replay"
python3 tools/create_fixture.py > /dev/null
"$OUT/replay" fixtures/stationary_then_yaw.csv > "$OUT/output.csv"
python3 - "$OUT/output.csv" <<'PY'
import csv, math, sys
with open(sys.argv[1], newline='') as fd:
    records = list(csv.DictReader(fd))
assert len(records) > 30
last = records[-1]
yaw = 2 * math.atan2(float(last['qz']), float(last['qw']))
expected = 5 * math.pi / 8
assert abs(yaw - expected) < 0.025, (yaw, expected)
assert int(last['gaps']) == 0 and int(last['saturations']) == 0
print(f'PASS CSV replay ({len(records)} rows): yaw={yaw:.6f}, target={expected:.6f}')
PY
if [[ "${BUNDLE_A_SANITIZERS:-0}" == "1" ]]; then
  "$CXX" -std=c++17 -UNDEBUG -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=address,undefined tests/test_eskf15.cpp -o "$OUT/test_eskf15_san"
  ASAN_OPTIONS=detect_leaks=1 "$OUT/test_eskf15_san"
  "$CXX" -std=c++17 -UNDEBUG -O1 -g -Wall -Wextra -Wpedantic -Werror -fno-omit-frame-pointer -fsanitize=undefined tools/replay_imu_csv.cpp -o "$OUT/replay_ubsan"
  "$OUT/replay_ubsan" fixtures/stationary_then_yaw.csv > "$OUT/output_san.csv"
  echo "PASS sanitizers"
fi
