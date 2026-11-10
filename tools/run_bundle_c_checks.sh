#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CXX="${CXX:-g++}"
OUT="${TMPDIR:-/tmp}/rp2350_bundle_c_checks"
mkdir -p "$OUT"
FLAGS=(-std=c++17 -UNDEBUG -O2 -Wall -Wextra -Wpedantic)
if [[ "${BUNDLE_C_SANITIZERS:-0}" == 1 ]]; then FLAGS+=(-fsanitize=address,undefined -fno-omit-frame-pointer -O1 -g); fi
"$CXX" "${FLAGS[@]}" tests/test_bundle_c.cpp -o "$OUT/test_bundle_c"
"$OUT/test_bundle_c"
"$CXX" "${FLAGS[@]}" tools/binary_log_tool.cpp -o "$OUT/binary_log_tool"
"$OUT/binary_log_tool" generate "$OUT/fixture.bin"
"$OUT/binary_log_tool" replay "$OUT/fixture.bin" 1234 > "$OUT/replayed.csv"
python3 - "$OUT/replayed.csv" "$OUT/fixture.bin" "$OUT/binary_log_tool" <<'PY'
import csv, subprocess, sys
from pathlib import Path
rows=list(csv.DictReader(open(sys.argv[1],newline='')))
assert len(rows)==1200,len(rows)
assert sum(int(r['valid']) for r in rows)>1000
f=Path(sys.argv[2]); exe=sys.argv[3]
assert subprocess.run([exe,'replay',str(f),'999'],capture_output=True).returncode==5
b=bytearray(f.read_bytes());b[32+64*10+33]^=0x10
p=f.with_suffix('.corrupted.bin');p.write_bytes(b)
assert subprocess.run([exe,'replay',str(p),'1234'],capture_output=True).returncode==7
p=f.with_suffix('.truncated.bin');p.write_bytes(f.read_bytes()[:-3])
assert subprocess.run([exe,'replay',str(p),'1234'],capture_output=True).returncode==6
print('PASS 1200-record replay, mismatch / CRC / truncation rejection')
PY
