#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CXX="${CXX:-g++}"
mkdir -p /tmp/rp2350_lsm6ds3_checks
"$CXX" -std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic tests/test_eskf15.cpp -o /tmp/rp2350_lsm6ds3_checks/test_eskf15
/tmp/rp2350_lsm6ds3_checks/test_eskf15
"$CXX" -std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic tools/replay_imu_csv.cpp -o /tmp/rp2350_lsm6ds3_checks/replay
python3 tools/create_fixture.py
/tmp/rp2350_lsm6ds3_checks/replay fixtures/stationary_then_yaw.csv > /tmp/rp2350_lsm6ds3_checks/result.csv
python3 - <<'PY'
import csv, math
p='/tmp/rp2350_lsm6ds3_checks/result.csv'
with open(p,newline='') as f:
    records=list(csv.DictReader(f))
assert len(records)>30
last=records[-1]
w=float(last['qw']); z=float(last['qz'])
yaw=2*math.atan2(z,w)
expected=5.0*(math.pi/8)
assert abs(yaw-expected)<0.025,(yaw,expected)
assert int(last['gaps'])==0 and int(last['saturations'])==0
print(f'PASS deterministic CSV fixture: yaw={yaw:.4f} rad vs expected {expected:.4f} rad')
PY
